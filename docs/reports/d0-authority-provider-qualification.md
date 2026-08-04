# D0 Authority-integrated Provider Qualification

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Implementation evidence SHA: `8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`
- Date: 2026-08-04
- Provider/API mode: OpenAI Responses API
- Route policy: `d0-route-policy.v1`
- SDK retries: `max_retries=0`
- Secret reference: `env://OPENAI_API_KEY`

## Authority chain implemented

The Fixture-qualified harness now executes through the formal chain:

```text
D0 Qualification Command
→ Operation / RouteSnapshot
→ worker claim / Attempt / Lease and Fence
→ ExternalEffect
→ Provider request identity and Receipt
→ request/response Object Store evidence
→ usage and versioned calculated price
→ query/cancel/reconcile evidence
→ Qualification Decision
→ PostgreSQL D0 Report AssetVersion
→ query projection
```

Migration 0053 persists the D0 run, price version, six scenario evidence rows,
and scope guards. The formal worker reclaims `READY` work from PostgreSQL. A
new scheduler/application instance reconciles the existing ExternalEffect by
its stored Provider request ID rather than creating a second Provider request.

The OpenAI SDK remains an optional dependency (`provider-openai`); it is not a
base runtime dependency. `build_openai_d0_adapter()` constructs the client with
`max_retries=0`, so retry, UNKNOWN, reconciliation, and duplicate-cost policy
remain in the Command Kernel. Credentials are injected only at runtime and are
not persisted in PostgreSQL, logs, or Object Store evidence.

## Evidence stored

The authority schema and report carry:

- Provider request ID, HTTP request ID, backend, model and provider-reported
  model version when available;
- route policy version, timeout, query/cancel capability and SDK retry setting;
- raw and normalized usage;
- provider cost when actually reported, plus calculated cost from a versioned
  price record;
- receipt and request/response hashes;
- Object Store references, content type, size, retention class and encryption
  metadata;
- UNKNOWN, reconciliation, cancellation, late-result and restart-query
  evidence.

`MinioObjectStore` evidence tests verify canonical JSON bytes, SHA-256 content
hashes, long-term retention metadata, and versioned `minio://` references.

## Scenario results

No real Provider credential/model was present in the validation environment,
and the optional OpenAI SDK was not installed. Therefore no external Provider
request was executed and every real Gate remains false.

| Scenario | Fixture/contract result | Real-provider result |
|---|---|---|
| D0-A Auth and receipt | Stored fixture receipt; deliberately `BLOCKED` for auth | `BLOCKED_MISSING_CREDENTIALS` |
| D0-B Background query | Reconciled stored fixture request identity | not executed |
| D0-C Cancel | `CANCELLED`/idempotent fixture evidence | not executed |
| D0-D Timeout/UNKNOWN | distinguishes before-send retryable from after-send UNKNOWN | not executed |
| D0-E Late result | preserves terminal decision and records late-result marker | not executed |
| D0-F Restart recovery | new application instance queries existing ID without resend | not executed against a real Provider |

The fixture run creates PostgreSQL Operation/Attempt/ExternalEffect/Receipt,
six scenario rows, request/response Object Store references, and a D0 Report
AssetVersion. Its decision stays non-qualified and its real Gate fields stay
false. Fixture token usage or fixture price arithmetic is not promoted to
`provider_usage_proven` or `provider_cost_proven`.

The current live runner can perform a basic request when configured, but one
request cannot prove cost, background query, cancel, controlled timeout,
UNKNOWN reconciliation, late result, or process restart. Those scenarios must
be run separately and their Gate must be computed from persisted evidence.

## Real Gate

```text
real_provider_auth_proven=false
provider_request_receipt_proven=false
provider_usage_proven=false
provider_cost_proven=false
provider_timeout_query_cancel_behavior_recorded=false
unknown_reconciliation_proven=false
provider_restart_recovery_proven=false
```

## Evidence classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
local_deployment_verified=VALIDATION_PENDING
external_execution_proven=false
longform_proven=false
production_verified=false
```

Blocker: `BLOCKED_MISSING_CREDENTIALS` (and the optional SDK/model configuration
needed for an external run). C1 cannot use this Fixture harness as real Provider
qualification.
