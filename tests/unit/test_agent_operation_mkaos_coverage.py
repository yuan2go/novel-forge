from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.agent_scheduler import list_agent_operation_contracts, mkaos_agent_operation_coverage_report
from novel_forge.modules.agent_scheduler.service import AgentOperationRegistry
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class AgentOperationMkaosCoverageTests(unittest.TestCase):
    def test_core_operations_require_mkaos_context_contract(self):
        contracts = {row["operation"]: row for row in list_agent_operation_contracts()}
        required = [
            "run-analysis",
            "decompose",
            "convert-analysis-report",
            "generate-outline",
            "generate-chapter-plan",
            "draft",
            "review",
            "revise",
            "create-editor-patch",
            "run-longform-recap",
            "create-publish-gate-report",
            "create-feedback-backflow-plan",
            "process-real-feedback-backflow",
            "run-review-revision-publish-loop",
        ]

        for operation in required:
            with self.subTest(operation=operation):
                contract = contracts[operation]
                self.assertTrue(contract["mkaos_context_required"])
                self.assertTrue(contract["production_bypass_forbidden"])
                for field in ["context_bundle_id", "knowledge_pack_id", "source_policy", "source_isolation", "mkaos_flow"]:
                    self.assertIn(field, contract["knowledge_context_contract_fields"])

    def test_operation_coverage_report_classifies_required_and_compat_operations(self):
        report = mkaos_agent_operation_coverage_report()
        rows = {row["operation"]: row for row in report["operations"]}

        self.assertGreaterEqual(report["summary"]["registered_count"], 14)
        self.assertEqual(rows["draft"]["status"], "mkaos_required")
        self.assertEqual(rows["review"]["status"], "mkaos_required")
        self.assertEqual(rows["create-publish-gate-report"]["status"], "mkaos_required")
        self.assertEqual(rows["run-longform-recap"]["status"], "mkaos_required")
        self.assertEqual(rows["apply-editor-patch"]["status"], "compat")
        self.assertTrue(rows["draft"]["production_bypass_forbidden"])
        self.assertFalse(rows["apply-editor-patch"]["production_bypass_forbidden"])

    def test_scheduler_production_output_reuse_requires_knowledge_context_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            output_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Existing draft without MKAOS contract",
                    content={"text": "fixture", "copyright_boundary": "project-owned fixture"},
                    metadata={"project_id": "local-system"},
                ),
            )
            rel_path = str(output_path.relative_to(storage.root))
            registry = AgentOperationRegistry()

            with self.assertRaisesRegex(RuntimeError, "requires knowledge context contract"):
                registry.execute(
                    storage,
                    {
                        "content": {
                            "dispatch_id": "dispatch-test",
                            "idempotency_key": "draft-production-contract",
                            "expected_output_assets": [rel_path],
                        }
                    },
                    {
                        "content": {
                            "run_id": "agent-run-test",
                            "operation": "draft",
                            "evidence": {"environment": "production", "expected_output_assets": [rel_path]},
                            "input_assets": [],
                        },
                        "metadata": {"project_id": "local-system"},
                    },
                )


if __name__ == "__main__":
    unittest.main()
