from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import PlanContractType
from novel_forge.modules.hierarchical_planning.realization_domain import (
    NarrativeRealizationContract,
    NarrativeRealizationLifecycle,
)


def _hash(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _contract() -> NarrativeRealizationContract:
    return NarrativeRealizationContract.from_mapping(
        {
            "schema_version": "narrative-realization-contract.v1",
            "realization_id": "realization:group-1:g1",
            "project_id": "project-1",
            "book_id": "book-1",
            "chapter_group_plan_version_id": "group-plan-v1",
            "chapter_group_content_hash": _hash("g"),
            "chapter_range": [1, 3],
            "foundation_set_digest": _hash("f"),
            "accepted_boundary": {
                "accepted_through_chapter": 0,
                "story_state_version_id": "story-state-v0",
                "story_state_content_hash": _hash("s"),
                "canon_version_id": "canon-v0",
                "canon_content_hash": _hash("c"),
            },
            "arc_working_set_digest": _hash("w"),
            "arc_plan_bindings": [
                {
                    "arc_id": "arc-main",
                    "asset_version_id": "arc-plan-v1",
                    "content_hash": _hash("a"),
                }
            ],
            "events": [
                {
                    "event_id": "event-discover",
                    "slice_id": "chapter-1",
                    "chapter_number": 1,
                    "causes": [],
                    "actor_ref": "character:mara",
                    "motivation": "Protect a threatened witness.",
                    "preconditions": ["Mara possesses the altered map."],
                    "knowledge_boundary": {
                        "actor_knows": ["the district is missing"],
                        "reader_may_learn": ["a witness delays erasure"],
                        "forbidden_disclosures": ["archive master key"],
                    },
                    "action": "Mara asks the witness to testify publicly.",
                    "decision": "She shares incomplete evidence.",
                    "resistance": "The witness fears exposure.",
                    "consequence": "The district remains accessible for seven days.",
                    "state_deltas": [
                        {
                            "state_kind": "character_belief",
                            "entity_id": "mara",
                            "from_state": "certainty protects witnesses",
                            "to_state": "shared uncertainty can protect witnesses",
                        }
                    ],
                    "disclosures": ["witness-delay rule"],
                    "obligation_actions": ["ADVANCE:promise-witness"],
                    "arc_contributions": ["arc-main:ADVANCE"],
                    "irreversible_change": "The witness becomes publicly known.",
                    "next_event_ids": ["event-pressure"],
                    "required": True,
                },
                {
                    "event_id": "event-pressure",
                    "slice_id": "chapter-2",
                    "chapter_number": 2,
                    "causes": ["event-discover"],
                    "actor_ref": "faction:archive",
                    "motivation": "Restore control of public memory.",
                    "preconditions": ["The witness is publicly known."],
                    "knowledge_boundary": {
                        "actor_knows": ["the witness identity"],
                        "reader_may_learn": ["the archive coerces witnesses"],
                        "forbidden_disclosures": ["archive master key"],
                    },
                    "action": "The archive freezes the witness's transit access.",
                    "decision": "Mara must choose rescue or evidence preservation.",
                    "resistance": "Saving either one weakens the other.",
                    "consequence": "Mara loses sole control of the investigation.",
                    "state_deltas": [
                        {
                            "state_kind": "resource_state",
                            "entity_id": "witness-access",
                            "from_state": "available",
                            "to_state": "frozen",
                        }
                    ],
                    "disclosures": ["archive transit leverage"],
                    "obligation_actions": ["ADVANCE:promise-witness"],
                    "arc_contributions": ["arc-main:ESCALATE"],
                    "irreversible_change": "The investigation becomes collective.",
                    "next_event_ids": ["event-choice"],
                    "required": True,
                },
                {
                    "event_id": "event-choice",
                    "slice_id": "chapter-3",
                    "chapter_number": 3,
                    "causes": ["event-pressure"],
                    "actor_ref": "character:mara",
                    "motivation": "Keep both witness and truth accountable.",
                    "preconditions": ["The archive has frozen witness access."],
                    "knowledge_boundary": {
                        "actor_knows": ["collective custody is possible"],
                        "reader_may_learn": ["Mara caused an earlier map failure"],
                        "forbidden_disclosures": ["archive master key"],
                    },
                    "action": "Mara gives the map to a public witness council.",
                    "decision": "She abandons solitary custody.",
                    "resistance": "The council demands her damaging prior map.",
                    "consequence": "The district gains collective protection at personal cost.",
                    "state_deltas": [
                        {
                            "state_kind": "relationship_state",
                            "entity_id": "mara:witness-council",
                            "from_state": "distrust",
                            "to_state": "accountable alliance",
                        }
                    ],
                    "disclosures": ["Mara's prior failure"],
                    "obligation_actions": ["RESOLVE:promise-witness"],
                    "arc_contributions": ["arc-main:TURN"],
                    "irreversible_change": "Map custody is now collective.",
                    "next_event_ids": [],
                    "required": True,
                },
            ],
            "proof": {
                "schema_version": "narrative-realization-proof.v1",
                "covered_event_ids": [
                    "event-discover",
                    "event-pressure",
                    "event-choice",
                ],
                "covered_parent_objectives": ["group-objective:public-witness"],
                "canon_state_legal": True,
                "character_motivation_legal": True,
                "world_rules_legal": True,
                "knowledge_boundaries_legal": True,
                "causal_escalation_proven": True,
                "state_transitions_covered": True,
                "obligations_covered": True,
                "arc_contributions_covered": True,
                "narrative_load_legal": True,
                "chapter_decomposition_legal": True,
                "semantic_evaluation_asset_version_id": "evaluation-v1",
                "semantic_evaluation_hash": _hash("e"),
            },
            "content_asset_version_id": "realization-content-v1",
            "content_hash": _hash("r"),
            "proof_asset_version_id": "realization-proof-v1",
            "proof_hash": _hash("p"),
            "lifecycle": "QUALIFIED",
        }
    )


def test_realization_is_not_a_plan_scale_or_accepted_actual() -> None:
    realization = _contract()

    assert {item.value for item in PlanContractType} == {
        "BOOK",
        "VOLUME",
        "ARC",
        "CHAPTER_GROUP",
        "CHAPTER",
    }
    assert realization.lifecycle is NarrativeRealizationLifecycle.QUALIFIED
    assert realization.event_ids == (
        "event-discover",
        "event-pressure",
        "event-choice",
    )
    assert realization.contract_digest.startswith("sha256:")


def test_realization_rejects_dangling_or_backward_causality() -> None:
    contract = _contract()
    values = contract.to_dict()
    values["events"][1]["causes"] = ["missing-event"]

    with pytest.raises(KernelError, match="REALIZATION_CAUSALITY_INVALID"):
        NarrativeRealizationContract.from_mapping(values)

    values = contract.to_dict()
    values["events"][0]["causes"] = ["event-choice"]
    with pytest.raises(KernelError, match="REALIZATION_CAUSALITY_INVALID"):
        NarrativeRealizationContract.from_mapping(values)


def test_realization_rejects_proof_or_slice_coverage_gaps() -> None:
    values = _contract().to_dict()
    values["proof"]["covered_event_ids"] = ["event-discover", "event-pressure"]
    with pytest.raises(KernelError, match="REALIZATION_PROOF_INCOMPLETE"):
        NarrativeRealizationContract.from_mapping(values)

    values = _contract().to_dict()
    values["events"][2]["chapter_number"] = 4
    with pytest.raises(KernelError, match="REALIZATION_SLICE_INVALID"):
        NarrativeRealizationContract.from_mapping(values)


def test_realization_lifecycle_never_implies_actual() -> None:
    realization = _contract()
    frozen = replace(
        realization,
        lifecycle=NarrativeRealizationLifecycle.FROZEN,
    )

    assert frozen.lifecycle is NarrativeRealizationLifecycle.FROZEN
    assert not hasattr(frozen, "accepted_actual")
