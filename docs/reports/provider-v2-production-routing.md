# Provider v2 Production Routing

`ProviderAdapterRegistry` and route qualification now construct Chapter Authority
model gateways from explicit capability profiles. Validation/production routes reject
`LEGACY_UNCONTROLLED` and fixture control levels. `OpenAIProviderAdapterV2` is an
injected-transport SDK boundary: timeout and stable idempotency propagate, request,
usage and cost receipts normalize, and unsupported query/cancel capabilities remain
manual-reconciliation requirements. No network or real SDK request ran.

Evidence: `modules/provider_control/registry.py`, `openai_v2.py`, provider unit tests,
commit `27d534e`. Maturity: implemented + mock-conformance-proven; not real-provider-proven.
