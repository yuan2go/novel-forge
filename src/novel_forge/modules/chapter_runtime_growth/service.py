from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.audit_log import record_audit_event
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.permission_center import create_approval_request, list_approval_requests
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.modules.runtime_project_scope import asset_matches_project_scope
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

CONTRACT = "chapter-runtime-growth-profile-v1"
SNAPSHOT_KIND = "chapter_runtime_growth_profile"
HOTSPOT_LEDGER_CONTRACT = "chapter-runtime-growth-hotspot-ledger-v1"
HOTSPOT_LEDGER_SNAPSHOT_KIND = "chapter_runtime_growth_hotspot_ledger"
WRITE_POLICY_PLAN_CONTRACT = "chapter-runtime-growth-write-policy-candidate-plan-v1"
WRITE_POLICY_PLAN_SNAPSHOT_KIND = "chapter_runtime_growth_write_policy_candidate_plan"
APPROVED_APPLY_PLAN_CONTRACT = "chapter-runtime-growth-approved-policy-apply-plan-v1"
APPROVED_APPLY_PLAN_SNAPSHOT_KIND = "chapter_runtime_growth_approved_policy_apply_plan"
APPLIED_POLICY_CONTRACT = "chapter-runtime-growth-approved-policy-apply-v1"
APPLIED_POLICY_SNAPSHOT_KIND = "chapter_runtime_growth_applied_policy"
POLICY_ROLLBACK_CONTRACT = "chapter-runtime-growth-policy-rollback-v1"
POLICY_ROLLBACK_SNAPSHOT_KIND = "chapter_runtime_growth_policy_rollback"
THRESHOLD_GATE_KIND = "chapter_runtime_growth_threshold"
THRESHOLD_GATE_CONTRACT = "chapter-runtime-growth-threshold-gate-v1"
WRITE_BUDGET_GATE_KIND = "chapter_runtime_growth_write_budget"
WRITE_BUDGET_GATE_CONTRACT = "chapter-runtime-growth-write-budget-gate-v1"
HIGH_REF_THRESHOLD = 120
DEFAULT_WRITE_BUDGETS = {
    "max_linked_asset_refs_per_run": 120,
    "max_task_status_refs_per_run": 60,
    "max_step_output_refs_per_run": 60,
    "max_node_runs_per_run": 20,
    "max_trace_spans_per_run": 20,
    "max_repeated_asset_type_total": 50,
}


def build_chapter_runtime_growth_profile(storage: LocalStorage, *, project_id: str = "", persist: bool = True) -> dict[str, Any]:
    storage.ensure_layout()
    runs = _chapter_run_rows(storage, project_id=project_id)
    runtime_rows = [_runtime_row(storage, run) for run in runs]
    high_growth = [row for row in runtime_rows if row["risk_level"] in {"high", "critical"}]
    missing_policy_count = sum(1 for row in runtime_rows if row["runtime_artifact_policy_status"] == "missing")
    full_run_count = sum(1 for row in runtime_rows if row["task_status_mode"] == "full")
    status = "missing" if not runtime_rows else "review_required" if high_growth or missing_policy_count or full_run_count else "passed"
    summary = _summary(runtime_rows)
    content = {
        "snapshot_kind": SNAPSHOT_KIND,
        "contract": CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {
            "chapter_run_count": len(runtime_rows),
            "chapter_count": len({row["chapter"] for row in runtime_rows if row["chapter"]}),
            "compact_run_count": sum(1 for row in runtime_rows if row["task_status_mode"] == "compact"),
            "full_run_count": full_run_count,
        },
        "quality": {
            "runtime_growth_status": status,
            "high_growth_run_count": len(high_growth),
            "missing_runtime_policy_count": missing_policy_count,
            "max_linked_asset_ref_count": summary["max_linked_asset_ref_count"],
            "average_linked_asset_ref_count": summary["average_linked_asset_ref_count"],
        },
        "task_health": {
            "blocking_drift_count": 0,
            "review_required_count": len(high_growth) + missing_policy_count + full_run_count,
            "estimated_compacted_write_savings": summary["estimated_compacted_write_savings"],
        },
        "agent_health": {
            "chapter_runtime_profiler": status,
            "chapter_run_count": len(runtime_rows),
            "node_run_count": sum(int(row.get("node_run_count") or 0) for row in runtime_rows),
            "trace_span_count": sum(int(row.get("trace_span_count") or 0) for row in runtime_rows),
        },
        "storage_health": {
            "referenced_asset_type_counts": summary["referenced_asset_type_counts"],
            "repeated_asset_type_counts": summary["repeated_asset_type_counts"],
        },
        "runtime_rows": runtime_rows[:50],
        "evidence_paths": _dedupe([row["path"] for row in runtime_rows]),
        "recommendations": _recommendations(status, runtime_rows),
        "operator_action": _operator_action(status),
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth profile {project_id or 'all-projects'}",
        tags=["chapter-runtime-growth", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    return {
        "status": status,
        "path": _display_path(storage.root, path) if path else "",
        "asset": asset.to_dict(),
        "summary": summary,
        "runtime_rows": runtime_rows,
    }


def build_chapter_runtime_growth_hotspot_ledger(
    storage: LocalStorage,
    *,
    project_id: str = "",
    persist: bool = True,
    top_n: int = 10,
) -> dict[str, Any]:
    """Write a read-only hotspot ledger over existing chapter runtime evidence."""

    storage.ensure_layout()
    limit = max(1, int(top_n or 10))
    profile = build_chapter_runtime_growth_profile(storage, project_id=project_id, persist=False)
    runtime_rows = profile.get("runtime_rows", []) if isinstance(profile.get("runtime_rows", []), list) else []
    hotspot_rows = _artifact_hotspot_rows(runtime_rows, limit=limit)
    run_hotspot_rows = _run_hotspot_rows(runtime_rows, limit=limit)
    acceptance_report_rows = _acceptance_report_hotspot_rows(storage, project_id=project_id, limit=limit)
    status = _hotspot_status(runtime_rows, hotspot_rows)
    summary = {
        "chapter_run_count": len(runtime_rows),
        "hotspot_family_count": len(hotspot_rows),
        "high_risk_hotspot_count": sum(1 for row in hotspot_rows if row.get("risk_level") in {"high", "critical"}),
        "max_linked_asset_ref_count": int(profile.get("summary", {}).get("max_linked_asset_ref_count") or 0)
        if isinstance(profile.get("summary", {}), dict)
        else 0,
        "average_linked_asset_ref_count": float(profile.get("summary", {}).get("average_linked_asset_ref_count") or 0.0)
        if isinstance(profile.get("summary", {}), dict)
        else 0.0,
        "estimated_compacted_write_savings": int(profile.get("summary", {}).get("estimated_compacted_write_savings") or 0)
        if isinstance(profile.get("summary", {}), dict)
        else 0,
        "read_only": True,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
        "mutation_applied": False,
    }
    content = {
        "snapshot_kind": HOTSPOT_LEDGER_SNAPSHOT_KIND,
        "contract": HOTSPOT_LEDGER_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {
            "chapter_run_count": len(runtime_rows),
            "hotspot_family_count": len(hotspot_rows),
            "run_hotspot_count": len(run_hotspot_rows),
            "acceptance_report_hotspot_count": len(acceptance_report_rows),
        },
        "quality": {
            "runtime_growth_hotspot_status": status,
            "high_risk_hotspot_count": summary["high_risk_hotspot_count"],
            "max_linked_asset_ref_count": summary["max_linked_asset_ref_count"],
            "hotspot_family_count": summary["hotspot_family_count"],
        },
        "task_health": {
            "review_required_count": 1 if status == "review_required" else 0,
            "estimated_compacted_write_savings": summary["estimated_compacted_write_savings"],
            "mutation_applied": False,
        },
        "agent_health": {
            "chapter_runtime_hotspot_ledger": status,
            "chapter_production_executed": False,
            "provider_proof_executed": False,
        },
        "storage_health": {
            "artifact_hotspot_families": [str(row.get("artifact_family") or "") for row in hotspot_rows],
            "top_hotspot_count": int(hotspot_rows[0].get("total_count") or 0) if hotspot_rows else 0,
            "read_only": True,
        },
        "hotspot_rows": hotspot_rows,
        "run_hotspot_rows": run_hotspot_rows,
        "acceptance_report_hotspot_rows": acceptance_report_rows,
        "evidence_paths": _dedupe(
            [
                *[str(row.get("path") or "") for row in runtime_rows if isinstance(row, dict)],
                *[str(row.get("path") or "") for row in acceptance_report_rows if isinstance(row, dict)],
            ]
        ),
        "recommendations": _hotspot_recommendations(status, hotspot_rows),
        "operator_action": _hotspot_operator_action(status),
        "mutation_policy": "read-only: identify artifact hotspots before changing runtime write policies",
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth hotspot ledger {project_id or 'all-projects'}",
        tags=["chapter-runtime-growth-hotspot", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": HOTSPOT_LEDGER_SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    return {
        "status": status,
        "path": _display_path(storage.root, path) if path else "",
        "asset": asset.to_dict(),
        "summary": summary,
        "hotspot_rows": hotspot_rows,
        "run_hotspot_rows": run_hotspot_rows,
    }


def build_chapter_runtime_growth_write_policy_candidate_plan(
    storage: LocalStorage,
    *,
    project_id: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Write a reviewable, no-mutation candidate plan from runtime hotspot evidence."""

    storage.ensure_layout()
    hotspot = build_chapter_runtime_growth_hotspot_ledger(storage, project_id=project_id, persist=False)
    hotspot_asset = hotspot.get("asset", {}) if isinstance(hotspot.get("asset", {}), dict) else {}
    hotspot_content = hotspot_asset.get("content", {}) if isinstance(hotspot_asset.get("content", {}), dict) else {}
    hotspot_rows = hotspot_content.get("hotspot_rows", []) if isinstance(hotspot_content.get("hotspot_rows", []), list) else []
    candidate_actions = _write_policy_candidate_actions(hotspot_rows)
    status = "missing" if str(hotspot.get("status") or "") == "missing" else "review_required" if candidate_actions else "passed"
    estimated_savings = _estimated_candidate_savings(hotspot_content, candidate_actions)
    summary = {
        "hotspot_status": str(hotspot.get("status") or "missing"),
        "candidate_action_count": len(candidate_actions),
        "estimated_compacted_write_savings": estimated_savings,
        "requires_operator_review": bool(candidate_actions),
        "mutation_applied": False,
        "runtime_policy_changed": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    content = {
        "snapshot_kind": WRITE_POLICY_PLAN_SNAPSHOT_KIND,
        "contract": WRITE_POLICY_PLAN_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {
            "candidate_action_count": len(candidate_actions),
            "hotspot_family_count": int(hotspot_content.get("summary", {}).get("hotspot_family_count") or 0)
            if isinstance(hotspot_content.get("summary", {}), dict)
            else 0,
        },
        "quality": {
            "write_policy_candidate_status": status,
            "requires_operator_review": bool(candidate_actions),
            "unsafe_to_apply_automatically": True,
        },
        "task_health": {
            "review_required_count": 1 if status == "review_required" else 0,
            "mutation_applied": False,
            "runtime_policy_changed": False,
        },
        "agent_health": {
            "chapter_runtime_write_policy_plan": status,
            "chapter_production_executed": False,
            "provider_proof_executed": False,
        },
        "storage_health": {
            "candidate_artifact_families": [str(row.get("artifact_family") or "") for row in candidate_actions],
            "hotspot_evidence_path": str(hotspot.get("path") or ""),
            "read_only": True,
        },
        "candidate_actions": candidate_actions,
        "safeguards": _write_policy_safeguards(),
        "rollback_criteria": _write_policy_rollback_criteria(),
        "recommendations": _write_policy_recommendations(status, candidate_actions),
        "evidence_paths": _dedupe(
            [
                str(hotspot.get("path") or ""),
                *[
                    str(path)
                    for row in hotspot_content.get("run_hotspot_rows", [])
                    if isinstance(row, dict)
                    for path in [row.get("path")]
                    if str(path or "").strip()
                ],
            ]
        ),
        "operator_action": _write_policy_operator_action(status),
        "mutation_policy": "read-only: candidate plan only; requires approval before runtime policy changes",
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth write-policy candidate plan {project_id or 'all-projects'}",
        tags=["chapter-runtime-write-policy-plan", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": WRITE_POLICY_PLAN_SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    return {
        "status": status,
        "path": _display_path(storage.root, path) if path else "",
        "asset": asset.to_dict(),
        "summary": summary,
        "candidate_actions": candidate_actions,
    }


def request_chapter_runtime_growth_write_policy_approval(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "production",
) -> dict[str, Any]:
    """Create or reuse an ApprovalRequest for a runtime write-policy candidate plan."""

    storage.ensure_layout()
    plan = build_chapter_runtime_growth_write_policy_candidate_plan(storage, project_id=project_id, persist=True)
    plan_path = str(plan.get("path") or "")
    if str(plan.get("status") or "") == "missing" or not plan_path:
        return {
            "status": "missing",
            "message": "runtime write-policy candidate plan is missing",
            "plan": plan,
            "approval_request_path": "",
            "approval_created": False,
            "mutation_applied": False,
            "runtime_policy_changed": False,
        }
    existing = _existing_write_policy_approval(storage, project_id=project_id, plan_path=plan_path)
    if existing:
        content = existing.get("content", {}) if isinstance(existing.get("content", {}), dict) else {}
        return {
            "status": str(content.get("status") or "unknown"),
            "message": "runtime write-policy candidate plan already has ApprovalRequest evidence",
            "plan": plan,
            "approval_request_path": str(existing.get("path") or ""),
            "approval_request": existing,
            "approval_created": False,
            "mutation_applied": False,
            "runtime_policy_changed": False,
        }
    approval = create_approval_request(
        storage,
        {
            "project_id": project_id,
            "scope": "agent",
            "action": "approve_runtime_write_policy_candidate_plan",
            "risk_level": "high",
            "environment": environment,
            "target_type": "project_metric_snapshot",
            "target_id": str(plan.get("asset", {}).get("id") or ""),
            "target_path": plan_path,
            "target_refs": [plan_path],
            "evidence_refs": [plan_path],
            "required_before": ["runtime_policy_update", "chapter_sequence_growth_reduction", "final_v1_acceptance"],
            "reason": "Runtime write-policy candidate plan must be approved before any write-policy apply path.",
            "rollback_plan": {
                "strategy": "do not apply policy automatically; if a later apply slice fails, restore previous runtime policy and rerun focused regression",
                "required_evidence": ["approval_request", "runtime_growth_regression", "cockpit_visibility"],
            },
        },
    )
    return {
        "status": "pending",
        "message": "runtime write-policy candidate plan approval requested",
        "plan": plan,
        "approval_request_path": approval["path"],
        "approval_request": approval["asset"],
        "approval_created": True,
        "mutation_applied": False,
        "runtime_policy_changed": False,
    }


def build_chapter_runtime_growth_approved_policy_apply_plan(
    storage: LocalStorage,
    *,
    project_id: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Write a no-execution apply plan that requires approved ApprovalRequest evidence."""

    storage.ensure_layout()
    plan_asset = _latest_write_policy_candidate_plan(storage, project_id=project_id)
    if not plan_asset:
        generated = build_chapter_runtime_growth_write_policy_candidate_plan(storage, project_id=project_id, persist=True)
        plan_asset = generated.get("asset", {}) if isinstance(generated.get("asset", {}), dict) else {}
        plan_asset["path"] = str(generated.get("path") or "")
    plan_content = plan_asset.get("content", {}) if isinstance(plan_asset.get("content", {}), dict) else {}
    plan_path = str(plan_asset.get("path") or "")
    approval = _approved_write_policy_approval(storage, project_id=project_id, plan_path=plan_path)
    candidate_actions = plan_content.get("candidate_actions", []) if isinstance(plan_content.get("candidate_actions", []), list) else []
    policy_deltas = _policy_deltas_from_candidate_actions(candidate_actions)
    approved = bool(approval)
    status = "ready" if approved and policy_deltas else "review_required" if candidate_actions else "missing"
    summary = {
        "candidate_plan_path": plan_path,
        "approval_request_path": str(approval.get("path") or ""),
        "approved": approved,
        "apply_allowed": approved and bool(policy_deltas),
        "policy_delta_count": len(policy_deltas),
        "mutation_applied": False,
        "runtime_policy_changed": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    content = {
        "snapshot_kind": APPROVED_APPLY_PLAN_SNAPSHOT_KIND,
        "contract": APPROVED_APPLY_PLAN_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {"policy_delta_count": len(policy_deltas), "candidate_action_count": len(candidate_actions)},
        "quality": {
            "approved_apply_plan_status": status,
            "approved": approved,
            "apply_allowed": approved and bool(policy_deltas),
            "unsafe_to_apply_automatically": True,
        },
        "task_health": {"review_required_count": 0 if status == "ready" else 1, "mutation_applied": False, "runtime_policy_changed": False},
        "agent_health": {"runtime_write_policy_apply_plan": status, "chapter_production_executed": False, "provider_proof_executed": False},
        "storage_health": {"candidate_plan_path": plan_path, "approval_request_path": str(approval.get("path") or ""), "read_only": True},
        "policy_deltas": policy_deltas,
        "blocked_reason": "" if approved else "runtime write-policy ApprovalRequest is not approved",
        "required_regression_gates": ["runtime-growth-regression", "chapter-production-compact-failure-preservation"],
        "rollback_criteria": _write_policy_rollback_criteria(),
        "evidence_paths": _dedupe([plan_path, str(approval.get("path") or "")]),
        "operator_action": _approved_apply_operator_action(status),
        "mutation_policy": "read-only: describes approved apply deltas but does not change runtime policy",
        "recommendations": _approved_apply_recommendations(status),
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth approved apply plan {project_id or 'all-projects'}",
        tags=["chapter-runtime-approved-apply-plan", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": APPROVED_APPLY_PLAN_SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    return {"status": status, "path": _display_path(storage.root, path) if path else "", "asset": asset.to_dict(), "summary": summary}


def apply_chapter_runtime_growth_approved_policy_plan(
    storage: LocalStorage,
    *,
    project_id: str = "",
    apply_plan_path: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Apply an approved runtime write-policy plan as forward-only policy evidence.

    This is intentionally not a retroactive rewrite of chapter_production_run
    artifacts. The active policy change is represented by a new
    ProjectMetricSnapshot that future runners can consume.
    """

    storage.ensure_layout()
    apply_plan = _resolve_or_latest_approved_apply_plan(storage, project_id=project_id, apply_plan_path=apply_plan_path)
    plan_content = apply_plan.get("content", {}) if isinstance(apply_plan.get("content", {}), dict) else {}
    plan_summary = plan_content.get("summary", {}) if isinstance(plan_content.get("summary", {}), dict) else {}
    policy_deltas = plan_content.get("policy_deltas", []) if isinstance(plan_content.get("policy_deltas", []), list) else []
    allowed = (
        str(plan_content.get("snapshot_kind") or "") == APPROVED_APPLY_PLAN_SNAPSHOT_KIND
        and str(plan_content.get("status") or "") == "ready"
        and bool(plan_summary.get("approved", False))
        and bool(plan_summary.get("apply_allowed", False))
        and bool(policy_deltas)
    )
    previous_snapshot = _latest_project_metric_snapshot(storage, APPLIED_POLICY_SNAPSHOT_KIND, project_id=project_id)
    before_policy = _active_runtime_write_policy(previous_snapshot)
    after_policy = _deep_merge_runtime_policy(before_policy, policy_deltas) if allowed else before_policy
    plan_path = str(apply_plan.get("path") or "")
    status = "applied" if allowed else "blocked"
    blocked_reason = "" if allowed else _policy_apply_blocked_reason(plan_content, plan_summary, policy_deltas)
    summary = {
        "apply_plan_path": plan_path,
        "approval_request_path": str(plan_summary.get("approval_request_path") or ""),
        "approved": bool(plan_summary.get("approved", False)),
        "apply_allowed": bool(plan_summary.get("apply_allowed", False)),
        "policy_delta_count": len(policy_deltas),
        "mutation_applied": allowed,
        "runtime_policy_changed": allowed,
        "existing_run_artifacts_mutated": False,
        "retroactive_artifact_mutation": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    content = {
        "snapshot_kind": APPLIED_POLICY_SNAPSHOT_KIND,
        "contract": APPLIED_POLICY_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {"policy_delta_count": len(policy_deltas), "applied_policy_snapshot_count": 1 if allowed else 0},
        "quality": {
            "applied_policy_status": status,
            "approved": summary["approved"],
            "apply_allowed": summary["apply_allowed"],
            "failure_evidence_preserved": True,
            "gate_budget_provider_approval_evidence_preserved": True,
        },
        "task_health": {
            "review_required_count": 0 if allowed else 1,
            "mutation_applied": allowed,
            "runtime_policy_changed": allowed,
            "existing_run_artifacts_mutated": False,
        },
        "agent_health": {
            "runtime_write_policy_apply": status,
            "chapter_production_executed": False,
            "provider_proof_executed": False,
            "dead_letter_evidence_preserved": True,
        },
        "storage_health": {
            "active_policy_source": "forward_only_project_metric_snapshot" if allowed else "unchanged",
            "previous_applied_policy_path": str(previous_snapshot.get("path") or ""),
            "apply_plan_path": plan_path,
            "existing_run_artifacts_mutated": False,
        },
        "before_policy": before_policy,
        "policy_deltas": policy_deltas,
        "after_policy": after_policy,
        "safeguards_preserved": {
            "failed_task_status": True,
            "failed_node_run": True,
            "failed_trace_span": True,
            "gate_result": True,
            "budget_policy": True,
            "provider_runtime_guard": True,
            "approval_request": True,
            "dead_letter": True,
        },
        "rollback_plan": {
            "strategy": "write forward-only rollback snapshot restoring previous runtime write-policy evidence",
            "previous_policy": before_policy,
            "policy_to_rollback": after_policy,
            "apply_snapshot_path": "",
            "required_evidence": ["applied_policy_snapshot", "audit_log", "runtime-growth-regression"],
        },
        "blocked_reason": blocked_reason,
        "required_regression_gates": ["runtime-growth-regression", "chapter-production-compact-failure-preservation"],
        "evidence_paths": _dedupe([plan_path, str(plan_summary.get("approval_request_path") or ""), str(previous_snapshot.get("path") or "")]),
        "audit_event_path": "",
        "operator_action": _policy_apply_operator_action(status),
        "mutation_policy": "forward-only runtime write-policy evidence; does not mutate historical chapter run artifacts",
        "recommendations": _policy_apply_recommendations(status),
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth applied policy {project_id or 'all-projects'}",
        tags=["chapter-runtime-applied-policy", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": APPLIED_POLICY_SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    display_path = _display_path(storage.root, path) if path else ""
    audit_path = ""
    asset_dict = asset.to_dict()
    if persist and path:
        audit = record_audit_event(
            storage,
            event_type="runtime_policy",
            action="apply_chapter_runtime_growth_write_policy",
            project_id=project_id,
            trace_id=f"runtime-policy-apply:{project_id or 'global'}",
            target={"type": "project_metric_snapshot", "snapshot_kind": APPLIED_POLICY_SNAPSHOT_KIND, "path": display_path},
            input_refs=[plan_path],
            output_refs=[display_path],
            evidence_refs=content["evidence_paths"],
            status="succeeded" if allowed else "blocked",
            blocking=not allowed,
            rollback_ref="",
            metadata={"contract": APPLIED_POLICY_CONTRACT, "blocked_reason": blocked_reason},
        )
        audit_path = str(audit.get("path") or "")
        persisted = storage.read_json(path)
        persisted_content = persisted.get("content", {}) if isinstance(persisted.get("content", {}), dict) else {}
        persisted_content["audit_event_path"] = audit_path
        persisted_content["evidence_paths"] = _dedupe([*content["evidence_paths"], audit_path])
        if isinstance(persisted_content.get("rollback_plan", {}), dict):
            persisted_content["rollback_plan"]["apply_snapshot_path"] = display_path
        persisted["content"] = persisted_content
        storage.write_json(path, persisted)
        asset_dict = persisted
    return {
        "status": status,
        "path": display_path,
        "asset": asset_dict,
        "summary": summary,
        "audit_event_path": audit_path,
        "mutation_applied": allowed,
        "runtime_policy_changed": allowed,
        "blocked_reason": blocked_reason,
    }


def rollback_chapter_runtime_growth_applied_policy(
    storage: LocalStorage,
    *,
    project_id: str = "",
    applied_policy_path: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Write rollback evidence for an applied runtime write-policy snapshot."""

    storage.ensure_layout()
    applied = _resolve_or_latest_applied_policy(storage, project_id=project_id, applied_policy_path=applied_policy_path)
    applied_content = applied.get("content", {}) if isinstance(applied.get("content", {}), dict) else {}
    rollback_plan = applied_content.get("rollback_plan", {}) if isinstance(applied_content.get("rollback_plan", {}), dict) else {}
    allowed = str(applied_content.get("snapshot_kind") or "") == APPLIED_POLICY_SNAPSHOT_KIND and str(applied_content.get("status") or "") == "applied"
    restored_policy = rollback_plan.get("previous_policy") if isinstance(rollback_plan.get("previous_policy"), dict) else _default_runtime_write_policy()
    policy_to_rollback = rollback_plan.get("policy_to_rollback") if isinstance(rollback_plan.get("policy_to_rollback"), dict) else applied_content.get("after_policy", {})
    applied_path = str(applied.get("path") or "")
    status = "rolled_back" if allowed else "blocked"
    blocked_reason = "" if allowed else "no applied runtime write-policy snapshot is available for rollback"
    summary = {
        "applied_policy_path": applied_path,
        "rollback_allowed": allowed,
        "rollback_applied": allowed,
        "mutation_applied": allowed,
        "runtime_policy_changed": allowed,
        "existing_run_artifacts_mutated": False,
        "retroactive_artifact_mutation": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    content = {
        "snapshot_kind": POLICY_ROLLBACK_SNAPSHOT_KIND,
        "contract": POLICY_ROLLBACK_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "summary": summary,
        "throughput": {"rolled_back_policy_snapshot_count": 1 if allowed else 0},
        "quality": {
            "rollback_status": status,
            "failure_evidence_preserved": True,
            "gate_budget_provider_approval_evidence_preserved": True,
        },
        "task_health": {
            "review_required_count": 0 if allowed else 1,
            "mutation_applied": allowed,
            "runtime_policy_changed": allowed,
            "existing_run_artifacts_mutated": False,
        },
        "agent_health": {
            "runtime_write_policy_rollback": status,
            "chapter_production_executed": False,
            "provider_proof_executed": False,
        },
        "storage_health": {
            "active_policy_source": "forward_only_rollback_snapshot" if allowed else "unchanged",
            "applied_policy_path": applied_path,
            "existing_run_artifacts_mutated": False,
        },
        "policy_to_rollback": policy_to_rollback,
        "restored_policy": restored_policy,
        "blocked_reason": blocked_reason,
        "evidence_paths": _dedupe([applied_path, str(applied_content.get("audit_event_path") or "")]),
        "audit_event_path": "",
        "operator_action": _policy_rollback_operator_action(status),
        "mutation_policy": "forward-only rollback evidence; does not mutate historical chapter run artifacts",
        "recommendations": _policy_rollback_recommendations(status),
    }
    asset = ProjectMetricSnapshot(
        title=f"Chapter runtime growth policy rollback {project_id or 'all-projects'}",
        tags=["chapter-runtime-policy-rollback", status],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": POLICY_ROLLBACK_SNAPSHOT_KIND, "asset_status": status},
    )
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset) if persist else None
    display_path = _display_path(storage.root, path) if path else ""
    audit_path = ""
    asset_dict = asset.to_dict()
    if persist and path:
        audit = record_audit_event(
            storage,
            event_type="runtime_policy",
            action="rollback_chapter_runtime_growth_write_policy",
            project_id=project_id,
            trace_id=f"runtime-policy-rollback:{project_id or 'global'}",
            target={"type": "project_metric_snapshot", "snapshot_kind": POLICY_ROLLBACK_SNAPSHOT_KIND, "path": display_path},
            input_refs=[applied_path],
            output_refs=[display_path],
            evidence_refs=content["evidence_paths"],
            status="succeeded" if allowed else "blocked",
            blocking=not allowed,
            rollback_ref=applied_path,
            metadata={"contract": POLICY_ROLLBACK_CONTRACT, "blocked_reason": blocked_reason},
        )
        audit_path = str(audit.get("path") or "")
        persisted = storage.read_json(path)
        persisted_content = persisted.get("content", {}) if isinstance(persisted.get("content", {}), dict) else {}
        persisted_content["audit_event_path"] = audit_path
        persisted_content["evidence_paths"] = _dedupe([*content["evidence_paths"], audit_path])
        persisted["content"] = persisted_content
        storage.write_json(path, persisted)
        asset_dict = persisted
    return {
        "status": status,
        "path": display_path,
        "asset": asset_dict,
        "summary": summary,
        "audit_event_path": audit_path,
        "rollback_applied": allowed,
        "runtime_policy_changed": allowed,
        "blocked_reason": blocked_reason,
    }


def run_chapter_runtime_growth_threshold_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "",
    max_linked_asset_refs: int = HIGH_REF_THRESHOLD,
    allow_full_mode: bool = False,
    persist_profile: bool = True,
) -> dict[str, Any]:
    """Write a read-only gate over existing chapter runtime-growth evidence."""

    storage.ensure_layout()
    threshold = max(1, int(max_linked_asset_refs or HIGH_REF_THRESHOLD))
    profile = build_chapter_runtime_growth_profile(storage, project_id=project_id, persist=persist_profile)
    profile_content = profile.get("asset", {}).get("content", {}) if isinstance(profile.get("asset", {}), dict) else {}
    profile_status = str(profile.get("status") or profile_content.get("status") or "missing")
    runtime_rows = profile.get("runtime_rows", []) if isinstance(profile.get("runtime_rows", []), list) else []
    applied_policy = _latest_project_metric_snapshot(storage, APPLIED_POLICY_SNAPSHOT_KIND, project_id=project_id)
    applied_policy_path = str(applied_policy.get("path") or "")
    applied_policy_recorded_at = str(applied_policy.get("updated_at") or applied_policy.get("created_at") or "")
    blockers = _threshold_blocking_rows(
        profile_status=profile_status,
        runtime_rows=runtime_rows,
        max_linked_asset_refs=threshold,
        allow_full_mode=allow_full_mode,
        applied_policy_path=applied_policy_path,
        applied_policy_recorded_at=applied_policy_recorded_at,
    )
    production = is_production_environment(environment)
    status = "failed" if production and blockers else "warning" if blockers else "passed"
    message = (
        f"chapter runtime growth threshold gate has {len(blockers)} blocking row(s)"
        if blockers
        else "chapter runtime growth threshold gate passed"
    )
    profile_path = str(profile.get("path") or "")
    evidence_paths = _dedupe([profile_path, applied_policy_path, *[str(row.get("path") or "") for row in runtime_rows], *[str(row.get("path") or "") for row in blockers]])
    summary = {
        "profile_status": profile_status,
        "chapter_run_count": int(profile.get("summary", {}).get("chapter_run_count") or 0) if isinstance(profile.get("summary", {}), dict) else 0,
        "blocking_count": len(blockers),
        "max_linked_asset_refs_threshold": threshold,
        "allow_full_mode": allow_full_mode,
        "latest_applied_policy_path": applied_policy_path,
        "latest_applied_policy_recorded_at": applied_policy_recorded_at,
        "applied_policy_consumed_run_count": sum(1 for row in runtime_rows if _runtime_row_consumed_applied_policy(row, applied_policy_path)),
        "production": production,
        "mutation_applied": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    gate = record_gate_result(
        storage,
        gate_kind=THRESHOLD_GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": THRESHOLD_GATE_CONTRACT,
            "project_id": project_id,
            "environment": environment,
            "thresholds": {
                "max_linked_asset_refs": threshold,
                "allow_full_mode": allow_full_mode,
            },
            "summary": summary,
            "blocking_rows": blockers,
            "profile_path": profile_path,
            "operator_action": _threshold_operator_action(blockers),
            "mutation_policy": "read-only: no chapter production, acceptance, provider proof, or run mutation",
        },
        project_id=project_id,
        message=message,
        blocking=production and bool(blockers),
    )
    return {
        "status": status,
        "production": production,
        "blocking": production and bool(blockers),
        "message": message,
        "summary": summary,
        "blocking_rows": blockers,
        "profile": profile,
        "gate_result": gate,
        "gate_result_path": str(gate.get("path") or ""),
    }


def run_chapter_runtime_growth_write_budget_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "",
    budgets: dict[str, Any] | None = None,
    persist_profile: bool = True,
) -> dict[str, Any]:
    """Write a read-only gate over chapter runtime write-amplification budgets."""

    storage.ensure_layout()
    profile = build_chapter_runtime_growth_profile(storage, project_id=project_id, persist=persist_profile)
    profile_content = profile.get("asset", {}).get("content", {}) if isinstance(profile.get("asset", {}), dict) else {}
    profile_status = str(profile.get("status") or profile_content.get("status") or "missing")
    runtime_rows = profile.get("runtime_rows", []) if isinstance(profile.get("runtime_rows", []), list) else []
    profile_summary = profile.get("summary", {}) if isinstance(profile.get("summary", {}), dict) else {}
    normalized_budgets = _normalize_write_budgets(budgets, chapter_run_count=len(runtime_rows))
    blockers = _write_budget_blocking_rows(
        profile_status=profile_status,
        runtime_rows=runtime_rows,
        profile_summary=profile_summary,
        budgets=normalized_budgets,
    )
    production = is_production_environment(environment)
    status = "failed" if production and blockers else "warning" if blockers else "passed"
    message = (
        f"chapter runtime write budget gate has {len(blockers)} blocking row(s)"
        if blockers
        else "chapter runtime write budget gate passed"
    )
    profile_path = str(profile.get("path") or "")
    evidence_paths = _dedupe([profile_path, *[str(row.get("path") or "") for row in runtime_rows], *[str(row.get("path") or "") for row in blockers]])
    summary = {
        "profile_status": profile_status,
        "chapter_run_count": len(runtime_rows),
        "blocking_count": len(blockers),
        "budgets": normalized_budgets,
        "max_linked_asset_ref_count": int(profile_summary.get("max_linked_asset_ref_count") or 0),
        "max_task_status_ref_count": max((int(row.get("task_status_ref_count") or 0) for row in runtime_rows), default=0),
        "max_step_output_ref_count": max((int(row.get("step_output_ref_count") or 0) for row in runtime_rows), default=0),
        "max_node_run_count": max((int(row.get("node_run_count") or 0) for row in runtime_rows), default=0),
        "max_trace_span_count": max((int(row.get("trace_span_count") or 0) for row in runtime_rows), default=0),
        "repeated_asset_type_counts": profile_summary.get("repeated_asset_type_counts", {}),
        "production": production,
        "mutation_applied": False,
        "chapter_production_executed": False,
        "provider_proof_executed": False,
    }
    gate = record_gate_result(
        storage,
        gate_kind=WRITE_BUDGET_GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": WRITE_BUDGET_GATE_CONTRACT,
            "project_id": project_id,
            "environment": environment,
            "summary": summary,
            "blocking_rows": blockers,
            "profile_path": profile_path,
            "operator_action": _write_budget_operator_action(blockers),
            "mutation_policy": "read-only: no chapter production, acceptance, provider proof, compaction, or artifact deletion",
        },
        project_id=project_id,
        message=message,
        blocking=production and bool(blockers),
    )
    return {
        "status": status,
        "production": production,
        "blocking": production and bool(blockers),
        "message": message,
        "summary": summary,
        "blocking_rows": blockers,
        "profile": profile,
        "gate_result": gate,
        "gate_result_path": str(gate.get("path") or ""),
    }


def _chapter_run_rows(storage: LocalStorage, *, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "chapter_production_run":
            continue
        if project_id and not asset_matches_project_scope(storage, data, project_id):
            continue
        data["_path"] = _display_path(storage.root, path)
        rows.append(data)
    return sorted(rows, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))


def _runtime_row(storage: LocalStorage, run: dict[str, Any]) -> dict[str, Any]:
    content = run.get("content", {}) if isinstance(run.get("content", {}), dict) else {}
    control = content.get("control", {}) if isinstance(content.get("control", {}), dict) else {}
    policy = control.get("runtime_artifact_policy", {}) if isinstance(control.get("runtime_artifact_policy", {}), dict) else {}
    steps = _steps(content.get("steps", {}))
    outputs = content.get("outputs", {}) if isinstance(content.get("outputs", {}), dict) else {}
    output_refs = [str(value) for value in outputs.values() if str(value or "").strip()]
    task_status_refs = _step_refs(steps, "task_status_paths")
    step_output_refs = _step_refs(steps, "output_paths")
    linked_refs = _dedupe([*output_refs, *task_status_refs, *step_output_refs])
    run_id = str(content.get("run_id") or run.get("id") or "")
    runtime_counts = _runtime_asset_counts(storage, run_id=run_id)
    ref_type_counts = _referenced_asset_type_counts(storage, linked_refs)
    task_status_mode = str(control.get("task_status_mode") or policy.get("task_status_mode") or "missing")
    runtime_policy_path = str(control.get("runtime_artifact_policy_path") or policy.get("applied_policy_path") or policy.get("source_path") or "")
    linked_count = len(linked_refs)
    risk_level = _risk_level(linked_count=linked_count, task_status_mode=task_status_mode, policy=policy)
    step_count = len(steps)
    compact_savings = _estimated_compaction_savings(step_count=step_count, task_status_mode=task_status_mode, policy=policy)
    return {
        "run_id": run_id,
        "path": str(run.get("_path") or run.get("path") or ""),
        "recorded_at": str(run.get("updated_at") or run.get("created_at") or ""),
        "chapter": int(content.get("chapter") or 0),
        "status": str(content.get("status") or ""),
        "current_step": str(content.get("current_step") or ""),
        "task_status_mode": task_status_mode,
        "runtime_artifact_policy_status": "present" if policy else "missing",
        "runtime_artifact_policy_source": str(control.get("runtime_artifact_policy_source") or ""),
        "runtime_artifact_policy_path": runtime_policy_path,
        "runtime_artifact_policy_applied_policy_path": str(policy.get("applied_policy_path") or ""),
        "step_count": step_count,
        "linked_asset_ref_count": linked_count,
        "output_ref_count": len(output_refs),
        "task_status_ref_count": len(task_status_refs),
        "step_output_ref_count": len(step_output_refs),
        "node_run_count": runtime_counts["node_run_count"],
        "trace_span_count": runtime_counts["trace_span_count"],
        "estimated_compacted_write_savings": compact_savings,
        "referenced_asset_type_counts": ref_type_counts,
        "risk_level": risk_level,
        "recommendation": _row_recommendation(risk_level, task_status_mode, linked_count),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "chapter_run_count": 0,
            "max_linked_asset_ref_count": 0,
            "average_linked_asset_ref_count": 0.0,
            "estimated_compacted_write_savings": 0,
            "referenced_asset_type_counts": {},
            "repeated_asset_type_counts": {},
        }
    type_counts: Counter[str] = Counter()
    for row in rows:
        type_counts.update(row.get("referenced_asset_type_counts", {}))
    repeated = {key: value for key, value in type_counts.items() if value > max(1, len(rows))}
    linked_counts = [int(row.get("linked_asset_ref_count") or 0) for row in rows]
    return {
        "chapter_run_count": len(rows),
        "max_linked_asset_ref_count": max(linked_counts),
        "average_linked_asset_ref_count": round(sum(linked_counts) / max(1, len(linked_counts)), 3),
        "estimated_compacted_write_savings": sum(int(row.get("estimated_compacted_write_savings") or 0) for row in rows),
        "referenced_asset_type_counts": dict(sorted(type_counts.items())),
        "repeated_asset_type_counts": dict(sorted(repeated.items())),
    }


def _artifact_hotspot_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    family_counts: Counter[str] = Counter()
    family_run_counts: dict[str, int] = {}
    family_max_per_run: dict[str, int] = {}
    for row in rows:
        counts = Counter(row.get("referenced_asset_type_counts", {}) if isinstance(row.get("referenced_asset_type_counts", {}), dict) else {})
        if int(row.get("task_status_ref_count") or 0):
            counts["task_status_ref"] += int(row.get("task_status_ref_count") or 0)
        if int(row.get("output_ref_count") or 0):
            counts["chapter_output_ref"] += int(row.get("output_ref_count") or 0)
        if int(row.get("step_output_ref_count") or 0):
            counts["step_output_ref"] += int(row.get("step_output_ref_count") or 0)
        if int(row.get("node_run_count") or 0):
            counts["node_run"] += int(row.get("node_run_count") or 0)
        if int(row.get("trace_span_count") or 0):
            counts["trace_span"] += int(row.get("trace_span_count") or 0)
        for family, count in counts.items():
            if count <= 0:
                continue
            family_counts[str(family)] += int(count)
            family_run_counts[str(family)] = family_run_counts.get(str(family), 0) + 1
            family_max_per_run[str(family)] = max(family_max_per_run.get(str(family), 0), int(count))
    run_count = max(1, len(rows))
    result = []
    for family, count in family_counts.most_common(limit):
        max_per_run = family_max_per_run.get(family, 0)
        average_per_run = round(count / run_count, 3)
        result.append(
            {
                "artifact_family": family,
                "total_count": int(count),
                "run_count": int(family_run_counts.get(family, 0)),
                "max_per_run": int(max_per_run),
                "average_per_run": average_per_run,
                "risk_level": _artifact_family_risk(family, total_count=int(count), max_per_run=max_per_run, run_count=run_count),
                "operator_action": _artifact_family_operator_action(family),
            }
        )
    return result


def _run_hotspot_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda item: (
            int(item.get("linked_asset_ref_count") or 0),
            int(item.get("node_run_count") or 0) + int(item.get("trace_span_count") or 0),
        ),
        reverse=True,
    )
    result = []
    for row in sorted_rows[:limit]:
        ref_counts = row.get("referenced_asset_type_counts", {}) if isinstance(row.get("referenced_asset_type_counts", {}), dict) else {}
        result.append(
            {
                "run_id": str(row.get("run_id") or ""),
                "chapter": int(row.get("chapter") or 0),
                "path": str(row.get("path") or ""),
                "risk_level": str(row.get("risk_level") or "unknown"),
                "linked_asset_ref_count": int(row.get("linked_asset_ref_count") or 0),
                "node_run_count": int(row.get("node_run_count") or 0),
                "trace_span_count": int(row.get("trace_span_count") or 0),
                "top_referenced_asset_types": dict(Counter(ref_counts).most_common(5)),
                "recommendation": str(row.get("recommendation") or ""),
            }
        )
    return result


def _acceptance_report_hotspot_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "long_chain_acceptance_report":
            continue
        if project_id and not asset_matches_project_scope(storage, data, project_id):
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        output_counts = content.get("output_counts", {}) if isinstance(content.get("output_counts", {}), dict) else {}
        if not output_counts:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "status": str(content.get("status") or data.get("status") or ""),
                "top_output_counts": dict(Counter({str(key): int(value or 0) for key, value in output_counts.items()}).most_common(limit)),
            }
        )
    return sorted(rows, key=lambda item: str(item.get("path") or ""))[-limit:]


def _artifact_family_risk(family: str, *, total_count: int, max_per_run: int, run_count: int) -> str:
    if family in {"unresolved_ref"}:
        return "high"
    if family in {"trace_span", "node_run", "task_status_ref"} and max_per_run > 10:
        return "high"
    if max_per_run > HIGH_REF_THRESHOLD or total_count > run_count * HIGH_REF_THRESHOLD:
        return "high"
    if max_per_run > 25 or total_count > run_count * 25:
        return "medium"
    return "low"


def _artifact_family_operator_action(family: str) -> str:
    if family in {"task_status_ref", "node_run", "trace_span"}:
        return "review runtime artifact recording policy for compact sequence runs"
    if family in {"draft_chapter", "draft_version", "revision_task", "review_issue", "review_report"}:
        return "inspect chapter quality loop and revision artifact fanout before final acceptance"
    if family == "unresolved_ref":
        return "repair unresolved runtime references before final acceptance"
    return "monitor this artifact family before changing write policy"


def _hotspot_status(runtime_rows: list[dict[str, Any]], hotspot_rows: list[dict[str, Any]]) -> str:
    if not runtime_rows:
        return "missing"
    if any(row.get("risk_level") == "high" for row in hotspot_rows):
        return "review_required"
    if any(row.get("risk_level") == "medium" for row in hotspot_rows):
        return "review_required"
    if any(str(row.get("risk_level") or "") in {"medium", "high", "critical"} for row in runtime_rows):
        return "review_required"
    return "passed"


def _hotspot_recommendations(status: str, hotspot_rows: list[dict[str, Any]]) -> list[str]:
    if status == "missing":
        return ["Create or import chapter_production_run evidence before building artifact hotspot ledger"]
    recommendations = []
    families = {str(row.get("artifact_family") or "") for row in hotspot_rows if row.get("risk_level") in {"medium", "high"}}
    if families & {"task_status_ref", "node_run", "trace_span"}:
        recommendations.append("Inspect runtime artifact policy before reducing or expanding chapter sequence runs")
    if families & {"draft_chapter", "draft_version", "revision_task", "review_issue", "review_report"}:
        recommendations.append("Inspect quality-loop and revision fanout before changing draft/review write policy")
    if "unresolved_ref" in families:
        recommendations.append("Resolve missing artifact references before final unified acceptance")
    if not recommendations:
        recommendations.append("Runtime artifact hotspots are within current development bounds")
    return recommendations


def _hotspot_operator_action(status: str) -> str:
    if status == "missing":
        return "build hotspot ledger after chapter runtime evidence exists"
    if status == "review_required":
        return "inspect hotspot rows before changing runtime write policy or running final acceptance"
    return "hotspot ledger is ready for continued runtime growth governance"


def _write_policy_candidate_actions(hotspot_rows: list[Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for row in hotspot_rows:
        if not isinstance(row, dict):
            continue
        family = str(row.get("artifact_family") or "")
        risk = str(row.get("risk_level") or "low")
        if family in {"task_status_ref", "node_run", "trace_span"}:
            actions.append(
                {
                    "action_id": f"candidate-{family}",
                    "artifact_family": family,
                    "risk_level": risk,
                    "recommended_policy": _runtime_policy_recommendation(family),
                    "expected_effect": "reduce successful-run write amplification while preserving failure and governance evidence",
                    "requires_operator_approval": True,
                    "auto_apply": False,
                    "source_hotspot": row,
                }
            )
        elif family == "unresolved_ref":
            actions.append(
                {
                    "action_id": "candidate-repair-unresolved-ref",
                    "artifact_family": family,
                    "risk_level": "high",
                    "recommended_policy": {"repair": "resolve missing runtime references before policy changes"},
                    "expected_effect": "prevent hidden evidence loss before final acceptance",
                    "requires_operator_approval": True,
                    "auto_apply": False,
                    "source_hotspot": row,
                }
            )
        elif family in {"draft_chapter", "draft_version", "review_issue", "review_report", "revision_task"} and risk in {"medium", "high"}:
            actions.append(
                {
                    "action_id": f"candidate-audit-{family}",
                    "artifact_family": family,
                    "risk_level": risk,
                    "recommended_policy": {"audit": "inspect content quality and revision fanout before suppressing any artifact family"},
                    "expected_effect": "separate necessary creative evidence from avoidable loop fanout",
                    "requires_operator_approval": True,
                    "auto_apply": False,
                    "source_hotspot": row,
                }
            )
    return actions


def _runtime_policy_recommendation(family: str) -> dict[str, Any]:
    if family == "task_status_ref":
        return {"task_status_recording": {"pending": False, "running": False, "completed": True, "failed": True}}
    if family == "node_run":
        return {"node_run_recording": {"succeeded": False, "failed": True}}
    if family == "trace_span":
        return {"trace_recording": {"node_run_succeeded_span": False, "node_run_failed_span": True, "external_runtime_spans": True}}
    return {}


def _estimated_candidate_savings(hotspot_content: dict[str, Any], candidate_actions: list[dict[str, Any]]) -> int:
    summary = hotspot_content.get("summary", {}) if isinstance(hotspot_content.get("summary", {}), dict) else {}
    baseline = int(summary.get("estimated_compacted_write_savings") or 0)
    runtime_candidates = sum(1 for row in candidate_actions if row.get("artifact_family") in {"task_status_ref", "node_run", "trace_span"})
    return baseline + runtime_candidates


def _write_policy_safeguards() -> list[str]:
    return [
        "preserve failed TaskStatus, NodeRun, TraceSpan, gate, budget, approval, provider, and dead-letter evidence",
        "do not suppress ReviewIssue, RevisionTask, DraftVersion, Canon, Context, or release evidence without a separate approved plan",
        "apply policy changes only through an operator-approved runtime policy update with rollback evidence",
        "rerun focused runtime-growth regression before any final chapter acceptance",
    ]


def _write_policy_rollback_criteria() -> list[str]:
    return [
        "rollback if failed chapter debugging loses required NodeRun or TraceSpan evidence",
        "rollback if gate/budget/provider/approval evidence disappears from Cockpit or Agent Center",
        "rollback if compact run coverage no longer satisfies V1_SEQUENCE_REQUIRED_OUTPUTS",
    ]


def _write_policy_operator_action(status: str) -> str:
    if status == "missing":
        return "build runtime hotspot ledger before creating write-policy candidate plan"
    if status == "review_required":
        return "review candidate actions and safeguards before changing runtime policy"
    return "no runtime write-policy changes are recommended from current hotspot evidence"


def _write_policy_recommendations(status: str, candidate_actions: list[dict[str, Any]]) -> list[str]:
    if status == "missing":
        return ["Build hotspot evidence before proposing runtime write-policy changes"]
    if candidate_actions:
        return [
            "Review candidate actions with an operator before applying runtime policy changes",
            "Preserve failure, gate, budget, approval, provider, and dead-letter evidence",
            "Run focused runtime-growth regression after any approved write-policy change",
        ]
    return ["No runtime write-policy changes are recommended from current hotspot evidence"]


def _existing_write_policy_approval(storage: LocalStorage, *, project_id: str, plan_path: str) -> dict[str, Any]:
    fallback: dict[str, Any] = {}
    for row in list_approval_requests(storage, project_id=project_id or None, scope="agent", limit=500):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        target = content.get("target", {}) if isinstance(content.get("target", {}), dict) else {}
        if str(content.get("action") or "") != "approve_runtime_write_policy_candidate_plan":
            continue
        if str(content.get("status") or "") in {"pending", "approved"} and not fallback:
            fallback = row
        if str(target.get("target_path") or "") == plan_path:
            return row
    return fallback


def _approved_write_policy_approval(storage: LocalStorage, *, project_id: str, plan_path: str) -> dict[str, Any]:
    for row in list_approval_requests(storage, project_id=project_id or None, scope="agent", status="approved", limit=500):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        target = content.get("target", {}) if isinstance(content.get("target", {}), dict) else {}
        if str(content.get("action") or "") != "approve_runtime_write_policy_candidate_plan":
            continue
        if not plan_path or str(target.get("target_path") or "") == plan_path:
            return row
    return {}


def _latest_write_policy_candidate_plan(storage: LocalStorage, *, project_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "project_metric_snapshot":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") != WRITE_POLICY_PLAN_SNAPSHOT_KIND:
            continue
        if project_id and not asset_matches_project_scope(storage, data, project_id):
            continue
        data["path"] = _display_path(storage.root, path)
        matches.append(data)
    if not matches:
        return {}
    return sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]


def _latest_project_metric_snapshot(storage: LocalStorage, snapshot_kind: str, *, project_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "project_metric_snapshot":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") != snapshot_kind:
            continue
        if project_id and not asset_matches_project_scope(storage, data, project_id):
            continue
        data["path"] = _display_path(storage.root, path)
        matches.append(data)
    if not matches:
        return {}
    return sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]


def _resolve_or_latest_approved_apply_plan(storage: LocalStorage, *, project_id: str, apply_plan_path: str) -> dict[str, Any]:
    if str(apply_plan_path or "").strip():
        path = resolve_path(storage.root, apply_plan_path)
        data = _read_json_safe(storage, path)
        data["path"] = _display_path(storage.root, path)
        return data
    latest = _latest_project_metric_snapshot(storage, APPROVED_APPLY_PLAN_SNAPSHOT_KIND, project_id=project_id)
    if latest:
        return latest
    generated = build_chapter_runtime_growth_approved_policy_apply_plan(storage, project_id=project_id, persist=True)
    asset = generated.get("asset", {}) if isinstance(generated.get("asset", {}), dict) else {}
    asset["path"] = str(generated.get("path") or "")
    return asset


def _resolve_or_latest_applied_policy(storage: LocalStorage, *, project_id: str, applied_policy_path: str) -> dict[str, Any]:
    if str(applied_policy_path or "").strip():
        path = resolve_path(storage.root, applied_policy_path)
        data = _read_json_safe(storage, path)
        data["path"] = _display_path(storage.root, path)
        return data
    return _latest_project_metric_snapshot(storage, APPLIED_POLICY_SNAPSHOT_KIND, project_id=project_id)


def _default_runtime_write_policy() -> dict[str, Any]:
    return {
        "policy_version": "chapter-production-runtime-artifact-policy-v1",
        "task_status_mode": "compact",
        "task_status_recording": {"pending": False, "running": False, "completed": True, "failed": True},
        "node_run_recording": {"succeeded": False, "failed": True},
        "trace_recording": {"node_run_succeeded_span": False, "node_run_failed_span": True, "external_runtime_spans": True},
        "evidence_preservation": {
            "gate_result": True,
            "budget_policy": True,
            "provider_runtime_guard": True,
            "approval_request": True,
            "dead_letter": True,
            "review_issue": True,
            "revision_task": True,
        },
    }


def _active_runtime_write_policy(previous_snapshot: dict[str, Any]) -> dict[str, Any]:
    content = previous_snapshot.get("content", {}) if isinstance(previous_snapshot.get("content", {}), dict) else {}
    if isinstance(content.get("after_policy"), dict) and content.get("after_policy"):
        return content["after_policy"]
    if isinstance(content.get("restored_policy"), dict) and content.get("restored_policy"):
        return content["restored_policy"]
    return _default_runtime_write_policy()


def _deep_merge_runtime_policy(before_policy: dict[str, Any], policy_deltas: list[Any]) -> dict[str, Any]:
    merged = _deep_copy_dict(before_policy)
    for delta in policy_deltas:
        if not isinstance(delta, dict):
            continue
        recommended = delta.get("recommended_policy", {}) if isinstance(delta.get("recommended_policy", {}), dict) else {}
        merged = _deep_merge_dicts(merged, recommended)
    merged["policy_version"] = str(merged.get("policy_version") or "chapter-production-runtime-artifact-policy-v1")
    merged["policy_source"] = APPLIED_POLICY_CONTRACT
    merged["policy_updated_at"] = utc_now()
    return merged


def _deep_copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            copied[key] = _deep_copy_dict(item)
        elif isinstance(item, list):
            copied[key] = [(_deep_copy_dict(row) if isinstance(row, dict) else row) for row in item]
        else:
            copied[key] = item
    return copied


def _deep_merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = _deep_copy_dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dicts(result[key], value)
        elif isinstance(value, dict):
            result[key] = _deep_copy_dict(value)
        else:
            result[key] = value
    return result


def _policy_apply_blocked_reason(plan_content: dict[str, Any], plan_summary: dict[str, Any], policy_deltas: list[Any]) -> str:
    if not plan_content:
        return "approved runtime write-policy apply plan is missing"
    if str(plan_content.get("snapshot_kind") or "") != APPROVED_APPLY_PLAN_SNAPSHOT_KIND:
        return "apply_plan_path does not point to a runtime growth approved apply plan"
    if str(plan_content.get("status") or "") != "ready":
        return "runtime write-policy apply plan is not ready"
    if not bool(plan_summary.get("approved", False)):
        return "runtime write-policy ApprovalRequest is not approved"
    if not bool(plan_summary.get("apply_allowed", False)):
        return "runtime write-policy apply plan is not allowed"
    if not policy_deltas:
        return "runtime write-policy apply plan has no policy deltas"
    return "runtime write-policy apply blocked by unknown readiness gap"


def _policy_apply_operator_action(status: str) -> str:
    if status == "applied":
        return "run focused runtime-growth regression before final unified acceptance consumes the applied policy"
    return "approve and rebuild runtime write-policy apply plan before applying runtime policy"


def _policy_apply_recommendations(status: str) -> list[str]:
    if status == "applied":
        return [
            "Use this applied policy snapshot as the future runtime write-policy evidence source",
            "Keep failed TaskStatus, NodeRun, TraceSpan, gate, budget, provider, approval, and dead-letter evidence enabled",
            "Run focused runtime-growth regression before final unified acceptance",
        ]
    return ["Do not change runtime write policy until the apply plan is ready and approved"]


def _policy_rollback_operator_action(status: str) -> str:
    if status == "rolled_back":
        return "rerun focused runtime-growth regression after rollback before final unified acceptance"
    return "select an applied runtime write-policy snapshot before rollback"


def _policy_rollback_recommendations(status: str) -> list[str]:
    if status == "rolled_back":
        return [
            "Use restored_policy as the future runtime write-policy evidence source",
            "Confirm cockpit and runtime-growth regression still surface failure/governance evidence",
        ]
    return ["No rollback was applied because no applied runtime write-policy evidence was available"]


def _policy_deltas_from_candidate_actions(candidate_actions: list[Any]) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    for row in candidate_actions:
        if not isinstance(row, dict):
            continue
        policy = row.get("recommended_policy", {}) if isinstance(row.get("recommended_policy", {}), dict) else {}
        if not policy or "audit" in policy or "repair" in policy:
            continue
        deltas.append(
            {
                "artifact_family": str(row.get("artifact_family") or ""),
                "recommended_policy": policy,
                "preserve_failure_evidence": True,
                "requires_approved_request": True,
                "auto_apply": False,
            }
        )
    return deltas


def _approved_apply_operator_action(status: str) -> str:
    if status == "ready":
        return "review exact policy deltas and run focused regression before any future apply slice"
    if status == "missing":
        return "create candidate plan and approval request before apply planning"
    return "approve runtime write-policy candidate plan before any apply path"


def _approved_apply_recommendations(status: str) -> list[str]:
    if status == "ready":
        return ["Use this plan as the input to a separate guarded apply slice; do not mutate policy from this report"]
    if status == "missing":
        return ["Build candidate plan and ApprovalRequest evidence before planning runtime policy apply"]
    return ["Resolve the runtime write-policy ApprovalRequest before planning any policy mutation"]


def _threshold_blocking_rows(
    *,
    profile_status: str,
    runtime_rows: list[dict[str, Any]],
    max_linked_asset_refs: int,
    allow_full_mode: bool,
    applied_policy_path: str = "",
    applied_policy_recorded_at: str = "",
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if profile_status == "missing" or not runtime_rows:
        blockers.append(
            {
                "code": "chapter_runtime_growth_profile_missing",
                "severity": "high",
                "message": "chapter runtime growth profile has no chapter run evidence",
                "path": "",
            }
        )
        return blockers
    post_apply_rows = [
        row
        for row in runtime_rows
        if applied_policy_path and _runtime_row_is_at_or_after_policy(row, applied_policy_recorded_at)
    ]
    if applied_policy_path and not post_apply_rows:
        blockers.append(
            {
                "code": "chapter_runtime_applied_policy_no_post_apply_run",
                "severity": "high",
                "message": "latest applied runtime write-policy has no future chapter run evidence",
                "path": applied_policy_path,
                "applied_policy_path": applied_policy_path,
            }
        )
    for row in runtime_rows:
        run_id = str(row.get("run_id") or "")
        path = str(row.get("path") or "")
        linked_count = int(row.get("linked_asset_ref_count") or 0)
        if applied_policy_path and _runtime_row_is_at_or_after_policy(row, applied_policy_recorded_at) and not _runtime_row_consumed_applied_policy(row, applied_policy_path):
            blockers.append(
                {
                    "code": "chapter_runtime_applied_policy_not_consumed",
                    "severity": "high",
                    "run_id": run_id,
                    "path": path,
                    "applied_policy_path": applied_policy_path,
                    "message": "chapter production run did not record consumption of the latest applied runtime write-policy",
                }
            )
        if str(row.get("runtime_artifact_policy_status") or "") != "present":
            blockers.append(
                {
                    "code": "chapter_runtime_policy_missing",
                    "severity": "high",
                    "run_id": run_id,
                    "path": path,
                    "message": "chapter production run is missing runtime_artifact_policy evidence",
                }
            )
        if not allow_full_mode and str(row.get("task_status_mode") or "") == "full":
            blockers.append(
                {
                    "code": "chapter_runtime_full_mode",
                    "severity": "medium",
                    "run_id": run_id,
                    "path": path,
                    "message": "chapter production run uses full task status mode instead of compact mode",
                }
            )
        if linked_count > max_linked_asset_refs:
            blockers.append(
                {
                    "code": "chapter_runtime_high_fanout",
                    "severity": "high",
                    "run_id": run_id,
                    "path": path,
                    "linked_asset_ref_count": linked_count,
                    "threshold": max_linked_asset_refs,
                    "message": "chapter production run exceeds linked asset reference threshold",
                }
            )
    return blockers


def _runtime_row_is_at_or_after_policy(row: dict[str, Any], applied_policy_recorded_at: str) -> bool:
    if not applied_policy_recorded_at:
        return True
    recorded_at = str(row.get("recorded_at") or "")
    if not recorded_at:
        return False
    return recorded_at >= applied_policy_recorded_at


def _runtime_row_consumed_applied_policy(row: dict[str, Any], applied_policy_path: str) -> bool:
    if not applied_policy_path:
        return False
    if str(row.get("runtime_artifact_policy_source") or "") == "applied_policy" and str(row.get("runtime_artifact_policy_path") or "") == applied_policy_path:
        return True
    return str(row.get("runtime_artifact_policy_applied_policy_path") or "") == applied_policy_path


def _threshold_operator_action(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "chapter runtime growth is within threshold"
    codes = {str(row.get("code") or "") for row in blockers}
    if "chapter_runtime_growth_profile_missing" in codes:
        return "create a chapter runtime growth profile before final unified acceptance"
    if "chapter_runtime_applied_policy_not_consumed" in codes or "chapter_runtime_applied_policy_no_post_apply_run" in codes:
        return "run a future chapter through the applied runtime write-policy resolver before final acceptance"
    if "chapter_runtime_high_fanout" in codes:
        return "inspect high-fanout chapter runs and compact runtime artifacts before final acceptance"
    if "chapter_runtime_full_mode" in codes or "chapter_runtime_policy_missing" in codes:
        return "switch sequence runs to compact runtime artifact policy before final acceptance"
    return "review chapter runtime growth threshold blockers"


def _normalize_write_budgets(budgets: dict[str, Any] | None, *, chapter_run_count: int) -> dict[str, int]:
    raw = budgets if isinstance(budgets, dict) else {}
    normalized: dict[str, int] = {}
    for key, default in DEFAULT_WRITE_BUDGETS.items():
        value = raw.get(key, default)
        try:
            normalized[key] = max(1, int(value))
        except (TypeError, ValueError):
            normalized[key] = default
    if "max_repeated_asset_type_total" not in raw:
        normalized["max_repeated_asset_type_total"] = max(DEFAULT_WRITE_BUDGETS["max_repeated_asset_type_total"], max(1, chapter_run_count) * 8)
    return normalized


def _write_budget_blocking_rows(
    *,
    profile_status: str,
    runtime_rows: list[dict[str, Any]],
    profile_summary: dict[str, Any],
    budgets: dict[str, int],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if profile_status == "missing" or not runtime_rows:
        return [
            {
                "code": "chapter_runtime_write_budget_profile_missing",
                "severity": "high",
                "message": "chapter runtime write budget gate has no chapter run evidence",
                "path": "",
            }
        ]
    for row in runtime_rows:
        run_id = str(row.get("run_id") or "")
        path = str(row.get("path") or "")
        _append_write_budget_blocker(
            blockers,
            code="chapter_runtime_write_budget_linked_refs",
            metric="linked_asset_ref_count",
            value=int(row.get("linked_asset_ref_count") or 0),
            threshold=budgets["max_linked_asset_refs_per_run"],
            run_id=run_id,
            path=path,
        )
        _append_write_budget_blocker(
            blockers,
            code="chapter_runtime_write_budget_task_status_refs",
            metric="task_status_ref_count",
            value=int(row.get("task_status_ref_count") or 0),
            threshold=budgets["max_task_status_refs_per_run"],
            run_id=run_id,
            path=path,
        )
        _append_write_budget_blocker(
            blockers,
            code="chapter_runtime_write_budget_step_output_refs",
            metric="step_output_ref_count",
            value=int(row.get("step_output_ref_count") or 0),
            threshold=budgets["max_step_output_refs_per_run"],
            run_id=run_id,
            path=path,
        )
        _append_write_budget_blocker(
            blockers,
            code="chapter_runtime_write_budget_node_runs",
            metric="node_run_count",
            value=int(row.get("node_run_count") or 0),
            threshold=budgets["max_node_runs_per_run"],
            run_id=run_id,
            path=path,
        )
        _append_write_budget_blocker(
            blockers,
            code="chapter_runtime_write_budget_trace_spans",
            metric="trace_span_count",
            value=int(row.get("trace_span_count") or 0),
            threshold=budgets["max_trace_spans_per_run"],
            run_id=run_id,
            path=path,
        )
    repeated_counts = profile_summary.get("repeated_asset_type_counts", {}) if isinstance(profile_summary.get("repeated_asset_type_counts", {}), dict) else {}
    for asset_type, count in sorted(repeated_counts.items()):
        value = int(count or 0)
        threshold = budgets["max_repeated_asset_type_total"]
        if value > threshold:
            blockers.append(
                {
                    "code": "chapter_runtime_write_budget_repeated_asset_family",
                    "severity": "medium",
                    "asset_type": str(asset_type),
                    "metric": "repeated_asset_type_count",
                    "value": value,
                    "threshold": threshold,
                    "path": "",
                    "message": f"repeated runtime asset family {asset_type} exceeds write budget",
                }
            )
    return blockers


def _append_write_budget_blocker(
    blockers: list[dict[str, Any]],
    *,
    code: str,
    metric: str,
    value: int,
    threshold: int,
    run_id: str,
    path: str,
) -> None:
    if value <= threshold:
        return
    blockers.append(
        {
            "code": code,
            "severity": "high",
            "run_id": run_id,
            "path": path,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "message": f"chapter runtime metric {metric}={value} exceeds write budget {threshold}",
        }
    )


def _write_budget_operator_action(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "chapter runtime writes are within budget"
    codes = {str(row.get("code") or "") for row in blockers}
    if "chapter_runtime_write_budget_profile_missing" in codes:
        return "create a chapter runtime growth profile before enforcing write budgets"
    if "chapter_runtime_write_budget_repeated_asset_family" in codes:
        return "inspect repeated runtime asset families before final acceptance"
    return "tighten runtime write policy or reduce chapter run artifact fanout before final acceptance"


def _runtime_asset_counts(storage: LocalStorage, *, run_id: str) -> dict[str, int]:
    counts = {"node_run_count": 0, "trace_span_count": 0}
    if not run_id:
        return counts
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("run_id") or content.get("trace_id") or "") != run_id:
            continue
        if data.get("type") == "node_run":
            counts["node_run_count"] += 1
        elif data.get("type") == "trace_span":
            counts["trace_span_count"] += 1
    return counts


def _referenced_asset_type_counts(storage: LocalStorage, refs: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for ref in refs:
        data = _read_asset_ref(storage, ref)
        if data:
            counts[str(data.get("type") or "unknown")] += 1
        elif str(ref).endswith(".md"):
            counts["markdown_export"] += 1
        elif str(ref).strip():
            counts["unresolved_ref"] += 1
    return dict(sorted(counts.items()))


def _steps(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _step_refs(steps: list[dict[str, Any]], key: str) -> list[str]:
    refs: list[str] = []
    for step in steps:
        value = step.get(key, [])
        if isinstance(value, list):
            refs.extend(str(item) for item in value if str(item or "").strip())
    return _dedupe(refs)


def _estimated_compaction_savings(*, step_count: int, task_status_mode: str, policy: dict[str, Any]) -> int:
    if task_status_mode != "compact":
        return 0
    task_status_recording = policy.get("task_status_recording", {}) if isinstance(policy.get("task_status_recording", {}), dict) else {}
    node_run_recording = policy.get("node_run_recording", {}) if isinstance(policy.get("node_run_recording", {}), dict) else {}
    trace_recording = policy.get("trace_recording", {}) if isinstance(policy.get("trace_recording", {}), dict) else {}
    savings = 0
    if task_status_recording.get("pending") is False:
        savings += step_count
    if task_status_recording.get("running") is False:
        savings += step_count
    if node_run_recording.get("succeeded") is False:
        savings += step_count
    if trace_recording.get("node_run_succeeded_span") is False:
        savings += step_count
    return savings


def _risk_level(*, linked_count: int, task_status_mode: str, policy: dict[str, Any]) -> str:
    if not policy:
        return "high"
    if linked_count > HIGH_REF_THRESHOLD:
        return "high"
    if task_status_mode == "full":
        return "medium"
    return "low"


def _row_recommendation(risk_level: str, task_status_mode: str, linked_count: int) -> str:
    if risk_level == "high":
        return "inspect run artifact fanout before extending chapter count"
    if task_status_mode == "full":
        return "use compact mode for batch chapter sequence runs"
    if linked_count > 80:
        return "monitor linked asset count before final acceptance"
    return "runtime growth profile is within development bounds"


def _recommendations(status: str, rows: list[dict[str, Any]]) -> list[str]:
    if status == "missing":
        return ["Create or import a chapter_production_run fixture before profiling runtime growth"]
    recommendations = []
    if any(row["task_status_mode"] == "full" for row in rows):
        recommendations.append("Use compact task_status_mode for batch chapter sequence runs")
    if any(row["risk_level"] == "high" for row in rows):
        recommendations.append("Inspect high-fanout chapter runs before final unified acceptance")
    if not recommendations:
        recommendations.append("Keep compact runtime artifact policy for sequence runs")
    return recommendations


def _operator_action(status: str) -> str:
    if status == "missing":
        return "run profiler after a chapter_production_run fixture exists"
    if status == "review_required":
        return "review high-fanout or full-mode runs before final acceptance"
    return "runtime growth profile is ready for continued development"


def _read_asset_ref(storage: LocalStorage, ref: str) -> dict[str, Any]:
    try:
        data = storage.read_json(resolve_path(storage.root, ref))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(item) for item in values if str(item or "").strip())]
