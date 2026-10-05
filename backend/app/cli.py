"""Operational CLI: `python -m app.cli {seed|reset-demo|evaluate|check-config}`."""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings, validate_startup_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.domain import Role
from app.models import User
from app.policy.engine import Actor
from app.services.container import build_container


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["seed", "reset-demo", "evaluate", "check-config"])
    parser.add_argument("--no-workflow", action="store_true", help="evaluate: skip workflow cases")
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    settings = get_settings()
    if args.command == "check-config":
        print(json.dumps({"warnings": validate_startup_settings(settings), "index_version": settings.index_version}, indent=2))
        return 0
    container = build_container(settings.model_copy(update={"workflow_execution_mode": "sync"}))
    from app.seed.seed import reset_demo, seed_all

    with get_session_factory()() as db:
        if args.command == "seed":
            print(json.dumps(seed_all(db, container), indent=2))
        elif args.command == "reset-demo":
            print(json.dumps(reset_demo(db, container, actor=None), indent=2))
        else:
            from app.evaluation.harness import EvaluationHarness

            user = db.execute(select(User).where(User.role == Role.OPERATIONS_MANAGER, User.tenant_id == "contoso-demo")
                              .order_by(User.username)).scalars().first()
            if user is None:
                print("Seed the database first.", file=sys.stderr)
                return 2
            er = EvaluationHarness(container).run(db, Actor(user.id, user.username, user.role, user.tenant_id),
                                                  include_workflow=not args.no_workflow)
            print(json.dumps({"id": er.id, "status": er.status, "gate_passed": er.gate_passed,
                              "gate_failures": er.gate_failures, "metrics": er.metrics}, indent=2, default=str))
            return 0 if er.status == "completed" else 1
    container.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
