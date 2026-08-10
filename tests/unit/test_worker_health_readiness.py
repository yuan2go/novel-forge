from __future__ import annotations

from novel_forge.storage.worker_health import evaluate_worker_fleet_readiness


def _worker(kind: str, *, fresh: bool = True, status: str = "READY") -> dict:
    return {
        "worker_kind": kind,
        "fresh": fresh,
        "status": status,
        "database_status": "READY",
    }


def test_required_worker_kinds_must_all_have_a_fresh_healthy_instance() -> None:
    result = evaluate_worker_fleet_readiness(
        [_worker("chapter")],
        required_worker_kinds=("chapter", "book"),
    )

    assert result["ready"] is False
    assert result["missing_worker_kinds"] == ["book"]


def test_stale_replaced_instance_does_not_degrade_a_healthy_required_kind() -> None:
    result = evaluate_worker_fleet_readiness(
        [
            _worker("chapter", fresh=False),
            _worker("chapter", fresh=True),
            _worker("book", fresh=True),
        ],
        required_worker_kinds=("chapter", "book"),
    )

    assert result["ready"] is True
    assert result["missing_worker_kinds"] == []
    assert result["unhealthy_worker_kinds"] == []
