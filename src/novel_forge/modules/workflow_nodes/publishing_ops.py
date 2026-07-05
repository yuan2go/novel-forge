from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.publishing import create_publish_gate_report, create_release_package
from novel_forge.storage.local import LocalStorage


def run_publish_gate_report_operation(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    chapter_audit_path: str | Path | None = None,
    human_override: bool = False,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> Path:
    return create_publish_gate_report(
        storage,
        draft_path,
        workspace_path=workspace_path,
        chapter_audit_path=chapter_audit_path,
        human_override=human_override,
        environment=environment,
        envelope=envelope,
        source_policy=source_policy,
    )


def run_release_package_operation(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    publish_gate_path: str | Path | None = None,
    channel: str = "local",
    human_override: bool = False,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> Path:
    return create_release_package(
        storage,
        draft_path,
        workspace_path=workspace_path,
        publish_gate_path=publish_gate_path,
        channel=channel,
        human_override=human_override,
        environment=environment,
        envelope=envelope,
        source_policy=source_policy,
    )

