from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_governance import build_production_governance_report
from novel_forge.storage.local import LocalStorage


PREFLIGHT_GATES = ["os_envelope", "scheduler_dispatch", "operation_contract", "source_isolation", "provider_runtime_gate"]
FINAL_GATES = [*PREFLIGHT_GATES, "operation_output"]


def enforce_scheduler_preflight_governance(
    storage: LocalStorage,
    *,
    operation: str,
    environment: str,
    queue_path: str | Path,
    agent_run_path: str | Path,
    queue_item: dict[str, Any],
    agent_run: dict[str, Any],
) -> dict[str, Any]:
    if not is_production_environment(environment):
        return {}
    return _build_scheduler_governance(
        storage,
        operation=operation,
        phase="preflight",
        environment=environment,
        queue_path=queue_path,
        agent_run_path=agent_run_path,
        queue_item=queue_item,
        agent_run=agent_run,
        output_assets=[],
        required_gates=PREFLIGHT_GATES,
    )


def enforce_scheduler_final_governance(
    storage: LocalStorage,
    *,
    operation: str,
    environment: str,
    queue_path: str | Path,
    agent_run_path: str | Path,
    queue_item: dict[str, Any],
    agent_run: dict[str, Any],
    output_assets: list[str],
    preflight_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_production_environment(environment):
        return {}
    return _build_scheduler_governance(
        storage,
        operation=operation,
        phase="completed",
        environment=environment,
        queue_path=queue_path,
        agent_run_path=agent_run_path,
        queue_item=queue_item,
        agent_run=agent_run,
        output_assets=output_assets,
        required_gates=FINAL_GATES,
        preflight_report=preflight_report or {},
    )


def _build_scheduler_governance(
    storage: LocalStorage,
    *,
    operation: str,
    phase: str,
    environment: str,
    queue_path: str | Path,
    agent_run_path: str | Path,
    queue_item: dict[str, Any],
    agent_run: dict[str, Any],
    output_assets: list[str],
    required_gates: list[str],
    preflight_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_content = agent_run.get("content", {}) if isinstance(agent_run.get("content", {}), dict) else {}
    run_metadata = agent_run.get("metadata", {}) if isinstance(agent_run.get("metadata", {}), dict) else {}
    evidence = run_content.get("evidence", {}) if isinstance(run_content.get("evidence", {}), dict) else {}
    contract_path = str(run_content.get("contract_path") or "")
    target_path = _display_path(storage.root, agent_run_path)
    queue_ref = _display_path(storage.root, queue_path)
    output_refs = [_display_path(storage.root, item) for item in output_assets]
    report = build_production_governance_report(
        storage,
        operation=f"agent_scheduler.{operation}" if phase == "completed" else f"agent_scheduler.{operation}.{phase}",
        environment=environment,
        target_asset_id=str(run_content.get("run_id") or agent_run.get("id") or operation),
        target_asset_path=agent_run_path,
        project_id=str(run_metadata.get("project_id") or evidence.get("project_id") or ""),
        workspace_path=str(run_metadata.get("workspace_path") or evidence.get("workspace_path") or ""),
        gate_statuses={
            "os_envelope": _os_envelope_gate(evidence),
            "scheduler_dispatch": {"status": "passed", "path": queue_ref, "summary": {"dispatch_id": _dispatch_id(queue_item)}},
            "operation_contract": _contract_gate(storage, contract_path),
            "source_isolation": _source_isolation_gate(evidence),
            "provider_runtime_gate": _provider_runtime_gate(storage, evidence),
            "operation_output": _output_gate(storage, output_refs),
        },
        required_gates=required_gates,
        source_policy=_source_policy(evidence),
        evidence_refs=[queue_ref, target_path, contract_path, *(output_refs or []), str((preflight_report or {}).get("path", ""))],
        rollback_plan={
            "rollback_action": "scheduler_retry_or_dead_letter",
            "rollback_ref": queue_ref,
            "requires_operator_review": True,
        },
        trace={"trace_id": _trace_id(evidence)},
    )
    if report["blocking"]:
        raise RuntimeError(_blocked_message(operation, report["blocking_issues"]))
    return report


def _os_envelope_gate(evidence: dict[str, Any]) -> dict[str, Any]:
    envelope = evidence.get("os_envelope") if isinstance(evidence.get("os_envelope"), dict) else evidence.get("envelope") if isinstance(evidence.get("envelope"), dict) else {}
    if not isinstance(envelope, dict) or not envelope:
        return {"status": "missing", "blocking": True, "summary": {"reason": "production scheduler run requires OS envelope"}}
    return {"status": "passed", "summary": {"envelope_id": envelope.get("envelope_id", ""), "trace_id": envelope.get("trace_id", "")}}


def _contract_gate(storage: LocalStorage, contract_path: str) -> dict[str, Any]:
    if not contract_path:
        return {"status": "missing", "blocking": True, "summary": {"reason": "agent contract path is missing"}}
    try:
        exists = resolve_path(storage.root, contract_path).exists()
    except Exception:
        exists = False
    return {"status": "passed" if exists else "missing", "blocking": not exists, "path": contract_path, "summary": {"contract_path": contract_path}}


def _source_isolation_gate(evidence: dict[str, Any]) -> dict[str, Any]:
    policy = _source_policy(evidence)
    if not policy:
        return {"status": "missing", "blocking": True, "summary": {"reason": "source policy evidence is missing"}}
    return {"status": "passed", "summary": policy}


def _provider_runtime_gate(storage: LocalStorage, evidence: dict[str, Any]) -> dict[str, Any]:
    gate = evidence.get("provider_runtime_guard") if isinstance(evidence.get("provider_runtime_guard"), dict) else evidence.get("provider_runtime_gate") if isinstance(evidence.get("provider_runtime_gate"), dict) else {}
    if not isinstance(gate, dict) or not gate:
        inherited = _provider_gate_from_publish_gate(storage, evidence)
        if inherited:
            return inherited
        return {"status": "missing", "blocking": True, "summary": {"reason": "provider runtime evidence is missing"}}
    return gate


def _provider_gate_from_publish_gate(storage: LocalStorage, evidence: dict[str, Any]) -> dict[str, Any]:
    publish_gate_ref = str(evidence.get("publish_gate_path") or "").strip()
    if not publish_gate_ref:
        return {}
    try:
        gate = storage.read_json(resolve_path(storage.root, publish_gate_ref))
    except Exception:
        return {}
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    governance = content.get("production_governance", {}) if isinstance(content.get("production_governance", {}), dict) else {}
    status = str(governance.get("status") or "").strip().lower()
    if status == "passed" and governance.get("path"):
        return {
            "status": "passed",
            "path": str(governance.get("path") or ""),
            "summary": {
                "source": "publish_gate_production_governance",
                "publish_gate_path": publish_gate_ref,
                "production_governance_path": str(governance.get("path") or ""),
            },
        }
    return {}


def _output_gate(storage: LocalStorage, output_refs: list[str]) -> dict[str, Any]:
    if not output_refs:
        return {"status": "missing", "blocking": True, "summary": {"reason": "scheduler operation produced no output asset"}}
    missing = [ref for ref in output_refs if not resolve_path(storage.root, ref).exists()]
    return {"status": "passed" if not missing else "missing", "blocking": bool(missing), "path": output_refs[0], "summary": {"output_assets": output_refs, "missing": missing}}


def _source_policy(evidence: dict[str, Any]) -> dict[str, Any]:
    if isinstance(evidence.get("source_policy"), dict) and evidence["source_policy"]:
        return evidence["source_policy"]
    envelope = evidence.get("os_envelope") if isinstance(evidence.get("os_envelope"), dict) else evidence.get("envelope") if isinstance(evidence.get("envelope"), dict) else {}
    if isinstance(envelope, dict) and isinstance(envelope.get("source_policy"), dict):
        return envelope["source_policy"]
    return {}


def _dispatch_id(queue_item: dict[str, Any]) -> str:
    content = queue_item.get("content", {}) if isinstance(queue_item.get("content", {}), dict) else {}
    return str(content.get("dispatch_id") or queue_item.get("dispatch_id") or "")


def _trace_id(evidence: dict[str, Any]) -> str:
    trace = evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {}
    envelope = evidence.get("os_envelope") if isinstance(evidence.get("os_envelope"), dict) else evidence.get("envelope") if isinstance(evidence.get("envelope"), dict) else {}
    return str(trace.get("trace_id") or envelope.get("trace_id") or "")


def _blocked_message(operation: str, issues: list[dict[str, Any]]) -> str:
    dimensions = ", ".join(str(issue.get("dimension") or "") for issue in issues if isinstance(issue, dict))
    return f"agent scheduler production governance blocked {operation}: {dimensions}"


def _display_path(root: Path, path: str | Path) -> str:
    resolved = resolve_path(root, path)
    return str(resolved.relative_to(root)) if resolved.is_absolute() and resolved.is_relative_to(root) else str(resolved)
