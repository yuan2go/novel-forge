from __future__ import annotations

import json
from pathlib import Path
import unittest

from novel_forge.modules.provider_qualification import (
    D0LiveQualificationEvidence,
    D0ProbeConfig,
    D0QualificationAuthority,
    D0QualificationCommand,
    D0QualificationScheduler,
)
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
    reconcile_external_effect,
)
from novel_forge.modules.provider_control import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


ROOT = Path(__file__).resolve().parents[2]


class _RecordingObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_json(self, *, object_key: str, payload: dict) -> str:
        self.objects[object_key] = json.loads(json.dumps(payload))
        return f"fixture-object://authority-evidence/{object_key}"


class _ContractOnlyLiveGateway:
    provider = "production_execution_gateway"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True
    capability_profile = ProviderCapabilityProfile(
        provider=provider,
        control_level=ProviderControlLevel.V2_CONTROLLED,
        supports_request_timeout=True,
        supports_provider_idempotency=True,
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reconciliation_mode="query",
        real_provider_validation_eligible=True,
    )

    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence
        self.response_lost = False

    def execute(self, **_kwargs: object) -> ProviderResult:
        self.response_lost = True
        raise ExternalEffectAdapterError(
            "contract test lost the response after Provider completion",
            request_sent=True,
        )

    def query(self, **_kwargs: object) -> ProviderResult:
        return ProviderResult(
            "success",
            "process-receipt:contract-only",
            self.evidence,
        )

    def cancel(self, **_kwargs: object) -> ProviderResult:
        return ProviderResult(
            "already_completed",
            "process-receipt:contract-only",
            self.evidence,
        )


class D0ProviderQualificationAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_fixture_protocol_is_persisted_but_real_gates_stay_false(self) -> None:
        project_id = identifier("d0-project")
        book_id = identifier("d0-book")
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(project_id=project_id, book_id=book_id)
        store = _RecordingObjectStore()
        authority = D0QualificationAuthority(
            DATABASE_URL,
            evidence_store=store,
            application_build_id="d0-authority-integration",
            commit_sha="a" * 40,
        )
        command = D0QualificationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id="d0-integration-operator",
            idempotency_key=f"{project_id}:openai:d0:v1",
            trace_id=identifier("d0-trace"),
            correlation_id=identifier("d0-correlation"),
            config=D0ProbeConfig.from_mapping(
                json.loads(
                    (ROOT / "config/provider/d0-openai-probe.json").read_text(
                        encoding="utf-8"
                    )
                )
            ),
        )

        admitted = authority.admit(command)
        scheduler = D0QualificationScheduler(authority)
        self.assertIn(
            (admitted["operation_id"], project_id), scheduler.pending_operations()
        )
        result = scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=project_id
        )
        restarted_store = _RecordingObjectStore()
        replay = D0QualificationScheduler(
            D0QualificationAuthority(
                DATABASE_URL,
                evidence_store=restarted_store,
                application_build_id="d0-authority-integration",
                commit_sha="a" * 40,
                worker_id="integration-worker:d0-restarted",
            )
        ).run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)

        self.assertEqual(result["status"], "BLOCKED_MISSING_CREDENTIALS")
        self.assertEqual(
            replay["report_asset_version_id"], result["report_asset_version_id"]
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(store.objects), 2)
        self.assertEqual(restarted_store.objects, {})
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT effect.external_effect_id),
                       COUNT(DISTINCT receipt.external_receipt_id)
                FROM authority_operation AS operation
                LEFT JOIN authority_attempt AS attempt ON attempt.operation_id=operation.operation_id
                LEFT JOIN authority_external_effect AS effect ON effect.operation_id=operation.operation_id
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                LEFT JOIN authority_external_receipt AS receipt ON receipt.dispatch_id=dispatch.dispatch_id
                WHERE operation.operation_id=%s
                GROUP BY operation.status
                """,
                [result["operation_id"]],
            )
            row = cursor.fetchone()
            # The fixture protocol persists both the synchronous basic receipt and
            # the reconciled unknown-after-send receipt. The cancelled probe has
            # no provider receipt, so replay must preserve exactly two receipts.
            self.assertEqual(row, ("WAITING_GATE", 1, 3, 2))
            cursor.execute(
                """
                SELECT run.fixture_protocol_only, run.decision, run.sdk_max_retries,
                       COUNT(scenario.scenario), BOOL_AND(scenario.request_object_ref <> ''),
                       BOOL_AND(scenario.response_object_ref <> '')
                FROM authority_d0_qualification_run AS run
                JOIN authority_d0_scenario_evidence AS scenario
                  ON scenario.qualification_run_id=run.qualification_run_id
                WHERE run.qualification_run_id=%s
                GROUP BY run.fixture_protocol_only, run.decision, run.sdk_max_retries
                """,
                [result["qualification_run_id"]],
            )
            self.assertEqual(cursor.fetchone(), (True, "BLOCKED", 0, 6, True, True))
            cursor.execute(
                """
                SELECT content->'gates', content->>'status', schema_version
                FROM authority_asset_version WHERE asset_version_id=%s
                """,
                [result["report_asset_version_id"]],
            )
            gates, status, schema_version = cursor.fetchone()
            self.assertFalse(any(gates.values()))
            self.assertEqual(status, "BLOCKED_MISSING_CREDENTIALS")
            self.assertEqual(schema_version, "d0-provider-probe-report.v2")
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_effect_reconciliation_evidence AS evidence
                JOIN authority_external_effect AS effect
                  ON effect.external_effect_id=evidence.external_effect_id
                WHERE effect.operation_id=(
                    SELECT operation_id FROM authority_d0_qualification_run
                    WHERE qualification_run_id=%s
                ) AND evidence.evidence->>'recovered_without_resend'='true'
                """,
                [result["qualification_run_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_only_authority_can_promote_correlated_live_execution_evidence(self) -> None:
        project_id = identifier("d0-live-project")
        book_id = identifier("d0-live-book")
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(project_id=project_id, book_id=book_id)
        authority = D0QualificationAuthority(
            DATABASE_URL,
            evidence_store=_RecordingObjectStore(),
            application_build_id="d0-live-authority-integration",
            commit_sha="a" * 40,
        )
        config = D0ProbeConfig.from_mapping(
            {
                **json.loads(
                    (ROOT / "config/provider/d0-openai-probe.json").read_text(
                        encoding="utf-8"
                    )
                ),
                "provider": "codex-cli",
                "backend_id": "codex-cli",
            }
        )
        command = D0QualificationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id="d0-live-integration-operator",
            idempotency_key=f"{project_id}:codex:d0:v1",
            trace_id=identifier("d0-live-trace"),
            correlation_id=identifier("d0-live-correlation"),
            config=config,
        )
        authority.admit(command)
        source_operation_id = identifier("d0-live-source-operation")
        source_definition = identifier("d0-live-source-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, source_definition)
            insert_operation(
                cursor,
                operation_id=source_operation_id,
                definition_name=source_definition,
                project_id=project_id,
                workspace_id=workspace_id,
                status="EXECUTING",
            )
        prompt_hash = "sha256:" + "d" * 64
        instruction_hash = "sha256:" + "e" * 64
        skill_hash = "sha256:" + "f" * 64
        usage = {
            "measurement": "MEASURED",
            "input_tokens": 11,
            "output_tokens": 3,
            "total_tokens": 14,
        }
        cost = {
            "amount": "0.0001",
            "currency": "USD",
            "estimated": True,
            "provider_billed": False,
            "pricing_snapshot_hash": "sha256:" + "3" * 64,
        }
        route_snapshot = {
            "route_snapshot_id": "route:retrieval@1",
            "release_sha": "a" * 40,
            "model_provider": "codex-cli",
            "model_id": "gpt-5.6-sol",
            "auth_profile_ref": "auth:chatgpt-codex-cli",
        }
        route_hash = request_hash(route_snapshot)
        provider_evidence = {
            "provider_id": "codex-cli",
            "model_id": "gpt-5.6-sol",
            "prompt_version": "prompt:retrieval@1",
            "skill_version": "skill:retrieval@1",
            "real_model_call": True,
            "fixture_protocol_only": False,
            "usage": usage,
            "cost": cost,
            "latency": {"duration_ms": 42},
            "capability_runtime": {
                "prompt_system_instruction_hash": instruction_hash,
                "prompt_template_hash": prompt_hash,
                "skill_content_hash": skill_hash,
            },
            "production_execution": {
                "execution_request": {
                    "execution_id": f"chapter-execution:{source_operation_id}",
                },
                "execution_handle": {
                    "local_execution_receipt_id": "process-receipt:contract-only",
                    "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                },
                "execution_result": {"outcome": "SUCCEEDED"},
                "route_snapshot": route_snapshot,
            },
        }
        context = EffectCommandContext(
            operation_id=source_operation_id,
            project_id=project_id,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        payload = {
            "stage": "d0_qualification",
            "input": {"probe": "d0"},
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
        }
        adapter = _ContractOnlyLiveGateway(provider_evidence)
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="provider.qualification.live",
            provider=adapter.provider,
            capability=config.capability,
            stable_idempotency_key=f"{project_id}:live-effect",
            request_payload=payload,
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
            model_id="gpt-5.6-sol",
            request_timeout_seconds=config.timeout_seconds,
            reconciliation_mode="query",
            provider_capability_profile=adapter.capability_profile.to_dict(),
        )
        with self.assertRaisesRegex(KernelError, "recorded as unknown"):
            dispatch_external_effect(
                DATABASE_URL,
                context,
                effect_id=str(effect["external_effect_id"]),
                worker_id="d0-live-effect-worker",
                lease_seconds=30,
                adapter=adapter,
            )
        reconciled = reconcile_external_effect(
            DATABASE_URL,
            context,
            effect_id=str(effect["external_effect_id"]),
            adapter=adapter,
        )
        evidence = D0LiveQualificationEvidence.from_mapping(
            {
                "schema_version": "d0-live-qualification-evidence.v1",
                "release_sha": "a" * 40,
                "implementation_identity": "sha256:" + "b" * 64,
                "source_operation_id": source_operation_id,
                "external_effect_id": str(effect["external_effect_id"]),
                "request_object_ref": "s3://evidence/d0/request.json",
                "response_object_ref": "s3://evidence/d0/response.json",
                "auth_profile_ref": "auth:chatgpt-codex-cli",
                "provider": "codex-cli",
                "backend_id": "codex-cli",
                "model": "gpt-5.6-sol",
                "model_version": "gpt-5.6-sol",
                "route_snapshot_id": "route:retrieval@1",
                "route_snapshot_hash": route_hash,
                "prompt_version": "prompt:retrieval@1",
                "prompt_hash": prompt_hash,
                "instruction_version": "instruction:retrieval@1",
                "instruction_hash": instruction_hash,
                "skill_version": "skill:retrieval@1",
                "skill_hash": skill_hash,
                "request_hash": request_hash(payload),
                "response_hash": request_hash(provider_evidence),
                "provider_execution_id": f"chapter-execution:{source_operation_id}",
                "provider_request_identity": "process-receipt:contract-only",
                "usage": usage,
                "cost": cost,
                "latency": {"duration_ms": 42},
                "controlled_failure": {
                    "checkpoint": "after_provider_response_before_effect_receipt",
                    "request_sent": True,
                },
                "recovery": {
                    "external_state_was_ambiguous": True,
                    "recovered_without_resend": True,
                    "replayed": True,
                },
                "dispatch_count": 1,
                "receipt_count": 1,
                "provider_execution_count": 1,
                "duplicate_external_effect_count": 0,
                "fixture_protocol_only": False,
                "real_model_call": True,
            }
        )

        result = authority.execute_live(command, evidence)
        replay = authority.execute_live(command, evidence)

        self.assertTrue(adapter.response_lost)
        self.assertEqual(reconciled["outcome"], "success")
        self.assertEqual(result["status"], "PASSED")
        self.assertTrue(replay["replayed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT fixture_protocol_only,status,decision,report_asset_version_id
                FROM authority_d0_qualification_run
                WHERE qualification_run_id=%s
                """,
                [result["qualification_run_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                (False, "COMPLETED", "QUALIFIED", result["report_asset_version_id"]),
            )


if __name__ == "__main__":
    unittest.main()
