from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_context_projection import project_book_method_scope
from novel_forge.modules.mkaos_authority.craft_selection import _hash
from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references, expand_exact_context_references


def selection():
    need = {"hard_constraints": ["Retain author commitments"], "craft_context": {"query": "recall only"},
            "recent_craft_usage": [{"evidence": "working original"}], "required_card_asset_version_ids": ["method:v1"]}
    need["need_digest"] = _hash(need)
    source = {"schema_version": "mkaos-narrative-intelligence-selection.v1", "need": need,
              "knowledge_access_policy": {"mode": "ALLOW_ONLY", "usage_scope": "EXPERIMENTAL_VALIDATION",
                                          "craft_candidate_review_version": "explicit-allowlist-craft-review.v1"},
              "selected": [{"selected_content": {"mechanism": "Purpose precedes choice", "exceptions": ["Intentional ambiguity"]},
                            "applicability_assessment": {"status": "UNKNOWN", "unmet_prerequisites": ["Current information"]},
                            "craft_assessment": {"matching_assessment": {"score": 0}, "budget_assessment": {"working_allocation_history": [{"draft": "original:v1"}]}}}]}
    source["selection_digest"] = _hash(source)
    return source


def test_book_scope_preserves_current_methods_constraints_and_working_history():
    source = selection()
    original = deepcopy(source)
    result = project_book_method_scope(source)
    assert source == original
    assert result["selected"][0]["selected_content"] == original["selected"][0]["selected_content"]
    assert result["selected"][0]["applicability_assessment"] == original["selected"][0]["applicability_assessment"]
    assert result["selected"][0]["craft_assessment"]["budget_assessment"] == original["selected"][0]["craft_assessment"]["budget_assessment"]
    assert result["need"]["hard_constraints"] == source["need"]["hard_constraints"]
    assert result["need"]["recent_craft_usage"] == source["need"]["recent_craft_usage"]
    assert "craft_context" not in result["need"]
    assert result["recall_query_receipt"]["source_selection_digest"] == source["selection_digest"]


@pytest.mark.parametrize("field,value", [("mode", "DENY_ALL"), ("usage_scope", "PRODUCTION"), ("craft_candidate_review_version", "different")])
def test_book_scope_cannot_leak_into_other_knowledge_policies(field, value):
    source = selection()
    source["knowledge_access_policy"][field] = value
    source["selection_digest"] = _hash({k:v for k,v in source.items() if k != "selection_digest"})
    with pytest.raises(KernelError, match="CRAFT_CONTEXT_PROJECTION_DRIFT"):
        project_book_method_scope(source)


def test_short_literal_transport_is_lossless_and_legacy_encoding_stays_separate():
    literal = "A repeated short narrative condition. " * 4
    data = {"a": literal, "b": literal, "c": {"long_pointer_name" * 9: literal}}
    legacy, old_proof = compile_exact_context_references(data, structured_transport=True)
    projected, proof = compile_exact_context_references(data, structured_transport=True, short_literals=True)
    assert expand_exact_context_references(projected) == data
    assert legacy == data
    assert projected != legacy
    assert old_proof["transport_version"] == "provider-structured-exact-reference.v1"
    assert proof["transport_version"] == "provider-structured-exact-reference.v3"


def group_selection():
    source = selection()
    source["selected"][0]["applicability_assessment"].update(
        hard_constraints=deepcopy(source["need"]["hard_constraints"]),
        hard_constraint_semantics="UNVERIFIED_EXCEPT_EXPLICIT_TYPED_CHECKS",
        checks=[{"method": "SEMANTIC_UNVERIFIED", "result": "UNKNOWN", "statement": "A current objective exists"}],
    )
    source["selection_digest"] = _hash({k: v for k, v in source.items() if k != "selection_digest"})
    return source


def test_group_scope_references_only_unverified_flattened_query_and_retains_conditions():
    from novel_forge.modules.mkaos_authority.craft_context_projection import project_group_method_scope
    source = group_selection()
    frozen = deepcopy(source)
    projected = project_group_method_scope(source)
    assert source == frozen
    assert "hard_constraints" not in projected["need"]
    original_card, card = source["selected"][0], projected["selected"][0]
    assert card["selected_content"] == original_card["selected_content"]
    assert card["applicability_assessment"] == {k: v for k, v in original_card["applicability_assessment"].items() if k != "hard_constraints"}
    assert projected["need"]["recent_craft_usage"] == source["need"]["recent_craft_usage"]
    assert card["craft_assessment"]["budget_assessment"] == original_card["craft_assessment"]["budget_assessment"]
    assert projected["recall_query_receipt"]["flattened_constraint_query"]["content_hash"] == _hash(source["need"]["hard_constraints"])
    assert project_book_method_scope(source)["need"]["hard_constraints"] == source["need"]["hard_constraints"]


@pytest.mark.parametrize("mutation", ["typed_check", "different_query", "different_semantics"])
def test_group_scope_never_discards_explicit_constraint_checks_or_unmatched_queries(mutation):
    from novel_forge.modules.mkaos_authority.craft_context_projection import project_group_method_scope
    source = group_selection()
    assessment = source["selected"][0]["applicability_assessment"]
    if mutation == "typed_check":
        assessment["checks"].append({"method": "EXPLICIT_TYPED_CHECK", "result": "PASS"})
    elif mutation == "different_query":
        assessment["hard_constraints"].append("A distinct condition")
    else:
        assessment["hard_constraint_semantics"] = "AUTHOR_REQUIREMENTS"
    source["selection_digest"] = _hash({k: v for k, v in source.items() if k != "selection_digest"})
    projected = project_group_method_scope(source)
    assert projected["need"]["hard_constraints"] == source["need"]["hard_constraints"]
    assert projected["selected"][0]["applicability_assessment"] == assessment
    assert "flattened_constraint_query" not in projected["recall_query_receipt"]


@pytest.mark.parametrize("chapter,role,generator", [(False,"related_arc:1","arc_plan.generate"),
    (True,"related_arc:1","arc_plan.generate"), (True,"chapter_group_plan","chapter_group_plan.generate")])
def test_group_upstream_audit_reference_preserves_all_plan_constraints_and_failed_candidate(chapter, role, generator):
    from novel_forge.modules.chapter_authority.provider_views import _reference_prior_planning_method_audits
    translations = [{"knowledge_card_asset_version_id": "method:v1", "content_hash": "sha256:method", "decision": "ADAPT", "use_sites": [{"target_pointer": "/objective", "realization_excerpt": "A local objective"}], "rationale": "Prior stage only"}]
    content = {"generator_operation_name": generator, "book_id": "book:one", "knowledge_translations": translations, "hard_constraints": ["Keep actual condition"], "forbidden_events": ["No invented knowledge"]}
    segment = {"role": role, "asset_type": "planning_generation_candidate", "asset_version_id": "arc:v1", "content_hash": "sha256:arc", "content": deepcopy(content)}
    view = {"narrative_position": {"book_id": "book:one"}, "segments": [deepcopy(segment)], "repair_context": {"source_candidate": {"content": deepcopy(content)}}, "selection_explanation": {"loss_records": [], "omitted_item_count": 0}}
    failed = deepcopy(view["repair_context"])
    _reference_prior_planning_method_audits(view, sources=[segment], chapter=chapter)
    projected = view["segments"][0]["content"]
    assert projected["hard_constraints"] == content["hard_constraints"]
    assert projected["forbidden_events"] == content["forbidden_events"]
    assert projected["prior_method_decisions"][0]["decision"] == "ADAPT"
    assert view["repair_context"] == failed
    assert segment["content"] == content
    assert view["selection_explanation"]["loss_records"][0]["removed_value_hash"] == _hash(translations)


def test_group_forward_guard_retains_every_historical_branch():
    from novel_forge.storage.migrations.versions.v20261014_0208_book_method_scope_context import UPGRADE_STATEMENTS as old
    from novel_forge.storage.migrations.versions.v20261014_0212_group_method_scope_context import UPGRADE_STATEMENTS as new
    assert old[0].removesuffix(" $$") + " OR " in new[0]
    assert "AND attempt.result->>'error_message'='CONTEXT_CAPACITY_EXCEEDED: Complete input leaves no model context for generation'" in new[0]
    assert "output_key<>'planning.context_bundle'" in new[0]
    assert "context.content #>> '{repair_context,source_candidate,asset_version_id}'=r.source_command->>'repair_of_candidate_id'" in new[0]


def test_group_reprojection_requires_the_explicit_registered_contract():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    source = {"input_versions": [], "narrative_intelligence": group_selection(), "repair_context": {"source_candidate": {"content": {"narrative_event_chain": "exact rejected chain"}}}}
    source["knowledge_access_policy"] = deepcopy(source["narrative_intelligence"]["knowledge_access_policy"])
    frozen = deepcopy(source)
    command = SimpleNamespace(generator_operation_name="chapter_group_plan.generate", narrative_search_id="search:one", execution_contract_version="1.21.0")
    port = SimpleNamespace(_planning_context_manifest=lambda **kwargs: {"token_accounting": {"accepted_tokens": 100}})
    old = PostgresPlanningExecutionPreparer._reproject_frozen_context(port, source, command=command, task_tokens=1000, projection_contract="typed-planning-window-projection.v1")
    new = PostgresPlanningExecutionPreparer._reproject_frozen_context(port, source, command=command, task_tokens=1000, projection_contract="group-method-scope-projection.v1")
    assert "planning_group_method_scope_projection_version" not in old
    assert new["planning_group_method_scope_projection_version"] == "group-method-scope-projection.v1"
    assert new["repair_context"] == old["repair_context"] == source["repair_context"]
    assert source == frozen


def test_explicit_world_scope_retains_two_arcs_and_legacy_view():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    source = group_selection()
    task = {"contract_version": "world-provider-task.v1", "role": "WORLD_REASONER", "fact_mutation_allowed": False,
            "source_ref": {"asset_version_id": "world:v1", "content_hash": "sha256:world"},
            "narrative_intelligence": source, "planning_window": []}
    for index, decision in enumerate(("ADAPT", "REJECT")):
        task["planning_window"].append({"role": "arc_plans", "asset_version_id": f"arc:{index}",
            "content_hash": f"sha256:arc{index}", "content": {"hard_constraints": [f"Condition {index}"],
            "knowledge_translations": [{"knowledge_card_asset_version_id": "method:v1", "content_hash": "sha256:method",
                "decision": decision, "rationale": f"Prior rationale {index}", "use_sites": []}]}})
    frozen = deepcopy(task)
    legacy = build_provider_task_view("world_candidates.generate", {"world_preparation": task})["world_preparation"]
    assert legacy == frozen
    task["world_method_scope_projection_version"] = "world-method-scope-projection.v1"
    projected = build_provider_task_view("world_candidates.generate", {"world_preparation": task})["world_preparation"]
    assert build_provider_task_view("world_candidates.generate", {"world_preparation": projected})["world_preparation"] == projected
    for index, segment in enumerate(projected["planning_window"]):
        assert segment["content"]["hard_constraints"] == frozen["planning_window"][index]["content"]["hard_constraints"]
        assert segment["prior_method_audit_receipt"]["plan_asset_version_id"] == f"arc:{index}"
        assert segment["prior_method_audit_receipt"]["json_pointer"] == f"/contract/planning_window/{index}/content/knowledge_translations"
        assert segment["content"]["prior_method_decisions"][0]["decision"] == ("ADAPT", "REJECT")[index]
    assert projected["narrative_intelligence"]["selected"][0]["selected_content"] == source["selected"][0]["selected_content"]
    assert "hard_constraints" not in projected["narrative_intelligence"]["need"]
    source["selected"][0]["applicability_assessment"]["checks"].append({"method": "EXPLICIT_TYPED_CHECK", "result": "PASS"})
    source["selection_digest"] = _hash({k: v for k, v in source.items() if k != "selection_digest"})
    protected = build_provider_task_view("world_candidates.generate", {"world_preparation": task})["world_preparation"]
    assert protected["narrative_intelligence"]["need"]["hard_constraints"] == source["need"]["hard_constraints"]


@pytest.mark.parametrize("change", ["authorization", "model", "cli_directory"])
def test_world_recovery_retains_exact_runtime_allowing_only_budget_authorization(change):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.world_context_recovery import require_runtime_identity
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    prior = {"model_provider": "codex-cli", "model_id": "same-model", "reasoning_effort": "high",
             "model_backend_id": "same-backend", "runtime_class": "SUBSCRIPTION_CLI",
             "cost_accounting_basis": "ACCOUNT_ENTITLEMENT",
             "account": {"cli_directory": "/original", "entitlement": {"authorization_ref": "old", "account_identity": "same"}}}
    source = {"source_operation_id": "stopped", "context_revalidation": {
        "prior_runtime_continuation_id": "original", "prior_runtime_hash": canonical_hash(prior)}}
    uow = SimpleNamespace(cursor=SimpleNamespace(execute=lambda *args: None, fetchone=lambda: (prior,)))
    target = deepcopy(prior)
    if change == "authorization":
        target["account"]["entitlement"]["authorization_ref"] = "new-approved"
        assert require_runtime_identity(uow, source=source, target=target)["authorization_reference_change"] == "NATIVE_BUDGET_SUCCESSOR_ALLOWED"
    else:
        if change == "model":
            target["model_id"] = "different-model"
        else:
            target["account"]["cli_directory"] = "/different"
        with pytest.raises(KernelError, match="WORLD_CONTEXT_RECOVERY_RUNTIME_DRIFT"):
            require_runtime_identity(uow, source=source, target=target)


def test_chapter_scope_is_explicit_and_rejects_another_stage():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    source = {"input_versions": [], "narrative_intelligence": group_selection(), "planning_scope": "CHAPTER",
              "arc_working_set": {"working_manuscript": {"snapshot_hash": "original"}}}
    source["knowledge_access_policy"] = deepcopy(source["narrative_intelligence"]["knowledge_access_policy"])
    frozen = deepcopy(source)
    command = SimpleNamespace(generator_operation_name="chapter_plan.generate", execution_contract_version="1.21.0")
    port = SimpleNamespace(_planning_context_manifest=lambda **kwargs: {"token_accounting": {"accepted_tokens": 100}})
    legacy = PostgresPlanningExecutionPreparer._reproject_frozen_context(port, source, command=command, task_tokens=1000)
    projected = PostgresPlanningExecutionPreparer._reproject_frozen_context(port, source, command=command,
        task_tokens=1000, projection_contract="chapter-method-scope-projection.v1")
    assert "planning_chapter_method_scope_projection_version" not in legacy
    assert projected["narrative_intelligence"] == frozen["narrative_intelligence"]
    assert projected["arc_working_set"] == frozen["arc_working_set"]
    assert source == frozen
    command.generator_operation_name = "book_plan.generate"
    with pytest.raises(KernelError, match="CRAFT_CONTEXT_PROJECTION_DRIFT"):
        PostgresPlanningExecutionPreparer._reproject_frozen_context(port, source, command=command,
            task_tokens=1000, projection_contract="chapter-method-scope-projection.v1")


@pytest.mark.parametrize("mutation", [None, "baseline", "production", "old_contract", "another_stage", "empty"])
def test_fresh_chapter_scope_requires_its_exact_experimental_policy(mutation):
    from novel_forge.modules.mkaos_authority.craft_context_projection import experimental_chapter_method_scope
    source = group_selection()
    policy = deepcopy(source["knowledge_access_policy"])
    generator, version = "chapter_plan.generate", "1.21.0"
    if mutation == "baseline":
        policy["mode"] = "DENY_ALL"
    if mutation == "production":
        policy["usage_scope"] = "PRODUCTION"
    if mutation == "old_contract":
        version = "1.20.0"
    if mutation == "another_stage":
        generator = "book_plan.generate"
    if mutation == "empty":
        source["selected"] = []
    frozen = deepcopy(source)
    result = experimental_chapter_method_scope(generator=generator, contract_version=version, selection=source, policy=policy)
    assert source == frozen
    assert bool(result) is (mutation is None)
    if result:
        assert result["planning_chapter_method_scope_projection_version"] == "chapter-method-scope-projection.v1"
        assert result["world_method_scope_projection_version"] == "world-method-scope-projection.v1"
