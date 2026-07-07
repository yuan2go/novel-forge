from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.publishing import create_publish_gate_report, create_release_package
from novel_forge.modules.editor import execute_revision_plan
from novel_forge.modules.mkaos import check_canon_conflict
from novel_forge.modules.review import service as review_service
from novel_forge.modules.review_issue import (
    blocking_review_issues,
    create_review_issue,
    list_review_issues,
    persist_issue_candidates,
    review_issue_to_revision_task_candidate,
)
from novel_forge.modules.revision import service as revision_service
from novel_forge.schemas import ContextBundle, DraftChapter, ReviewReport, RevisionPlan
from novel_forge.storage.local import LocalStorage


class StructuredRevisionModel:
    name = "structured-revision-model"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, context=None):
        self.calls += 1
        return {
            "model": self.name,
            "provider": "fixture-provider",
            "text": (
                '{"operations":[{"kind":"replace_text","paragraph_index":1,'
                '"before":"第一段原创文本。","after":"第一段原创文本，逻辑修正完成。",'
                '"instruction":"fix logic","rationale":"close review gap","risk":"low"}],'
                '"revision_summary":"fix logic gap","quality_notes":["stable"],"risk_controls":["rollback available"]}'
            ),
            "copyright_boundary": "project-owned fixture output",
        }


class ReviewIssueTests(unittest.TestCase):
    def setUp(self):
        self._previous_model_provider = os.environ.get("NOVEL_FORGE_MODEL_PROVIDER")
        os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = "mock"

    def tearDown(self):
        if self._previous_model_provider is None:
            os.environ.pop("NOVEL_FORGE_MODEL_PROVIDER", None)
        else:
            os.environ["NOVEL_FORGE_MODEL_PROVIDER"] = self._previous_model_provider

    def test_mkaos_review_issue_blocks_publish_gate_and_release_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Chapter 1 draft",
                    content={
                        "chapter": 1,
                        "text": "土地兼并是一种制度现象，本质上会导致小农破产。因此税源减少，所谓地方秩序也会变化。\n\n制度的概念是土地集中，专业上它意味着资源配置变化，因此需要解释清楚。",
                        "copyright_boundary": "project-owned test draft",
                    },
                    metadata={"project_id": "issue-p"},
                ),
            )

            review_path = review_service.review(storage, str(draft_path), model=MockModelAdapter())
            review = storage.read_asset(review_path)
            issues = list_review_issues(storage, project_id="issue-p", target_asset_id=storage.read_asset(draft_path).id)
            blocking = blocking_review_issues(storage, target_asset_id=storage.read_asset(draft_path).id, project_id="issue-p")

            self.assertTrue(review.metadata["review_issue_ids"])
            self.assertTrue(any(row["content"]["issue_type"] == "mkaos_conflict" for row in issues))
            self.assertTrue(blocking)

            gate_path = create_publish_gate_report(storage, draft_path)
            self.assertEqual(storage.read_asset(gate_path).content["decision"], "blocked")
            with self.assertRaisesRegex(ValueError, "release_package blocked by"):
                create_release_package(storage, draft_path, publish_gate_path=gate_path)

    def test_canon_issue_candidate_persists_as_review_issue_with_revision_task_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            result = check_canon_conflict(
                storage,
                {
                    "project_id": "canon-issue-p",
                    "target_asset_id": "draft-canon-1",
                    "target_asset_type": "draft_chapter",
                    "artifact_text": "阿照死了。",
                    "canon": {"entities": [{"canonical_name": "阿照", "status": "alive"}]},
                },
            )

            persisted = persist_issue_candidates(storage, result["issue_candidates"], source_system="mkaos.canon_conflict")
            rows = list_review_issues(storage, project_id="canon-issue-p", target_asset_id="draft-canon-1")

            self.assertEqual(persisted["issue_count"], 1)
            self.assertEqual(rows[0]["content"]["issue_type"], "canon_conflict")
            self.assertTrue(rows[0]["content"]["blocking"])
            self.assertEqual(rows[0]["content"]["revision_task_candidate"]["source_issue_id"], rows[0]["content"]["issue_id"])
            self.assertEqual(rows[0]["content"]["revision_task_candidate"]["revision_strategy_id"], "canon_aligned_rewrite")

    def test_review_issue_candidate_selects_readable_prose_revision_strategy(self):
        candidate = review_issue_to_revision_task_candidate(
            {
                "content": {
                    "issue_id": "issue-opening-pressure",
                    "issue_type": "quality_gate",
                    "severity": "high",
                    "blocking": True,
                    "target_asset_id": "draft-readable-1",
                    "target_asset_path": "data/drafts/draft-readable-1.json",
                    "source_system": "readable_prose_gate.v1",
                    "message": "opening_pressure failed: opening lacks pressure",
                    "fix_suggestion": "rewrite the opening with immediate pressure",
                }
            }
        )

        self.assertEqual(candidate["revision_strategy_id"], "rewrite_opening_pressure")
        self.assertTrue(candidate["re_review_required"])
        self.assertIn("re_review_path", candidate["required_output_evidence"])
        self.assertIn("opening pressure", candidate["re_review_focus"])

    def test_revision_task_and_plan_preserve_strategy_and_re_review_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Thin draft",
                    content={"chapter": 1, "text": "他说这很重要。\n\n于是继续。", "copyright_boundary": "project-owned test draft"},
                    metadata={"project_id": "strategy-p"},
                ),
            )
            draft = storage.read_asset(draft_path)
            review_path = storage.write_asset(
                "reviews",
                ReviewReport(
                    title="Readable prose gate review",
                    source=draft.id,
                    content={"rubric": "readable_prose_gate_v1", "summary": "opening blocked"},
                    score=62,
                    strengths=[],
                    weaknesses=["opening pressure"],
                    issues=[
                        {
                            "issue_id": "readable-opening-1",
                            "issue_index": 0,
                            "issue_type": "quality_gate",
                            "severity": "high",
                            "blocking": True,
                            "source_system": "readable_prose_gate.v1",
                            "dimension": "opening_pressure",
                            "message": "opening_pressure failed",
                            "recommendation": "rewrite opening with event pressure",
                        }
                    ],
                    risk_level="high",
                    revision_suggestions=["repair opening pressure"],
                    next_action="revise",
                    metadata={"project_id": "strategy-p"},
                ),
            )

            task = revision_service.create_revision_task(storage, review_path, draft_path=draft_path)
            task_asset = storage.read_asset(task["path"])
            strategy_plan = task_asset.content["revision_strategy_plan"]

            self.assertEqual(strategy_plan["strategy_ids"], ["rewrite_opening_pressure"])
            self.assertTrue(task_asset.content["re_review_required"])
            self.assertIn("re_review_path", task_asset.content["required_output_evidence"])
            self.assertEqual(task_asset.content["issues"][0]["revision_strategy_id"], "rewrite_opening_pressure")

            revision_plan_path = revision_service.revise(
                storage,
                str(review_path),
                model=MockModelAdapter(),
                post_quality_loop=False,
                auto_execute_revision_plan=False,
                post_review=False,
            )
            revision_plan = storage.read_asset(revision_plan_path)

            self.assertEqual(revision_plan.content["revision_strategy_plan"]["strategy_ids"], ["rewrite_opening_pressure"])
            self.assertTrue(revision_plan.content["re_review_required"])
            self.assertTrue(any("rewrite_opening_pressure" in step for step in revision_plan.content["steps"]))

    def test_blocking_review_issue_prevents_final_draft_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path = storage.write_asset(
                "drafts",
                DraftChapter(
                    title="Draft",
                    content={"chapter": 1, "text": "第一段原创文本。", "copyright_boundary": "project-owned test draft"},
                    metadata={"project_id": "final-block-p"},
                ),
            )
            draft = storage.read_asset(draft_path)
            review_path = storage.write_asset(
                "reviews",
                ReviewReport(
                    title="Review",
                    source=draft.id,
                    content={"rubric": ["logic"], "summary": "needs fix"},
                    score=70,
                    strengths=[],
                    weaknesses=["logic"],
                    issues=[],
                    risk_level="high",
                    revision_suggestions=["fix logic"],
                    next_action="revise",
                    metadata={"project_id": "final-block-p"},
                ),
            )
            revision_path = storage.write_asset(
                "reviews",
                RevisionPlan(
                    title="Revision plan",
                    source=storage.read_asset(review_path).id,
                    content={"steps": ["fix"], "target_score": 85, "must_preserve": []},
                    metadata={"project_id": "final-block-p"},
                ),
            )
            bundle_path = storage.write_asset(
                "contexts",
                ContextBundle(
                    title="Bundle",
                    content={
                        "build_plan_id": "plan",
                        "target_asset_id": draft.id,
                        "selected_assets": [],
                        "compressed_context": {},
                        "token_budget": {"max_tokens": 2000},
                        "token_estimate": 1,
                        "actual_context": "test",
                        "source_asset_ids": [],
                    },
                    metadata={"project_id": "final-block-p"},
                ),
            )
            create_review_issue(
                storage,
                {
                    "project_id": "final-block-p",
                    "target_asset_id": draft.id,
                    "target_asset_type": "draft_chapter",
                    "issue_type": "canon_conflict",
                    "severity": "critical",
                    "message": "canonical promotion must stop",
                },
            )

            with self.assertRaisesRegex(ValueError, "canonical_chapter blocked by"):
                execute_revision_plan(
                    storage,
                    draft_path=draft_path,
                    review_path=review_path,
                    revision_path=revision_path,
                    context_bundle_path=bundle_path,
                    model=MockModelAdapter(),
                )

    def test_production_final_draft_promotion_requires_provider_runtime_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path, review_path, revision_path, bundle_path = _write_revision_executor_fixture(storage, project_id="final-prod-p")
            model = StructuredRevisionModel()

            with self.assertRaisesRegex(ValueError, "provider_runtime_gate"):
                execute_revision_plan(
                    storage,
                    draft_path=draft_path,
                    review_path=review_path,
                    revision_path=revision_path,
                    context_bundle_path=bundle_path,
                    model=model,
                    environment="production",
                    os_envelope=_production_envelope("final-prod-p"),
                    source_policy={"source_isolation_required": True},
                )

            self.assertEqual(model.calls, 0)

    def test_production_final_draft_promotion_records_governance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            draft_path, review_path, revision_path, bundle_path = _write_revision_executor_fixture(storage, project_id="final-prod-p")

            result = execute_revision_plan(
                storage,
                draft_path=draft_path,
                review_path=review_path,
                revision_path=revision_path,
                context_bundle_path=bundle_path,
                model=StructuredRevisionModel(),
                environment="production",
                os_envelope=_production_envelope("final-prod-p"),
                source_policy={"source_isolation_required": True},
                provider_runtime_gate={"status": "passed", "provider": "fixture-provider", "model": "structured-revision-model", "path": "runs/provider-runtime-gate.json"},
            )

            final_draft = storage.read_asset(result["final_draft_path"])
            governance = final_draft.content["production_governance"]
            governance_asset = storage.read_json(storage.root / governance["path"])

            self.assertEqual(governance["status"], "passed")
            self.assertEqual(governance_asset["type"], "production_governance_report")
            self.assertEqual(governance_asset["content"]["operation"], "editor.execute_revision_plan.final_draft")
            self.assertIn(result["production_governance_path"], result["output_paths"])


def _write_revision_executor_fixture(storage: LocalStorage, *, project_id: str):
    draft_path = storage.write_asset(
        "drafts",
        DraftChapter(
            title="Draft",
            content={"chapter": 1, "text": "第一段原创文本。", "copyright_boundary": "project-owned test draft"},
            metadata={"project_id": project_id},
        ),
    )
    draft = storage.read_asset(draft_path)
    review_path = storage.write_asset(
        "reviews",
        ReviewReport(
            title="Review",
            source=draft.id,
            content={"rubric": ["logic"], "summary": "needs fix"},
            score=70,
            strengths=[],
            weaknesses=["logic"],
            issues=[],
            risk_level="medium",
            revision_suggestions=["fix logic"],
            next_action="revise",
            metadata={"project_id": project_id},
        ),
    )
    revision_path = storage.write_asset(
        "reviews",
        RevisionPlan(
            title="Revision plan",
            source=storage.read_asset(review_path).id,
            content={"steps": ["fix"], "target_score": 85, "must_preserve": []},
            metadata={"project_id": project_id},
        ),
    )
    bundle_path = storage.write_asset(
        "contexts",
        ContextBundle(
            title="Bundle",
            content={
                "build_plan_id": "plan",
                "target_asset_id": draft.id,
                "selected_assets": [],
                "compressed_context": {},
                "token_budget": {"max_tokens": 2000},
                "token_estimate": 1,
                "actual_context": "test",
                "source_asset_ids": [],
                "knowledge_context_contract": {
                    "context_bundle_id": "bundle-final-prod",
                    "knowledge_pack_id": "knowledge-pack-final-prod",
                    "source_policy": {"source_isolation_required": True},
                    "source_isolation": {"raw_text_included": False, "source_text_included": False},
                    "mkaos_flow": "revision",
                },
            },
            metadata={"project_id": project_id},
        ),
    )
    return draft_path, review_path, revision_path, bundle_path


def _production_envelope(project_id: str) -> dict[str, object]:
    return {
        "environment": "production",
        "project_id": project_id,
        "task_type": "revision",
        "asset_type": "draft_chapter",
        "actor_type": "editor_service",
        "source": "unit-test",
        "trace_id": f"trace-{project_id}",
        "source_policy": {"source_isolation_required": True},
    }


if __name__ == "__main__":
    unittest.main()
