from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_forge.infrastructure.legacy_http import (
    development_only_http_request,
)
from novel_forge.model_adapters.embeddings import (
    OpenAICompatibleEmbeddingAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
)
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainModelOperation,
    ExternalActionCandidate,
    ExternalActionExecutionEvidence,
    execute_domain_candidate,
)
from novel_forge.modules.clickhouse_analytics.service import _clickhouse_execute
from novel_forge.modules.tool_gateway.service import _mcp_json_rpc
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


class _LegacyModel:
    def __init__(self) -> None:
        self.called = False

    def generate(self, *args, **kwargs):
        self.called = True
        raise AssertionError(f"legacy model must not execute: {args}, {kwargs}")


class _ExternalActionFixturePort:
    def __init__(self) -> None:
        self.capabilities: list[str] = []

    def execute(self, command):
        self.capabilities.append(command.capability)
        return ExternalActionCandidate(
            raw_output={
                "result": {"tools": []},
                "status": "ok",
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
            evidence=ExternalActionExecutionEvidence(
                execution_id=f"execution:{command.capability}",
                operation_id=f"operation:{command.capability}",
                attempt_id=f"attempt:{command.capability}",
                fencing_token=1,
                capability=command.capability,
                backend_id="remote-external-action",
                route_snapshot_id=f"route:{command.capability}",
                input_manifest_ref=f"input:{command.capability}",
                output_manifest_ref=f"output:{command.capability}",
                validation_manifest_ref=f"validation:{command.capability}",
                external_receipt_ref=f"receipt:{command.capability}",
                usage_receipt_ref=f"usage:{command.capability}",
                cost_receipt_ref=f"cost:{command.capability}",
                external_request_id=f"external:{command.capability}",
                query_supported=True,
                cancel_supported=True,
                callback_supported=True,
                fixture_protocol_only=True,
            ),
        )


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

    def test_controlled_legacy_http_and_embedding_block_before_network(
        self,
    ) -> None:
        with patch(
            "novel_forge.infrastructure.legacy_http.urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaisesRegex(
                RuntimeError, "legacy execution is blocked"
            ):
                development_only_http_request(
                    component="guard fixture",
                    url="https://example.invalid",
                    method="POST",
                    body=b"{}",
                    headers={"Content-Type": "application/json"},
                    timeout_seconds=1,
                    environment="production",
                )
            urlopen.assert_not_called()

        adapter = OpenAICompatibleEmbeddingAdapter(
            {
                "NOVEL_FORGE_ENVIRONMENT": "production",
                "OPENAI_API_KEY": "must-not-be-used",
            }
        )
        with patch(
            "novel_forge.model_adapters.embeddings.urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaisesRegex(
                RuntimeError, "legacy execution is blocked"
            ):
                adapter.embed_batch(["bounded input"])
            urlopen.assert_not_called()

    def test_controlled_local_storage_model_fallback_blocks_before_call(
        self,
    ) -> None:
        model = _LegacyModel()
        with self.assertRaisesRegex(
            RuntimeError, "requires GatewayDomainExecutionPort"
        ):
            execute_domain_candidate(
                capability="creative.topic.generate",
                operation=DomainModelOperation.GENERATE,
                candidate_kind=CandidateKind.GENERATION,
                prompt="bounded prompt",
                context={"project_id": "project:guard:1"},
                legacy_model=model,
                environment="production",
            )
        self.assertFalse(model.called)

    def test_tool_and_analytics_remote_calls_accept_gateway_port(self) -> None:
        port = _ExternalActionFixturePort()
        tool_result = _mcp_json_rpc(
            {
                "id": "mcp-server:fixture",
                "content": {
                    "server_id": "mcp-server:fixture",
                    "transport": "https",
                    "endpoint": "https://must-not-connect.invalid",
                },
            },
            "tools/list",
            {},
            external_action_execution_port=port,
            project_id="project:guard:1",
            environment="production",
        )
        analytics_result = _clickhouse_execute(
            "select 1",
            external_action_execution_port=port,
            environment="production",
        )
        self.assertIn("production_execution", tool_result)
        self.assertIn("production_execution", analytics_result)
        self.assertEqual(
            port.capabilities,
            ["tool.remote.invoke", "analytics.query.execute"],
        )


if __name__ == "__main__":
    unittest.main()
