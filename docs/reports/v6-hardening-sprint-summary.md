# V6 Hardening Sprint Summary

## Status

Completed for the current hardening slice.

## Implemented

- Added OS surface coverage report API and audit script.
- Added provider hard-stop evidence report with triggered token/cost/cancel/timeout dimensions.
- Added provider cost cutoff to `ProviderRuntimeGuard`.
- Attached provider guard gate evidence to Model Gateway runtime envelopes.
- Hardened Agent Center backend snapshot and Admin cockpit UI.
- Added editable Longform Stability controls for Canon, Arc, Foreshadowing, Character/Debt and Villain assets.
- Added longform extraction calibration with confidence, metrics and evidence spans.
- Added local-smoke coverage for backend import, FastAPI contract, pgvector dry-run, scheduler smoke, unit/integration tests and Web Admin build.
- Added repeatable scripts for enforcement audit, provider hard-stop proof, Agent Center report and 12-chapter pressure acceptance.

## Evidence

- `docs/reports/os-enforcement-audit.md`
- `docs/reports/provider-hard-stop-report.md`
- `docs/reports/agent-center-hardening-report.md`
- `docs/reports/longform-12ch-pressure-acceptance.md`
- `docs/reports/local-smoke-report.md`

## Test Results

- `PYTHONPATH=src python3 -m unittest tests.unit.test_provider_runtime_guard tests.unit.test_runtime_policy tests.unit.test_agent_scheduler tests.unit.test_longform_stability tests.unit.test_product_api_routes`: passed.
- `npm --prefix web/admin test`: passed.
- `npm --prefix web/admin run lint`: passed.
- `npm --prefix web/admin run build`: passed.
- `make local-smoke`: passed.

## Remaining Risks

- Surface coverage still reports local-workspace evidence gaps for operations not exercised in the current `.local/workspace`; the code path matrix is enforced/compatible, but broader fixture runs should exercise every registered policy.
- Agent Center intentionally shows blocked state when dead-letter proof items exist; this is correct evidence, but production operation should recover or cancel them before autonomous scheduling.
- The 12-chapter pressure test uses deterministic injectors over local generated chapters to guarantee gate coverage; a future acceptance run should replay an unmodified long manuscript sample as a separate benchmark.

## Next Iteration

- Add a full operation coverage fixture that exercises every runtime policy operation at least once.
- Add rollback rehearsal fixtures that verify business rollback, not only rollback preview evidence.
- Add platform adapter release dry-runs for each configured target platform.
- Add pgvector online migration proof against a disposable Postgres service in CI.
- Promote extraction calibration reports into a versioned regression corpus.

