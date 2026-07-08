from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.core.constants import DATA_DIRS
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.modules.source_intake.guarded_apply_readiness import build_source_guarded_apply_readiness_report
from novel_forge.modules.source_intake.service import _dedupe, _display_path
from novel_forge.modules.source_intake.stale_sweep import SOURCE_DERIVED_TYPES
from novel_forge.storage.local import LocalStorage


SOURCE_GOVERNANCE_RUNTIME_GATE_KIND = "source_governance_runtime"


def run_source_governance_runtime_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "",
    mode: str = "",
    limit: int = 1000,
    persist_readiness: bool = True,
) -> dict[str, Any]:
    """Run a non-mutating runtime gate over source-governance evidence.

    The gate writes only gate/readiness evidence. It does not execute
    connectors, apply source repair plans, mark assets stale, dispatch
    regeneration, run rollback, or include raw source text.
    """

    storage.ensure_layout()
    bounded_limit = max(1, int(limit or 1000))
    readiness = build_source_guarded_apply_readiness_report(
        storage,
        project_id=project_id,
        limit=bounded_limit,
        persist=persist_readiness,
    )
    stale_report = _latest_source_report(storage, project_id=project_id, tag="stale-quarantine-sweep")
    retention_report = _latest_source_report(storage, project_id=project_id, tag="retention-expiry-sweep")
    unguarded_assets = _unguarded_source_derived_assets(storage, project_id=project_id, limit=bounded_limit)

    blockers = _blocking_rows(readiness, stale_report, retention_report, unguarded_assets)
    production = _strict_mode(environment=environment, mode=mode)
    status = "failed" if production and blockers else "warning" if blockers else "passed"
    message = (
        f"source governance runtime gate has {len(blockers)} blocking source-governance row(s)"
        if blockers
        else "source governance runtime gate passed"
    )
    evidence_paths = _dedupe(
        [
            str(readiness.get("path") or ""),
            str(stale_report.get("path") or ""),
            str(retention_report.get("path") or ""),
            *[str(row.get("path") or "") for row in blockers],
        ]
    )
    summary = {
        "readiness_status": str(readiness.get("status") or ""),
        "stale_sweep_status": str(stale_report.get("status") or "missing"),
        "retention_sweep_status": str(retention_report.get("status") or "missing"),
        "unguarded_source_derived_count": len(unguarded_assets),
        "blocking_count": len(blockers),
        "missing_evidence_count": sum(1 for row in blockers if str(row.get("code") or "").endswith("_missing")),
        "production": production,
        "raw_source_text_included": False,
        "mutation_applied": False,
        "connector_execution_performed": False,
        "dispatch_applied": False,
        "rollback_applied": False,
    }
    gate = record_gate_result(
        storage,
        gate_kind=SOURCE_GOVERNANCE_RUNTIME_GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": "source-governance-runtime-gate-v1",
            "project_id": project_id,
            "environment": environment,
            "mode": mode,
            "production": production,
            "summary": summary,
            "blocking_rows": blockers,
            "readiness_path": str(readiness.get("path") or ""),
            "stale_sweep_path": str(stale_report.get("path") or ""),
            "retention_sweep_path": str(retention_report.get("path") or ""),
            "operator_action": _operator_action(blockers),
            "mutation_policy": "read-only: no connector execution, source apply, rollback, regeneration, or raw-source context injection",
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
        "readiness_report": readiness,
        "stale_sweep_report": stale_report,
        "retention_sweep_report": retention_report,
        "gate_result": gate,
    }


def _latest_source_report(storage: LocalStorage, *, project_id: str, tag: str) -> dict[str, Any]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, reverse=True, context=f"source runtime gate {tag}"):
            if data.get("type") != "change_impact_report":
                continue
            tags = {str(item) for item in data.get("tags", []) if str(item)} if isinstance(data.get("tags", []), list) else set()
            if tag not in tags:
                continue
            if project_id and _project_id(data) not in {"", project_id}:
                continue
            matches.append((path, data))
    if not matches:
        return {"status": "missing", "path": "", "summary": {"impacted_count": 0, "blocking_count": 0}}
    path, data = sorted(matches, key=lambda item: str(item[1].get("updated_at") or item[1].get("created_at") or ""))[-1]
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    impacted = content.get("impacted_assets", []) if isinstance(content.get("impacted_assets", []), list) else []
    severity_summary = content.get("severity_summary", {}) if isinstance(content.get("severity_summary", {}), dict) else {}
    status = "blocked" if int(severity_summary.get("blocking") or 0) else "review_required" if impacted else "clean"
    return {
        "status": status,
        "path": _display_path(storage.root, path),
        "asset": data,
        "summary": {
            "impacted_count": len(impacted),
            "blocking_count": int(severity_summary.get("blocking") or 0),
            "recommendation": str(content.get("recommendation") or ""),
        },
        "impacted_assets": impacted[:40],
    }


def _unguarded_source_derived_assets(storage: LocalStorage, *, project_id: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scanned = 0
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, context="source runtime gate unguarded source-derived scan"):
            if data.get("type") not in SOURCE_DERIVED_TYPES:
                continue
            if project_id and _project_id(data) not in {"", project_id}:
                continue
            if not _looks_source_derived(data):
                continue
            scanned += 1
            if _has_source_governance_evidence(data):
                continue
            rows.append(
                {
                    "code": "unguarded_source_derived_asset",
                    "severity": "high",
                    "path": _display_path(storage.root, path),
                    "asset_id": str(data.get("id") or ""),
                    "asset_type": str(data.get("type") or ""),
                    "reason": "source-derived asset lacks source eligibility/policy/risk evidence",
                    "operator_action": "attach SourcePolicy/SourceRiskReport/eligibility evidence or quarantine before context selection",
                }
            )
            if len(rows) >= limit or scanned >= limit:
                return rows
    return rows


def _blocking_rows(
    readiness: dict[str, Any],
    stale_report: dict[str, Any],
    retention_report: dict[str, Any],
    unguarded_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    readiness_status = str(readiness.get("status") or "")
    if readiness_status == "review_required":
        summary = readiness.get("summary", {}) if isinstance(readiness.get("summary", {}), dict) else {}
        rows.append(
            {
                "code": "source_guarded_apply_review_required",
                "severity": "high",
                "path": str(readiness.get("path") or ""),
                "reason": "source repair/invalidation readiness still requires review",
                "summary": summary,
            }
        )
    rows.extend(_report_blockers(stale_report, code="source_stale_quarantine_sweep"))
    rows.extend(_report_blockers(retention_report, code="source_retention_expiry_sweep"))
    rows.extend(unguarded_assets)
    return rows


def _report_blockers(report: dict[str, Any], *, code: str) -> list[dict[str, Any]]:
    status = str(report.get("status") or "missing")
    if status == "missing":
        return [
            {
                "code": f"{code}_missing",
                "severity": "high",
                "path": "",
                "reason": f"{code} evidence is missing",
                "operator_action": f"run {code.replace('_', ' ')} before production source-derived context selection",
            }
        ]
    impacted = report.get("impacted_assets", []) if isinstance(report.get("impacted_assets", []), list) else []
    if status in {"blocked", "review_required"} and impacted:
        return [
            {
                "code": f"{code}_impacted",
                "severity": "critical" if status == "blocked" else "high",
                "path": str(report.get("path") or ""),
                "reason": f"{code} found source-governance impacts that require review",
                "summary": report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {},
                "impacted_assets": impacted[:20],
            }
        ]
    return []


def _looks_source_derived(data: dict[str, Any]) -> bool:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    tags = {str(item).strip().lower() for item in data.get("tags", []) if str(item).strip()} if isinstance(data.get("tags", []), list) else set()
    return (
        "source-derived" in tags
        or "source-governance" in tags
        or bool(content.get("source_eligibility"))
        or any(str(metadata.get(key) or content.get(key) or "").strip() for key in _SOURCE_REF_FIELDS)
    )


def _has_source_governance_evidence(data: dict[str, Any]) -> bool:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_eligibility = content.get("source_eligibility") if isinstance(content.get("source_eligibility"), dict) else {}
    if source_eligibility and (source_eligibility.get("source_policy_ref") or source_eligibility.get("source_risk_report_ref") or source_eligibility.get("decision")):
        return True
    return any(str(metadata.get(key) or content.get(key) or "").strip() for key in _GOVERNANCE_REF_FIELDS)


def _project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _operator_action(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "source governance runtime evidence is ready"
    return "review source governance blockers, run required sweeps/readiness reports, attach source eligibility evidence, then rerun the gate"


def _strict_mode(*, environment: str, mode: str) -> bool:
    env = str(environment or "").strip().lower()
    run_mode = str(mode or "").strip().lower()
    return (
        is_production_environment(env)
        or is_production_environment(run_mode)
        or env in {"strict", "enforced", "operating_system"}
        or run_mode in {"strict", "enforced", "operating_system"}
    )


_SOURCE_REF_FIELDS = (
    "source_ref",
    "source_refs",
    "source_snapshot_ref",
    "source_snapshot_refs",
    "source_policy_ref",
    "source_policy_refs",
    "source_risk_report_ref",
    "source_risk_report_refs",
    "risk_report_path",
    "license_check_ref",
)

_GOVERNANCE_REF_FIELDS = (
    "source_policy_ref",
    "source_policy_refs",
    "source_risk_report_ref",
    "source_risk_report_refs",
    "risk_report_path",
    "license_check_ref",
    "source_eligibility_ref",
)
