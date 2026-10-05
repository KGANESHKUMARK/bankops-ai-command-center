"""Deterministic evaluation metrics and release-gate logic."""

from __future__ import annotations

import operator
from collections.abc import Sequence
from typing import Any

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}


def dedupe(seq: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(seq))


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall is undefined without relevant items")
    return len(set(dedupe(ranked)[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    top = dedupe(ranked)[:k]
    return len(set(top) & relevant) / k if k else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, item in enumerate(dedupe(ranked), start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def evaluate_gate(metrics: dict[str, Any], rules: dict[str, dict[str, Any]]) -> tuple[bool, list[str], list[str]]:
    """Return (passed, blocking_failures, warnings). Missing required metrics are failures."""
    failures: list[str] = []
    warnings: list[str] = []
    for name, rule in rules.items():
        value = metrics.get(name)
        op = _OPS[rule["op"]]
        target = rule["value"]
        if value is None:
            message = f"{name}: not measured (required {rule['op']} {target})"
        elif op(value, target):
            continue
        else:
            message = f"{name}={value} violates {rule['op']} {target}"
        (failures if rule.get("required") else warnings).append(message)
    return not failures, failures, warnings
