from __future__ import annotations

import unittest
from dataclasses import asdict

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    FakeDeterministicProvider,
)
from novel_forge.modules.provider_control import (
    LegacyProviderCompatibilityAdapter,
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
    def test_stable_key_and_provider_request_id_are_first_class(self) -> None:
        adapter = ScriptedProviderAdapterV2("success")
        result = adapter.invoke(_request())

        self.assertEqual(adapter.last_request.stable_idempotency_key, "stable-key")
        self.assertTrue(result.handle.provider_request_id.startswith("scripted-request:"))
        replay = adapter.invoke(_request())
        self.assertTrue(replay.evidence["replayed"])
        self.assertEqual(replay.handle.provider_request_id, result.handle.provider_request_id)

    def test_timeout_before_and_after_send_have_different_identity(self) -> None:
        before = ScriptedProviderAdapterV2("timeout_before_send").invoke(_request("before"))
        after = ScriptedProviderAdapterV2("timeout_after_send").invoke(_request("after"))
        self.assertEqual(before.outcome, "retryable_failure")
        self.assertFalse(before.request_sent)
        self.assertIsNone(before.handle)
        self.assertEqual(after.outcome, "unknown")
        self.assertTrue(after.request_sent)
        self.assertIsNotNone(after.handle)

    def test_query_cancel_and_callback_protocol(self) -> None:
        adapter = ScriptedProviderAdapterV2("unknown_after_send")
        initial = adapter.invoke(_request())
        query = adapter.query_v2(ProviderQueryRequest(
            provider_request_id=initial.handle.provider_request_id,
            stable_idempotency_key="stable-key",
            trace_id="trace-1",
            correlation_id="correlation-1",
        ))
        cancelled = adapter.cancel_v2(ProviderCancellationRequest(
            provider_request_id=initial.handle.provider_request_id,
            stable_idempotency_key="stable-key",
            reason="operator cancel",
            trace_id="trace-1",
            correlation_id="correlation-1",
        ))
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
            adapter.accept_callback(ProviderReceipt(
                **{**asdict(receipt), "payload_hash": "sha256:conflict"}
            ))

    def test_real_validation_profile_fails_closed_without_timeout_or_idempotency(self) -> None:
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
            "scripted_provider_v2", "fixture", environment="provider-validation"
        )
        self.assertFalse(report.qualified)
        self.assertIn("V2_CONTROLLED", " ".join(report.reasons))

    def test_openai_v2_transport_receives_timeout_key_and_returns_request_id(self) -> None:
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
                    "outcome": "success", "request_sent": True,
                    "provider_request_id": request.provider_request_id,
                    "evidence": {
                        "result": {"text": "controlled draft"},
                        "usage": {"input_tokens": 4, "output_tokens": 3},
                        "cost": {"amount": "0.01", "currency": "USD"},
                    },
                }

            def cancel(self, request):
                return {
                    "outcome": "cancelled", "request_sent": True,
                    "provider_request_id": request.provider_request_id,
                    "evidence": {"cancelled": True},
                }

            def verify_callback(self, body, headers, *, secret):
                self.callback = (body, headers, secret)
                return ProviderReceipt(
                    "response_123", "receipt_1", "message_1", "success",
                    "sha256:callback", {"signature_verified": True},
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
            provider="openai", model="gpt-test", capability="model.draft",
            stage="draft", stable_idempotency_key="stable-openai",
            request_payload={"stage": "draft"}, request_hash="sha256:req",
            timeout_seconds=17, trace_id="trace", correlation_id="correlation",
            operation_id="operation", external_effect_id="effect",
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
                stage="draft", provider_id=adapter.provider,
                model_id="scripted", adapter_contract_version="provider-capability-v2",
                prompt_version="prompt-v1", skill_version="skill-v1",
                timeout_seconds=30, environment="test", idempotency_policy="provider",
                query_policy="query", cancel_policy="cancel", callback_policy="callback",
                usage_receipt_policy="required", cost_receipt_policy="required",
            ),
            adapter,
        )
        gateway = ChapterProviderV2Gateway({"draft": route})
        result = gateway.execute(
            stable_idempotency_key="gateway-key",
            capability="model.draft",
            request_payload={
                "stage": "draft", "input": {}, "request_hash": "sha256:req",
                "timeout_seconds": 20, "trace_id": "trace", "correlation_id": "correlation",
                "operation_id": "operation", "external_effect_id": "effect",
            },
        )
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.provider_request_id, "scripted-request:gateway-key")
        self.assertEqual(result.evidence["result"]["text"], "Scripted chapter fixture.")

    def test_legacy_adapter_is_not_a_production_route(self) -> None:
        adapter = LegacyProviderCompatibilityAdapter(
            FakeDeterministicProvider("success"),
            provider="fake_deterministic_provider",
            environment="production",
        )
        self.assertFalse(adapter.capability_profile.real_provider_validation_eligible)
        self.assertEqual(
            adapter.capability_profile.control_level,
            ProviderControlLevel.LEGACY_UNCONTROLLED,
        )
        with self.assertRaises(ExternalEffectAdapterError):
            adapter.execute(
                stable_idempotency_key="stable",
                capability="model.draft",
                request_payload={},
            )


if __name__ == "__main__":
    unittest.main()
