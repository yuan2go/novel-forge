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
@pytest.mark.parametrize("drift", [None, "book", "target", "accepted", "hash", "legacy"])
def test_world_author_intent_binds_frozen_working_frontier(role, stage, drift):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
    from tests.unit.test_author_design_adoption import _world_author_context
    _, _, context = _world_author_context(stage)
    source = world_source()
    task = PlanningWorldPreparation._task(source, {"asset_version_id": "source", "content_hash": "digest"}, role)
    context.update(project_id="p", book_id="b", logical_key="chapter:5", world_preparation=task)
    author = context["author_design_projection"]
    author["chapter_range"] = [5, 5]
    for fragment in author["fragments"]:
        fragment["chapter_range"] = [5, 5]
    if drift == "book":
        context["book_id"] = "other"
    elif drift == "target":
        task["target_chapter"] = 6
    elif drift == "accepted":
        task["accepted_through_chapter"] = 1
    elif drift == "hash":
        task["working_manuscript"]["sources"][0]["content_hash"] = "stale"
    elif drift == "legacy":
        task.pop("working_manuscript")
    if drift:
        with pytest.raises(KernelError):
            build_provider_context_view(stage, context, {"world_preparation": task})
    else:
        view = build_provider_context_view(stage, context, {"world_preparation": task})
        assert view["accepted_state_boundary"]["accepted_through_chapter"] == 0
        assert view["author_design_projection"]["chapter_range"] == [5, 5]


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


@pytest.mark.parametrize("role,stage", [("WORLD_REASONER", "world_candidates.generate"), ("DIRECTOR", "world_candidates.evaluate")])
def test_compact_world_delivery_preserves_exact_story_and_original_observation_binding(role, stage):
    from novel_forge.modules.worldbuilding.working_state import project_working_observation_context
    source = world_source()
    source["provider_projection_version"] = "world-role-delivery.v4"
    source["reality"] = project_working_observation_context(reality=source["reality"], working=source["working_manuscript"], characters=[])
    original = deepcopy(source)
    task = PlanningWorldPreparation._task(source, {"asset_version_id": "source", "content_hash": "digest"}, role)
    delivered = build_provider_task_view(stage, {"world_preparation": task})["world_preparation"]
    assert source == original
    assert delivered["contract_version"] == "world-provider-task.v5"
    receipt = delivered["working_delivery_receipt"]
    assert receipt["source_snapshot_hash"] == source["working_manuscript"]["snapshot_hash"]
    assert receipt["source_snapshot_hash"] == delivered["working_observation_context"]["snapshot_hash"]
    assert receipt["delivery_snapshot_hash"] == delivered["working_manuscript"]["snapshot_hash"]
    assert receipt["character_knowledge_granted"] is False
    assert delivered["working_manuscript"]["sources"][-1]["passages"][0]["text"] == "".join(p["text"] for p in source["working_manuscript"]["sources"][-1]["passages"])
    assert "schema" not in delivered["transition_contract"]
    assert delivered["transition_contract"]["payload_schema"] == task["transition_contract"]["payload_schema"]
    assert build_provider_task_view(stage, {"world_preparation": delivered})["world_preparation"] == delivered
    delivered["working_delivery_receipt"]["source_snapshot_hash"] = "sha256:another-source"
    with pytest.raises(KernelError, match="WORLD_WORKING_DELIVERY_DRIFT"):
        build_provider_task_view(stage, {"world_preparation": delivered})


def test_world_delivery_keeps_knowledge_and_separates_selection_criteria_from_character_rules():
    from novel_forge.modules.chapter_authority.provider_views import _project_world_knowledge_delivery
    need = {"need_digest": "sha256:" + "a" * 64, "target_stage": "chapter_plan.generate", "required_card_asset_version_ids": [],
        "hard_constraints": ["runtime-reference"], "condition_sources": {"source": {"asset_version_id": "asset", "content_hash": "hash"}}}
    original = {"need": need, "selection_digest": "sha256:" + "b" * 64, "selected": [], "selection_status": "NO_ELIGIBLE_MATCH"}
    frozen = deepcopy(original)
    result = _project_world_knowledge_delivery(original)
    assert original == frozen and result["selected"] == original["selected"]
    assert result["need"] == {key: need[key] for key in ("need_digest", "target_stage", "required_card_asset_version_ids")}
    assert "hard_constraints" in result["need_delivery_receipt"]["omitted_fields"]
    assert _project_world_knowledge_delivery(result) == result
    result["need_delivery_receipt"]["need_digest"] = "changed"
    with pytest.raises(KernelError, match="WORLD_SELECTION_RECEIPT_INVALID"):
        _project_world_knowledge_delivery(result)


@pytest.mark.parametrize("version", ["world-role-delivery.v3", "world-role-delivery.v4"])
def test_task_scoped_world_history_excludes_unselected_internal_event(version, monkeypatch):
    from novel_forge.modules.story_planning_runtime import world_preparation as module
    source = world_source()
    source["provider_projection_version"] = version
    source["reality"]["events"] = [{"event_id": identity, "state_kind": "world_state",
        "identity": {"entity_key": identity}, "coordinate": {"source_chapter": 0},
        "mutation": {"payload": {"world_transition": True, "description": value}}}
        for identity, value in [("selected", "Visible consequence"), ("internal", "Private quality decision")]]
    monkeypatch.setattr(module, "project_role_context", lambda **kwargs: {"context_digest": "digest",
        "selection": [{"source_event_id": "selected"}]})
    task = PlanningWorldPreparation._task(source, {"asset_version_id": "source", "content_hash": "digest"}, "DIRECTOR")
    assert [event["event_id"] for event in task["accepted_history"]] == ["selected"]
    assert task["accepted_history"][0]["fields"]["description"] == "Visible consequence"


@pytest.mark.parametrize("drift", [None, "story", "knowledge", "inputs", "task", "proof"])
def test_actual_world_successor_consumes_registered_frozen_delivery_proof(drift, monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime import runtime_continuation, world_preparation
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    from novel_forge.modules.worldbuilding.working_state import project_working_observation_context
    original_contract = world_source()
    original_contract["provider_projection_version"] = "world-role-delivery.v3"
    original_contract["reality"] = project_working_observation_context(reality=original_contract["reality"], working=original_contract["working_manuscript"], characters=[])
    def document(identity, contract):
        content = {"contract": contract}
        return SimpleNamespace(asset_version_id=identity, asset_type="world_preparation_source", content=content, content_hash=canonical_hash(content))
    original = document("original", original_contract)
    corrected = {**deepcopy(original_contract), "provider_projection_version": "world-role-delivery.v4"}
    current = document("successor", corrected)
    preview = document("original", corrected)
    base = SimpleNamespace(asset_version_id="context", content_hash="context-hash", content={"narrative_intelligence": {}, "input_versions": []})
    monkeypatch.setattr(world_preparation, "world_plan_references", lambda *args: {})
    def context_content(*, command, base, stage, source):
        return {"context_manifest": {"provider_context_view": {"world_preparation": stage.task}}}
    monkeypatch.setattr(PostgresPlanningExecutionPreparer, "_world_context_content", staticmethod(context_content))
    command = SimpleNamespace(project_id="p", runtime_continuation_id="runtime")
    def stage(source):
        return PlanningWorldPreparation.generation_stage(source.content["contract"],
            {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}, {}, allowed_references={})
    actual = stage(current)
    proposed = stage(preview)
    proof = {"contract_version": "world-input-delivery-revalidation.v1", "source_ref": {"asset_version_id": original.asset_version_id, "content_hash": original.content_hash},
        "delivered_task_hash": canonical_hash(proposed.task), "context_projection_hash": runtime_continuation._context_projection_hash(context_content(command=command,base=base,stage=proposed,source=preview))}
    binding = {"target_runtime": {"planning_capacity": {"context_revalidation": {"context_asset_version_id": base.asset_version_id, "context_content_hash": base.content_hash, "world_input_delivery": proof}}}}
    monkeypatch.setattr(runtime_continuation, "require_binding", lambda *args: binding)
    preparer = object.__new__(PostgresPlanningExecutionPreparer)
    preparer.database_url = "unused"
    preparer.query = SimpleNamespace(require=lambda **kwargs: {"original": original, "context": base}[kwargs["asset_version_id"]])
    actual_base = deepcopy(base)
    if drift == "story":
        current.content["contract"]["intent"] = {"changed": "New story input"}
    elif drift == "knowledge":
        actual_base.content["narrative_intelligence"] = {"new_selection": True}
    elif drift == "inputs":
        actual_base.content["input_versions"] = [{"asset_version_id": "foreign"}]
    elif drift == "task":
        actual.task["intent"] = {"changed": "New story input"}
    elif drift == "proof":
        proof["delivered_task_hash"] = "changed"
    if drift:
        with pytest.raises(KernelError, match="WORLD_INPUT_DELIVERY_REVALIDATION_DRIFT"):
            preparer._require_world_delivery_continuation(command=command,base=actual_base,stage=actual,source=current)
    else:
        preparer._require_world_delivery_continuation(command=command,base=actual_base,stage=actual,source=current)


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


def test_local_disclosure_uses_bound_working_chapter_without_advancing_accepted_history():
    from novel_forge.modules.narrative_state.information import project_candidate_disclosure, project_disclosure
    from tests.unit.test_world_initial_agency import chain

    reality = working_epistemic_source()
    reality["disclosure_fields_contract"] = "world-disclosure-fields.v2"
    frozen = deepcopy(reality)
    disclosure = {"disclosure_id": "visible", "event_id": "local:open", "audience": "READER", "mode": "CONFIRM",
        "fields": ["changes.access"], "presentation_channel": "witnessed opening", "claim_kind": "HISTORICAL_OCCURRENCE"}
    result = project_candidate_disclosure(reality, disclosure, transitions=chain(), chapter_number=2, path_id="working")
    assert result["source"]["state"] == {"access": "AVAILABLE"}
    assert result["source"]["evidence_role"] == "PLANNED_LOCAL_OCCURRENCE"
    assert reality == frozen and reality["chapter_number"] == 0 and reality["events"] == []
    with pytest.raises(KernelError, match="WORLD_DISCLOSURE_SOURCE_UNKNOWN"):
        project_disclosure(reality, disclosure)
    for target in (1, 3):
        with pytest.raises(KernelError, match="WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID"):
            project_candidate_disclosure(reality, disclosure, transitions=chain(), chapter_number=target, path_id="working")


@pytest.mark.parametrize("target", [None, True, 0, "2"])
def test_unbound_or_invalid_working_frontier_cannot_authorize_candidate_disclosure(target):
    from novel_forge.modules.narrative_state.reality import narrative_hash
    from novel_forge.modules.worldbuilding.dynamics import candidate_chapter

    reality = working_epistemic_source()
    working = reality["working_observation_context"]
    working["target_chapter"] = target
    working["projection_hash"] = narrative_hash({key: value for key, value in working.items() if key != "projection_hash"})
    with pytest.raises(KernelError, match="WORLD_WORKING_OBSERVATION_INVALID"):
        candidate_chapter(reality)


@pytest.mark.parametrize("projection", [{}, [], False])
def test_corrupt_working_projection_cannot_fall_back_to_accepted_scope(projection):
    from novel_forge.modules.worldbuilding.dynamics import candidate_chapter

    reality = working_epistemic_source()
    reality["working_observation_context"] = projection
    with pytest.raises(KernelError, match="WORLD_WORKING_OBSERVATION_INVALID"):
        candidate_chapter(reality)


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

