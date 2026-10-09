from copy import deepcopy

from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
import pytest

from novel_forge.modules.story_planning_runtime.execution import bind_provider_realization_selectors
from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_output_schema
from novel_forge.modules.story_planning_runtime.narrative_search import NarrativeSearchProjection
from tests.integration.current_planning_wire_support import current_planning_wire_result
from tests.integration.synthesis_production_support import SynthesisTransport


def test_current_foundation_search_fixture_obeys_actual_v5_schema():
    transport = SynthesisTransport()
    outputs = []
    for ordinal, directive in enumerate(("character agency", "world consequence"), start=1):
        inputs = {
            "foundation_task": {"contract_version": "foundation-generation.v5"},
            "planning_command": {
                "execution_contract_version": "1.21.0", "narrative_search_id": "frozen-search",
                "narrative_search_branch_key": f"branch-{ordinal}", "narrative_search_strategy_directive": directive,
            },
        }
        result = transport.planning("creative.candidates.generate", inputs)
        _validate(foundation_output_schema("creative.candidates.generate", work_requirements=True, rfc6901_paths=True, narrative_search=True), result, path="$")
        NarrativeSearchProjection.from_mapping(result["narrative_search_projection"])
        outputs.append(result)
    assert outputs[0]["constraints"] != outputs[1]["constraints"]
    assert outputs[0]["narrative_search_projection"]["strategy_fingerprint"] != outputs[1]["narrative_search_projection"]["strategy_fingerprint"]


@pytest.mark.parametrize("version", ["1.18.0", "1.19.0", "1.20.0"])
def test_historical_planning_fixture_keeps_original_provider_body(version):
    original = {"world_realization": [{"state_ref": {"asset_version_id": "frozen", "content_hash": "original"}}]}
    assert current_planning_wire_result(original, {"planning_command": {"execution_contract_version": version}}) is original
    result = SynthesisTransport().planning("creative.candidates.generate", {"foundation_task": {"contract_version": "foundation-generation.v4"}})
    assert "narrative_search_projection" not in result
    _validate(foundation_output_schema("creative.candidates.generate", work_requirements=True, rfc6901_paths=True), result, path="$")


def test_current_selector_fixture_only_selects_a_supplied_domain_source():
    original = {"world_realization": [{"invariant_refs": [], "structure_refs": [], "state_ref": {"asset_version_id": "old-fixture-source", "content_hash": "fixture-does-not-own-hash"}}]}
    frozen = deepcopy(original)
    catalog = {"references_by_domain": {"WORLD_STATE": [{"asset_version_id": "actual-source", "content_hash": "native-hash", "frozen_by_operation_id": "native-owner"}]}}
    wire = current_planning_wire_result(original, {"planning_command": {"execution_contract_version": "1.21.0"}, "realization_reference_contract": catalog})
    assert original == frozen
    assert wire["world_realization"][0]["state_ref"] == {"asset_version_id": "actual-source"}
    assert bind_provider_realization_selectors(wire, catalog)["world_realization"][0]["state_ref"] == catalog["references_by_domain"]["WORLD_STATE"][0]


@pytest.mark.parametrize("sources", [[], [{"asset_version_id": "a"}, {"asset_version_id": "b"}]])
def test_current_selector_fixture_refuses_missing_or_ambiguous_domain(sources):
    with pytest.raises(ValueError, match="unambiguous frozen WORLD_STATE"):
        current_planning_wire_result({"world_realization": [{"invariant_refs": [], "structure_refs": [], "state_ref": {"asset_version_id": "missing"}}]}, {"planning_command": {"execution_contract_version": "1.21.0"}, "realization_reference_contract": {"references_by_domain": {"WORLD_STATE": sources}}})


def test_current_foundation_search_fixture_cannot_invent_a_search_grant():
    with pytest.raises(ValueError, match="frozen search command"):
        SynthesisTransport().planning("creative.candidates.generate", {"foundation_task": {"contract_version": "foundation-generation.v5"}, "planning_command": {"execution_contract_version": "1.21.0"}})


def disclosure_inputs():
    from tests.unit.test_world_initial_agency import genesis
    source = {"state_kind": "world_state", "entity_key": "resource:record", "source_event_id": "accepted:notice", "entity_version": 1, "state": {"status": "OPEN"}}
    task = {"epistemic_contract": "world-agency.v2", "character_definitions": [{"character_id": "character:reader"}], "context_projection": {"selection": [source]}}
    result = {"candidates": [{"information_scope": {"disclosures": [{"event_id": "accepted:notice", "presentation_channel": "LETTER"}]}, "affected_entities": ["character:reader"], "transition": {"payload_json": __import__("json").dumps({"transition_id": "reveal-accepted-notice", "actor_id": "character:keeper", "camera": "ON_CAMERA", "story_time": {"timeline_id": "main", "start_ordinal": 2, "end_ordinal": 2, "precision": "ORDERED", "label": ""}, "action": "reveal", "state_kind": "disclosure_event", "entity_key": "disclosure_id=accepted-notice", "changes": {"disclosure_id": "accepted-notice", "fact_id": "accepted:notice", "audience": "READER", "disclosure_mode": "CONFIRM"}, "requirements": [], "epistemic_basis": [], "cause_refs": ["accepted:notice"]})}, "preparation_paths": []}]}
    reality = genesis()
    reality["current_state"] = {"world_state": [source]}
    return result, task, reality


def test_current_disclosure_fixture_requires_real_source_then_own_acquisition():
    import json
    from novel_forge.modules.worldbuilding.production_schema import world_transition_schema
    from novel_forge.modules.worldbuilding.working_state import validate_preparation_batch
    from tests.integration.current_planning_wire_support import current_world_disclosure_result, current_world_fixture_classification
    result, task, reality = disclosure_inputs()
    frozen = deepcopy(reality)
    prepared = current_world_disclosure_result(result, task)["candidates"][0]
    observe = json.loads(prepared["preparation_paths"][0]["steps"][0]["transition"]["payload_json"])
    disclose = json.loads(prepared["transition"]["payload_json"])
    for transition in (observe, disclose):
        _validate(world_transition_schema(agency=True), transition, path="$")
        assert current_world_fixture_classification(transition)
    ordered, preview = validate_preparation_batch(reality=reality, transitions=[disclose, observe], chapter_number=1, path_id="fixture")
    assert [item["transition_id"] for item in ordered] == ["observe-accepted-notice", "reveal-accepted-notice"]
    assert reality == frozen
    assert preview["current_state"]["character_knowledge"][0]["source_event_id"] == "local:observe-accepted-notice"


@pytest.mark.parametrize("missing", ["source", "actor"])
def test_current_disclosure_fixture_does_not_invent_an_observer_or_source(missing):
    from tests.integration.current_planning_wire_support import current_world_disclosure_result
    result, task, _ = disclosure_inputs()
    if missing == "source":
        task["context_projection"]["selection"] = []
    else:
        task["character_definitions"] = []
    with pytest.raises(ValueError, match="frozen objective status and an approved character"):
        current_world_disclosure_result(result, task)


def test_current_disclosure_native_gate_refuses_borrowed_acquisition():
    import json
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.worldbuilding.working_state import validate_preparation_batch
    from tests.integration.current_planning_wire_support import current_world_disclosure_result
    result, task, reality = disclosure_inputs()
    candidate = current_world_disclosure_result(result, task)["candidates"][0]
    observe = json.loads(candidate["preparation_paths"][0]["steps"][0]["transition"]["payload_json"])
    disclose = json.loads(candidate["transition"]["payload_json"])
    disclose["actor_id"] = "character:keeper"
    with pytest.raises(KernelError, match="WORLD_EPISTEMIC_ACTOR_MISMATCH"):
        validate_preparation_batch(reality=reality, transitions=[observe, disclose], chapter_number=1, path_id="fixture")


@pytest.mark.parametrize("scope,stage,key", [("BOOK", "book_plan.generate", "book"), ("VOLUME", "volume_plan.generate", "volume:1"), ("ARC", "arc_plan.generate", "arc:1"), ("CHAPTER_GROUP", "chapter_group_plan.generate", "chapter-group:1-3"), ("CHAPTER", "chapter_plan.generate", "chapter:1")])
def test_current_synthesis_hierarchical_wire_obeys_exact_provider_schema(scope, stage, key):
    from novel_forge.modules.hierarchical_planning.domain import PlanContractType
    from novel_forge.modules.story_planning_runtime.execution import planning_provider_output_schema, bind_realization_selector_schema
    from tests.integration.synthesis_production_support import SynthesisChapterTransport
    from tests.unit.test_story_planning_runtime import _realization_slice, _chapter_schedule_row
    catalog = {"references_by_domain": {domain: [{"asset_version_id": domain.lower() + ":actual", "content_hash": "native-hash", "frozen_by_operation_id": "native-owner"}] for domain in ("WORLD_INVARIANT", "WORLD_STRUCTURE", "WORLD_STATE", "CHARACTER_IDENTITY", "CHARACTER_STATE", "CHARACTER_TRAJECTORY")}}
    inputs = {"planning_command": {"execution_contract_version": "1.21.0", "creative_requirements_contract": "work-requirements.v2", "logical_key": key, "parent_version_id": "parent:v1", "input_versions": {"arc_plans": "arc:v1"}}, "realization_reference_contract": catalog}
    arguments = {"logical_key": key, "parent_version_id": "parent:v1", "arc_plan_version_id": "arc:v1", "work_requirements": True, "aligned_methods": True, "serialization_contract": True}
    if scope == "CHAPTER":
        arguments.update(narrative_realization=_realization_slice(parent_version_id="parent:v1"), chapter_schedule_row=_chapter_schedule_row())
        inputs["narrative_realization"] = arguments["narrative_realization"]
        inputs["controlled_frozen_segments"] = [{"role": "chapter_function_matrix_row", "content": arguments["chapter_schedule_row"]}]
        inputs["planning_command"]["narrative_realization"] = arguments["narrative_realization"]
    result = SynthesisChapterTransport().planning(stage, inputs)
    schema = bind_realization_selector_schema(planning_provider_output_schema(PlanContractType(scope), **arguments), catalog, primary_arc_id="arc:v1", related_arc_ids=())
    _validate(schema, result, path="$")


def test_current_fixture_reads_original_operation_context_without_changing_it(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from tests.integration.current_planning_wire_support import current_planning_fixture_inputs
    view = {"realization_reference_contract": {"references_by_domain": {}}, "segments": [{"role": "chapter_function_matrix_row", "content": {"chapter_number": 1}}]}
    frozen = deepcopy(view)
    captured = []
    def require(query, **selectors):
        captured.append(selectors)
        return SimpleNamespace(content={"context_manifest": {"provider_context_view": {"compiled_view": view}}})
    monkeypatch.setattr(AuthorityAssetQuery, "require", require)
    result = current_planning_fixture_inputs({"planning_command": {"execution_contract_version": "1.21.0", "project_id": "original-project", "generation_operation_id": "original-generation"}}, "postgresql://unused")
    assert captured == [{"project_id": "original-project", "logical_ref": "planning/context_bundles/original-generation.json"}]
    result["controlled_frozen_segments"][0]["content"]["chapter_number"] = 999
    assert view == frozen


@pytest.mark.parametrize("scheduled", [["arc:v1"], ["arc:v1", "arc:related"], ["arc:foreign"]])
def test_chapter_arc_schema_uses_required_row_not_all_frozen_context(scheduled):
    from novel_forge.modules.hierarchical_planning.domain import PlanContractType
    from novel_forge.modules.story_planning_runtime.execution import planning_provider_output_schema
    from tests.unit.test_story_planning_runtime import _realization_slice, _chapter_schedule_row

    row = _chapter_schedule_row()
    row["required_arc_contributions"] = [{"arc_plan_version_id": "arc:v1", "contribution": "frozen required movement"}]
    schema = planning_provider_output_schema(PlanContractType.CHAPTER, logical_key="chapter:1", parent_version_id="parent:v1", arc_plan_version_id="arc:v1", related_arc_plan_version_ids=("arc:related",), narrative_realization=_realization_slice(parent_version_id="parent:v1"), chapter_schedule_row=row)
    values = [{"arc_plan_version_id": identity, "role": "PRIMARY" if n == 0 else "TOUCH", "segment_id": "segment", "expected_movement": "planned movement"} for n, identity in enumerate(scheduled)]
    if scheduled == ["arc:v1"]:
        _validate(schema["properties"]["arc_schedule"], values, path="$.arc_schedule")
    else:
        with pytest.raises(ValueError):
            _validate(schema["properties"]["arc_schedule"], values, path="$.arc_schedule")


def test_current_fixture_refuses_missing_actual_frozen_context():
    from tests.integration.current_planning_wire_support import current_planning_fixture_inputs
    with pytest.raises(ValueError, match="actual frozen Context"):
        current_planning_fixture_inputs({"planning_command": {"execution_contract_version": "1.21.0"}}, "")
