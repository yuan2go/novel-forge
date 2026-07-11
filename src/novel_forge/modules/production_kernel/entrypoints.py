from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


_ENTRYPOINTS: tuple[dict[str, str], ...] = (
    {"operation": "chapter_production.start", "state_owner": "chapter_production_run", "parent_state_owner": "production_operation", "kernel_route": "dispatch_production_operation", "envelope_policy": "required_in_production"},
    {"operation": "workflow.execute", "state_owner": "workflow_run", "parent_state_owner": "production_operation", "kernel_route": "dispatch_production_operation", "envelope_policy": "required_in_production"},
    {"operation": "agent.dispatch", "state_owner": "agent_run", "parent_state_owner": "production_operation", "kernel_route": "dispatch_production_operation", "envelope_policy": "required_in_production"},
    {"operation": "loop.run", "state_owner": "loop_run", "parent_state_owner": "production_operation", "kernel_route": "dispatch_production_operation", "envelope_policy": "required_in_production"},
    {"operation": "review_revision_publish", "state_owner": "loop_run", "parent_state_owner": "production_operation", "kernel_route": "dispatch_production_operation", "envelope_policy": "required_in_production"},
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


def production_entrypoint_audit(*, repo_root: str | Path | None = None) -> dict[str, Any]:
    """Find direct calls to registered production child runners outside Kernel.

    This is a conservative static scan. It is a bypass detector, not a proof
    that every dynamic or reflective call is safe; production callers must use
    the Kernel dispatcher and any finding is review-required until migrated.
    """

    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[4]
    source_root = root / "src" / "novel_forge"
    targets = {"dispatch_chapter_production", "execute_workflow", "dispatch_agent_run", "run_loop"}
    rows: list[dict[str, Any]] = []
    if not source_root.exists():
        return {"repo_root": str(root), "summary": {"candidate_count": 0, "review_required_count": 0, "kernel_internal_count": 0}, "findings": []}
    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        relative = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if called not in targets:
                continue
            status = "kernel_internal" if relative == "src/novel_forge/modules/production_kernel/service.py" else "review_required"
            rows.append({"path": relative, "line": int(getattr(node, "lineno", 0)), "symbol": called, "status": status})
    review_required = [row for row in rows if row["status"] == "review_required"]
    return {
        "repo_root": str(root),
        "summary": {
            "candidate_count": len(rows),
            "review_required_count": len(review_required),
            "kernel_internal_count": len(rows) - len(review_required),
        },
        "findings": rows,
        "recommendation": "route every review_required call through dispatch_production_operation" if review_required else "no direct child-runner calls outside Production Kernel were found",
    }
