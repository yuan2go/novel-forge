from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
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


@pytest.mark.parametrize(
    "scenario", ["success", "unknown_then_reconciled", "terminal_failure"]
)
def test_native_chapter_sample_replays_without_formal_chapter_mutation(
    tmp_path, scenario
):
    h = CapabilityPackPostgresHarness("native-chapter-sampling")
    formal = h.register_compile_approve("1.0.0", generation=1)
    h.activate(h.deploy(formal))
    original = h.run_draft_attempt()
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
    calls = []
    grants = []
    for candidate in deepseek_candidates(available=True)[:2]:
        command = ChapterProviderSampleCommand(
            h.project_id,
            principal.principal_id,
            original["operation_id"],
            "sample:" + candidate.candidate_id,
            h.project_id + ":sample:" + candidate.candidate_id,
        )
        prepared = app.prepare_provider_sample(command, principal=principal)
        assert prepared["provider_calls"] == 0
        grants.append(
            {
                "authorization_id": command.authorization_id,
                "reason": "scripted Chapter boundary regression",
                "environment": "validation",
                "book_id": h.book_ids[0],
                "task_type": "draft",
                "logical_key": command.source_operation_id,
                "generation_idempotency_key": command.idempotency_key,
                "input_versions_hash": prepared["input_versions_hash"],
                "command_hash": prepared["command_hash"],
                "candidate_id": candidate.candidate_id,
                "model_revision": candidate.model_revision,
                "expires_at": expiry,
                "maximum_calls": 1,
                "maximum_tokens": 200000,
                "maximum_amount": "1",
                "currency": "USD",
                "purpose": "BENCHMARK_CHALLENGER",
                "production_eligible": False,
                "campaign": {
                    "campaign_id": h.project_id,
                    "manifest_hash": "sha256:" + "c" * 64,
                    "sample_id": "draft",
                    "group_id": command.source_operation_id,
                    "partition": "CALIBRATION",
                    "maximum_calls": 2,
                    "maximum_tokens": 400000,
                    "maximum_amount": "2",
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

        def fixture_provider(**kwargs):
            calls.append(kwargs)
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
            evidence = deepcopy(original["dispatch_evidence"])
            assert evidence["fixture_protocol_only"]
            evidence.update(real_model_call=False, production_verified=False)
            return ProviderResult(
                "success",
                "chapter-sample-fixture:" + kwargs["stable_idempotency_key"],
                evidence,
            )

        with patch.object(execution.gateway, "execute", side_effect=fixture_provider):
            if scenario == "success":
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
                    evidence = deepcopy(original["dispatch_evidence"])
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
            assert (
                outputs[0][2]["sampled_output"]["text"]
                == original["draft_content"]["text"]
            )
            uow.cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [original["operation_id"]],
            )
            assert uow.cursor.fetchone() == ("SUCCEEDED",)
    assert len(calls) == 2
    campaign = PostgresRoutingRegistry(DATABASE_URL).campaign(
        project_id=h.project_id, campaign_id=h.project_id
    )
    assert campaign["usage"]["calls_used_or_reserved"] == 2
    assert len(campaign["operations"]) == 2
