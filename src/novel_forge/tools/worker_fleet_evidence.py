from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


WORKER_SCENARIOS = (
    "chapter",
    "content",
    "source",
    "mkaos",
    "book",
    "outbox",
    "maintenance",
)

REQUIRED_SCENARIO_FIELDS = frozenset(
    {
        "worker",
        "scenario",
        "commit_sha",
        "run_id",
        "project_name",
        "runtime_group",
        "worker_id",
        "work_id",
        "pre_restart_work_id",
        "recovered_work_id",
        "post_restart_work_id",
        "authoritative_side_effect",
        "cleanup",
        "attempt_or_job_id",
        "lease_id",
        "fencing_token",
        "checkpoint",
        "restart",
        "recovery",
        "stale_rejection",
        "graceful_drain",
        "zero_leaked_connections",
        "fixture",
        "real_provider_proven",
        "production_verified",
        "result",
    }
)


def validate_worker_evidence(
    evidence: Mapping[str, Any], *, expected_worker: str = "", expected_sha: str = ""
) -> dict[str, Any]:
    missing = sorted(REQUIRED_SCENARIO_FIELDS - evidence.keys())
    if missing:
        raise ValueError(f"worker evidence is missing required fields: {missing}")
    worker = str(evidence["worker"])
    if worker not in WORKER_SCENARIOS:
        raise ValueError(f"unsupported Authority worker scenario: {worker}")
    if expected_worker and worker != expected_worker:
        raise ValueError(
            f"worker evidence mismatch: expected {expected_worker}, received {worker}"
        )
    commit_sha = str(evidence["commit_sha"])
    if len(commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in commit_sha):
        raise ValueError("worker evidence commit_sha must be a full lowercase Git SHA")
    if expected_sha and commit_sha != expected_sha:
        raise ValueError("worker evidence belongs to another Git SHA")
    run_id = str(evidence["run_id"])
    project_name = str(evidence["project_name"])
    if (
        len(run_id) != 35
        or not run_id.startswith("p0-")
        or any(character not in "0123456789abcdef" for character in run_id[3:])
        or not project_name.startswith(f"nf-p0-{run_id[3:]}")
    ):
        raise ValueError("worker evidence lacks a run-scoped resource identity")
    required_truth = (
        "restart",
        "recovery",
        "stale_rejection",
        "graceful_drain",
        "zero_leaked_connections",
        "fixture",
    )
    if any(evidence[field] is not True for field in required_truth):
        raise ValueError("worker evidence does not prove restart/recovery/fencing/drain")
    if evidence["real_provider_proven"] is not False:
        raise ValueError("fixture worker evidence cannot claim a real provider")
    if evidence["production_verified"] is not False:
        raise ValueError("fixture worker evidence cannot claim production verification")
    if str(evidence["result"]) != "PASS":
        raise ValueError("worker scenario did not pass")
    for field in (
        "scenario",
        "runtime_group",
        "worker_id",
        "work_id",
        "pre_restart_work_id",
        "recovered_work_id",
        "post_restart_work_id",
        "attempt_or_job_id",
        "lease_id",
        "checkpoint",
    ):
        if not str(evidence[field]).strip():
            raise ValueError(f"worker evidence field {field} is empty")
    work_ids = {
        str(evidence["pre_restart_work_id"]),
        str(evidence["recovered_work_id"]),
        str(evidence["post_restart_work_id"]),
    }
    if len(work_ids) != 3:
        raise ValueError("worker evidence requires distinct post-restart work")
    if str(evidence["work_id"]) != str(evidence["recovered_work_id"]):
        raise ValueError("worker evidence primary work must be the recovered work")
    if evidence["authoritative_side_effect"] is not True:
        raise ValueError("worker evidence lacks a post-restart authoritative side effect")
    cleanup = evidence["cleanup"]
    if (
        not isinstance(cleanup, Mapping)
        or cleanup.get("status") != "PASS"
        or cleanup.get("remaining_resource_count") != 0
    ):
        raise ValueError("worker evidence ownership-checked cleanup is incomplete")
    if int(evidence["fencing_token"]) < 2:
        raise ValueError("worker recovery evidence requires a higher fencing token")
    return dict(evidence)


def build_worker_fleet_summary(
    scenarios: Iterable[Mapping[str, Any]], *, commit_sha: str
) -> dict[str, Any]:
    accepted: dict[str, dict[str, Any]] = {}
    for item in scenarios:
        validated = validate_worker_evidence(item, expected_sha=commit_sha)
        worker = str(validated["worker"])
        if worker in accepted:
            raise ValueError(f"duplicate worker scenario evidence: {worker}")
        accepted[worker] = validated
    missing = sorted(set(WORKER_SCENARIOS) - accepted.keys())
    extra = sorted(accepted.keys() - set(WORKER_SCENARIOS))
    if missing or extra:
        raise ValueError(
            f"worker fleet evidence set is incomplete: missing={missing}, extra={extra}"
        )
    return {
        "type": "AuthorityWorkerFleetReleaseEvidence",
        "schema_version": "authority-worker-fleet-evidence.v1",
        "commit_sha": commit_sha,
        "worker_count": len(accepted),
        "workers": [accepted[name] for name in WORKER_SCENARIOS],
        "worker_fleet_e2e_proven": True,
        "fixture": True,
        "real_provider_proven": False,
        "production_verified": False,
        "result": "PASS",
    }


__all__ = [
    "REQUIRED_SCENARIO_FIELDS",
    "WORKER_SCENARIOS",
    "build_worker_fleet_summary",
    "validate_worker_evidence",
]
