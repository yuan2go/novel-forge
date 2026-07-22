# Analysis Risks

Date: 2026-07-22

| Priority | Risk | Required control |
|---|---|---|
| P0 | Local Codex output is ephemeral and process identity is confused with provider identity | persistent supervisor and typed process receipt |
| P0 | Book fixture acceptance can be mistaken for real Chapter delegation | dynamic child Saga plus explicit reconcile/accept |
| P0 | Legacy/local writes can form a second production authority | PostgreSQL-only guard and migration adapters |
| P1 | Missing provider cost is represented as zero | explicit unknown cost and reconciliation |
| P1 | Mutable route resolution does not freeze actual execution inputs | immutable RouteSnapshot |
| P1 | Old operation/attempt/lease tables invite a parallel runtime | freeze new writes and guard Authority Attempt uniqueness |
| P1 | Book scheduler is project-scoped rather than root-scoped | root-scoped leases and concurrency tests |
