from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.approval_domain import (
    build_canon_change_proposal,
    resolve_canon_extraction,
    validate_edited_canon_payload,
)
from novel_forge.modules.command_kernel.errors import KernelError


def extraction() -> dict:
    return {
        "project_id": "project-a", "chapter": 2,
        "revision_asset_version_id": "revision-v2",
        "canon_assertion_candidates": [],
        "character_state_changes": [{
            "character_id": "hero", "status": "dead", "impact_type": "character_death",
            "confidence": .9, "approval_requirement": "REQUIRED",
            "extraction_evidence": {
                "span": {"start": 0, "end": 10}, "excerpt_digest": "sha256:evidence",
                "previous_state_reference": "character-state-v1",
            },
        }],
        "relationship_changes": [], "timeline_event_candidates": [],
        "foreshadow_changes": [], "promise_changes": [], "reward_changes": [],
        "world_rule_usages": [], "power_state_changes": [],
        "plot_thread_changes": [], "resource_state_changes": [],
        "narrative_pattern_fingerprints": [], "theme_movements": [],
        "antagonist_pressure_changes": [],
    }


class CanonApprovalDomainTests(unittest.TestCase):
    def test_high_impact_change_requires_per_change_decision(self) -> None:
        proposal = build_canon_change_proposal(
            project_id="project-a", extraction=extraction(),
            extraction_asset_version_id="extraction-v2",
        )
        self.assertEqual(len(proposal["approval_required_change_ids"]), 1)
        with self.assertRaisesRegex(KernelError, "CANON_APPROVAL_INCOMPLETE"):
            resolve_canon_extraction(extraction=extraction(), proposal=proposal, decisions=[])

    def test_reject_excludes_and_edit_uses_approved_payload(self) -> None:
        proposal = build_canon_change_proposal(
            project_id="project-a", extraction=extraction(),
            extraction_asset_version_id="extraction-v2",
        )
        change_id = proposal["changes"][0]["change_id"]
        rejected = resolve_canon_extraction(
            extraction=extraction(), proposal=proposal,
            decisions=[{"change_id": change_id, "decision": "REJECT", "asset_version_id": "decision-v1"}],
        )
        self.assertEqual(rejected["character_state_changes"], [])
        edited = resolve_canon_extraction(
            extraction=extraction(), proposal=proposal,
            decisions=[{
                "change_id": change_id, "decision": "EDIT_AND_APPROVE",
                "change_resolution": validate_edited_canon_payload(
                    project_id="project-a",
                    change=proposal["changes"][0],
                    edited_payload={"character_id": "hero", "status": "missing"},
                ),
                "asset_version_id": "decision-v2",
            }],
        )
        self.assertEqual(edited["character_state_changes"][0]["status"], "missing")
        self.assertEqual(
            edited["character_state_changes"][0]["approval_resolution"]["decision"],
            "EDIT_AND_APPROVE",
        )

    def test_edited_payload_cannot_change_identity_or_cross_project(self) -> None:
        proposal = build_canon_change_proposal(
            project_id="project-a", extraction=extraction(),
            extraction_asset_version_id="extraction-v2",
        )
        with self.assertRaisesRegex(KernelError, "CANON_EDITED_PAYLOAD_INVALID"):
            validate_edited_canon_payload(
                project_id="project-a",
                change=proposal["changes"][0],
                edited_payload={"character_id": "villain", "project_id": "project-b"},
            )

    def test_high_impact_without_digest_is_rejected(self) -> None:
        broken = extraction()
        broken["character_state_changes"][0]["extraction_evidence"]["excerpt_digest"] = ""
        with self.assertRaisesRegex(KernelError, "CANON_HIGH_IMPACT_EVIDENCE_REQUIRED"):
            build_canon_change_proposal(
                project_id="project-a", extraction=broken,
                extraction_asset_version_id="extraction-v2",
            )

    def test_distinct_fact_predicates_and_event_spans_are_not_contradictions(self) -> None:
        candidate = extraction()
        candidate["canon_assertion_candidates"] = [
            {
                "subject": "hero", "predicate": "owns", "object": "sword",
                "impact_type": "REVEAL", "confidence": .9,
                "extraction_evidence": {"span": {"start": 10, "end": 20}},
            },
            {
                "subject": "hero", "predicate": "visits", "object": "city",
                "impact_type": "REVEAL", "confidence": .9,
                "extraction_evidence": {"span": {"start": 21, "end": 30}},
            },
        ]
        candidate["timeline_event_candidates"] = [
            {
                "summary": "first event", "impact_type": "EVENT", "confidence": .9,
                "extraction_evidence": {"span": {"start": 31, "end": 40}},
            },
            {
                "summary": "second event", "impact_type": "EVENT", "confidence": .9,
                "extraction_evidence": {"span": {"start": 41, "end": 50}},
            },
        ]

        proposal = build_canon_change_proposal(
            project_id="project-a", extraction=candidate,
            extraction_asset_version_id="extraction-v2",
        )

        self.assertEqual(len(proposal["changes"]), 5)

    def test_same_fact_slot_with_different_objects_is_rejected(self) -> None:
        candidate = extraction()
        candidate["canon_assertion_candidates"] = [
            {
                "subject": "hero", "predicate": "owns", "object": "sword",
                "impact_type": "REVEAL", "confidence": .9,
                "extraction_evidence": {"span": {"start": 10, "end": 20}},
            },
            {
                "subject": "hero", "predicate": "owns", "object": "crown",
                "impact_type": "REVEAL", "confidence": .9,
                "extraction_evidence": {"span": {"start": 21, "end": 30}},
            },
        ]

        with self.assertRaisesRegex(KernelError, "CANON_EXTRACTION_CONTRADICTION"):
            build_canon_change_proposal(
                project_id="project-a", extraction=candidate,
                extraction_asset_version_id="extraction-v2",
            )

    def test_disclosure_identity_is_not_derived_from_shared_evidence_span(self) -> None:
        candidate = extraction()
        shared = {
            "fact_id": "fact:witness-alive",
            "impact_type": "DISCLOSURE",
            "confidence": .9,
            "disclosure_mode": "CONFIRM",
            "extraction_evidence": {"span": {"start": 10, "end": 20}},
        }
        candidate["disclosure_events"] = [
            {
                **shared,
                "disclosure_id": "disclosure:witness:character",
                "audience": "character:lin",
            },
            {
                **shared,
                "disclosure_id": "disclosure:witness:reader",
                "audience": "READER",
            },
        ]

        proposal = build_canon_change_proposal(
            project_id="project-a",
            extraction=candidate,
            extraction_asset_version_id="extraction-v2",
        )

        disclosures = [
            item for item in proposal["changes"]
            if item["change_field"] == "disclosure_events"
        ]
        self.assertEqual(len(disclosures), 2)

    def test_same_disclosure_identity_with_conflicting_audience_is_rejected(self) -> None:
        candidate = extraction()
        shared = {
            "disclosure_id": "disclosure:witness",
            "fact_id": "fact:witness-alive",
            "impact_type": "DISCLOSURE",
            "confidence": .9,
            "disclosure_mode": "CONFIRM",
            "extraction_evidence": {"span": {"start": 10, "end": 20}},
        }
        candidate["disclosure_events"] = [
            {**shared, "audience": "character:lin"},
            {**shared, "audience": "READER"},
        ]

        with self.assertRaisesRegex(KernelError, "CANON_EXTRACTION_CONTRADICTION"):
            build_canon_change_proposal(
                project_id="project-a",
                extraction=candidate,
                extraction_asset_version_id="extraction-v2",
            )


if __name__ == "__main__":
    unittest.main()
