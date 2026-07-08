from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.os_envelope import is_production_environment
from novel_forge.modules.production_governance import run_production_governance_drift_gate
from novel_forge.storage.local import LocalStorage


def run_publish_gate_report(
    storage: LocalStorage,
    *,
    input_path: str | Path,
    workspace_path: str | None,
    evidence: dict[str, Any],
    envelope: dict[str, Any] | None,
) -> dict[str, Any]:
    from novel_forge.modules.publishing import create_publish_gate_report

    result = {
        "path": create_publish_gate_report(
            storage,
            input_path,
            workspace_path=workspace_path or None,
            chapter_audit_path=evidence.get("chapter_audit_path") or None,
            human_override=bool(evidence.get("human_override", False)),
            environment=str(evidence.get("environment") or ""),
            envelope=envelope,
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
        )
    }
    return _attach_drift_gate(storage, result, evidence=evidence, envelope=envelope)


def run_release_package(
    storage: LocalStorage,
    *,
    input_path: str | Path,
    workspace_path: str | None,
    evidence: dict[str, Any],
    envelope: dict[str, Any] | None,
) -> dict[str, Any]:
    from novel_forge.modules.publishing import create_release_package

    result = {
        "path": create_release_package(
            storage,
            input_path,
            workspace_path=workspace_path or None,
            publish_gate_path=evidence.get("publish_gate_path") or None,
            channel=str(evidence.get("channel", "local")),
            human_override=bool(evidence.get("human_override", False)),
            environment=str(evidence.get("environment") or ""),
            envelope=envelope,
            source_policy=evidence.get("source_policy") if isinstance(evidence.get("source_policy"), dict) else None,
        )
    }
    return _attach_drift_gate(storage, result, evidence=evidence, envelope=envelope)


def _attach_drift_gate(storage: LocalStorage, result: dict[str, Any], *, evidence: dict[str, Any], envelope: dict[str, Any] | None) -> dict[str, Any]:
    environment = str(evidence.get("environment") or (envelope or {}).get("environment") or "")
    mode = str(evidence.get("mode") or evidence.get("runtime_mode") or "")
    if not _strict_mode(environment=environment, mode=mode):
        return result
    gate = run_production_governance_drift_gate(
        storage,
        project_id=str(evidence.get("project_id") or (envelope or {}).get("project_id") or ""),
        environment=environment,
        mode=mode,
        persist_report=True,
    )
    result["production_governance_drift_gate_path"] = gate.get("gate_result", {}).get("path", "")
    result["production_governance_drift_gate"] = {
        "status": gate.get("status", ""),
        "blocking": bool(gate.get("blocking")),
        "gate_result_path": gate.get("gate_result", {}).get("path", ""),
        "drift_report_path": gate.get("drift_report", {}).get("path", ""),
    }
    if gate.get("blocking"):
        raise RuntimeError(f"production governance drift gate failed: {gate.get('message', '')}")
    return result


def _strict_mode(*, environment: str = "", mode: str = "") -> bool:
    resolved = str(environment or mode or "").strip().lower()
    return is_production_environment(resolved) or resolved in {"strict", "enforced", "operating_system"}
