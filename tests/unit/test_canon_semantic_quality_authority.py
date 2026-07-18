from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    build_canon_update,
    extract_canon_candidates,
)
from novel_forge.modules.chapter_authority.domain_handlers import build_quality_report
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS


class CanonSemanticQualityAuthorityTests(unittest.TestCase):
    def test_digest_is_identity_only_not_semantic_change(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-1",
            revision={"chapter": 1, "text": "The door closes."},
            revision_asset_version_id="revision-v1",
            context_bundle_version_id="context-v1",
        )

        self.assertTrue(extraction["digest_identity_only"])
        self.assertEqual(extraction["semantic_change_count"], 0)
        self.assertEqual(extraction["semantic_coverage"], "INSUFFICIENT")
        digest = extraction["canon_assertion_candidates"][0]
        self.assertEqual(digest["extractor_type"], "deterministic_revision_digest")
        self.assertEqual(digest["confidence"], 1.0)

    def test_low_confidence_high_impact_change_requires_approval(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-1",
            revision={
                "chapter": 2,
                "text": "After the blast, nobody can confirm whether Lin survived.",
                "character_state_changes": [
                    {
                        "character_id": "lin",
                        "status": "dead",
                        "impact_type": "character_death",
                        "confidence": 0.55,
                        "evidence_start": 0,
                        "evidence_end": 59,
                    }
                ],
            },
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
        )
        update = build_canon_update(
            project_id="project-1",
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            extraction=extraction,
        )

        self.assertEqual(extraction["semantic_coverage"], "EXTRACTED")
        self.assertEqual(
            extraction["character_state_changes"][0]["approval_requirement"],
            "REQUIRED",
        )
        self.assertEqual(update["gate"], "BLOCKED")
        self.assertTrue(
            any(
                item["conflict_code"]
                == "HIGH_IMPACT_SEMANTIC_CHANGE_REQUIRES_APPROVAL"
                for item in update["conflicts"]
            )
        )

    def test_quality_aggregate_contains_all_target_bound_dimensions(self) -> None:
        report = build_quality_report(
            project_id="project-1",
            revision={
                "chapter": 1,
                "text": "A choice is made, but the safe road is surrendered as its cost.",
            },
            revision_asset_version_id="revision-v1",
            review={
                "report_type": "ReReviewReport",
                "decision": "PASSED",
                "blocking_issue_count": 0,
                "score": 88,
                "provider_evidence": {"real_model_call": False},
            },
            review_asset_version_id="rereview-v1",
            canon={"gate": "PASSED", "conflicts": []},
            canon_asset_version_id="canon-v1",
            context_bundle_version_id="context-v1",
            context_bundle={
                "source_isolation_result": {"passed": True},
                "context_segments": [],
            },
        )

        evidence = report["evidence_reports"]
        self.assertEqual({item["dimension"] for item in evidence}, set(QUALITY_DIMENSIONS))
        self.assertTrue(
            all(item["target_asset_version_id"] == "revision-v1" for item in evidence)
        )
        self.assertFalse(report["production_verified"])
        self.assertIn("originality", report["uncalibrated_dimensions"])


if __name__ == "__main__":
    unittest.main()
