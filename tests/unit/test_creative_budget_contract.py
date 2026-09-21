from copy import deepcopy
import hashlib
import json
import re

import pytest

from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
from novel_forge.modules.command_kernel.creative_budget_contract import (
    PAIRED_SAMPLES_VERSION,
    V4_POLICY_SCHEMA,
    POLICY_SCHEMA,
    arm_for_project,
    classify_phase,
    contract_hash,
    validate_comparison_budget,
    validate_policy,
)


def paired_samples_policy():
    policy = budget_policy()
    plan = policy["comparison_budget"]
    plan["contract_version"] = PAIRED_SAMPLES_VERSION
    pair = deepcopy(plan["arms"])
    plan["arms"] = []
    for index in range(8):
        for original in pair:
            arm = deepcopy(original)
            arm.update(sample_id=f"sample-{index}", stage="PILOT" if index < 2 else "EXPLORATION",
                       project_id=original["project_id"] + str(index), book_id=original["book_id"] + str(index))
            arm["qualification_allocation"] = {"calls": 1, "tokens": 1000}
            arm["project_total"] = {key: amount + arm["qualification_allocation"][key] for key, amount in arm["project_total"].items()}
            plan["arms"].append(arm)
    plan["shared_total"] = {key: sum(arm["project_total"][key] for arm in plan["arms"]) for key in ("calls", "tokens")}
    policy["authorization"].update(project_id="project-A0", book_id="book-A0")
    policy["authorization"]["authorized_cumulative_caps"]["QUALIFICATION"] = {"calls": 1, "tokens": 1000}
    return policy


def test_bounded_paired_samples_use_existing_authorization_contract():
    policy = paired_samples_policy()
    _validate(V4_POLICY_SCHEMA, policy, path="$")
    assert validate_policy(policy) == policy
    assert arm_for_project(policy["comparison_budget"], "project-B7")["sample_id"] == "sample-7"
    assert policy["authorization"]["authorized_cumulative_caps"]["CREATION"]["calls"] == 0
    with pytest.raises(ValueError):
        _validate(POLICY_SCHEMA, policy, path="$")


@pytest.mark.parametrize("mutation", [
    lambda p: p["arms"][1].update(project_id=p["arms"][0]["project_id"]),
    lambda p: p["arms"][2].update(book_id=p["arms"][0]["book_id"]),
    lambda p: p["arms"][0].update(stage="EXPLORATION"),
    lambda p: p["arms"].pop(),
    lambda p: p["shared_total"].update(calls=10_000),
    lambda p: p["arms"][1]["creation_allocation"].update(tokens=5000),
    lambda p: p.update(accounting_basis="PRICED"),
])
def test_paired_samples_cannot_share_scope_shift_stage_or_reset_allowance(mutation):
    plan = paired_samples_policy()["comparison_budget"]
    mutation(plan)
    with pytest.raises(ValueError):
        validate_comparison_budget(plan)


def budget_policy():
    arms = [
        {
            "arm": name,
            "project_id": "project-" + name,
            "book_id": "book-" + name,
            "project_total": {"calls": total, "tokens": total * 1000},
            "source_allocation": {"calls": source, "tokens": source * 1000},
            "creation_allocation": {"calls": 10, "tokens": 10000},
            "repair_allocation": {"calls": 2, "tokens": 2000},
        }
        for name, total, source in (("A", 15, 3), ("B", 12, 0))
    ]
    return {
        "policy_version": "operator-grant-v1",
        "comparison_budget": {
            "contract_version": "creative-experiment-budget.v1",
            "experiment_id": "实验-fixture",
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "shared_total": {"calls": 27, "tokens": 27000},
            "arms": arms,
        },
        "authorization": {
            "authorization_ref": "fixture-evidence-only",
            "evidence_hash": "sha256:" + "a" * 64,
            "project_id": "project-A",
            "book_id": "book-A",
            "authorized_cumulative_caps": {
                "SOURCE": {"calls": 1, "tokens": 1000},
                "CREATION": {"calls": 0, "tokens": 0},
                "REPAIR": {"calls": 0, "tokens": 0},
            },
        },
    }


def test_source_only_cumulative_grant_does_not_authorize_creative_opportunity():
    policy = budget_policy()
    _validate(POLICY_SCHEMA, policy, path="$")
    assert validate_policy(policy) == policy
    result = validate_policy(policy)
    result["authorization"]["authorized_cumulative_caps"]["SOURCE"]["calls"] = 0
    assert policy["authorization"]["authorized_cumulative_caps"]["SOURCE"]["calls"] == 1
    assert "execution_authorized" not in result
    assert arm_for_project(policy["comparison_budget"], "project-B")["arm"] == "B"
    with pytest.raises(ValueError, match="project"):
        arm_for_project(policy["comparison_budget"], "foreign-project")


def test_contract_hash_binds_fixed_allocation_not_grant_or_run_key():
    policy = budget_policy()
    plan = policy["comparison_budget"]
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    assert contract_hash(plan) == expected
    policy["policy_version"] = "operator-grant-v2"
    policy["authorization"]["authorized_cumulative_caps"]["SOURCE"]["calls"] = 2
    assert contract_hash(validate_policy(policy)["comparison_budget"]) == expected
    changed = deepcopy(plan)
    changed["experiment_id"] += "-other"
    assert contract_hash(changed) != expected


@pytest.mark.parametrize("bad", [True, False, "1", 1.0, -1, None, float("inf")])
def test_no_numeric_coercion_in_policy_or_schema(bad):
    policy = budget_policy()
    policy["authorization"]["authorized_cumulative_caps"]["SOURCE"]["calls"] = bad
    with pytest.raises(ValueError, match="integer"):
        validate_policy(policy)
    with pytest.raises(ValueError):
        _validate(POLICY_SCHEMA, policy, path="$")


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(run_key="reset-attempt"),
    lambda p: p["authorization"].update(account_entitled=True),
    lambda p: p["authorization"]["authorized_cumulative_caps"].update(UNCLASSIFIED={"calls": 1, "tokens": 1}),
    lambda p: p["comparison_budget"]["arms"][0]["source_allocation"].update(usd="1"),
    lambda p: p["comparison_budget"].pop("arms"),
    lambda p: p["authorization"]["authorized_cumulative_caps"].pop("REPAIR"),
    lambda p: p.update(policy_version=""),
])
def test_schema_and_policy_reject_unbound_or_incomplete_fields(mutate):
    policy = budget_policy()
    mutate(policy)
    with pytest.raises(ValueError):
        _validate(POLICY_SCHEMA, policy, path="$")
    with pytest.raises(ValueError):
        validate_policy(policy)


def test_authorization_requires_exact_evidence_hash():
    policy = budget_policy()
    policy["authorization"]["evidence_hash"] = "sha256:not-a-digest"
    with pytest.raises(ValueError, match="evidence_hash"):
        validate_policy(policy)
    field = POLICY_SCHEMA["properties"]["authorization"]["properties"]["evidence_hash"]
    assert re.fullmatch(field["pattern"], policy["authorization"]["evidence_hash"]) is None


@pytest.mark.parametrize("invalid", [[], {}, None])
def test_untyped_accounting_basis_is_a_contract_rejection(invalid):
    policy = budget_policy()
    policy["comparison_budget"]["accounting_basis"] = invalid
    with pytest.raises(ValueError):
        validate_policy(policy)


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p["authorization"].update(book_id="book-B"), "scope"),
    (lambda p: p["authorization"]["authorized_cumulative_caps"]["SOURCE"].update(calls=4), "opportunity"),
    (lambda p: p["comparison_budget"]["arms"][0]["project_total"].update(calls=14), "frozen"),
    (lambda p: p["comparison_budget"]["shared_total"].update(tokens=26000), "shared"),
    (lambda p: p["comparison_budget"]["arms"][1]["source_allocation"].update(calls=1, tokens=1000), "control"),
    (lambda p: p["comparison_budget"]["arms"][1].update(project_id="project-A"), "independent"),
    (lambda p: p["comparison_budget"]["arms"][1].update(book_id="book-A"), "independent"),
])
def test_native_policy_checks_scope_and_fixed_totals(mutate, match):
    policy = budget_policy()
    mutate(policy)
    with pytest.raises(ValueError, match=match):
        validate_policy(policy)


@pytest.mark.parametrize("phase", ["creation_allocation", "repair_allocation"])
def test_each_creative_phase_has_equal_frozen_opportunity(phase):
    policy = budget_policy()
    other = policy["comparison_budget"]["arms"][1]
    other[phase]["calls"] -= 1
    other["project_total"]["calls"] -= 1
    with pytest.raises(ValueError, match="creative opportunity"):
        validate_policy(policy)


def test_preparation_plan_can_be_a_only_but_priced_cannot_be_native_stage_policy():
    policy = budget_policy()
    policy["comparison_budget"]["arms"] = policy["comparison_budget"]["arms"][:1]
    assert validate_policy(policy) == policy
    with pytest.raises(ValueError, match="both A/B"):
        validate_comparison_budget(policy["comparison_budget"], require_both_arms=True)
    policy["comparison_budget"]["accounting_basis"] = "PRICED"
    assert validate_comparison_budget(policy["comparison_budget"])
    with pytest.raises(ValueError, match="ACCOUNT_ENTITLEMENT"):
        validate_policy(policy)
    with pytest.raises(ValueError):
        _validate(POLICY_SCHEMA, policy, path="$")


@pytest.mark.parametrize("operation,capability,stage", [
    ("source.import.document.profile", "source.content.classify", "source.content.classify"),
    ("source.import.deconstruction.execute", "deconstruction.observe", "source.deconstruction.observe"),
    ("source.import.mkaos.extract", "mkaos.knowledge.extract", "source.mkaos.extract"),
    ("source.import.reprocessing.apply", "mkaos.rule.extract", "source.mkaos.extract"),
    ("provider.qualification.d0", "mkaos.template.extract", "d0_qualification"),
])
def test_source_including_repairs_and_d0_stays_in_source(operation, capability, stage):
    payload = {"stage": stage, "input": {"repair_round": 2}}
    assert classify_phase(operation, capability, payload, 1) == "SOURCE"
    assert classify_phase(operation, capability, payload, 3) == "SOURCE"


@pytest.mark.parametrize("operation,stage,phase", [
    ("chapter.memo.generate", "memo", "CREATION"),
    ("chapter.context.retrieve", "retrieval", "CREATION"),
    ("chapter.draft.generate", "draft", "CREATION"),
    ("chapter.review.evaluate", "review", "CREATION"),
    ("chapter.revision.apply", "revision", "REPAIR"),
    ("chapter.revision.review", "rereview", "REPAIR"),
    ("chapter.canon.extract", "canon_extraction", "CREATION"),
    ("chapter.canon.propose_changes", "canon_support", "CREATION"),
    ("chapter.quality.source_originality.evaluate", "quality_source_originality", "CREATION"),
    ("reader_outcome.evaluate", "reader_outcome", "CREATION"),
    ("story_design.semantic_evaluate", "narrative_semantic_evaluation", "CREATION"),
])
def test_explicit_creative_operations_and_exact_extra_attempt(operation, stage, phase):
    payload = {"stage": stage, "input": {}}
    assert classify_phase(operation, "model." + stage, payload, 1) == phase
    assert classify_phase(operation, "model." + stage, payload, 2) == "REPAIR"


@pytest.mark.parametrize("stage,capability", [
    ("creative.candidates.generate", "creative.proposal.generate"),
    ("theme.candidates.generate", "theme.question.generate"),
    ("book_plan.generate", "planning.book.generate"),
    ("chapter_plan.generate", "planning.story_chapter.generate"),
])
def test_planning_uses_actual_generic_operation_and_frozen_repair(stage, capability):
    payload = {"stage": stage, "input": {"planning_command": {"repair_number": 0}}}
    assert classify_phase("story_planning.generate", capability, payload, 1) == "CREATION"
    payload["input"]["planning_command"]["repair_number"] = 1
    assert classify_phase("story_planning.generate", capability, payload, 1) == "REPAIR"


@pytest.mark.parametrize("stage", ["world_candidates.generate", "world_candidates.evaluate"])
def test_world_preparation_uses_same_planning_effect_identity(stage):
    payload = {"stage": stage, "input": {"world_preparation": {"role": "WORLD_REASONER"}}}
    assert classify_phase("story_planning.generate", "planning.story_chapter.generate", payload, 1) == "CREATION"
    assert classify_phase("story_planning.generate", "planning.story_chapter.generate", payload, 2) == "REPAIR"


@pytest.mark.parametrize("operation,capability,payload,attempt", [
    ("chapter.unknown", "model.draft", {"stage": "draft", "input": {}}, 2),
    ("chapter.review.evaluate", "model.revision", {"stage": "revision", "input": {}}, 1),
    ("source.import.mkaos.extract", "model.draft", {"stage": "draft", "input": {}}, 1),
    ("chapter.quality.source_originality.evaluate", "mkaos.knowledge.extract", {"stage": "source.mkaos.extract", "input": {}}, 1),
    ("story_planning.generate", "planning.book.generate", {"stage": "chapter_plan.generate", "input": {}}, 1),
    ("story_planning.generate", "planning.book.generate", {"stage": "world_candidates.generate", "input": {"world_preparation": {}}}, 1),
    ("story_planning.generate", "planning.book.generate", {"stage": "book_plan.generate", "input": {}}, 1),
    ("story_planning.generate", "planning.book.generate", {"stage": "book_plan.generate", "input": {"planning_command": {"repair_number": True}}}, 1),
    ("story_planning.generate", "planning.book.generate", {"stage": "book_plan.generate", "input": {"planning_command": {"repair_number": "1"}}}, 1),
    ("chapter.draft.generate", "model.draft", {"stage": "draft", "input": {}}, True),
    ("chapter.draft.generate", "model.draft", {"stage": "draft", "input": {}}, 0),
    ("chapter.draft.generate", "model.draft", {}, 1),
])
def test_unknown_or_inconsistent_effect_identity_never_defaults_to_a_phase(operation, capability, payload, attempt):
    with pytest.raises(ValueError):
        classify_phase(operation, capability, payload, attempt)
