from copy import deepcopy
from dataclasses import asdict

import pytest

from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy, world_target_chapter
from tests.unit.test_working_prose_projection import snapshot, rehash
from tests.unit.test_world_initial_agency import genesis


def world_source():
    working = snapshot()
    return {"contract_version": "world-preparation-source.v5", "target_chapter": 5,
        "request": {"book_run_id": working["book_run_id"], "accepted_through_chapter": 0},
        "working_manuscript": working,
        "reality": {**genesis(), "project_id": "p", "book_id": "b",
            "disclosure_fields_contract": "world-disclosure-fields.v2"},
        "policy": asdict(WorldProductionPolicy()), "intent": {}, "world_foundation": {},
        "character_definitions": [], "planning_window": [], "entity_ids": genesis()["approved_entity_ids"]}


@pytest.mark.parametrize("role,stage", [("WORLD_REASONER", "world_candidates.generate"), ("DIRECTOR", "world_candidates.evaluate")])
def test_world_and_director_consume_selected_experience_without_granting_accepted_knowledge(role, stage):
    source = world_source()
    frozen = deepcopy(source)
    task = PlanningWorldPreparation._task(source, {"asset_version_id": "source", "content_hash": "digest"}, role)
    delivered = build_provider_task_view(stage, {"world_preparation": task})["world_preparation"]
    assert delivered["contract_version"] == "world-provider-task.v4"
    assert delivered["target_chapter"] == 5 and delivered["accepted_through_chapter"] == 0
    assert delivered["working_manuscript"] == source["working_manuscript"]
    assert delivered["working_manuscript"]["sources"][-1]["omitted_ranges"] == []
    assert delivered["working_manuscript"]["structured_facts"] == []
    assert all(row["character_knowledge"] == "NOT_VERIFIED" for row in delivered["working_manuscript"]["sources"])
    assert delivered["context_projection"]["selection"] == []
    assert source == frozen


@pytest.mark.parametrize("mutation", ["target", "book", "accepted", "missing-predecessor", "changed-passage"])
def test_world_continuation_rejects_wrong_frontier_or_unbound_selected_prose(mutation):
    source = world_source()
    if mutation == "target":
        source["target_chapter"] = 4
    elif mutation == "book":
        source["request"]["book_run_id"] = "another-run"
    elif mutation == "accepted":
        source["request"]["accepted_through_chapter"] = 1
    elif mutation == "missing-predecessor":
        source["working_manuscript"]["sources"].pop()
        rehash(source["working_manuscript"])
    else:
        source["working_manuscript"]["sources"][-1]["passages"][0]["text"] = "A different experience."
        rehash(source["working_manuscript"])
    with pytest.raises(KernelError):
        world_target_chapter(source)


def test_frozen_accepted_only_source_does_not_acquire_working_history_or_new_chapter():
    source = world_source()
    source["contract_version"] = "world-preparation-source.v4"
    assert world_target_chapter(source) == 1
    task = PlanningWorldPreparation._task(source, {"asset_version_id": "old", "content_hash": "digest"}, "DIRECTOR")
    assert task["contract_version"] == "world-provider-task.v3"
    assert "working_manuscript" not in task and "target_chapter" not in task


def test_native_working_generation_task_and_serialized_schema_share_the_scoped_transition_contract():
    import json
    from novel_forge.modules.worldbuilding.production_schema import world_transition_schema
    source = world_source()
    stage = PlanningWorldPreparation.generation_stage(source,
        {"asset_version_id": "source", "content_hash": "digest"}, {})
    serialized = stage.output_schema["properties"]["candidates"]["items"]["properties"]["transition"]["properties"]["payload_json"]["description"]
    schema = json.loads(serialized.removeprefix("JSON serialization of this typed contract: "))
    assert stage.output_schema_ref == "schema:world_candidates.generate:v4"
    assert schema == stage.task["transition_contract"]["payload_schema"] == stage.task["transition_contract"]["schema"]
    assert schema == world_transition_schema(agency=True, working_observations=True)
    legacy = deepcopy(source)
    legacy["contract_version"] = "world-preparation-source.v4"
    frozen = PlanningWorldPreparation.generation_stage(legacy, {"asset_version_id": "old", "content_hash": "digest"}, {})
    assert frozen.output_schema_ref == "schema:world_candidates.generate:v3"
    assert frozen.task["transition_contract"]["schema"] == world_transition_schema(agency=True)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("narrative_intent", [False, True])
@pytest.mark.parametrize("role", ["generation", "evaluation"])
def test_native_world_output_validator_accepts_scoped_versions_and_enforces_the_frozen_schema(legacy, narrative_intent, role):
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_native_world_schema_fragment
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema

    source = world_source()
    if legacy:
        source["contract_version"] = "world-preparation-source.v4"
    source_ref = {"asset_version_id": "source", "content_hash": "digest"}
    output = {"disposition": "NO_OP", "reason": "The quiet scene requires no proposed World transition.", "candidates": []}
    stage = PlanningWorldPreparation.generation_stage(source, source_ref, {})
    if role == "evaluation":
        stage = PlanningWorldPreparation.evaluation_stage(source, source_ref,
            {"source": source_ref, "output": output}, {"asset_version_id": "generation", "content_hash": "generation-digest"}, {})
        output = {"evaluations": [], "action_classifications": []}
    schema = stage.output_schema
    ref = stage.output_schema_ref
    if narrative_intent:
        schema = bind_narrative_intent_schema(schema)
        ref += ":narrative-intent-v1"
    assert validate_native_world_schema_fragment(stage.name, schema, output, output_schema_ref=ref) == output
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_native_world_schema_fragment(stage.name, schema, {**output, "invented": True}, output_schema_ref=ref)
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED"):
        validate_native_world_schema_fragment(stage.name, schema, output, output_schema_ref=ref.replace(":v3", ":v99").replace(":v4", ":v99"))


def working_epistemic_source():
    from novel_forge.modules.book_authority.working_prose import project_working_sources, working_instruction
    from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage, compile_working_memory, normalize_observations
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    from novel_forge.modules.worldbuilding.working_state import project_working_observation_context
    from tests.unit.test_working_memory import policy, source

    text = "Reader believed the gate was safe.\n\nKeeper heard the warning bell.\n\nOnly the reader saw the broken hinge."
    raw = [{"kind": "KNOWLEDGE", "subject": "Reader", "state_key": "gate", "claim": "The gate is safe.",
        "perspective": "BELIEF", "knowledge_owner": "Reader", "quote": "Reader believed the gate was safe.", "causes": []},
        {"kind": "KNOWLEDGE", "subject": "Keeper", "state_key": "warning", "claim": "The warning bell rang.",
        "perspective": "OBSERVED", "knowledge_owner": "Keeper", "quote": "Keeper heard the warning bell.", "causes": []},
        {"kind": "EVENT", "subject": "gate", "state_key": "hinge", "claim": "The hinge is broken.",
        "perspective": "READER_ONLY", "knowledge_owner": "", "quote": "Only the reader saw the broken hinge.", "causes": []}]
    originals = [source(1, text, normalize_observations(raw, text))]
    packet = compile_working_memory(originals, queries=[], max_characters=5000)
    rows = project_working_sources(originals, target_chapter=2, policy=policy(), memory=packet)
    working = {"version": "working-manuscript-context.v1", "book_run_id": "run", "project_id": "project:agency", "book_id": "book:agency",
        "target_chapter": 2, "accepted_through_chapter": 0, "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [],
        "projection_policy": policy(), "sources": rows, "working_memory": bind_packet_coverage(packet, rows),
        "instruction": working_instruction(policy())}
    working["snapshot_hash"] = canonical_hash(working)
    reality = genesis()
    projected = project_working_observation_context(reality=reality, working=working, characters=[
        {"character_id": "character:reader", "name": "Reader"}, {"character_id": "character:keeper", "name": "Keeper"}])
    return projected


def test_working_belief_and_acquired_information_support_own_next_action_without_becoming_world_truth():
    from novel_forge.modules.worldbuilding.dynamics import WorldTransition, candidate_transition, state_index
    from novel_forge.modules.worldbuilding.working_state import validate_preparation_batch
    from tests.unit.test_world_initial_agency import action, predicate
    reality = working_epistemic_source()
    frozen = deepcopy(reality)
    entries = reality["working_observation_context"]["entries"]
    assert {entry["state_kind"] for entry in entries} == {"character_belief", "character_knowledge"}
    assert all("broken" not in entry["state"]["proposition"] for entry in entries)
    for entry in entries:
        choice = action("choose", entry["state"]["character_id"], "INFORMATION_DEPENDENT", "world_state", "resource:record",
            {"request_copy": True}, 3, causes=(entry["source_event_id"],),
            basis=(predicate(entry["state_kind"], entry["entity_key"], "proposition", entry["state"]["proposition"]),))
        assert candidate_transition(WorldTransition.from_mapping(choice), reality)["eligible"]
        ordered, _ = validate_preparation_batch(reality=reality, transitions=[choice], chapter_number=2, path_id="next")
        assert ordered[0]["actor_id"] == entry["state"]["character_id"]
        choice["actor_id"] = "character:keeper" if choice["actor_id"] == "character:reader" else "character:reader"
        with pytest.raises(KernelError, match="WORLD_EPISTEMIC_ACTOR_MISMATCH"):
            candidate_transition(WorldTransition.from_mapping(choice), reality)
    assert reality["current_state"] == {} and reality["events"] == [] and reality == frozen
    assert not any(kind == "world_state" for kind, key in state_index(reality))


def test_supervisor_replans_only_future_when_world_missed_unchanged_working_history():
    from novel_forge.modules.book_authority.supervisor import PostgresBookProductionSupervisor
    supervisor = object.__new__(PostgresBookProductionSupervisor)
    source = world_source()
    working = {"working_manuscript": source["working_manuscript"]}
    supervisor._generation_arc_working_set = lambda **kwargs: working
    supervisor._future_plan_evidence = lambda *args, **kwargs: ()
    plan = {"execution_scope": "PLANNED", "content": {"constraint_envelope": {
        "arc_working_set": working, "world_preparation": {"frozen_source": {**source, "contract_version": "world-preparation-source.v4"}}}}}
    assert supervisor._plan_working_set_is_stale(book={}, plan=plan, generator="chapter_plan.generate", chapter_number=5)
    plan["content"]["constraint_envelope"]["world_preparation"]["frozen_source"] = source
    assert not supervisor._plan_working_set_is_stale(book={}, plan=plan, generator="chapter_plan.generate", chapter_number=5)
    plan["execution_scope"] = "FROZEN"
    with pytest.raises(KernelError, match="BOOK_SUPERVISOR_FROZEN_PLAN_WORKING_SET_STALE"):
        supervisor._replace_planned_working_set(book={}, plan=plan, generator="chapter_plan.generate", chapter_number=5)

