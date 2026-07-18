# Provider Adapter v2

## Contract

`modules/provider_control` defines typed invocation, handle, query, cancellation,
callback receipt, capability, result, and error-classification contracts. The stable
idempotency key and request hash cross the adapter boundary; provider request ID and
the frozen capability profile are first-class ExternalEffect fields (Migration 0028).

Capabilities explicitly declare timeout, provider idempotency, query, cancel,
callback, usage/cost receipts, and reconciliation mode. Claimed control without the
required request ID or stable-key acceptance fails closed.

## Proof adapter

The scripted adapter covers success, before-send failure, after-send UNKNOWN,
timeouts, duplicate/conflicting callbacks, query results, cancellation variants,
cost overrun, and token mismatch. It is marked
`fixture_protocol_only=true`, `real_model_call=false`, and
`production_verified=false`.

The legacy compatibility adapter is `LEGACY_UNCONTROLLED` and
`real_provider_validation_eligible=false`; it cannot be enabled as a production v2
route. No real Provider SDK was invoked in this phase.
