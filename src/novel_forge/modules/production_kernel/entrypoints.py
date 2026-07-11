from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


_COMMON_POLICY = {
    "parent_state_owner": "production_operation",
    "kernel_route": "dispatch_production_operation",
    "environment_policy": "production_requires_envelope_and_registered_kernel_route",
    "envelope_policy": "required_in_production",
    "approval_policy": "operation_policy_and_downstream_gate",
    "required_evidence": "execution_envelope,project_scope,idempotency_key,trace_span",
    "lifecycle_capabilities": "start,pause,resume,cancel,recover",
    "idempotency_scope": "project_operation",
    "retry_class": "child_owned",
    "compensation_class": "child_owned_or_manual",
}


def _entry(operation: str, state_owner: str, **overrides: str) -> dict[str, str]:
    return {**_COMMON_POLICY, "operation": operation, "state_owner": state_owner, **overrides}


_ENTRYPOINTS: tuple[dict[str, str], ...] = (
    _entry("chapter_production.start", "chapter_production_run", lifecycle_capabilities="start,pause,resume,cancel,recover,retry"),
    _entry("workflow.execute", "workflow_run", lifecycle_capabilities="start,resume,recover,retry"),
    _entry("agent.dispatch", "agent_run", lifecycle_capabilities="start,resume,recover,retry,dead_letter"),
    _entry("loop.run", "loop_run", lifecycle_capabilities="start,cancel,retry"),
    _entry("review_revision_publish", "loop_run", lifecycle_capabilities="start,cancel,retry", approval_policy="review_issue_and_publish_gate"),
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
        aliases = _runner_aliases(tree, targets)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _called_runner(node.func, aliases, targets)
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


def _runner_aliases(tree: ast.AST, targets: set[str]) -> dict[str, str]:
    """Resolve direct imports and simple aliases without executing source code."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name in targets:
                    aliases[imported.asname or imported.name] = imported.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            source = _called_runner(node.value, aliases, targets)
            if source:
                aliases[node.targets[0].id] = source
    return aliases


def _called_runner(node: ast.AST, aliases: dict[str, str], targets: set[str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id if node.id in targets else "")
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in targets else ""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        name = node.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str) and name.value in targets:
            return name.value
    return ""
