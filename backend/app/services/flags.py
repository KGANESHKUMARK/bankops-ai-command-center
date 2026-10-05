"""Failure-injection flags for resilience demos (demo_admin only, local/demo mode only)."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from app.models import DemoFlag

FaultName = Literal["provider_timeout", "retrieval_failure", "downstream_outage"]
FAULTS: dict[str, str] = {
    "provider_timeout": "Model gateway calls fail with a simulated timeout (AI steps degrade; no fabricated findings).",
    "retrieval_failure": "Knowledge retrieval raises an error (evidence becomes insufficient; workflow abstains).",
    "downstream_outage": "Synthetic monitoring/tool APIs are unavailable (tool calls fail safely; no execution).",
}


def get_faults(db: Session) -> dict[str, bool]:
    rows = {f.key: f for f in db.query(DemoFlag).filter(DemoFlag.key.in_(list(FAULTS))).all()}
    return {name: bool(rows[name].value.get("enabled")) if name in rows else False for name in FAULTS}


def fault_enabled(db: Session, name: str) -> bool:
    row = db.get(DemoFlag, name)
    return bool(row and row.value.get("enabled"))


def set_fault(db: Session, name: str, enabled: bool, user_id: str | None) -> None:
    if name not in FAULTS:
        raise ValueError("unknown fault")
    row = db.get(DemoFlag, name)
    if row is None:
        db.add(DemoFlag(key=name, value={"enabled": enabled}, updated_by=user_id))
    else:
        row.value = {"enabled": enabled}
        row.updated_by = user_id
