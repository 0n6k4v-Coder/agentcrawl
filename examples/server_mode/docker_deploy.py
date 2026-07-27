"""
AgentCrawl — Docker Deployment Generator
============================================

Generates Docker, Docker Compose, Kubernetes, and Nginx
configuration files for deploying AgentCrawl server.

Usage:
    # Generate all files
    python examples/server_mode/docker_deploy.py

    # Generate specific files
    python examples/server_mode/docker_deploy.py --dockerfile
    python examples/server_mode/docker_deploy.py --compose
    python examples/server_mode/docker_deploy.py --k8s
    python examples/server_mode/docker_deploy.py --nginx

    # Custom output directory
    python examples/server_mode/docker_deploy.py --output-dir deploy/

    # With Redis
    python examples/server_mode/docker_deploy.py --compose --redis

    # With custom port
    python examples/server_mode/docker_deploy.py --port 9000

Output:
    Dockerfile
    docker-compose.yml
    .dockerignore
    nginx.conf
    k8s/deployment.yaml
    k8s/service.yaml
    k8s/configmap.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════
# Templates
# ══════════════════════════════════════════════════════════════

DOCKERFILE_TEMPLATE = """\
# AgentCrawl Server — Dockerfile
# Multi-stage build for minimal image size

# ── Stage 1: Builder ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install ".[all]"

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM python:3.12-slim

# Install runtime dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \\
    wget \\
    gnupg2 \\
    libnss3 \\
    libatk1.0-0 \\
    libatk-bridge2.0-0 \\
    libcups2 \\
    libdrm2 \\
    libxkbcommon0 \\
    libxcomposite1 \\
    libxdamage1 \\
    libxrandr2 \\
    libgbm1 \\
    libpango-1.0-0 \\
    libcairo2 \\
    libasound2 \\
    libxshmfence1 \\
    fonts-liberation \\
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Install AgentCrawl
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir -e ".[all]"

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Create non-root user
RUN useradd --create-home --shell /bin/bash agentcrawl
USER agentcrawl

# Expose port
EXPOSE {port}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')" || exit 1

# Start server
CMD ["agentcrawl", "serve", "--host", "0.0.0.0", "--port", "{port}", "--workers", "{workers}"]
"""

DOCKER_COMPOSE_TEMPLATE = """\
# AgentCrawl — Docker Compose
version: "3.8"

services:
  agentcrawl:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "{port}:{port}"
    environment:
      - AGENTCRAWL_HOST=0.0.0.0
      - AGENTCRAWL_PORT={port}
      - AGENTCRAWL_WORKERS={workers}
      - AGENTCRAWL_API_KEY=${{API_KEY:-}}
      - AGENTCRAWL_LOG_LEVEL=${{LOG_LEVEL:-info}}
      - AGENTCRAWL_BROWSER_TYPE=chromium
      - AGENTCRAWL_HEADLESS=true
      - AGENTCRAWL_STEALTH=true{redis_env}
    depends_on:{redis_depends}
      - redis
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
{redis_service}
volumes:
  redis_data:
"""

DOCKER_COMPOSE_REDIS_SERVICE = """\
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
"""

DOCKERIGNORE_TEMPLATE = """\
# Git
.git
.gitignore

# Python
__pycache__
*.pyc
*.pyo
*.egg-info
.eggs
dist
build
.venv
venv
env

# IDE
.vscode
.idea
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Docs
docs/
*.md
!README.md

# Tests
tests/
.pytest_cache
.coverage
htmlcov

# Examples
examples/
scripts/

# Config
.env
.env.local
*.local

# Docker
Dockerfile
docker-compose*.yml
.dockerignore

# K8s
k8s/
deploy/
"""

NGINX_TEMPLATE = """\
# AgentCrawl — Nginx Reverse Proxy
upstream agentcrawl {{
    server agentcrawl:{port};
    keepalive 32;
}}

server {{
    listen 80;
    server_name _;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Request size limit
    client_max_body_size 10M;

    # Timeouts
    proxy_connect_timeout 30s;
    proxy_send_timeout 120s;
    proxy_read_timeout 120s;

    # Health check (no auth)
    location /health {{
        proxy_pass http://agentcrawl;
        proxy_set_header Host $host;
    }}

    # API endpoints
    location / {{
        proxy_pass http://agentcrawl;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m;

    location /scrape {{
        limit_req zone=api burst=10 nodelay;
        proxy_pass http://agentcrawl;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
"""

K8S_DEPLOYMENT_TEMPLATE = """\
# AgentCrawl — Kubernetes Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentcrawl
  labels:
    app: agentcrawl
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: agentcrawl
  template:
    metadata:
      labels:
        app: agentcrawl
    spec:
      containers:
        - name: agentcrawl
          image: agentcrawl:latest
          ports:
            - containerPort: {port}
          env:
            - name: AGENTCRAWL_HOST
              value: "0.0.0.0"
            - name: AGENTCRAWL_PORT
              value: "{port}"
            - name: AGENTCRAWL_WORKERS
              value: "{workers}"
            - name: AGENTCRAWL_API_KEY
              valueFrom:
                secretKeyRef:
                  name: agentcrawl-secrets
                  key: api-key
                  optional: true
            - name: AGENTCRAWL_LOG_LEVEL
              valueFrom:
                configMapKeyRef:
                  name: agentcrawl-config
                  key: log-level
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "2Gi"
              cpu: "1000m"
          livenessProbe:
            httpGet:
              path: /health
              port: {port}
            initialDelaySeconds: 15
            periodSeconds: 30
            timeoutSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: {port}
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
      terminationGracePeriodSeconds: 30
"""

K8S_SERVICE_TEMPLATE = """\
# AgentCrawl — Kubernetes Service
apiVersion: v1
kind: Service
metadata:
  name: agentcrawl
  labels:
    app: agentcrawl
spec:
  type: ClusterIP
  selector:
    app: agentcrawl
  ports:
    - name: http
      port: 80
      targetPort: {port}
      protocol: TCP
"""

K8S_CONFIGMAP_TEMPLATE = """\
# AgentCrawl — Kubernetes ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: agentcrawl-config
data:
  log-level: "info"
  browser-type: "chromium"
  headless: "true"
  stealth: "true"
  cache-backend: "memory"
  cache-ttl: "3600"
"""

K8S_INGRESS_TEMPLATE = """\
# AgentCrawl — Kubernetes Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: agentcrawl
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "120"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "120"
    nginx.ingress.kubernetes.io/limit-rps: "10"
spec:
  ingressClassName: nginx
  rules:
    - host: api.agentcrawl.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: agentcrawl
                port:
                  number: 80
"""


# ══════════════════════════════════════════════════════════════
# Generator
# ══════════════════════════════════════════════════════════════

class DeployGenerator:
    """
    Generates deployment configuration files.

    Args:
        output_dir: Output directory for generated files.
        port: Server port.
        workers: Number of worker processes.
        replicas: Kubernetes replicas.
        redis: Whether to include Redis.
    """

    def __init__(
        self,
        output_dir: str = ".",
        port: int = 8000,
        workers: int = 2,
        replicas: int = 2,
        redis: bool = False,
    ):
        self._output_dir = Path(output_dir)
        self._port = port
        self._workers = workers
        self._replicas = replicas
        self._redis = redis

    def _write(self, filepath: str, content: str) -> None:
        """Write content to a file."""
        path = self._output_dir / filepath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"  ✓ {path}")

    def generate_dockerfile(self) -> None:
        """Generate Dockerfile."""
        content = DOCKERFILE_TEMPLATE.format(
            port=self._port,
            workers=self._workers,
        )
        self._write("Dockerfile", content)

    def generate_dockerignore(self) -> None:
        """Generate .dockerignore."""
        self._write(".dockerignore", DOCKERIGNORE_TEMPLATE)

    def generate_compose(self) -> None:
        """Generate docker-compose.yml."""
        redis_env = ""
        redis_depends = ""
        redis_service = ""

        if self._redis:
            redis_env = "\n      - AGENTCRAWL_CACHE_BACKEND=redis\n      - AGENTCRAWL_REDIS_URL=redis://redis:6379"
            redis_depends = "\n      - redis"
            redis_service = "\n" + DOCKER_COMPOSE_REDIS_SERVICE

        content = DOCKER_COMPOSE_TEMPLATE.format(
            port=self._port,
            workers=self._workers,
            redis_env=redis_env,
            redis_depends=redis_depends,
            redis_service=redis_service,
        )
        self._write("docker-compose.yml", content)

    def generate_nginx(self) -> None:
        """Generate nginx.conf."""
        content = NGINX_TEMPLATE.format(port=self._port)
        self._write("nginx.conf", content)

    def generate_k8s(self) -> None:
        """Generate Kubernetes manifests."""
        k8s_dir = "k8s"

        self._write(
            f"{k8s_dir}/deployment.yaml",
            K8S_DEPLOYMENT_TEMPLATE.format(
                port=self._port,
                workers=self._workers,
                replicas=self._replicas,
            ),
        )

        self._write(
            f"{k8s_dir}/service.yaml",
            K8S_SERVICE_TEMPLATE.format(port=self._port),
        )

        self._write(
            f"{k8s_dir}/configmap.yaml",
            K8S_CONFIGMAP_TEMPLATE,
        )

        self._write(
            f"{k8s_dir}/ingress.yaml",
            K8S_INGRESS_TEMPLATE,
        )

    def generate_all(self) -> None:
        """Generate all deployment files."""
        self.generate_dockerfile()
        self.generate_dockerignore()
        self.generate_compose()
        self.generate_nginx()
        self.generate_k8s()

    def print_instructions(self) -> None:
        """Print deployment instructions."""
        print(f"""
{'=' * 55}
  Deployment Instructions
{'=' * 55}

  Docker:
    docker build -t agentcrawl .
    docker run -p {self._port}:{self._port} agentcrawl

  Docker Compose:
    docker compose up -d
    docker compose logs -f agentcrawl

  Kubernetes:
    kubectl apply -f k8s/
    kubectl get pods -l app=agentcrawl

  Verify:
    curl http://localhost:{self._port}/health

  Environment Variables:
    API_KEY          — API authentication key
    LOG_LEVEL        — Logging level (info, debug, warning)
    AGENTCRAWL_PORT  — Server port (default: {self._port})
""")


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Docker/K8s deployment files for AgentCrawl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/server_mode/docker_deploy.py
  python examples/server_mode/docker_deploy.py --compose --redis
  python examples/server_mode/docker_deploy.py --k8s --replicas 3
  python examples/server_mode/docker_deploy.py --output-dir deploy/ --port 9000
        """,
    )

    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of workers (default: 2)",
    )
    parser.add_argument(
        "--replicas",
        type=int,
        default=2,
        help="Kubernetes replicas (default: 2)",
    )
    parser.add_argument(
        "--redis",
        action="store_true",
        help="Include Redis in docker-compose",
    )
    parser.add_argument(
        "--dockerfile",
        action="store_true",
        help="Generate Dockerfile only",
    )
    parser.add_argument(
        "--compose",
        action="store_true",
        help="Generate docker-compose.yml only",
    )
    parser.add_argument(
        "--nginx",
        action="store_true",
        help="Generate nginx.conf only",
    )
    parser.add_argument(
        "--k8s",
        action="store_true",
        help="Generate Kubernetes manifests only",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all files (default)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("\nAgentCrawl — Deployment Generator")
    print("=" * 55)
    print(f"  Output: {args.output_dir}")
    print(f"  Port: {args.port}")
    print(f"  Workers: {args.workers}")
    print(f"  Redis: {args.redis}")
    print()

    generator = DeployGenerator(
        output_dir=args.output_dir,
        port=args.port,
        workers=args.workers,
        replicas=args.replicas,
        redis=args.redis,
    )

    # Determine what to generate
    generate_specific = any([
        args.dockerfile,
        args.compose,
        args.nginx,
        args.k8s,
    ])

    if args.dockerfile:
        generator.generate_dockerfile()
        generator.generate_dockerignore()

    if args.compose:
        generator.generate_compose()

    if args.nginx:
        generator.generate_nginx()

    if args.k8s:
        generator.generate_k8s()

    if not generate_specific or args.all:
        generator.generate_all()

    generator.print_instructions()


if __name__ == "__main__":
    main()