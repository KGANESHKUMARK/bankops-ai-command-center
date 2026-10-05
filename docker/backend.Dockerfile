# BankOps AI Command Center — Backend image
# Multi-stage build: install deps, then copy app into a slim runtime image.
# SYNTHETIC DEMO ONLY — never connect to real banking systems.

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies for argon2-cffi and pgvector-related packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN python -m venv /opt/venv
RUN /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r bankops && useradd -r -g bankops -d /app -s /sbin/nologin bankops

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/pyproject.toml ./

RUN mkdir -p /app/data && chown -R bankops:bankops /app

USER bankops

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
