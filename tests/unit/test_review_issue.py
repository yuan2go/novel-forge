from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.model_adapters.mock import MockModelAdapter
from novel_forge.modules.audit import create_publish_gate_report, create_release_package
from novel_forge.modules.editor import execute_revision_plan
from novel_forge.modules.mkaos import check_canon_conflict
from novel_forge.modules.review import service as review_service
from novel_forge.modules.review_issue import (
    blocking_review_issues,
    create_review_issue,
    list_review_issues,
    persist_issue_candidates,
)
from novel_forge.schemas import ContextBundle, DraftChapter, ReviewReport, RevisionPlan
from novel_forge.storage.local import LocalStorage


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


if __name__ == "__main__":
    unittest.main()
