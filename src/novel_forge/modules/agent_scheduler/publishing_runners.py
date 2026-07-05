from __future__ import annotations

from pathlib import Path
from typing import Any

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

    return {
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


def run_release_package(
    storage: LocalStorage,
    *,
    input_path: str | Path,
    workspace_path: str | None,
    evidence: dict[str, Any],
    envelope: dict[str, Any] | None,
) -> dict[str, Any]:
    from novel_forge.modules.publishing import create_release_package

    return {
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
