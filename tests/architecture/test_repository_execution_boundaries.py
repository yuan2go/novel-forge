from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
)
from novel_forge.tools.production_execution_inventory import (
    scan_repository_execution_boundaries,
)


ROOT = Path(__file__).resolve().parents[2]
EXECUTION_PLANE = ROOT / "src/novel_forge/modules/production_execution"
BACKEND_FILES = (
    EXECUTION_PLANE / "backends.py",
    EXECUTION_PLANE / "external_action_backend.py",
    EXECUTION_PLANE / "agent_workspace_backend.py",
)


class _LegacyAdapter:
    provider = "legacy-provider"
    production_execution_gateway_backed = False

    def execute(self, **kwargs):
        raise AssertionError(f"legacy adapter must not execute: {kwargs}")


class RepositoryExecutionBoundaryTests(unittest.TestCase):
    def test_repository_ast_execution_boundary_has_no_business_violation(
        self,
    ) -> None:
        self.assertEqual(scan_repository_execution_boundaries(ROOT), [])

    def test_execution_plane_imports_no_business_domain_module(self) -> None:
        violations: list[tuple[str, str]] = []
        allowed = (
            "novel_forge.modules.production_execution",
            "novel_forge.modules.provider_control",
            "novel_forge.modules.command_kernel",
        )
        for path in EXECUTION_PLANE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not node.module.startswith("novel_forge.modules."):
                    continue
                if not node.module.startswith(allowed):
                    violations.append((path.name, node.module))
        self.assertEqual(violations, [])

    def test_backends_cannot_activate_approve_or_commit_domain_assets(
        self,
    ) -> None:
        forbidden = {
            "activate",
            "activate_asset",
            "approve",
            "approve_asset",
            "bind_blob_to_asset_version",
            "commit_asset",
            "materialize_output",
            "write_asset",
        }
        violations: list[tuple[str, int, str]] = []
        for path in BACKEND_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in forbidden:
                    violations.append((path.name, node.lineno, name))
        self.assertEqual(violations, [])

    def test_reducers_do_not_call_execution_gateway(self) -> None:
        violations: list[tuple[str, str, int]] = []
        for path in (ROOT / "src/novel_forge/modules").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) or "reduc" not in node.name.lower():
                    continue
                source = ast.get_source_segment(
                    path.read_text(encoding="utf-8"), node
                ) or ""
                for marker in (
                    "ProductionExecutionGateway",
                    "execute_domain_candidate",
                    "execute_external_action",
                    "execution_port.",
                    "gateway.submit",
                ):
                    if marker in source:
                        violations.append(
                            (
                                str(path.relative_to(ROOT)),
                                node.name,
                                node.lineno,
                            )
                        )
        self.assertEqual(violations, [])

    def test_controlled_external_effect_blocks_legacy_before_database(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"NOVEL_FORGE_ENVIRONMENT": "production"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "legacy execution is blocked"):
                dispatch_external_effect(
                    "postgresql://must-not-connect",
                    EffectCommandContext(
                        operation_id="operation:guard:1",
                        project_id="project:guard:1",
                        actor_id="actor:guard:1",
                        trace_id="trace:guard:1",
                        correlation_id="correlation:guard:1",
                    ),
                    effect_id="effect:guard:1",
                    worker_id="worker:guard:1",
                    lease_seconds=30,
                    adapter=_LegacyAdapter(),
                )

if __name__ == "__main__":
    unittest.main()
