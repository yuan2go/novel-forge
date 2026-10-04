from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.canon_graph.domain import (
    build_canon_update,
    extract_canon_candidates,
)
from novel_forge.modules.chapter_authority.domain_handlers import build_quality_report
from novel_forge.modules.chapter_quality_authority import (
    CURRENT_CHAPTER_OUTCOME_CONTRACT,
    QUALITY_DIMENSIONS,
    SUPPORTED_CHAPTER_OUTCOME_CONTRACTS,
    build_multiscale_quality_report,
    build_quality_group_evidence,
    validate_chapter_outcome_contract,
)


class CanonSemanticQualityAuthorityTests(unittest.TestCase):
    def test_accepted_quality_projection_reads_v2_v3_history_and_v4_now(
        self,
    ) -> None:
        self.assertEqual(CURRENT_CHAPTER_OUTCOME_CONTRACT, "chapter-outcome-v4")
        self.assertEqual(
            SUPPORTED_CHAPTER_OUTCOME_CONTRACTS,
            ("chapter-outcome-v2", "chapter-outcome-v3", "chapter-outcome-v4"),
        )
        self.assertEqual(
            validate_chapter_outcome_contract("chapter-outcome-v2"),
            "chapter-outcome-v2",
        )
        self.assertEqual(
            validate_chapter_outcome_contract("chapter-outcome-v3"),
            "chapter-outcome-v3",
        )
        with self.assertRaises(KernelError) as raised:
            validate_chapter_outcome_contract("chapter-outcome-v1")
        self.assertEqual(
            raised.exception.code,
            "LONGITUDINAL_QUALITY_OUTCOME_CONTRACT_UNSUPPORTED",
        )

    def test_multiscale_quality_uses_only_accepted_lineage_and_bounded_windows(
        self,
    ) -> None:
        observations = [
            {
                "project_id": "project-1",
                "book_id": "book-1",
                "chapter_number": chapter,
                "acceptance_id": f"acceptance-{chapter}",
                "accepted_asset_version_id": f"outcome-{chapter}",
                "acceptance_status": "COMMITTED",
                "volume_id": "volume-1" if chapter <= 15 else "volume-2",
                "segment_ids": [f"segment-{(chapter - 1) // 5 + 1}"],
                "active_arc_ids": ["arc-main"] if chapter not in {8, 9} else [],
                "character_ids": ["mara"] if chapter != 11 else [],
                "scene_ids": [f"scene-{chapter}-1"],
                "hook_signature": "threat" if chapter <= 12 else "choice",
                "payoff_count": 1 if chapter in {5, 10, 15, 20} else 0,
                "narrative_debt_score": float(chapter % 6),
                "new_world_concept_ids": [f"concept-{chapter}"],
                "average_sentence_length": 20.0 + (chapter % 3),
                "reader_reward_count": 1 if chapter % 4 == 0 else 0,
            }
            for chapter in range(1, 21)
        ]
        report = build_multiscale_quality_report(
            project_id="project-1",
            book_id="book-1",
            context_bundle={
                "context_segments": [
                    {
                        "structured_facts": [
                            {
                                "key": "accepted_quality_observations",
                                "value": observations,
                            }
                        ]
                    }
                ]
            },
            accepted_through_chapter=20,
            source_asset_version_ids=("context-v1",),
        )

        self.assertEqual(report["observation_status"], "MEASURED")
        self.assertEqual(set(report["scales"]), {
            "BOOK", "VOLUME", "ARC", "SEGMENT", "CHAPTER", "SCENE"
        })
        windows = {item["window"]: item for item in report["window_reports"]}
        self.assertEqual(windows["LAST_10_CHAPTERS"]["chapter_range"], [11, 20])
        self.assertEqual(windows["LAST_30_CHAPTERS"]["chapter_count"], 20)
        self.assertEqual(windows["CURRENT_VOLUME"]["chapter_range"], [16, 20])
        self.assertTrue(report["accepted_history_only"])

    def test_multiscale_quality_rejects_unaccepted_or_future_history(self) -> None:
        with self.assertRaises(KernelError) as raised:
            build_multiscale_quality_report(
                project_id="project-1",
                book_id="book-1",
                context_bundle={
                    "context_segments": [{
                        "structured_facts": [{
                            "key": "accepted_quality_observations",
                            "value": [{
                                "project_id": "project-1",
                                "book_id": "book-1",
                                "chapter_number": 4,
                                "acceptance_id": "acceptance-4",
                                "accepted_asset_version_id": "outcome-4",
                                "acceptance_status": "PENDING",
                            }],
                        }],
                    }],
                },
                accepted_through_chapter=3,
                source_asset_version_ids=(),
            )

        self.assertEqual(
            raised.exception.code,
            "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
        )

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

    def test_real_provider_uncalibrated_evidence_participates_without_claiming_calibration(
        self,
    ) -> None:
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
                        "asset_version_id": "provider-quality-v1",
                        "narrative_function": "quality_evidence",
                        "source_expression_included": False,
                        "structured_facts": [
                            {
                                "key": "dimension_evidence",
                                "value": [
                                    {
                                        "dimension": "originality",
                                        "gate_status": "PASSED",
                                        "target_asset_version_id": "revision-current",
                                        "calibration_status": "PROVIDER_UNCALIBRATED",
                                        "provider_verified": True,
                                        "evidence_locations": [
                                            {"start": 0, "end": 18}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            canon={"gate": "PASSED", "conflicts": []},
            fixture=False,
        )

        originality = next(
            item
            for item in group["dimensions"]
            if item["dimension"] == "originality"
        )
        self.assertEqual(originality["gate_status"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(
            originality["calibration_status"], "PROVIDER_UNCALIBRATED"
        )
        self.assertTrue(originality["provider_verified"])
        self.assertFalse(group["production_verified"])

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
