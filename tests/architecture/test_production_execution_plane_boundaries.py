from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from novel_forge.modules.production_execution import ExecutionBackend


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "src/novel_forge/modules/production_execution/contracts.py"
MIGRATIONS = ROOT / "src/novel_forge/storage/migrations/versions"


class ProductionExecutionPlaneBoundaryTests(unittest.TestCase):
    def test_execution_contract_module_does_not_own_provider_or_process_runtime(self) -> None:
        tree = ast.parse(CONTRACTS.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        called_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.update(item.name for item in node.names)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)

        self.assertTrue(
            imported_modules.issubset(
                {
                    "__future__",
                    "dataclasses",
                    "enum",
                    "hashlib",
                    "json",
                    "re",
                    "types",
                    "typing",
                }
            ),
            imported_modules,
        )
        self.assertFalse(
            any(
                name.startswith("novel_forge.model_adapters")
                or name.startswith("novel_forge.modules.provider_control")
                or name.startswith("novel_forge.storage")
                for name in imported_modules
            )
        )
        self.assertTrue(
            {"Popen", "run", "connect", "generate", "analyze", "review", "revise"}.isdisjoint(
                called_names
            )
        )

    def test_no_parallel_execution_attempt_table_is_declared(self) -> None:
        declarations: list[str] = []
        for path in MIGRATIONS.glob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            if "create table execution_attempt" in source or "create table if not exists execution_attempt" in source:
                declarations.append(str(path.relative_to(ROOT)))
        self.assertEqual(declarations, [], "Authority Attempt must remain the only attempt authority")

    def test_contracts_are_attempt_bound_without_an_attempt_repository(self) -> None:
        source = CONTRACTS.read_text(encoding="utf-8")
        for contract in (
            "ExecutionRequest",
            "ExecutionHandle",
            "ExecutionResult",
            "ExecutionCancellationResult",
            "RouteSnapshot",
            "InputManifest",
            "ExecutionManifest",
            "OutputManifest",
            "ValidationManifest",
            "CommitManifest",
        ):
            start = source.index(f"class {contract}")
            body = source[start : source.find("\n@dataclass", start + 1) if "\n@dataclass" in source[start + 1 :] else len(source)]
            self.assertIn("attempt_id", body, contract)
        self.assertNotIn("class ExecutionAttempt", source)
        self.assertNotIn("class ExecutionAttemptRepository", source)

    def test_backend_protocol_signatures_remain_minimal(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(ExecutionBackend.submit).parameters),
            ("self", "request"),
        )
        self.assertEqual(
            tuple(inspect.signature(ExecutionBackend.reconcile).parameters),
            ("self", "handle"),
        )
        self.assertEqual(
            tuple(inspect.signature(ExecutionBackend.cancel).parameters),
            ("self", "handle", "reason"),
        )


if __name__ == "__main__":
    unittest.main()
