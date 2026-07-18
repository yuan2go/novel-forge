from __future__ import annotations

import hashlib
import unittest

from novel_forge.modules.command_kernel.errors import KernelError
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
