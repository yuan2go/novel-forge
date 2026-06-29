# Novel OS Remaining Closure Execution Plan

Date: 2026-06-29

Source: `docs/08-roadmap/novel-os-remaining-closure-plan.md`

## Execution Summary

Novel Forge is currently an early Novel Operating System runtime. The codebase already contains:

- Workflow Executor with DAG parsing, ready queue, processor registry, scheduler loop, gates, resume, invalidation, and output quarantine.
- Agent Scheduler with dispatch queue, lease, retry, dead-letter, checkpoint, operation registry, and recovery.
- Novel KG with typed ontology snapshots, semantic enhancement, dirty tracking, gate integration, path/impact/conflict queries, and context hooks.
- Trace Timeline and Cost Ledger with trace spans, gate results, model call logs, cost ledgers, budget policies, cost snapshots, and cost-quality dashboard.
- Review Rework Loop with review issues, revision task, editor patch, apply, draft version, re-review, and publish gate first slice.
- Web OS Console routes for workflow, agents, KG, trace, cost, invalidation, and review rework.
- Integration acceptance fixture for the core OS chain.

The remaining work is closure hardening: universal enforcement, real provider runtime control, deep checkpoint resume, multi-asset rollback, stronger KG semantics, operator-grade Web Console, feedback backflow, and long-chain acceptance.

## Prioritized Work Breakdown

| Priority | Work Item | Dependency | Impact Range | Implementation Plan | Acceptance Standard | Test Plan | Current Status |
|---|---|---|---|---|---|---|---|
| P0 | Universal Runtime Policy | None | All model-producing API/CLI/service paths | Added registry, strict/compat checks, `RuntimePolicyEnvelope`, enforcement report, legacy-entrypoint audit, KG-context check, and GuardedModelAdapter ledger capture. | OS mode fails closed for missing required evidence; compat mode warns; coverage/audit reports identify uncovered operations and old entrypoints. | `tests.unit.test_runtime_policy`; full unit discovery. | Hardened first production slice. |
| P0 | Provider Runtime Guard | Runtime Policy | `model_adapters`, agent/workflow execution | Added normalized provider runtime contracts, `ProviderRuntimeController`, OpenAI-compatible SSE streaming usage, streaming delta cutoff, runtime events, and local Codex/Claude Code process polling. | Provider timeout/cutoff/cancel can fail closed and return normalized usage/runtime events. | `tests.unit.test_provider_runtime_guard`, `tests.unit.test_model_adapter`. | Hardened first production slice; future provider SDKs still need native streaming bindings. |
| P0 | Deep Checkpoint Resume | Runtime Policy, Provider Guard | Workflow processors, Agent operations | Added operation checkpoint stage schema, idempotency key, resume plan, durable stage checkpoint assets, latest-checkpoint lookup, and checkpoint chain. | Resume plans choose committed-output, validation, provider, prompt, or context stage. | `tests.unit.test_operation_checkpoint`, workflow/agent scheduler tests. | Hardened first production slice. |
| P0 | Business Rollback | Runtime Policy, Checkpoint | Output assets, ledger, KG dirty index, Web OS | Added operation transaction, rollback plan/result, version restore, logical rollback, ledger compensation, KG dirty marker, preview/apply/verify APIs, and OS rollback panel. | Rollback preview/apply writes traceable verified results without deleting ledger history. | `tests.unit.test_operation_transactions`. | Hardened first production slice. |
| P0 | KG Semantic Depth | Runtime Policy | KG, context builder, review/publish/continuity gates | Added identity resolution, merge queue, evidence/confidence support, model-assisted candidate validation, semantic extraction report asset/API/UI, KG-backed context enforcement, alias conflict hardening, and fast gate path. | KG gate/preflight hard-block high-severity conflicts and OS draft/review policy requires KG-backed context. | `tests.unit.test_novel_kg`, `tests.unit.test_novel_kg_identity`, `tests.unit.test_semantic_enhancement`, OS acceptance. | Hardened first production slice; production provider extraction remains future depth. |
| P1 | Web OS Console Hardening | Runtime/rollback APIs | Web Admin OS pages | OS routes remain wired; cockpit now shows runtime policy coverage, legacy bypass audit, rollback preview/apply/verify; KG workbench can create semantic extraction and identity merge reports. | OS pages are discoverable and API contracts remain explicit. | `npm --prefix web/admin test`, `npm --prefix web/admin run lint`. | Verified cockpit first slice; browser smoke optional when Playwright is installed. |
| P1 | Feedback-to-plan Backflow | KG/context/gates | Feedback, planning, review rules, workflow | Added feedback backflow assets, service, API endpoints, and agent permissions. | Feedback creates traceable human-gated plan/rule/KG proposals, never silent mutations. | `tests.unit.test_feedback_backflow`. | Complete first production slice. |
| P1 | Long-chain Scale Acceptance | All P0 | Tests/reports | Added scale metrics, 3-chapter deterministic smoke, and opt-in 12/50 chapter pressure profile. | Scale report includes continuity/quality/cost/recovery/feedback metrics. | `tests.integration.test_novel_os_long_chain_smoke`, `tests.integration.test_novel_os_long_chain_pressure`. | Complete smoke plus opt-in pressure profile. |
| P2 | Operator polish | P0/P1 | UI/docs/reports | Documentation and status pages updated for current OS closure batch. | Clearer operator handoff and verification commands. | Docs review plus validation commands. | Partially complete. |

## Module Impact Map

| Module | Expected Changes |
|---|---|
| `src/novel_forge/modules/runtime_policy` | Shared policy layer, registry, strict/compat mode, envelope, enforcement report, KG-context checks. |
| `src/novel_forge/model_adapters` | Normalized runtime usage, controller events, streaming cutoff contract, timeout, cancel, provider cost capture, automatic guarded model call ledger. |
| `src/novel_forge/modules/workflow_nodes` | Operation checkpoint stages, rollback transaction hooks, policy enforcement for processors. |
| `src/novel_forge/modules/agent_scheduler` | Operation-level checkpoint/resume/rollback hardening. |
| `src/novel_forge/modules/agent_runs` | Stronger runtime guard integration and policy evidence. |
| `src/novel_forge/modules/runtime_ledger` | Reused as source of truth for trace, gate, model call, cost, budget, alert. |
| `src/novel_forge/modules/novel_kg` | Identity resolution, evidence spans, semantic extraction report integration, KG-backed context/gates. |
| `src/novel_forge/modules/context_builder` | Mandatory KG context profile in OS mode. |
| `src/novel_forge/modules/feedback_backflow` | New feedback learning service. |
| `web/admin` | Fixture-backed OS route smoke, policy coverage cockpit, rollback verification panel, semantic extraction workbench action. |
| `tests` | Policy, provider, checkpoint, rollback, KG-backed context, feedback backflow, and long-chain acceptance. |
| `docs` | Updated roadmap, implementation summary, API/runtime notes. |

## Validation Gate

Each completed batch must run the smallest relevant checks:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_policy
PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_ledger tests.unit.test_workflow_executor tests.unit.test_agent_scheduler
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
npm --prefix web/admin test
npm --prefix web/admin run lint
git diff --check
```

If optional dependencies are unavailable, the failure must be documented rather than hidden.

## Validation Result 2026-06-29

Passed:

```bash
PYTHONPATH=src python3 -m unittest discover tests/unit
PYTHONPATH=src python3 -m unittest discover tests/integration
PYTHONPATH=src python3 -m compileall -q src tests
git diff --check
npm --prefix web/admin test
npm --prefix web/admin run lint
```

Notes:

- `npm --prefix web/admin test` skips browser smoke when Playwright is not installed. The route/API architecture test still passes.
- Unit and integration tests force `NOVEL_FORGE_MODEL_PROVIDER=mock` where needed so the default local Claude Code Codex worker does not affect deterministic validation.
- `tests.integration.test_novel_os_long_chain_pressure` is present but skipped unless `NOVEL_FORGE_RUN_LONG_CHAIN_PRESSURE=1`; use `NOVEL_FORGE_LONG_CHAIN_CHAPTERS=12` or `50` for local pressure runs.
