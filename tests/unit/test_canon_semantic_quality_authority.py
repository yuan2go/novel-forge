from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    build_canon_update,
    extract_canon_candidates,
)
from novel_forge.modules.chapter_authority.domain_handlers import build_quality_report
from novel_forge.modules.chapter_quality_authority import (
    QUALITY_DIMENSIONS,
    build_quality_group_evidence,
)


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

    def test_nonfixture_quality_evidence_for_wrong_revision_is_not_accepted(self) -> None:
        group = build_quality_group_evidence(
            group="source_originality", project_id="project-1",
            revision={"chapter": 1, "text": "A complete sentence. Another consequence follows."},
            revision_asset_version_id="revision-current",
            context_bundle={
                "source_isolation_result": {"passed": True},
                "copyright_boundary": "abstract_or_project_owned_only",
                "context_segments": [{
                    "asset_version_id": "old-quality-v1",
                    "narrative_function": "quality_evidence",
                    "source_expression_included": False,
                    "structured_facts": [{"key": "dimension_evidence", "value": [{
                        "dimension": "originality", "gate_status": "PASSED",
                        "target_asset_version_id": "revision-old",
                        "calibration_status": "HUMAN_CALIBRATED", "human_verified": True,
                    }]}],
                }],
            },
            canon={"gate": "PASSED", "conflicts": []}, fixture=False,
        )
        originality = next(item for item in group["dimensions"] if item["dimension"] == "originality")
        self.assertEqual(originality["gate_status"], "REQUIRES_PROVIDER_JUDGE")
        self.assertIn("originality", group["blocking_dimension_codes"])

    def test_fixture_human_claim_is_normalized_to_uncalibrated(self) -> None:
        group = build_quality_group_evidence(
            group="source_originality",
            project_id="project-1",
            revision={
                "chapter": 1,
                "text": "A complete sentence. Another consequence follows.",
            },
            revision_asset_version_id="revision-current",
            context_bundle={
                "source_isolation_result": {"passed": True},
                "copyright_boundary": "abstract_or_project_owned_only",
                "context_segments": [
                    {
                        "asset_version_id": "fixture-quality-v1",
                        "source_expression_included": False,
                        "structured_facts": [
                            {
                                "key": "dimension_evidence",
                                "value": [
                                    {
                                        "dimension": "originality",
                                        "gate_status": "PASSED",
                                        "calibration_status": "HUMAN_CALIBRATED",
                                        "human_verified": True,
                                        "fixture_protocol_only": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            canon={"gate": "PASSED", "conflicts": []},
            fixture=True,
        )
        originality = next(
            item
            for item in group["dimensions"]
            if item["dimension"] == "originality"
        )
        self.assertEqual(
            originality["gate_status"], "PASSED_WITH_UNCALIBRATED"
        )
        self.assertEqual(
            originality["calibration_status"], "FIXTURE_UNCALIBRATED"
        )

    def test_fixture_waiver_requires_versioned_scoped_approval(self) -> None:
        project_id = "project-1"
        common = {
            "source_isolation_result": {"passed": True},
            "copyright_boundary": "abstract_or_project_owned_only",
            "context_segments": [
                {
                    "asset_type": "operator_checklist",
                    "asset_version_id": "checklist-v1",
                    "source_expression_included": False,
                    "structured_facts": [
                        {"key": "completed", "value": True},
                        {
                            "key": "contract_version",
                            "value": "fixture-waiver-checklist-v1",
                        },
                    ],
                },
                {
                    "asset_type": "operator_approval",
                    "asset_version_id": "approval-v1",
                    "source_expression_included": False,
                    "structured_facts": [
                        {"key": "decision", "value": "APPROVED"},
                        {
                            "key": "contract_version",
                            "value": "fixture-waiver-approval-v1",
                        },
                        {"key": "waiver_reason", "value": "fixture protocol"},
                        {"key": "waived_dimensions", "value": ["originality"]},
                        {
                            "key": "scope",
                            "value": {
                                "project_id": project_id,
                                "scope_type": "PROJECT_FIXTURE",
                                "release_readiness": "INTERNAL_REVIEW_RELEASE",
                            },
                        },
                        {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                        {"key": "fixture_protocol_only", "value": True},
                    ],
                },
                {
                    "asset_type": "source_originality_quality_report",
                    "asset_version_id": "fixture-quality-v1",
                    "source_expression_included": False,
                    "structured_facts": [
                        {
                            "key": "dimension_evidence",
                            "value": [
                                {
                                    "dimension": "originality",
                                    "gate_status": "WAIVED_BY_APPROVAL",
                                    "calibration_status": "FIXTURE_UNCALIBRATED",
                                    "fixture_protocol_only": True,
                                }
                            ],
                        }
                    ],
                },
            ],
        }
        group = build_quality_group_evidence(
            group="source_originality",
            project_id=project_id,
            revision={
                "chapter": 1,
                "text": "A complete sentence. Another consequence follows.",
            },
            revision_asset_version_id="revision-current",
            context_bundle=common,
            canon={"gate": "PASSED", "conflicts": []},
            fixture=True,
        )
        originality = next(
            item
            for item in group["dimensions"]
            if item["dimension"] == "originality"
        )
        self.assertEqual(originality["gate_status"], "WAIVED_BY_APPROVAL")
        self.assertEqual(
            originality["waiver"]["approval_asset_version_id"],
            "approval-v1",
        )
        self.assertFalse(originality["waiver"]["production_verified"])


if __name__ == "__main__":
    unittest.main()
