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
