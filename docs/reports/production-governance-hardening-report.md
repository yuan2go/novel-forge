# Production Governance Hardening Report

Date: 2026-07-05

Scope: production path governance, critical gate fixtures, fallback auditability, and service seam hardening.

## Summary

This pass adds a schema-backed governance seam for production-sensitive paths:

- `production_governance_report` records normalized gate evidence for publish/release paths.
- `fallback_decision` records explicit fallback approval/denial with rollback evidence.
- Publish Gate now writes a unified governance report covering OS Envelope, Context Bundle, source isolation, MKAOS risk, ReviewIssue, longform stability, EvaluationGate, ProviderRuntimeGate, and PlatformStrategyGate.
- Release Package now treats the governance report as required production evidence.
- Platform API publishing now hard-stops in production unless the upload package points to a release package with passed production governance evidence.
- Provider fallback approval now writes a durable fallback decision with `silent_fallback_allowed=false` and a rollback plan.
- Postgres/local read fallback policy now exposes audit and rollback fields instead of only returning `allow_local_fallback`.
- Postgres/local read fallback call sites in product/API reads now persist `fallback_decision` plus audit events when fallback is audited.
- MKAOS model extraction now blocks production mock/local/offline provider routes unless explicit fixture mode is supplied, and persists provider route approval evidence.
- Final draft promotion through `execute_revision_plan` now has production preflight governance and writes final-draft governance evidence when production gates pass.
- Agent Scheduler registered operation execution now runs production preflight/final governance and writes governance evidence back to AgentRun evidence.
- Workflow Agent nodes now preserve `environment`, OS envelope, source policy, and provider runtime evidence into AgentRun evidence so scheduler production policy is not lost between workflow and runner.
- Longform model-assisted extraction now records deterministic fallback as `fallback_decision`; production model fallback is denied and fails closed.
- Platform API adapter failures now write schema-valid failure status plus denied `fallback_decision`, with secret-like error fragments redacted.

## Files Changed

| Area | Files |
| --- | --- |
| Governance seam | `src/novel_forge/modules/production_governance/` |
| Schema / directory registry | `src/novel_forge/schemas/assets.py`, `src/novel_forge/schemas/base.py`, `src/novel_forge/schemas/__init__.py`, `src/novel_forge/core/constants.py` |
| Publish/release gates | `src/novel_forge/modules/publishing/publish_gate.py`, `src/novel_forge/modules/publishing/release_gate.py`, `src/novel_forge/modules/publishing/release_package.py` |
| Fallback policy | `src/novel_forge/modules/provider_fallback/service.py`, `src/novel_forge/api/services/postgres_fallback_policy.py` |
| Product/API fallback call sites | `src/novel_forge/api/services/product.py`, `src/novel_forge/api/app.py` |
| Editor final draft governance | `src/novel_forge/modules/editor/service.py` |
| MKAOS provider route governance | `src/novel_forge/modules/mkaos_model_extraction/provider_runner.py`, `src/novel_forge/modules/mkaos_model_extraction/service.py` |
| Scheduler production governance | `src/novel_forge/modules/agent_scheduler/production_governance.py`, `src/novel_forge/modules/agent_scheduler/service.py` |
| Workflow -> Scheduler evidence handoff | `src/novel_forge/modules/workflow_nodes/service.py` |
| Longform fallback governance | `src/novel_forge/modules/longform_stability/service.py` |
| Platform publish hard-stop/fallback | `src/novel_forge/modules/publishing_feedback_adapters/service.py`, `src/novel_forge/modules/publishing_feedback_adapters/fallbacks.py` |
| Tests | `tests/unit/test_publish_feedback_loop.py`, `tests/unit/test_provider_fallback_policy.py`, `tests/unit/test_large_service_seams.py`, `tests/unit/test_genre_os.py`, `tests/unit/test_style_os.py`, `tests/unit/test_schemas.py`, `tests/unit/test_publishing_feedback_adapters.py`, `tests/unit/test_mkaos_provider_semantic_governance.py`, `tests/unit/test_review_issue.py`, `tests/unit/test_agent_scheduler.py`, `tests/unit/test_longform_stability.py` |

## Gate Fixture Coverage

| Gate | Positive fixture | Negative fixture |
| --- | --- | --- |
| Publish/Release production governance | `test_release_package_production_ready_fixture_creates_ready_package` | `test_publish_gate_governance_blocks_missing_provider_fixture` |
| Provider runtime policy | `test_production_model_route_defaults_to_claude_code_only`, provider success fixtures | provider missing/failed/mock-deny tests |
| Genre Risk Gate | `test_risk_gate_passes_clean_genre_execution_without_review_issue` | `test_risk_gate_generates_review_issue_for_uncontrolled_longform_risk` |
| Style Drift Gate | `test_style_drift_gate_passes_matching_profile_without_rewrite_task` | `test_style_drift_gate_writes_review_issue_and_rewrite_task_for_high_drift` |
| Canon Graph plugins | schema-backed pass report fixtures | fantasy power-scale blocking fixture |
| Quality Eval 2.0 | ready report/gate and provider-backed judge fixture | low-quality report and production local-heuristic block fixture |
| Platform publish adapter | API adapter receipt fixture | production missing client/endpoint fail-closed fixture |
| Platform publish governance | API adapter uses production-ready release package fixture | upload package without release governance fails closed |
| Provider fallback | explicit approval decision fixture | approval-required block fixture |
| Postgres fallback | fail-open fallback decision fixture and product read seam fixture | strict fail-closed fixture |
| MKAOS provider route | production explicit fixture mode fixture | production mock/local/offline provider route block fixture |
| Final draft promotion governance | production final draft governance report fixture | missing ProviderRuntimeGate production block fixture |
| Agent Scheduler production governance | registered operation records production governance fixture | missing ProviderRuntimeGate dead-letter fixture |
| Workflow scheduler evidence handoff | production processor evidence is preserved in AgentRun fixture | covered by scheduler missing-gate fixture when evidence is absent |
| Longform model-assisted fallback | local deterministic fallback writes `fallback_decision` fixture | production deterministic fallback denied fixture |
| External platform adapter fallback | API failure writes failure status and denied `fallback_decision` fixture | production missing client/endpoint and release governance fail-closed fixtures |

## Remaining Risks

- `mkaos/service.py`, `workflow_nodes/service.py`, `agent_scheduler/service.py`, and `api/services/product.py` remain large. This pass extracted focused scheduler and platform-adapter governance seams rather than attempting a risky horizontal split across all of them.
- The new production governance report is now enforced by publishing/release/platform publish paths, final draft promotion, and registered Agent Scheduler execution. The next batch should wire the same pattern into remaining model/provider-assisted operations that are not yet routed through scheduler or publish gates.
- Postgres fallback is explicit and audited for product/API read fallback paths; longform model-assisted fallback and platform API adapter failure are now assetized. Remaining fallback work should audit other external adapters and non-critical local compatibility fallbacks.
- MKAOS provider route governance now denies production mock/local/offline routes without fixture approval. This is still fixture/provider-route proof, not proof of a premium commercial provider producing high-quality extraction.

## Verification

- `python3 -m unittest tests.unit.test_large_service_seams tests.unit.test_publish_feedback_loop tests.unit.test_provider_fallback_policy tests.unit.test_genre_os tests.unit.test_style_os`
- `python3 -m unittest tests.unit.test_schemas tests.unit.test_product_api_routes tests.unit.test_provider_hard_stop_proof tests.unit.test_canon_graph_plugins tests.unit.test_quality_eval_v2 tests.unit.test_publishing_feedback_adapters`
- `python3 -m unittest tests.unit.test_review_issue tests.unit.test_context_and_production_chain tests.unit.test_large_service_seams tests.unit.test_mkaos_provider_semantic_governance tests.unit.test_provider_fallback_policy tests.unit.test_schemas`
- `python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_longform_stability tests.unit.test_publishing_feedback_adapters tests.unit.test_large_service_seams tests.unit.test_provider_fallback_policy tests.unit.test_review_issue tests.unit.test_publish_feedback_loop tests.unit.test_mkaos_provider_semantic_governance`
- `python3 -m unittest tests.unit.test_workflow_executor`
- `python3 -m compileall -q src/novel_forge tests`
- `make test` => Python `545` tests OK (`2` skipped); Web admin `11` pass (`1` skipped).

All focused checks passed.
