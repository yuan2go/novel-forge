import json
from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError


def binding():
    transition = {
        "transition_id": "council-moves",
        "actor_id": "faction:council",
        "camera": "OFF_CAMERA",
        "story_time": {
            "timeline_id": "main",
            "start_ordinal": 2,
            "end_ordinal": 2,
            "precision": "EXACT",
            "label": "",
        },
        "action": "Secret council mobilisation",
        "state_kind": "faction_state",
        "entity_key": "faction_id=council",
        "changes": {"status": "MOBILISED"},
        "requirements": [],
        "epistemic_basis": [],
        "cause_refs": ["foundation:world"],
    }
    return {
        "asset_version_id": "action",
        "content_hash": "sha256:" + "a" * 64,
        "action": {
            "contract_version": "world-production-action.v1",
            "source": {
                "asset_version_id": "source",
                "content_hash": "sha256:" + "b" * 64,
            },
            "generation": {"asset_version_id": "generation"},
            "evaluation": {"asset_version_id": "evaluation"},
            "world_plan": {
                "chapter_number": 1,
                "disposition": "ELIGIBLE",
                "selected_candidate_id": "future",
                "candidate_futures": [
                    {
                        "candidate_id": "future",
                        "eligible": True,
                        "transition": transition,
                    }
                ],
                "preparation_schedule": [],
            },
        },
    }


def extraction():
    return {
        "project_id": "project",
        "chapter": 1,
        "revision_asset_version_id": "draft",
        "faction_state_changes": [],
        "disclosure_events": [],
        "reader_knowledge_changes": [],
        "character_knowledge_changes": [],
        "approval_required_changes": [],
    }


def test_background_acceptance_proposal_has_no_fabricated_prose_or_knowledge():
    from novel_forge.modules.canon_graph.background import attach_background_proposals

    source = extraction()
    result = attach_background_proposals(extraction=source, binding=binding())
    event = result["faction_state_changes"][0]
    assert event["fact_origin"]["kind"] == "GOVERNED_BACKGROUND"
    assert event["fact_origin"]["action_asset_version_id"] == "action"
    assert "extraction_evidence" not in event
    assert event["visibility"] == "HIDDEN"
    assert source == extraction()
    assert (
        result["reader_knowledge_changes"]
        == result["character_knowledge_changes"]
        == []
    )


def test_observer_cannot_forge_background_acceptance_provenance():
    from novel_forge.modules.canon_graph.background import attach_background_proposals

    source = extraction()
    source["faction_state_changes"] = [{"fact_origin": {"kind": "GOVERNED_BACKGROUND"}}]
    with pytest.raises(KernelError, match="WORLD_FACT_ORIGIN_FORGED"):
        attach_background_proposals(extraction=source, binding=binding())


def test_background_acceptance_compares_all_frozen_content():
    from novel_forge.modules.canon_graph.background import (
        attach_background_proposals,
        require_background_payload,
    )
    from novel_forge.modules.narrative_state.contracts import events_from_canon_patch

    expected = attach_background_proposals(extraction=extraction(), binding=binding())[
        "faction_state_changes"
    ][0]
    event = events_from_canon_patch(
        project_id="project",
        book_id="book",
        source_chapter=1,
        chapter_outcome_id="outcome",
        canon_patch_asset_version_id="patch",
        accepted_draft_asset_version_id="draft",
        source_operation_id="op",
        trace_id="trace",
        canon_patch={
            "state_changes": {"faction_state": [{**expected, "entity_version": 1}]}
        },
    )[0]
    require_background_payload(expected=expected, actual=event.payload)
    for changed in (
        {**event.payload, "unapproved_secret": "forged"},
        {**event.payload, "status": "DESTROYED"},
    ):
        with pytest.raises(KernelError, match="WORLD_ACCEPTANCE_SOURCE_DRIFT"):
            require_background_payload(expected=expected, actual=changed)


def test_planning_and_writer_views_exclude_background_explanations_and_full_source():
    from novel_forge.modules.canon_graph.background import (
        public_world_direction,
        without_private_world,
    )

    value = binding()
    before = deepcopy(value)
    direction = public_world_direction(value)
    assert direction["on_camera_events"] == []
    assert "Secret council" not in str(direction)
    assert without_private_world(
        {"constraint_envelope": {"world_preparation": value}, "scene": "public inquiry"}
    ) == {"constraint_envelope": {}, "scene": "public inquiry"}
    assert value == before


def test_high_impact_background_requires_canon_approval_without_prose_span():
    from novel_forge.modules.canon_graph.background import attach_background_proposals
    from novel_forge.modules.canon_graph.approval_domain import (
        build_canon_change_proposal,
    )

    value = binding()
    value["action"]["world_plan"]["candidate_futures"][0]["transition"]["changes"][
        "impact_type"
    ] = "major_faction_ownership_change"
    result = attach_background_proposals(extraction=extraction(), binding=value)
    proposal = build_canon_change_proposal(
        project_id="project", extraction=result, extraction_asset_version_id="observed"
    )
    assert proposal["changes"][0]["approval_requirement"] == "REQUIRED"
    assert proposal["changes"][0]["evidence_span"] == {}
    assert proposal["changes"][0]["fact_origin"]["kind"] == "GOVERNED_BACKGROUND"


@pytest.mark.parametrize("origin_kind", ["GOVERNED_BACKGROUND", "GOVERNED_PREPARATION"])
def test_background_state_is_not_retrieved_by_entity_or_unknown_fact_selector(
    origin_kind,
):
    from novel_forge.modules.chapter_authority.provider_views import (
        project_narrative_state_facts,
    )

    fact = {
        "state_kind": "faction_state",
        "entity_key": "faction_id=council",
        "source_event_id": "accepted-secret",
        "state": {
            "visibility": "HIDDEN",
            "fact_origin": {"kind": origin_kind},
            "status": "MOBILISED",
        },
    }
    assert (
        project_narrative_state_facts(
            [fact],
            projection={
                "state_entity_refs": ["faction_id=council"],
                "fact_refs": ["accepted-secret"],
            },
            chapter=2,
        )
        == []
    )
    assert project_narrative_state_facts([fact], projection={}, chapter=2) == []
    disclosed = project_narrative_state_facts(
        [fact],
        projection={
            "authorized_disclosure_fact_refs": ["accepted-secret"],
            "fact_refs": ["accepted-secret"],
        },
        chapter=2,
    )
    assert disclosed[0]["state"]["status"] == fact["state"]["status"]
    assert "fact_origin" not in disclosed[0]["state"]


def test_planning_previous_outcome_cannot_bypass_private_state_projection():
    from novel_forge.modules.chapter_authority.provider_views import (
        _project_planning_content,
    )

    private = {
        "mutation": {
            "payload": {
                "fact_origin": {"kind": "GOVERNED_PREPARATION"},
                "preparation_schedule": "secret council mobilisation",
            }
        }
    }
    source = {
        "chapter_number": 1,
        "state_events": [private],
        "obligation_events": [private],
        "arc_evidence": [],
    }
    view, _, _ = _project_planning_content(
        stage="chapter_plan.generate",
        role="previous_chapter_outcome",
        content=source,
        chapter=2,
        selectors=frozenset(),
    )
    assert "secret council mobilisation" not in str(view)
    assert view["chapter_number"] == 1


def test_character_selector_does_not_expand_writer_epistemic_permission():
    from novel_forge.modules.chapter_authority.provider_views import (
        project_narrative_state_facts,
    )

    fact = {
        "state_kind": "character_knowledge",
        "entity_key": "character_id=hero|fact_id=private-message",
        "state": {
            "character_id": "hero",
            "fact_id": "private-message",
            "status": "KNOWN",
        },
    }
    projection = {
        "contract_version": "chapter-task-narrative-projection-v1",
        "character_ids": ["hero"],
        "authorized_epistemic_fact_refs": [],
    }
    assert project_narrative_state_facts([fact], projection=projection, chapter=2) == []
    projection["authorized_epistemic_fact_refs"] = ["private-message"]
    assert project_narrative_state_facts([fact], projection=projection, chapter=2) == [
        fact
    ]


def test_retrieved_state_summary_cannot_restore_filtered_secrets():
    from novel_forge.modules.chapter_authority.provider_views import (
        project_retrieved_state_context,
    )

    source = {
        "safe_summary": "secret council mobilisation",
        "structured_facts": [
            {
                "state_kind": "character_knowledge",
                "entity_key": "character_id=hero|fact_id=private",
                "state": {
                    "character_id": "hero",
                    "fact_id": "private",
                    "status": "KNOWN",
                },
            }
        ],
    }
    projected = project_retrieved_state_context(
        source,
        projection={
            "contract_version": "chapter-task-narrative-projection-v1",
            "character_ids": ["hero"],
            "authorized_epistemic_fact_refs": [],
        },
        chapter=2,
    )
    assert projected["structured_facts"] == []
    assert "secret council" not in projected["safe_summary"]
    assert source["safe_summary"] == "secret council mobilisation"


def test_on_camera_direction_cannot_leak_private_causal_explanation():
    from novel_forge.modules.canon_graph.background import public_world_direction

    source = binding()
    transition = source["action"]["world_plan"]["candidate_futures"][0]["transition"]
    transition.update(
        camera="ON_CAMERA",
        action="The courier moves because the secret council ordered a coup",
        epistemic_basis=[{"value": "secret council ordered a coup"}],
        cause_refs=["private-secret-event"],
    )
    projected = public_world_direction(source)
    assert "secret council" not in str(projected)
    assert "private-secret-event" not in str(projected)
    assert projected["on_camera_events"][0]["changes"] == transition["changes"]


def test_reader_view_does_not_expose_unrevealed_world_preparation():
    from novel_forge.modules.narrative_state.read_models import project_reality_view

    reality = {
        "revision_id": "revision",
        "outcome_version_id": "accepted",
        "current_state": {
            "narrative_obligation": [
                {
                    "entity_key": "obligation_id=secret",
                    "source_event_id": "secret",
                    "state": {
                        "obligation_id": "secret",
                        "obligation_type": "CAUSAL_DEBT",
                        "reader_visibility": "HIDDEN",
                        "fact_origin": {"kind": "GOVERNED_PREPARATION"},
                        "preparation_schedule": "secret council mobilisation",
                    },
                }
            ]
        },
    }
    assert project_reality_view(reality, view="reader")["entries"] == []
    assert len(project_reality_view(reality, view="obligations")["entries"]) == 1


def test_targeted_disclosure_exposes_the_fact_without_other_private_causes():
    from novel_forge.modules.chapter_authority.provider_views import (
        project_narrative_state_facts,
    )

    fact = {
        "state_kind": "faction_state",
        "entity_key": "faction_id=council",
        "source_event_id": "accepted-notice",
        "state": {
            "status": "MOBILISED",
            "visibility": "HIDDEN",
            "fact_origin": {"kind": "GOVERNED_BACKGROUND", "source": "secret-decision"},
            "world_transition": {"payload_json": '{"action":"private-cause-marker"}'},
            "causality": {"cause_refs": ["another-secret-event"]},
        },
    }
    projected = project_narrative_state_facts(
        [fact],
        projection={
            "authorized_disclosure_fact_refs": ["accepted-notice"],
            "fact_refs": ["accepted-notice"],
        },
        chapter=2,
    )
    assert len(projected) == 1 and projected[0]["state"]["status"] == "MOBILISED"
    assert "private-cause-marker" not in str(projected)
    assert "another-secret-event" not in str(projected)
    assert "secret-decision" not in str(projected)


def test_partial_disclosure_cannot_expand_to_full_hidden_state_in_provider_context():
    from novel_forge.modules.chapter_authority.provider_views import (
        project_narrative_state_facts,
    )

    facts = [
        {
            "state_kind": "world_state",
            "entity_key": "world_state_id=decree",
            "source_event_id": "accepted:decree",
            "state": {
                "status": "ISSUED",
                "secret": "hidden successor",
                "fact_origin": {"kind": "GOVERNED_BACKGROUND"},
            },
        }
    ]
    projected = project_narrative_state_facts(
        facts,
        projection={
            "authorized_disclosure_fact_refs": ["accepted:decree"],
            "disclosure_field_projections": {
                "accepted:decree": {"state": {"status": "ISSUED"}}
            },
        },
        chapter=3,
    )
    assert projected[0]["state"] == {"status": "ISSUED"}
    assert facts[0]["state"]["secret"] == "hidden successor"


def test_observed_on_camera_preparation_gets_exact_scope_only_after_matching():
    from novel_forge.modules.canon_graph.background import attach_background_proposals

    frozen = binding()
    frozen["action"]["contract_version"] = "world-production-action.v2"
    frozen["action"]["world_plan"].update(
        selected_path_id="path:selected", causal_debts=[]
    )
    frozen["frozen_source"] = {"reality": {"current_state": {}}}
    transition = frozen["action"]["world_plan"]["candidate_futures"][0]["transition"]
    transition["camera"] = "ON_CAMERA"
    source = extraction()
    source["faction_state_changes"] = [
        {
            "faction_id": "council",
            "status": "MOBILISED",
            "causal_batch": {
                "contract_version": "causal-batch-event.v1",
                "local_id": "council-moves",
                "depends_on": ["foundation:world"],
            },
            "extraction_evidence": {"start": 4, "end": 18},
            "world_transition": {
                "payload_json": json.dumps(
                    {
                        **transition,
                        "action": "The council actually mustered in the observed scene.",
                    }
                )
            },
        }
    ]
    result = attach_background_proposals(extraction=source, binding=frozen)
    observed = result["faction_state_changes"][0]
    assert observed["preparation_lineage"] == {
        "contract_version": "world-preparation-lineage.v1",
        "origin_action_version_id": "action",
        "path_id": "path:selected",
        "transition_id": "council-moves",
    }
    assert "fact_origin" not in observed
    assert (
        json.loads(observed["world_transition"]["payload_json"])["action"]
        == "The council actually mustered in the observed scene."
    )
    assert (
        observed["extraction_evidence"]
        == source["faction_state_changes"][0]["extraction_evidence"]
    )
    assert (
        attach_background_proposals(extraction=extraction(), binding=frozen)[
            "faction_state_changes"
        ]
        == []
    )
    source["faction_state_changes"][0]["status"] = "DISBANDED"
    with pytest.raises(KernelError, match="WORLD_PREPARATION_OBSERVED_EFFECT_MISMATCH"):
        attach_background_proposals(extraction=source, binding=frozen)


def test_scene_epistemic_projection_preserves_each_scene_without_global_union():
    from novel_forge.modules.chapter_authority.provider_views import (
        build_task_narrative_projection,
        project_narrative_state_facts,
    )

    plan = {
        "chapter": 3,
        "scene_plan": [
            {
                "scene_id": "A",
                "pov_character_id": "alice",
                "participants": ["alice"],
                "focalization": "LIMITED",
                "accessible_knowledge": ["fact:a"],
            },
            {
                "scene_id": "B",
                "pov_character_id": "bob",
                "participants": ["bob"],
                "focalization": "LIMITED",
                "accessible_knowledge": ["fact:b"],
            },
        ],
        "character_participation": [
            {"character_id": "alice", "known_fact_ids": ["fact:a"]},
            {"character_id": "bob", "known_fact_ids": ["fact:b"]},
        ],
        "constraint_envelope": {
            "world_preparation": {
                "action": {
                    "contract_version": "world-production-action.v2",
                    "world_plan": {},
                }
            }
        },
    }
    facts = [
        {
            "state_kind": "character_knowledge",
            "entity_key": f"character_id={actor}|fact_id=fact:{suffix}",
            "source_event_id": f"accepted:{suffix}",
            "state": {
                "character_id": actor,
                "fact_id": f"fact:{suffix}",
                "status": "KNOWN",
                "summary": f"Only {actor} knows this.",
            },
        }
        for actor, suffix in [("alice", "a"), ("bob", "b")]
    ]
    projection = build_task_narrative_projection(plan)
    result = project_narrative_state_facts(facts, projection=projection, chapter=3)
    assert len(result) == 2
    assert result[0]["presentation_scope"] == {
        "scene_ids": ["A"],
        "character_id": "alice",
    }
    assert result[1]["presentation_scope"] == {
        "scene_ids": ["B"],
        "character_id": "bob",
    }
    assert projection["authorized_epistemic_fact_refs"] == []
    facts[1]["state"]["character_id"] = "alice"
    assert (
        len(project_narrative_state_facts(facts, projection=projection, chapter=3)) == 1
    )


@pytest.mark.parametrize(
    "assignment", [[], ["unknown"], ["council-moves", "council-moves"]]
)
def test_world_scene_owner_rejects_missing_unknown_or_duplicate_assignment(assignment):
    from novel_forge.modules.canon_graph.background import bind_world_execution

    frozen = binding()
    frozen["action"]["world_plan"]["candidate_futures"][0]["transition"]["camera"] = (
        "ON_CAMERA"
    )
    with pytest.raises(KernelError, match="WORLD_SCENE_EVENT"):
        bind_world_execution(
            frozen, [{"scene_id": "scene:1", "world_event_ids": assignment}]
        )
    result = bind_world_execution(
        frozen, [{"scene_id": "scene:1", "world_event_ids": ["council-moves"]}]
    )
    assert result["on_camera_events"][0]["scene_id"] == "scene:1"
    assert result["on_camera_events"][0]["cause_refs"] == ["foundation:world"]
    assert "private causal" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["actor", "absent"])
def test_on_camera_reconciliation_cannot_replace_missing_or_different_observed_cause(
    fault,
):
    from novel_forge.modules.canon_graph.background import attach_background_proposals

    frozen = binding()
    frozen["action"]["contract_version"] = "world-production-action.v2"
    frozen["action"]["world_plan"].update(selected_path_id="selected", causal_debts=[])
    frozen["frozen_source"] = {"reality": {"current_state": {}}}
    raw = frozen["action"]["world_plan"]["candidate_futures"][0]["transition"]
    raw["camera"] = "ON_CAMERA"
    actual = {
        "faction_id": "council",
        "status": "MOBILISED",
        "causal_batch": {
            "contract_version": "causal-batch-event.v1",
            "local_id": "council-moves",
            "depends_on": ["foundation:world"],
        },
    }
    if fault == "actor":
        actual["world_transition"] = {
            "payload_json": json.dumps(
                {
                    **raw,
                    "actor_id": "different-actor",
                    "action": "A different actor caused the observed effect.",
                }
            )
        }
    result = extraction()
    result["faction_state_changes"] = [actual]
    with pytest.raises(KernelError, match="WORLD_PREPARATION_OBSERVATION"):
        attach_background_proposals(extraction=result, binding=frozen)


def test_observed_preparation_hides_validation_metadata_from_writer_projection():
    from novel_forge.modules.narrative_state.information import (
        disclosed_fact_projection,
    )

    projected = disclosed_fact_projection(
        {
            "source_event_id": "accepted:visible",
            "state": {
                "status": "OBSERVED",
                "preparation_lineage": {"origin_action_version_id": "a"},
                "world_transition": {"payload_json": "PRIVATE_VALIDATION_PREDICATE"},
            },
        }
    )
    assert projected["state"] == {"status": "OBSERVED"}


def test_observed_transition_resolves_optional_epistemic_default_without_key_error():
    from novel_forge.modules.canon_graph.background import require_observed_transition

    raw = binding()["action"]["world_plan"]["candidate_futures"][0]["transition"]
    raw["epistemic_basis"] = []
    observed = {key: value for key, value in raw.items() if key != "epistemic_basis"}
    result = require_observed_transition(
        expected=raw, actual={"payload_json": json.dumps(observed)}
    )
    assert json.loads(result["payload_json"]) == observed
