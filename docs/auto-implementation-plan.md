# Auto Implementation Plan

Date: 2026-06-29

Source optimization document: `docs/08-roadmap/novel-os-remaining-closure-plan.md`

## Scope

This plan tracks the autonomous closure work required to move Novel Forge from an early Novel Operating System runtime to a deliverable local-first Novel Operating System implementation.

The current project already has first production slices for Workflow Executor, Agent Scheduler, Novel KG, Trace Timeline, Cost Ledger, Review Rework Loop, OS acceptance tests, and Web OS Console routes. The remaining work is not a new skeleton. It is enforcement, provider control, resumability, rollback, semantic depth, operational UX, feedback learning, and scale acceptance.

## Optimization Table

| Priority | Item | Current State | Target State | Main Modules | Acceptance |
|---|---|---|---|---|---|
| P0 | Universal Runtime Policy | Scheduler paths were strong; direct paths needed a common evidence check. | Shared registry, strict/compat checks, reusable envelope, enforcement report, legacy-entrypoint audit, KG-context requirement, and guarded model ledger capture. | `modules/runtime_policy`, `model_adapters/guarded`, API runtime router, tests | Hardened first production slice. Strict mode blocks missing context/budget/trace/model/cost/gate evidence; coverage/audit reports show remaining gaps. |
| P0 | Provider Runtime Guard | Timeout/cancel/usage guard skeleton existed. | Normalized usage, cost estimation, controller events, OpenAI-compatible SSE usage, streaming delta cutoff, timeout/cancel checks, local worker process polling, and adapter runtime events. | `model_adapters`, `runtime_ledger`, `agent_runs` | Hardened first production slice for mock, local Codex, Claude Code Codex, and OpenAI-compatible adapters; future provider SDKs remain provider-specific. |
| P0 | Deep Checkpoint Resume | Checkpoint records and output reuse existed. | Stage schema, idempotency key, durable stage checkpoint assets, latest-checkpoint lookup, checkpoint chain, and resume plan. | `operation_checkpoint`, `workflow_nodes`, `agent_scheduler` | Hardened first production slice with unit coverage. |
| P0 | Business Rollback | Quarantine/supersede markers existed. | Operation transaction, rollback preview/apply/result, version restore, logical rollback, ledger compensation, KG dirty marker, and verification API/UI panel. | `operation_transactions`, schemas, constants, runtime API, Web OS Console | Hardened first production slice with unit coverage. |
| P0 | KG Semantic Depth | Novel KG and KG gate existed. | Identity resolution, merge queue, confidence/evidence handling, model-assisted candidate validation, semantic extraction report asset/API, KG-backed context enforcement, KG gate fast path. | `novel_kg`, `semantic_enhancement`, `continuity_graph`, Web KG Workbench | Hardened first production slice; production provider extraction remains future hardening. |
| P1 | Web OS Console Hardening | Seven OS routes existed with route/API contract tests. | OS console includes runtime policy coverage, legacy bypass audit, rollback preview/apply/verify; KG workbench exposes semantic extraction and identity merge queue; optional Playwright route smoke covers OS pages. | `web/admin`, OS API routers | First cockpit slice verified; Playwright browser smoke remains optional when Playwright is installed. |
| P1 | Feedback-to-plan Backflow | Feedback assets and insights existed. | Human-gated clusters and plan/rule/KG proposals. | `feedback_backflow`, feedback API, agent permissions | Completed first production slice with unit coverage. |
| P1 | Long-chain Scale Acceptance | One-chapter OS acceptance existed. | 3-chapter deterministic smoke plus opt-in 12/50 chapter pressure profile and scale metrics. | `operations`, integration tests | Completed smoke and opt-in pressure profile. |
| P2 | Operational polish | First slices are functional but sparse. | Richer filters, trend charts, evidence drawers, exportable reports. | Web OS Console, docs | Improves operator usability without blocking core runtime. |

## First Execution Batch

The first batch is P0 Universal Runtime Policy because it is the dependency root for provider guard, checkpoint resume, rollback, and scale acceptance.

Planned changes:

1. Add `src/novel_forge/modules/runtime_policy/`.
2. Add a central model-producing operation registry.
3. Add `check_runtime_policy()` and `runtime_policy_status()` APIs.
4. Expose:
   - `GET /product/runtime/policy/status`
   - `POST /product/runtime/policy/check`
5. Add unit tests for strict vs compatibility behavior.
6. Update implementation docs with current status and remaining work.

## Test Strategy

Baseline commands:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_policy
PYTHONPATH=src python3 -m unittest tests.unit.test_runtime_ledger tests.unit.test_workflow_executor tests.unit.test_agent_scheduler
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
npm --prefix web/admin test
npm --prefix web/admin run lint
git diff --check
```

Run browser smoke only when a live backend and Playwright dependency are available:

```bash
npm --prefix web/admin run smoke:browser
```

## Current Status

| Area | Status |
|---|---|
| Project scan | Complete for root configs, docs, API router map, worker tasks, module tree, web route tree, tests, runtime ledger, storage dirty tracking. |
| Optimization extraction | Complete. Eight closure items identified from source plan. |
| Execution plan | Complete for P0 and low-cost P1 closure batch. |
| Universal Runtime Policy | Hardened first production slice with envelope, enforcement report, legacy-entrypoint audit, KG-context check, and guarded model ledger capture. |
| Provider Runtime Guard | Hardened first production slice with runtime controller, OpenAI-compatible SSE streaming, local worker process polling, runtime events, and adapter integration. |
| Deep Checkpoint Resume | Hardened first production slice with durable stage checkpoint assets, checkpoint chain, and latest-checkpoint lookup. |
| Business Rollback | Hardened first production slice with preview/apply/verify APIs, version restore, and Web OS rollback panel. |
| KG Semantic Depth | Hardened first production slice with model-assisted extraction validation, identity merge queue, semantic extraction report/API/UI, and KG gate performance hardening. |
| Feedback Backflow | Complete first production slice. |
| Long-chain Scale Acceptance | Complete 3-chapter deterministic smoke and opt-in 12/50 chapter pressure test. |
| Validation | 214 unit tests, 5 integration tests with 1 intentional pressure skip, compileall, diff check, admin tests, TS lint, and `make validate` passed on 2026-06-29. |
