from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.curation import curated_availability

_PENDING = {
    "CREATED",
    "READY",
    "EXECUTING",
    "FAILED_RETRYABLE",
    "WAITING_EXTERNAL_RESULT",
    "RECONCILIATION_REQUIRED",
}
_FAILURE = {"FAILED_FINAL", "DEAD_LETTER"}


def analysis_job(repository: Any, sources: Any, job: dict, contract: dict) -> dict:
    payload = contract["payload"]
    revision_id = payload.get("curated_revision_id")
    frozen = (
        sources.catalog_current(
            "curated", job["project_id"], revision_id, revision=True
        )
        if revision_id
        else None
    )
    if (
        not frozen
        or frozen["workspace_id"] != job["workspace_id"]
        or frozen["manifest"].get("state") != "FROZEN"
    ):
        raise KernelError(
            "CURATED_JOB_LINEAGE_INVALID",
            "exact frozen curated revision missing or out of scope",
        )
    selected = [m for m in frozen["members"] if m["evidence"]["selected"]]
    if (
        payload.get("members") != selected
        or payload.get("requested_manifest", {}).get("revision_id") != revision_id
    ):
        raise KernelError(
            "CURATED_JOB_CONTRACT_INVALID", "frozen request and selection disagree"
        )
    purpose = frozen["manifest"].get("purpose")
    if purpose not in {
        "RESEARCH",
        "BENCHMARK",
        "MARKET_INTELLIGENCE",
        "PRODUCTION_REFERENCE",
    }:
        raise KernelError(
            "CURATED_JOB_PURPOSE_INVALID", "frozen purpose missing or invalid"
        )
    availability = curated_availability(sources, job["project_id"], frozen["members"])
    current = sources.catalog_current("curated", job["project_id"], frozen["corpus_id"])
    if (
        not current
        or current["revision_id"] != revision_id
        or current["manifest"]["state"] != "FROZEN"
    ):
        for member in availability:
            member["available"] = False
            member["reasons"].append("CURATED_SELECTION_CHANGED")
    counts = repository.job_execution_counts(job["project_id"], job["import_job_id"])
    pending = sum(r["count"] for r in counts if r["operation_status"] in _PENDING)
    failed = sum(
        r["count"]
        for r in counts
        if r["operation_status"] in _FAILURE
        or r["work_status"] in {"FAILED", "FAILED_FINAL", "FAILED_RETRYABLE", "BLOCKED"}
    )
    succeeded = sum(r["count"] for r in counts if r["operation_status"] == "SUCCEEDED")
    blocked_members = [m for m in availability if m["selected"] and not m["available"]]
    member_counts = repository.analysis_member_counts(
        job["project_id"], job["import_job_id"]
    )
    knowledge = repository.analysis_knowledge_counts(
        job["project_id"], job["import_job_id"]
    )
    if job["status"] in {"PAUSED", "CANCELLED"}:
        state = job["status"]
    elif failed:
        state = "PARTIAL" if succeeded else "FAILED"
    elif blocked_members and pending:
        state = "BLOCKED"
    elif pending:
        state = (
            "RUNNING"
            if succeeded or any(r["operation_status"] == "EXECUTING" for r in counts)
            else "QUEUED"
        )
    else:
        state = "AWAITING_GOVERNANCE" if knowledge["review_required"] else "COMPLETED"
    return {
        "job_kind": "CURATED_ANALYSIS",
        "purpose": purpose,
        "snapshot_id": None,
        "revision_id": revision_id,
        "contract_version": contract["version"],
        "frozen_request": payload["requested_manifest"],
        "frozen_budget": payload["budget"],
        **(
            {"reading_plans": payload["reading_plans"]}
            if payload.get("reading_plans")
            else {}
        ),
        "frozen_members": frozen["members"],
        "current_availability": availability,
        "members": [
            {
                **m,
                "stages": member_counts.get(m["processing_id"], []),
                "expansion": "EXPANDED"
                if member_counts.get(m["processing_id"])
                else "NOT_STARTED"
                if m["evidence"]["selected"]
                else "NOT_SELECTED",
            }
            for m in frozen["members"]
        ],
        "leased_stages": repository.job_active_leases(
            job["project_id"], job["import_job_id"]
        ),
        "selected_members": len(selected),
        "unselected_members": len(frozen["members"]) - len(selected),
        "content_imported": 0,
        "analysis_state": state,
        "execution_counts": counts,
        "remaining_stages": pending,
        "failed_stages": failed,
        "expanded_stages": sum(r["count"] for r in counts),
        "final_stage_denominator": None if pending else sum(r["count"] for r in counts),
        "knowledge": knowledge,
        "knowledge_approved_by_import": False,
        "budget": repository.analysis_budget(job["project_id"], job["import_job_id"]),
        "next_action": "RESUME"
        if state == "PAUSED"
        else "REVIEW_BLOCKERS"
        if failed or blocked_members
        else "RUN_OR_RECONCILE"
        if pending
        else "REVIEW_KNOWLEDGE"
        if knowledge["review_required"]
        else "NONE",
    }
