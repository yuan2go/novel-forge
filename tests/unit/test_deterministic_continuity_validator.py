from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    validate_deterministic_continuity,
)


class DeterministicContinuityValidatorTests(unittest.TestCase):
    def test_transition_preconditions_require_an_accepted_entity_baseline(self) -> None:
        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={},
            extraction={
                "character_state_changes": [
                    {
                        "character_id": "hero",
                        "from_status": "IN_GOOD_STANDING",
                        "status": "UNDER_REVIEW",
                    }
                ],
                "timeline_event_candidates": [
                    {
                        "event_id": "event-1",
                        "from_state": "ROUTINE",
                        "state": "DISPUTED",
                    }
                ],
                "foreshadow_changes": [
                    {
                        "thread_id": "thread-1",
                        "from_status": "UNSET",
                        "status": "PLANTED",
                    }
                ],
                "antagonist_pressure_changes": [
                    {
                        "entity_id": "faction-1",
                        "from_state": "DORMANT",
                        "state": "WATCHING",
                    }
                ],
            },
        )

        missing = [
            item
            for item in report["violations"]
            if item["conflict_code"] == "NARRATIVE_TRANSITION_BASELINE_MISSING"
        ]
        self.assertEqual(report["gate"], "BLOCKED")
        self.assertEqual(len(missing), 4)
        self.assertTrue(
            all(item["evidence"]["existing"] is None for item in missing)
        )

    def test_explicit_temporal_identity_death_knowledge_and_graph_rules_block(
        self,
    ) -> None:
        report = validate_deterministic_continuity(
            chapter=20,
            historical_state={
                "timeline_snapshot": [{"event_id": "event-1", "chapter": 19}],
                "character_state": [
                    {
                        "character_id": "hero",
                        "canonical_name": "Lin",
                        "life_status": "DEAD",
                        "known_fact_ids": ["fact-old"],
                    },
                    {"character_id": "ally", "canonical_name": "Mei"},
                ],
            },
            extraction={
                "timeline_event_candidates": [
                    {
                        "event_id": "event-future",
                        "effective_from_chapter": 21,
                    }
                ],
                "character_state_changes": [
                    {
                        "character_id": "hero",
                        "canonical_name": "Other Lin",
                        "action_state": "ACTIVE",
                        "requires_fact_ids": ["fact-future"],
                    }
                ],
                "relationship_changes": [
                    {"source_id": "hero", "target_id": "hero", "status": "ALLY"}
                ],
            },
        )

        self.assertEqual(report["gate"], "BLOCKED")
        self.assertTrue(
            {
                "FUTURE_STATE_LEAK",
                "CHARACTER_IDENTITY_CONTRADICTION",
                "DEAD_CHARACTER_USAGE",
                "KNOWLEDGE_BOUNDARY_VIOLATION",
                "GRAPH_INTEGRITY_VIOLATION",
            }.issubset({item["conflict_code"] for item in report["violations"]})
        )
        self.assertEqual(
            report["semantic_judgment_required"],
            ["CHARACTER_MOTIVATION", "EMOTIONAL_PLAUSIBILITY", "OOC"],
        )

    def test_explicit_transition_and_balance_invariants_block(self) -> None:
        report = validate_deterministic_continuity(
            chapter=40,
            historical_state={
                "relationship_state": [
                    {
                        "source_id": "hero",
                        "target_id": "ally",
                        "status": "HOSTILE",
                    }
                ],
                "foreshadow_state": [{"thread_id": "f-1", "status": "PAID"}],
                "reader_promise": [{"promise_id": "p-1", "status": "PAID"}],
                "power_state": [{"character_id": "hero", "tier": 3}],
                "resource_state": [
                    {"entity_id": "hero", "resource_id": "mana", "balance": 10}
                ],
                "world_rule": [{"rule_id": "w-1", "forbidden_states": ["teleport"]}],
            },
            extraction={
                "relationship_changes": [
                    {
                        "source_id": "hero",
                        "target_id": "ally",
                        "from_state": "TRUSTED",
                        "status": "ALLY",
                    }
                ],
                "foreshadow_changes": [
                    {"thread_id": "f-1", "from_status": "OPEN", "status": "PAID"}
                ],
                "promise_changes": [
                    {"promise_id": "p-1", "from_status": "OPEN", "status": "PAID"}
                ],
                "power_state_changes": [
                    {
                        "character_id": "hero",
                        "from_tier": 2,
                        "tier": 4,
                        "transition_kind": "ADVANCE",
                        "change_reasons": [],
                    }
                ],
                "resource_state_changes": [
                    {
                        "entity_id": "hero",
                        "resource_id": "mana",
                        "balance_before": 10,
                        "delta": -4,
                        "balance_after": 8,
                    }
                ],
                "world_rule_usages": [
                    {"rule_id": "w-1", "state": "teleport", "exception": False}
                ],
            },
        )

        codes = {item["conflict_code"] for item in report["violations"]}
        self.assertTrue(
            {
                "INVALID_RELATIONSHIP_TRANSITION",
                "FORESHADOW_LIFECYCLE_CONTRADICTION",
                "PROMISE_LIFECYCLE_CONTRADICTION",
                "POWER_STATE_TRANSITION_INVALID",
                "RESOURCE_STATE_BALANCE_INVALID",
                "WORLD_RULE_CONTRADICTION",
            }.issubset(codes)
        )

    def test_only_declared_state_is_checked_without_heuristic_text_matching(
        self,
    ) -> None:
        report = validate_deterministic_continuity(
            chapter=12,
            historical_state={},
            extraction={
                "raw_text": "dead betrayed impossible too powerful",
                "character_state_changes": [],
                "relationship_changes": [],
            },
        )
        self.assertEqual(report["gate"], "PASSED")
        self.assertEqual(report["violations"], [])
        self.assertFalse(report["used_text_heuristics"])


if __name__ == "__main__":
    unittest.main()
