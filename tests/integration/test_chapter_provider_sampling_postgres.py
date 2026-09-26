from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash
from novel_forge.modules.chapter_authority.execution_gateway import (
    _RecoveryAuthorizedGatewayAdapter,
    chapter_producer_contract_identity,
)

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authority_handler_runtime.policy_commands import (
    configure_owned_policy,
)
from novel_forge.modules.capability_packs.validation_deployment import (
    install_chapter_validation_pack,
    register_validation_runtime_definitions,
)
from novel_forge.modules.chapter_authority.sampling import ChapterProviderSampleCommand
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
from novel_forge.modules.production_execution.routing_runtime import (
    ProductionProviderRouter,
    PostgresRoutingRegistry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
    ROOT,
)


def native_reviewer_source(h, tmp_path, original, stage):
    settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
    env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
           "NOVEL_FORGE_COMMIT_SHA": h.release_sha, "NOVEL_FORGE_APPLICATION_BUILD_ID": h.application_build_id,
           "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": h.pack_id, "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)}
    app = build_chapter_authority_application(settings, execution=build_production_execution_composition(settings, env=env), env=env)
    scheduler = app.scheduler(principal=Principal(principal_id="reference-source-fixture-worker", principal_type=PrincipalType.WORKER,
        permissions=frozenset({"chapter.authority.execute"}), project_scope=frozenset({h.project_id}), authentication_source="integration-fixture"))
    for _ in range(20):
        tick = scheduler.tick(project_id=h.project_id, root_operation_id=original["root_operation_id"])
        assert tick.operation_status == "SUCCEEDED", tick
        if tick.node == stage:
            break
    else:
        raise AssertionError("native reviewer source was not reached")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""SELECT effect.operation_id,effect.request_payload,dispatch.evidence
            FROM authority_external_effect effect JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
            WHERE effect.project_id=%s AND effect.operation_id=%s AND dispatch.status='SUCCEEDED'""", [h.project_id, tick.operation_id])
        row = uow.cursor.fetchone()
        assert row is not None
    return {**original, "operation_id": row[0], "effect_request_payload": row[1], "dispatch_evidence": row[2]}


def fixture_adjudicated_reference(h, original, stage, *, sample_target=None, live_shape=False, generator_contract=None):
    from novel_forge.modules.content_authority import CONTENT_CODECS
    from novel_forge.modules.content_authority.application import ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.chapter_quality_authority.reference_sampling import reference_dimensions

    app = ContentAuthorityApplication(DATABASE_URL, application_build_id=h.application_build_id,
        commit_sha=h.release_sha, integration_proven=CONTENT_CODECS, trusted_only=True)
    if sample_target is None:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("""SELECT version.asset_version_id,version.content_hash FROM authority_asset_version version
            JOIN authority_asset asset USING(asset_id) JOIN authority_operation operation ON operation.project_id=asset.project_id
            WHERE operation.operation_id=%s AND asset.asset_type=%s
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(operation.input_asset_snapshot) input
                          WHERE input->>'asset_version_id'=version.asset_version_id)""",
            [original["operation_id"], "draft_chapter" if stage == "review" else "best_draft_candidate"])
            target = dict(zip(("asset_version_id", "content_hash"), uow.cursor.fetchone(), strict=True))
        result = original["dispatch_evidence"]["result"]
    else:
        target = sample_target
        result = {"decision": "PASSED"}

    def author(name, actor, payload, inputs):
        if sample_target is not None:
            payload = {**payload, "reference_sample": target}
        written = app.execute(ContentOperationRequest(name, h.project_id, h.workspace_id, actor,
            "fixture", "fixture", h.project_id + ":" + target["asset_version_id"] + ":" + actor + ":" + payload[next(iter(payload))]["dimension"],
            payload, tuple(inputs)), principal=Principal(principal_id=actor, principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"content.authority.execute", "content.operation:" + name}),
                project_scope=frozenset({h.project_id}), authentication_source="integration-fixture"))
        return {"asset_version_id": written.asset_version_id, "content_hash": written.content_hash}

    adjudications = []
    dimensions = generator_contract["dimensions"] if generator_contract and generator_contract["dimensions"] else reference_dimensions(stage)
    for dimension in dimensions:
        entry = {"gate_status": result["decision"], "score": 80} if stage in {"review", "rereview", "memo", "canon_extraction"} else next(item for item in result["dimensions"] if item["dimension"] == dimension)
        shared = {"subject_asset_version_id": target["asset_version_id"], "dimension": dimension,
            "status": entry["gate_status"], "protocol_version": generator_contract["protocol_version"] if generator_contract else "fixture-blind-reference-v1",
            "evaluation_version": generator_contract["evaluation_version"] if generator_contract else "fixture-review-labels-v1", "scope_type": "CHAPTER", "chapter_start": 1, "chapter_end": 1}
        humans = []
        for ordinal in (1, 2):
            actor = h.principal("fixture-human-" + str(ordinal)).principal_id
            humans.append(author("quality.human_evaluation.record", actor, {"evaluation": {
                **shared, "evaluation_id": h.project_id + ":" + dimension + ":human:" + str(ordinal),
                "evaluator_id": actor, "evaluator_group": "synthetic-native-shaped-contract-test" if live_shape else "SCRIPTED_INTEGRATION_FIXTURE",
                "evaluator_identity_class": "PROFESSIONAL_EDITOR", "score": entry.get("score"),
                "confidence": 0.8, "evidence": [{"fixture_protocol_only": not live_shape, "span": [0, 5]}], "blind": True,
            }}, [target]))
        actor = h.principal("fixture-adjudicator").principal_id
        adjudications.append(author("quality.adjudication.record", actor, {"adjudication": {
            **shared, "adjudication_id": h.project_id + ":" + dimension + ":adjudication", "adjudicator_id": actor,
            "adjudicator_identity_class": "PROFESSIONAL_EDITOR", "score_range": [78, 82] if generator_contract else [0, 100],
            "source_human_evaluation_asset_version_ids": [row["asset_version_id"] for row in humans],
            "rationale": "Scripted labels exercise provenance only; no human quality claim.",
        }}, [target, *humans]))
    return {"protocol_version": generator_contract["protocol_version"] if generator_contract else "fixture-blind-reference-v1", "adjudications": adjudications}


@pytest.mark.parametrize("stage,scenario", [
    *(("draft", scenario) for scenario in ("success", "unknown_then_reconciled", "terminal_failure", "producer_drift")),
    ("review", "success"), ("review", "unknown_then_reconciled"), ("quality_structural", "success"),
    ("revision", "success"), ("review", "reference_feedback"), ("draft", "generator_feedback"), ("memo", "generator_feedback"),
])
def test_native_chapter_sample_replays_without_formal_chapter_mutation(
    tmp_path, scenario, stage
):
    h = CapabilityPackPostgresHarness("native-chapter-sampling")
    formal = h.register_compile_approve("1.0.0", generation=1)
    h.activate(h.deploy(formal))
    profiles = ()
    if stage.startswith("quality_"):
        from tests.integration.test_chapter_model_effects_postgres import ChapterModelEffectsPostgresTests
        profiles = tuple(item for item in ChapterModelEffectsPostgresTests()._release_evidence(h.project_id)
                         if item["asset_type"] in {"quality_rubric", "platform_profile"})
    original = h.run_draft_attempt(extra_context_candidates=profiles)
    reference = None
    if stage == "memo":
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("""SELECT effect.operation_id,effect.request_payload,dispatch.evidence
                FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
                JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
                WHERE effect.project_id=%s AND operation.definition_name='chapter.memo.generate' AND dispatch.status='SUCCEEDED'""", [h.project_id])
            row = uow.cursor.fetchone()
            assert row is not None
        original = {**original, "operation_id": row[0], "effect_request_payload": row[1], "dispatch_evidence": row[2]}
    elif stage != "draft":
        original = native_reviewer_source(h, tmp_path, original, stage)
        if stage != "revision":
            reference = fixture_adjudicated_reference(h, original, stage, live_shape=scenario == "reference_feedback")
    original_runtime = original["effect_request_payload"]["_production_execution"][
        "capability_runtime"
    ]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [original_runtime["materialization_asset_version_id"]],
        )
        materialization = uow.cursor.fetchone()[0]
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [original_runtime["provider_admission_asset_version_id"]],
        )
        admission = uow.cursor.fetchone()[0]
    formal_contract = chapter_producer_contract_identity(
        admission.get("contract", admission)["prompt_materialization"],
        materialization.get("contract", materialization),
    )
    register_validation_runtime_definitions(
        DATABASE_URL,
        application_build_id=h.application_build_id,
        commit_sha=h.release_sha,
    )
    install_chapter_validation_pack(
        DATABASE_URL,
        repository_root=ROOT,
        project_id=h.project_id,
        workspace_id=h.workspace_id,
        book_id=h.book_ids[0],
        application_build_id=h.application_build_id,
        commit_sha=h.release_sha,
        compiler=h.compiler,
        approver=h.approver,
        agent_admin=h.agent_admin,
        pack_id_override=h.pack_id,
        provider_sampling=True,
        reference_sampling=reference is not None,
    )
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_COMMIT_SHA": h.release_sha,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": h.application_build_id,
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": h.pack_id,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path),
    }
    settings = IndustrialSettings(
        root=ROOT,
        environment="development",
        storage_authority="postgresql",
        database_url=DATABASE_URL,
    )
    execution = build_production_execution_composition(settings, env=env)
    execution.gateway.routes = {
        stage: replace(route, model_context_limit=200000)
        for stage, route in execution.gateway.routes.items()
    }
    app = build_chapter_authority_application(settings, execution=execution, env=env)
    binder = app._model_port.capability_binder
    binder.pack_environment = binder.pack_runtime_profile = "validation"
    binder.provider_router = ProductionProviderRouter(
        DATABASE_URL,
        candidates=deepseek_candidates(available=True),
        execution_environment="validation",
        task_money_limit="1",
        task_token_limit=200000,
    )
    app._model_port.max_cost_per_call = "1"
    principal = h.principal(
        "sample-operator",
        "chapter.authority.execute",
        "provider.routing_policy.configure",
        "book.authority.execute",
    )
    scheduler = app.scheduler(
        principal=Principal(
            principal_id="chapter-sample-worker",
            principal_type=PrincipalType.WORKER,
            permissions=frozenset({"chapter.authority.execute"}),
            project_scope=frozenset({h.project_id}),
            authentication_source="integration-fixture",
        )
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    from tests.unit.test_creative_budget_contract import provider_campaign_policy
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
    from novel_forge.modules.command_kernel.budget_runtime import provider_usage_accounted_sql

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(f"SELECT count(*) FROM authority_budget_reservation WHERE project_id=%s AND {provider_usage_accounted_sql()}", [h.project_id])
        original_calls = uow.cursor.fetchone()[0]
    assert original_calls > 0

    campaign_policy = provider_campaign_policy()
    arm = campaign_policy["comparison_budget"]["arms"][0]
    arm.update(project_id=h.project_id, book_id=h.book_ids[0])
    from novel_forge.modules.command_kernel.creative_budget_runtime import _usage
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        historical = _usage(uow.cursor, campaign_policy["comparison_budget"], h.project_id)
    sampling_phase = "REFERENCE" if reference else "CALIBRATION"
    cold_start = stage in {"draft", "revision"} and scenario in {"success", "generator_feedback"}
    cold_stage = "rereview" if stage == "revision" else "review"
    for phase, allocation in campaign_policy["authorization"]["authorized_cumulative_caps"].items():
        prior_calls = historical["phases"][phase]["calls_used_or_reserved"]
        allocation.update(calls=2 if phase == sampling_phase else prior_calls,
                          tokens=400000 if phase == sampling_phase else 1000000 if prior_calls else 0,
                          priced_usd="2" if phase == sampling_phase else "1" if prior_calls else "0")
        if cold_start and phase == "REFERENCE":
            allocation.update(calls=prior_calls + 1, tokens=200000, priced_usd="1")
        arm[phase.lower() + "_allocation"] = dict(allocation)
    allocations = campaign_policy["authorization"]["authorized_cumulative_caps"].values()
    totals = {**{key: sum(row[key] for row in allocations) for key in ("calls", "tokens")},
              "priced_usd": str(sum(int(row["priced_usd"]) for row in allocations))}
    arm["project_total"] = totals
    campaign_policy["comparison_budget"].update(experiment_id=h.project_id, expires_at=expiry,
                                              shared_total=totals, entitlements=[])
    campaign_policy["authorization"].update(project_id=h.project_id, book_id=h.book_ids[0])
    configure_owned_policy(database_url=DATABASE_URL, owner="CREATIVE_EXPERIMENT_BUDGET",
        project_id=h.project_id, workspace_id=h.workspace_id, content=campaign_policy,
        idempotency_key=h.project_id + ":campaign-budget", trace_id="fixture", correlation_id="fixture",
        application_build_id=h.application_build_id, commit_sha=h.release_sha, principal=principal)
    calls = []
    grants = []
    for candidate in deepseek_candidates(available=True)[:2]:
        command = ChapterProviderSampleCommand(
            h.project_id,
            principal.principal_id,
            original["operation_id"],
            "sample:" + candidate.candidate_id,
            h.project_id + ":sample:" + candidate.candidate_id,
            reference_evaluation=reference,
        )
        prepared = app.prepare_provider_sample(command, principal=principal)
        assert prepared["provider_calls"] == 0
        if reference:
            changed = deepcopy(reference)
            changed["adjudications"][0]["content_hash"] = "sha256:" + "0" * 64
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_PROVENANCE_INVALID"):
                app.prepare_provider_sample(replace(command, reference_evaluation=changed), principal=principal)
            changed = {**reference, "protocol_version": "another-label-protocol"}
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
                app.prepare_provider_sample(replace(command, reference_evaluation=changed), principal=principal)
            human = h.principal("fixture-human-1", "chapter.authority.execute")
            with pytest.raises(KernelError, match="QUALITY_REFERENCE_NOT_INDEPENDENT"):
                app.prepare_provider_sample(replace(command, actor_id=human.principal_id), principal=human)
            if len(reference["adjudications"]) > 1:
                changed = {**reference, "adjudications": reference["adjudications"][:-1]}
                with pytest.raises(KernelError, match="QUALITY_REFERENCE_COVERAGE_INCOMPLETE"):
                    app.prepare_provider_sample(replace(command, reference_evaluation=changed), principal=principal)
        grants.append(
            {
                "authorization_id": command.authorization_id,
                "reason": "scripted Chapter boundary regression",
                "environment": "validation",
                "book_id": h.book_ids[0],
                "task_type": stage,
                "logical_key": command.source_operation_id,
                "generation_idempotency_key": command.idempotency_key,
                "input_versions_hash": prepared["input_versions_hash"],
                "command_hash": prepared["command_hash"],
                "producer_contract_hash": authorization_hash(formal_contract),
                "candidate_id": candidate.candidate_id,
                "model_revision": candidate.model_revision,
                "expires_at": expiry,
                "maximum_calls": 1,
                "maximum_tokens": 200000,
                "maximum_amount": "1",
                "currency": "USD",
                "purpose": "REFERENCE_EVALUATION" if reference else "BENCHMARK_CHALLENGER",
                **({"reference_evaluation": reference} if reference else {}),
                "production_eligible": False,
                "campaign": {
                    "campaign_id": h.project_id,
                    "manifest_hash": "sha256:" + "c" * 64,
                    "sample_id": stage,
                    "group_id": command.source_operation_id,
                    "partition": "CALIBRATION",
                    "maximum_calls": 3 if cold_start else 2,
                    "maximum_tokens": 600000 if cold_start else 400000,
                    "maximum_amount": "3" if cold_start else "2",
                    "expires_at": expiry,
                },
            }
        )
        configure_owned_policy(
            database_url=DATABASE_URL,
            owner="PROVIDER_ROUTING",
            project_id=h.project_id,
            workspace_id=h.workspace_id,
            content={
                "policy_version": f"sampling:{len(grants)}",
                "reason": "fixture-only",
                "task_overrides": [],
                "bootstrap_authorizations": grants,
            },
            idempotency_key=f"{h.project_id}:sampling-policy:{len(grants)}",
            trace_id="fixture",
            correlation_id="fixture",
            application_build_id=h.application_build_id,
            commit_sha=h.release_sha,
            principal=principal,
        )

        def reject_replacement():
            successor = replace(
                command,
                authorization_id=command.authorization_id + ":replacement",
                idempotency_key=command.idempotency_key + ":replacement",
                predecessor_operation_id=admitted["operation_id"],
            )
            preview = app.prepare_provider_sample(successor, principal=principal)
            grants.append(
                {
                    **grants[-1],
                    "authorization_id": successor.authorization_id,
                    "generation_idempotency_key": successor.idempotency_key,
                    "command_hash": preview["command_hash"],
                }
            )
            configure_owned_policy(
                database_url=DATABASE_URL,
                owner="PROVIDER_ROUTING",
                project_id=h.project_id,
                workspace_id=h.workspace_id,
                content={
                    "policy_version": f"sampling:{len(grants)}",
                    "reason": "fixture-only",
                    "task_overrides": [],
                    "bootstrap_authorizations": grants,
                },
                idempotency_key=f"{h.project_id}:sampling-policy:{len(grants)}",
                trace_id="fixture",
                correlation_id="fixture",
                application_build_id=h.application_build_id,
                commit_sha=h.release_sha,
                principal=principal,
            )
            with pytest.raises(
                KernelError, match="CHAPTER_SAMPLE_PREDECESSOR_NOT_REPLACEABLE"
            ):
                app.admit_provider_sample(successor, principal=principal)

        admitted = app.admit_provider_sample(command, principal=principal)
        assert (
            app.admit_provider_sample(command, principal=principal)["operation_id"]
            == admitted["operation_id"]
        )
        assert admitted["operation_id"] != original["operation_id"]

        def fixture_evidence(kwargs):
            evidence = deepcopy(original["dispatch_evidence"])
            evidence.update(real_model_call=False, production_verified=False)
            metadata = kwargs["request_payload"]["_production_execution"]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND stable_idempotency_key=%s",
                    [metadata["operation_id"], kwargs["stable_idempotency_key"]])
                effect_id = uow.cursor.fetchone()[0]
            evidence["production_execution"]["execution_request"].update(
                {key: metadata[key] for key in ("operation_id", "attempt_id", "project_id")}, external_effect_id=effect_id)
            return evidence

        def fixture_provider(**kwargs):
            calls.append(kwargs)
            if reference:
                import json
                assert "fixture-blind-reference-v1" not in json.dumps(kwargs["request_payload"].get("input", {}))
            runtime = kwargs["request_payload"]["_production_execution"][
                "capability_runtime"
            ]
            assert (
                runtime["routing_decision"]["task"]["producer_contract"]
                == formal_contract
            )
            if scenario == "unknown_then_reconciled":
                return ProviderResult(
                    "unknown",
                    "chapter-sample-unknown:" + kwargs["stable_idempotency_key"],
                    {"fixture_protocol_only": True},
                )
            if scenario == "terminal_failure":
                return ProviderResult(
                    "final_failure",
                    "chapter-sample-failed:" + kwargs["stable_idempotency_key"],
                    {
                        "fixture_protocol_only": True,
                        "real_model_call": False,
                        "request_sent": True,
                        "production_execution": {
                            "process_evidence": {
                                "submission_phase": "PROVIDER_RESULT_RECORDED"
                            }
                        },
                    },
                )
            evidence = fixture_evidence(kwargs)
            assert evidence["fixture_protocol_only"]
            evidence.update(real_model_call=False, production_verified=False)
            if scenario in {"reference_feedback", "generator_feedback"}:
                evidence.update(real_model_call=True, fixture_protocol_only=False, provider_id=candidate.provider, model_id=candidate.model)
                evidence["production_execution"]["route_snapshot"]["reasoning_effort"] = candidate.reasoning
                evidence["production_execution"].setdefault("process_evidence", {})["served_model_identity_hash"] = "sha256:" + "f" * 64
                if scenario == "reference_feedback" and len(calls) == 2:
                    evidence["result"]["decision"] = "PASSED" if evidence["result"]["decision"] != "PASSED" else "NEEDS_REVISION"
                    if evidence["result"]["decision"] == "PASSED":
                        evidence["result"]["issues"] = []
            return ProviderResult(
                "success",
                "chapter-sample-fixture:" + kwargs["stable_idempotency_key"],
                evidence,
            )

        with patch.object(execution.gateway, "execute", side_effect=fixture_provider):
            if scenario == "producer_drift":
                with patch(
                    "novel_forge.modules.chapter_authority.execution_gateway.chapter_producer_contract_identity",
                    return_value={**formal_contract, "context_policy": {"version": "changed-after-authorization"}},
                ), pytest.raises(KernelError, match="ROUTING_BOOTSTRAP_PRODUCER_DRIFT"):
                    scheduler.tick(project_id=h.project_id, root_operation_id=admitted["operation_id"])
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [admitted["operation_id"]])
                    assert uow.cursor.fetchone() == (0,)
                    uow.cursor.execute("SELECT count(*) FROM authority_budget_reservation WHERE operation_id=%s", [admitted["operation_id"]])
                    assert uow.cursor.fetchone() == (0,)
                continue
            if scenario in {"success", "reference_feedback", "generator_feedback"}:
                tick = scheduler.tick(
                    project_id=h.project_id, root_operation_id=admitted["operation_id"]
                )
                assert tick.operation_status == "SUCCEEDED"
                assert tick.saga_status == "SUCCEEDED"
            else:
                with pytest.raises(KernelError):
                    scheduler.tick(
                        project_id=h.project_id,
                        root_operation_id=admitted["operation_id"],
                    )
                before_recovery = PostgresRoutingRegistry(DATABASE_URL).campaign(
                    project_id=h.project_id, campaign_id=h.project_id
                )
                reservation = next(
                    row
                    for row in before_recovery["reservations"]
                    if row["operation_id"] == admitted["operation_id"]
                )
                if scenario == "terminal_failure":
                    assert reservation["reservation_status"] == "SETTLED"
                    assert (
                        reservation["actual_tokens"] == reservation["estimated_tokens"]
                    )
                    terminal = scheduler.tick(
                        project_id=h.project_id,
                        root_operation_id=admitted["operation_id"],
                    )
                    assert terminal.saga_status == "MANUAL_INTERVENTION"
                    assert terminal.operation_status == "FAILED_FINAL"
                    continue
                assert reservation["reservation_status"] == "HELD_UNKNOWN"
                assert before_recovery["state"] == "RECONCILIATION_REQUIRED"
                reject_replacement()

                def recovered_provider(_adapter, **kwargs):
                    evidence = fixture_evidence(kwargs)
                    evidence.update(real_model_call=False, production_verified=False)
                    return ProviderResult(
                        "success",
                        "chapter-sample-recovered:" + kwargs["stable_idempotency_key"],
                        evidence,
                    )

                with patch.object(
                    _RecoveryAuthorizedGatewayAdapter, "query", recovered_provider
                ):
                    tick = scheduler.tick(
                        project_id=h.project_id,
                        root_operation_id=admitted["operation_id"],
                    )
                    assert tick.operation_status == "SUCCEEDED"
                    assert tick.saga_status == "SUCCEEDED"
            replay = scheduler.tick(
                project_id=h.project_id, root_operation_id=admitted["operation_id"]
            )
            assert replay.recovery_mode == "terminal_replay"
            if scenario == "success":
                reject_replacement()
        result = app.query.require_provider_sample(
            project_id=h.project_id, operation_id=admitted["operation_id"]
        )
        assert result["status"] == "SUCCEEDED"
        assert not result["production_eligible"]
        if cold_start:
            target = next({key: item[key] for key in ("asset_version_id", "content_hash")}
                          for item in result["outputs"] if item["asset_type"] == "chapter_provider_sample")
            from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract
            labels = fixture_adjudicated_reference(h, original, cold_stage, sample_target=target,
                live_shape=scenario == "generator_feedback", generator_contract=generator_reference_contract(stage, authorization_hash(formal_contract))
                if scenario == "generator_feedback" else None)
            from novel_forge.modules.chapter_quality_authority.reference_sampling import require_adjudicated_reference
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_reference_annotation
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                from novel_forge.storage.chapter_authority_repositories import AuthorityHandlerRepository
                with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
                    AuthorityHandlerRepository(uow.cursor).frozen_inputs(h.project_id, [target])
                verified = require_adjudicated_reference(uow.cursor, project_id=h.project_id, binding=labels,
                    target_id=target["asset_version_id"], target_hash=target["content_hash"],
                    generators=[principal.principal_id], evaluator_actor_id="another-fixture-evaluator", chapter=1,
                    expected_dimensions=(cold_stage + "_decision",), allowed_statuses={"PASSED", "NEEDS_REVISION", "BLOCKED"})
                assert verified["production_qualification_eligible"] is False
                for invalid in (
                    {"reference_sample": {**target, "content_hash": "sha256:" + "f" * 64},
                     "evaluation": {"subject_asset_version_id": target["asset_version_id"], "evaluator_id": "author"}},
                    {"reference_sample": target,
                     "evaluation": {"subject_asset_version_id": target["asset_version_id"], "evaluator_id": "different-author"}},
                ):
                    with pytest.raises(KernelError, match="QUALITY_REFERENCE_"):
                        require_reference_annotation(uow.cursor, project_id=h.project_id,
                            definition_name="quality.human_evaluation.record", payload=invalid, actor_id="author")
                uow.cursor.execute("SELECT eligibility FROM authority_asset_version WHERE asset_version_id=%s", [target["asset_version_id"]])
                assert uow.cursor.fetchone() == ("INELIGIBLE",)
        with pytest.raises(KernelError, match="CHAPTER_SAMPLE_NOT_FOUND"):
            app.query.require_provider_sample(
                project_id="another-project", operation_id=admitted["operation_id"]
            )
        if scenario == "unknown_then_reconciled":
            assert (
                sum(
                    row["role"] == "model_failure_evidence" for row in result["outputs"]
                )
                == 1
            )
            assert (
                sum(row["asset_type"] == "model_call_log" for row in result["outputs"])
                == 2
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """SELECT a.asset_type,v.eligibility,v.content FROM authority_operation_output_asset o
                JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
                WHERE o.operation_id=%s""",
                [admitted["operation_id"]],
            )
            outputs = uow.cursor.fetchall()
            assert not {row[0] for row in outputs}.intersection(
                {"draft_chapter", "draft_version", "canon_patch", "chapter_outcome"}
            )
            outputs = [row for row in outputs if row[0] == "chapter_provider_sample"]
            assert len(outputs) == 1
            assert outputs[0][:2] == ("chapter_provider_sample", "INELIGIBLE")
            assert outputs[0][2]["production_eligible"] is False
            if reference:
                agreement = outputs[0][2]["reference_evaluation"]
                assert agreement["status_accuracy"] == (0 if scenario == "reference_feedback" and len(calls) == 2 else 1)
                assert agreement["real_model_call"] is (scenario == "reference_feedback")
                assert agreement["calibration_claim_allowed"] is False
                assert agreement["production_qualification_eligible"] is False
            else:
                assert {key: outputs[0][2]["sampled_output"][key] for key in original["dispatch_evidence"]["result"]} == original["dispatch_evidence"]["result"]
            uow.cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [original["operation_id"]],
            )
            assert uow.cursor.fetchone() == ("SUCCEEDED",)
        if stage == "memo" and scenario == "generator_feedback":
            from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract
            target = next({key: item[key] for key in ("asset_version_id", "content_hash")}
                          for item in result["outputs"] if item["asset_type"] == "chapter_provider_sample")
            fixture_adjudicated_reference(h, original, stage, sample_target=target, live_shape=True,
                generator_contract=generator_reference_contract(stage, authorization_hash(formal_contract)))
        from novel_forge.modules.authority_handler_runtime.routing_feedback import domain_gate_outcomes
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s", [admitted["operation_id"]])
            effect_id = uow.cursor.fetchone()[0]
            projected = domain_gate_outcomes(uow.cursor, project_id=h.project_id, effect_ids=[effect_id])
        if scenario == "reference_feedback":
            assert projected[effect_id]["reference_agreed"] is (len(calls) == 1)
            assert projected[effect_id]["reference_label_classes"] == (("PASS" if original["dispatch_evidence"]["result"]["decision"] == "PASSED" else "FAIL"),)
            assert projected[effect_id]["accepted"] is None
            registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=domain_gate_outcomes)
            observations = registry.observations(project_id=h.project_id, task_type=stage, candidate=candidate,
                producer_contract_hash=authorization_hash(formal_contract))
            assert len(observations) == 1
            assert observations[0].reference_agreed is (len(calls) == 1)
            assert observations[0].evidence_class == "REFERENCE_EVALUATION"
            assert observations[0].sample_identity == projected[effect_id]["reference_sample_identity"]
        elif stage == "memo" and scenario == "generator_feedback":
            assert projected[effect_id]["generator_quality_score"] == .78
            assert projected[effect_id]["sample_promoted"] is False
            observed = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=domain_gate_outcomes).observations(
                project_id=h.project_id, task_type=stage, candidate=candidate, producer_contract_hash=authorization_hash(formal_contract))
            assert len(observed) == 1 and observed[0].generator_quality_score == .78
        else:
            assert not projected
    if cold_start:
        install_chapter_validation_pack(DATABASE_URL, repository_root=ROOT, project_id=h.project_id,
            workspace_id=h.workspace_id, book_id=h.book_ids[0], application_build_id=h.application_build_id,
            commit_sha=h.release_sha, compiler=h.compiler, approver=h.approver, agent_admin=h.agent_admin,
            pack_id_override=h.pack_id, provider_sampling=True, reference_sampling=True, reference_samples=True)
        cold_command = replace(command, generation_sample=target, reference_stage=cold_stage, reference_evaluation=labels,
            authorization_id="fixture-review-coldstart", idempotency_key=h.project_id + ":review-coldstart")
        prepared = app.prepare_provider_sample(cold_command, principal=principal)
        assert prepared["definition_version"] == "1.1.0"
        grants.append({**grants[0], "authorization_id": cold_command.authorization_id, "task_type": cold_stage,
            "generation_idempotency_key": cold_command.idempotency_key, "command_hash": prepared["command_hash"],
            "input_versions_hash": prepared["input_versions_hash"], "producer_contract_hash": prepared["producer_contract_hash"],
            "purpose": "REFERENCE_EVALUATION", "reference_evaluation": labels,
            "campaign": {**grants[0]["campaign"], "sample_id": "review-coldstart"}})
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=h.project_id,
            workspace_id=h.workspace_id, content={"policy_version": "coldstart", "reason": "fixture-only",
                "task_overrides": [], "bootstrap_authorizations": grants}, idempotency_key=h.project_id + ":coldstart-policy",
            trace_id="fixture", correlation_id="fixture", application_build_id=h.application_build_id,
            commit_sha=h.release_sha, principal=principal)
        cold = app.admit_provider_sample(cold_command, principal=principal)

        def review_sample_provider(**kwargs):
            from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
            from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
            from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
            calls.append(kwargs)
            runtime = kwargs["request_payload"]["_production_execution"]["capability_runtime"]
            assert runtime["routing_decision"]["task"]["producer_contract"] == prepared["producer_contract"]
            provider_view = build_provider_task_view(cold_stage, kwargs["request_payload"]["input"])
            assert "fixture-blind-reference-v1" not in str(provider_view)
            assert "provider_evidence" not in str(provider_view)
            evidence = fixture_evidence(kwargs)
            evidence["result"] = normalize_model_output(cold_stage, default_chapter_fixture_response(cold_stage, kwargs["request_payload"]["input"]))
            if scenario == "generator_feedback":
                reviewer = runtime["routing_decision"]["selected"]["candidate"]
                evidence.update(real_model_call=True, fixture_protocol_only=False, provider_id=reviewer["provider"], model_id=reviewer["model"])
                evidence["production_execution"]["route_snapshot"]["reasoning_effort"] = reviewer["reasoning"]
                evidence["production_execution"].setdefault("process_evidence", {})["served_model_identity_hash"] = "sha256:" + "e" * 64
            return ProviderResult("success", "fixture-review-coldstart:" + kwargs["stable_idempotency_key"], evidence)

        with patch.object(execution.gateway, "execute", side_effect=review_sample_provider):
            assert scheduler.tick(project_id=h.project_id, root_operation_id=cold["operation_id"]).operation_status == "SUCCEEDED"
            assert scheduler.tick(project_id=h.project_id, root_operation_id=cold["operation_id"]).recovery_mode == "terminal_replay"
        with patch.object(binder.pack_resolver, "resolve_in_uow", side_effect=AssertionError("replay must use its frozen Pack")):
            assert app.prepare_provider_sample(cold_command, principal=principal)["producer_contract"] == prepared["producer_contract"]
            assert app.admit_provider_sample(cold_command, principal=principal)["operation_id"] == cold["operation_id"]
        reviewed = app.query.require_provider_sample(project_id=h.project_id, operation_id=cold["operation_id"])
        cold_output = next(item["sample"] for item in reviewed["outputs"] if item["asset_type"] == "chapter_provider_sample")
        assert cold_output["reference_evaluation"]["target_asset_version_id"] == target["asset_version_id"]
        assert cold_output["reference_evaluation"]["calibration_claim_allowed"] is False
        if scenario == "generator_feedback":
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                projected = domain_gate_outcomes(uow.cursor, project_id=h.project_id, effect_ids=[effect_id])
            assert projected[effect_id]["generator_quality_score"] == .78
            assert projected[effect_id]["sample_promoted"] is False
            registry = PostgresRoutingRegistry(DATABASE_URL, outcome_projection=domain_gate_outcomes)
            observed = registry.observations(project_id=h.project_id, task_type=stage, candidate=candidate,
                producer_contract_hash=authorization_hash(formal_contract))
            assert len(observed) == 1 and observed[0].generator_quality_score == .78
            from novel_forge.modules.production_execution.cost_routing import benchmark_snapshot, task_policy
            admission = benchmark_snapshot(observed, now=datetime.now(timezone.utc), policy=task_policy(stage), input_tokens=observed[0].generator_context_tokens)
            assert admission["uncertain"] and admission["production_acceptance_sample_count"] == 0
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND definition_name=%s",
                [h.project_id, "chapter.revision.review" if cold_stage == "rereview" else "chapter.review.evaluate"])
            assert uow.cursor.fetchone() == (0,)
    expected_calls = 0 if scenario == "producer_drift" else 3 if cold_start else 2
    assert len(calls) == expected_calls
    campaign = PostgresRoutingRegistry(DATABASE_URL).campaign(
        project_id=h.project_id, campaign_id=h.project_id
    )
    assert campaign["usage"]["calls_used_or_reserved"] == expected_calls
    assert len(campaign["operations"]) == (3 if cold_start else 2)
    cumulative = get_creative_budget(DATABASE_URL, h.project_id)["budget_usage"]
    assert cumulative["project_total"]["calls_used_or_reserved"] == expected_calls + original_calls
    assert cumulative["phases"][sampling_phase]["calls_used_or_reserved"] == expected_calls - int(cold_start)
