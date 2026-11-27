from __future__ import annotations

import unittest

from novel_forge.modules.canon_graph.domain import (
    validate_deterministic_continuity,
)


class DeterministicContinuityValidatorTests(unittest.TestCase):
    def test_real_failure_lin_yao_wrong_pronoun_is_blocking(self) -> None:
        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={},
            extraction={},
            revision_text=(
                "收档钟敲过第一遍时，林遥还蹲在路沿边。\n\n"
                "他把底图压在膝上，沿图中道路的东缘重新量了一次。"
            ),
            identity_profiles=(
                {
                    "character_id": "lin-yao",
                    "canonical_name": "林遥",
                    "aliases": ["林遥"],
                    "pronouns": ["她"],
                    "source_asset_version_id": "character-cast:93846845",
                },
            ),
        )

        self.assertEqual(report["gate"], "BLOCKED")
        violation = next(
            item
            for item in report["violations"]
            if item["conflict_code"]
            == "CHARACTER_IDENTITY_PRONOUN_CONTRADICTION"
        )
        self.assertEqual(violation["evidence"]["candidate"]["observed_pronoun"], "他")
        self.assertEqual(
            violation["evidence"]["existing"]["source_asset_version_id"],
            "character-cast:93846845",
        )

    def test_real_failure_director_xu_wrong_pronoun_is_blocking(self) -> None:
        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={},
            extraction={},
            revision_text=(
                "徐主任的通话随即接入。\n\n"
                "他没有问路长什么样，只扫了一眼材料目录。"
            ),
            identity_profiles=(
                {
                    "character_id": "director-xu",
                    "canonical_name": "徐主任",
                    "aliases": ["徐主任"],
                    "pronouns": ["她"],
                    "source_asset_version_id": "character-cast:f34db8be",
                },
            ),
        )

        self.assertEqual(report["gate"], "BLOCKED")
        self.assertIn(
            "CHARACTER_IDENTITY_PRONOUN_CONTRADICTION",
            {item["conflict_code"] for item in report["violations"]},
        )

    def test_identity_checker_does_not_guess_without_explicit_vocabulary(self) -> None:
        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={},
            extraction={},
            revision_text="林遥转向乔生。他看着她，没有说话。",
            identity_profiles=(),
        )

        self.assertEqual(report["gate"], "PASSED")
        self.assertEqual(report["violations"], [])

    def test_foreshadow_transition_matches_canonical_entity_across_obligation_adapter(
        self,
    ) -> None:
        report = validate_deterministic_continuity(
            chapter=2,
            historical_state={
                "narrative_obligation": [
                    {
                        "entity_id": "foreshadow:mount-markers",
                        "obligation_id": "promise:explain-mount-markers",
                        "state": "PLANTED_UNINTERPRETED",
                        "status": "OPEN",
                    }
                ]
            },
            extraction={
                "foreshadow_changes": [
                    {
                        "entity_id": "foreshadow:mount-markers",
                        "thread_id": "thread:record-contradiction",
                        "promise_id": "promise:explain-mount-markers",
                        "from_state": "PLANTED_UNINTERPRETED",
                        "from_status": "OPEN",
                        "state": "EDGE_ANOMALY_OBSERVED_UNAUTHENTICATED",
                        "status": "OPEN",
                    }
                ]
            },
        )

        self.assertEqual(report["gate"], "PASSED")
        self.assertNotIn(
            "NARRATIVE_TRANSITION_BASELINE_MISSING",
            {item["conflict_code"] for item in report["violations"]},
        )

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
        self.assertTrue(all(item["evidence"]["existing"] is None for item in missing))

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
            [
                "CHARACTER_MOTIVATION",
                "EMOTIONAL_PLAUSIBILITY",
                "OOC",
                "EXPECTED_EXIT_STATE",
            ],
        )

    def test_chapter_execution_transitions_and_disclosures_are_acceptance_gates(
        self,
    ) -> None:
        planned = {
            "required_state_transitions": [
                {
                    "state_kind": "character_arc",
                    "entity_key": "protagonist:accountability",
                    "from_state": "DENIAL",
                    "to_state": "COMMITTED",
                }
            ],
            "disclosures": [
                {
                    "disclosure_id": "disclosure:hidden-cost",
                    "fact_id": "fact:hidden-cost",
                    "audience": "READER",
                    "mode": "HINT",
                }
            ],
        }
        missing = validate_deterministic_continuity(
            chapter=2,
            historical_state={},
            extraction={},
            planned_execution=planned,
        )
        matched = validate_deterministic_continuity(
            chapter=2,
            historical_state={
                "character_arc": [
                    {
                        "character_id": "protagonist",
                        "arc_id": "character-arc:accountability",
                        "state": "DENIAL",
                    }
                ]
            },
            extraction={
                "character_arc_changes": [
                    {
                        "character_id": "protagonist",
                        "arc_id": "character-arc:accountability",
                        "from_state": "DENIAL",
                        "state": "COMMITTED",
                    }
                ],
                "disclosure_events": [
                    {
                        "disclosure_id": "disclosure:hidden-cost",
                        "fact_id": "fact:hidden-cost",
                        "audience": "READER",
                        "disclosure_mode": "HINT",
                    }
                ],
                "reader_knowledge_changes": [
                    {"fact_id": "fact:hidden-cost", "status": "HINTED"}
                ],
            },
            planned_execution=planned,
        )

        self.assertEqual(missing["gate"], "BLOCKED")
        self.assertEqual(
            {item["conflict_code"] for item in missing["violations"]},
            {"PLANNED_STATE_TRANSITION_MISSING", "PLANNED_DISCLOSURE_MISSING"},
        )
        self.assertEqual(matched["gate"], "PASSED")

    def test_character_belief_uses_stance_for_cas_and_plan_reconciliation(self) -> None:
        report = validate_deterministic_continuity(
            chapter=2,
            historical_state={
                "character_belief": [
                    {
                        "character_id": "hero",
                        "proposition_id": "proposition:silence-is-safe",
                        "stance": "BELIEVES",
                    }
                ]
            },
            extraction={
                "character_belief_changes": [
                    {
                        "character_id": "hero",
                        "proposition_id": "proposition:silence-is-safe",
                        "from_stance": "BELIEVES",
                        "stance": "DOUBTS",
                        "belief_confidence": 0.7,
                    }
                ]
            },
            planned_execution={
                "required_state_transitions": [
                    {
                        "state_kind": "character_belief",
                        "entity_key": "hero:proposition:silence-is-safe",
                        "from_state": "BELIEVES",
                        "to_state": "DOUBTS",
                    }
                ]
            },
        )

        self.assertEqual(report["gate"], "PASSED")

    def test_planned_execution_accepts_exact_generic_entity_identity(self) -> None:
        planned = {
            "required_state_transitions": [
                {
                    "state_kind": "character_arc",
                    "entity_key": "alice:arc:accountability",
                    "from_state": "DENIAL",
                    "to_state": "COMMITTED",
                },
                {
                    "state_kind": "foreshadow_state",
                    "entity_key": "obligation:explain-ledger",
                    "from_state": "UNGROUNDED",
                    "to_state": "GROUNDED",
                },
            ]
        }

        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={},
            extraction={
                "character_arc_changes": [
                    {
                        "entity_id": "alice:arc:accountability",
                        "character_id": "alice",
                        "arc_id": "alice:arc:accountability",
                        "state": "COMMITTED",
                    }
                ],
                "foreshadow_changes": [
                    {
                        "entity_id": "obligation:explain-ledger",
                        "thread_id": "thread:ledger",
                        "state": "GROUNDED",
                    }
                ],
            },
            planned_execution=planned,
        )

        self.assertEqual(report["gate"], "PASSED")

    def test_planned_execution_uses_frozen_precondition_when_extraction_omits_it(
        self,
    ) -> None:
        planned = {
            "required_state_transitions": [
                {
                    "state_kind": "world_rule",
                    "entity_key": "rule:revision-traces",
                    "from_state": "UNGROUNDED",
                    "to_state": "GROUNDED",
                }
            ]
        }

        report = validate_deterministic_continuity(
            chapter=1,
            historical_state={
                "world_rule": [
                    {"rule_id": "rule:revision-traces", "state": "UNGROUNDED"}
                ]
            },
            extraction={
                "world_rule_usages": [
                    {
                        "rule_id": "rule:revision-traces",
                        "state": "GROUNDED",
                    }
                ]
            },
            planned_execution=planned,
        )

        self.assertEqual(report["gate"], "PASSED")

        mismatched = validate_deterministic_continuity(
            chapter=1,
            historical_state={
                "world_rule": [
                    {"rule_id": "rule:revision-traces", "state": "UNGROUNDED"}
                ]
            },
            extraction={
                "world_rule_usages": [
                    {
                        "rule_id": "rule:revision-traces",
                        "from_state": "CONTRADICTED",
                        "state": "GROUNDED",
                    }
                ]
            },
            planned_execution=planned,
        )

        self.assertEqual(mismatched["gate"], "BLOCKED")

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

    def test_reader_knowledge_requires_reader_facing_disclosure(self) -> None:
        blocked = validate_deterministic_continuity(
            chapter=3,
            historical_state={},
            extraction={
                "reader_knowledge_changes": [
                    {"fact_id": "fact:traitor", "status": "KNOWN"}
                ],
                "disclosure_events": [],
            },
        )
        mismatched = validate_deterministic_continuity(
            chapter=3,
            historical_state={},
            extraction={
                "reader_knowledge_changes": [
                    {"fact_id": "fact:traitor", "status": "KNOWN"}
                ],
                "disclosure_events": [
                    {
                        "disclosure_id": "disclosure:traitor",
                        "fact_id": "fact:traitor",
                        "audience": "READER",
                        "disclosure_mode": "HINT",
                    }
                ],
            },
        )
        passed = validate_deterministic_continuity(
            chapter=3,
            historical_state={},
            extraction={
                "reader_knowledge_changes": [
                    {"fact_id": "fact:traitor", "status": "HINTED"}
                ],
                "disclosure_events": [
                    {
                        "disclosure_id": "disclosure:traitor",
                        "fact_id": "fact:traitor",
                        "audience": "READER",
                        "disclosure_mode": "HINT",
                        "presentation_channel": "OBJECT_DETAIL",
                    }
                ],
            },
        )

        self.assertEqual(blocked["gate"], "BLOCKED")
        self.assertEqual(
            blocked["violations"][0]["conflict_code"],
            "READER_KNOWLEDGE_DISCLOSURE_MISMATCH",
        )
        self.assertEqual(mismatched["gate"], "BLOCKED")
        self.assertEqual(passed["gate"], "PASSED")

    def test_planned_reader_knowledge_is_reconciled_from_accepted_disclosure(self) -> None:
        planned = {
            "knowledge_boundaries": [
                {
                    "layer": "READER_KNOWLEDGE",
                    "subject_id": "reader",
                    "fact_id": "fact:traitor",
                    "status": "KNOWN",
                }
            ],
            "disclosures": [
                {
                    "disclosure_id": "disclosure:traitor",
                    "fact_id": "fact:traitor",
                    "audience": "READER",
                    "mode": "CONFIRM",
                }
            ],
        }
        mismatched = validate_deterministic_continuity(
            chapter=3,
            historical_state={},
            extraction={
                "reader_knowledge_changes": [
                    {"fact_id": "fact:traitor", "status": "HINTED"}
                ],
                "disclosure_events": [
                    {
                        "disclosure_id": "disclosure:traitor",
                        "fact_id": "fact:traitor",
                        "audience": "READER",
                        "disclosure_mode": "CONFIRM",
                    }
                ],
            },
            planned_execution=planned,
        )

        self.assertEqual(mismatched["gate"], "BLOCKED")
        self.assertIn(
            "PLANNED_READER_KNOWLEDGE_MISMATCH",
            {item["conflict_code"] for item in mismatched["violations"]},
        )

    def test_withheld_reader_boundary_requires_no_reader_state_mutation(self) -> None:
        report = validate_deterministic_continuity(
            chapter=3,
            historical_state={},
            extraction={"reader_knowledge_changes": [], "disclosure_events": []},
            planned_execution={
                "knowledge_boundaries": [
                    {
                        "layer": "READER_KNOWLEDGE",
                        "fact_id": "fact:traitor",
                        "status": "WITHHELD",
                    }
                ],
                "disclosures": [
                    {
                        "disclosure_id": "disclosure:traitor",
                        "fact_id": "fact:traitor",
                        "audience": "READER",
                        "mode": "WITHHOLD",
                    }
                ],
            },
        )

        self.assertEqual(report["gate"], "PASSED")


if __name__ == "__main__":
    unittest.main()


def test_creative_pronoun_contract_records_ambiguity_without_relabeling_it_passed():
    profiles=({'character_id':'lu','canonical_name':'陆圆','pronouns':['他']},
        {'character_id':'tuan','canonical_name':'团耳','pronouns':['它']})
    inputs=dict(chapter=1,historical_state={},extraction={},identity_profiles=profiles,
        revision_text='团耳抬起爪子。\n他把照料单转向团耳，指给它看。')
    legacy=validate_deterministic_continuity(**inputs)
    assert legacy['gate']=='BLOCKED'
    current=validate_deterministic_continuity(**inputs,validation_contract='grounded-canon-validation.v2')
    assert not current['violations']
    assert current['identity_reference_check_status']=='PARTIAL'
    assert current['identity_reference_observations'][0]['status']=='NOT_RUN'
    assert current['identity_reference_observations'][0]['review_required'] is True
    explicit=validate_deterministic_continuity(chapter=1,historical_state={},extraction={},
        identity_profiles=({'character_id':'lin','canonical_name':'林遥','pronouns':['她']},),
        revision_text='林遥蹲下。\n他拿起图纸。',validation_contract='grounded-canon-validation.v2')
    assert explicit['gate']=='BLOCKED'


def test_known_summary_plan_target_does_not_replace_typed_status_or_accepted_cas():
    from copy import deepcopy
    change={'character_id':'character:hero','fact_id':'fact:delivery','status':'KNOWN','summary':'亲眼核对当日到货'}
    plan={'required_state_transitions':[{'state_kind':'character_knowledge','entity_key':'character:hero:fact:delivery',
        'from_state':'尚未核对当日到货','to_state':'亲眼核对当日到货'}]}
    args=dict(chapter=1,historical_state={},extraction={'character_knowledge_changes':[change]},planned_execution=plan)
    assert any(v['conflict_code']=='PLANNED_STATE_TRANSITION_MISMATCH' for v in validate_deterministic_continuity(**args)['violations'])
    current=validate_deterministic_continuity(**args,validation_contract='grounded-canon-validation.v2')
    assert not any(v['conflict_code']=='PLANNED_STATE_TRANSITION_MISMATCH' for v in current['violations'])
    for field,value in [('status','UNKNOWN'),('summary','尚未核对当日到货'),('from_state','invented accepted state')]:
        changed=deepcopy(args)
        changed['extraction']['character_knowledge_changes'][0][field]=value
        report=validate_deterministic_continuity(**changed,validation_contract='grounded-canon-validation.v2')
        assert report['gate']=='BLOCKED'
