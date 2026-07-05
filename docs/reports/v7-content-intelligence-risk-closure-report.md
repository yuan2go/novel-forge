# V7 Content Intelligence Risk Closure Report

Date: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`
Scope: remaining V7 content intelligence risk closure after foundation pass

## Closed Or Reduced Risks

| Risk | Current state | Evidence | Remaining boundary |
|---|---|---|---|
| Quality Eval 2.0 was local heuristic only | Reduced. `run_provider_quality_judge` now calls provider adapters through `model_router.call_model_via_router`, writes `model_judge_result`, and records route approval, provider policy, model call log, runtime policy gate, and cost ledger paths. Production `run_quality_gate` blocks local-heuristic reports without provider judge evidence. | `src/novel_forge/modules/quality_eval/service.py`, `src/novel_forge/modules/model_router/service.py`, `tests/unit/test_quality_eval_v2.py` | Unit tests use a fixture adapter. Real external provider execution still requires configured provider routes, credentials, and operator approval. |
| Long-chain proof was deterministic/state-only | Reduced. `provider_50_proof` is an explicit opt-in mode that requires a provider adapter, generates 50 provider-backed draft chapter proof assets, and records model call/cost/runtime evidence for every chapter. | `src/novel_forge/modules/long_chain_proof/service.py`, `tests/unit/test_long_chain_proof.py` | The default suite still avoids real network/cost. A real slow provider run remains an operator-triggered environment test. |
| Publishing adapter was manual only | Reduced. `publish_platform_upload_package` adds a platform client seam plus `HttpPlatformClient`, writes platform receipts/status, persists platform API evidence, redacts secrets, and fails closed in production when no client/endpoint exists. | `src/novel_forge/modules/publishing_feedback_adapters/service.py`, `src/novel_forge/api/routers/publishing_feedback_adapters.py`, `tests/unit/test_publishing_feedback_adapters.py` | No specific commercial platform SDK is hardcoded. Real endpoints require platform credentials, terms review, and operator configuration. |
| UI could trigger runs but not inspect/compare/repair | Reduced. V7 content intelligence consoles now include an Artifact Inspector that loads assets through `/product/assets/detail`, compares content keys, and can mark an asset `needs_review`. Publishing console can call the platform publish endpoint. | `web/admin/app/features/content-intelligence/ContentIntelligencePages.tsx`, `npm --prefix web/admin run lint`, `npm --prefix web/admin test` | Browser smoke remains optional because Playwright is not installed in the default local environment. |
| Agent/Workflow coverage did not include new provider/platform operations | Reduced. Agent Scheduler and Workflow ProcessorRegistry now include `run-provider-quality-judge` and `publish-platform-upload-package`. | `src/novel_forge/modules/agent_scheduler/service.py`, `src/novel_forge/modules/workflow_nodes/service.py`, agent/workflow tests | Provider adapter execution through scheduler remains fixture/explicit-config only; production still fails closed without real adapter configuration. |

## Tests Run

| Command | Result |
|---|---|
| `python3 -m unittest tests.unit.test_quality_eval_v2 tests.unit.test_long_chain_proof tests.unit.test_publishing_feedback_adapters tests.unit.test_product_api_routes` | Passed: 12 tests |
| `python3 -m unittest tests.unit.test_agent_workflow_and_impact tests.unit.test_loop_kernel tests.integration.test_workflow_steps` | Passed: 7 tests |
| `python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_agent_registry_scheduler_integration` | Passed: 19 tests |
| `python3 -m compileall -q src/novel_forge tests` | Passed |
| `npm --prefix web/admin run lint` | Passed |
| `npm --prefix web/admin test` | Passed: 10 passed, 1 optional browser smoke skipped |
| `make test` | Passed: Python 527 tests OK, skipped=2; Web Admin 10 passed, 1 optional browser smoke skipped |

## Residual Risk

1. Provider-backed quality and long-chain proofs are now runtime-evidence-capable, but real external provider runs still depend on configured provider routes, credentials, budget policy, and operator approval.
2. The HTTP platform adapter is generic and safe by default; platform-specific SDK behavior, rate limits, review callbacks, and terms constraints remain future work.
3. UI artifact repair is intentionally conservative: it marks assets for review instead of silently mutating outlines, chapters, or release packages.
