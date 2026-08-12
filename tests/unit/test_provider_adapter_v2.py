from __future__ import annotations

import unittest
from dataclasses import asdict
from unittest.mock import patch

from novel_forge.modules.provider_control import (
    ProviderCancellationRequest,
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderInvocationRequest,
    ProviderQueryRequest,
    ProviderReceipt,
    ScriptedProviderAdapterV2,
    ChapterProviderV2Gateway,
    ChapterProviderV2Route,
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
    ProviderRouteDefinition,
    build_provider_adapter_registry,
)


def _request(key: str = "stable-key") -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        provider="scripted_provider_v2",
        model="scripted-model",
        capability="model.draft",
        stage="draft",
        stable_idempotency_key=key,
        request_payload={"chapter": 1},
        request_hash="sha256:request",
        timeout_seconds=30,
        trace_id="trace-1",
        correlation_id="correlation-1",
        operation_id="operation-1",
        external_effect_id="effect-1",
        budget_reservation_id="reservation-1",
    )


class ProviderAdapterV2Tests(unittest.TestCase):
    def test_provider_composition_is_fixture_only_in_local_environments(self) -> None:
        registry = build_provider_adapter_registry(
            environment="test",
            provider_ids={"mock"},
            env={},
        )
        self.assertIsInstance(
            registry.resolve("scripted_provider_v2"), ScriptedProviderAdapterV2
        )

    def test_controlled_provider_composition_fails_closed_without_credentials(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            build_provider_adapter_registry(
                environment="validation",
                provider_ids={"openai"},
                env={},
            )
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            build_provider_adapter_registry(
                environment="production",
                provider_ids={"mock"},
                env={},
            )

    def test_controlled_provider_composition_uses_registered_factory(self) -> None:
        adapter = ScriptedProviderAdapterV2()
        adapter.provider = "openai"
        adapter.capability_profile = ProviderCapabilityProfile(
            provider="openai",
            control_level=ProviderControlLevel.V2_CONTROLLED,
            supports_request_timeout=True,
            supports_provider_idempotency=True,
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=True,
            supports_cost_receipt=False,
            reconciliation_mode="query",
            real_provider_validation_eligible=True,
        )
        with patch(
            "novel_forge.modules.provider_control.composition.build_openai_provider_adapter",
            return_value=adapter,
        ):
            registry = build_provider_adapter_registry(
                environment="validation",
                provider_ids={"openai", "codex-cli"},
                env={"OPENAI_API_KEY": "resolved-secret"},
            )
        self.assertIs(registry.resolve("openai"), adapter)

    def test_stable_key_and_provider_request_id_are_first_class(self) -> None:
        adapter = ScriptedProviderAdapterV2("success")
        result = adapter.invoke(_request())

        self.assertEqual(adapter.last_request.stable_idempotency_key, "stable-key")
        self.assertTrue(
            result.handle.provider_request_id.startswith("scripted-request:")
        )
        replay = adapter.invoke(_request())
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(
            replay.handle.provider_request_id, result.handle.provider_request_id
        )

    def test_timeout_before_and_after_send_have_different_identity(self) -> None:
        before = ScriptedProviderAdapterV2("timeout_before_send").invoke(
            _request("before")
        )
        after = ScriptedProviderAdapterV2("timeout_after_send").invoke(
            _request("after")
        )
        self.assertEqual(before.outcome, "retryable_failure")
        self.assertFalse(before.request_sent)
        self.assertIsNone(before.handle)
        self.assertEqual(after.outcome, "unknown")
        self.assertTrue(after.request_sent)
        self.assertIsNotNone(after.handle)

    def test_query_cancel_and_callback_protocol(self) -> None:
        adapter = ScriptedProviderAdapterV2("unknown_after_send")
        initial = adapter.invoke(_request())
        query = adapter.query_v2(
            ProviderQueryRequest(
                provider_request_id=initial.handle.provider_request_id,
                stable_idempotency_key="stable-key",
                trace_id="trace-1",
                correlation_id="correlation-1",
            )
        )
        cancelled = adapter.cancel_v2(
            ProviderCancellationRequest(
                provider_request_id=initial.handle.provider_request_id,
                stable_idempotency_key="stable-key",
                reason="operator cancel",
                trace_id="trace-1",
                correlation_id="correlation-1",
            )
        )
        self.assertEqual(query.outcome, "success")
        self.assertEqual(cancelled.outcome, "cancelled")
        receipt = ProviderReceipt(
            provider_request_id=initial.handle.provider_request_id,
            receipt_id="receipt-1",
            message_id="message-1",
            outcome="success",
            payload_hash="sha256:payload",
            evidence={"fixture_protocol_only": True},
        )
        self.assertIs(adapter.accept_callback(receipt), receipt)
        self.assertIs(adapter.accept_callback(receipt), receipt)
        with self.assertRaisesRegex(ValueError, "conflicting callback"):
            adapter.accept_callback(
                ProviderReceipt(
                    **{**asdict(receipt), "payload_hash": "sha256:conflict"}
                )
            )

    def test_real_validation_profile_fails_closed_without_timeout_or_idempotency(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "SDK request timeout"):
            ProviderCapabilityProfile(
                provider="provider-x",
                control_level=ProviderControlLevel.V2_CONTROLLED,
                supports_request_timeout=False,
                supports_provider_idempotency=True,
                supports_query=True,
                supports_cancel=True,
                supports_callback=False,
                supports_usage_receipt=True,
                supports_cost_receipt=True,
                reconciliation_mode="query",
                real_provider_validation_eligible=True,
            )

    def test_registry_qualifies_only_controlled_routes_for_validation(self) -> None:
        registry = ProviderAdapterRegistry()
        registry.register(ScriptedProviderAdapterV2())
        report = registry.qualify(
            "scripted_provider_v2", "fixture", environment="validation"
        )
        self.assertFalse(report.qualified)
        self.assertIn("V2_CONTROLLED", " ".join(report.reasons))

    def test_openai_v2_transport_receives_timeout_key_and_returns_request_id(
        self,
    ) -> None:
        class Transport:
            request = None

            def execute(self, request):
                self.request = request
                return {
                    "outcome": "success",
                    "request_sent": True,
                    "provider_request_id": "response_123",
                    "provider_correlation_id": "request_123",
                    "evidence": {
                        "result": {"text": "controlled draft"},
                        "usage": {"input_tokens": 4, "output_tokens": 3},
                        "cost": {"amount": "0.01", "currency": "USD"},
                    },
                }

            def query(self, request):
                return {
                    "outcome": "success",
                    "request_sent": True,
                    "provider_request_id": request.provider_request_id,
                    "evidence": {
                        "result": {"text": "controlled draft"},
                        "usage": {"input_tokens": 4, "output_tokens": 3},
                        "cost": {"amount": "0.01", "currency": "USD"},
                    },
                }

            def cancel(self, request):
                return {
                    "outcome": "cancelled",
                    "request_sent": True,
                    "provider_request_id": request.provider_request_id,
                    "evidence": {"cancelled": True},
                }

            def verify_callback(self, body, headers, *, secret):
                self.callback = (body, headers, secret)
                return ProviderReceipt(
                    "response_123",
                    "receipt_1",
                    "message_1",
                    "success",
                    "sha256:callback",
                    {"signature_verified": True},
                )

        transport = Transport()
        adapter = OpenAIProviderAdapterV2(
            transport,
            supports_query=True,
            supports_cancel=True,
            supports_callback=True,
            supports_cost_receipt=True,
            provider_idempotency_supported=True,
        )
        request = ProviderInvocationRequest(
            provider="openai",
            model="gpt-test",
            capability="model.draft",
            stage="draft",
            stable_idempotency_key="stable-openai",
            request_payload={"stage": "draft"},
            request_hash="sha256:req",
            timeout_seconds=17,
            trace_id="trace",
            correlation_id="correlation",
            operation_id="operation",
            external_effect_id="effect",
        )
        result = adapter.invoke(request)
        self.assertEqual(transport.request.timeout_seconds, 17)
        self.assertEqual(transport.request.stable_idempotency_key, "stable-openai")
        self.assertEqual(result.handle.provider_request_id, "response_123")
        receipt = adapter.verify_callback(b"{}", {"x": "y"}, secret="secret")
        self.assertEqual(receipt.message_id, "message_1")

    def test_gateway_fails_closed_on_capability_handle_mismatch(self) -> None:
        adapter = ScriptedProviderAdapterV2()
        route = ChapterProviderV2Route(
            ProviderRouteDefinition(
                stage="draft",
                provider_id=adapter.provider,
                model_id="scripted",
                adapter_contract_version="provider-capability-v2",
                prompt_version="prompt-v1",
                skill_version="skill-v1",
                timeout_seconds=30,
                environment="test",
                idempotency_policy="provider",
                query_policy="query",
                cancel_policy="cancel",
                callback_policy="callback",
                usage_receipt_policy="required",
                cost_receipt_policy="required",
            ),
            adapter,
        )
        gateway = ChapterProviderV2Gateway({"draft": route})
        result = gateway.execute(
            stable_idempotency_key="gateway-key",
            capability="model.draft",
            request_payload={
                "stage": "draft",
                "input": {},
                "request_hash": "sha256:req",
                "timeout_seconds": 20,
                "trace_id": "trace",
                "correlation_id": "correlation",
                "operation_id": "operation",
                "external_effect_id": "effect",
            },
        )
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.provider_request_id, "scripted-request:gateway-key")
        self.assertEqual(result.evidence["result"]["text"], "Scripted chapter fixture.")


if __name__ == "__main__":
    unittest.main()
