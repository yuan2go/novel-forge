from __future__ import annotations

import time
from typing import Any, Callable

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_scheduler.execution_runner import bucket_dispatch_result
from novel_forge.storage.local import LocalStorage

TickCallback = Callable[..., Any]


def run_scheduler_tick(
    storage: LocalStorage,
    *,
    project_id: str | None,
    limit: int,
    lease_owner: str,
    lease_ttl_seconds: int,
    force_lease: bool,
    retry_delay_seconds: int,
    dry_run: bool,
    acquire_lease: TickCallback,
    release_lease: TickCallback,
    materialize_prepared_agent_runs: TickCallback,
    claimable_queue_candidates: TickCallback,
    claim_queue_item: TickCallback,
    run_claimed_dispatch: TickCallback,
    fail_queue_item: TickCallback,
) -> dict[str, Any]:
    storage.ensure_layout()
    tick_id = make_id("agent_scheduler_tick", utc_now())
    owner = lease_owner or tick_id
    lease = acquire_lease(storage, lease_key="agent_scheduler", owner=owner, ttl_seconds=lease_ttl_seconds, force=force_lease)
    if not lease.get("acquired"):
        return _empty_tick(tick_id, status="skipped", reason="agent_scheduler_lease_active", lease=lease)
    materialized = materialize_prepared_agent_runs(storage, project_id=project_id, limit=limit)
    candidates = claimable_queue_candidates(storage, project_id=project_id, limit=limit)
    if dry_run:
        release = release_lease(storage, lease_key="agent_scheduler", owner=owner, last_tick=tick_id)
        result = _empty_tick(tick_id, status="completed", lease=release.get("lease", lease.get("lease", {})))
        result.update({"dry_run": True, "materialized": materialized, "candidate_count": len(candidates)})
        return result
    claimed: list[dict[str, Any]] = []
    buckets: dict[str, list[dict[str, Any]]] = {"acked": [], "waiting_human": [], "retried": [], "dead_lettered": []}
    errors: list[dict[str, Any]] = []
    for row in candidates:
        claim = claim_queue_item(storage, row["path"], owner=owner, ttl_seconds=lease_ttl_seconds)
        if not claim.get("claimed"):
            continue
        claimed.append(claim["queue"])
        try:
            result = run_claimed_dispatch(storage, claim["queue"], retry_delay_seconds=retry_delay_seconds)
            bucket_dispatch_result(result, buckets)
        except Exception as exc:
            errors.append({"queue_path": row["path"], "error": f"{type(exc).__name__}: {exc}"})
            fail_queue_item(storage, row["path"], reason=f"{type(exc).__name__}: {exc}", retry_delay_seconds=retry_delay_seconds)
    release = release_lease(storage, lease_key="agent_scheduler", owner=owner, last_tick=tick_id)
    return {
        "scheduler_tick_id": tick_id,
        "status": "failed" if errors else "completed",
        "lease": release.get("lease", lease.get("lease", {})) if isinstance(release, dict) else lease.get("lease", {}),
        "materialized": materialized,
        "candidate_count": len(candidates),
        "claimed_count": len(claimed),
        "acked_count": len(buckets["acked"]),
        "waiting_human_count": len(buckets["waiting_human"]),
        "retry_count": len(buckets["retried"]),
        "dead_letter_count": len(buckets["dead_lettered"]),
        "error_count": len(errors),
        "claimed": claimed,
        "acked": buckets["acked"],
        "waiting_human": buckets["waiting_human"],
        "retried": buckets["retried"],
        "dead_lettered": buckets["dead_lettered"],
        "errors": errors,
    }


def run_scheduler_loop(
    tick_runner: Callable[..., dict[str, Any]],
    *,
    storage: LocalStorage,
    project_id: str | None,
    limit: int,
    iterations: int,
    interval_seconds: float,
    stop_when_idle: bool,
    lease_owner: str,
    lease_ttl_seconds: int,
    force_lease: bool,
    retry_delay_seconds: int,
) -> dict[str, Any]:
    loop_id = make_id("agent_scheduler_loop", utc_now())
    ticks: list[dict[str, Any]] = []
    for index in range(max(1, int(iterations or 1))):
        tick = tick_runner(
            storage,
            project_id=project_id,
            limit=limit,
            lease_owner=lease_owner or loop_id,
            lease_ttl_seconds=lease_ttl_seconds,
            force_lease=force_lease,
            retry_delay_seconds=retry_delay_seconds,
        )
        tick["iteration"] = index + 1
        ticks.append(tick)
        if stop_when_idle and int(tick.get("candidate_count", 0) or 0) == 0:
            break
        if index + 1 < max(1, int(iterations or 1)) and interval_seconds > 0:
            time.sleep(min(float(interval_seconds), 60.0))
    errors = [item for tick in ticks for item in tick.get("errors", []) if isinstance(item, dict)]
    return {
        "scheduler_loop_id": loop_id,
        "status": "failed" if errors else "completed",
        "tick_count": len(ticks),
        "ticks": ticks,
        "latest_tick": ticks[-1] if ticks else {},
        "acked_count": sum(int(tick.get("acked_count", 0) or 0) for tick in ticks),
        "waiting_human_count": sum(int(tick.get("waiting_human_count", 0) or 0) for tick in ticks),
        "retry_count": sum(int(tick.get("retry_count", 0) or 0) for tick in ticks),
        "dead_letter_count": sum(int(tick.get("dead_letter_count", 0) or 0) for tick in ticks),
        "error_count": len(errors),
        "errors": errors,
    }


def _empty_tick(tick_id: str, *, status: str, lease: dict[str, Any], reason: str = "") -> dict[str, Any]:
    result = {
        "scheduler_tick_id": tick_id,
        "status": status,
        "lease": lease,
        "claimed": [],
        "acked": [],
        "waiting_human": [],
        "retried": [],
        "dead_lettered": [],
        "errors": [],
    }
    if reason:
        result["reason"] = reason
    return result
