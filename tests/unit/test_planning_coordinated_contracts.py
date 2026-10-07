from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.application import story_planning_generation_definition
from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS, foundation_output_schema, foundation_output_schema_ref
from novel_forge.modules.story_planning_runtime.runtime_continuation import require_source, runtime_continuation_definition, _world_agency_pack_profile
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
from novel_forge.modules.worldbuilding.production_schema import world_transition_schema, world_generation_schema, world_evaluation_schema
from tests.unit.test_story_planning_runtime import _command

ROOT = Path(__file__).resolve().parents[2]
FROZEN = json.loads((ROOT / "tests/fixtures/planning_main_c621_contract_hashes.json").read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize("version", ["1.17.0", "1.18.0", "1.19.0"])
def test_main_frozen_planning_definition_manifest_catalog_and_foundation_schema_are_exact(version):
    definition = story_planning_generation_definition(application_build_id="historical-hash-probe", commit_sha="1" * 40, definition_version=version)
    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64, execution_contract_version=version)
    assert {"definition": digest(definition), "manifest": digest(profile.manifest), "catalog": digest(profile.artifact_catalog)} == FROZEN["contracts"][version]
    assert {generator: digest(foundation_output_schema(generator, work_requirements=True, rfc6901_paths=version == "1.19.0")) for generator in FOUNDATION_GENERATORS} == FROZEN["foundation"][version]


def test_main_world_reader_and_runtime_registration_identity_are_exact():
    assert {
        "transition": digest(world_transition_schema()),
        "generation": digest(world_generation_schema(WorldProductionPolicy())),
        "scoped_generation": digest(world_generation_schema(WorldProductionPolicy(), audience_scoped=True, arc_refs=("arc:a",), obligation_refs=("obligation:a",))),
        "evaluation": digest(world_evaluation_schema({"candidates": [{"transition": {"transition_id": "future"}}]})),
    } == FROZEN["contracts"]["world"]
    assert digest(runtime_continuation_definition(application_build_id="historical-hash-probe", commit_sha="1" * 40)) == FROZEN["foundation"]["runtime_continuation"]


def test_current_planning_contract_keeps_main_serialization_and_adds_explicit_world_schema():
    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "b" * 64)
    assert profile.manifest["identity"]["version"] == "2.12.0"
    assert {node["operation_definition_ref"] for node in profile.manifest["workflow_template"]["nodes"]} == {"story_planning.generate@1.20.0"}
    assert profile.manifest["prompt_binding"]["system_instruction_version"] == "v10"
    system = next(item for item in profile.artifact_catalog["artifacts"] if item["ref"] == "prompt-system:story-planning-pack" and item["version"] == "v10")
    assert "CHARACTER_INITIATED" in system["content"]["text"]
    assert foundation_output_schema_ref("creative.candidates.generate", execution_contract_version="1.20.0").endswith(":v4")
    current = world_generation_schema(WorldProductionPolicy(), agency=True)
    assert "action_mode" in json.loads(current["properties"]["candidates"]["items"]["properties"]["transition"]["properties"]["payload_json"]["description"].split(": ", 1)[1])["properties"]
    assert "action_mode" not in world_transition_schema()["properties"]


@pytest.mark.parametrize("version", ["1.18.0", "1.19.0"])
def test_world_contract_pack_upgrade_preserves_source_policies_and_history(version):
    source = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64, execution_contract_version=version)
    frozen = {"manifest": deepcopy(source.manifest), "artifact_catalog": deepcopy(source.artifact_catalog)}
    before = deepcopy(frozen)
    successor, generation = _world_agency_pack_profile(frozen, "sha256:" + "b" * 64, repository_root=ROOT)
    assert frozen == before
    assert generation == 1
    assert successor.manifest["identity"]["version"] == "2.12.0"
    for key in ("context_sources", "routing_policy", "tool_permissions", "skill_binding"):
        if key in frozen["manifest"]:
            assert successor.manifest[key] == frozen["manifest"][key]
    assert successor.manifest["prompt_binding"]["system_instruction_version"] == "v10"
    assert successor.artifact_catalog["artifacts"][:-1] == frozen["artifact_catalog"]["artifacts"]
    for original, current in zip(frozen["manifest"]["workflow_template"]["nodes"], successor.manifest["workflow_template"]["nodes"], strict=True):
        expected = {**original, "operation_definition_ref": "story_planning.generate@1.20.0", "operation_definition_hash": "sha256:" + "b" * 64}
        assert current == expected


@pytest.mark.parametrize("reason", ["WORLD_AGENCY_CONTRACT_SUCCESSOR", "WORLD_HOST_REVALIDATION_SUCCESSOR", "WORLD_HOST_PROJECTION_SUCCESSOR"])
def test_world_contract_successor_has_exact_version_reason_world_scope_and_counter(reason):
    source = _command("chapter_plan.generate")
    current = replace(source, world_preparation_request={"book_run_id": "run", "input_snapshot_id": "snapshot", "accepted_through_chapter": 0, "story_state_version_id": "", "canon_version_id": ""}, runtime_continuation_id="registered", repair_reason=reason, repair_number=2)
    assert current.repair_number == 2
    for fields in [dict(execution_contract_version="1.19.0"), dict(runtime_continuation_id=""), dict(repair_reason="arbitrary"), dict(repair_number=5), dict(world_preparation_request=None)]:
        with pytest.raises(ValueError):
            replace(current, **fields)


@pytest.mark.parametrize("source_status,attempt_status", [("FAILED_RETRYABLE", "FAILED_RETRYABLE"), ("FAILED_FINAL", "FAILED_RETRYABLE"), ("FAILED_FINAL", "UNKNOWN")])
def test_world_contract_continuation_cannot_consume_retryable_or_unknown_attempt(source_status, attempt_status):
    responses = [(source_status, 1, "workspace", {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "execution_contract_version": "1.19.0"}, "book", None), (attempt_status, {"error_code": "WORLD_PREPARATION_RESULT_INVALID"}, {})]

    class Cursor:
        def execute(self, *_):
            self.response = responses.pop(0)

        def fetchone(self):
            return self.response

    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        require_source(SimpleNamespace(cursor=Cursor()), source_operation_id="source", project_id="project")


def test_native_world_current_schema_identity_keeps_exact_stage_and_historical_reader():
    from novel_forge.api.authority_dependencies import validate_production_structured_result
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_native_world_schema_fragment
    from tests.unit.test_world_initial_agency import chain
    from novel_forge.modules.worldbuilding.production_schema import decode_world_generation

    transitions = chain()
    raw = {"disposition": "CANDIDATES", "reason": "Native agency schema proof", "candidates": [{
        "transition": transitions[-1], "affected_entities": ["character:reader"], "world_consequences": ["Accountable choice"],
        "arc_refs": [], "obligation_refs": [], "risks": [], "soft_assumptions": [], "narrative_preferences": [],
        "rationale": "Observe before choosing", "preparation_paths": [{"path_id": "first", "steps": [{"transition": transition, "chapter_offset": 0} for transition in transitions[:-1]], "rationale": "Causal observation"}],
        "information_scope": {"disclosures": []},
    }]}
    for candidate in raw["candidates"]:
        candidate["transition"] = {"payload_json": json.dumps(candidate["transition"])}
        for path in candidate["preparation_paths"]:
            for step in path["steps"]:
                step["transition"] = {"payload_json": json.dumps(step["transition"])}
    schema = world_generation_schema(WorldProductionPolicy(), audience_scoped=True, agency=True)
    validated = validate_production_structured_result("world_candidates.generate", schema, raw, output_schema_ref="schema:world_candidates.generate:v2")
    assert decode_world_generation(validated, agency=True)["candidates"][0]["transition"]["action_mode"] == "INFORMATION_DEPENDENT"
    for ref in ("schema:world_candidates.generate:v3", "schema:world_candidates.evaluate:v2", "schema:world_candidates.generate:v2:actor-isolation-v1"):
        with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED"):
            validate_native_world_schema_fragment("world_candidates.generate", schema, raw, output_schema_ref=ref)
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED"):
        validate_native_world_schema_fragment("world_candidates.actor_0", schema, raw, output_schema_ref="schema:world_candidates.actor_0:v2")


def contract_route(**overrides):
    from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
    from tests.unit.test_cost_aware_routing import NOW, task
    from tests.unit.test_creative_execution_template import membership, template
    from novel_forge.modules.production_execution.execution_template import template_decision
    from novel_forge.modules.production_execution.cost_routing import RoutingDecision

    receipt = {"contract_version": "planning-route-contract-successor.v1", "operation_id": "operation", "source_operation_id": "parent",
        "input_hash": "current", "source_input_hash": "prior", "changed_contract": "world-agency.v2", "contract_chain_depth": 1,
        "repair_number": 0, "maximum_repairs": 4, "accepted_history_mutation_allowed": False, "authorized_history_operation_ids": ["parent"], **overrides}
    current = task(task_type="world_candidates.generate", input_hash="current", lineage_operation_ids=("parent", "operation"),
        policy_snapshot={"policy": {"execution_templates": [template()]}},
        history=({"operation_id": "parent", "candidate_id": "member", "failure_class": "SCHEMA_REJECTION"},),
        declared_requirements={"governed_repair": receipt})
    snapshot = CostAwareRouter().explain(current, [replace(membership(), authorized_tasks=("world_candidates.generate",))], {}, now=NOW)
    return template_decision(RoutingDecision(snapshot.snapshot_json)).to_dict()


def test_world_contract_successor_uses_governed_chain_at_unchanged_zero_content_repair_counter():
    snapshot = contract_route()
    assert snapshot["status"] == "SELECTED"
    assert "native_repair_admission" not in snapshot["candidates"][0]
    assert snapshot["task"]["declared_requirements"]["governed_repair"]["repair_number"] == 0
    assert snapshot["checks"]["literary_model_qualification"]["status"] == "NOT_RUN"


@pytest.mark.parametrize("change", [{"contract_chain_depth": 2}, {"contract_chain_depth": True}, {"maximum_repairs": 4.0}, {"maximum_repairs": True}, {"repair_number": 5}, {"repair_number": -1},
    {"input_hash": "other"}, {"source_input_hash": "current"}, {"changed_contract": "arbitrary"}, {"accepted_history_mutation_allowed": True},
    {"authorized_history_operation_ids": ["other"]}, {"contract_version": "planning-route-contract-successor.v2"}])
def test_world_contract_route_cannot_expand_lineage_counter_or_reinterpret_unknown_contract(change):
    assert contract_route(**change)["status"] == "BLOCKED"


def test_historical_serialized_world_reader_does_not_acquire_current_action_mode():
    from tests.unit.test_world_causal_preparation import generated_paths
    from novel_forge.modules.worldbuilding.production_schema import decode_world_generation

    raw = generated_paths()
    for candidate in raw['candidates']:
        candidate['transition']['action_mode'] = 'ROUTINE'
        candidate['transition'] = {'payload_json': json.dumps(candidate['transition'])}
        for path in candidate['preparation_paths']:
            for step in path['steps']:
                step['transition'] = {'payload_json': json.dumps(step['transition'])}
    with pytest.raises(KernelError, match='CAUSAL_CONTRACT_INVALID'):
        decode_world_generation(raw)


def test_current_actor_world_role_preserves_adjudication_and_selects_explicit_agency_reader():
    from novel_forge.api.authority_dependencies import validate_production_structured_result
    from novel_forge.modules.worldbuilding.actor_isolation import actor_judge_schema, require_actor_judgments
    from tests.unit.test_world_initial_agency import chain

    proposal = {"actor_id": "character:reader", "proposal_hash": "sha256:" + "a" * 64, "action": "choose"}
    candidate = {"transition": {"payload_json": json.dumps(chain()[-1])}, "affected_entities": ["character:reader"], "world_consequences": ["Accountable action"],
        "arc_refs": [], "obligation_refs": [], "risks": [], "soft_assumptions": [], "narrative_preferences": [], "rationale": "Keep private intention", "preparation_paths": [],
        "information_scope": {"disclosures": []}}
    raw = {"disposition": "CANDIDATES", "reason": "Exact actor intention", "candidates": [candidate], "actor_adjudications": [{
        "actor_id": proposal["actor_id"], "proposal_hash": proposal["proposal_hash"], "decision": "EXECUTABLE", "consequence_summary": "Native candidate only"}]}
    schema = actor_judge_schema(world_generation_schema(WorldProductionPolicy(), agency=True, audience_scoped=True), [proposal])
    validated = validate_production_structured_result("world_candidates.generate", schema, raw, output_schema_ref="schema:world_candidates.generate:v2:actor-isolation-v1")
    require_actor_judgments(validated, [proposal], agency=True)
    with pytest.raises(KernelError, match="CAUSAL_CONTRACT_INVALID"):
        require_actor_judgments(validated, [proposal])
    changed = deepcopy(validated)
    changed["actor_adjudications"][0]["proposal_hash"] = "sha256:" + "b" * 64
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_REWRITTEN"):
        require_actor_judgments(changed, [proposal], agency=True)
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED"):
        validate_production_structured_result("world_candidates.generate", schema, raw, output_schema_ref="schema:world_candidates.generate:v1:actor-isolation-v1")


def test_current_actor_director_uses_current_classification_schema_without_generator_adjudications():
    from novel_forge.api.authority_dependencies import validate_production_structured_result
    from novel_forge.modules.worldbuilding.production_schema import agency_transition_paths
    from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS
    from tests.unit.test_world_initial_agency import chain

    generated = {"candidates": [{"transition": chain()[-1], "preparation_paths": []}]}
    schema = world_evaluation_schema(generated, agency=True)
    output = {"evaluations": [{"transition_id": "choose", "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.8), "rationale": "Exact actor judgment", "preferred_path_id": ""}],
        "action_classifications": [{"field_path": path, "supported": True, "rationale": "Typed source supports this current action"} for path in agency_transition_paths(generated)]}
    assert validate_production_structured_result("world_candidates.evaluate", schema, output, output_schema_ref="schema:world_candidates.evaluate:v2:actor-isolation-v1") == output
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_CONTRACT_UNSUPPORTED"):
        validate_production_structured_result("world_candidates.evaluate", world_evaluation_schema(generated), {"evaluations": output["evaluations"]}, output_schema_ref="schema:world_candidates.evaluate:v2:actor-isolation-v1")


@pytest.mark.parametrize("version", ["creative-execution-template.v10", "creative-execution-template.v11"])
def test_composed_template_preserves_historical_quality_control_and_current_guards(version):
    from novel_forge.modules.production_execution.execution_template import validate_templates
    from tests.unit.test_creative_execution_template import template

    value = template(version=version, world_future_preparation="OPTIONAL",
        repair_routing={"version": "native-repair-routing.v2", "max_same_route_repairs": 2},
        canon_validation_contract="grounded-canon-validation.v2",
        chapter_graph_recovery="RETAIN_SETTLED_CREATIVE_RESULT",
        canon_evidence_localization="TYPOGRAPHIC_QUOTE_EQUIVALENCE_V1",
        quality_corrections={"version": "quality-correction-control.v1", "maximum_passes": 3, "maximum_unchanged_candidates": 1})
    validate_templates({"execution_templates": [value]})
    for invalid in (
        {**value, "quality_corrections": None},
        {**value, "quality_corrections": {**value["quality_corrections"], "maximum_passes": 11}},
        {**value, "version": "creative-execution-template.v9"},
        {**value, "mode": "STRICT_PRODUCTION", "require_literary_qualification": True},
    ):
        with pytest.raises(KernelError):
            validate_templates({"execution_templates": [invalid]})


def test_current_contract_receipt_is_rechecked_by_the_native_dispatch_owner_before_send():
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter

    snapshot = contract_route()
    receipt = snapshot["task"]["declared_requirements"]["governed_repair"]
    calls = []

    def changed_receipt(**arguments):
        calls.append(arguments)
        return {**receipt, "source_input_hash": "another-native-stage"}

    owner = SimpleNamespace(registry=SimpleNamespace(planning_repair_receipt=changed_receipt))
    with pytest.raises(KernelError, match="ROUTING_REPAIR_EVIDENCE_DRIFT"):
        ProductionProviderRouter._selected_route(owner, None, snapshot)
    assert calls == [{"project_id": snapshot["task"]["project_id"], "book_id": snapshot["task"]["work_id"],
        "operation_id": snapshot["task"]["operation_id"], "task_type": snapshot["task"]["task_type"],
        "input_hash": snapshot["task"]["input_hash"], "lineage": tuple(snapshot["task"]["lineage_operation_ids"])}]
