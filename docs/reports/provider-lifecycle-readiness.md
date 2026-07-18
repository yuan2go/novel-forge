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
| Cost ledger | integration_proven with fixture | settlement evidence |
| Duplicate stable-key prevention | integration_proven | unique effect/reservation keys |
| Long blocking real SDK heartbeat | fixture-proven topology | real adapter proof deferred |
| Real Provider | not run | explicitly out of scope |

Migration `v20260718_0023_provider_budget_lifecycle` adds reconciliation metadata and
the project-scoped budget reservation aggregate without modifying prior migrations.
UNKNOWN effects retain reservations because a charge may already exist.
