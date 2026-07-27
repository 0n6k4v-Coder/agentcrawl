# ══════════════════════════════════════════════════════════════
# AgentCrawl — Multi-Stage Dockerfile
# AI-Ready Web Crawler & Scraper
# ══════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────
# Stage 1: Builder — Install dependencies & build wheels
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first (layer caching)
COPY pyproject.toml README.md LICENSE ./
COPY agentcrawl/ ./agentcrawl/
COPY server/ ./server/
COPY agent/ ./agent/

# Build wheel
RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /build/dist

# Install the wheel + server dependencies into a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir /build/dist/*.whl \
    && pip install --no-cache-dir \
        "fastapi>=0.110.0" \
        "uvicorn[standard]>=0.27.0" \
        "gunicorn>=21.2.0" \
        "python-multipart>=0.0.9" \
        "python-jose[cryptography]>=3.3.0" \
        "passlib[bcrypt]>=1.7.0" \
        "slowapi>=0.1.9" \
        "sse-starlette>=2.0.0" \
        "websockets>=12.0" \
        "redis[hiredis]>=5.0.0" \
        "prometheus-client>=0.20.0"

# ──────────────────────────────────────────────────────────────
# Stage 2: Playwright — Install browsers separately
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS playwright

# Install Playwright system dependencies for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        # X11 / display
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxcursor1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        libxss1 \
        libxtst6 \
        # GTK / rendering
        libgtk-3-0 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libcairo-gobject2 \
        # Fonts
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-freefont-ttf \
        fonts-unifont \
        # Network / TLS
        libnss3 \
        libnspr4 \
        libdbus-1-3 \
        # Audio / video (for full browser support)
        libasound2 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libgbm1 \
        libxkbcommon0 \
        # Misc
        libatspi2.0-0 \
        libxshmfence1 \
        xdg-utils \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Playwright Chromium browser
RUN playwright install chromium \
    && playwright install-deps chromium

# ──────────────────────────────────────────────────────────────
# Stage 3: Runtime — Final minimal image
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="AgentCrawl Team <team@agentcrawl.dev>"
LABEL description="AI-Ready Web Crawler & Scraper — Server Mode"
LABEL version="1.0.0"

# Security: create non-root user
RUN groupadd --gid 1000 agentcrawl \
    && useradd --uid 1000 --gid agentcrawl --shell /bin/bash --create-home agentcrawl

# Install only runtime system dependencies (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Playwright runtime libs
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxcursor1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        libxss1 \
        libxtst6 \
        libgtk-3-0 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libcairo-gobject2 \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-freefont-ttf \
        fonts-unifont \
        libnss3 \
        libnspr4 \
        libdbus-1-3 \
        libasound2 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libgbm1 \
        libxkbcommon0 \
        libatspi2.0-0 \
        libxshmfence1 \
        xdg-utils \
        wget \
        ca-certificates \
        # Health check
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy Playwright browsers from playwright stage
COPY --from=playwright /root/.cache/ms-playwright /home/agentcrawl/.cache/ms-playwright

# Copy Python virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv" \
    # Playwright config
    PLAYWRIGHT_BROWSERS_PATH="/home/agentcrawl/.cache/ms-playwright" \
    # Python config
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    # AgentCrawl defaults
    AGENTCRAWL_HEADLESS=true \
    AGENTCRAWL_STEALTH=true \
    AGENTCRAWL_BROWSER=chromium \
    AGENTCRAWL_MAX_CONCURRENT=5 \
    AGENTCRAWL_TIMEOUT=30 \
    AGENTCRAWL_HOST=0.0.0.0 \
    AGENTCRAWL_PORT=8000

WORKDIR /app

# Copy application source
COPY --chown=agentcrawl:agentcrawl agentcrawl/ ./agentcrawl/
COPY --chown=agentcrawl:agentcrawl server/ ./server/
COPY --chown=agentcrawl:agentcrawl agent/ ./agent/
COPY --chown=agentcrawl:agentcrawl pyproject.toml README.md LICENSE ./

# Create directories for cache, logs, data
RUN mkdir -p /app/.cache /app/logs /app/data \
    && chown -R agentcrawl:agentcrawl /app

# Switch to non-root user
USER agentcrawl

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Volume mounts for persistence
VOLUME ["/app/.cache", "/app/logs", "/app/data"]

# ──────────────────────────────────────────────────────────────
# Entrypoint & Command
# ──────────────────────────────────────────────────────────────

# Default: run with uvicorn (single worker, good for dev / small deployments)
# For production, override with gunicorn:
#   docker run agentcrawl gunicorn server.main:app \
#     --worker-class uvicorn.workers.UvicornWorker \
#     --bind 0.0.0.0:8000 --workers 4 --timeout 120
ENTRYPOINT []

CMD ["python", "-m", "uvicorn", "server.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--log-level", "info", \
     "--access-log", \
     "--timeout-keep-alive", "65"]