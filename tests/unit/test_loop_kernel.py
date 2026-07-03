from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.loop_kernel import get_loop_run, run_loop
from novel_forge.modules.review_issue import create_review_issue
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage
from novel_forge.storage.rag_context import generation_context_policy


class LoopKernelTests(unittest.TestCase):
    def test_chapter_review_loop_writes_context_checkpoint_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = _draft(storage, project_id="loop-p")

            result = run_loop(
                storage,
                {
                    "loop_type": "chapter_review",
                    "target_path": str(draft_path.relative_to(storage.root)),
                    "project_id": "loop-p",
                    "budget": {"max_steps": 5, "max_tokens": 2000, "max_cost": 1.0, "max_duration_seconds": 60},
                },
            )
            detail = get_loop_run(storage, result["loop_run_path"])
            report = result["report"]

            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["stop_condition"], "quality_passed")
            self.assertTrue(result["context_bundle_path"])
            self.assertGreaterEqual(len(result["step_paths"]), 3)
            self.assertEqual(len(result["step_paths"]), len(result["checkpoint_paths"]))
            self.assertEqual(report["type"], "loop_report")
            self.assertEqual(report["content"]["stop_condition"], "quality_passed")
            self.assertEqual(detail["asset"]["content"]["status"], "succeeded")

            for path in [result["loop_run_path"], *result["step_paths"], *result["checkpoint_paths"], result["loop_report_path"]]:
                asset = storage.read_json(storage.root / path)
                self.assertFalse(generation_context_policy(asset)["eligible"], asset["type"])

    def test_loop_stops_on_blocking_review_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = _draft(storage, project_id="loop-block")
            draft = storage.read_asset(draft_path)
            create_review_issue(
                storage,
                {
                    "project_id": "loop-block",
                    "target_asset_id": draft.id,
                    "target_asset_type": "draft_chapter",
                    "issue_type": "canon_conflict",
                    "severity": "critical",
                    "message": "loop must stop on unresolved canon conflict",
                },
            )

            result = run_loop(
                storage,
                {
                    "loop_type": "chapter_review",
                    "target_path": str(draft_path.relative_to(storage.root)),
                    "project_id": "loop-block",
                    "budget": {"max_steps": 5, "max_tokens": 2000, "max_cost": 1.0, "max_duration_seconds": 60},
                },
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["stop_condition"], "blocking_issue")
            self.assertEqual(result["report"]["content"]["blocking_review_issues"][0]["issue_type"], "canon_conflict")

    def test_loop_stops_on_budget_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()

            result = run_loop(
                storage,
                {
                    "loop_type": "outline_revision",
                    "project_id": "loop-budget",
                    "budget": {"max_steps": 3, "max_tokens": 10, "max_cost": 1.0, "max_duration_seconds": 60},
                    "steps": [{"step_type": "revision_plan", "operation": "plan", "token_estimate": 40, "cost_estimate": 0.0}],
                },
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["stop_condition"], "budget_exceeded")
            self.assertIn("max_tokens exceeded", result["asset"]["content"]["stop_message"])
            self.assertEqual(len(result["checkpoint_paths"]), 1)

    def test_production_loop_requires_os_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            with self.assertRaisesRegex(ValueError, "OS envelope required"):
                run_loop(storage, {"loop_type": "chapter_review", "project_id": "loop-prod", "environment": "production"})

            result = run_loop(
                storage,
                {
                    "loop_type": "chapter_review",
                    "project_id": "loop-prod",
                    "environment": "production",
                    "envelope": {
                        "envelope_id": "env-loop-prod",
                        "project_id": "loop-prod",
                        "task_type": "chapter_review",
                        "asset_type": "loop_run",
                        "actor_type": "test",
                        "source": "unit-test",
                        "trace_id": "trace-loop-prod",
                        "source_policy": {"raw_source_text_allowed": False},
                        "environment": "production",
                    },
                    "steps": [{"step_type": "quality_gate", "operation": "quality_passed", "token_estimate": 1, "cost_estimate": 0.0}],
                },
            )
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["envelope"]["status"], "enforced")

    def test_review_revision_publish_loop_writes_main_chain_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = _draft(storage, project_id="loop-main")

            result = run_loop(
                storage,
                {
                    "loop_type": "review_revision_publish",
                    "target_path": str(draft_path.relative_to(storage.root)),
                    "project_id": "loop-main",
                    "budget": {"max_steps": 8, "max_tokens": 4000, "max_cost": 1.0, "max_duration_seconds": 60},
                },
            )
            outputs = result["outputs"]
            report_outputs = result["report"]["content"]["outputs"]

            self.assertEqual(result["status"], "succeeded")
            for key in ["review_report_path", "revision_task_path", "revision_plan_path", "editor_patch_path", "final_draft_path", "draft_version_path", "re_review_path", "publish_gate_report_path"]:
                self.assertTrue(outputs[key], key)
                self.assertTrue((storage.root / outputs[key]).exists(), key)
                self.assertEqual(outputs[key], report_outputs[key])
            self.assertEqual(storage.read_json(storage.root / outputs["review_report_path"])["type"], "review_report")
            self.assertEqual(storage.read_json(storage.root / outputs["revision_task_path"])["type"], "revision_task")
            self.assertEqual(storage.read_json(storage.root / outputs["revision_plan_path"])["type"], "revision_plan")
            self.assertEqual(storage.read_json(storage.root / outputs["editor_patch_path"])["type"], "editor_patch")
            self.assertEqual(storage.read_json(storage.root / outputs["draft_version_path"])["type"], "draft_version")
            self.assertEqual(storage.read_json(storage.root / outputs["publish_gate_report_path"])["type"], "publish_gate_report")
            task = storage.read_json(storage.root / outputs["revision_task_path"])
            self.assertEqual(task["content"]["outputs"]["loop_run_path"], result["loop_run_path"])
            self.assertEqual(task["content"]["outputs"]["loop_report_path"], result["loop_report_path"])


def _draft(storage: LocalStorage, *, project_id: str) -> Path:
    return storage.write_asset(
        "drafts",
        DraftChapter(
            title="Loop draft",
            content={"chapter": 1, "text": "原创章节文本，用于 Loop Kernel 测试。", "copyright_boundary": "project-owned unit fixture"},
            metadata={"project_id": project_id},
        ),
    )


if __name__ == "__main__":
    unittest.main()
