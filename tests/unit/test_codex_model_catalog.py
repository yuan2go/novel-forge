from dataclasses import asdict, replace
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import bootstrap_candidate_accounting_matches
from novel_forge.modules.production_execution.codex_model_catalog import (
    CATALOG_VERSION, codex_catalog_candidates, parse_codex_model_catalog,
)
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter, authorized_codex_entitlement
from novel_forge.modules.production_execution.routing_runtime import validate_routed_reservation
from tests.unit.test_cost_aware_routing import NOW, generator_samples, samples, task


def catalog():
    return {"contract_version": CATALOG_VERSION, "models": [
        {"model": "gpt-6-sol", "reasoning": "medium", "role": "PRIMARY", "tasks": ["draft"],
         "context_limit": 200000, "output_limit": 32000},
        {"model": "gpt-6.1-sol", "reasoning": "high", "role": "REFERENCE", "tasks": ["review"],
         "context_limit": 200000, "output_limit": 32000},
    ]}


def candidates(value=None):
    return codex_catalog_candidates(parse_codex_model_catalog(json.dumps(value or catalog())),
        entitlement={"configuration_ref": "configuration:panel-v1", "authorization_ref": "account:user-v1"},
        quota=80, valid_from="2026-09-01T00:00:00+00:00", valid_until="2027-01-01T00:00:00+00:00")


def test_v2_unexposed_output_limit_uses_context_admission_bound_without_rewriting_v1():
    value = catalog()
    value["models"][0]["output_limit"] = None
    with pytest.raises(ValueError, match="ENTRY_INVALID"):
        candidates(value)
    value["contract_version"] = "codex-router-models.v2"
    writer, _ = candidates(value)
    assert writer.output_limit == writer.context_limit == 200000
    assert "codex-router-models.v2" in writer.model_revision
    assert candidates()[0].output_limit == 32000


def test_headroom_scope_rejects_mixed_capacities_before_route_selection():
    from novel_forge.modules.production_execution.codex_model_catalog import require_uniform_headroom_catalog
    value = catalog()
    value["contract_version"] = "codex-router-models.v2"
    for row in value["models"]:
        row["output_limit"] = None
    require_uniform_headroom_catalog(parse_codex_model_catalog(json.dumps(value)), context_limit=200000)
    value["models"][1]["context_limit"] = 300000
    with pytest.raises(ValueError, match="ROUTING_SCOPE_INVALID"):
        require_uniform_headroom_catalog(parse_codex_model_catalog(json.dumps(value)), context_limit=200000)
    with pytest.raises(ValueError, match="ROUTING_SCOPE_INVALID"):
        require_uniform_headroom_catalog(parse_codex_model_catalog(json.dumps(catalog())), context_limit=200000)


def test_primary_draft_requires_qualification_but_no_fabricated_escalation():
    writer, judge = candidates()
    context = task(task_type="draft")
    evidence = {row.candidate_id: generator_samples() for row in (writer, judge)}
    decision = CostAwareRouter().explain(context, [writer, judge], evidence, now=NOW).to_dict()
    assert decision["status"] == "SELECTED"
    assert decision["selected"]["candidate"]["model"] == "gpt-6-sol"
    assert decision["task"]["history"] == []
    assert decision["task"]["escalation_reason"] == ""
    assert "MODEL_TASK_NOT_AUTHORIZED" in decision["candidates"][1]["rejected_reasons"]
    blocked = CostAwareRouter().explain(context, [writer], {}, now=NOW).to_dict()
    assert blocked["status"] == "BLOCKED"
    assert "BENCHMARK_INSUFFICIENT" in blocked["candidates"][0]["rejected_reasons"]
    legacy = replace(writer, escalation_only=True, entitlement_role="")
    assert CostAwareRouter().explain(context, [legacy], evidence, now=NOW).to_dict()["status"] == "BLOCKED"


def test_reference_model_routes_only_on_qualified_reviewer_evidence():
    writer, judge = candidates()
    rows = [replace(row, quality_score=None, accepted=None, evidence_class="REFERENCE_EVALUATION",
        production_eligible=False, reference_agreed=True, reference_label_classes=("PASS" if index % 2 else "FAIL",),
        sample_identity=str(index), experiment_partition="CALIBRATION", reference_risk="MEDIUM",
        reference_context_tokens=1000, reference_protocol_hash="sha256:" + "1" * 64)
        for index, row in enumerate(samples(n=80))]
    decision = CostAwareRouter().explain(task(task_type="review"), [writer, judge],
        {writer.candidate_id: rows, judge.candidate_id: rows}, now=NOW).to_dict()
    assert decision["status"] == "SELECTED"
    assert decision["selected"]["candidate"]["model"] == "gpt-6.1-sol"
    assert "MODEL_TASK_NOT_AUTHORIZED" in decision["candidates"][0]["rejected_reasons"]
    assert decision["selected"]["benchmark"]["production_acceptance_rate"] is None


def test_model_task_scope_is_rechecked_at_reservation_boundary():
    _, judge = candidates()
    with pytest.raises(KernelError, match="outside its frozen task scope"):
        validate_routed_reservation({"status": "SELECTED", "selected": {"candidate": asdict(judge)},
            "task": {"task_type": "draft", "declared_requirements": {}, "remaining_tokens": 10000}},
            reserved_tokens=1000, reserved_amount=None)


def test_entitlement_role_requires_exact_account_and_frozen_catalog_identity():
    writer, judge = candidates()
    grant = {"accounting_basis": "ACCOUNT_ENTITLEMENT", "currency": "UNKNOWN",
             "cost_authorization_ref": "account:user-v1"}
    assert all(bootstrap_candidate_accounting_matches(grant, asdict(row)) for row in (writer, judge))
    assert not bootstrap_candidate_accounting_matches({**grant, "cost_authorization_ref": "other"}, asdict(writer))
    assert not authorized_codex_entitlement({**asdict(writer), "authorization_ref": "other"})
    changed = catalog()
    changed["models"][0]["reasoning"] = "high"
    assert candidates(changed)[0].model_revision != writer.model_revision
    changed = catalog()
    changed["models"][0]["tasks"] += ["revision"]
    assert candidates(changed)[0].model_revision != writer.model_revision


@pytest.mark.parametrize("change", [
    {"reasoning": "unsupported"}, {"role": "human"}, {"tasks": ["invented"]},
    {"tasks": []}, {"tasks": ["draft", "draft"]}, {"output_limit": 300000},
    {"context_limit": True}, {"context_limit": 0}, {"secret": "not-a-supported-field"},
])
def test_invalid_catalog_fails_closed(change):
    value = catalog()
    value["models"][0].update(change)
    with pytest.raises(ValueError):
        parse_codex_model_catalog(json.dumps(value))


def test_duplicate_model_effort_and_null_catalog_fail_closed():
    value = catalog()
    value["models"].append(value["models"][0])
    with pytest.raises(ValueError, match="DUPLICATE"):
        parse_codex_model_catalog(json.dumps(value))
    with pytest.raises(ValueError):
        parse_codex_model_catalog("null")
