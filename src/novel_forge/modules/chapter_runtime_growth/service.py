from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
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
THRESHOLD_GATE_KIND = "chapter_runtime_growth_threshold"
THRESHOLD_GATE_CONTRACT = "chapter-runtime-growth-threshold-gate-v1"
HIGH_REF_THRESHOLD = 120


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
    blockers = _threshold_blocking_rows(
        profile_status=profile_status,
        runtime_rows=runtime_rows,
        max_linked_asset_refs=threshold,
        allow_full_mode=allow_full_mode,
    )
    production = is_production_environment(environment)
    status = "failed" if production and blockers else "warning" if blockers else "passed"
    message = (
        f"chapter runtime growth threshold gate has {len(blockers)} blocking row(s)"
        if blockers
        else "chapter runtime growth threshold gate passed"
    )
    profile_path = str(profile.get("path") or "")
    evidence_paths = _dedupe([profile_path, *[str(row.get("path") or "") for row in runtime_rows], *[str(row.get("path") or "") for row in blockers]])
    summary = {
        "profile_status": profile_status,
        "chapter_run_count": int(profile.get("summary", {}).get("chapter_run_count") or 0) if isinstance(profile.get("summary", {}), dict) else 0,
        "blocking_count": len(blockers),
        "max_linked_asset_refs_threshold": threshold,
        "allow_full_mode": allow_full_mode,
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
    linked_count = len(linked_refs)
    risk_level = _risk_level(linked_count=linked_count, task_status_mode=task_status_mode, policy=policy)
    step_count = len(steps)
    compact_savings = _estimated_compaction_savings(step_count=step_count, task_status_mode=task_status_mode, policy=policy)
    return {
        "run_id": run_id,
        "path": str(run.get("_path") or run.get("path") or ""),
        "chapter": int(content.get("chapter") or 0),
        "status": str(content.get("status") or ""),
        "current_step": str(content.get("current_step") or ""),
        "task_status_mode": task_status_mode,
        "runtime_artifact_policy_status": "present" if policy else "missing",
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


def _threshold_blocking_rows(
    *,
    profile_status: str,
    runtime_rows: list[dict[str, Any]],
    max_linked_asset_refs: int,
    allow_full_mode: bool,
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
    for row in runtime_rows:
        run_id = str(row.get("run_id") or "")
        path = str(row.get("path") or "")
        linked_count = int(row.get("linked_asset_ref_count") or 0)
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


def _threshold_operator_action(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "chapter runtime growth is within threshold"
    codes = {str(row.get("code") or "") for row in blockers}
    if "chapter_runtime_growth_profile_missing" in codes:
        return "create a chapter runtime growth profile before final unified acceptance"
    if "chapter_runtime_high_fanout" in codes:
        return "inspect high-fanout chapter runs and compact runtime artifacts before final acceptance"
    if "chapter_runtime_full_mode" in codes or "chapter_runtime_policy_missing" in codes:
        return "switch sequence runs to compact runtime artifact policy before final acceptance"
    return "review chapter runtime growth threshold blockers"


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
