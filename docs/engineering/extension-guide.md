# Extension Guide

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

Use this guide when adding a new Novel Forge / Novel Operating System capability. The goal is to extend the existing operating layer instead of creating a parallel path.

## Start With Evidence

Before coding:

1. Read `CLAUDE.md`.
2. Read `docs/project-current-state.md`.
3. Inspect the relevant module, schema, API router, UI route, and tests.
4. Identify the asset type, operation, gate, and storage boundary.
5. Decide the smallest acceptance test that proves the change.

## Capability Checklist

| Layer | What To Add Or Verify | Evidence Path |
|---|---|---|
| Schema | Asset type, required fields, status, version, source lineage, confidence/evidence spans when needed | `src/novel_forge/schemas/assets.py` |
| Constants/storage | Asset directory, type mapping, validation coverage | `src/novel_forge/core/constants.py`, `src/novel_forge/storage/` |
| Module service | Domain/application implementation with narrow public function(s) | `src/novel_forge/modules/<capability>/` |
| Product API | Thin router plus service/use-case boundary | `src/novel_forge/api/routers/`, `src/novel_forge/api/services/` |
| Workflow | Node registration, run status, recovery behavior, idempotency | `src/novel_forge/workflows/`, `modules/workflow_nodes/` |
| Agent operation | Runtime profile/operation registration, queue runner, gates, budget, retry/dead-letter when scheduled | `modules/agent_registry/`, `modules/agent_scheduler/` |
| Context Builder | Source isolation, ranking, compression, token budget, replayable bundle | `modules/context_builder/` |
| MKAOS / Canon / KG | Knowledge selection, lineage, risk, continuity, graph update or gate | `modules/mkaos*`, `modules/canon_graph/`, `modules/novel_kg/` |
| Runtime policy | Provider route, allowlist/denylist, approval evidence, timeout/cancel, trace/model-call/cost ledger | `modules/runtime_policy/`, `modules/runtime_ledger/`, `model_adapters/`, `modules/model_router/` |
| Quality gate | ReviewIssue, EvaluationGate, ProviderGate, PlatformGate, MKAOS risk, publish/release gate | `modules/review_issue/`, `modules/evaluation_center/`, `modules/publishing/` |
| UI | Route/page, API helper, loading/error/empty states, operator evidence | `web/admin/app/` |
| Tests | Unit, integration, acceptance, fixture, UI or route smoke if relevant | `tests/` and `web/admin/tests/` |
| Docs | Current state, module map, capability map, roadmap, reports if behavior changed | `docs/` |
| Skills | Root Skill change only if repeatable capability guidance is needed | `skills/`; runtime sync via Makefile |

## Do Not Bypass These Boundaries

- OS Envelope for runtime evidence.
- Context Builder for generation context.
- ReviewIssue for blocking creative/quality defects.
- Canon/KG/continuity gates for long-form state.
- Runtime provider policy for model calls.
- Publishing facade and release gates for production release packages.
- Root `skills/` as Skill source of truth.

## Adding A New Creative Asset

1. Add or extend the schema in `src/novel_forge/schemas/assets.py`.
2. Add storage/type mapping if needed.
3. Implement a module service under `src/novel_forge/modules/`.
4. Add CLI/API/UI only if this is an operator-facing capability.
5. Add unit tests for schema and service behavior.
6. Add integration tests if the asset participates in a workflow.
7. Update `docs/project-current-state.md` and `docs/product/capability-map.md`.

## Adding A New Agent Operation

1. Define the bounded input/output contract and operation name.
2. Register the operation in the Agent operation registry.
3. Ensure scheduler runner code uses OS Envelope, provider policy, checkpoints, gates, and ledger evidence where applicable.
4. Add success, failure, retry, recovery, and dead-letter tests according to risk.
5. Add UI/ops report exposure if operators must inspect evidence.
6. Update the Agent/operation docs and roadmap.

## Adding Provider-Backed Behavior

Provider-backed code must fail closed in production.

Minimum requirements:

- explicit provider route resolution;
- production provider allowlist and mock denylist behavior;
- approval evidence recorded;
- timeout and cancel behavior;
- raw provider output checkpoint if needed for recovery;
- strict JSON/schema validation before writing assets;
- model call log and cost ledger;
- tests for missing, failed, and successful provider evidence.

## Splitting A Large Service

1. Add characterization tests before moving code.
2. Extract one seam at a time: query, command, runner, writer, gate, policy, or adapter.
3. Keep the public service facade stable unless the task explicitly changes it.
4. Run the focused tests plus `make lint`.
5. Update `docs/architecture/module-map.md` when the ownership boundary changes.

## Documentation Rule

Any new capability that changes operator behavior, public contracts, core architecture, tests, or roadmap must update docs in the same change. If a feature is only a design proposal, say so explicitly.
