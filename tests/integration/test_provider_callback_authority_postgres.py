from __future__ import annotations

import hashlib
import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
)
from novel_forge.modules.provider_callback_authority import (
    ProviderCallbackAcceptCommand,
    ProviderCallbackAuthorityService,
)
from novel_forge.modules.provider_control import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderAdapterRegistry,
    ProviderReceipt,
    ScriptedProviderAdapterV2,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class _CallbackScriptedAdapter(ScriptedProviderAdapterV2):
    def verify_callback(self, body, headers, *, secret):
        if headers.get("x-test-signature") != secret:
            raise ValueError("invalid signature")
        return ProviderReceipt(
            provider_request_id=str(headers["x-provider-request-id"]),
            receipt_id=str(headers["x-message-id"]),
            message_id=str(headers["x-message-id"]),
            outcome="success",
            payload_hash="sha256:" + hashlib.sha256(body).hexdigest(),
            evidence={
                "signature_verified": True,
                "result": {"text": "callback result"},
                "usage": {"input_tokens": 3, "output_tokens": 2},
                "cost": {"amount": "0", "currency": "USD"},
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
        )


class _GatewayCallbackEnvelopeAdapter:
    provider = "production_execution_gateway"
    reconciliation_mode = "query"
    capability_profile = ProviderCapabilityProfile(
        provider=provider,
        control_level=ProviderControlLevel.FIXTURE_CONTROLLED,
        supports_request_timeout=True,
        supports_provider_idempotency=True,
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reconciliation_mode="query",
        real_provider_validation_eligible=False,
    )

    def __init__(self, provider_request_id: str) -> None:
        self.provider_request_id = provider_request_id

    def execute(self, **_kwargs):  # type: ignore[no-untyped-def]
        return ProviderResult(
            "unknown",
            "gateway-correlation",
            {"production_execution_gateway": True},
            self.provider_request_id,
        )

    def query(self, **_kwargs):  # type: ignore[no-untyped-def]
        return ProviderResult("ambiguous", "gateway-query", {})

    def cancel(self, **_kwargs):  # type: ignore[no-untyped-def]
        return ProviderResult("ambiguous", "gateway-cancel", {})


class ProviderCallbackAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_verified_callback_is_durable_replayable_and_resumes_unknown_effect(self) -> None:
        context = self._context()
        adapter = _CallbackScriptedAdapter("unknown_after_send")
        effect_id = self._effect(context, adapter)
        dispatched = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect_id,
            worker_id="callback-dispatch-worker",
            lease_seconds=30,
            adapter=adapter,
        )
        self.assertEqual(dispatched["outcome"], "unknown")
        registry = ProviderAdapterRegistry()
        registry.register(adapter)
        service = ProviderCallbackAuthorityService(DATABASE_URL, registry)
        body = b'{"type":"completed"}'
        message_id = identifier("provider-message")
        command = ProviderCallbackAcceptCommand(
            provider=adapter.provider,
            provider_message_id=message_id,
            body=body,
            headers={
                "x-test-signature": "secret",
                "x-provider-request-id": dispatched["provider_request_id"],
                "x-message-id": message_id,
            },
            signature_secret="secret",
            actor_id="provider-callback-service",
            worker_id="callback-worker",
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
        )
        first = service.accept(command)
        replay = service.accept(command)
        self.assertEqual(first["processing_status"], "PROCESSED")
        self.assertTrue(replay["replayed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT callback.processing_status, callback.signature_status,
                       effect.status, operation.status,
                       (SELECT COUNT(*) FROM audit_log WHERE operation_id=operation.operation_id
                          AND action='provider.callback.accepted'),
                       (SELECT COUNT(*) FROM outbox_event WHERE project_id=operation.project_id
                          AND topic='provider.callback.accepted')
                FROM authority_provider_callback_receipt AS callback
                JOIN authority_external_effect AS effect
                  ON effect.external_effect_id=callback.external_effect_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=effect.operation_id
                WHERE callback.callback_receipt_id=%s
                """,
                [first["callback_receipt_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("PROCESSED", "VERIFIED", "SUCCEEDED", "EXECUTING", 1, 1),
            )

    def test_invalid_signature_is_quarantined_without_touching_effect(self) -> None:
        context = self._context()
        adapter = _CallbackScriptedAdapter("unknown_after_send")
        effect_id = self._effect(context, adapter)
        dispatched = dispatch_external_effect(
            DATABASE_URL, context, effect_id=effect_id,
            worker_id="callback-dispatch-worker", lease_seconds=30, adapter=adapter,
        )
        registry = ProviderAdapterRegistry()
        registry.register(adapter)
        with self.assertRaises(KernelError) as caught:
            ProviderCallbackAuthorityService(DATABASE_URL, registry).accept(
                ProviderCallbackAcceptCommand(
                    provider=adapter.provider,
                    provider_message_id=identifier("bad-message"),
                    body=b"invalid",
                    headers={
                        "x-test-signature": "wrong",
                        "x-provider-request-id": dispatched["provider_request_id"],
                    },
                    signature_secret="secret",
                    actor_id="provider-callback-service",
                    worker_id="callback-worker",
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                )
            )
        self.assertEqual(caught.exception.code, "PROVIDER_CALLBACK_SIGNATURE_INVALID")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT processing_status, signature_status, project_id FROM authority_provider_callback_receipt WHERE provider_message_id LIKE 'bad-message-%'"
            )
            self.assertEqual(cursor.fetchone(), ("QUARANTINED", "REJECTED", None))
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE external_effect_id=%s",
                [effect_id],
            )
            self.assertEqual(cursor.fetchone()[0], "UNKNOWN")

    def test_gateway_callback_is_deferred_to_frozen_execution_reconciliation(self) -> None:
        context = self._context()
        provider = _CallbackScriptedAdapter("unknown_after_send")
        request_id = identifier("gateway-provider-request")
        gateway = _GatewayCallbackEnvelopeAdapter(request_id)
        effect_id = str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider=gateway.provider,
                capability="model.draft",
                stable_idempotency_key=identifier("gateway-callback-effect"),
                request_payload={
                    "stage": "draft",
                    "_production_execution": {
                        "route_provider": provider.provider,
                    },
                },
                max_attempts=2,
                reversible=False,
                completion_policy="callback_receipt",
                request_timeout_seconds=30,
                reconciliation_mode="query",
                provider_capability_profile=gateway.capability_profile.to_dict(),
            )["external_effect_id"]
        )
        dispatched = dispatch_external_effect(
            DATABASE_URL,
            context,
            effect_id=effect_id,
            worker_id="gateway-callback-dispatch",
            lease_seconds=30,
            adapter=gateway,
        )
        self.assertEqual(dispatched["outcome"], "unknown")
        registry = ProviderAdapterRegistry()
        registry.register(provider)
        message_id = identifier("gateway-provider-message")
        body = b'{"type":"completed"}'
        command = ProviderCallbackAcceptCommand(
                provider=provider.provider,
                provider_message_id=message_id,
                body=body,
                headers={
                    "x-test-signature": "secret",
                    "x-provider-request-id": request_id,
                    "x-message-id": message_id,
                },
                signature_secret="secret",
                actor_id="provider-callback-service",
                worker_id="callback-worker",
                trace_id=context.trace_id,
                correlation_id=context.correlation_id,
            )
        accepted = ProviderCallbackAuthorityService(DATABASE_URL, registry).accept(command)
        self.assertEqual(accepted["processing_status"], "PENDING")
        self.assertTrue(accepted["reconciliation_required"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT provider, status FROM authority_external_effect WHERE external_effect_id=%s",
                [effect_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("production_execution_gateway", "UNKNOWN"),
            )

    @staticmethod
    def _context() -> EffectCommandContext:
        project_id = identifier("callback-project")
        operation_id = identifier("callback-operation")
        definition = identifier("callback-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition,
                project_id=project_id,
                status="EXECUTING",
            )
        return EffectCommandContext(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="callback-test",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )

    @staticmethod
    def _effect(context: EffectCommandContext, adapter: _CallbackScriptedAdapter) -> str:
        return str(
            plan_external_effect(
                DATABASE_URL,
                context,
                effect_type="model.invoke",
                provider=adapter.provider,
                capability="model.draft",
                stable_idempotency_key=identifier("callback-effect"),
                request_payload={
                    "stage": "draft", "trace_id": context.trace_id,
                    "correlation_id": context.correlation_id,
                },
                max_attempts=2,
                reversible=False,
                completion_policy="callback_receipt",
                request_timeout_seconds=30,
                reconciliation_mode="query",
                provider_capability_profile=adapter.capability_profile.to_dict(),
            )["external_effect_id"]
        )


if __name__ == "__main__":
    unittest.main()


def test_native_gateway_callback_reuses_frozen_contract_after_local_failure(tmp_path):
    import base64
    import json
    import pytest
    from unittest.mock import patch
    from tests.integration import capability_pack_postgres_support as support
    from tests.unit.test_production_execution_gateway import _remote_adapter
    from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response

    adapter, transport = _remote_adapter("unknown_after_send")
    registry = ProviderAdapterRegistry()
    registry.register(adapter)
    registry.register(ScriptedProviderAdapterV2("success"))

    def verify(body, headers, *, secret):
        assert headers["x-test-signature"] == secret
        return ProviderReceipt(
            provider_request_id=headers["x-provider-request-id"], receipt_id=headers["x-message-id"],
            message_id=headers["x-message-id"], outcome="success",
            payload_hash="sha256:" + hashlib.sha256(body).hexdigest(), evidence=json.loads(body),
        )

    transport.verify_callback = verify

    def pending(request):
        transport.query_calls += 1
        return {"outcome": "unknown", "request_sent": True, "provider_request_id": request.provider_request_id,
                "completion_mode": "background", "evidence": {"fixture_protocol_only": True}}

    transport.query = pending
    harness = support.CapabilityPackPostgresHarness("native-callback-contract")
    approved = harness.register_compile_approve("1.0.0", generation=1)
    harness.register_agents(approved.compiled)
    harness.activate(harness.deploy(approved))
    settings = support.IndustrialSettings(root=tmp_path, environment="development",
        storage_authority="postgresql", database_url=DATABASE_URL)
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_COMMIT_SHA": harness.release_sha, "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": harness.pack_id,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path),
        "NOVEL_FORGE_DRAFT_PROVIDER": "openai", "NOVEL_FORGE_DRAFT_MODEL": "gpt-4o",
        "NOVEL_FORGE_DRAFT_MODEL_CONTEXT_LIMIT": "100000",
        "NOVEL_FORGE_DRAFT_TOKEN_ACCOUNTING_METHOD": "OPENAI_UTF8_BYTES_UPPER_BOUND_V1",
        "NOVEL_FORGE_DRAFT_TOKEN_ACCOUNTING_EVIDENCE_REF": "fixture:openai-byte-upper-bound:v1",
    }
    execution = support.build_production_execution_composition(settings, provider_registry=registry, env=env)
    chapter = support.build_chapter_authority_application(settings, execution=execution, env=env)
    operator = harness.principal("chapter-operator", "chapter.authority.execute")
    admitted = chapter.admit(support.SingleChapterRequest(
        project_id=harness.project_id, workspace_id=harness.workspace_id, actor_id=operator.principal_id,
        chapter=1, title="Frozen callback fixture", premise="A frozen choice must survive recovery.",
        trace_id=identifier("trace"), correlation_id=identifier("correlation"),
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
        idempotency_key=harness.project_id + ":callback", preparation_report={"decision": "READY", "fixture": True, "stage_context_profile_versions": {"draft": "draft-context-profile-v4"}},
        context_candidates=harness._chapter_context_candidates(1), context_token_budget=32_768), principal=operator)
    worker = support.Principal(principal_id="chapter-worker:" + harness.project_id,
        principal_type=support.PrincipalType.WORKER, permissions=frozenset({"chapter.authority.execute"}),
        project_scope=frozenset({harness.project_id}), authentication_source="integration-fixture")
    scheduler = chapter.scheduler(principal=worker)

    def tick():
        return scheduler.tick(project_id=harness.project_id, root_operation_id=admitted.root_operation_id)

    try:
        for node in ("plan", "execution_intent", "memo", "retrieval", "context"):
            result = tick()
            assert result.node == node and result.operation_status == "SUCCEEDED"
        with pytest.raises(KernelError, match="MODEL_EFFECT_OUTCOME_UNKNOWN"):
            tick()
        with transaction() as connection:
            effect_id, payload, request_id, status = connection.execute(
                "SELECT external_effect_id,request_payload,provider_request_id,status FROM authority_external_effect WHERE project_id=%s AND capability='model.draft'",
                [harness.project_id],
            ).fetchone()
        assert status == "UNKNOWN" and transport.execute_calls == 1
        session = execution.gateway._session(harness.project_id)
        execution_id = "chapter-execution:" + effect_id
        record = session.evidence_store.get_record(execution_id)
        frozen = dict(record.frozen_output_contract)
        raw = {"scene_artifacts": default_chapter_fixture_response("draft", payload["input"])["scene_artifacts"]}
        queries_before_callback = transport.query_calls
        evidence = {"result": raw, "usage": {"input_tokens": 3, "output_tokens": 2},
                    "cost": {"amount": "0", "currency": "USD"}, "fixture_protocol_only": True, "real_model_call": False}
        service = ProviderCallbackAuthorityService(DATABASE_URL, registry)

        def command(values):
            message = identifier("native-callback-message")
            return ProviderCallbackAcceptCommand(provider=adapter.provider, provider_message_id=message,
                body=json.dumps(values, sort_keys=True).encode(), headers={"x-test-signature": "secret", "x-provider-request-id": request_id, "x-message-id": message},
                signature_secret="secret", actor_id="fixture:callback", worker_id="fixture:callback",
                trace_id="fixture:callback", correlation_id="fixture:callback")

        conflict = command({**evidence, "output_schema_version": "provider:spoofed"})
        rejected = service.accept(conflict)
        assert rejected["processing_status"] == "PENDING"
        with pytest.raises(KernelError, match="PROVIDER_FROZEN_CONTRACT_CONFLICT"):
            tick()
        with transaction() as connection:
            assert connection.execute("SELECT processing_status FROM authority_provider_callback_receipt WHERE callback_receipt_id=%s",
                [rejected["callback_receipt_id"]]).fetchone() == ("FAILED_FINAL",)
        saved = command(evidence)
        accepted = service.accept(saved)
        assert accepted["processing_status"] == "PENDING" and accepted["reconciliation_required"] is True
        assert "request_payload" not in accepted
        backend = session.gateway.backends.resolve(record.handle.backend_id)
        with patch.object(backend, "structured_result_validator", side_effect=RuntimeError("local validation interruption")):
            with pytest.raises(KernelError, match="local validation interruption"):
                tick()
        with transaction() as connection:
            status, body = connection.execute("SELECT processing_status,raw_metadata->>'body_base64' FROM authority_provider_callback_receipt WHERE callback_receipt_id=%s",
                [accepted["callback_receipt_id"]]).fetchone()
            assert status == "FAILED_RETRYABLE" and base64.b64decode(body) == saved.body
        result = tick()
        assert result.node == "draft" and result.operation_status == "SUCCEEDED"
        assert service.accept(saved)["replayed"] is True
        assert service.accept(command(evidence))["replayed"] is True
        with pytest.raises(KernelError, match="PROVIDER_CALLBACK_PAYLOAD_CONFLICT"):
            from dataclasses import replace
            service.accept(replace(saved, body=json.dumps({**evidence, "cost": {"amount": "1", "currency": "USD"}}).encode()))
        with pytest.raises(KernelError, match="PROVIDER_CALLBACK_EFFECT_TERMINAL"):
            service.accept(command({**evidence, "result": {"scene_artifacts": [{"slot_id": "changed", "text": "changed", "used_fact_ids": []}]}}))
        assert transport.execute_calls == 1 and transport.query_calls == queries_before_callback
        assert session.evidence_store.get_record(execution_id).frozen_output_contract == frozen
        with transaction() as connection:
            status, processed = connection.execute("SELECT status,(SELECT COUNT(*) FROM authority_external_receipt receipt JOIN authority_external_effect_dispatch dispatch USING(dispatch_id) WHERE dispatch.external_effect_id=%s) FROM authority_external_effect WHERE external_effect_id=%s", [effect_id, effect_id]).fetchone()
            receipt_status, attempts = connection.execute("SELECT processing_status,attempt_count FROM authority_provider_callback_receipt WHERE callback_receipt_id=%s", [accepted["callback_receipt_id"]]).fetchone()
        assert status == "SUCCEEDED" and processed == 1
        assert receipt_status == "PROCESSED" and attempts == 2
    finally:
        execution.close()
