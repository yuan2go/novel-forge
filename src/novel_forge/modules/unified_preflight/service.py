from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.storage.local import LocalStorage

GATE_KIND = "v1_unified_preflight"
GATE_CONTRACT = "v1-unified-preflight-rollup-gate-v1"


def run_v1_unified_preflight_rollup_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "local",
) -> dict[str, Any]:
    """Write a read-only gate over the latest unified acceptance preflight manifest."""

    storage.ensure_layout()
    latest = _latest_preflight_manifest(storage, project_id=project_id)
    manifest = latest.get("manifest", {}) if isinstance(latest.get("manifest", {}), dict) else {}
    report_path = str(latest.get("report_path") or "")
    manifest_status = str(manifest.get("status") or "missing")
    missing_manifest = not bool(manifest)
    unready_rows = manifest.get("unready_final_evidence", []) if isinstance(manifest.get("unready_final_evidence", []), list) else []
    required_rows = manifest.get("required_evidence", []) if isinstance(manifest.get("required_evidence", []), list) else []
    if not unready_rows:
        unready_rows = _unready_rows_from_required(required_rows)
    repair_plan = manifest.get("operator_repair_plan", {}) if isinstance(manifest.get("operator_repair_plan", {}), dict) else {}
    repair_actions = repair_plan.get("actions", []) if isinstance(repair_plan.get("actions", []), list) else []
    production = is_production_environment(environment)
    blockers = _rollup_blockers(manifest_status=manifest_status, missing_manifest=missing_manifest, unready_rows=unready_rows)
    status = "passed" if not blockers else "failed" if production else "warning"
    message = "v1 unified preflight rollup gate passed" if status == "passed" else f"v1 unified preflight rollup gate has {len(blockers)} blocker(s)"
    evidence_paths = _dedupe(
        [
            report_path,
            *[str(row.get("evidence_path") or "") for row in unready_rows if isinstance(row, dict)],
            *[str(path) for row in unready_rows if isinstance(row, dict) for path in row.get("linked_evidence_paths", []) if str(path or "").strip()],
        ]
    )
    summary = {
        "manifest_status": manifest_status,
        "manifest_present": not missing_manifest,
        "enforced_failure_count": int(manifest.get("enforced_failure_count") or 0),
        "unready_final_evidence_count": int(manifest.get("unready_final_evidence_count") or manifest.get("missing_or_deferred_final_evidence_count") or len(unready_rows)),
        "repair_action_count": len(repair_actions),
        "blocking_count": len(blockers),
        "production": production,
        "read_only": True,
        "repair_executed": False,
        "provider_call_executed": False,
        "chapter_acceptance_executed": False,
    }
    gate = record_gate_result(
        storage,
        gate_kind=GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": GATE_CONTRACT,
            "project_id": project_id,
            "environment": environment,
            "acceptance_report_path": report_path,
            "summary": summary,
            "blockers": blockers,
            "operator_repair_plan": repair_plan,
            "operator_action": _operator_action(status, blockers),
            "mutation_policy": "read-only: no source, workflow, approval, quality, provider, repair, or acceptance mutation",
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
        "blockers": blockers,
        "acceptance_report_path": report_path,
        "gate_result": gate,
        "gate_result_path": str(gate.get("path") or ""),
    }


def _latest_preflight_manifest(storage: LocalStorage, *, project_id: str) -> dict[str, Any]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "long_chain_acceptance_report":
            continue
        if project_id and _project_id(data) not in {"", project_id}:
            continue
        matches.append((path, data))
    if not matches:
        return {"report_path": "", "manifest": {}}
    path, data = sorted(matches, key=lambda item: str(item[1].get("updated_at") or item[1].get("created_at") or ""))[-1]
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    manifest = content.get("unified_acceptance_preflight_manifest", {}) if isinstance(content.get("unified_acceptance_preflight_manifest", {}), dict) else {}
    return {"report_path": _display_path(storage.root, path), "manifest": manifest}


def _rollup_blockers(*, manifest_status: str, missing_manifest: bool, unready_rows: list[Any]) -> list[dict[str, Any]]:
    if manifest_status == "passed" and not missing_manifest and not unready_rows:
        return []
    blockers: list[dict[str, Any]] = []
    if missing_manifest:
        blockers.append(
            {
                "code": "unified_preflight_manifest_missing",
                "severity": "critical",
                "message": "latest v1 acceptance report has no unified preflight manifest",
                "operator_action": "create unified preflight manifest before final acceptance",
            }
        )
    if manifest_status in {"failed", "review_required", "missing", "unknown"}:
        blockers.append(
            {
                "code": "unified_preflight_manifest_not_passed",
                "severity": "critical" if manifest_status == "failed" else "high",
                "message": f"unified preflight manifest status is {manifest_status}",
                "operator_action": "resolve enforced failures and unready final evidence before final acceptance",
            }
        )
    for row in unready_rows[:20]:
        if not isinstance(row, dict):
            continue
        blockers.append(
            {
                "code": "unified_preflight_final_evidence_unready",
                "severity": "high",
                "dimension": str(row.get("key") or ""),
                "status": str(row.get("status") or ""),
                "message": str(row.get("message") or f"final preflight evidence is {row.get('status') or 'unready'}"),
                "operator_action": str(row.get("operator_action") or "complete this final preflight evidence"),
            }
        )
    return blockers


def _unready_rows_from_required(required_rows: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in required_rows:
        if not isinstance(row, dict):
            continue
        if bool(row.get("enforced_now", False)) or str(row.get("status") or "") == "passed":
            continue
        rows.append(
            {
                "key": str(row.get("key") or ""),
                "status": str(row.get("status") or ""),
                "evidence_path": str(row.get("evidence_path") or ""),
                "message": str(row.get("message") or ""),
                "operator_action": str(row.get("operator_action") or ""),
                "linked_evidence_paths": row.get("linked_evidence_paths", []) if isinstance(row.get("linked_evidence_paths", []), list) else [],
            }
        )
    return rows


def _operator_action(status: str, blockers: list[dict[str, Any]]) -> str:
    if status == "passed":
        return "unified preflight is ready for final acceptance gate checks"
    if blockers:
        return "resolve unified preflight blockers before final acceptance"
    return "review unified preflight rollup gate"


def _project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
