from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


DEFAULT_WRITE_BUDGET = {
    "max_file_writes": 500,
    "max_asset_writes": 240,
    "max_scan_calls": 5000,
    "max_context_builds": 24,
    "max_bytes_written": 25_000_000,
}

_ACTIVE_BUDGET: ContextVar["WriteBudget | None"] = ContextVar("novel_forge_write_budget", default=None)


class WriteBudgetExceeded(RuntimeError):
    def __init__(self, metric: str, value: int, limit: int) -> None:
        self.metric = metric
        self.value = int(value)
        self.limit = int(limit)
        super().__init__(f"write budget exceeded: {metric}={value} > {limit}")


@dataclass
class WriteBudget:
    limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WRITE_BUDGET))
    metrics: dict[str, int] = field(default_factory=lambda: {key.removeprefix("max_"): 0 for key in DEFAULT_WRITE_BUDGET})
    writes_by_category: dict[str, int] = field(default_factory=dict)
    status: str = "active"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "WriteBudget":
        raw = payload if isinstance(payload, dict) else {}
        limits = dict(DEFAULT_WRITE_BUDGET)
        for key in limits:
            if key not in raw:
                continue
            try:
                limits[key] = max(1, int(raw[key]))
            except (TypeError, ValueError):
                raise ValueError(f"write budget {key} must be a positive integer")
        return cls(limits=limits, metrics={key.removeprefix("max_"): 0 for key in limits})

    def record_write(self, path: str | Path, *, byte_count: int, asset: bool, category: str = "") -> None:
        self._increment("file_writes", 1, "max_file_writes")
        self._increment("bytes_written", max(0, int(byte_count)), "max_bytes_written")
        if asset:
            self._increment("asset_writes", 1, "max_asset_writes")
        if category:
            self.writes_by_category[category] = self.writes_by_category.get(category, 0) + 1

    def record_metric(self, metric: str, amount: int = 1) -> None:
        normalized = str(metric or "").strip()
        if not normalized:
            return
        limit_key = f"max_{normalized}"
        self._increment(normalized, amount, limit_key)

    def snapshot(self) -> dict[str, Any]:
        return {"limits": dict(self.limits), "metrics": dict(self.metrics), "writes_by_category": dict(self.writes_by_category), "status": self.status if self.status != "active" else "passed"}

    def _increment(self, metric: str, amount: int, limit_key: str) -> None:
        value = int(self.metrics.get(metric, 0)) + int(amount)
        self.metrics[metric] = value
        limit = self.limits.get(limit_key)
        if limit is not None and value > int(limit):
            self.status = "failed"
            raise WriteBudgetExceeded(metric, value, int(limit))


def active_write_budget() -> WriteBudget | None:
    return _ACTIVE_BUDGET.get()


@contextmanager
def write_budget(payload: dict[str, Any] | WriteBudget | None) -> Iterator[WriteBudget]:
    budget = payload if isinstance(payload, WriteBudget) else WriteBudget.from_payload(payload)
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)
