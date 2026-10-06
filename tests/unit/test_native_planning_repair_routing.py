from copy import deepcopy
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter, RoutingDecision
from novel_forge.modules.production_execution.execution_template import template_decision, validate_templates
from novel_forge.modules.production_execution.planning_repair_routing import REPAIR_VERSION, verify_native_repair
from tests.unit.test_cost_aware_routing import NOW, task
from tests.unit.test_creative_execution_template import membership, template


def repair_snapshot(*, number=1, failures=("SCHEMA_REJECTION",), **changes):
    value = template(version="creative-execution-template.v2", repair_routing={
        "version": "native-repair-routing.v1", "max_same_route_repairs": 2})
    evidence = {"version": REPAIR_VERSION, "operation_id": "operation", "repair_number": number,
        "parent_candidate_id": "member", "lineage_operation_ids": ["parent", "operation"]}
    current = task(policy_snapshot={"policy": {"execution_templates": [value]}},
        history=tuple({"candidate_id": "member", "failure_class": failure, "status": "SUCCEEDED"}
            for failure in failures), lineage_operation_ids=("parent", "operation"),
        declared_requirements={"native_planning_repair": evidence}, **changes)
    return CostAwareRouter().explain(current, [membership()], {}, now=NOW).to_dict()


def decide(snapshot):
    return template_decision(RoutingDecision(json.dumps(snapshot))).to_dict()


@pytest.mark.parametrize("number,failures", [(1, ("SCHEMA_REJECTION",)),
    (2, ("SCHEMA_REJECTION", "MALFORMED_STRUCTURED_OUTPUT"))])
def test_explicit_native_bounded_repair_retains_failures_and_requires_contract(number, failures):
    result = decide(repair_snapshot(number=number, failures=failures))
    assert result["status"] == "SELECTED"
    admission = result["selected"]["native_repair_admission"]
    assert len(admission["retained_failed_outcomes"]) == number
    assert admission["candidate_contract_acceptance"] == "REQUIRED_AFTER_REPAIR"
    assert admission["literary_qualification"] == "NOT_RUN"


@pytest.mark.parametrize("change", ["v1", "strict", "missing", "wrong-operation", "wrong-lineage", "wrong-route", "counter", "quality", "unknown", "too-many"])
def test_unrelated_or_unproven_failure_cannot_receive_native_repair_route(change):
    snapshot = repair_snapshot()
    value = snapshot["task"]["policy_snapshot"]["policy"]["execution_templates"][0]
    evidence = snapshot["task"]["declared_requirements"]["native_planning_repair"]
    if change == "v1":
        value["version"] = "creative-execution-template.v1"
        value.pop("repair_routing")
    elif change == "strict":
        value.update(mode="STRICT_PRODUCTION", require_literary_qualification=True)
    elif change == "missing":
        snapshot["task"]["declared_requirements"].clear()
    elif change == "wrong-operation":
        evidence["operation_id"] = "other"
    elif change == "wrong-lineage":
        evidence["lineage_operation_ids"] = ["other", "operation"]
    elif change == "wrong-route":
        evidence["parent_candidate_id"] = "other"
    elif change == "counter":
        evidence["repair_number"] = 3
    else:
        failures = {"quality": ("QUALITY_FAILURE",), "unknown": ("UNKNOWN_EXTERNAL_OUTCOME",),
            "too-many": ("SCHEMA_REJECTION", "SCHEMA_REJECTION")}[change]
        snapshot = repair_snapshot(failures=failures)
    assert decide(snapshot)["status"] == "BLOCKED"


@pytest.mark.parametrize("reason", ["CONTEXT_CAPACITY_EXCEEDED", "PROVIDER_TASK_NOT_AUTHORIZED",
    "CROSS_MODEL_REVIEW_DIFFERENT_PROVIDER_REQUIRED", "RECONCILIATION_OR_POLICY_RESOLUTION_REQUIRED",
    "MAX_CHAIN_ATTEMPTS_REACHED", "RETRY_AFTER_NOT_ELAPSED"])
def test_native_contract_repair_never_removes_other_guards(reason):
    snapshot = repair_snapshot()
    snapshot["candidates"][0]["rejected_reasons"].append(reason)
    result = decide(snapshot)
    assert result["status"] == "BLOCKED"
    assert reason in result["candidates"][0]["rejected_reasons"]


def test_native_repair_evidence_is_rechecked_at_dispatch(monkeypatch):
    snapshot = repair_snapshot()
    evidence = deepcopy(snapshot["task"]["declared_requirements"]["native_planning_repair"])
    import novel_forge.modules.production_execution.planning_repair_routing as module
    monkeypatch.setattr(module, "native_planning_repair", lambda *args, **kwargs: evidence)
    verify_native_repair(None, snapshot)
    evidence["repair_number"] = 2
    with pytest.raises(KernelError, match="EVIDENCE_DRIFT"):
        verify_native_repair(None, snapshot)


def test_other_route_quality_failure_keeps_semantic_arbitration():
    snapshot = repair_snapshot()
    snapshot["task"]["history"].append({"candidate_id": "other", "failure_class": "QUALITY_FAILURE"})
    snapshot["candidates"][0]["rejected_reasons"].append("SEMANTIC_ARBITRATION_REQUIRED")
    assert decide(snapshot)["status"] == "BLOCKED"


def test_repair_policy_requires_explicit_template_successor():
    with pytest.raises(KernelError, match="REPAIR_VERSION_INVALID"):
        validate_templates({"execution_templates": [template(repair_routing={
            "version": "native-repair-routing.v1", "max_same_route_repairs": 2})]})
    with pytest.raises(KernelError, match="REPAIR_VERSION_INVALID"):
        validate_templates({"execution_templates": [template(version="creative-execution-template.v2")]})


def test_expanded_template_configuration_uses_successor_definition():
    from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
    from novel_forge.modules.command_kernel.service import _validate_json_schema
    value = template(version="creative-execution-template.v2", repair_routing={
        "version": "native-repair-routing.v1", "max_same_route_repairs": 2})
    content = {"policy_version":"test", "task_overrides":[], "reason":"explicit successor", "execution_templates":[value]}
    definition = owned_policy_definition(owner="PROVIDER_ROUTING", content=content,
        application_build_id="test", commit_sha="e"*40)
    assert definition["definition_version"] == "1.7.0"
    assert definition["command_schema_version"].endswith(".v7")
    _validate_json_schema(definition["command_schema"], {"project_id":"project", "owner":"PROVIDER_ROUTING", "policy":content})
