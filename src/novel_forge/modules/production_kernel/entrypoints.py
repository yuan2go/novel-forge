from __future__ import annotations

from typing import Any


_ENTRYPOINTS: tuple[dict[str, str], ...] = (
    {"operation": "chapter_production.start", "state_owner": "chapter_production_run", "kernel_route": "dispatch_chapter_production", "envelope_policy": "required_in_production"},
    {"operation": "workflow.execute", "state_owner": "workflow_run", "kernel_route": "compat_pending", "envelope_policy": "required_in_production"},
    {"operation": "agent.dispatch", "state_owner": "agent_run", "kernel_route": "compat_pending", "envelope_policy": "required_in_production"},
    {"operation": "loop.run", "state_owner": "loop_run", "kernel_route": "compat_pending", "envelope_policy": "required_in_production"},
    {"operation": "review_revision_publish", "state_owner": "loop_run", "kernel_route": "compat_pending", "envelope_policy": "required_in_production"},
)


def production_entrypoints() -> list[dict[str, str]]:
    """Return the audited production-command registry, never a mutable global."""
    return [dict(item) for item in _ENTRYPOINTS]


def require_production_entrypoint(operation: str) -> dict[str, str]:
    normalized = str(operation or "").strip()
    for entrypoint in _ENTRYPOINTS:
        if entrypoint["operation"] == normalized:
            return dict(entrypoint)
    raise ValueError(f"unregistered production operation: {normalized}")
