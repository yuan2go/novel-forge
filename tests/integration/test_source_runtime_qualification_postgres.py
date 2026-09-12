"""TEST: Synthetic live-shaped receipts exercise D0/Source transactions, not real-model proof."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from dataclasses import replace
from psycopg.errors import LockNotAvailable

from novel_forge.modules.provider_qualification import D0LiveQualificationEvidence, D0ProbeConfig, D0QualificationAuthority, D0QualificationCommand
from novel_forge.modules.provider_qualification.domain import request_hash
from novel_forge.modules.provider_qualification.source_binding import require_source_runtime_qualification
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, dispatch_external_effect, plan_external_effect, reconcile_external_effect
from novel_forge.modules.mkaos_authority import MkaosAuthorityApplication
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, seed_authority_project_book, transaction
from tests.integration.test_d0_provider_qualification_authority_postgres import _ContractOnlyLiveGateway, _RecordingObjectStore
from tests.integration import test_mkaos_authority_postgres as mkaos_fixture

ROOT = Path(__file__).resolve().parents[2]


class SourceRuntimeQualificationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_migrated()

    def test_exact_source_qualification_receipt_approval_replay_and_revocation(self):
        project_id = identifier("d0-live-project")
        book_id = identifier("d0-live-book")
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(project_id=project_id, book_id=book_id)
        authority = D0QualificationAuthority(
            DATABASE_URL,
            evidence_store=_RecordingObjectStore(),
            application_build_id="d0-live-authority-integration",
            commit_sha="a" * 40,
            implementation_identity="sha256:" + "b" * 64,
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
                "route_policy_version": "source-intelligence.mkaos-knowledge-extract.route@1",
                "capability": "mkaos.knowledge.extract",
                "prompt_version": "prompt:retrieval@1",
                "prompt_hash": "sha256:" + "d" * 64,
                "instruction_version": "instruction:retrieval@1",
                "instruction_hash": "sha256:" + "e" * 64,
                "skill_version": "skill:retrieval@1",
                "skill_hash": "sha256:" + "f" * 64,
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
            resolved_model="gpt-5.6-sol",
            resolved_model_version="gpt-5.6-sol",
            resolved_auth_profile_ref="auth:chatgpt-codex-cli",
            implementation_identity="sha256:" + "b" * 64,
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
            "backend_id": "codex-cli",
            "policy_id": "source-intelligence.mkaos-knowledge-extract.route",
            "backend_version": "codex-fixture-v1", "runtime_host_id": "host:qualification-fixture",
            "model_profile_id": "source-intelligence.mkaos-knowledge-extract.default",
            "model_profile_version": 1, "model_profile_hash": "1" * 64,
            "route_policy_hash": "2" * 64, "reasoning_effort": "none",
            "output_schema_ref": "mkaos.knowledge.extract.v1",
            "policy_version": 1,
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
            "result": {"fixture": "candidate"},
            "capability_runtime": {
                "system_instruction": {"content_hash": instruction_hash},
                "prompt_template": {"content_hash": prompt_hash},
                "skill": {"content_hash": skill_hash},
                "output_schema_hash": "sha256:" + "4" * 64,
                "materialization_hash": "sha256:" + "5" * 64,
                "provider_request_envelope_hash": "sha256:" + "6" * 64,
            },
            "production_execution": {
                "execution_request": {
                    "execution_id": f"chapter-execution:{source_operation_id}",
                    "operation_id": source_operation_id, "project_id": project_id,
                    "workspace_id": workspace_id, "capability": "mkaos.knowledge.extract",
                },
                "execution_handle": {
                    "execution_id": f"chapter-execution:{source_operation_id}",
                    "backend_id": "codex-cli",
                    "local_execution_receipt_id": "process-receipt:contract-only",
                    "transport": "LOCAL_CLI_REMOTE_INFERENCE",
                },
                "execution_result": {
                    "execution_id": f"chapter-execution:{source_operation_id}",
                    "outcome": "SUCCEEDED",
                    "normalized_output_ref": "fixture-output", "usage_receipt_ref": "fixture-usage",
                    "cost_receipt_ref": "fixture-cost",
                    "started_at": "2026-09-02T00:00:00+00:00",
                    "completed_at": "2026-09-02T00:00:00.042000+00:00",
                },
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
            "stage": "source.mkaos.extract",
            "_source_intelligence": {"kind": "mkaos"},
            "_production_execution": {"operation_id": source_operation_id, "project_id": project_id,
                                      "workspace_id": workspace_id, "capability_runtime": {
                                          "materialization_hash": "sha256:" + "5" * 64,
                                          "provider_request_envelope_hash": "sha256:" + "6" * 64}},
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
        provider_evidence["production_execution"]["execution_request"]["external_effect_id"] = str(effect["external_effect_id"])
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
                    "failure_kind": "response_loss",
                    "request_sent": True,
                },
                "recovery": {
                    "external_state_was_ambiguous": True,
                    "recovered_without_resend": True,
                    "replayed": True,
                },
                "fixture_protocol_only": False,
                "real_model_call": True,
            }
        )

        with self.assertRaisesRegex(ValueError, "D0 route"):
            authority.execute_live(command, replace(evidence, backend_id="other"))
        result = authority.execute_live(command, evidence)
        replay = authority.execute_live(command, evidence)

        self.assertTrue(adapter.response_lost)
        self.assertEqual(reconciled["outcome"], "success")
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["provider_execution_count"], 1)
        self.assertEqual(result["duplicate_external_effect_count"], 0)
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

        execution = {
            "schema_version": "source-model-call-log.v1", "gateway": "ProductionExecutionGateway",
            "production_execution_gateway_backed": True, "fixture_protocol_only": False,
            "real_provider_proven": True, "production_verified": False,
            "production_execution": provider_evidence["production_execution"], "usage": usage, "cost": cost,
        }
        execution_id = mkaos_fixture.MkaosAuthorityPostgresTests._insert_asset_version(project_id, "model_call_log", execution)
        kwargs = {"project_id": project_id, "workspace_id": workspace_id,
                  "execution_asset_version_id": execution_id, "execution_content_hash": request_hash(execution),
                  "candidate_payload_hash": request_hash(provider_evidence["result"])}
        binding = require_source_runtime_qualification(DATABASE_URL, **kwargs)
        assert binding["report_asset_version_id"] == result["report_asset_version_id"]
        assert binding["scope"]["capability"] == "mkaos.knowledge.extract"
        assert binding["production_effect_proven"] is False
        assert require_source_runtime_qualification(DATABASE_URL, **kwargs, frozen=binding) == binding
        candidate = {"workspace_id": workspace_id, "status": "NEEDS_REVIEW", "lifecycle": "CANDIDATE",
                     "eligibility": "PENDING_EVALUATION", "governance": "CLEAR",
                     "content": {"candidate": provider_evidence["result"], "execution_evidence": {
                         "asset_version_id": execution_id, "content_hash": request_hash(execution),
                         "proof": {"fixture_protocol_only": False, "real_provider_proven": True, "production_verified": False}}}}
        approval = MkaosAuthorityApplication(DATABASE_URL, application_build_id="source-qualification-contract-fixture", commit_sha="a" * 40)
        approval_kwargs = {"project_id": project_id, "workspace_id": workspace_id, "policy_version": "test-governance.v1",
                           "reviewer_id": "fixture-reviewer-not-human", "approval_class": "PRODUCTION"}
        approved_contract = approval._require_approvable(candidate, **approval_kwargs)
        assert approved_contract["provider_runtime_qualification"] == binding
        candidate["content"]["execution_evidence"]["proof"]["production_verified"] = True
        assert approval._require_approvable(candidate, **approval_kwargs)["provider_runtime_qualification"] == binding
        candidate["content"]["execution_evidence"]["proof"]["production_verified"] = False
        assert approval._require_approvable(candidate, **approval_kwargs, frozen_runtime_qualification=binding) == approved_contract
        with self.assertRaisesRegex(KernelError, "SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
            require_source_runtime_qualification(DATABASE_URL, **{**kwargs, "candidate_payload_hash": request_hash({"forged": True})})
        with self.assertRaisesRegex(KernelError, "SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
            require_source_runtime_qualification(DATABASE_URL, **{**kwargs, "workspace_id": workspace_id + ":other"})
        with transaction() as connection:
            assert require_source_runtime_qualification(DATABASE_URL, **kwargs, frozen=binding, approval_cursor=connection.cursor()) == binding
            with self.assertRaises(LockNotAvailable), transaction() as revocation:
                revocation.execute("SET LOCAL lock_timeout='100ms'")
                revocation.execute("UPDATE authority_asset_version SET eligibility='REVOKED' WHERE asset_version_id=%s", [result["report_asset_version_id"]])
        with transaction() as connection:
            connection.cursor().execute("UPDATE authority_asset_version SET eligibility='REVOKED' WHERE asset_version_id=%s", [result["report_asset_version_id"]])
        with self.assertRaisesRegex(KernelError, "SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
            approval._require_approvable(candidate, **approval_kwargs, frozen_runtime_qualification=binding)
