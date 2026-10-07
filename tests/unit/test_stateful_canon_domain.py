from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    build_canon_update,
    extract_canon_candidates,
)


class StatefulCanonDomainTests(unittest.TestCase):
    def extraction(self):
        return extract_canon_candidates(
            project_id="project-a",
            revision={
                "chapter": 2,
                "text": "The alliance breaks after the costly choice.",
                "canon_assertions": [
                    {"subject": "alliance", "predicate": "status", "object": "broken"}
                ],
                "timeline_events": [
                    {
                        "event_id": "timeline:late-insertion",
                        "effective_from_chapter": 1,
                        "event": "late insertion",
                    }
                ],
                "character_state_changes": [
                    {"character_id": "hero", "canonical_name": "Different Hero"}
                ],
                "world_rule_usages": [{"exception": True, "cost": ""}],
                "power_state_changes": [{"tier_increase": True, "change_reasons": []}],
                "foreshadow_changes": [{"status": "PAID", "payoff_evidence": ""}],
                "promise_changes": [{"status": "PAID", "payoff_evidence": ""}],
            },
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
        )

    def test_real_path_always_has_independent_digest_assertion(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 1, "text": "A choice changes the public record."},
            revision_asset_version_id="revision-v1",
            context_bundle_version_id="context-v1",
        )
        self.assertEqual(extraction["extraction_source"], "deterministic_extractor")
        self.assertEqual(
            extraction["canon_assertion_candidates"][-1]["predicate"],
            "accepted_revision_digest",
        )

    def test_reader_knowledge_is_derived_from_disclosure_mode(self) -> None:
        base = {
            "summary": "A ledger mark hints that the witness was present.",
            "effective_from_chapter": 2,
            "disclosure_id": "disclosure:witness-mark",
            "fact_id": "fact:witness-present",
            "audience": "READER",
            "presentation_channel": "OBJECT_DETAIL",
            "evidence_start": 0,
            "evidence_end": 12,
            "confidence": 0.9,
            "impact_type": "reader_disclosure",
        }
        hinted = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 2, "text": "A ledger mark appears in the margin."},
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            provider_extraction={
                "disclosure_events": [{**base, "disclosure_mode": "HINT"}]
            },
        )
        confirmed = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 2, "text": "The ledger confirms the witness."},
            revision_asset_version_id="revision-v2b",
            context_bundle_version_id="context-v2",
            provider_extraction={
                "disclosure_events": [{**base, "disclosure_mode": "CONFIRM"}]
            },
        )

        self.assertEqual(hinted["reader_knowledge_changes"][0]["status"], "HINTED")
        self.assertEqual(confirmed["reader_knowledge_changes"][0]["status"], "KNOWN")
        self.assertEqual(
            hinted["reader_knowledge_changes"][0]["extractor_type"],
            "derived_disclosure_projection",
        )

    def test_character_knowledge_bundle_becomes_atomic_canon_state(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 2, "text": "The witness reads both entries."},
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            provider_extraction={
                "character_knowledge_changes": [
                    {
                        "character_id": "character:lin",
                        "acquired_fact_ids": ["fact:first", "fact:second"],
                        "status": "KNOWN",
                        "effective_from_chapter": 2,
                    }
                ]
            },
        )
        update = build_canon_update(
            project_id="project-a",
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            extraction=extraction,
            historical_state={},
        )

        self.assertEqual(
            [
                (item["character_id"], item["fact_id"], item["entity_version"])
                for item in update["state_changes"]["character_knowledge"]
            ],
            [
                ("character:lin", "fact:first", 1),
                ("character:lin", "fact:second", 1),
            ],
        )

    def test_unified_obligation_payoff_reaches_canon_state_changes(self) -> None:
        extraction = extract_canon_candidates(
            project_id="project-a",
            revision={"chapter": 2, "text": "The witness sees the promise fulfilled."},
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            provider_extraction={
                "obligation_changes": [
                    {
                        "obligation_id": "promise:late",
                        "obligation_type": "PROMISE",
                        "from_status": "OPEN",
                        "status": "FULFILLED",
                        "priority": "HIGH",
                        "target_window": {
                            "status": "SCHEDULED",
                            "from_chapter": 1,
                            "to_chapter": 2,
                        },
                        "payoff_evidence": {
                            "asset_version_id": "revision-v2",
                            "event_id": "payoff:event:2",
                        },
                        "linked_arc_ids": ["arc:v1"],
                        "summary": "The accepted choice fulfills the promise.",
                    }
                ]
            },
        )
        update = build_canon_update(
            project_id="project-a",
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            extraction=extraction,
            historical_state={
                "narrative_obligation": [
                    {
                        "asset_version_id": "story-state:v1",
                        "obligation_id": "promise:late",
                        "status": "OPEN",
                        "entity_version": 1,
                    }
                ]
            },
        )

        obligation = update["state_changes"]["narrative_obligation"][0]
        self.assertEqual(obligation["status"], "FULFILLED")
        self.assertEqual(obligation["entity_version"], 2)
        self.assertEqual(update["gate"], "PASSED")

    def test_historical_state_detects_typed_cross_chapter_conflicts(self) -> None:
        state = {
            "canon_snapshot": [
                {
                    "asset_version_id": "canon-v1",
                    "subject": "alliance",
                    "predicate": "status",
                    "object": "active",
                }
            ],
            "timeline_snapshot": [{"asset_version_id": "timeline-v1", "chapter": 2}],
            "character_state": [
                {
                    "asset_version_id": "character-v1",
                    "character_id": "hero",
                    "canonical_name": "Hero",
                }
            ],
            "world_rule": [{"asset_version_id": "world-v1"}],
            "power_state": [{"asset_version_id": "power-v1"}],
            "foreshadow_state": [{"asset_version_id": "foreshadow-v1"}],
            "reader_promise": [{"asset_version_id": "promise-v1"}],
        }
        update = build_canon_update(
            project_id="project-a",
            revision_asset_version_id="revision-v2",
            context_bundle_version_id="context-v2",
            extraction=self.extraction(),
            historical_state=state,
        )
        codes = {item["conflict_code"] for item in update["conflicts"]}
        self.assertTrue(
            {
                "FACT_CONTRADICTION",
                "TEMPORAL_CONTRADICTION",
                "CHARACTER_IDENTITY_CONTRADICTION",
                "WORLD_RULE_CONTRADICTION",
                "POWER_PROGRESSION_CONTRADICTION",
                "FORESHADOW_LIFECYCLE_CONTRADICTION",
                "PROMISE_LIFECYCLE_CONTRADICTION",
            }.issubset(codes)
        )
        self.assertEqual(update["gate"], "BLOCKED")
        self.assertIn("canon_fact", update["state_changes"])
        self.assertIn("character_state", update["state_changes"])
        self.assertNotIn("snapshot_candidates", update)
        self.assertIn("canon-v1", update["historical_input_version_ids"])


if __name__ == "__main__":
    unittest.main()



def test_typed_knowledge_plan_label_preserves_cas_and_does_not_create_accepted_history():
    from novel_forge.modules.canon_graph.domain import _validate_planned_execution
    plan = {"required_state_transitions": [{"state_kind": "character_knowledge", "entity_key": "zhou:roster", "from_state": "UNKNOWN", "to_state": "KNOWN：亲见栏目差异"}]}
    event = {"character_id": "zhou", "proposition_id": "roster", "status": "KNOWN", "from_status": None}
    failures = []
    _validate_planned_execution(failures, state={}, extraction={"character_knowledge_changes": [event]}, planned_execution=plan)
    assert failures == []
    for invalid in ({**event, "status": "SUSPECTED"}, {**event, "from_status": "UNKNOWN"}):
        failures = []
        _validate_planned_execution(failures, state={}, extraction={"character_knowledge_changes": [invalid]}, planned_execution=plan)
        assert failures[0]["conflict_code"] == "PLANNED_STATE_TRANSITION_MISMATCH"
