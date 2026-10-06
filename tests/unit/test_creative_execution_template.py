from dataclasses import replace
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter, PricingSnapshot
from novel_forge.modules.production_execution.execution_template import template_decision, validate_templates
from novel_forge.modules.production_execution.membership_identity import observe_membership_identity, require_membership_identity
from tests.unit.test_cost_aware_routing import NOW, candidate, task


def template(book="book", paid=None, **changes):
    return {"version": "creative-execution-template.v1", "book_id": book,
            "mode": "CREATIVE_VALIDATION", "allowed_candidates": ["member", "flash"],
            "member_authorization_ref": "member-grant", "deepseek": paid,
            "optional_enhancements": [], "require_literary_qualification": False,
            "require_independent_review": False, "require_pack_human_approval": False, **changes}


def membership():
    return replace(candidate("member"), provider="codex-cli", quota_remaining=None,
                   authorization_ref="member-grant", entitlement_role="PRIMARY",
                   authorized_tasks=("classification",), model_revision="model-v1",
                   pricing=PricingSnapshot("capability-v1", "2026-01-01T00:00:00+00:00",
                                           "2027-01-01T00:00:00+00:00", "0", "0", "0",
                                           currency="UNKNOWN", source="member-grant",
                                           accounting_basis="ACCOUNT_ENTITLEMENT"))


def test_membership_cold_start_has_no_cumulative_budget_but_no_literary_pass():
    t = task(remaining_tokens=0, remaining_money="0", policy_snapshot={"policy": {
        "execution_templates": [template()]}}, budget_snapshot={"candidates": {
        "member": {"resource_control_version": "billing-channel-resources.v1",
                   "remaining_tokens": 100000, "remaining_money": None}}})
    strict = CostAwareRouter().explain(t, [membership()], {}, now=NOW)
    assert strict.to_dict()["status"] == "BLOCKED"
    result = template_decision(strict).to_dict()
    assert result["status"] == "SELECTED"
    assert result["checks"]["literary_model_qualification"]["status"] == "NOT_RUN"
    assert result["independent_qualification_eligible"] is False
    assert result["strict_certification_eligible"] is False


@pytest.mark.parametrize("requirement", ["PROVIDER_TASK_NOT_AUTHORIZED", "CAPABILITY_UNSUPPORTED",
                                       "CONTEXT_CAPACITY_EXCEEDED", "RECONCILIATION_OR_POLICY_RESOLUTION_REQUIRED"])
def test_validation_retains_execution_and_security_rejections(requirement):
    changes = {
        "PROVIDER_TASK_NOT_AUTHORIZED": {"declared_requirements": {"provider_task_scope": {"codex-cli": []}}},
        "CAPABILITY_UNSUPPORTED": {"required_capabilities": ("external_tool",)},
        "CONTEXT_CAPACITY_EXCEEDED": {"input_tokens": 200000},
        "RECONCILIATION_OR_POLICY_RESOLUTION_REQUIRED": {"history": ({"failure_class": "UNKNOWN_EXTERNAL_OUTCOME"},)},
    }[requirement]
    t = task(policy_snapshot={"policy": {"execution_templates": [template()]}}, **changes)
    result = template_decision(CostAwareRouter().explain(t, [membership()], {}, now=NOW)).to_dict()
    assert result["status"] == "BLOCKED"
    assert requirement in result["candidates"][0]["rejected_reasons"]


def test_missing_paid_template_disables_only_paid_channel():
    t = task(policy_snapshot={"policy": {"execution_templates": [template()]}},
             budget_snapshot={"candidates": {
                 "member": {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000, "remaining_money": None},
                 "flash": {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000, "remaining_money": "0", "paid_authorized": False}}})
    result = template_decision(CostAwareRouter().explain(t, [candidate(), membership()], {}, now=NOW)).to_dict()
    assert result["selected"]["candidate"]["provider"] == "codex-cli"
    assert "PAID_TEMPLATE_AUTHORIZATION_REQUIRED" in result["candidates"][0]["rejected_reasons"]


def test_strict_template_never_relaxes_missing_qualification():
    value = template(mode="STRICT_PRODUCTION", require_literary_qualification=True)
    validate_templates({"execution_templates": [value]})
    t = task(policy_snapshot={"policy": {"execution_templates": [value]}})
    assert template_decision(CostAwareRouter().explain(t, [membership()], {}, now=NOW)).to_dict()["status"] == "BLOCKED"
    with pytest.raises(KernelError, match="STRICT_TEMPLATE_QUALIFICATION_REQUIRED"):
        validate_templates({"execution_templates": [template(mode="STRICT_PRODUCTION")]})


def test_membership_identity_is_authentication_based_and_detects_account_switch(tmp_path):
    auth = {"auth_mode": "chatgpt", "tokens": {"account_id": "account-a", "access_token": "fixture", "refresh_token": "fixture"}}
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    identity = observe_membership_identity(str(tmp_path))
    assert "fixture" not in json.dumps(identity)
    auth["tokens"]["account_id"] = "account-b"
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    with pytest.raises(ValueError, match="IDENTITY_DRIFT"):
        require_membership_identity(str(tmp_path), identity)
    auth["auth_mode"] = "apikey"
    (tmp_path / "auth.json").write_text(json.dumps(auth))
    with pytest.raises(ValueError, match="MEMBERSHIP_AUTH_REQUIRED"):
        observe_membership_identity(str(tmp_path))


def test_membership_preflight_does_not_request_cumulative_budget_configuration(tmp_path):
    import sys
    from novel_forge.modules.production_execution.codex_configuration import inspect_local_codex
    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
        "account_id": "fixture-account", "access_token": "secret-fixture", "refresh_token": "secret-fixture"}}))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = inspect_local_codex({"NOVEL_FORGE_RESOURCE_CONTROL_VERSION": "billing-channel-resources.v1",
        "NOVEL_FORGE_CODEX_HOME": str(tmp_path), "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
        "NOVEL_FORGE_CODEX_EXECUTABLE": sys.executable, "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(tmp_path / "executions"),
        "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF": observe_membership_identity(str(tmp_path))["account_ref"]})
    assert not any("PROJECT_PROVIDER" in name for name in report["missing_configuration"])
    assert report["model_calls"] == 0 and report["credentials_inspected"] is True
    assert "secret-fixture" not in json.dumps(report)


def test_membership_opening_has_workload_without_cumulative_capacity():
    from novel_forge.modules.command_kernel.budget_runtime import canonical_budget_policy, next_provider_budget_allowance
    from novel_forge.modules.book_authority.opening_workflow import assess_book_opening_topology_budget

    policy = canonical_budget_policy({"resource_control_version": "billing-channel-resources.v1", "execution_mode": "PROVIDER_ALLOWED",
        "accounting_basis": "ACCOUNT_ENTITLEMENT", "authorization_ref": "member-grant", "cost_observability": "UNKNOWN", "per_call_token_limit": 100000})
    allowance = next_provider_budget_allowance(policy["policy_snapshot"])
    assert allowance["requested_amount"] is None
    topology = assess_book_opening_topology_budget(policy_contract_version="book-opening-provider-budget.v2", policy_hash=policy["policy_hash"], policy=policy["policy_snapshot"], arc_count=50)
    assert topology.max_volume_count is None and topology.provider_call_capacity is None
    topology.require_volume_count(10000)
    with pytest.raises(KernelError):
        canonical_budget_policy({**policy["policy_snapshot"], "token_limit": 1000000})


@pytest.mark.parametrize("remaining", ["0", "0.01"])
def test_paid_completion_pressure_routes_to_member_and_never_changes_goal(remaining):
    paid = {"account_ref": "account", "currency": "USD", "maximum_amount": "1", "authorization_ref": "paid"}
    t = task(policy_snapshot={"policy": {"execution_templates": [template(paid=paid)]}},
        budget_snapshot={"work_resource_plan": {"provider_calls_range": [10, 28], "deepseek": {
            "remaining_amount": remaining, "remaining_cost_range": ["0.02", "0.06"]}},
            "candidates": {"member": {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000, "remaining_money": None},
                           "flash": {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000, "remaining_money": remaining, "paid_authorized": True}}})
    result = template_decision(CostAwareRouter().explain(t, [candidate(), membership()], {}, now=NOW)).to_dict()
    assert result["selected"]["candidate"]["provider"] == "codex-cli"
    assert result["resource_actions"]["paid_completion_pressure"]
    assert not result["resource_actions"]["work_scope_changed"] and not result["resource_actions"]["quality_floor_changed"]


def test_validation_preserves_explicit_cross_provider_independence():
    t = task(policy_snapshot={"policy": {"execution_templates": [template(require_independent_review=True)]}},
        declared_requirements={"cross_model_review": {"schema_version": "cross-model-review.v1",
            "generator": {"provider": "codex-cli", "model": "member", "model_revision": "model-v1"},
            "required_reviewer_provider": "deepseek", "target_content_hash": "sha256:" + "a" * 64}},
        budget_snapshot={"candidates": {"member": {"resource_control_version": "billing-channel-resources.v1", "remaining_tokens": 100000, "remaining_money": None}}})
    result = template_decision(CostAwareRouter().explain(t, [membership()], {}, now=NOW)).to_dict()
    assert result["status"] == "BLOCKED"
    assert "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED" in result["candidates"][0]["rejected_reasons"]


def test_inherited_paid_configuration_is_closed_and_missing_configuration_disables_only_paid(tmp_path):
    from novel_forge.modules.production_execution.execution_template import load_paid_configuration
    values = {"NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE": str(tmp_path / "paid.json"),
              "NOVEL_FORGE_DEEPSEEK_BILLING_ACCOUNT_REF": "actual-configured-account"}
    assert load_paid_configuration(values)[0] is None
    paid = {"account_ref": "actual-configured-account", "currency": "USD", "maximum_amount": "2",
            "authorization_ref": "existing-paid-grant"}
    (tmp_path / "paid.json").write_text(json.dumps(paid))
    assert load_paid_configuration(values) == (paid, "")
    paid["currency"] = "CNY"
    (tmp_path / "paid.json").write_text(json.dumps(paid))
    assert load_paid_configuration(values)[1] == "PAID_TEMPLATE_UNAVAILABLE_OR_INVALID"


def test_v3_world_policy_is_explicit_and_strict_requires_simulation():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    repair = {"version": "native-repair-routing.v1", "max_same_route_repairs": 2}
    value = template(version="creative-execution-template.v3", repair_routing=repair, world_future_preparation="DISABLED")
    validate_templates({"execution_templates": [value]})
    definition = owned_policy_definition(owner="PROVIDER_ROUTING", content={"execution_templates": [value]},
        application_build_id="fixture", commit_sha="a"*40)
    assert definition["definition_version"] == "1.8.0"
    previous = template(version="creative-execution-template.v2", repair_routing=repair)
    assert owned_policy_definition(owner="PROVIDER_ROUTING", content={"execution_templates": [previous]},
        application_build_id="fixture", commit_sha="a"*40)["definition_version"] == "1.7.0"
    with pytest.raises(KernelError):
        validate_templates({"execution_templates": [{k:v for k,v in value.items() if k != "world_future_preparation"}]})
    with pytest.raises(KernelError):
        validate_templates({"execution_templates": [{**value, "mode":"STRICT_PRODUCTION", "require_literary_qualification":True}]})
    validate_templates({"execution_templates": [{**value, "mode":"STRICT_PRODUCTION",
        "require_literary_qualification":True, "world_future_preparation":"REQUIRED"}]})


@pytest.mark.parametrize("field", ["actor_experiment", "preparation_sources"])
def test_optional_world_policy_cannot_defer_independent_or_accepted_commitments(field):
    from novel_forge.modules.story_planning_runtime.world_optional import require_optional_source
    require_optional_source({"actor_experiment":None, "preparation_sources":[]})
    with pytest.raises(KernelError, match="WORLD_OPTIONAL_DEFERRAL_DEPENDENCY_REQUIRED"):
        require_optional_source({field: ["required"]})


def test_execution_window_recovery_is_explicit_creative_v5_only():
    value = template(version='creative-execution-template.v5',world_future_preparation='DISABLED',
        repair_routing={'version':'native-repair-routing.v2','max_same_route_repairs':2},
        chapter_contract_recovery='KNOWN_SETTLED_CONTRACT_REPAIR')
    validate_templates({'execution_templates':[value]})
    value['version'] = 'creative-execution-template.v4'
    with pytest.raises(KernelError,match='EXECUTION_TEMPLATE_WINDOW_RECOVERY_INVALID'):
        validate_templates({'execution_templates':[value]})
    value.update(version='creative-execution-template.v5',mode='STRICT_PRODUCTION',
        require_literary_qualification=True,world_future_preparation='REQUIRED')
    with pytest.raises(KernelError,match='EXECUTION_TEMPLATE_WINDOW_RECOVERY_INVALID'):
        validate_templates({'execution_templates':[value]})


def test_v6_canon_validation_is_explicit_preserves_v5_and_strict():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    value=template(version='creative-execution-template.v6',world_future_preparation='DISABLED',
        repair_routing={'version':'native-repair-routing.v2','max_same_route_repairs':2},
        chapter_contract_recovery='KNOWN_SETTLED_CONTRACT_REPAIR',canon_validation_contract='grounded-canon-validation.v2')
    validate_templates({'execution_templates':[value]})
    kwargs=dict(owner='PROVIDER_ROUTING',application_build_id='fixture',commit_sha='a'*40)
    new=owned_policy_definition(content={'execution_templates':[value]},**kwargs)
    assert new['definition_version']=='1.11.0'
    previous={k:v for k,v in value.items() if k!='canon_validation_contract'}
    previous['version']='creative-execution-template.v5'
    validate_templates({'execution_templates':[previous]})
    old=owned_policy_definition(content={'execution_templates':[previous]},**kwargs)
    assert old['definition_version']=='1.10.0'
    schema=old['command_schema']['properties']['policy']['properties']['execution_templates']['items']
    assert 'canon_validation_contract' not in schema['properties']
    assert 'creative-execution-template.v6' not in schema['properties']['version']['enum']
    for invalid in ({**value,'version':'creative-execution-template.v5'},
                    {**value,'mode':'STRICT_PRODUCTION','require_literary_qualification':True,'world_future_preparation':'REQUIRED'},
                    {k:v for k,v in value.items() if k!='canon_validation_contract'}):
        with pytest.raises(KernelError):
            validate_templates({'execution_templates':[invalid]})


def test_retained_graph_policy_is_explicit_and_does_not_change_historical_schema():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    value=template(version='creative-execution-template.v7',world_future_preparation='DISABLED',repair_routing={'version':'native-repair-routing.v2','max_same_route_repairs':2},chapter_contract_recovery='KNOWN_SETTLED_CONTRACT_REPAIR',canon_validation_contract='grounded-canon-validation.v2',chapter_graph_recovery='RETAIN_SETTLED_QUALITY_RANGE_RESULT')
    validate_templates({'execution_templates':[value]})
    current=owned_policy_definition(owner='PROVIDER_ROUTING',content={'execution_templates':[value]},application_build_id='unit',commit_sha='a'*40)
    assert current['definition_version']=='1.12.0'
    old={k:v for k,v in value.items() if k!='chapter_graph_recovery'}
    old['version']='creative-execution-template.v6'
    legacy=owned_policy_definition(owner='PROVIDER_ROUTING',content={'execution_templates':[old]},application_build_id='unit',commit_sha='a'*40)
    assert legacy['definition_version']=='1.11.0'
    schema=legacy['command_schema']['properties']['policy']['properties']['execution_templates']['items']
    assert 'chapter_graph_recovery' not in schema['properties'] and 'creative-execution-template.v7' not in schema['properties']['version']['enum']
    for invalid in ({**value,'version':'creative-execution-template.v6'},{**value,'mode':'STRICT_PRODUCTION','require_literary_qualification':True,'canon_validation_contract':None}):
        with pytest.raises(KernelError):
            validate_templates({'execution_templates':[invalid]})
