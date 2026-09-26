from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.production_execution.cost_routing import (
    BenchmarkObservation,
    CostAwareRouter,
    ModelCandidate,
    PricingSnapshot,
    RoutingTask,
)


NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


def candidate(name="flash", price="1", **overrides):
    return ModelCandidate(
        name,
        "deepseek",
        name,
        "high",
        name,
        ("structured_output",),
        100_000,
        20_000,
        PricingSnapshot(
            "price-v1",
            "2026-09-01T00:00:00+00:00",
            "2026-10-01T00:00:00+00:00",
            price,
            "0.01",
            price,
            source="official",
        ),
        "capability-v1",
        **overrides,
    )


def task(**overrides):
    return replace(
        RoutingTask(
            "classification",
            "project",
            "book",
            "operation",
            "attempt",
            1000,
            100,
            100_000,
            "1",
        ),
        **overrides,
    )


def samples(score=0.99, n=30, cached=0, **overrides):
    return [
        BenchmarkObservation(
            str(i),
            NOW.isoformat(),
            score,
            True,
            True,
            False,
            False,
            False,
            False,
            2,
            1000,
            100,
            cached,
            ".001",
            **overrides,
        )
        for i in range(n)
    ]


def route(task_context, candidates, observations):
    return (
        CostAwareRouter()
        .explain(task_context, candidates, observations, now=NOW)
        .to_dict()
    )


def test_quality_floor_precedes_price_and_equal_quality_uses_effective_cost():
    cheap, strong = candidate(), candidate("pro", "3")
    result = route(task(), [cheap, strong], {"flash": samples(0.5), "pro": samples()})
    assert result["selected"]["candidate"]["candidate_id"] == "pro"
    result = route(task(), [strong, cheap], {"flash": samples(), "pro": samples()})
    assert result["selected"]["candidate"]["candidate_id"] == "flash"


def test_failed_outputs_cannot_hide_behind_surviving_high_quality_scores():
    successes = samples(n=10)
    failures = [
        replace(
            row,
            evidence_ref="failed:" + row.evidence_ref,
            quality_score=None,
            accepted=False,
            schema_success=False,
        )
        for row in samples(n=20)
    ]
    result = route(task(), [candidate()], {"flash": successes + failures})
    benchmark = result["candidates"][0]["benchmark"]
    assert benchmark["conditional_content_quality"] > 0.9
    assert benchmark["predicted_quality"] == pytest.approx(1 / 3)
    assert result["status"] == "BLOCKED"


def test_cache_cost_uses_observed_tokens_without_discounting_the_prefix_twice():
    result = route(
        task(cache_eligible=True, reusable_prefix_tokens=500),
        [candidate()],
        {"flash": samples(cached=500)},
    )
    assert result["selected"]["cache_tokens_estimate"] == 500


def test_absent_stale_and_fixture_benchmarks_fail_closed():
    for evidence in (
        [],
        samples(n=1),
        samples(evidence_kind="FIXTURE"),
        [replace(row, occurred_at="2026-07-01T00:00:00+00:00") for row in samples()],
    ):
        result = route(task(), [candidate()], {"flash": evidence})
        assert result["status"] == "BLOCKED"
        assert "BENCHMARK_INSUFFICIENT" in result["candidates"][0]["rejected_reasons"]


def test_routing_task_requires_a_root_to_current_operation_lineage():
    lineage = task(lineage_operation_ids=("root-operation", "operation"))
    assert lineage.lineage_operation_ids == ("root-operation", "operation")
    with pytest.raises(ValueError, match="ROUTING_TASK_LINEAGE_INVALID"):
        task(lineage_operation_ids=("operation", "root-operation"))
    with pytest.raises(ValueError, match="ROUTING_TASK_LINEAGE_INVALID"):
        task(lineage_operation_ids=("operation", "operation"))


def test_high_risk_uncertainty_and_budget_never_lower_floor():
    context = task(task_type="critical_chapter", remaining_money="0.0001")
    result = route(context, [candidate()], {"flash": samples()})
    assert result["status"] == "BLOCKED"
    assert result["policy"]["quality_floor"] == 0.85
    assert "BUDGET_HARD_LIMIT" in result["candidates"][0]["rejected_reasons"]


def test_cache_changes_rank_but_reservation_assumes_miss():
    cold, warm = candidate(), candidate("pro", "2")
    context = task(cache_eligible=True, reusable_prefix_tokens=1000)
    result = route(
        context, [cold, warm], {"flash": samples(), "pro": samples(cached=1000)}
    )
    assert result["selected"]["candidate"]["candidate_id"] == "pro"
    assert result["selected"]["reservation_upper_bound"] == "0.0022"
    assert result["selected"]["estimated_monetary_cost"] == "0.00021"


def test_soft_limit_is_visible_and_does_not_remove_qualified_routes():
    result = route(task(soft_money_limit=".0001"), [candidate()], {"flash": samples()})
    assert result["selected"]["soft_limit_pressure"] is True


@pytest.mark.parametrize(
    "failure",
    [
        "QUALITY_FAILURE",
        "SCHEMA_REJECTION",
        "CONTEXT_OVERFLOW",
        "AMBIGUOUS_JUDGE",
    ],
)
def test_failed_route_is_excluded(failure):
    context = task(history=({"candidate_id": "flash", "failure_class": failure},))
    result = route(
        context,
        [candidate(), candidate("pro", "2")],
        {"flash": samples(), "pro": samples()},
    )
    assert result["selected"]["candidate"]["candidate_id"] == "pro"


def test_unavailable_capability_and_capacity_fail_closed():
    for value in (
        candidate(available=False),
        replace(candidate(), context_limit=100),
        replace(candidate(), capabilities=("text",)),
    ):
        assert route(task(), [value], {"flash": samples()})["status"] == "BLOCKED"


def test_codex_requires_threshold_authorization_quota_and_no_loop():
    codex = candidate(
        "codex",
        "10",
        escalation_only=True,
        quota_remaining=1,
        authorization_ref="grant:1",
    )
    assert route(task(), [codex], {"codex": samples()})["status"] == "BLOCKED"
    context = task(
        history=tuple(
            {"candidate_id": "flash", "failure_class": "AMBIGUOUS_JUDGE"}
            for _ in range(2)
        )
    )
    assert route(context, [codex], {"codex": samples()})["status"] == "SELECTED"
    assert (
        route(context, [replace(codex, available=False)], {"codex": samples()})[
            "status"
        ]
        == "BLOCKED"
    )
    context = replace(
        context,
        history=(*context.history, {"candidate_id": "codex", "escalation": True}),
    )
    assert route(context, [codex], {"codex": samples()})["status"] == "BLOCKED"


def test_unknown_outcome_requires_reconciliation_and_decision_is_immutable():
    context = task(history=({"failure_class": "UNKNOWN_EXTERNAL_OUTCOME"},))
    decision = CostAwareRouter().explain(
        context, [candidate()], {"flash": samples()}, now=NOW
    )
    original = decision.to_dict()
    original["policy"]["quality_floor"] = 0
    assert decision.to_dict()["policy"]["quality_floor"] == 0.60
    assert decision.to_dict()["status"] == "BLOCKED"


def test_domain_acceptance_is_a_distinct_measured_metric_not_a_literary_score():
    from novel_forge.modules.production_execution.cost_routing import (
        benchmark_snapshot,
        task_policy,
    )

    observations = [
        replace(
            row,
            quality_score=None,
            domain_gate_accepted=True,
            outcome_refs=("qualification:" + row.evidence_ref,),
        )
        for row in samples(n=50)
    ]
    planning = benchmark_snapshot(observations, now=NOW, policy=task_policy("book_plan.generate"))
    assert planning["quality_metric"] == "GENERATOR_SCORE"
    assert planning["predicted_quality"] == 0 and planning["uncertain"]
    policy = task_policy("source.deconstruction.observe")
    benchmark = benchmark_snapshot(observations, now=NOW, policy=policy)
    assert benchmark["quality_metric"] == "DOMAIN_GATE_ACCEPTANCE"
    assert benchmark["quality_distribution"] == []
    assert benchmark["quality_sample_count"] == 0
    assert benchmark["predicted_quality"] >= policy.quality_floor
    assert not benchmark["uncertain"]
    failed = [replace(row, domain_gate_accepted=False) for row in observations[:20]]
    assert (
        benchmark_snapshot(failed + observations[20:], now=NOW, policy=policy)[
            "predicted_quality"
        ]
        < policy.quality_floor
    )
    unreviewed = [
        replace(row, domain_gate_accepted=None, schema_success=True)
        for row in observations
    ]
    assert (
        benchmark_snapshot(unreviewed, now=NOW, policy=policy)["predicted_quality"] == 0
    )


def test_benchmark_challengers_qualify_without_becoming_production_acceptance():
    from novel_forge.modules.production_execution.cost_routing import (
        benchmark_snapshot,
        task_policy,
    )

    production = replace(
        samples(n=1)[0],
        evidence_ref="production",
        accepted=False,
    )
    challengers = [
        replace(
            row,
            evidence_ref=f"challenger:{number}",
            evidence_class="BENCHMARK_CHALLENGER",
            production_eligible=False,
        )
        for number, row in enumerate(samples(n=30))
    ]
    snapshot = benchmark_snapshot(
        [production, *challengers],
        now=NOW,
        policy=task_policy("classification"),
    )

    assert snapshot["sample_count"] == 31
    assert snapshot["benchmark_challenger_sample_count"] == 30
    assert snapshot["production_eligible_sample_count"] == 1
    assert snapshot["qualification_acceptance_rate"] == pytest.approx(30 / 31)
    assert snapshot["production_acceptance_rate"] == 0
    assert snapshot["acceptance_rate"] == 0


def test_work_and_chapter_policy_cannot_weaken_quality_or_select_a_model():
    from novel_forge.modules.production_execution.routing_policy import (
        task_requirements,
        validate_routing_policy,
    )

    policy = {
        "policy_version": "critical-chapter-v1",
        "reason": "climax continuity",
        "task_overrides": [
            {
                "work_id": "novel",
                "task_type": "draft",
                "risk": "HIGH",
                "quality_floor": 0.9,
            },
            {
                "work_id": "novel",
                "task_type": "draft",
                "chapter": 9,
                "risk": "MEDIUM",
                "quality_floor": 0.8,
            },
        ],
    }
    requirements = task_requirements(
        policy, work_id="novel", task_type="draft", chapter=9
    )
    assert requirements["risk"] == "HIGH"
    assert requirements["quality_floor"] == 0.9
    assert task_requirements(policy, work_id="unrelated", task_type="draft") == {}
    policy["task_overrides"][0]["quality_floor"] = 0.1
    with pytest.raises(ValueError, match="DOWNGRADE_FORBIDDEN"):
        validate_routing_policy(policy)
    policy["task_overrides"][0]["quality_floor"] = 0.9
    policy["task_overrides"][0]["model"] = "cheapest"
    with pytest.raises(Exception, match="SCHEMA_INVALID"):
        validate_routing_policy(policy)
    del policy["task_overrides"][0]["model"]
    policy["task_overrides"][0]["latency_sla_seconds"] = 0
    with pytest.raises(Exception, match="SCHEMA_INVALID"):
        validate_routing_policy(policy)


def test_cache_history_from_another_prefix_does_not_discount_route():
    context = task(
        cache_eligible=True, reusable_prefix_tokens=1000, cache_prefix_hash="current"
    )
    cheap, costly = candidate(), candidate("pro", "2")
    historical = [
        replace(row, cache_prefix_hash="another") for row in samples(cached=1000)
    ]
    decision = route(context, [cheap, costly], {"flash": samples(), "pro": historical})
    assert decision["selected"]["candidate"]["candidate_id"] == "flash"
    assert all(row["cache_tokens_estimate"] == 0 for row in decision["candidates"])


@pytest.mark.parametrize("state", ["READY", "DISPATCHING", "DISPATCHED"])
def test_authoritative_inflight_effect_blocks_overlapping_chain(state):
    result = route(
        task(history=({"status": state},)), [candidate()], {"flash": samples()}
    )
    assert "CHAIN_EXECUTION_IN_FLIGHT" in result["candidates"][0]["rejected_reasons"]


def test_missing_latency_is_uncertain_under_sla():
    observations = [replace(row, latency_seconds=None) for row in samples()]
    result = route(task(latency_sla_seconds=30), [candidate()], {"flash": observations})
    assert result["status"] == "BLOCKED"
    assert result["candidates"][0]["benchmark"]["latency_seconds"] is None


@pytest.mark.parametrize(
    "drift",
    [
        "none",
        "attempt_id",
        "book_id",
        "input",
        "admission",
        "decision",
        "protocol",
        "reasoning_effort",
        "pricing_policy_json",
        "lineage",
    ],
)
def test_frozen_route_requires_original_scope_input_and_admission(drift):
    from copy import deepcopy
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    from novel_forge.modules.production_execution.routing_runtime import (
        ProductionProviderRouter,
    )

    original = route(
        task(
            input_hash="sha256:prompt",
            request_hash=snapshot_hash({"text": "original"}),
            stable_key="stable",
        ),
        [candidate()],
        {"flash": samples()},
    )
    frozen = {**deepcopy(original), "asset_version_id": "decision-version"}
    identity = {
        "input_text_hash": "sha256:prompt",
        "stable_idempotency_key": "stable",
        "max_output_tokens": 100,
        "provider": "deepseek",
        "model": "flash",
        "protocol": "deepseek-chat-completions-json-v1",
        "reasoning_effort": "high",
        "pricing_policy_json": json.dumps(original["selected"]["candidate"]["pricing"]),
    }
    documents = {
        "decision-version": SimpleNamespace(
            asset_type="routing_decision", content=original
        ),
        "admission-version": SimpleNamespace(
            asset_type="provider_request_admission_manifest",
            content_hash="sha256:admission",
            content={"provider_request_identity": identity},
        ),
    }
    payload = {
        "stage": "classification",
        "input": {"text": "original"},
        "_production_execution": {
            "project_id": "project",
            "operation_id": "operation",
            "attempt_id": "attempt",
            "book_id": "book",
            "capability_runtime": {
                "routing_decision": frozen,
                "provider_admission_asset_version_id": "admission-version",
                "provider_admission_content_hash": "sha256:admission",
            },
        },
    }
    if drift in {"attempt_id", "book_id"}:
        payload["_production_execution"][drift] = "different"
    elif drift == "input":
        payload["input"]["text"] = "different"
    elif drift == "admission":
        identity["input_text_hash"] = "sha256:other"
    elif drift == "decision":
        frozen["selected"]["candidate"]["model"] = "other"
    elif drift == "lineage":
        original["task"]["lineage_operation_ids"] = ["operation", "root"]
        original["decision_id"] = "routing-decision:" + snapshot_hash(
            {key: value for key, value in original.items() if key != "decision_id"}
        ).removeprefix("sha256:")
        frozen = {**deepcopy(original), "asset_version_id": "decision-version"}
        payload["_production_execution"]["capability_runtime"][
            "routing_decision"
        ] = frozen
    elif drift in {"protocol", "reasoning_effort", "pricing_policy_json"}:
        identity[drift] = "{}" if drift == "pricing_policy_json" else "other"
    router = ProductionProviderRouter(
        "unused", candidates=[candidate()], task_money_limit="1", task_token_limit=10000
    )
    router.registry.query.require = Mock(
        side_effect=lambda **kw: documents[kw["asset_version_id"]]
    )
    router._selected_route = Mock(return_value="selected")
    if drift == "none":
        assert router.select_for_payload(None, payload)[0] == "selected"
    else:
        with pytest.raises(KernelError):
            router.select_for_payload(None, payload)
        router._selected_route.assert_not_called()


def test_repeated_inputs_cannot_supply_independent_qualification_samples():
    result = route(task(), [candidate()], {"flash": samples(n=30, sample_identity="same-input")})
    benchmark = result["candidates"][0]["benchmark"]
    assert result["status"] == "BLOCKED"
    assert benchmark["sample_count"] == 30
    assert benchmark["independent_sample_count"] == 1
    assert benchmark["repeated_sample_attempt_count"] == 29
    assert benchmark["metric_sample_count"] == 1
    assert benchmark["actual_cost"] == "0.030"


@pytest.mark.parametrize("partition", ["DEVELOPMENT", "HOLDOUT"])
def test_unpublished_experiment_partitions_cannot_change_routing(partition):
    observations = [replace(row, sample_identity=row.evidence_ref,
                            experiment_partition=partition) for row in samples()]
    result = route(task(), [candidate()], {"flash": observations})
    benchmark = result["candidates"][0]["benchmark"]
    assert result["status"] == "BLOCKED"
    assert benchmark["sample_count"] == 0
    assert benchmark["excluded_experiment_partition_count"] == 30


def test_repair_cannot_replace_failed_first_attempt_for_calibration():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    from datetime import timedelta
    rows = samples(n=3)
    observations = []
    for row in rows:
        observations.append(replace(row, sample_identity=row.evidence_ref,
            quality_score=None, schema_success=False, accepted=False))
        observations.append(replace(row, sample_identity=row.evidence_ref,
            evidence_ref="repair:" + row.evidence_ref,
            occurred_at=(NOW + timedelta(seconds=1)).isoformat(), repaired=True))
    result = benchmark_snapshot(observations, now=NOW + timedelta(seconds=2),
                                policy=task_policy("classification"))
    assert result["metric_sample_count"] == 0
    assert result["schema_success"] == .5
    assert result["sample_count"] == 6
    assert result["independent_sample_count"] == 3


def test_window_censoring_does_not_promote_repaired_samples():
    from datetime import timedelta
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    first = replace(samples(n=1)[0], sample_identity="same-input", quality_score=None,
                    schema_success=False, accepted=False)
    repairs = [replace(row, sample_identity="same-input", retried=True,
                       evidence_ref="repair:" + row.evidence_ref,
                       occurred_at=(NOW + timedelta(seconds=1)).isoformat())
               for row in samples(n=5)]
    for observations in ([first, *repairs], repairs):
        result = benchmark_snapshot(observations, now=NOW + timedelta(seconds=2),
                                    policy=task_policy("classification"), maximum_samples=3)
        assert result["metric_sample_count"] == 0
        assert result["independent_sample_count"] == 1


@pytest.mark.parametrize("change", ["prompt", "schema", "pack_schema", "context_policy", "provider_view", "language", "source_isolation"])
def test_producer_identity_separates_contract_changes_from_new_independent_data(change):
    from copy import deepcopy
    from novel_forge.modules.production_execution.cost_routing import producer_contract_identity, snapshot_hash

    artifact = {"ref": "fixture-prompt", "version": "1", "content_hash": "sha256:" + "a" * 64}
    prompt = {"system_instruction": dict(artifact), "prompt_template": dict(artifact), "skill": dict(artifact),
              "output_schema_ref": "fixture-schema", "output_schema_hash": "sha256:" + "b" * 64,
              "allowed_tools": ["model.provider.invoke"], "fully_rendered_prompt_hash": "sample-one",
              "context_asset_version_ids": ["sample-one-context"], "required_reader_facing_language": "zh",
              "provider_view": {"task_contract_version": "task.v1", "context_contract_version": "context.v1",
                                "component_hashes": {"data": "sample-one"}}}
    materialization = {"schema_version": "fixture.v1", "stage": "draft",
                       "pack_artifacts": {"context_policy": dict(artifact), "output_schema": dict(artifact)},
                       "source_isolation": {"raw_source_allowed": False},
                       "attempt_snapshot": {"operation_id": "sample-one"}}
    original = snapshot_hash(producer_contract_identity(prompt, materialization))
    next_prompt, next_materialization = deepcopy(prompt), deepcopy(materialization)
    next_prompt.update(fully_rendered_prompt_hash="sample-two", context_asset_version_ids=["sample-two-context"])
    next_prompt["provider_view"]["component_hashes"]["data"] = "sample-two"
    next_materialization["attempt_snapshot"]["operation_id"] = "sample-two"
    assert snapshot_hash(producer_contract_identity(next_prompt, next_materialization)) == original
    if change == "prompt":
        next_prompt["prompt_template"]["content_hash"] = "sha256:" + "c" * 64
    elif change == "schema":
        next_prompt["output_schema_hash"] = "sha256:" + "c" * 64
    elif change == "pack_schema":
        next_materialization["pack_artifacts"]["output_schema"]["version"] = "2"
    elif change == "context_policy":
        next_materialization["pack_artifacts"]["context_policy"]["version"] = "2"
    elif change == "provider_view":
        next_prompt["provider_view"]["context_contract_version"] = "context.v2"
    elif change == "language":
        next_prompt["required_reader_facing_language"] = "en"
    else:
        next_materialization["source_isolation"]["raw_source_allowed"] = True
    assert snapshot_hash(producer_contract_identity(next_prompt, next_materialization)) != original


def test_planning_schema_identity_preserves_independent_bindings_and_contract_shape():
    from copy import deepcopy
    from novel_forge.modules.story_planning_runtime.execution import planning_provider_output_schema, planning_schema_evidence_identity
    from novel_forge.modules.hierarchical_planning.domain import PlanContractType

    first = planning_provider_output_schema(PlanContractType.VOLUME, logical_key="volume:a",
        parent_version_id="parent:a", dependency_version_ids=("input:a",))
    second = planning_provider_output_schema(PlanContractType.VOLUME, logical_key="volume:b",
        parent_version_id="parent:b", dependency_version_ids=("input:b",))
    assert first != second
    identity = planning_schema_evidence_identity(first, "volume:v1")
    assert planning_schema_evidence_identity(second, "volume:v1") == identity
    incompatible = deepcopy(second)
    incompatible["properties"]["objective"]["maxLength"] = 12
    assert planning_schema_evidence_identity(incompatible, "volume:v1") != identity
    assert planning_schema_evidence_identity(second, "volume:v2") != identity
    different_shape = planning_provider_output_schema(PlanContractType.VOLUME, logical_key="volume:c",
        parent_version_id="parent:c", dependency_version_ids=("input:c", "input:d"))
    assert planning_schema_evidence_identity(different_shape, "volume:v1") != identity


def test_chapter_evidence_compatibility_projects_only_unreachable_context_types():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.execution_gateway import chapter_producer_contract_identity

    artifact = {"ref": "fixture", "version": "1", "content_hash": "sha256:" + "a" * 64}
    prompt = {"system_instruction": artifact, "prompt_template": artifact, "skill": artifact,
              "output_schema_ref": "fixture-schema", "output_schema_hash": "sha256:" + "b" * 64,
              "allowed_tools": ["model.provider.invoke"]}
    materialization = {
        "schema_version": "novelos.chapter_capability_materialization.v1", "stage": "draft",
        "pack_artifacts": {"context_policy": {**artifact, "content": {
            "allowed_asset_types": ["context_bundle", "chapter_plan"],
            "forbidden_asset_types": ["raw_source_chunk"], "max_tokens": 16000,
            "source_isolation": "ABSTRACT_ASSETS_ONLY", "reject_cross_project": True,
        }}, "tool_policy": {**artifact, "content": {
            "default": "DENY", "explicit_tool_refs": ["model.provider.invoke", "storage.object.put"],
            "audit_high_and_critical": True,
        }}},
        "tool_permissions": {"allowed": ["model.provider.invoke"], "denied": ["storage.object.put"],
                             "default": "DENY", "governing_policy_hash": "formal"},
    }
    expected = chapter_producer_contract_identity(prompt, materialization)
    sample = deepcopy(materialization)
    sample["pack_artifacts"]["context_policy"]["content"]["allowed_asset_types"].append("draft_chapter")
    sample["pack_artifacts"]["context_policy"]["content_hash"] = "sha256:" + "c" * 64
    sample["tool_permissions"]["governing_policy_hash"] = "sample"
    sample["tool_permissions"]["denied"] = []
    sample["pack_artifacts"]["tool_policy"]["content"]["explicit_tool_refs"] = ["model.provider.invoke"]
    assert chapter_producer_contract_identity(prompt, sample) == expected
    for key, value in [("max_tokens", 8000), ("source_isolation", "RAW_ALLOWED"),
                       ("reject_cross_project", False), ("allowed_asset_types", ["chapter_plan"]),
                       ("forbidden_asset_types", [])]:
        changed = deepcopy(sample)
        changed["pack_artifacts"]["context_policy"]["content"][key] = value
        assert chapter_producer_contract_identity(prompt, changed) != expected
    sample["tool_permissions"]["allowed"].append("storage.object.put")
    assert chapter_producer_contract_identity(prompt, sample) != expected


def test_reference_agreement_requires_both_label_strata_and_preserves_failed_first_attempts():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy

    reference_task = task(task_type="review")
    observations = [replace(row, quality_score=None, accepted=None, evidence_class="REFERENCE_EVALUATION",
        production_eligible=False, reference_agreed=True, reference_label_classes=("PASS" if i % 2 else "FAIL",),
        sample_identity=str(i), experiment_partition="CALIBRATION", reference_risk="MEDIUM", reference_context_tokens=1000,
        reference_protocol_hash="sha256:" + "1" * 64) for i, row in enumerate(samples(n=80))]
    for name in ("review", "rereview", "quality_structural", "quality_longform", "world_candidates.evaluate", "narrative_semantic_evaluation"):
        result = route(replace(reference_task, task_type=name), [candidate()], {"flash":
            [replace(row, reference_risk=task_policy(name).risk) for row in observations]})
        assert result["status"] == "SELECTED"
        benchmark = result["selected"]["benchmark"]
        assert benchmark["quality_metric"] == "REFERENCE_AGREEMENT"
        assert benchmark["metric_sample_count"] == 80
        assert benchmark["quality_sample_count"] == 0
        assert benchmark["production_acceptance_rate"] is None
        assert benchmark["reference_label_strata"]["FAIL"]["sample_count"] == 40
    for bad in (
        [replace(row, reference_label_classes=("PASS",)) for row in observations],
        [replace(row, reference_risk="LOW") for row in observations],
        [replace(row, reference_context_tokens=100_000) for row in observations],
        [replace(row, reference_protocol_hash="sha256:" + str(i % 2) * 64) for i, row in enumerate(observations)],
        [replace(row, experiment_partition="HOLDOUT") for row in observations],
        [replace(row, reference_agreed=i % 2 == 1) for i, row in enumerate(observations)],
        [replace(row, sample_identity="same-prose") for row in observations],
        [replace(row, retried=True) for row in observations],
    ):
        assert route(reference_task, [candidate()], {"flash": bad})["status"] == "BLOCKED"
    other_context = [replace(row, evidence_ref=f"long:{repeat}:" + row.evidence_ref, sample_identity=f"long:{repeat}:" + row.sample_identity,
        reference_context_tokens=100_000) for repeat in range(3) for row in observations]
    assert route(reference_task, [candidate()], {"flash": observations + other_context})["status"] == "SELECTED"
    failures = [replace(row, evidence_ref="failure:" + row.evidence_ref, reference_agreed=None,
        reference_label_classes=(), sample_identity="failed:" + row.sample_identity, schema_success=False,
        accepted=False) for row in observations]
    result = route(reference_task, [candidate()], {"flash": observations + failures})
    assert result["status"] == "BLOCKED"
    assert result["candidates"][0]["benchmark"]["schema_success"] == 0.5
    first = replace(observations[0], reference_agreed=False)
    repaired = replace(first, evidence_ref="replacement", reference_agreed=True, retried=True)
    assert benchmark_snapshot([first, repaired], now=NOW, policy=task_policy("review"))["reference_agreement_rate"] == 0


def generator_samples(n=80):
    return [replace(row, quality_score=None, accepted=None, domain_gate_accepted=None,
        evidence_class="BENCHMARK_CHALLENGER", production_eligible=False,
        sample_identity="content:" + str(index), independence_group="frozen-input:" + str(index), experiment_partition="CALIBRATION",
        producer_contract_hash="sha256:producer", generator_quality_score=0.98,
        generator_protocol_hash="sha256:protocol", generator_risk="MEDIUM", generator_context_tokens=1000,
        outcome_refs=("native-independent-adjudication:" + str(index),))
        for index, row in enumerate(samples(n=n))]


def test_generator_admission_uses_independent_scores_without_promoting_samples():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    rows = generator_samples()
    policy = task_policy("draft")
    evidence = benchmark_snapshot(rows, now=NOW, policy=policy, input_tokens=1000)
    assert policy.quality_metric == "GENERATOR_SCORE"
    assert evidence["predicted_quality"] >= policy.quality_floor and not evidence["uncertain"]
    assert evidence["production_acceptance_sample_count"] == 0
    assert evidence["generator_protocol_hashes"] == ["sha256:protocol"]
    assert not any(row.production_eligible for row in rows)
    routed = CostAwareRouter().explain(task(task_type="draft"), [candidate()], {"flash": rows}, now=NOW).to_dict()
    assert routed["status"] == "SELECTED"
    assert routed["selected"]["benchmark"]["quality_metric"] == "GENERATOR_SCORE"
    negative = [replace(row, generator_quality_score=0) for row in rows[:30]] + rows[30:]
    assert CostAwareRouter().explain(task(task_type="draft"), [candidate()], {"flash": negative}, now=NOW).to_dict()["status"] == "BLOCKED"


@pytest.mark.parametrize("change", [
    {"sample_identity": "same-normalized-content"}, {"independence_group": "same-frozen-input"}, {"retried": True},
    {"generator_risk": "LOW"}, {"generator_context_tokens": 50000},
    {"generator_quality_score": None, "quality_score": 1, "domain_gate_accepted": True},
])
def test_generator_feedback_isolated_from_retries_scope_and_business_success(change):
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    rows = [replace(row, **change) for row in generator_samples()]
    result = benchmark_snapshot(rows, now=NOW, policy=task_policy("draft"), input_tokens=1000)
    assert result["uncertain"] or result["predicted_quality"] < 0.85


def test_generator_unknown_protocol_and_partition_cannot_gain_current_qualification():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    rows = generator_samples()
    mixed = rows[:40] + [replace(row, generator_protocol_hash="sha256:different-protocol") for row in rows[40:]]
    assert benchmark_snapshot(mixed, now=NOW, policy=task_policy("draft"))["uncertain"]
    for partition in ("DEVELOPMENT", "HOLDOUT", ""):
        with pytest.raises(ValueError, match="BENCHMARK_GENERATOR_INVALID"):
            replace(rows[0], experiment_partition=partition)
    with pytest.raises(ValueError, match="BENCHMARK_GENERATOR_INVALID"):
        replace(rows[0], generator_protocol_hash="")


def test_generator_attribution_is_conservative_and_keeps_negative_evaluation():
    from novel_forge.modules.authority_handler_runtime.generator_feedback import adjudicated_generator_score
    label = {"dimension": "review_decision", "status": "PASSED", "score_range": [88, 96]}
    assert adjudicated_generator_score([label]) == 0.88
    assert adjudicated_generator_score([{**label, "status": "NEEDS_REVISION"}]) == 0
    assert adjudicated_generator_score([{**label, "score_range": [0, 100]}]) is None
    assert adjudicated_generator_score([{**label, "score_range": [float("nan"), 100]}]) is None
    assert adjudicated_generator_score([label, label]) is None



def test_independent_global_reviewer_qualification_is_separate_from_generation_and_coverage():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    policy = task_policy("longform_prose_review")
    assert policy.quality_metric == "INDEPENDENT_REVIEWER_SCORE"
    assert benchmark_snapshot(generator_samples(), now=NOW, policy=policy)["uncertain"]
    rows = [replace(row, evidence_class="REFERENCE_EVALUATION", generator_quality_score=None,
        independent_quality_score=.98, independent_protocol_hash="sha256:review-protocol",
        independent_risk="MEDIUM", independent_context_tokens=1000) for row in generator_samples()]
    positive = benchmark_snapshot(rows, now=NOW, policy=policy, input_tokens=1000)
    assert not positive["uncertain"] and positive["predicted_quality"] >= policy.quality_floor
    negative = [replace(row, independent_quality_score=0) for row in rows[:30]] + rows[30:]
    assert benchmark_snapshot(negative, now=NOW, policy=policy, input_tokens=1000)["predicted_quality"] < policy.quality_floor
    for changed in (
        [replace(row, independent_protocol_hash="sha256:other") for row in rows[:40]] + rows[40:],
        [replace(row, independent_risk="HIGH") for row in rows],
        [replace(row, sample_identity="same-window") for row in rows],
        [replace(row, independent_quality_score=None, quality_score=1, accepted=True) for row in rows],
    ):
        assert benchmark_snapshot(changed, now=NOW, policy=policy, input_tokens=1000)["uncertain"]
    with pytest.raises(ValueError, match="BENCHMARK_INDEPENDENT_REVIEWER_INVALID"):
        replace(rows[0], experiment_partition="HOLDOUT")



@pytest.mark.parametrize("age_days", [0, 31])
def test_campaign_renaming_cannot_reclassify_held_out_generator_content(age_days):
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    calibrated = generator_samples()
    heldout = [replace(row, evidence_ref="other-campaign:" + row.evidence_ref,
        experiment_partition="HOLDOUT", generator_quality_score=None,
        occurred_at=(NOW - timedelta(days=age_days)).isoformat()) for row in calibrated]
    result = benchmark_snapshot(calibrated + heldout, now=NOW, policy=task_policy("draft"), input_tokens=1000)
    assert result["uncertain"] and result["quality_sample_count"] == 0
    assert len(result["partition_conflicted_sample_identities"]) == len(calibrated)



def test_unadjudicated_or_uninformative_generator_outcomes_cannot_hide_behind_positive_subset():
    from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
    rows = generator_samples()
    unadjudicated = replace(rows[0], evidence_ref="not-yet-labeled", sample_identity="new-output",
        independence_group="new-input", generator_quality_score=None)
    result = benchmark_snapshot(rows + [unadjudicated], now=NOW, policy=task_policy("draft"), input_tokens=1000)
    assert result["uncertain"] and result["unadjudicated_generator_sample_count"] == 1


@pytest.mark.parametrize("scenario", ["distinct", "same_model_other_transport", "same_revision", "same_served_model", "unknown_alias", "missing_revision"])
def test_generator_judge_requires_independent_concrete_model_identity(scenario):
    from novel_forge.modules.authority_handler_runtime.generator_feedback import independent_model_identities
    generator = {"provider": "codex-cli", "model": "gpt-6-astra", "model_revision": "approved-contract-A"}
    evaluator = {"provider": "codex-cli", "model": "gpt-6-sol", "model_revision": "approved-contract-B"}
    if scenario == "same_model_other_transport":
        evaluator.update(provider="openai", model=generator["model"])
    elif scenario == "same_revision":
        evaluator["model_revision"] = generator["model_revision"]
    elif scenario == "unknown_alias":
        evaluator["model"] = "gpt-latest"
    elif scenario == "missing_revision":
        evaluator["model_revision"] = ""
    def receipt(candidate, served):
        return {"provider_id": candidate["provider"], "model_id": candidate["model"], "real_model_call": True,
            "production_execution": {"process_evidence": {"served_model_identity_hash": served}}}
    assert independent_model_identities(generator, evaluator, receipt(generator, "served-A"),
        receipt(evaluator, "served-A" if scenario == "same_served_model" else "served-B")) is (scenario == "distinct")
