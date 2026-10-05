"""Process-local HTTP request metrics (rolling window). Persistent AI/tool metrics live in the database."""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RequestSample:
    ts: float
    method: str
    route: str
    status: int
    duration_ms: float


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


class RequestMetrics:
    def __init__(self, window: int = 5000) -> None:
        self._samples: deque[RequestSample] = deque(maxlen=window)
        self._lock = threading.Lock()
        self._started = time.time()
        self._total = 0

    def record(self, method: str, route: str, status: int, duration_ms: float) -> None:
        with self._lock:
            self._samples.append(RequestSample(time.time(), method, route, status, duration_ms))
            self._total += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
            total = self._total
        durations = [s.duration_ms for s in samples]
        errors_5xx = sum(1 for s in samples if s.status >= 500)
        errors_4xx = sum(1 for s in samples if 400 <= s.status < 500)
        by_route = Counter(f"{s.method} {s.route}" for s in samples)
        slow_rows = [(r, percentile([s.duration_ms for s in samples if f"{s.method} {s.route}" == r], 95), c)
                    for r, c in by_route.most_common(12)]
        slow_rows.sort(key=lambda row: -(row[1] or 0))
        slow = [{"route": r, "p95_ms": p95, "count": c} for r, p95, c in slow_rows]
        return {
            "scope": "process-local rolling window (resets on restart)",
            "uptime_seconds": int(time.time() - self._started),
            "requests_total": total,
            "window_size": len(samples),
            "errors_5xx": errors_5xx,
            "errors_4xx": errors_4xx,
            "error_rate_5xx": round(errors_5xx / len(samples), 4) if samples else 0.0,
            "latency_ms": {"p50": percentile(durations, 50), "p95": percentile(durations, 95),
                           "p99": percentile(durations, 99)},
            "routes": slow,
        }
