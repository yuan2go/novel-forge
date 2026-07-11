from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.modules.os_envelope import enforce_os_envelope
from novel_forge.modules.production_kernel.entrypoints import require_production_entrypoint
from novel_forge.storage.local import LocalStorage


def dispatch_chapter_production(storage: LocalStorage, **command: Any) -> dict[str, Any]:
    """Single facade for chapter-production commands.

    The facade deliberately delegates lifecycle ownership to ChapterProductionRun;
    it does not introduce a second Run or Task state machine.
    """
    entrypoint = require_production_entrypoint("chapter_production.start")
    environment = str(command.get("environment") or "")
    envelope_payload = command.get("os_envelope") if isinstance(command.get("os_envelope"), dict) else None
    # The bus repeats this check with project-bound defaults. This early check
    # protects API/worker callers before they resolve or write a run.
    if envelope_payload is not None and str(envelope_payload.get("project_ref") or envelope_payload.get("project_id") or "").strip():
        enforce_os_envelope(
            storage,
            envelope_payload=envelope_payload,
            operation=entrypoint["operation"],
            project_id=str(envelope_payload.get("project_ref") or envelope_payload.get("project_id") or ""),
            task_type="chapter_production",
            asset_type="chapter_production_run",
            actor_type="production_kernel",
            source="production_kernel",
            source_policy=command.get("source_policy") if isinstance(command.get("source_policy"), dict) else None,
            environment=environment,
            require_for_production=True,
            record_trace=False,
        )
    elif envelope_payload is None and environment.strip().lower() in {"production", "prod", "operating_system", "strict"}:
        # Avoid a trace write for a rejected command; the bus independently
        # enforces as a defense-in-depth check for direct service callers.
        raise ValueError("OS envelope required for production operation chapter_production.start")

    from novel_forge.modules.chapter_production_bus import start_chapter_production

    return start_chapter_production(storage, **command)
