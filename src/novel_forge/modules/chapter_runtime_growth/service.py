from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.runtime_project_scope import asset_matches_project_scope
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage

CONTRACT = "chapter-runtime-growth-profile-v1"
SNAPSHOT_KIND = "chapter_runtime_growth_profile"
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
