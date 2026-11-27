from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.creative_budget_contract import (
    SINGLE_BOOK_PHASES,
    SINGLE_BOOK_VERSION,
    contract_hash,
    validate_comparison_budget,
    validate_policy,
)
from novel_forge.modules.command_kernel.creative_budget_scope import (
    classify_business_scope,
    require_business_scope,
)


def single_book_policy(*, chapter=12, design=True, source=True):
    allocations = {phase.lower() + "_allocation": {"calls": calls, "tokens": calls * 25000}
                   for phase, calls in zip(SINGLE_BOOK_PHASES, (20, 60, 150, 150, 100), strict=True)}
    arm = {"arm": "SINGLE", "project_id": "project-fixture", "book_id": "book-fixture",
           "project_total": {"calls": 480, "tokens": 12000000}, **allocations,
           "chapter_ranges": {"CREATION_EARLY": [1, 6], "CREATION_LATE": [7, 12]}}
    return {"policy_version": "fixture-not-real-authorization-v1",
            "comparison_budget": {"contract_version": SINGLE_BOOK_VERSION, "experiment_id": "same-lifetime-budget",
                                  "accounting_basis": "ACCOUNT_ENTITLEMENT", "shared_total": deepcopy(arm["project_total"]), "arms": [arm]},
            "authorization": {"authorization_ref": "fixture-protocol-only", "evidence_hash": "sha256:" + "a" * 64,
                              "project_id": arm["project_id"], "book_id": arm["book_id"],
                              "authorized_cumulative_caps": {phase: deepcopy(allocations[phase.lower() + "_allocation"]) for phase in SINGLE_BOOK_PHASES},
                              "business_scope": {"source_allowed": source, "design_allowed": design, "max_chapter_number": chapter}}}


def chapter_identity(chapter=1, *, stage="draft", attempt=1):
    operation = {"draft": "chapter.draft.generate", "review": "chapter.review.evaluate", "revision": "chapter.revision.apply", "rereview": "chapter.revision.review"}[stage]
    return {"operation_name": operation, "capability": "model." + stage, "attempt_no": attempt,
            "command_payload": {"payload": {"book_id": "book-fixture", "chapter_number": chapter}},
            "request_payload": {"stage": stage, "input": {}, "_production_execution": {"chapter": chapter, "book_id": "book-fixture"}}}


def planning_identity(*, chapter=None, repair=0, stage=None):
    stage = stage or ("chapter_plan.generate" if chapter else "book_plan.generate")
    generator = "chapter_plan.generate" if stage.startswith("world_candidates.") else stage
    command = {"book_id": "book-fixture", "generator_operation_name": generator, "repair_number": repair,
               "narrative_realization": {"chapter_number": chapter} if chapter else {}}
    payload = {"stage": stage, "input": {"planning_command": deepcopy(command)}}
    if stage.startswith("world_candidates."):
        command["world_preparation_request"] = {"accepted_through_chapter": chapter - 1}
        payload["input"] = {"world_preparation": {"accepted_through_chapter": chapter - 1}}
    return {"operation_name": "story_planning.generate", "capability": "planning.story_chapter.generate" if chapter else "planning.book.generate",
            "attempt_no": 1, "command_payload": {"payload": command}, "request_payload": payload}


def test_single_book_proposal_and_zero_grant_are_separate_from_ab_and_authorization():
    policy = single_book_policy()
    plan = policy["comparison_budget"]
    assert validate_comparison_budget(plan) == plan
    with pytest.raises(ValueError, match="A/B"):
        validate_comparison_budget(plan, require_both_arms=True)
    digest = contract_hash(plan)
    for cap in policy["authorization"]["authorized_cumulative_caps"].values():
        cap.update(calls=0, tokens=0)
    assert validate_policy(policy) == policy
    assert contract_hash(policy["comparison_budget"]) == digest


@pytest.mark.parametrize("mutate", [
    lambda p: p["comparison_budget"]["arms"].append(deepcopy(p["comparison_budget"]["arms"][0])),
    lambda p: p["comparison_budget"]["arms"][0]["chapter_ranges"].update(CREATION_LATE=[6, 12]),
    lambda p: p["comparison_budget"]["arms"][0]["chapter_ranges"].update(CREATION_EARLY=[True, 6]),
    lambda p: p["comparison_budget"]["arms"][0]["creation_early_allocation"].update(calls=151),
    lambda p: p["authorization"]["authorized_cumulative_caps"]["CREATION_LATE"].update(calls=151),
    lambda p: p["authorization"]["business_scope"].update(max_chapter_number=True),
    lambda p: p["authorization"]["business_scope"].update(max_chapter_number=13),
    lambda p: p["authorization"]["business_scope"].update(design_allowed="true"),
])
def test_scope_and_phase_allocations_cannot_be_coerced_or_transferred(mutate):
    policy = single_book_policy()
    mutate(policy)
    with pytest.raises(ValueError):
        validate_policy(policy)


@pytest.mark.parametrize("maximum,chapter,allowed", [(0, 1, False), (1, 1, True), (1, 2, False), (6, 6, True), (6, 7, False), (12, 12, True), (12, 13, False)])
@pytest.mark.parametrize("stage", ["draft", "review", "revision", "rereview"])
def test_native_creative_stages_and_shared_repair_respect_authorized_chapter(maximum, chapter, allowed, stage):
    policy = single_book_policy(chapter=maximum)
    identity = chapter_identity(chapter, stage=stage)
    if allowed:
        scope = classify_business_scope(identity)
        require_business_scope(policy, scope)
        assert scope["origin_phase"] == ("CREATION_EARLY" if chapter <= 6 else "CREATION_LATE")
        assert scope["phase"] == ("REPAIR" if stage in {"revision", "rereview"} else scope["origin_phase"])
    else:
        with pytest.raises(ValueError):
            require_business_scope(policy, classify_business_scope(identity))


def test_design_only_allows_design_repair_but_no_chapter_plan_or_world_call():
    policy = single_book_policy(chapter=0)
    for repair in (0, 1):
        scope = classify_business_scope(planning_identity(repair=repair))
        assert scope["origin_phase"] == "DESIGN"
        require_business_scope(policy, scope)
    for stage in ("chapter_plan.generate", "world_candidates.generate", "world_candidates.evaluate"):
        with pytest.raises(ValueError):
            require_business_scope(policy, classify_business_scope(planning_identity(chapter=1, stage=stage)))


def test_repair_retains_original_phase_and_does_not_expand_business_scope():
    scope = classify_business_scope(planning_identity(chapter=7), dispatch_generation=2)
    assert scope["phase"] == "REPAIR" and scope["origin_phase"] == "CREATION_LATE"
    with pytest.raises(ValueError):
        require_business_scope(single_book_policy(chapter=6), scope)


@pytest.mark.parametrize("mutate", [
    lambda x: x["request_payload"]["_production_execution"].update(chapter=2),
    lambda x: x["request_payload"]["_production_execution"].update(chapter=True),
    lambda x: x["command_payload"]["payload"].update(chapter_number="1"),
    lambda x: x.update(operation_name="chapter.future.generate"),
])
def test_unknown_or_conflicting_frozen_business_identity_fails_before_reservation(mutate):
    identity = chapter_identity()
    mutate(identity)
    with pytest.raises(ValueError):
        classify_business_scope(identity)


def test_semantic_review_cannot_claim_design_when_exact_generation_was_chapter_repair():
    original = planning_identity(chapter=7, repair=1)
    identity = {"operation_name": "story_design.semantic_evaluate", "capability": "model.narrative_semantic_evaluation", "attempt_no": 1,
                "command_payload": {"payload": {"book_id": "book-fixture", "generator_operation_name": "chapter_plan.generate"}},
                "request_payload": {"stage": "narrative_semantic_evaluation", "input": {"evaluation_target": {"generator_operation_name": "chapter_plan.generate"}}},
                "evaluation_origin": {"definition_name": "story_planning.generate", "command_payload": original["command_payload"], "source_ref": "fixture:exact-generation"}}
    scope = classify_business_scope(identity)
    assert scope["phase"] == "REPAIR" and scope["origin_phase"] == "CREATION_LATE"
    with pytest.raises(ValueError):
        require_business_scope(single_book_policy(chapter=0), scope)
    identity.pop("evaluation_origin")
    with pytest.raises(ValueError):
        classify_business_scope(identity)


def test_source_repairs_remain_source_and_require_source_permission():
    identity = {"operation_name": "source.import.mkaos.extract", "capability": "mkaos.knowledge.extract", "attempt_no": 2,
                "command_payload": {"payload": {}}, "request_payload": {"stage": "source.mkaos.extract", "input": {}}}
    scope = classify_business_scope(identity, dispatch_generation=2)
    assert scope["phase"] == scope["origin_phase"] == "SOURCE"
    with pytest.raises(ValueError, match="BUSINESS_SCOPE_DENIED"):
        require_business_scope(single_book_policy(source=False), scope)


def test_each_native_definition_uses_its_supported_strict_schema():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
    from novel_forge.modules.command_kernel.creative_budget_contract import V1_POLICY_SCHEMA, V2_POLICY_SCHEMA
    from tests.unit.test_creative_budget_contract import budget_policy
    for policy, version, schema in ((budget_policy(), "1.1.0", V1_POLICY_SCHEMA), (single_book_policy(), "1.2.0", V2_POLICY_SCHEMA)):
        definition = owned_policy_definition(owner="CREATIVE_EXPERIMENT_BUDGET", content=policy, application_build_id="fixture", commit_sha="a" * 40)
        assert definition["definition_version"] == version
        assert definition["command_schema"]["properties"]["policy"] == schema
        _validate(schema, policy, path="$")
        policy["authorization"]["authorized_cumulative_caps"]["SOURCE"]["calls"] = True
        with pytest.raises(ValueError):
            _validate(schema, policy, path="$")


def test_semantic_book_design_uses_native_outer_book_identity():
    from novel_forge.modules.command_kernel.creative_budget_runtime import _business_scope
    target = {"generation_operation_id": "native-generation", "candidate_asset_version_id": "exact-candidate",
              "candidate_content_hash": "sha256:" + "f" * 64, "generator_operation_name": "book_design.propose"}
    identity = {"operation_name": "story_design.semantic_evaluate", "capability": "model.narrative_semantic_evaluation", "attempt_no": 1,
                "command_payload": {"payload": {"book_id": "book-fixture", **target}},
                "request_payload": {"stage": "narrative_semantic_evaluation", "input": {"evaluation_target": target},
                                    "_production_execution": {"chapter": 0, "generation_operation_id": target["generation_operation_id"],
                                                              "target_asset_version_id": target["candidate_asset_version_id"], "target_content_hash": target["candidate_content_hash"]}}}
    class NativeShapeCursor:
        def execute(self, query, params):
            assert params == ["project-fixture", "native-generation", "exact-candidate"]

        def fetchall(self):
            return [("book_design.propose", {"book_id": "book-fixture", "payload": {"fixture": True}}, target["candidate_content_hash"])]

    actual = _business_scope(NativeShapeCursor(), identity, project_id="project-fixture")
    assert actual["phase"] == "DESIGN" and actual["chapter_number"] == 0
    require_business_scope(single_book_policy(chapter=0), actual)
