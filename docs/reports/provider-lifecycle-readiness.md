# Provider Lifecycle Readiness

Date: 2026-07-18. No real Provider was called.

| Capability | State | Evidence |
|---|---|---|
| Stable request identity/digest | integration_proven | ExternalEffect schema/runtime; `9f33ff3` |
| Provider request/model IDs | integration_proven with fixture | migration `0023`; dispatch tests |
| Attempt and effect lease/fencing | integration_proven | Command Kernel PostgreSQL tests |
| Heartbeat during blocking execution | integration_proven with slow fixture | one-second Attempt/effect lease renewal; `b9aee6e` |
| Timeout to UNKNOWN | integration_proven with fixture | ambiguous dispatch fixture |
| Query reconciliation | integration_proven with fixture | success/not-found/ambiguous fixtures |
| Unsupported reconciliation | integration_proven | manual resolution required, no auto-retry |
| Cancellation request/evidence | integration_proven with fixture | cancellation PostgreSQL tests |
| Budget reserve/settle/release | integration_proven with fixture | `authority_budget_reservation` tests |
| Scoped/daily concurrency | integration_proven with PostgreSQL | explicit timezone and advisory-lock serialized cap checks; migration `0024` |
| Cost ledger | integration_proven with fixture | settlement evidence |
| Duplicate stable-key prevention | integration_proven | unique effect/reservation keys |
| Grouped Quality Provider boundary | fixture_proven | five stage routes, exact frozen dimension response contract, target-bound evidence |
| Long blocking real SDK heartbeat | fixture-proven topology | real adapter proof deferred |
| Real Provider | not run | explicitly out of scope |

Migration `v20260718_0023_provider_budget_lifecycle` adds reconciliation metadata and
the project-scoped budget reservation aggregate. Migration `0024` adds frozen
business deadlines, explicit budget dimensions/currency/timezone, recover commands,
and manual ExternalEffect resolution. UNKNOWN effects retain reservations because a
charge may already exist; an overrun is held as a breach rather than silently
settled. Commit `159b1e2` adds root cancellation propagation, deadline scanning,
pre-materialization deadline probes, and adapter cancellation dispatch. Commit
`7773189` binds the five grouped Quality judges to the same governed model
ExternalEffect/budget boundary.
