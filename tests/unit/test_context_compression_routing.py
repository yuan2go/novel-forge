from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.production_execution.cost_routing import task_policy
from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot
from novel_forge.modules.production_execution.routing_policy import (
    validate_routing_policy,
)
from novel_forge.modules.authority_handler_runtime.context_feedback import (
    assess_extract,
)
from tests.unit.test_cost_aware_routing import candidate, route, samples, task
from tests.unit.test_task_scoped_context import candidate as source, compile_one


@pytest.mark.parametrize("stage", ["context_compress", "context_fidelity"])
def test_context_tasks_use_the_formal_taxonomy_with_engineering_gate_qualification(
    stage,
):
    policy = task_policy(stage)
    assert policy.risk == "HIGH" and policy.quality_metric == "DOMAIN_GATE_ACCEPTANCE"
    assert policy.minimum_samples == 20
    validate_routing_policy(
        {
            "policy_version": "test",
            "reason": "Finite test",
            "task_overrides": [
                {
                    "work_id": "book",
                    "task_type": stage,
                    "risk": "HIGH",
                    "quality_floor": policy.quality_floor,
                }
            ],
        }
    )
    t = replace(task(), task_type=stage)
    assert route(t, [candidate()], {})["status"] == "BLOCKED"
    observations = samples(n=150, domain_gate_accepted=True, sample_identity="")
    # WHY: independent native inputs matter; a repeated success cannot qualify a task.
    observations = [
        replace(row, sample_identity="source:" + row.evidence_ref)
        for row in observations
    ]
    assert route(t, [candidate()], {"flash": observations})["status"] == "SELECTED"
    rejected = [replace(row, domain_gate_accepted=False) for row in observations]
    assert route(t, [candidate()], {"flash": rejected})["status"] == "BLOCKED"


def test_overflow_invokes_both_formal_task_routes_then_reconstructs_the_original_source():
    calls = []

    def invoke(stage, payload):
        observations = [
            replace(row, sample_identity=row.evidence_ref)
            for row in samples(n=150, domain_gate_accepted=True)
        ]
        decision = route(
            replace(task(), task_type=stage), [candidate()], {"flash": observations}
        )
        assert decision["status"] == "SELECTED"
        calls.append((stage, deepcopy(payload)))
        return (
            {"selected_unit_ids": ["text:0"]}
            if stage == "context_compress"
            else {
                "supported": True,
                "coverage_complete": True,
                "missing_unit_ids": [],
                "distorted_unit_ids": [],
            }
        )

    original = source(
        text="A witnessed consequence.\n\nYou owe me one joke.\n\n"
        + "Irrelevant banquet. " * 50
    )
    result, receipt = compile_one(original, budget=180, model_call=invoke)
    assert [s for s, _ in calls] == ["context_compress", "context_fidelity"]
    assert result[0].safe_summary == "A witnessed consequence.\n\nYou owe me one joke."
    assert (
        receipt["compression_trace"][0]["source_content_hash"]
        == original.content_digest
    )
    assessment = receipt["compression_trace"][0]["routing_assessments"][0]
    comp = {
        "stage": "context_compress",
        "input": {"context_compression_task": calls[0][1]},
    }
    fid = {
        "stage": "context_fidelity",
        "input": {"context_compression_task": calls[1][1]},
    }
    assert assess_extract(assessment, compressor=comp, fidelity=fid) is True
    assert assess_extract(assessment, compressor=comp, fidelity=comp) is None
    changed = deepcopy(fid)
    changed["input"]["context_compression_task"]["source_binding"]["content_hash"] = (
        "other-book"
    )
    assert assess_extract(assessment, compressor=comp, fidelity=changed) is None


@pytest.mark.parametrize("stage", ["context_compress", "context_fidelity"])
def test_context_retried_failures_remain_in_the_qualification_denominator(stage):
    from tests.unit.test_cost_aware_routing import NOW

    observations = [
        replace(row, sample_identity="success:" + row.evidence_ref)
        for row in samples(n=150, domain_gate_accepted=True)
    ] + [
        replace(row, evidence_ref="failed:" + row.evidence_ref,
                sample_identity="failed:" + row.evidence_ref, accepted=False, retried=True)
        for row in samples(n=25, domain_gate_accepted=False)
    ]
    policy = task_policy(stage)
    snapshot = benchmark_snapshot(observations, now=NOW, policy=policy)
    assert snapshot["domain_gate_sample_count"] == 175
    assert route(replace(task(), task_type=stage), [candidate()], {"flash": observations})["status"] == "BLOCKED"
    # COMPATIBILITY: frozen policies keep their original accounting rule.
    frozen_policy = replace(policy, retain_failed_domain_samples=False)
    assert benchmark_snapshot(observations, now=NOW, policy=frozen_policy)["domain_gate_sample_count"] == 150
    assert task_policy("source.deconstruction.observe").retain_failed_domain_samples is False
