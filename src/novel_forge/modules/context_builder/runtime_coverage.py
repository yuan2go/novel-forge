from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import read_json_for_scan
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


RUNTIME_TYPES = {"context_bundle", "chapter_production_run", "agent_run", "node_run"}
GAP_STATUSES = {"missing_binding", "invalid_binding", "direct_report_mismatch"}


def build_context_governance_runtime_coverage_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 500,
    persist: bool = False,
) -> dict[str, Any]:
    """Build a read-only coverage report for selector-governance binding evidence.

    The report scans runtime artifacts and classifies only observed evidence. It
    does not infer that a path is governed because a feature exists in code.
    """

    requested_project_id = str(project_id or "")
    snapshot_project_id = requested_project_id or "local-system"
    rows = _scan_runtime_rows(storage, project_id=requested_project_id, limit=limit)
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["coverage_status"]] = status_counts.get(row["coverage_status"], 0) + 1
        type_counts[row["asset_type"]] = type_counts.get(row["asset_type"], 0) + 1
    blockers = [row for row in rows if row["blocking"]]
    generated_at = utc_now()
    recommendations = _recommendations(rows, blockers)
    report = {
        "coverage_report_id": make_id("context_governance_runtime_coverage", f"{requested_project_id or 'all'}-{utc_now()}"),
        "snapshot_kind": "context_governance_runtime_coverage",
        "contract": "context-governance-runtime-coverage-v1",
        "project_id": snapshot_project_id,
        "snapshot_at": generated_at,
        "generated_at": generated_at,
        "limit": limit,
        "throughput": {"scanned_artifact_count": len(rows), "limit": limit},
        "quality": {"context_governance_coverage": status_counts},
        "task_health": {"blocking_count": len(blockers), "gap_count": sum(status_counts.get(status, 0) for status in GAP_STATUSES)},
        "agent_health": {"agent_run_count": type_counts.get("agent_run", 0)},
        "storage_health": {"scanned_categories": ["contexts", "runs"], "asset_type_counts": type_counts},
        "summary": {
            "artifact_count": len(rows),
            "selector_evidence_count": sum(1 for row in rows if row["selector_governance"]["present"]),
            "governed_count": status_counts.get("governed", 0),
            "gap_count": sum(status_counts.get(status, 0) for status in GAP_STATUSES),
            "blocking_count": len(blockers),
            "local_legacy_count": status_counts.get("local_legacy", 0),
            "no_selector_governance_count": status_counts.get("no_selector_governance", 0),
            "status_counts": status_counts,
            "asset_type_counts": type_counts,
        },
        "rows": rows,
        "blocking_rows": blockers,
        "recommendations": recommendations,
        "source_isolation": {
            "raw_source_text_included": False,
            "draft_text_included": False,
            "report_is_read_only": True,
        },
    }
    if persist:
        asset = ProjectMetricSnapshot(
            id=report["coverage_report_id"],
            title=f"Context governance runtime coverage {utc_now()}",
            source="context-builder-runtime-coverage",
            tags=["context-governance", "runtime-coverage", "ops"],
            content=report,
            metadata={"project_id": snapshot_project_id, "snapshot_kind": "context_governance_runtime_coverage", "read_only": True},
            references=_dedupe([row["path"] for row in rows[:50]]) if requested_project_id else [],
        )
        data = asset.to_dict()
        errors = validate_common_fields(data)
        if errors:
            raise ValueError("; ".join(errors))
        path = storage.write_asset("runs", asset)
        report["path"] = _display_path(storage.root, path)
        report["asset"] = data
    return report


def run_context_governance_coverage_gate(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    environment: str = "",
    mode: str = "",
    limit: int = 500,
    persist_report: bool = True,
) -> dict[str, Any]:
    report = build_context_governance_runtime_coverage_report(storage, project_id=project_id, limit=limit, persist=persist_report)
    production = _strict_mode(environment=environment, mode=mode)
    blockers = report.get("blocking_rows", []) if isinstance(report.get("blocking_rows", []), list) else []
    status = "failed" if blockers and production else "warning" if blockers else "passed"
    message = (
        f"context governance runtime coverage has {len(blockers)} blocking row(s)"
        if blockers
        else "context governance runtime coverage passed"
    )
    target_paths = _dedupe([str(report.get("path") or ""), *[str(row.get("path") or "") for row in blockers]])
    gate = record_gate_result(
        storage,
        gate_kind="context_governance_runtime_coverage",
        status=status,
        target_paths=target_paths,
        result={
            "coverage_report_id": report["coverage_report_id"],
            "coverage_report_path": str(report.get("path") or ""),
            "summary": report["summary"],
            "blocking_rows": blockers,
            "environment": environment,
            "mode": mode,
            "production": production,
            "contract": "context-governance-runtime-coverage-gate-v1",
        },
        project_id=str(project_id or ""),
        message=message,
        blocking=production,
    )
    return {
        "status": status,
        "production": production,
        "blocking": production and bool(blockers),
        "coverage_report": report,
        "gate_result": gate,
        "message": message,
    }


def _scan_runtime_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in ["contexts", "runs"]:
        for path in reversed(storage.list_json(category)):
            if len(rows) >= limit:
                return rows
            data = read_json_for_scan(storage, path, context="context governance runtime coverage scan")
            asset_type = str(data.get("type") or "")
            if asset_type not in RUNTIME_TYPES:
                continue
            row_project_id = _project_id(data)
            if project_id and row_project_id and row_project_id != project_id:
                continue
            rows.append(_coverage_row(storage, path, data, project_id=row_project_id))
    return rows


def _coverage_row(storage: LocalStorage, path: Path, data: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    asset_type = str(data.get("type") or "")
    content = _content(data)
    metadata = _metadata(data)
    evidence = _selector_evidence(storage, data)
    strict = _strict_runtime_artifact(data)
    status = _coverage_status(evidence, strict=strict)
    blocking = status in GAP_STATUSES and (strict or evidence["present"])
    return {
        "asset_type": asset_type,
        "asset_id": str(data.get("id") or ""),
        "path": _display_path(storage.root, path),
        "project_id": project_id,
        "status": str(content.get("status") or metadata.get("status") or ""),
        "operation": _operation(data),
        "production_like": strict,
        "selector_governance": evidence,
        "coverage_status": status,
        "blocking": blocking,
        "reason": _coverage_reason(status, evidence, strict=strict),
    }


def _selector_evidence(storage: LocalStorage, data: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(data.get("type") or "")
    content = _content(data)
    metadata = _metadata(data)
    source: dict[str, Any] = {}
    if asset_type == "context_bundle":
        contract = content.get("knowledge_context_contract", {}) if isinstance(content.get("knowledge_context_contract", {}), dict) else {}
        binding = content.get("selector_governance_binding_application", {}) if isinstance(content.get("selector_governance_binding_application", {}), dict) else {}
        if not binding and isinstance(contract.get("selector_governance_binding_application", {}), dict):
            binding = contract.get("selector_governance_binding_application", {})
        selector = contract.get("selector_governance", {}) if isinstance(contract.get("selector_governance", {}), dict) else {}
        source = {
            "selector_governance_report_path": binding.get("selector_governance_report_path") or selector.get("report_path") or metadata.get("selector_governance_report_path"),
            "selector_governance_binding_application_report_path": binding.get("application_report_path")
            or binding.get("selector_governance_binding_application_report_path")
            or metadata.get("selector_governance_binding_application_path"),
            "direct_selector_governance_report_path": "",
        }
    elif asset_type == "chapter_production_run":
        outputs = content.get("outputs", {}) if isinstance(content.get("outputs", {}), dict) else {}
        source = {
            "selector_governance_report_path": outputs.get("selector_governance_report_path"),
            "selector_governance_binding_application_report_path": outputs.get("selector_governance_binding_application_report_path"),
            "direct_selector_governance_report_path": "",
        }
    elif asset_type == "node_run":
        processor = content.get("processor", {}) if isinstance(content.get("processor", {}), dict) else {}
        runtime_evidence = processor.get("runtime_policy_evidence", {}) if isinstance(processor.get("runtime_policy_evidence", {}), dict) else {}
        source = {
            "selector_governance_report_path": runtime_evidence.get("selector_governance_report_path"),
            "selector_governance_binding_application_report_path": runtime_evidence.get("selector_governance_binding_application_report_path"),
            "direct_selector_governance_report_path": processor.get("selector_governance_report_path"),
        }
    elif asset_type == "agent_run":
        evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
        source = {
            "selector_governance_report_path": evidence.get("selector_governance_report_path"),
            "selector_governance_binding_application_report_path": evidence.get("selector_governance_binding_application_report_path"),
            "direct_selector_governance_report_path": evidence.get("selector_governance_report_path"),
        }
    report_path = _normalize_optional_path(storage, str(source.get("selector_governance_report_path") or ""))
    application_path = _normalize_optional_path(storage, str(source.get("selector_governance_binding_application_report_path") or ""))
    direct_path = _normalize_optional_path(storage, str(source.get("direct_selector_governance_report_path") or ""))
    application = _application_status(storage, application_path)
    mismatch = bool(direct_path and report_path and direct_path != report_path)
    return {
        "present": bool(report_path or application_path or direct_path),
        "selector_governance_report_path": report_path or direct_path,
        "selector_governance_binding_application_report_path": application_path,
        "direct_selector_governance_report_path": direct_path,
        "binding_application_status": application["status"],
        "binding_application_valid": application["valid"],
        "direct_report_mismatch": mismatch,
        "validation_errors": application["errors"] + (["direct_selector_governance_report_path_mismatch"] if mismatch else []),
    }


def _application_status(storage: LocalStorage, application_path: str) -> dict[str, Any]:
    if not application_path:
        return {"status": "", "valid": False, "errors": []}
    data = read_json_for_scan(storage, resolve_path(storage.root, application_path), context="context governance binding application coverage scan")
    content = _content(data)
    metadata = _metadata(data)
    status = str(content.get("status") or metadata.get("asset_status") or "")
    errors: list[str] = []
    if data.get("type") != "mkaos_selector_governance_binding_application_report":
        errors.append("binding_application_path_not_application_report")
    if status != "applied":
        errors.append(f"binding_application_status:{status or 'unknown'}")
    return {"status": status, "valid": not errors, "errors": errors}


def _coverage_status(evidence: dict[str, Any], *, strict: bool) -> str:
    if evidence["direct_report_mismatch"]:
        return "direct_report_mismatch"
    if evidence["selector_governance_binding_application_report_path"] and not evidence["binding_application_valid"]:
        return "invalid_binding"
    if evidence["selector_governance_report_path"] and not evidence["selector_governance_binding_application_report_path"]:
        return "missing_binding"
    if evidence["selector_governance_report_path"] and evidence["binding_application_valid"]:
        return "governed"
    if strict:
        return "no_selector_governance"
    return "local_legacy"


def _strict_runtime_artifact(data: dict[str, Any]) -> bool:
    content = _content(data)
    metadata = _metadata(data)
    candidates = [content, metadata]
    processor = content.get("processor", {}) if isinstance(content.get("processor", {}), dict) else {}
    candidates.append(processor)
    for key in ["runtime_policy", "runtime_policy_evidence", "evidence"]:
        value = processor.get(key, {}) if isinstance(processor.get(key, {}), dict) else {}
        candidates.append(value)
        content_value = content.get(key, {}) if isinstance(content.get(key, {}), dict) else {}
        candidates.append(content_value)
    for candidate in candidates:
        mode = str(candidate.get("mode") or candidate.get("environment") or "").strip().lower()
        if mode in {"strict", "enforced"} or is_production_environment(mode):
            return True
    return False


def _strict_mode(*, environment: str = "", mode: str = "") -> bool:
    resolved = str(environment or mode or "").strip().lower()
    return is_production_environment(resolved) or resolved in {"strict", "enforced", "operating_system"}


def _coverage_reason(status: str, evidence: dict[str, Any], *, strict: bool) -> str:
    if status == "governed":
        return "selector governance report is bound through an applied binding application"
    if status == "direct_report_mismatch":
        return "direct selector governance report path does not match runtime bundle evidence"
    if status == "missing_binding":
        return "selector governance report is present without binding application evidence"
    if status == "invalid_binding":
        return "; ".join(evidence.get("validation_errors", [])) or "binding application evidence is invalid"
    if status == "no_selector_governance":
        return "strict runtime artifact has no selector governance evidence"
    if strict:
        return "strict runtime artifact has no selector governance coverage"
    return "local or legacy artifact without selector governance evidence"


def _recommendations(rows: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> list[str]:
    if blockers:
        return [
            "route production context builds through an approved selector governance binding application",
            "rerun affected workflow/agent/chapter paths after binding evidence is applied",
        ]
    if any(row["coverage_status"] == "governed" for row in rows):
        return ["coverage observed; keep using binding application evidence for production context builds"]
    return ["no selector governance runtime evidence observed; this is acceptable only for local legacy runs"]


def _project_id(data: dict[str, Any]) -> str:
    content = _content(data)
    metadata = _metadata(data)
    return str(content.get("project_id") or metadata.get("project_id") or "")


def _operation(data: dict[str, Any]) -> str:
    content = _content(data)
    processor = content.get("processor", {}) if isinstance(content.get("processor", {}), dict) else {}
    return str(content.get("operation") or processor.get("operation") or content.get("current_step") or "")


def _content(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}


def _metadata(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}


def _normalize_optional_path(storage: LocalStorage, value: str | Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _display_path(storage.root, resolve_path(storage.root, text))


def _display_path(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))
