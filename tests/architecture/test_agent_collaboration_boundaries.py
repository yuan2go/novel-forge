from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLABORATION = ROOT / "src/novel_forge/modules/agent_collaboration"


class AgentCollaborationBoundaryTests(unittest.TestCase):
    def test_domain_has_no_runtime_provider_or_transport_dependency(self) -> None:
        forbidden_roots = {
            "subprocess",
            "requests",
            "httpx",
            "urllib",
            "novel_forge.model_adapters",
            "novel_forge.modules.provider_control",
        }
        violations: list[str] = []
        for path in sorted(COLLABORATION.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if any(
                        name == root or name.startswith(f"{root}.")
                        for root in forbidden_roots
                    ):
                        violations.append(f"{path.name}:{node.lineno}:{name}")
        self.assertEqual(violations, [])

    def test_application_depends_on_pep_port_not_gateway_or_backend(self) -> None:
        source = (
            COLLABORATION / "application.py"
        ).read_text(encoding="utf-8")

        self.assertIn("DomainExecutionPort", source)
        self.assertIn("execute_domain_candidate", source)
        self.assertNotIn("ProductionExecutionGateway", source)
        self.assertNotIn("ScriptedFixtureExecutionBackend", source)
        self.assertNotIn("CodexCliExecutionBackend", source)
        self.assertNotIn("RemoteProviderExecutionBackend", source)

    def test_collaboration_schema_reuses_authority_attempt_and_asset_version(self) -> None:
        source = (
            ROOT
            / "src/novel_forge/storage/migrations/versions"
            / "v20260728_0033_agent_collaboration_v1.py"
        ).read_text(encoding="utf-8")

        self.assertIn("REFERENCES authority_attempt(attempt_id)", source)
        self.assertIn(
            "REFERENCES authority_asset_version(asset_version_id)", source
        )
        self.assertNotIn("agent_attempts", source.lower())
        self.assertNotIn("conversation_execution_attempts", source.lower())


if __name__ == "__main__":
    unittest.main()
