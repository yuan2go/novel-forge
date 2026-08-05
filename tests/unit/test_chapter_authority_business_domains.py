from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import build_canon_update
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.domain_handlers import build_quality_report
from novel_forge.modules.content_quality_loop.domain import evaluate_quality_evidence
from novel_forge.modules.publishing.domain import prepare_internal_release
from novel_forge.modules.review.domain import evaluate_rereview_result, evaluate_review_result
from novel_forge.modules.revision.domain import apply_revision_result


class ChapterAuthorityBusinessDomainTests(unittest.TestCase):
    def review(self):
        return evaluate_review_result(
            project_id="project-a",
            target_asset_version_id="draft-v1",
            context_bundle_version_id="context-v1",
            chapter=1,
            result={
                "decision": "NEEDS_REVISION",
                "score": 70,
                "issues": [{
                    "code": "COST_MISSING", "severity": "blocking",
                    "message": "Choice has no cost.",
                    "evidence": {"start": 10, "end": 20, "excerpt_digest": "sha256:evidence"},
                }],
            },
            provider_evidence={"provider_id": "fixture", "real_model_call": False},
        )

    def revision(self, review):
        return apply_revision_result(
            project_id="project-a",
            draft={"chapter": 1, "title": "Cost", "text": "old"},
            review=review,
            draft_asset_version_id="draft-v1",
            review_asset_version_id="review-v1",
            context_bundle_version_id="context-v1",
            result={
                "text": "The choice destroys an alliance.",
                "resolved_issue_codes": ["COST_MISSING"],
                "canon_assertions": [{"subject": "alliance", "predicate": "status", "object": "broken"}],
            },
            provider_evidence={"provider_id": "fixture", "real_model_call": False},
        )

    def rereview(self, review, revision, *, passed=True):
        return evaluate_rereview_result(
            project_id="project-a",
            original_draft_version_id="draft-v1",
            initial_review_version_id="review-v1",
            revision_version_id="revision-v1",
            context_bundle_version_id="context-v1",
            initial_review=review,
            revision=revision,
            result={
                "decision": "PASSED" if passed else "NEEDS_REVISION",
                "score": 88 if passed else 72,
                "issues": [] if passed else [{
                    "code": "COST_MISSING", "severity": "blocking",
                    "message": "Cost remains abstract.",
                }],
                "resolved_issue_codes": ["COST_MISSING"] if passed else [],
            },
            provider_evidence={"provider_id": "fixture", "real_model_call": False},
        )

    def test_review_issues_are_versioned_locatable_and_qualified(self) -> None:
        issue = self.review()["issues"][0]
        self.assertTrue(issue["review_issue_id"].startswith("review-issue:"))
        self.assertEqual(issue["status"], "OPEN")
        self.assertEqual(issue["qualification"], "ELIGIBLE")
        self.assertEqual(issue["context_bundle_version_id"], "context-v1")
        self.assertEqual(issue["evidence_locator"]["start"], 10)

    def test_revision_fails_closed_until_every_eligible_blocker_is_resolved(self) -> None:
        review = self.review()
        with self.assertRaisesRegex(KernelError, "CHAPTER_REVISION_INCOMPLETE"):
            apply_revision_result(
                project_id="project-a",
                draft={"chapter": 1, "title": "Cost", "text": "old"},
                review=review,
                draft_asset_version_id="draft-v1",
                review_asset_version_id="review-v1",
                context_bundle_version_id="context-v1",
                result={"text": "changed", "resolved_issue_codes": []},
                provider_evidence={},
            )
        review["issues"][0]["qualification"] = "REVOKED"
        self.assertEqual(
            self.revision(review)["issue_resolutions"][0]["to_status"],
            "RESOLUTION_CLAIMED",
        )

    def test_revision_claim_does_not_resolve_until_independent_rereview(self) -> None:
        review = self.review()
        revision = self.revision(review)
        failed = self.rereview(review, revision, passed=False)
        self.assertEqual(failed["issue_lineage"][0]["to_status"], "REOPENED")
        self.assertEqual(failed["blocking_issue_count"], 1)
        passed = self.rereview(review, revision, passed=True)
        self.assertEqual(passed["issue_lineage"][0]["to_status"], "RESOLVED")
        self.assertEqual(passed["revision_quality_delta"]["resolved_issue_count"], 1)

    def test_canon_quality_and_publish_use_structured_evidence(self) -> None:
        review = self.review()
        revision = self.revision(review)
        rereview = self.rereview(review, revision)
        canon = build_canon_update(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", context_bundle_version_id="context-v1",
        )
        context_bundle = {
            "source_isolation_result": {"passed": True},
            "copyright_boundary": "abstract_or_project_owned_only",
            "context_segments": [
                {"asset_version_id": "checklist-v1", "asset_type": "operator_checklist", "structured_facts": [{"key": "completed", "value": True}], "source_expression_included": False},
                {"asset_version_id": "approval-v1", "asset_type": "operator_approval", "structured_facts": [{"key": "approved", "value": True}], "source_expression_included": False},
            ],
        }
        quality = build_quality_report(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", review=rereview,
            review_asset_version_id="rereview-v1", canon=canon,
            canon_asset_version_id="canon-v1", context_bundle_version_id="context-v1",
            context_bundle=context_bundle,
        )
        publish_gate = prepare_internal_release(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", quality=quality,
            quality_asset_version_id="quality-v1", review=rereview,
            review_asset_version_id="rereview-v1", canon=canon,
            canon_asset_version_id="canon-v1",
            context_bundle=context_bundle,
            context_bundle_version_id="context-v1",
        )
        self.assertEqual(publish_gate["gate"], "PUBLISH_GATE_BLOCKED")
        self.assertFalse(publish_gate["external_publish_permitted"])
        self.assertEqual(canon["facts"][0]["object"], "broken")
        self.assertEqual(quality["gate"], "FAILED")
        self.assertIn("anti_ai", quality["blocking_dimensions"])

    def test_canon_conflict_blocks_quality(self) -> None:
        review = self.review()
        revision = self.revision(review)
        rereview = self.rereview(review, revision)
        canon = build_canon_update(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", context_bundle_version_id="context-v1",
            existing_facts=[{"subject": "alliance", "predicate": "status", "object": "active"}],
        )
        self.assertEqual(canon["gate"], "BLOCKED")
        with self.assertRaisesRegex(KernelError, "CHAPTER_QUALITY_GATE_FAILED"):
            evaluate_quality_evidence(
                project_id="project-a", revision=revision,
                revision_asset_version_id="revision-v1", review=rereview,
                review_asset_version_id="rereview-v1", canon=canon,
                canon_asset_version_id="canon-v1", context_bundle_version_id="context-v1",
            )


if __name__ == "__main__":
    unittest.main()
