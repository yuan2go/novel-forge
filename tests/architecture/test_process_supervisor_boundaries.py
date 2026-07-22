from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / "src/novel_forge/modules/production_execution/process_supervisor.py"
PROVIDERS = ROOT / "src/novel_forge/model_adapters/providers.py"


class ProcessSupervisorBoundaryTests(unittest.TestCase):
    def test_codex_processes_do_not_inherit_full_environment(self) -> None:
        source = PROVIDERS.read_text(encoding="utf-8")
        self.assertNotIn("env = dict(os.environ)", source)
        self.assertNotIn("env=dict(os.environ)", source)

    def test_supervisor_owns_process_group_signals_and_persistent_receipts(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("start_new_session=True", source)
        self.assertIn("os.killpg", source)
        self.assertIn("receipt_path", source)
        self.assertNotIn("TemporaryDirectory", source)

    def test_local_codex_evidence_does_not_fabricate_provider_request_id(self) -> None:
        tree = ast.parse(PROVIDERS.read_text(encoding="utf-8"))
        evidence_function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_local_codex_provider_evidence"
        )
        provider_id_assignments: list[str] = []
        for node in ast.walk(evidence_function):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in {"provider_request_id", "provider_response_id"}:
                        if isinstance(value, ast.JoinedStr):
                            provider_id_assignments.append(key.value)
                        elif isinstance(value, ast.Constant) and value.value not in {None, ""}:
                            provider_id_assignments.append(key.value)
        self.assertEqual(provider_id_assignments, [])


if __name__ == "__main__":
    unittest.main()
