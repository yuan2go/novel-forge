from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CoreOsCharacterizationTests(unittest.TestCase):
    def test_core_ci_is_bound_to_checkout_head_and_real_postgres_service(self):
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git rev-parse HEAD", workflow)
        self.assertIn("${GITHUB_SHA}", workflow)
        self.assertIn("postgres:16", workflow)
        self.assertIn("novel_forge_core_os_test", workflow)
        self.assertIn("test_*postgres*.py", workflow)

    def test_production_kernel_has_one_registered_dispatch_boundary(self):
        source = (ROOT / "src/novel_forge/modules/production_kernel/service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("dispatch_production_operation", names)
        self.assertIn("control_production_operation", names)

    def test_postgres_store_is_not_mistaken_for_operation_authority(self):
        source = (ROOT / "src/novel_forge/storage/postgres.py").read_text(encoding="utf-8")
        self.assertIn("sync_from_local", source)
        self.assertNotIn("class ProductionUnitOfWork", source)


if __name__ == "__main__":
    unittest.main()
