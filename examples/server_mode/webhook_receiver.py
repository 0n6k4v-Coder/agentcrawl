"""
AgentCrawl — Webhook Receiver Example
=========================================

A standalone FastAPI server that receives webhook callbacks from
AgentCrawl. Demonstrates how to handle scrape/crawl completion
events, verify signatures, and process results.

Prerequisites:
    pip install fastapi uvicorn httpx

Usage:
    # Start the webhook receiver
    python examples/server_mode/webhook_receiver.py

    # Or with uvicorn
    uvicorn examples.server_mode.webhook_receiver:app --port 9000

    # Configure AgentCrawl to send webhooks:
    # (In your crawl/scrape code, POST results to this receiver)

Endpoints:
    POST /webhook/scrape     — Receive scrape completion
    POST /webhook/crawl      — Receive crawl progress/completion
    POST /webhook/error      — Receive error notifications
    GET  /webhook/events     — List received events
    GET  /webhook/events/{id} — Get specific event
    GET  /health             — Health check
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

WEBHOOK_SECRET = "your-webhook-secret"  # Shared secret for HMAC verification
MAX_EVENTS_STORED = 1000
PORT = 9000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook_receiver")


# ══════════════════════════════════════════════════════════════
# Data Models
# ══════════════════════════════════════════════════════════════

@dataclass
class WebhookEvent:
    """A received webhook event."""
    id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]
    signature_valid: bool = False
    processed: bool = False
    processing_result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "signature_valid": self.signature_valid,
            "processed": self.processed,
            "processing_result": self.processing_result,
        }


class ScrapeWebhook(BaseModel):
    """Scrape completion webhook payload."""
    url: str
    success: bool
    status_code: int = 0
    word_count: int = 0
    token_count: int = 0
    response_time_ms: float = 0.0
    cached: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


class CrawlProgressWebhook(BaseModel):
    """Crawl progress webhook payload."""
    job_id: str
    status: str  # "running", "completed", "failed", "cancelled"
    pages_crawled: int = 0
    pages_failed: int = 0
    total_pages: int = 0
    progress: float = 0.0
    elapsed_ms: float = 0.0
    current_url: str = ""


class CrawlCompleteWebhook(BaseModel):
    """Crawl completion webhook payload."""
    job_id: str
    status: str
    start_url: str
    total_pages: int = 0
    successful_pages: int = 0
    failed_pages: int = 0
    total_words: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    strategy: str = ""


class ErrorWebhook(BaseModel):
    """Error notification webhook payload."""
    url: str
    error: str
    error_type: str = ""
    status_code: int = 0
    request_id: str = ""
    timestamp: str = ""


# ══════════════════════════════════════════════════════════════
# Event Store
# ══════════════════════════════════════════════════════════════

class EventStore:
    """In-memory event store."""

    def __init__(self, max_events: int = MAX_EVENTS_STORED):
        self._events: list[WebhookEvent] = []
        self._max_events = max_events
        self._stats: dict[str, int] = {
            "total_received": 0,
            "scrape_events": 0,
            "crawl_events": 0,
            "error_events": 0,
            "invalid_signatures": 0,
        }

    def add(self, event: WebhookEvent) -> None:
        """Add an event to the store."""
        self._events.append(event)
        self._stats["total_received"] += 1

        if event.event_type.startswith("scrape"):
            self._stats["scrape_events"] += 1
        elif event.event_type.startswith("crawl"):
            self._stats["crawl_events"] += 1
        elif event.event_type.startswith("error"):
            self._stats["error_events"] += 1

        if not event.signature_valid:
            self._stats["invalid_signatures"] += 1

        # Trim old events
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get(self, event_id: str) -> WebhookEvent | None:
        """Get an event by ID."""
        for event in self._events:
            if event.id == event_id:
                return event
        return None

    def list_events(
        self,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[WebhookEvent]:
        """List events, optionally filtered by type."""
        events = self._events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)


# ══════════════════════════════════════════════════════════════
# Signature Verification
# ══════════════════════════════════════════════════════════════

def verify_signature(
    payload: bytes,
    signature: str,
    secret: str = WEBHOOK_SECRET,
) -> bool:
    """
    Verify HMAC-SHA256 webhook signature.

    The signature is expected in the format: sha256=<hex_digest>

    Args:
        payload: Raw request body bytes.
        signature: Signature from X-Webhook-Signature header.
        secret: Shared secret.

    Returns:
        True if signature is valid.
    """
    if not signature:
        return False

    # Strip prefix
    if signature.startswith("sha256="):
        signature = signature[7:]

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def compute_signature(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """
    Compute HMAC-SHA256 signature for a payload.

    Use this when sending webhooks from AgentCrawl.

    Args:
        payload: Request body bytes.
        secret: Shared secret.

    Returns:
        Signature string (sha256=<hex_digest>).
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


# ══════════════════════════════════════════════════════════════
# FastAPI App
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title="AgentCrawl Webhook Receiver",
    description="Receives and processes webhook callbacks from AgentCrawl",
    version="1.0.0",
)

store = EventStore()


# ──────────────────────────────────────────────────────────────
# Middleware
# ──────────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Any:
    """Log all incoming requests."""
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000

    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )

    return response


# ──────────────────────────────────────────────────────────────
# Webhook Endpoints
# ──────────────────────────────────────────────────────────────

@app.post("/webhook/scrape")
async def receive_scrape_webhook(
    request: Request,
    x_webhook_signature: str = Header(default=""),
) -> JSONResponse:
    """
    Receive scrape completion webhook.

    Expected payload:
    {
        "url": "https://example.com",
        "success": true,
        "status_code": 200,
        "word_count": 150,
        "token_count": 200,
        "response_time_ms": 1234.5,
        "cached": false,
        "metadata": {"title": "..."},
        "request_id": "req_abc123"
    }
    """
    body = await request.body()

    # Verify signature
    signature_valid = verify_signature(body, x_webhook_signature)

    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Create event
    event = WebhookEvent(
        id=str(uuid.uuid4()),
        event_type="scrape.complete",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        signature_valid=signature_valid,
    )

    # Process
    event.processed = True
    event.processing_result = _process_scrape_event(payload)

    # Store
    store.add(event)

    logger.info(
        "Scrape webhook: %s (success=%s, words=%d)",
        payload.get("url", "?"),
        payload.get("success"),
        payload.get("word_count", 0),
    )

    return JSONResponse(
        status_code=200,
        content={"status": "received", "event_id": event.id},
    )


@app.post("/webhook/crawl")
async def receive_crawl_webhook(
    request: Request,
    x_webhook_signature: str = Header(default=""),
) -> JSONResponse:
    """
    Receive crawl progress/completion webhook.

    Expected payload:
    {
        "job_id": "job_abc123",
        "status": "running|completed|failed|cancelled",
        "pages_crawled": 15,
        "total_pages": 50,
        "progress": 0.30,
        "current_url": "https://..."
    }
    """
    body = await request.body()
    signature_valid = verify_signature(body, x_webhook_signature)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    status = payload.get("status", "unknown")
    event_type = f"crawl.{status}"

    event = WebhookEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        signature_valid=signature_valid,
    )

    event.processed = True
    event.processing_result = _process_crawl_event(payload)

    store.add(event)

    logger.info(
        "Crawl webhook: job=%s status=%s progress=%.0f%%",
        payload.get("job_id", "?"),
        status,
        payload.get("progress", 0) * 100,
    )

    return JSONResponse(
        status_code=200,
        content={"status": "received", "event_id": event.id},
    )


@app.post("/webhook/error")
async def receive_error_webhook(
    request: Request,
    x_webhook_signature: str = Header(default=""),
) -> JSONResponse:
    """
    Receive error notification webhook.

    Expected payload:
    {
        "url": "https://example.com",
        "error": "Timeout after 30s",
        "error_type": "timeout",
        "status_code": 0,
        "request_id": "req_abc123"
    }
    """
    body = await request.body()
    signature_valid = verify_signature(body, x_webhook_signature)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = WebhookEvent(
        id=str(uuid.uuid4()),
        event_type="error",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        signature_valid=signature_valid,
    )

    event.processed = True
    event.processing_result = _process_error_event(payload)

    store.add(event)

    logger.warning(
        "Error webhook: %s — %s",
        payload.get("url", "?"),
        payload.get("error", "unknown"),
    )

    return JSONResponse(
        status_code=200,
        content={"status": "received", "event_id": event.id},
    )


# ──────────────────────────────────────────────────────────────
# Query Endpoints
# ──────────────────────────────────────────────────────────────

@app.get("/webhook/events")
async def list_events(
    event_type: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    """List received webhook events."""
    events = store.list_events(event_type=event_type, limit=limit)

    return JSONResponse(content={
        "total": len(events),
        "events": [e.to_dict() for e in events],
        "stats": store.stats,
    })


@app.get("/webhook/events/{event_id}")
async def get_event(event_id: str) -> JSONResponse:
    """Get a specific event by ID."""
    event = store.get(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return JSONResponse(content=event.to_dict())


@app.get("/health")
async def health() -> JSONResponse:
    """Health check."""
    return JSONResponse(content={
        "status": "healthy",
        "events_stored": len(store._events),
        "stats": store.stats,
    })


# ──────────────────────────────────────────────────────────────
# Event Processors
# ──────────────────────────────────────────────────────────────

def _process_scrape_event(payload: dict[str, Any]) -> str:
    """Process a scrape completion event."""
    url = payload.get("url", "")
    success = payload.get("success", False)
    word_count = payload.get("word_count", 0)

    if success:
        # Example: store in database, trigger downstream processing
        return f"Stored scrape result for {url} ({word_count} words)"
    else:
        # Example: alert, retry, log
        error = payload.get("error", "unknown")
        return f"Scrape failed for {url}: {error}"


def _process_crawl_event(payload: dict[str, Any]) -> str:
    """Process a crawl progress/completion event."""
    job_id = payload.get("job_id", "")
    status = payload.get("status", "")

    if status == "completed":
        total_pages = payload.get("total_pages", 0)
        total_words = payload.get("total_words", 0)
        return f"Crawl {job_id} completed: {total_pages} pages, {total_words} words"
    elif status == "failed":
        return f"Crawl {job_id} failed"
    elif status == "cancelled":
        return f"Crawl {job_id} cancelled"
    else:
        progress = payload.get("progress", 0)
        return f"Crawl {job_id} in progress: {progress:.0%}"


def _process_error_event(payload: dict[str, Any]) -> str:
    """Process an error event."""
    url = payload.get("url", "")
    error = payload.get("error", "")
    return f"Error logged for {url}: {error}"


# ──────────────────────────────────────────────────────────────
# Webhook Sender (for testing)
# ══════════════════════════════════════════════════════════════

async def send_test_webhook(
    event_type: str = "scrape",
    base_url: str = f"http://localhost:{PORT}",
) -> None:
    """
    Send a test webhook to the receiver.

    Useful for testing the webhook pipeline.
    """
    import httpx

    payloads = {
        "scrape": {
            "url": "https://example.com",
            "success": True,
            "status_code": 200,
            "word_count": 150,
            "token_count": 200,
            "response_time_ms": 1234.5,
            "cached": False,
            "metadata": {"title": "Example Domain"},
            "request_id": "req_test123",
        },
        "crawl": {
            "job_id": "job_test456",
            "status": "completed",
            "pages_crawled": 10,
            "pages_failed": 1,
            "total_pages": 10,
            "progress": 1.0,
            "elapsed_ms": 15000,
            "total_words": 5000,
            "total_tokens": 7000,
        },
        "error": {
            "url": "https://broken.example.com",
            "error": "Connection timeout after 30s",
            "error_type": "timeout",
            "status_code": 0,
            "request_id": "req_err789",
        },
    }

    payload = payloads.get(event_type, payloads["scrape"])
    body = json.dumps(payload).encode("utf-8")
    signature = compute_signature(body)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/webhook/{event_type}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
            },
        )

        print(f"  Sent {event_type} webhook → {resp.status_code}")
        print(f"  Response: {resp.json()}")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        # Send test webhooks
        import asyncio

        async def run_tests() -> None:
            print("Sending test webhooks...")
            await send_test_webhook("scrape")
            await send_test_webhook("crawl")
            await send_test_webhook("error")
            print("Done!")

        asyncio.run(run_tests())

    else:
        # Start the webhook receiver server
        import uvicorn

        print("\nAgentCrawl Webhook Receiver")
        print(f"{'=' * 50}")
        print(f"  Port: {PORT}")
        print(f"  Secret: {WEBHOOK_SECRET[:8]}...")
        print("  Endpoints:")
        print("    POST /webhook/scrape")
        print("    POST /webhook/crawl")
        print("    POST /webhook/error")
        print("    GET  /webhook/events")
        print("    GET  /health")
        print("\n  Start server:")
        print(f"    uvicorn examples.server_mode.webhook_receiver:app --port {PORT}")
        print("\n  Send test webhooks:")
        print("    python examples/server_mode/webhook_receiver.py --test")
        print()

        uvicorn.run(app, host="0.0.0.0", port=PORT)
