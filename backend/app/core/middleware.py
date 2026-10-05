"""Pure-ASGI middleware (safe for streaming/SSE responses).

- RequestContextMiddleware: request/correlation IDs, access log, metrics, security headers.
- BodySizeLimitMiddleware: rejects oversized bodies (Content-Length and streamed).
- RateLimitMiddleware: per-client sliding-window limit (in-memory, per process).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.context import correlation_id_var, request_id_var, user_id_var
from app.core.errors import error_body
from app.core.logging import get_logger
from app.services.metrics import RequestMetrics

log = get_logger("http")
_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


async def _send_json(send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                            *(headers or [])]})
    await send({"type": "http.response.body", "body": payload})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, metrics: RequestMetrics, settings: Settings) -> None:
        self.app = app
        self.metrics = metrics
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode(errors="ignore") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _ID.match(incoming) else uuid.uuid4().hex
        corr = headers.get("x-correlation-id", "")
        tokens = (request_id_var.set(rid), correlation_id_var.set(corr if _ID.match(corr) else rid), user_id_var.set(None))
        path: str = scope.get("path", "")
        status_holder = {"status": 500}
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = rid
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                if not path.startswith(_DOCS_PATHS):
                    h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                h.setdefault("Cache-Control", "no-store")
                if self.settings.is_production_like:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = (time.perf_counter() - started) * 1000
            route = getattr(scope.get("route"), "path", None) or ("unmatched" if status_holder["status"] == 404 else path)
            self.metrics.record(scope.get("method", "GET"), route, status_holder["status"], duration)
            if path not in ("/health", "/ready"):
                log.info("request", extra={"method": scope.get("method"), "route": route,
                                           "status": status_holder["status"], "duration_ms": round(duration, 1)})
            for var, token in zip((request_id_var, correlation_id_var, user_id_var), tokens, strict=True):
                var.reset(token)  # type: ignore[attr-defined]


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.default_limit = settings.max_request_body_bytes
        self.upload_limit = settings.max_upload_bytes + 64 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.upload_limit if scope.get("path") == "/knowledge/ingest" else self.default_limit
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    if int(value) > limit:
                        await _send_json(send, 413, error_body("payload_too_large", f"Request body exceeds {limit} bytes."))
                        return
                except ValueError:
                    await _send_json(send, 400, error_body("bad_request", "Invalid Content-Length."))
                    return
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await _send_json(send, 413, error_body("payload_too_large", f"Request body exceeds {limit} bytes."))


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(window - (now - hits[0])))
            hits.append(now)
            if len(self._hits) > 50_000:  # bound memory under key-spraying
                self._hits.pop(next(iter(self._hits)))
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in ("/health", "/ready") or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        allowed, retry = limiter.check(f"ip:{client}", self.settings.rate_limit_per_minute)
        if not allowed:
            await _send_json(send, 429, error_body("rate_limited", "Too many requests; slow down."),
                             [(b"retry-after", str(retry).encode())])
            return
        await self.app(scope, receive, send)
