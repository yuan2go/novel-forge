from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.os_envelope import enforce_os_envelope, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.production_governance import build_production_governance_report
from novel_forge.storage.local import LocalStorage

MODEL_OPERATION_PREFLIGHT_GATES = ["provider_runtime_gate", "os_envelope", "source_isolation"]
MODEL_OPERATION_FINAL_GATES = [*MODEL_OPERATION_PREFLIGHT_GATES, "operation_output"]


def enforce_model_operation_preflight(
    storage: LocalStorage,
    *,
    operation: str,
    environment: str = "",
    target_asset_id: str = "",
    target_asset_path: str | Path = "",
    project_id: str = "",
    workspace_path: str = "",
    asset_type: str = "",
    task_type: str = "",
    os_envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
    context_bundle_path: str = "",
    require_context_bundle: bool = False,
    extra_gate_statuses: dict[str, Any] | None = None,
    extra_required_gates: list[str] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed before a model/provider-assisted operation mutates production state."""

    policy = normalize_runtime_request_policy(
        envelope_payload=os_envelope,
        environment=environment,
        source_policy=source_policy,
        operation=operation,
    )
    resolved_environment = str(policy.get("environment") or environment or "")
    if not is_production_environment(resolved_environment):
        return {
            "status": "skipped",
            "blocking": False,
            "environment": resolved_environment or "dev",
            "source_policy": policy.get("source_policy", {}),
            "provider_runtime_gate": provider_runtime_gate or {},
            "path": "",
        }
    envelope = enforce_os_envelope(
        storage,
        envelope_payload=policy.get("envelope") if isinstance(policy.get("envelope"), dict) else os_envelope,
        operation=operation,
        project_id=project_id,
        task_type=task_type or operation,
        asset_type=asset_type,
        source_policy=policy.get("source_policy", {}),
        environment=resolved_environment,
        require_for_production=True,
    )
    gates = {
        "os_envelope": _os_envelope_gate(envelope),
        "source_isolation": _source_isolation_gate(policy.get("source_policy", {})),
    }
    if isinstance(provider_runtime_gate, dict) and provider_runtime_gate:
        gates["provider_runtime_gate"] = provider_runtime_gate
    required = list(MODEL_OPERATION_PREFLIGHT_GATES)
    if require_context_bundle:
        gates["context_bundle"] = _context_bundle_gate(context_bundle_path)
        required.append("context_bundle")
    gates.update(extra_gate_statuses or {})
    required.extend(extra_required_gates or [])
    report = build_production_governance_report(
        storage,
        operation=operation,
        environment=resolved_environment,
        target_asset_id=target_asset_id,
        target_asset_path=target_asset_path or target_asset_id or "data/runs/model-operation-preflight.json",
        project_id=project_id,
        workspace_path=workspace_path,
        gate_statuses=gates,
        required_gates=required,
        source_policy=policy.get("source_policy", {}),
        evidence_refs=_evidence_refs(envelope, provider_runtime_gate, context_bundle_path),
        rollback_plan={"rollback_action": "stop_before_model_call", "rollback_ref": str(target_asset_path or target_asset_id), "requires_operator_review": True},
        trace=trace or {"trace_id": envelope.get("trace_id", "")},
    )
    result = {
        **report,
        "environment": resolved_environment,
        "source_policy": policy.get("source_policy", {}),
        "os_envelope": envelope,
        "provider_runtime_gate": provider_runtime_gate or {},
        "required_gates": required,
    }
    if report.get("blocking"):
        raise RuntimeError(_blocked_message(operation, report.get("blocking_issues", []), preflight=True))
    return result


def record_model_operation_final_governance(
    storage: LocalStorage,
    *,
    operation: str,
    environment: str = "",
    output_asset_id: str = "",
    output_asset_path: str | Path = "",
    project_id: str = "",
    workspace_path: str = "",
    source_policy: dict[str, Any] | None = None,
    os_envelope: dict[str, Any] | None = None,
    provider_runtime_gate: dict[str, Any] | None = None,
    preflight_governance: dict[str, Any] | None = None,
    context_bundle_path: str = "",
    require_context_bundle: bool = False,
    extra_gate_statuses: dict[str, Any] | None = None,
    extra_required_gates: list[str] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record final governance evidence for a completed model/provider-assisted output."""

    policy = normalize_runtime_request_policy(
        envelope_payload=os_envelope or _preflight_envelope(preflight_governance),
        environment=environment or str((preflight_governance or {}).get("environment") or ""),
        source_policy=source_policy or _preflight_source_policy(preflight_governance),
        operation=operation,
    )
    resolved_environment = str(policy.get("environment") or environment or "")
    if not is_production_environment(resolved_environment):
        return {
            "status": "skipped",
            "blocking": False,
            "environment": resolved_environment or "dev",
            "source_policy": policy.get("source_policy", {}),
            "path": "",
        }
    envelope = _preflight_envelope(preflight_governance) or enforce_os_envelope(
        storage,
        envelope_payload=policy.get("envelope") if isinstance(policy.get("envelope"), dict) else os_envelope,
        operation=operation,
        project_id=project_id,
        task_type=operation,
        asset_type="",
        source_policy=policy.get("source_policy", {}),
        environment=resolved_environment,
        require_for_production=True,
    )
    provider_gate = provider_runtime_gate or _preflight_provider_gate(preflight_governance)
    gates = {
        "provider_runtime_gate": provider_gate,
        "os_envelope": _os_envelope_gate(envelope),
        "source_isolation": _source_isolation_gate(policy.get("source_policy", {})),
        "operation_output": _operation_output_gate(output_asset_path),
    }
    required = list(MODEL_OPERATION_FINAL_GATES)
    if require_context_bundle:
        gates["context_bundle"] = _context_bundle_gate(context_bundle_path)
        required.append("context_bundle")
    gates.update(extra_gate_statuses or {})
    required.extend(extra_required_gates or [])
    report = build_production_governance_report(
        storage,
        operation=operation,
        environment=resolved_environment,
        target_asset_id=output_asset_id,
        target_asset_path=output_asset_path or output_asset_id or "data/runs/model-operation-output.json",
        project_id=project_id,
        workspace_path=workspace_path,
        gate_statuses=gates,
        required_gates=required,
        source_policy=policy.get("source_policy", {}),
        evidence_refs=_evidence_refs(envelope, provider_gate, context_bundle_path, str((preflight_governance or {}).get("path") or "")),
        rollback_plan={"rollback_action": "quarantine_output_asset", "rollback_ref": _display_path(storage.root, output_asset_path), "requires_operator_review": True},
        trace=trace or {"trace_id": envelope.get("trace_id", "")},
    )
    result = {
        **report,
        "environment": resolved_environment,
        "source_policy": policy.get("source_policy", {}),
        "os_envelope": envelope,
        "provider_runtime_gate": provider_gate,
        "required_gates": required,
    }
    if report.get("blocking"):
        raise RuntimeError(_blocked_message(operation, report.get("blocking_issues", []), preflight=False))
    return result


def attach_model_operation_governance(storage: LocalStorage, asset_path: str | Path, governance: dict[str, Any]) -> None:
    if not governance or not governance.get("path"):
        return
    data = storage.read_json(asset_path)
    if not isinstance(data, dict):
        return
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    summary = {
        "status": str(governance.get("status") or ""),
        "path": str(governance.get("path") or ""),
        "gate_result_path": str(governance.get("gate_result_path") or ""),
        "blocking": bool(governance.get("blocking")),
        "required_gates": governance.get("required_gates", []),
    }
    content["production_governance"] = summary
    metadata["production_governance_status"] = summary["status"]
    metadata["production_governance_path"] = summary["path"]
    metadata["production_governance_gate_result_path"] = summary["gate_result_path"]
    data["content"] = content
    data["metadata"] = metadata
    references = [str(item) for item in data.get("references", []) if str(item).strip()]
    for ref in [summary["path"], summary["gate_result_path"]]:
        if ref and ref not in references:
            references.append(ref)
    data["references"] = references
    storage.write_json(asset_path, data)


def _os_envelope_gate(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict) or not envelope:
        return {"status": "missing", "blocking": True, "summary": {"reason": "os envelope missing"}}
    status = str(envelope.get("status") or "").strip().lower()
    return {"status": "passed" if status in {"enforced", "compat", "bypassed"} else "blocked", "blocking": status not in {"enforced", "compat", "bypassed"}, "path": str(envelope.get("trace_span_path") or ""), "summary": envelope}


def _source_isolation_gate(source_policy: Any) -> dict[str, Any]:
    policy = source_policy if isinstance(source_policy, dict) else {}
    if not policy:
        return {"status": "missing", "blocking": True, "summary": {"reason": "source policy missing"}}
    raw_allowed = any(bool(policy.get(key)) for key in ["raw_source_text_allowed", "raw_text_allowed", "source_chunk_raw_text_allowed"])
    required = policy.get("source_isolation_required", True)
    passed = bool(required) and not raw_allowed
    return {
        "status": "passed" if passed else "blocked",
        "blocking": not passed,
        "summary": {
            "source_isolation_required": required,
            "raw_source_text_allowed": raw_allowed,
            "policy": policy,
        },
    }


def _context_bundle_gate(path: str) -> dict[str, Any]:
    return {"status": "passed" if str(path or "").strip() else "missing", "blocking": not bool(str(path or "").strip()), "context_bundle_path": str(path or "")}


def _operation_output_gate(path: str | Path) -> dict[str, Any]:
    path_text = str(path or "")
    exists = bool(path_text) and Path(path).exists()
    return {"status": "passed" if exists else "missing", "blocking": not exists, "path": path_text}


def _preflight_envelope(preflight: dict[str, Any] | None) -> dict[str, Any]:
    return preflight.get("os_envelope", {}) if isinstance(preflight, dict) and isinstance(preflight.get("os_envelope"), dict) else {}


def _preflight_source_policy(preflight: dict[str, Any] | None) -> dict[str, Any]:
    return preflight.get("source_policy", {}) if isinstance(preflight, dict) and isinstance(preflight.get("source_policy"), dict) else {}


def _preflight_provider_gate(preflight: dict[str, Any] | None) -> dict[str, Any]:
    return preflight.get("provider_runtime_gate", {}) if isinstance(preflight, dict) and isinstance(preflight.get("provider_runtime_gate"), dict) else {}


def _evidence_refs(*values: Any) -> list[str]:
    refs: list[str] = []
    for value in values:
        if isinstance(value, dict):
            for key in ["path", "gate_result_path", "trace_span_path"]:
                ref = str(value.get(key) or "")
                if ref and ref not in refs:
                    refs.append(ref)
        else:
            ref = str(value or "")
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def _blocked_message(operation: str, issues: Any, *, preflight: bool) -> str:
    dimensions = ", ".join(str(issue.get("dimension") or "unknown") for issue in issues if isinstance(issue, dict))
    phase = "preflight" if preflight else "final"
    return f"{operation} production governance {phase} blocked: {dimensions or 'unknown'}"


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)
