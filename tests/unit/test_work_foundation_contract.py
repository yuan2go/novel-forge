from __future__ import annotations

from copy import deepcopy
import pytest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.foundation_generation import (
    foundation_task,
    validate_foundation_payload,
)
from novel_forge.modules.story_design_authority.qualification import (
    scripted_qualification,
    validate_narrative_qualification,
)


def ending_payload(status="NOT_APPLICABLE"):
    return {
        "objective": "保留开放结局",
        "constraints": [],
        "prohibited_outcomes": [],
        "ending_direction": "保留未回答的问题，不新增人物代价",
        "protagonist_cost": None,
        "closure_conditions": [],
        "unacceptable_shortcuts": [],
        "applicability": [
            {
                "field_path": "$.protagonist_cost",
                "status": status,
                "rationale": "本书选择观察性开放结局",
            }
        ],
        "foundation_parent_bindings": {},
        "constraint_envelope": {
            "contract_version": "foundation-generation.v2",
            "foundation_parent_bindings": {},
        },
    }


def test_optional_ending_cost_is_not_a_missing_field():
    payload = ending_payload()
    validate_foundation_payload(
        "ending.intent.generate", {"candidate_payload": payload}
    )
    del payload["protagonist_cost"]
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_foundation_payload(
            "ending.intent.generate", {"candidate_payload": payload}
        )


def test_optional_feature_requires_consistent_exact_applicability():
    payload = ending_payload()
    payload["applicability"] = []
    with pytest.raises(KernelError, match="FOUNDATION_APPLICABILITY_REQUIRED"):
        validate_foundation_payload(
            "ending.intent.generate", {"candidate_payload": payload}
        )
    payload = ending_payload("APPLICABLE")
    with pytest.raises(KernelError, match="FOUNDATION_APPLICABILITY_INVALID"):
        validate_foundation_payload(
            "ending.intent.generate", {"candidate_payload": payload}
        )


def test_old_ending_contract_remains_cost_required():
    payload = ending_payload()
    payload.pop("applicability")
    payload["constraint_envelope"]["contract_version"] = "foundation-generation.v1"
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_foundation_payload(
            "ending.intent.generate", {"candidate_payload": payload}
        )
    assert "irreversible costs" in foundation_task("ending.intent.generate")["task"]
    assert (
        "open ending"
        in foundation_task("ending.intent.generate", work_requirements=True)["task"]
    )


@pytest.mark.parametrize(
    "generator",
    [
        "creative.candidates.generate",
        "ending.intent.generate",
        "volume_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    ],
)
def test_work_qualification_cannot_reuse_legacy_profile_receipts(generator):
    current = scripted_qualification(generator, work_requirements=True)
    assert (
        validate_narrative_qualification(
            generator_operation_name=generator, value=current, work_requirements=True
        ).status
        == "PASS"
    )
    with pytest.raises(KernelError, match="NARRATIVE_SEMANTIC_PROFILE_DRIFT"):
        validate_narrative_qualification(
            generator_operation_name=generator, value=current
        )
    legacy = scripted_qualification(generator)
    with pytest.raises(KernelError, match="NARRATIVE_SEMANTIC_PROFILE_DRIFT"):
        validate_narrative_qualification(
            generator_operation_name=generator, value=legacy, work_requirements=True
        )
    failed = deepcopy(current)
    criterion = failed["evaluations"][0]["criteria"][0]
    criterion.update(verdict="FAIL", repair_directive="落实已选择的作品要求")
    with pytest.raises(KernelError, match="NARRATIVE_SEMANTIC_QUALIFICATION_FAILED"):
        validate_narrative_qualification(
            generator_operation_name=generator, value=failed, work_requirements=True
        )


def test_raw_repair_validator_and_final_provider_task_share_frozen_work_contract():
    from novel_forge.modules.story_planning_runtime.result_recovery import validate_raw_result
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    raw = ending_payload()
    raw.pop("foundation_parent_bindings")
    raw.pop("constraint_envelope")
    assert validate_raw_result("ending.intent.generate", raw, work_requirements=True)["protagonist_cost"] is None
    with pytest.raises(KernelError):
        validate_raw_result("ending.intent.generate", raw)
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_INPUT_ROLES
    inputs = {"planning_command": {"planning_scope": "NOT_APPLICABLE", "creative_requirements_contract": "work-requirements.v1"},
              "frozen_inputs": [{"role": role} for role in FOUNDATION_INPUT_ROLES["ending.intent.generate"]],
              "foundation_task": foundation_task("ending.intent.generate", work_requirements=True)}
    current = build_provider_task_view(stage="ending.intent.generate", inputs=inputs)
    assert "open ending" in str(current)
    inputs["foundation_task"] = foundation_task("ending.intent.generate")
    with pytest.raises(KernelError, match="FOUNDATION_PROVIDER_TASK_INVALID"):
        build_provider_task_view(stage="ending.intent.generate", inputs=inputs)


def test_admitted_runtime_continuation_retains_frozen_pack_after_activation_changes(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime import runtime_continuation as runtime
    from novel_forge.modules.story_planning_runtime.application import _command_payload
    from novel_forge.modules.story_planning_runtime.domain import StoryPlanningGenerationCommand
    command = StoryPlanningGenerationCommand(project_id="p", workspace_id="w", book_id="b", actor_id="a",
        generator_operation_name="creative.candidates.generate", logical_key="k", input_versions={"creative_brief": "brief-v"},
        idempotency_key="k", trace_id="t", correlation_id="c", runtime_continuation_id="r", execution_contract_version="1.15.0")
    binding = {"successor_command": _command_payload(command), "target_release_sha": "release",
               "target_runtime": {"pack": "frozen"}, "successor_operation_id": "admitted"}
    monkeypatch.setattr(runtime, "require_binding", lambda *_: binding)
    def changed_activation(*_):
        raise AssertionError("admitted replay must not resolve active Pack")
    monkeypatch.setattr(runtime, "resolve_target", changed_activation)
    application = SimpleNamespace(database_url="offline", commit_sha="release")
    assert runtime.require_successor(application, command) == binding
    binding["successor_operation_id"] = None
    monkeypatch.setattr(runtime, "resolve_target", lambda *_: {"pack": "new"})
    with pytest.raises(KernelError, match="PLANNING_RUNTIME_CONTINUATION_RUNTIME_DRIFT"):
        runtime.require_successor(application, command)


def test_foundation_search_projection_is_optional_and_bound_through_raw_and_host_validation():
    from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_output_schema
    from novel_forge.modules.story_planning_runtime.result_recovery import validate_raw_result
    from tests.integration.synthesis_production_support import SynthesisTransport
    from tests.unit.test_narrative_search_branch_registration import _projection
    generator = "creative.candidates.generate"
    raw = SynthesisTransport().planning(generator, {"foundation_task": {"contract_version": "foundation-generation.v3"}})
    raw["narrative_search_projection"] = _projection("character-motivation", 0.8)
    assert "narrative_search_projection" not in foundation_output_schema(generator)["properties"]
    normalized = validate_raw_result(generator, raw, work_requirements=True, aligned_methods=True, narrative_search=True)
    payload = {**normalized, "foundation_parent_bindings": {}, "constraint_envelope": {
        "contract_version": "foundation-generation.v3", "foundation_parent_bindings": {}, "narrative_search": {"search_id": "native-search"}}}
    validate_foundation_payload(generator, {"candidate_payload": payload})
    with pytest.raises(KernelError, match="OUTPUT_SCHEMA_INVALID"):
        validate_raw_result(generator, raw, work_requirements=True, aligned_methods=True)
    with pytest.raises(ValueError, match="direction selection"):
        foundation_output_schema("character.cast.generate", narrative_search=True)
