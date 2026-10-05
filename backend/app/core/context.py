"""Request/workflow correlation context propagated through contextvars."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
investigation_id_var: ContextVar[str | None] = ContextVar("investigation_id", default=None)
agent_var: ContextVar[str | None] = ContextVar("agent", default=None)
tool_var: ContextVar[str | None] = ContextVar("tool", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def current_context() -> dict[str, str]:
    values = {
        "request_id": request_id_var.get(),
        "correlation_id": correlation_id_var.get(),
        "investigation_id": investigation_id_var.get(),
        "agent": agent_var.get(),
        "tool": tool_var.get(),
        "user_id": user_id_var.get(),
    }
    return {k: v for k, v in values.items() if v}
