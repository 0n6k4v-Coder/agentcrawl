"""
AgentCrawl — Webhook Dispatcher
===================================

Delivers webhook notifications for queue job events to
external HTTP endpoints.

Features:
    - HMAC-SHA256 signed payloads
    - Async HTTP delivery via httpx
    - Retry with exponential backoff
    - Event type filtering
    - Delivery logging and tracking
    - Dead letter for failed deliveries
    - Configurable timeout and concurrency

Events:
    job.queued      — Job added to queue
    job.started     — Job processing began
    job.progress    — Job progress update
    job.completed   — Job finished successfully
    job.failed      — Job failed permanently
    job.cancelled   — Job was cancelled

Usage:
    from server.queue.webhook import (
        WebhookDispatcher,
        WebhookConfig,
    )

    config = WebhookConfig(
        url="https://example.com/webhook",
        secret="your-webhook-secret",
        events=["job.completed", "job.failed"],
    )

    dispatcher = WebhookDispatcher(configs=[config])
    await dispatcher.start()

    # Dispatch event
    await dispatcher.dispatch(
        event_type="job.completed",
        payload={"job_id": "job_123", "pages": 10},
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agentcrawl.server.queue.webhook")


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

@dataclass
class WebhookConfig:
    """
    Webhook endpoint configuration.

    Attributes:
        url: Target URL for webhook delivery.
        secret: Shared secret for HMAC signing.
        events: Event types to deliver (empty = all).
        enabled: Whether this webhook is active.
        timeout: Delivery timeout in seconds.
        max_retries: Maximum delivery retries.
        retry_delay: Base retry delay in seconds.
        headers: Additional HTTP headers.
    """
    url: str
    secret: str = ""
    events: list[str] = field(default_factory=list)
    enabled: bool = True
    timeout: float = 10.0
    max_retries: int = 3
    retry_delay: float = 1.0
    headers: dict[str, str] = field(default_factory=dict)

    def should_receive(self, event_type: str) -> bool:
        """Check if this webhook should receive an event type."""
        if not self.enabled:
            return False
        if not self.events:
            return True  # Empty = all events
        return event_type in self.events


# ══════════════════════════════════════════════════════════════
# Event Models
# ══════════════════════════════════════════════════════════════

@dataclass
class WebhookEvent:
    """
    A webhook event to be delivered.

    Attributes:
        event_id: Unique event identifier.
        event_type: Event type (e.g., "job.completed").
        timestamp: Event timestamp (ISO 8601).
        payload: Event payload data.
        source: Event source identifier.
    """
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: str = ""
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "agentcrawl"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "source": self.source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class DeliveryResult:
    """
    Result of a webhook delivery attempt.

    Attributes:
        event_id: Event identifier.
        url: Target URL.
        success: Whether delivery succeeded.
        status_code: HTTP status code.
        attempts: Number of attempts made.
        duration_ms: Total delivery time.
        error: Error message (if failed).
    """
    event_id: str
    url: str
    success: bool = False
    status_code: int = 0
    attempts: int = 0
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "url": self.url,
            "success": self.success,
            "status_code": self.status_code,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
        }


# ══════════════════════════════════════════════════════════════
# Dispatcher
# ══════════════════════════════════════════════════════════════

class WebhookDispatcher:
    """
    Dispatches webhook events to configured endpoints.

    Args:
        configs: List of webhook configurations.
        max_concurrent: Maximum concurrent deliveries.
        dead_letter_max: Maximum dead letter entries.

    Example:
        >>> dispatcher = WebhookDispatcher(configs=[config])
        >>> await dispatcher.start()
        >>> await dispatcher.dispatch("job.completed", {"job_id": "j1"})
        >>> await dispatcher.stop()
    """

    def __init__(
        self,
        configs: list[WebhookConfig] | None = None,
        max_concurrent: int = 5,
        dead_letter_max: int = 100,
    ):
        self._configs = configs or []
        self._max_concurrent = max_concurrent
        self._dead_letter_max = dead_letter_max

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._started = False

        # Delivery tracking
        self._total_dispatched: int = 0
        self._total_delivered: int = 0
        self._total_failed: int = 0

        # Dead letter queue
        self._dead_letter: list[dict[str, Any]] = []

        # Delivery log (recent)
        self._delivery_log: list[DeliveryResult] = []
        self._log_max = 200

    # ──────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dispatcher."""
        if self._started:
            return
        self._started = True
        logger.info(
            "Webhook dispatcher started (%d endpoints)",
            len(self._configs),
        )

    async def stop(self) -> None:
        """Stop the dispatcher."""
        self._started = False
        logger.info("Webhook dispatcher stopped")

    # ──────────────────────────────────────────────────────────
    # Configuration
    # ──────────────────────────────────────────────────────────

    def add_config(self, config: WebhookConfig) -> None:
        """Add a webhook endpoint."""
        self._configs.append(config)
        logger.info("Webhook endpoint added: %s", config.url)

    def remove_config(self, url: str) -> bool:
        """Remove a webhook endpoint by URL."""
        before = len(self._configs)
        self._configs = [c for c in self._configs if c.url != url]
        return len(self._configs) < before

    def list_configs(self) -> list[dict[str, Any]]:
        """List all webhook configurations."""
        return [
            {
                "url": c.url,
                "events": c.events,
                "enabled": c.enabled,
                "max_retries": c.max_retries,
            }
            for c in self._configs
        ]

    # ──────────────────────────────────────────────────────────
    # Dispatch
    # ──────────────────────────────────────────────────────────

    async def dispatch(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "agentcrawl",
    ) -> list[DeliveryResult]:
        """
        Dispatch an event to all matching webhook endpoints.

        Args:
            event_type: Event type (e.g., "job.completed").
            payload: Event payload.
            source: Event source.

        Returns:
            List of delivery results.
        """
        if not self._started:
            logger.warning("Dispatcher not started, skipping dispatch")
            return []

        event = WebhookEvent(
            event_type=event_type,
            payload=payload,
            source=source,
        )

        self._total_dispatched += 1

        # Find matching endpoints
        targets = [c for c in self._configs if c.should_receive(event_type)]

        if not targets:
            logger.debug("No webhook targets for event: %s", event_type)
            return []

        # Deliver concurrently
        tasks = [
            self._deliver_with_semaphore(config, event)
            for config in targets
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        delivery_results: list[DeliveryResult] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Webhook delivery exception: %s", result)
                delivery_results.append(DeliveryResult(
                    event_id=event.event_id,
                    url="unknown",
                    error=str(result),
                ))
            else:
                delivery_results.append(result)

        # Track stats
        for dr in delivery_results:
            if dr.success:
                self._total_delivered += 1
            else:
                self._total_failed += 1

        # Log
        self._delivery_log.extend(delivery_results)
        if len(self._delivery_log) > self._log_max:
            self._delivery_log = self._delivery_log[-self._log_max:]

        return delivery_results

    async def dispatch_job_event(
        self,
        job_id: str,
        status: str,
        data: dict[str, Any] | None = None,
    ) -> list[DeliveryResult]:
        """
        Dispatch a job lifecycle event.

        Convenience method that maps job status to event type.

        Args:
            job_id: Job identifier.
            status: Job status (queued, started, completed, failed, cancelled).
            data: Additional event data.

        Returns:
            Delivery results.
        """
        event_map = {
            "queued": "job.queued",
            "started": "job.started",
            "running": "job.progress",
            "processing": "job.progress",
            "completed": "job.completed",
            "failed": "job.failed",
            "cancelled": "job.cancelled",
        }

        event_type = event_map.get(status, f"job.{status}")

        payload = {
            "job_id": job_id,
            "status": status,
            **(data or {}),
        }

        return await self.dispatch(event_type, payload)

    # ──────────────────────────────────────────────────────────
    # Delivery
    # ──────────────────────────────────────────────────────────

    async def _deliver_with_semaphore(
        self,
        config: WebhookConfig,
        event: WebhookEvent,
    ) -> DeliveryResult:
        """Deliver with concurrency limiting."""
        async with self._semaphore:
            return await self._deliver(config, event)

    async def _deliver(
        self,
        config: WebhookConfig,
        event: WebhookEvent,
    ) -> DeliveryResult:
        """
        Deliver an event to a single endpoint with retries.

        Args:
            config: Webhook configuration.
            event: Event to deliver.

        Returns:
            DeliveryResult.
        """
        import httpx

        start = time.perf_counter()
        body = event.to_json()

        # Build headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentCrawl-Webhook/1.0",
            "X-Webhook-Event": event.event_type,
            "X-Webhook-ID": event.event_id,
            **config.headers,
        }

        # Sign payload
        if config.secret:
            signature = self._sign(body.encode("utf-8"), config.secret)
            headers["X-Webhook-Signature"] = signature

        # Retry loop
        last_error = ""
        last_status = 0

        for attempt in range(1, config.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=config.timeout) as client:
                    response = await client.post(
                        config.url,
                        content=body,
                        headers=headers,
                    )

                    last_status = response.status_code

                    if 200 <= response.status_code < 300:
                        elapsed = (time.perf_counter() - start) * 1000

                        logger.debug(
                            "Webhook delivered: %s → %s (%d, %.0fms, attempt=%d)",
                            event.event_type,
                            config.url,
                            response.status_code,
                            elapsed,
                            attempt,
                        )

                        return DeliveryResult(
                            event_id=event.event_id,
                            url=config.url,
                            success=True,
                            status_code=response.status_code,
                            attempts=attempt,
                            duration_ms=elapsed,
                        )

                    # Server error — retry
                    if response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}"
                        logger.warning(
                            "Webhook delivery failed (attempt %d/%d): %s → %s (%d)",
                            attempt,
                            config.max_retries,
                            event.event_type,
                            config.url,
                            response.status_code,
                        )
                    else:
                        # Client error — don't retry
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        break

            except httpx.TimeoutException:
                last_error = f"Timeout after {config.timeout}s"
                logger.warning(
                    "Webhook timeout (attempt %d/%d): %s → %s",
                    attempt,
                    config.max_retries,
                    event.event_type,
                    config.url,
                )

            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                logger.warning(
                    "Webhook connection error (attempt %d/%d): %s → %s",
                    attempt,
                    config.max_retries,
                    event.event_type,
                    config.url,
                )

            except Exception as e:
                last_error = str(e)
                logger.error(
                    "Webhook delivery error: %s → %s: %s",
                    event.event_type,
                    config.url,
                    e,
                )
                break

            # Exponential backoff
            if attempt < config.max_retries:
                delay = config.retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        # All retries exhausted
        elapsed = (time.perf_counter() - start) * 1000

        result = DeliveryResult(
            event_id=event.event_id,
            url=config.url,
            success=False,
            status_code=last_status,
            attempts=config.max_retries,
            duration_ms=elapsed,
            error=last_error,
        )

        # Dead letter
        self._add_dead_letter(event, config, result)

        logger.error(
            "Webhook delivery failed permanently: %s → %s (%s)",
            event.event_type,
            config.url,
            last_error,
        )

        return result

    # ──────────────────────────────────────────────────────────
    # Signing
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _sign(payload: bytes, secret: str) -> str:
        """
        Generate HMAC-SHA256 signature.

        Args:
            payload: Request body bytes.
            secret: Shared secret.

        Returns:
            Signature string (sha256=<hex>).
        """
        digest = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={digest}"

    @staticmethod
    def verify_signature(
        payload: bytes,
        signature: str,
        secret: str,
    ) -> bool:
        """
        Verify a webhook signature.

        Args:
            payload: Request body bytes.
            signature: Signature from header.
            secret: Shared secret.

        Returns:
            True if valid.
        """
        if signature.startswith("sha256="):
            signature = signature[7:]

        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # ──────────────────────────────────────────────────────────
    # Dead Letter
    # ──────────────────────────────────────────────────────────

    def _add_dead_letter(
        self,
        event: WebhookEvent,
        config: WebhookConfig,
        result: DeliveryResult,
    ) -> None:
        """Add a failed delivery to the dead letter queue."""
        entry = {
            "event": event.to_dict(),
            "url": config.url,
            "result": result.to_dict(),
            "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._dead_letter.append(entry)

        if len(self._dead_letter) > self._dead_letter_max:
            self._dead_letter = self._dead_letter[-self._dead_letter_max:]

    async def get_dead_letter(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get dead letter entries."""
        return self._dead_letter[-limit:]

    async def retry_dead_letter(self, index: int) -> DeliveryResult | None:
        """Retry a dead letter entry."""
        if index < 0 or index >= len(self._dead_letter):
            return None

        entry = self._dead_letter[index]
        event_data = entry["event"]

        event = WebhookEvent(
            event_id=event_data.get("event_id", ""),
            event_type=event_data.get("event_type", ""),
            timestamp=event_data.get("timestamp", ""),
            payload=event_data.get("payload", {}),
            source=event_data.get("source", "agentcrawl"),
        )

        # Find matching config
        url = entry.get("url", "")
        config = next((c for c in self._configs if c.url == url), None)

        if config is None:
            return DeliveryResult(
                event_id=event.event_id,
                url=url,
                error="Webhook endpoint no longer configured",
            )

        result = await self._deliver(config, event)

        if result.success:
            self._dead_letter.pop(index)

        return result

    # ──────────────────────────────────────────────────────────
    # Stats
    # ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get dispatcher statistics."""
        return {
            "endpoints": len(self._configs),
            "active_endpoints": sum(1 for c in self._configs if c.enabled),
            "total_dispatched": self._total_dispatched,
            "total_delivered": self._total_delivered,
            "total_failed": self._total_failed,
            "delivery_rate": round(
                self._total_delivered / max(self._total_dispatched, 1), 4
            ),
            "dead_letter_count": len(self._dead_letter),
            "recent_deliveries": len(self._delivery_log),
        }

    def get_recent_deliveries(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent delivery results."""
        return [dr.to_dict() for dr in self._delivery_log[-limit:]]

    def __repr__(self) -> str:
        return (
            f"WebhookDispatcher("
            f"endpoints={len(self._configs)}, "
            f"dispatched={self._total_dispatched})"
        )
