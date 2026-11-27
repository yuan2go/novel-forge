from __future__ import annotations

from dataclasses import replace
from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import PlanContractType
from novel_forge.modules.hierarchical_planning.realization_domain import (
    NarrativeRealizationContract,
    NarrativeRealizationLifecycle,
)
from novel_forge.modules.hierarchical_planning.realization_application import (
    _realization_proof_decisions,
)
from novel_forge.storage.narrative_realization_repositories import (
    _realization_event_deviations,
)


def test_semantic_realization_preserves_paraphrase_and_exact_prose_identity():
    from novel_forge.modules.canon_graph.realization_comparison import comparison_input, validate_comparisons

    planned = _contract().events[0].to_dict() if hasattr(_contract().events[0], "to_dict") else dict(_contract().events[0])
    observed = {"planned_event_id": planned["event_id"], "grounded_claim_id": "claim:observed",
                "observation_status": "OBSERVED", "evidence_quote": "She handed the map to the council.",
                "observed_action": "A different description", "observed_cause_event_ids": ["same-chapter-perception"]}
    text = "She handed the map to the council."
    inputs = comparison_input(planned={"events": [planned]}, extraction={"realization_evidence": [observed]}, text=text)
    result = {"realization_comparisons": [{"planned_event_id": planned["event_id"], "causality": "EQUIVALENT",
        "required_state": "EQUIVALENT", "knowledge_boundary": "EQUIVALENT", "reason": "Intent is preserved.",
        "evidence_quotes": [text]}]}
    comparison = validate_comparisons(inputs=inputs, result=result, revision_asset_version_id="adopted:v1", text=text)[0]
    comparison["support_operation_id"] = "support:exact"
    observed["semantic_comparison"] = comparison
    assert _realization_event_deviations(planned, observed) == ()
    comparison["judgments"]["knowledge_boundary"] = "DEVIATED"
    assert _realization_event_deviations(planned, observed) == ("KNOWLEDGE_BOUNDARY_DRIFT",)
    comparison["judgments"]["knowledge_boundary"] = "UNCERTAIN"
    assert _realization_event_deviations(planned, observed) == ("REALIZATION_COMPARISON_UNCERTAIN",)
    planned["action"] = "Changed authorized intent"
    with pytest.raises(KernelError, match="REALIZATION_COMPARISON_SOURCE_INVALID"):
        _realization_event_deviations(planned, observed)


def test_realization_comparison_rejects_unobserved_quote_and_future_event():
    from novel_forge.modules.canon_graph.realization_comparison import comparison_input, validate_comparisons

    with pytest.raises(KernelError, match="CANON_REALIZATION_EVIDENCE_INVALID"):
        comparison_input(planned={"events": []}, extraction={"realization_evidence": [{
            "planned_event_id": "future", "observation_status": "OBSERVED"}]}, text="Only accepted candidate")
    inputs = {"events": [{"planned_event_id": "one", "planned_event_hash": _hash("p"), "observed_claim_id": "claim"}],
              "evidence_quotes": ["Only accepted candidate"]}
    with pytest.raises(KernelError, match="REALIZATION_COMPARISON_EVIDENCE_INVALID"):
        validate_comparisons(inputs=inputs, result={"realization_comparisons": [{"planned_event_id": "one",
            "causality": "EQUIVALENT", "required_state": "EQUIVALENT", "knowledge_boundary": "EQUIVALENT",
            "reason": "Unsupported", "evidence_quotes": ["A fabricated improvement"]}]},
            revision_asset_version_id="exact:v1", text="Only accepted candidate")


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
                        "reader_may_learn": ["witness-delay rule"],
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
                        "reader_may_learn": ["archive transit leverage"],
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
                        "reader_may_learn": ["Mara's prior failure"],
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


def _extended_contract(chapters: int) -> NarrativeRealizationContract:
    values = _contract().to_dict()
    values["chapter_range"] = [1, chapters]
    event = values["events"][0]
    values["events"] = [
        {
            **deepcopy(event),
            "event_id": f"event-{number}",
            "slice_id": f"chapter-{number}",
            "chapter_number": number,
            "causes": [f"event-{number - 1}"] if number > 1 else [],
            "next_event_ids": [f"event-{number + 1}"] if number < chapters else [],
        }
        for number in range(1, chapters + 1)
    ]
    values["proof"]["covered_event_ids"] = [
        event["event_id"] for event in values["events"]
    ]
    return NarrativeRealizationContract.from_mapping(values)


@pytest.mark.parametrize("chapters", [1, 2, 9, 12])
def test_realization_length_is_not_a_narrative_invariant(chapters: int) -> None:
    contract = _extended_contract(chapters)
    assert len(contract.events) == chapters
    assert contract.chapter_range == (1, chapters)
    values = contract.to_dict()
    values["events"].pop()
    with pytest.raises(KernelError):
        NarrativeRealizationContract.from_mapping(values)


def test_realization_rejects_dangling_or_backward_causality() -> None:
    contract = _contract()
    values = contract.to_dict()
    values["events"][1]["causes"] = ["missing-event"]

    with pytest.raises(KernelError, match="event=event-pressure, cause=missing-event"):
        NarrativeRealizationContract.from_mapping(values)

    values = contract.to_dict()
    values["events"][0]["causes"] = ["event-choice"]
    with pytest.raises(KernelError, match="event=event-discover, cause=event-choice"):
        NarrativeRealizationContract.from_mapping(values)

    values = contract.to_dict()
    values["events"][0]["next_event_ids"] = []
    with pytest.raises(KernelError, match="event=event-pressure lists cause=event-discover"):
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

    values = _contract().to_dict()
    values["events"][0]["disclosures"] = ["archive master key"]
    with pytest.raises(KernelError, match="REALIZATION_KNOWLEDGE_BOUNDARY_INVALID"):
        NarrativeRealizationContract.from_mapping(values)


def test_realization_lifecycle_never_implies_actual() -> None:
    realization = _contract()
    frozen = replace(
        realization,
        lifecycle=NarrativeRealizationLifecycle.FROZEN,
    )

    assert frozen.lifecycle is NarrativeRealizationLifecycle.FROZEN
    assert not hasattr(frozen, "accepted_actual")


def test_realization_proof_requires_independent_criterion_evidence() -> None:
    criteria = [
        {
            "criterion": criterion,
            "verdict": "PASS",
            "rationale": f"independent evidence for {criterion}",
            "evidence_refs": [f"evidence:{criterion.lower()}"],
        }
        for criterion in (
            "CANON_STATE_LEGAL",
            "CHARACTER_MOTIVATION_LEGAL",
            "WORLD_RULES_LEGAL",
            "KNOWLEDGE_BOUNDARIES_LEGAL",
            "CAUSAL_ESCALATION",
            "STATE_TRANSITION_COVERAGE",
            "OBLIGATION_LIFECYCLE",
            "ARC_CONTRIBUTION_COVERAGE",
            "NARRATIVE_LOAD_LEGAL",
            "CHAPTER_DECOMPOSITION_LEGAL",
        )
    ]

    decisions = _realization_proof_decisions({"criteria": criteria})

    assert len(decisions) == 10
    assert all(decisions.values())
    criteria[4]["verdict"] = "FAIL"
    with pytest.raises(KernelError, match="REALIZATION_PROOF_FAILED"):
        _realization_proof_decisions({"criteria": criteria})


def test_accepted_realization_evidence_detects_material_causal_drift() -> None:
    planned = _contract().to_dict()["events"][0]
    exact = {
        "observed_action": planned["action"],
        "observed_decision": planned["decision"],
        "observed_consequence": planned["consequence"],
        "observed_cause_event_ids": planned["causes"],
        "observed_disclosures": planned["disclosures"],
        "observed_state_deltas": planned["state_deltas"],
        "observed_state_event_ids": [
            item["entity_id"] for item in planned["state_deltas"]
        ],
    }

    assert _realization_event_deviations(planned, exact) == ()

    drifted = {
        **exact,
        "observed_action": "Mara hides the map and leaves.",
        "observed_disclosures": ["archive master key"],
        "observed_state_deltas": [
            {**planned["state_deltas"][0], "to_state": "solitary certainty"}
        ],
    }
    assert set(_realization_event_deviations(planned, drifted)) == {
        "CAUSALITY_DRIFT",
        "KNOWLEDGE_BOUNDARY_DRIFT",
        "STATE_DELTA_DRIFT",
    }
