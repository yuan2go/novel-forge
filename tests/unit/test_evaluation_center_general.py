from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.modules.evaluation_center import create_evaluation_case, create_evaluation_gate, create_evaluation_suite, evaluate_asset, run_evaluation_suite
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.schemas import DraftChapter
from novel_forge.storage.local import LocalStorage


class EvaluationCenterGeneralTests(unittest.TestCase):
    def test_general_evaluation_suite_evaluates_assets_and_runs_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Evaluation draft",
                    content={"chapter": 1, "text": "原创章节，有冲突、动机、目标、反转、留存和节奏。", "context_bundle_id": "ctx-1", "envelope_id": "env-1"},
                    metadata={"project_id": "eval-p", "trace_id": "trace-eval"},
                ),
            )

            suite = create_evaluation_suite(storage, name="Novel OS unit suite", project_id="eval-p")
            case = create_evaluation_case(storage, suite_id=suite["asset"]["content"]["suite_id"], target_asset_path=str(draft_path.relative_to(storage.root)))
            result = evaluate_asset(storage, str(draft_path.relative_to(storage.root)), project_id="eval-p")
            run = run_evaluation_suite(storage, suite_path=suite["path"], target_asset_paths=[str(draft_path.relative_to(storage.root))], project_id="eval-p")

            self.assertEqual(suite["asset"]["type"], "evaluation_suite")
            self.assertEqual(case["asset"]["type"], "evaluation_case")
            self.assertEqual(result["asset"]["type"], "evaluation_result")
            self.assertEqual(run["asset"]["type"], "evaluation_run")
            self.assertIn(result["recommendation"], {"pass", "revise", "block"})

    def test_evaluation_gate_block_generates_review_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Gate draft",
                    content={"chapter": 1, "text": "短文本", "raw_text": "forbidden source_chunk.raw_text"},
                    metadata={"project_id": "eval-gate-p"},
                ),
            )

            gate = create_evaluation_gate(storage, str(draft_path.relative_to(storage.root)), minimum_score=0.99, project_id="eval-gate-p")
            issues = list_review_issues(storage, project_id="eval-gate-p")

            self.assertEqual(gate["asset"]["content"]["status"], "blocked")
            self.assertTrue(gate["asset"]["content"]["blocking"])
            self.assertTrue(issues)
            self.assertEqual(issues[0]["content"]["source_system"], "evaluation_center")

    def test_evaluate_asset_accepts_human_annotations_and_model_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Annotated draft",
                    content={"chapter": 1, "text": "原创章节，有目标但钩子较弱。", "context_bundle_id": "ctx-1", "envelope_id": "env-1"},
                    metadata={"project_id": "eval-annotation-p", "trace_id": "trace-eval-annotation"},
                ),
            )

            result = evaluate_asset(
                storage,
                str(draft_path.relative_to(storage.root)),
                project_id="eval-annotation-p",
                human_annotations=[{"dimension": "hook_strength", "score": 0.2, "annotator": "editor", "comment": "hook weak"}],
                model_judge={"enabled": False, "provider": "local", "model": "deterministic", "score": 0.3, "confidence": 0.9},
            )
            content = result["asset"]["content"]

            self.assertEqual(content["evaluation_mode"], "local_heuristic_with_human_and_model_judge")
            self.assertEqual(content["scores"]["human_annotation"], 0.2)
            self.assertEqual(content["scores"]["model_judge"], 0.3)
            self.assertFalse(content["evaluator_inputs"]["external_provider_called"])

    def test_external_model_judge_requires_explicit_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="External judge draft",
                    content={"chapter": 1, "text": "原创章节，有目标、冲突和钩子。"},
                    metadata={"project_id": "eval-external-p"},
                ),
            )

            with self.assertRaisesRegex(PermissionError, "allow_external_model_judge"):
                evaluate_asset(
                    storage,
                    str(draft_path.relative_to(storage.root)),
                    project_id="eval-external-p",
                    model_judge={"enabled": True, "mode": "external", "provider": "mock"},
                )

    def test_external_model_judge_uses_mock_provider_when_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Authorized judge draft",
                    content={"chapter": 1, "text": "原创章节，有目标、冲突、动机、钩子和留存期待。"},
                    metadata={"project_id": "eval-external-p"},
                ),
            )

            result = evaluate_asset(
                storage,
                str(draft_path.relative_to(storage.root)),
                project_id="eval-external-p",
                model_judge={
                    "enabled": True,
                    "mode": "external",
                    "provider": "mock",
                    "allow_external_model_judge": True,
                    "source_policy": {"raw_source_text_allowed": False},
                    "trace": {"trace_id": "trace-eval-external"},
                },
            )
            judge = result["asset"]["content"]["evaluator_inputs"]["model_judge"]

            self.assertEqual(result["asset"]["content"]["evaluation_mode"], "local_heuristic_with_external_model_judge")
            self.assertTrue(judge["external_provider_called"])
            self.assertEqual(judge["provider"], "mock")
            self.assertTrue(judge["model_gateway_call"]["model_call_log_path"])
