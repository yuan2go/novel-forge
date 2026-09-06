from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import (
    NarrativeRealityRevision,
    project_reality,
)
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind, StoryTime
from novel_forge.modules.worldbuilding.dynamics import (
    CausalRequirement,
    RequirementOperator,
    WorldTransition,
    candidate_transition,
)
from novel_forge.modules.hierarchical_planning.causal_domain import (
    CandidateFuture,
    DIRECTOR_DIMENSIONS,
    build_causal_plan,
)


def test_reality_requires_exact_outcome_and_sequential_parent():
    revision = NarrativeRealityRevision(
        "project",
        "book",
        "run",
        1,
        "accepted",
        "actual",
        "state",
        "canon",
        "projection",
        "sha256:" + "a" * 64,
    )
    assert (
        revision.revision_id != replace(revision, canon_version_id="other").revision_id
    )
    with pytest.raises(KernelError, match="sequential"):
        replace(revision, chapter_number=2)
    with pytest.raises(KernelError, match="exact accepted outcome"):
        project_reality(
            revision,
            {
                "project_id": "project",
                "book_id": "book",
                "accepted_through_chapter": 1,
                "based_on_chapter_outcome_asset_version_id": "unaccepted",
            },
            {},
        )


def reality_state():
    return {
        "project_id": "project",
        "book_id": "book",
        "book_run_id": "run",
        "chapter_number": 1,
        "revision_id": "reality:sha256:accepted",
        "world_clock": {"main": 10},
        "events": [
            {
                "story_time": {
                    "timeline_id": "main",
                    "start_ordinal": 10,
                    "end_ordinal": 10,
                    "precision": "EXACT",
                }
            }
        ],
        "current_state": {
            "character_state": [
                {
                    "entity_key": "hero",
                    "source_event_id": "event:hero",
                    "state": {
                        "character_id": "hero",
                        "life_status": "ALIVE",
                        "location_id": "home",
                        "max_travel_speed": 2,
                        "story_time": 10,
                    },
                }
            ],
            "character_knowledge": [
                {
                    "entity_key": "hero:supplies",
                    "source_event_id": "event:knowledge",
                    "state": {
                        "character_id": "hero",
                        "fact_id": "supply",
                        "status": "KNOWN",
                    },
                }
            ],
            "resource_state": [
                {
                    "entity_key": "supply",
                    "source_event_id": "event:supply",
                    "state": {"balance": 2},
                }
            ],
        },
    }


def transition():
    return WorldTransition(
        "departure",
        "hero",
        "OFF_CAMERA",
        StoryTime("main", 12, 12, "EXACT"),
        "prepare journey",
        NarrativeStateKind.RESOURCE_STATE,
        "supply",
        {"balance": 1},
        (
            CausalRequirement(
                "supplies",
                NarrativeStateKind.RESOURCE_STATE,
                "supply",
                "balance",
                RequirementOperator.AT_LEAST,
                3,
            ),
        ),
        ("event:supply",),
        (
            CausalRequirement(
                "actor-basis",
                NarrativeStateKind.CHARACTER_KNOWLEDGE,
                "hero:supplies",
                "status",
                RequirementOperator.EQUALS,
                "KNOWN",
            ),
        ),
    )


def test_causal_debt_cannot_be_discharged_by_candidate_changes():
    reality = reality_state()
    future = CandidateFuture(
        transition(),
        dict.fromkeys(DIRECTOR_DIMENSIONS, 0.8),
        ("hero",),
        ("supplies consumed",),
        (),
        (),
        (),
        "Travel prepares the confrontation",
    )
    plan = build_causal_plan(
        reality=reality,
        candidates=(future,),
        chapter_number=2,
        intent_revision_id="intent",
    )
    assert not plan["selected_candidate_id"]
    assert plan["causal_debts"][0]["status"] == "PREPARATION_REQUIRED"
    assert reality["current_state"]["resource_state"][0]["state"]["balance"] == 2
    reality["current_state"]["resource_state"][0]["state"]["balance"] = 3
    reality["revision_id"] = "reality:sha256:new-accepted"
    ready = build_causal_plan(
        reality=reality,
        candidates=(future,),
        chapter_number=2,
        intent_revision_id="intent",
    )
    assert ready["selected_candidate_id"]
    assert ready["causal_debts"][0]["status"] == "DISCHARGED_BY_ACCEPTED_REALITY"
    assert ready["causal_debts"][0]["discharge_evidence"] == "event:supply"


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"location_id": "city", "travel_distance": 10}, "WORLD_TRAVEL_IMPOSSIBLE"),
        ({"power_level": 9}, "WORLD_POWER_TRANSITION_FORBIDDEN"),
        ({"balance": -1}, "WORLD_QUANTITY_INVALID"),
    ],
)
def test_hard_world_rules_block_candidate_transition(changes, expected):
    candidate = replace(
        transition(),
        state_kind=NarrativeStateKind.CHARACTER_STATE,
        entity_key="hero",
        changes=changes,
    )
    with pytest.raises(KernelError) as error:
        candidate_transition(candidate, reality_state())
    assert error.value.code == expected


def test_dead_actor_and_epistemic_separation():
    reality = reality_state()
    reality["current_state"]["character_state"][0]["state"]["life_status"] = "DEAD"
    with pytest.raises(KernelError) as error:
        candidate_transition(transition(), reality)
    assert error.value.code == "WORLD_DEAD_ACTOR"
    with pytest.raises(KernelError) as error:
        replace(
            transition(),
            epistemic_basis=(
                CausalRequirement(
                    "secret",
                    NarrativeStateKind.READER_KNOWLEDGE,
                    "secret",
                    "status",
                    RequirementOperator.EQUALS,
                    "KNOWN",
                ),
            ),
        )
    assert error.value.code == "WORLD_EPISTEMIC_BASIS_INVALID"


def test_role_context_separates_actor_knowledge_and_fails_closed_on_required_budget():
    from novel_forge.modules.context_builder.reality_projection import (
        project_role_context,
    )

    reality = reality_state()
    reality["current_state"]["character_knowledge"] = [
        {
            "entity_key": "hero:secret",
            "source_event_id": "knows:hero",
            "state": {"character_id": "hero", "status": "KNOWN"},
        },
        {
            "entity_key": "villain:secret",
            "source_event_id": "knows:villain",
            "state": {"character_id": "villain", "status": "KNOWN"},
        },
    ]
    packet = project_role_context(
        reality=reality,
        role="DIALOGUE_WRITER",
        token_budget=1000,
        character_ids=("hero",),
    )
    assert {entry["state"]["character_id"] for entry in packet["selection"]} == {"hero"}
    assert any(item["reason"] == "ACTOR_SCOPE_DENIED" for item in packet["rejections"])
    with pytest.raises(KernelError) as error:
        project_role_context(
            reality=reality,
            role="DIALOGUE_WRITER",
            token_budget=1,
            character_ids=("hero",),
            required_event_ids=("knows:hero",),
        )
    assert error.value.code == "REALITY_CONTEXT_REQUIRED_SOURCE_UNAVAILABLE"


def test_world_observation_reconciles_into_existing_actual_event_contract():
    import json
    from dataclasses import asdict
    from novel_forge.modules.canon_graph.domain import (
        extract_canon_candidates,
        build_canon_update,
    )
    from novel_forge.modules.chapter_outcome.domain import (
        build_chapter_outcome,
        reduce_story_state,
    )

    observed = replace(
        transition(),
        state_kind=NarrativeStateKind.WORLD_STATE,
        entity_key="world_state_id=storm",
        changes={"status": "GATHERING"},
        requirements=(),
    )
    extraction = extract_canon_candidates(
        project_id="project",
        revision={"chapter": 1, "text": "The storm gathers while the council meets."},
        revision_asset_version_id="draft",
        context_bundle_version_id="context",
        provider_extraction={
            "world_state_changes": [
                {
                    "world_state_id": "storm",
                    "status": "GATHERING",
                    "summary": "Storm gathers off camera",
                    "evidence_start": 0,
                    "evidence_end": 17,
                    "confidence": 0.9,
                    "world_transition": {"payload_json": json.dumps(asdict(observed))},
                }
            ]
        },
    )
    patch = build_canon_update(
        project_id="project",
        revision_asset_version_id="draft",
        context_bundle_version_id="context",
        extraction=extraction,
        historical_state={
            "character_knowledge": reality_state()["current_state"][
                "character_knowledge"
            ],
            "resource_state": [
                {
                    "entity_key": "supply",
                    "source_event_id": "event:supply",
                    "state": {"balance": 2},
                }
            ],
        },
    )
    assert patch["gate"] == "PASSED"
    actual = build_chapter_outcome(
        project_id="project",
        book_id="book",
        chapter_number=1,
        chapter_plan_version_id="plan",
        parent_group_version_id="group",
        accepted_draft_version_id="draft",
        final_release_gate_version_id="release",
        quality_aggregate_version_id="quality",
        canon_patch_asset_version_id="patch",
        canon_patch=patch,
        cost_receipt_refs=(),
        created_by_operation_id="accept",
        trace_id="trace",
    )
    state = reduce_story_state(
        previous=None, chapter_outcome=actual, chapter_outcome_asset_version_id="actual"
    )
    world = state["current_state"]["world_state"][0]
    assert world["state"]["status"] == "GATHERING"
    event = next(e for e in actual["state_events"] if e["state_kind"] == "world_state")
    assert event["story_time"]["timeline_id"] == "main"
    assert event["causality"]["cause_refs"] == ["event:supply"]
    assert actual["authority"]["status"] == "PENDING_BOOK_ACCEPTANCE"


def test_compiled_hard_rule_is_executable_and_never_paid_by_director_score():
    reality = reality_state()
    reality["world_rule_constraints"] = [
        {
            "asset_version_id": "qualified-world:v1",
            "content_hash": "hash",
            "rule": {
                "rule_id": "minimum-supply",
                "category": "ecology_resources",
                "statement": "A reserve must remain.",
                "enforcement": "QUANTITATIVE",
                "applicability": ["resource_state"],
                "consequences": ["journey denied"],
                "predicate": {
                    "requirement_id": "reserve",
                    "state_kind": "resource_state",
                    "entity_key": "supply",
                    "field": "balance",
                    "operator": "AT_LEAST",
                    "value": 2,
                },
            },
        }
    ]
    with pytest.raises(KernelError) as error:
        candidate_transition(replace(transition(), requirements=()), reality)
    assert error.value.code == "WORLD_COMPILED_RULE_VIOLATION"


@pytest.mark.parametrize(
    "payload", [{}, {"state_kind": "invented"}, {"transition_id": 10}]
)
def test_untrusted_transition_shape_has_a_structured_domain_error(payload):
    with pytest.raises(KernelError) as error:
        WorldTransition.from_mapping(payload)
    assert error.value.code == "CAUSAL_CONTRACT_INVALID"


def test_intent_projection_routes_constraints_without_broadcasting_source_text():
    from novel_forge.modules.story_design_authority.intent import NarrativeIntent
    from novel_forge.modules.chapter_authority.provider_views import (
        _project_planning_content,
    )

    raw = {
        "source_text": "Make the city feel dangerous without killing the witness.",
        "goal": "Expose the conspiracy",
        "must_have": ["witness survives"],
        "must_not": ["witness death"],
        "tone": "unease",
        "pacing": "gradual escalation",
        "relationship_direction": "trust grows",
        "arc_constraint": "retain uncertainty",
        "theme_constraint": "public accountability",
        "ending_constraint": "archive becomes public",
        "allowed_deviation": "local scene order only",
    }
    intent = NarrativeIntent.from_mapping(raw)
    book = intent.route(target="BOOK")
    prose = intent.route(target="REALIZATION")
    assert "ending_constraint" in book["constraints"]
    assert "tone" not in book["constraints"]
    assert "tone" in prose["constraints"]
    assert "source_text" not in str(prose)
    provider, omitted, truncated = _project_planning_content(
        stage="book_plan.generate",
        role="creative_foundation",
        content={"candidate_payload": {"narrative_intent": raw}},
        chapter=1,
        selectors=frozenset(),
    )
    assert provider == book
    assert (omitted, truncated) == (0, 0)


def test_causal_obligation_closes_only_on_accepted_condition_and_exact_payoff():
    import json
    from novel_forge.modules.narrative_state import (
        events_from_canon_patch,
        reduce_story_state_v2,
    )

    predicate = {
        "requirement_id": "prepare",
        "state_kind": "resource_state",
        "entity_key": "entity_id=hero|resource_id=supply",
        "field": "balance",
        "operator": "AT_LEAST",
        "value": 3,
    }
    debt = {
        "obligation_id": "debt:journey",
        "obligation_type": "CAUSAL_DEBT",
        "status": "OPEN",
        "priority": "HIGH",
        "target_window": {"status": "SCHEDULED", "from_chapter": 2, "to_chapter": 4},
        "causal_requirement": {"payload_json": json.dumps(predicate)},
        "causal_plan_asset_version_id": "causal-plan:v1",
    }

    def apply(chapter, previous, changes):
        events = events_from_canon_patch(
            project_id="project",
            book_id="book",
            source_chapter=chapter,
            chapter_outcome_id=f"actual:{chapter}",
            canon_patch_asset_version_id=f"patch:{chapter}",
            accepted_draft_asset_version_id=f"draft:{chapter}",
            source_operation_id=f"operation:{chapter}",
            trace_id="causal-debt-test",
            canon_patch={"state_changes": changes},
        )
        return reduce_story_state_v2(
            previous=previous,
            events=events,
            chapter_outcome_asset_version_id=f"actual-version:{chapter}",
            chapter_outcome_id=f"actual:{chapter}",
        )

    initial = apply(
        1,
        None,
        {
            "resource_state": [
                {"entity_id": "hero", "resource_id": "supply", "balance": 2}
            ],
            "narrative_obligation": [debt],
        },
    )
    source_event = initial["current_state"]["resource_state"][0]["source_event_id"]
    close = {
        **debt,
        "from_status": "OPEN",
        "status": "FULFILLED",
        "payoff_evidence": {"asset_version_id": "draft:1", "event_id": source_event},
    }
    with pytest.raises(KernelError) as error:
        apply(2, initial, {"narrative_obligation": [close]})
    assert error.value.code == "CAUSAL_OBLIGATION_NOT_DISCHARGED"
    prepared = apply(
        2,
        initial,
        {
            "resource_state": [
                {"entity_id": "hero", "resource_id": "supply", "balance": 3}
            ]
        },
    )
    payoff = prepared["current_state"]["resource_state"][0]["source_event_id"]
    fulfilled = apply(
        3,
        prepared,
        {
            "narrative_obligation": [
                {
                    **close,
                    "payoff_evidence": {
                        "asset_version_id": "draft:2",
                        "event_id": payoff,
                    },
                }
            ]
        },
    )
    assert (
        fulfilled["current_state"]["narrative_obligation"][0]["state"]["status"]
        == "FULFILLED"
    )
    assert (
        initial["current_state"]["narrative_obligation"][0]["state"]["status"] == "OPEN"
    )


def test_structured_realization_scopes_specialists_and_preserves_slot_revisions():
    from novel_forge.modules.chapter_authority.realization_composition import (
        compile_realization_contract,
        integrate_realization,
        reconcile_revision_composition,
    )

    plan = {
        "source_chapter_plan_asset_version_id": "plan-v1",
        "source_chapter_plan_content_hash": "sha256:plan",
        "character_participation": [
            {"character_id": "hero", "known_fact_ids": ["public-record"]}
        ],
        "scene_plan": [
            {
                "scene_id": "interrogation",
                "participants": ["hero"],
                "beats": [{"beat_id": "question"}],
                "accessible_knowledge": ["public-record"],
                "realization_capabilities": ["SKELETON", "DIALOGUE", "INTEGRATION"],
            },
            {
                "scene_id": "escape",
                "participants": ["hero"],
                "beats": [{"beat_id": "flight"}],
                "accessible_knowledge": [],
                "realization_capabilities": ["SKELETON", "ACTION"],
            },
        ],
    }
    style = {
        "policies": [
            {
                "asset_version_id": "voice-v1",
                "structured_facts": [
                    {
                        "kind": "voice_contract",
                        "layer": "NARRATOR",
                        "voice_id": "restrained",
                        "forbidden_markers": ["as an AI"],
                        "required_markers": [],
                    }
                ],
            }
        ]
    }
    contract = compile_realization_contract(plan, style)
    slots = [
        {"slot_id": slot["slot_id"], "text": f"Prose {index}.", "used_fact_ids": []}
        for index, slot in enumerate(contract["slots"])
    ]

    def text(items):
        return "\n\n".join(item["text"] for item in items)

    accepted = integrate_realization(
        contract=contract, artifacts=slots, text=text(slots)
    )
    assert [slot["capability"] for slot in contract["slots"]] == [
        "SKELETON",
        "DIALOGUE",
        "INTEGRATION",
        "SKELETON",
        "ACTION",
    ]
    assert accepted["voice_evidence"][0]["status"] == "CONTRACT_MATCH"
    revised = [dict(slot) for slot in slots]
    revised[1]["text"] = '"The public record contradicts you."'
    revised[1]["used_fact_ids"] = ["public-record"]
    revision = reconcile_revision_composition(
        accepted, {"scene_artifacts": revised, "text": text(revised)}
    )
    assert revision["changed_slot_ids"] == ["interrogation:dialogue:hero"]
    assert revision["previous_composition_digest"] == accepted["composition_digest"]
    with pytest.raises(KernelError, match="INTEGRATION_DRIFT"):
        integrate_realization(
            contract=contract,
            artifacts=slots,
            text=text(slots) + " Unplanned factual change.",
        )
    revised[1]["used_fact_ids"] = ["reader-only-secret"]
    with pytest.raises(KernelError, match="EPISTEMIC_SCOPE_VIOLATION"):
        integrate_realization(contract=contract, artifacts=revised, text=text(revised))
    revised[1]["used_fact_ids"] = []
    revised[0]["text"] = "as an AI"
    with pytest.raises(KernelError, match="VOICE_DRIFT"):
        integrate_realization(contract=contract, artifacts=revised, text=text(revised))


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("AUTO", set()),
        ("REVIEW_MAJOR_DECISION", {"MAJOR_DECISION"}),
        ("REVIEW_PLAN", {"BOOK", "VOLUME", "ARC", "NEAR_TERM", "CHAPTER", "SCENE"}),
        ("REVIEW_CHAPTER", {"FINAL_CANDIDATE"}),
        ("REVIEW_REALITY_COMMIT", {"REALITY_COMMIT"}),
        ("MANUAL_DIRECTOR", {"DIRECTOR"}),
    ],
)
def test_editorial_modes_share_explicit_authority_boundaries(mode, expected):
    from novel_forge.modules.book_authority.control_policy import (
        ControlPolicy,
        CONTROL_BOUNDARIES,
    )

    policy = ControlPolicy(policy_version="operator-policy:v1", mode=mode)
    assert {
        boundary for boundary in CONTROL_BOUNDARIES if policy.requires(boundary)
    } == expected
    with pytest.raises(KernelError, match="Unknown editorial boundary"):
        policy.requires("WRITE_CANON")
    with pytest.raises(KernelError, match="declared mode"):
        ControlPolicy(mode="AGENT_APPROVES_ITSELF")


def test_scene_planning_cannot_promote_reader_fact_belief_or_suspicion_to_knowledge():
    from novel_forge.modules.hierarchical_planning.epistemic_validation import (
        validate_planned_character_knowledge,
    )
    from copy import deepcopy

    state = {
        "current_state": {
            "character_knowledge": [
                {
                    "state": {
                        "character_id": "hero",
                        "fact_id": "secret",
                        "status": "SUSPECTED",
                    }
                }
            ],
            "character_belief": [
                {
                    "state": {
                        "character_id": "hero",
                        "fact_id": "secret",
                        "stance": "BELIEVES",
                    }
                }
            ],
            "reader_knowledge": [
                {"state": {"fact_id": "secret", "status": "REVEALED"}}
            ],
        }
    }
    plan = {
        "character_participation": [
            {"character_id": "hero", "known_fact_ids": ["secret"]}
        ]
    }
    before = deepcopy(state)
    with pytest.raises(KernelError, match="ACCEPTED_KNOWLEDGE_MISMATCH"):
        validate_planned_character_knowledge(plan, state)
    assert state == before
    state["current_state"]["character_knowledge"][0]["state"]["status"] = "KNOWN"
    validate_planned_character_knowledge(plan, state)
    plan["character_participation"][0]["character_id"] = "rival"
    with pytest.raises(KernelError, match="ACCEPTED_KNOWLEDGE_MISMATCH"):
        validate_planned_character_knowledge(plan, state)


def test_narrative_flashforward_cannot_advance_the_physical_world_clock():
    reality = reality_state()
    reality["events"][0]["story_time"].update(start_ordinal=1000, end_ordinal=1000)
    candidate = candidate_transition(transition(), reality)
    assert candidate["transition"]["story_time"]["start_ordinal"] == 12
    assert candidate["eligible"] is False


def test_intent_compiler_preserves_source_and_routes_only_declared_constraints():
    from novel_forge.modules.story_design_authority.intent import (
        compile_narrative_intent,
    )

    source = "目标：让角色面对公开证据的代价\n必须：一场可信的关系冲突\n禁止：凭空复活\n基调：克制\n允许偏离：只调整场景顺序"
    intent = compile_narrative_intent(source)
    assert intent.source_text == source
    assert intent.must_not == ("凭空复活",)
    assert "tone" not in intent.route(target="BOOK")["constraints"]
    assert intent.route(target="REALIZATION")["constraints"]["tone"] == "克制"
    for invalid in (
        "Make the ending better",
        source + "\n目标：另一个目标",
        source.replace("允许偏离：只调整场景顺序", ""),
    ):
        with pytest.raises(KernelError):
            compile_narrative_intent(invalid)


def test_character_action_requires_own_epistemic_evidence():
    with pytest.raises(KernelError, match="WORLD_CHARACTER_DECISION_BASIS_REQUIRED"):
        candidate_transition(replace(transition(), epistemic_basis=()), reality_state())
    reality = reality_state()
    reality["current_state"]["character_knowledge"][0]["state"]["character_id"] = (
        "other"
    )
    with pytest.raises(KernelError, match="WORLD_EPISTEMIC_ACTOR_MISMATCH"):
        candidate_transition(transition(), reality)


def test_reader_information_and_why_projection_do_not_invent_objective_facts():
    from copy import deepcopy
    from novel_forge.modules.narrative_state.read_models import (
        project_reality_view,
        project_why_trace,
    )

    reality = reality_state()
    reality["outcome_version_id"] = "accepted-actual"
    reality["current_state"]["narrative_obligation"] = [
        {
            "entity_key": "obligation:mystery",
            "source_event_id": "accepted:question",
            "state": {"obligation_type": "MYSTERY", "status": "OPEN"},
        }
    ]
    reality["events"] = [
        {
            "event_id": "accepted:question",
            "causality": {"cause_refs": ["external:source"]},
        }
    ]
    original = deepcopy(reality)
    reader = project_reality_view(reality, view="reader")
    assert reader["reader_information_roles"]["questions"] == ["obligation:mystery"]
    assert "NOT_MEASURED_READER_RESPONSE" in reader["reader_information_proof_ceiling"]
    why = project_why_trace(reality, event_id="accepted:question")
    assert not why["complete_within_accepted_events"]
    assert why["external_evidence_refs"] == ["external:source"]
    assert reality == original


def test_published_text_beats_have_explicit_replay_adapter_but_v2_is_strict():
    from novel_forge.modules.chapter_authority.realization_composition import (
        compile_realization_contract,
    )

    plan = {"scene_plan": [{"scene_id": "scene", "beats": ["choice", "cost"]}]}
    contract = compile_realization_contract(plan, {})
    assert contract["plan_representation"] == "LEGACY_TEXT_BEATS_FROZEN_ADAPTATION"
    assert contract["slots"][0]["beat_ids"] == [
        "scene:legacy-beat:0",
        "scene:legacy-beat:1",
    ]
    assert compile_realization_contract(plan, {}) == contract
    plan["chapter_contract_schema_version"] = "chapter-mission-scene.v2"
    with pytest.raises(KernelError, match="REALIZATION_BEAT_CONTRACT_INVALID"):
        compile_realization_contract(plan, {})
