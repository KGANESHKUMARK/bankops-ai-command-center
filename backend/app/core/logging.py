"""Structured JSON logging with correlation IDs and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import current_context

SENSITIVE_KEYS = re.compile(r"(pass(word)?|secret|token|authorization|api[_-]?key|cookie|credential)", re.I)
BEARER_RE = re.compile(r"(?i)bearer\s+[a-z0-9\-_\.=]+")
JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+")
KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def redact_text(value: str) -> str:
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = JWT_RE.sub("[REDACTED_JWT]", value)
    return KEY_RE.sub("[REDACTED_KEY]", value)


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively redact secrets from structures before they are logged or stored."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if SENSITIVE_KEYS.search(str(k)) else redact(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value][:200]
    if isinstance(value, str):
        return redact_text(value)[:4000]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        payload.update(current_context())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact(value) if not SENSITIVE_KEYS.search(key) else "[REDACTED]"
        if record.exc_info and record.exc_info[0] is not None:
            # Only the exception type is logged by default to avoid leaking data in messages.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
