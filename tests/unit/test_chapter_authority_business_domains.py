from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import build_canon_update
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_quality_loop.domain import evaluate_quality_evidence
from novel_forge.modules.publishing.domain import prepare_internal_release
from novel_forge.modules.review.domain import evaluate_review_result
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
        self.assertEqual(self.revision(review)["issue_resolutions"][0]["to_status"], "RESOLVED")

    def test_canon_quality_and_publish_use_structured_evidence(self) -> None:
        review = self.review()
        revision = self.revision(review)
        canon = build_canon_update(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", context_bundle_version_id="context-v1",
        )
        quality = evaluate_quality_evidence(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", review=review,
            review_asset_version_id="review-v1", canon=canon,
            canon_asset_version_id="canon-v1", context_bundle_version_id="context-v1",
        )
        gate = prepare_internal_release(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", quality=quality,
            quality_asset_version_id="quality-v1", review=review,
            review_asset_version_id="review-v1", canon=canon,
            canon_asset_version_id="canon-v1",
            context_bundle={
                "source_isolation_result": {"passed": True},
                "copyright_boundary": "abstract_or_project_owned_only",
            },
            context_bundle_version_id="context-v1",
        )
        self.assertEqual(canon["facts"][0]["object"], "broken")
        self.assertEqual(quality["gate"], "PASSED")
        self.assertEqual(gate["gate"], "PASSED")
        self.assertTrue(gate["rollback_metadata"]["release_not_externally_published"])

    def test_canon_conflict_blocks_quality(self) -> None:
        review = self.review()
        revision = self.revision(review)
        canon = build_canon_update(
            project_id="project-a", revision=revision,
            revision_asset_version_id="revision-v1", context_bundle_version_id="context-v1",
            existing_facts=[{"subject": "alliance", "predicate": "status", "object": "active"}],
        )
        self.assertEqual(canon["gate"], "BLOCKED")
        with self.assertRaisesRegex(KernelError, "CHAPTER_QUALITY_GATE_FAILED"):
            evaluate_quality_evidence(
                project_id="project-a", revision=revision,
                revision_asset_version_id="revision-v1", review=review,
                review_asset_version_id="review-v1", canon=canon,
                canon_asset_version_id="canon-v1", context_bundle_version_id="context-v1",
            )


if __name__ == "__main__":
    unittest.main()
