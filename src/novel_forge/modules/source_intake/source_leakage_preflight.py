from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


SOURCE_LEAKAGE_READINESS_SNAPSHOT_KIND = "source_leakage_readiness"
SOURCE_LEAKAGE_PREFLIGHT_GATE_KIND = "source_leakage_preflight"
SOURCE_LEAKAGE_READINESS_CONTRACT = "source-leakage-readiness-v1"
SOURCE_LEAKAGE_PREFLIGHT_GATE_CONTRACT = "source-leakage-preflight-gate-v1"

V1_SOURCE_LEAKAGE_REQUIRED_STAGES = (
    "topic",
    "worldbuilding",
    "character",
    "outline",
    "chapter_plan",
    "draft",
    "review",
    "revision",
)

RAW_CONTEXT_ASSET_TYPES = {
    "source_document",
    "source_chunk",
    "parallel_pair",
    "raw_document",
    "clean_document",
    "document_chunk",
}


def build_source_leakage_readiness_report(
    storage: LocalStorage,
    *,
    project_id: str = "",
    required_stages: list[str] | tuple[str, ...] | None = None,
    limit: int = 1000,
    persist: bool = True,
) -> dict[str, Any]:
    """Build a read-only source-leakage readiness snapshot over ContextBundle evidence."""

    storage.ensure_layout()
    stages = _dedupe([str(stage or "").strip() for stage in (required_stages or V1_SOURCE_LEAKAGE_REQUIRED_STAGES) if str(stage or "").strip()])
    bundles = _context_bundle_rows(storage, project_id=project_id, limit=max(1, int(limit or 1000)))
    latest_by_stage = _latest_context_bundle_by_stage(bundles)
    stage_rows = [_stage_readiness_row(stage, latest_by_stage.get(stage)) for stage in stages]
    missing_rows = [row for row in stage_rows if row["status"] == "missing"]
    failed_rows = [row for row in stage_rows if row["status"] == "failed"]
    passed_rows = [row for row in stage_rows if row["status"] == "passed"]
    evidence_paths = _dedupe([row["context_bundle_path"] for row in stage_rows if row.get("context_bundle_path")])
    status = "ready" if not missing_rows and not failed_rows else "missing" if not passed_rows and not failed_rows else "review_required"
    summary = {
        "required_stage_count": len(stages),
        "passed_stage_count": len(passed_rows),
        "missing_stage_count": len(missing_rows),
        "failed_stage_count": len(failed_rows),
        "context_bundle_count": len(bundles),
        "evidence_path_count": len(evidence_paths),
        "raw_source_text_included": any(row["summary"]["raw_source_selected_count"] or row["summary"]["raw_source_text_allowed"] for row in stage_rows),
        "high_risk_selected_count": sum(row["summary"]["high_risk_selected_count"] for row in stage_rows),
        "mutation_applied": False,
        "provider_call_executed": False,
        "connector_execution_performed": False,
        "chapter_acceptance_executed": False,
    }
    content = {
        "snapshot_kind": SOURCE_LEAKAGE_READINESS_SNAPSHOT_KIND,
        "contract": SOURCE_LEAKAGE_READINESS_CONTRACT,
        "status": status,
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "required_stages": stages,
        "stage_rows": stage_rows,
        "throughput": {
            "context_bundle_count": len(bundles),
            "required_stage_count": len(stages),
            "passed_stage_count": len(passed_rows),
        },
        "summary": summary,
        "quality": {
            "readiness_status": status,
            "all_required_stages_covered": not missing_rows,
            "all_required_stages_passed": not missing_rows and not failed_rows,
            "missing_stage_count": len(missing_rows),
            "failed_stage_count": len(failed_rows),
            "raw_source_text_included": summary["raw_source_text_included"],
            "high_risk_selected_count": summary["high_risk_selected_count"],
        },
        "task_health": {
            "missing_stage_count": len(missing_rows),
            "failed_stage_count": len(failed_rows),
            "operator_action": _readiness_operator_action(status, missing_rows, failed_rows),
        },
        "agent_health": {
            "planned_agent_operations": [],
            "dispatch_boundary": "readiness report does not enqueue, dispatch, recover, or run AgentTasks",
        },
        "storage_health": {
            "evidence_path_count": len(evidence_paths),
            "asset_type": "project_metric_snapshot",
            "source_asset_types": ["context_bundle"],
        },
        "recommendations": [_readiness_operator_action(status, missing_rows, failed_rows)],
        "focused_regression_bundle": {
            "command": "python3 scripts/run_source_governance_regression.py",
            "test": "tests.unit.test_context_builder_stage_profiles.ContextBuilderStageProfileTests.test_v1_stage_profiles_reject_raw_and_high_risk_source_derived_assets",
            "script": "scripts/run_source_governance_regression.py",
            "default_exclusions": ["connector_execution", "provider_proof", "chapter_acceptance", "external_corpus_import"],
        },
        "evidence_paths": evidence_paths,
        "operator_action": _readiness_operator_action(status, missing_rows, failed_rows),
        "mutation_policy": "read-only: scans context bundle evidence only; does not mutate source, context, provider, connector, or chapter assets",
    }
    asset = ProjectMetricSnapshot(
        title=f"Source leakage readiness {project_id or 'workspace'}",
        tags=["source-governance", "source-leakage", status],
        content=content,
        metadata={
            "project_id": project_id,
            "snapshot_kind": SOURCE_LEAKAGE_READINESS_SNAPSHOT_KIND,
            "asset_status": status,
            "use_in_generation_rag": False,
        },
        references=filter_project_safe_references(storage, project_id, evidence_paths),
    )
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = ""
    if persist:
        path = _display_path(storage.root, storage.write_asset_auto(asset))
        data = storage.read_json(storage.root / path)
    return {"status": status, "path": path, "asset": data, "summary": summary, "stage_rows": stage_rows}


def run_source_leakage_preflight_gate(
    storage: LocalStorage,
    *,
    project_id: str = "",
    environment: str = "",
    mode: str = "",
    required_stages: list[str] | tuple[str, ...] | None = None,
    persist_readiness: bool = True,
    limit: int = 1000,
) -> dict[str, Any]:
    """Write a read-only gate over source-leakage readiness evidence."""

    readiness = build_source_leakage_readiness_report(
        storage,
        project_id=project_id,
        required_stages=required_stages,
        limit=limit,
        persist=persist_readiness,
    )
    stage_rows = readiness.get("stage_rows", []) if isinstance(readiness.get("stage_rows", []), list) else []
    blockers = [row for row in stage_rows if isinstance(row, dict) and row.get("status") in {"missing", "failed"}]
    production = _strict_mode(environment=environment, mode=mode)
    status = "passed" if not blockers else "failed" if production else "warning"
    summary = dict(readiness.get("summary", {}) if isinstance(readiness.get("summary", {}), dict) else {})
    summary.update(
        {
            "blocking_count": len(blockers),
            "production": production,
            "read_only": True,
            "repair_executed": False,
            "provider_call_executed": False,
            "chapter_acceptance_executed": False,
        }
    )
    evidence_paths = _dedupe([str(readiness.get("path") or ""), *[str(row.get("context_bundle_path") or "") for row in stage_rows if isinstance(row, dict)]])
    message = "source leakage preflight gate passed" if status == "passed" else f"source leakage preflight gate has {len(blockers)} blocker(s)"
    gate = record_gate_result(
        storage,
        gate_kind=SOURCE_LEAKAGE_PREFLIGHT_GATE_KIND,
        status=status,
        target_paths=evidence_paths,
        result={
            "contract": SOURCE_LEAKAGE_PREFLIGHT_GATE_CONTRACT,
            "project_id": project_id,
            "environment": environment,
            "mode": mode,
            "production": production,
            "readiness_path": str(readiness.get("path") or ""),
            "summary": summary,
            "stage_rows": stage_rows,
            "blockers": blockers,
            "operator_action": _gate_operator_action(status, blockers),
            "mutation_policy": "read-only: no source repair, connector execution, provider call, context mutation, or chapter acceptance",
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
        "readiness_report": readiness,
        "gate_result": gate,
        "gate_result_path": str(gate.get("path") or ""),
    }


def _context_bundle_rows(storage: LocalStorage, *, project_id: str, limit: int) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for category in DATA_DIRS:
        for path, data in iter_json_objects(storage, category, reverse=True, context="source leakage readiness context bundle scan"):
            if data.get("type") != "context_bundle":
                continue
            if project_id and _project_id(data) not in {"", project_id}:
                continue
            rows.append((path, data))
            if len(rows) >= limit:
                return rows
    return rows


def _latest_context_bundle_by_stage(rows: list[tuple[Path, dict[str, Any]]]) -> dict[str, tuple[Path, dict[str, Any]]]:
    latest: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, data in rows:
        stage = _bundle_stage(data)
        if not stage:
            continue
        current = latest.get(stage)
        if current is None or _sort_key(data) >= _sort_key(current[1]):
            latest[stage] = (path, data)
    return latest


def _stage_readiness_row(stage: str, bundle: tuple[Path, dict[str, Any]] | None) -> dict[str, Any]:
    if bundle is None:
        return {
            "stage": stage,
            "status": "missing",
            "context_bundle_path": "",
            "context_bundle_id": "",
            "failure_rows": [
                {
                    "code": "context_bundle_stage_evidence_missing",
                    "severity": "high",
                    "message": f"no context bundle source-isolation evidence found for {stage}",
                    "operator_action": f"run governed {stage} context build before final source-leakage preflight",
                }
            ],
            "summary": {
                "raw_source_text_allowed": False,
                "selected_asset_count": 0,
                "policy_rejection_count": 0,
                "raw_source_selected_count": 0,
                "high_risk_selected_count": 0,
            },
        }
    path, data = bundle
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    failures = _bundle_leakage_failures(data)
    selected_assets = content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else []
    policy_rejections = content.get("policy_rejections", []) if isinstance(content.get("policy_rejections", []), list) else []
    return {
        "stage": stage,
        "status": "failed" if failures else "passed",
        "context_bundle_path": _display_path_from_path(path),
        "context_bundle_id": str(data.get("id") or ""),
        "failure_rows": failures,
        "source_isolation": content.get("source_isolation", {}) if isinstance(content.get("source_isolation", {}), dict) else {},
        "source_governance_runtime_gate": content.get("source_governance_runtime_gate", {}) if isinstance(content.get("source_governance_runtime_gate", {}), dict) else {},
        "summary": {
            "raw_source_text_allowed": bool((content.get("source_isolation", {}) if isinstance(content.get("source_isolation", {}), dict) else {}).get("raw_source_text_allowed", False)),
            "selected_asset_count": len(selected_assets),
            "policy_rejection_count": len(policy_rejections),
            "raw_source_selected_count": sum(1 for item in selected_assets if isinstance(item, dict) and _is_raw_context_asset(item)),
            "high_risk_selected_count": sum(1 for item in selected_assets if isinstance(item, dict) and _selected_asset_blocks_context(item)),
        },
    }


def _bundle_leakage_failures(data: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_isolation = content.get("source_isolation", {}) if isinstance(content.get("source_isolation", {}), dict) else {}
    if bool(source_isolation.get("raw_source_text_allowed", False)):
        failures.append(
            {
                "code": "raw_source_text_allowed",
                "severity": "critical",
                "message": "context bundle allows raw source text in generation context",
                "operator_action": "rebuild context bundle with source isolation raw_source_text_allowed=false",
            }
        )
    selected_assets = content.get("selected_assets", []) if isinstance(content.get("selected_assets", []), list) else []
    for item in selected_assets:
        if not isinstance(item, dict):
            continue
        if _is_raw_context_asset(item):
            failures.append(
                {
                    "code": "raw_source_asset_selected",
                    "severity": "critical",
                    "path": str(item.get("path") or ""),
                    "asset_type": _asset_type(item),
                    "message": "raw source asset was selected into context",
                    "operator_action": "remove raw source assets and keep only abstract, policy-cleared evidence",
                }
            )
        if _selected_asset_blocks_context(item):
            failures.append(
                {
                    "code": "blocked_source_eligibility_selected",
                    "severity": "critical",
                    "path": str(item.get("path") or ""),
                    "asset_type": _asset_type(item),
                    "source_eligibility": item.get("source_eligibility", {}) if isinstance(item.get("source_eligibility", {}), dict) else {},
                    "message": "high-risk or evidence-only source-derived asset was selected into context",
                    "operator_action": "rerun context selection after source policy/risk review or keep this asset evidence-only",
                }
            )
    return failures


def _is_raw_context_asset(item: dict[str, Any]) -> bool:
    return _asset_type(item) in RAW_CONTEXT_ASSET_TYPES


def _selected_asset_blocks_context(item: dict[str, Any]) -> bool:
    eligibility = item.get("source_eligibility", {}) if isinstance(item.get("source_eligibility", {}), dict) else {}
    if not eligibility:
        return False
    status = str(eligibility.get("status") or eligibility.get("decision") or "").strip().lower()
    risk = str(eligibility.get("risk_level") or eligibility.get("risk_tier") or "").strip().upper()
    if bool(eligibility.get("quarantine", False)):
        return True
    if status in {"blocked", "failed", "rejected", "deny", "denied"}:
        return True
    if bool(eligibility.get("evidence_only", False)):
        return True
    if eligibility.get("generation_context_allowed") is False:
        return True
    return risk in {"R3", "R4"} and eligibility.get("generation_context_allowed") is not True


def _asset_type(item: dict[str, Any]) -> str:
    return str(item.get("asset_type") or item.get("type") or "").strip()


def _bundle_stage(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    contract = content.get("stage_context_contract", {}) if isinstance(content.get("stage_context_contract", {}), dict) else {}
    return str(contract.get("stage") or content.get("stage") or content.get("context_profile") or metadata.get("stage") or metadata.get("context_profile") or "").strip()


def _project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _readiness_operator_action(status: str, missing_rows: list[dict[str, Any]], failed_rows: list[dict[str, Any]]) -> str:
    if status == "ready":
        return "source-leakage readiness evidence is ready for final preflight"
    if failed_rows:
        return "rebuild failed context bundles so raw/high-risk source assets remain evidence-only"
    if missing_rows:
        return "build governed context bundles for all v1 stages before final source-leakage preflight"
    return "review source-leakage readiness evidence"


def _gate_operator_action(status: str, blockers: list[dict[str, Any]]) -> str:
    if status == "passed":
        return "source-leakage preflight evidence is ready"
    if blockers:
        return "resolve missing/failed source-leakage stage evidence before final acceptance"
    return "review source-leakage preflight evidence"


def _strict_mode(*, environment: str, mode: str) -> bool:
    env = str(environment or "").strip().lower()
    run_mode = str(mode or "").strip().lower()
    return (
        is_production_environment(env)
        or is_production_environment(run_mode)
        or env in {"strict", "enforced", "operating_system"}
        or run_mode in {"strict", "enforced", "operating_system"}
    )


def _sort_key(data: dict[str, Any]) -> str:
    return str(data.get("updated_at") or data.get("created_at") or data.get("id") or "")


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _display_path_from_path(path: Path) -> str:
    try:
        return str(path.relative_to(path.parents[2]))
    except (IndexError, ValueError):
        return str(path)


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
