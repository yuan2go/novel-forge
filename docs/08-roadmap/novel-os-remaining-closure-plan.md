# Novel OS Remaining Closure Plan

Date: 2026-06-29

## Current Judgment

Novel Forge v6 is already an early Novel Operating System runtime, not only a local AI novel production platform.

The current worktree has code, tests, and Web Admin first slices for:

- Workflow Executor and scheduler;
- Agent Scheduler and dispatch queue;
- Novel KG, KG gate, semantic enhancement, and dirty tracking;
- trace spans, gate results, model call logs, cost ledgers, budget policies, and cost-quality dashboard assets;
- review rework loop from issue to revision task, patch, draft version, re-review, and publish gate;
- OS acceptance integration fixture;
- Web OS console routes.

The remaining gap is no longer "build the OS skeleton". The remaining gap is:

```text
first production slice
  -> universal enforcement
  -> true provider runtime control
  -> deep resumability
  -> business rollback
  -> semantic depth
  -> operational UX
  -> feedback learning loop
  -> long-chain scale acceptance
```

Estimated current maturity:

| Area | Current maturity | Target for complete Novel OS |
|---|---:|---|
| Local novel production platform | 88%-90% | 95%+ |
| Workflow Executor | 84%-86% | 92%+ |
| Agent Scheduler | 80%-82% | 92%+ |
| Trace Timeline / Cost Ledger | 80% | 92%+ |
| Novel Knowledge Graph | 78%-80% | 90%+ |
| Review Rework Loop | 78%-80% | 90%+ |
| Web OS Console | 75%-78% | 90%+ |
| Novel Operating System overall | 80%-83% | 95% |

The project is roughly 17%-20% away from a complete Novel Operating System.

## Implementation Update 2026-06-29

The first closure implementation batch is now complete as a hardened first production slice:

- Universal Runtime Policy includes strict/compat checks, `RuntimePolicyEnvelope`, enforcement reports, KG-context requirements, guarded model-call ledger capture, and a legacy-entrypoint bypass audit.
- Provider Runtime Guard includes normalized usage/cost, OpenAI-compatible SSE streaming usage, streaming token cutoff, timeout/cancel checks, and polling-based live cancel for local Codex / Claude Code workers.
- Checkpoint Resume includes stage checkpoint records, durable `agent_checkpoint` assets, checkpoint chains, and resume plans across prompt/provider/raw-output/validation/commit phases.
- Business Rollback includes transaction/plan/result assets, preview/apply/verify APIs, ledger compensation, dirty-index markers, and version-restore rollback actions.
- Novel KG Semantic Depth includes model-assisted candidate validation, identity resolution / merge queues, confidence/evidence spans, KG-backed context enforcement, and KG workbench actions.
- Web OS Console includes runtime policy coverage, legacy bypass audit, rollback preview/apply/verify, KG identity queues, and route/API contract tests.

Remaining work is now mostly provider-specific, scale, and cockpit polish: native streaming bindings for future providers, making every long operation call stage checkpoints internally, cross-node rollback consistency checks, production provider KG extraction behind runtime policy, richer browser-backed UI smoke, and recurring 12/50+ chapter pressure acceptance.

## Priority Order

The eight remaining gaps should not be implemented independently. They form a dependency chain:

```text
Universal Runtime Policy
  -> Provider Runtime Guard
  -> Deep Checkpoint Resume
  -> Business Rollback
  -> KG-backed Context/Gates
  -> Feedback-to-plan Learning
  -> Web OS Console Operations
  -> Long-chain Scale Acceptance
```

Recommended delivery order:

1. Universal Runtime Policy.
2. Provider-level runtime guard and cost usage capture.
3. Deep checkpoint/resume protocol for model-producing operations.
4. Business rollback and transactional output groups.
5. KG semantic depth and KG-backed mandatory context/gates.
6. Feedback-to-plan automatic learning loop.
7. Web OS Console operational hardening.
8. Long-chain multi-chapter acceptance.

## 1. Universal Runtime Policy

### Current State

Scheduler-mediated paths are relatively strong. `execute_workflow`, `resume_workflow`, Agent Scheduler, and `execute_agent_run_once` can enforce context, budget, trace, model call, cost ledger, and gate evidence.

The remaining issue is inconsistent enforcement across older or direct entry points:

- CLI commands can still call module services directly.
- Some FastAPI endpoints call domain services without a runtime execution envelope.
- Some module-level model calls can write output assets before model-call/cost evidence is complete.
- Some deterministic tests and sample flows intentionally bypass full OS policy.

### Target State

Every model-producing or production-mutating operation must run inside one standard runtime envelope:

```text
RuntimeExecutionContext
  -> policy preflight
  -> trace span start
  -> budget precheck
  -> provider runtime guard
  -> model call log
  -> cost ledger
  -> schema validation
  -> gate result
  -> output commit or quarantine
  -> trace span finish
```

The rule should be fail-closed for OS mode:

```text
No context bundle when required -> blocked
No active budget policy when required -> blocked
No model_call_log for model work -> blocked
No cost_ledger for nonzero usage/cost -> blocked
No trace span -> blocked
No gate result for gated operations -> blocked
```

### Implementation Plan

#### 1.1 Add a runtime execution envelope

Create a shared module:

```text
src/novel_forge/modules/runtime_policy/
  __init__.py
  service.py
```

Core API:

```python
class RuntimeExecutionContext:
    project_id: str
    workspace_path: str
    operation: str
    operation_kind: str
    input_assets: list[str]
    output_types: list[str]
    context_bundle_path: str
    runtime_policy: dict[str, Any]
    trace: dict[str, str]

def begin_runtime_execution(...): ...
def record_model_result(...): ...
def commit_runtime_outputs(...): ...
def fail_runtime_execution(...): ...
```

This module should wrap existing ledger functions rather than duplicating them.

#### 1.2 Add a model-producing operation registry

Add a central policy map:

```python
MODEL_PRODUCING_OPERATIONS = {
    "draft",
    "generate_draft",
    "review",
    "revise",
    "editor_patch",
    "analysis_run",
    "analysis_convert",
    "model_benchmark",
    "semantic_kg_extract",
    "feedback_cluster",
}
```

Each entry should define:

- required input asset types;
- whether `context_bundle` is mandatory;
- whether `budget_policy` is mandatory;
- required gate kinds;
- model usage recording requirements;
- allowed bypass mode for tests only.

#### 1.3 Route old entry points through the envelope

High-priority files to wrap:

| Area | Files |
|---|---|
| Draft/review/revision | `src/novel_forge/modules/drafting/*`, `src/novel_forge/modules/review/*`, `src/novel_forge/modules/revision/*` |
| Analysis/conversion | `src/novel_forge/modules/analysis/*`, API analysis routers |
| Editor | `src/novel_forge/modules/editor/*`, draft/editor routes |
| Model evaluation | `src/novel_forge/modules/evaluation/*` |
| Feedback semantic clustering | `src/novel_forge/modules/feedback/*` |
| CLI | `src/novel_forge/cli/*` model-producing commands |

FastAPI and CLI should call the same service wrapper. No endpoint should construct model-call/cost evidence manually.

#### 1.4 Add bypass rules only for deterministic tests

Allowed bypass:

```text
NOVEL_FORGE_RUNTIME_POLICY_MODE=compat
```

Strict mode:

```text
NOVEL_FORGE_RUNTIME_POLICY_MODE=operating_system
```

Tests that prove legacy compatibility can use `compat`; OS acceptance tests must use `operating_system`.

### Acceptance Criteria

- A direct API draft/review/revision call writes `trace_span`, `model_call_log`, and `cost_ledger`.
- A direct CLI model-producing command writes the same evidence or fails with a clear policy error.
- Missing budget policy blocks OS-mode model work.
- Missing context bundle blocks OS-mode context-bound operations.
- Existing scheduler-mediated tests continue passing.
- Add tests:

```text
tests/unit/test_runtime_policy.py
tests/integration/test_universal_runtime_policy.py
```

## 2. Provider-level Runtime Guard

### Current State

Runtime guard skeletons exist:

- timeout fields;
- cancellation flags;
- token usage checks;
- provider usage parsing for some local Codex output;
- fail-closed provider guard wrapper.

The remaining gaps:

- streaming usage is not universally available;
- OpenAI-compatible providers, DeepSeek, Codex CLI, Claude Code Codex, and mock do not expose a normalized usage lifecycle;
- hard cutoff is mostly postflight, not realtime;
- precise cost depends on provider usage being returned consistently;
- cancellation is a policy flag, not always a live cancellation mechanism.

### Target State

All provider calls should report a normalized lifecycle:

```text
provider_call_started
provider_usage_delta
provider_token_cutoff
provider_timeout
provider_cancel_requested
provider_call_finished
provider_call_failed
```

Normalized usage shape:

```json
{
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "cached_tokens": 0,
  "reasoning_tokens": 0,
  "elapsed_ms": 0,
  "provider_request_id": "",
  "finish_reason": "",
  "usage_source": "provider|codex_stdout|estimated"
}
```

### Implementation Plan

#### 2.1 Define provider runtime interfaces

Create:

```text
src/novel_forge/model_adapters/runtime.py
```

Core contracts:

```python
class ProviderRuntimeGuard:
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_total_tokens: int | None
    timeout_ms: int | None
    cancel_file: str | None
    cost_profile: dict[str, Any]

class ProviderUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    elapsed_ms: int
    usage_source: str

class ProviderRuntimeEvent:
    event_type: str
    usage: ProviderUsage
    message: str
```

#### 2.2 Normalize adapters

Required behavior by provider:

| Provider | Required implementation |
|---|---|
| `mock` | deterministic usage and cost for tests |
| `codex` | parse usage from `codex exec` stdout; enforce process timeout; support cancel file before spawn |
| `claude-code` | same command path with `CODEX_HOME=~/.codex-claude codex`; parse stdout usage; support timeout |
| `chatgpt` | parse provider usage response; estimate only if provider omits usage |
| `deepseek` | parse OpenAI-compatible usage response; cost from model profile |

#### 2.3 Add live cutoff where possible

For stream-capable providers:

- stop reading stream if projected total exceeds limit;
- record `provider_token_cutoff` event;
- mark model call failed or cancelled;
- do not commit output unless policy allows partial output.

For non-streaming providers:

- preflight context size before request;
- postflight usage guard;
- mark over-budget output quarantined.

#### 2.4 Tie provider usage to ledger

`record_model_call_log` should receive real provider usage whenever available.

Cost source priority:

1. provider-returned cost if available;
2. provider-returned token usage plus `model_profile.cost_profile`;
3. deterministic estimate with `usage_source=estimated`.

### Acceptance Criteria

- Every adapter returns normalized `ProviderUsage`.
- Timeout creates failed `model_call_log` and `trace_span`.
- Token cutoff creates `cost_alert` or guard failure.
- Cost ledger uses real token usage for OpenAI-compatible providers when returned.
- Codex/Claude Code provider tests verify `CODEX_HOME=~/.codex-claude codex` path.
- Add tests:

```text
tests/unit/test_provider_runtime_guard.py
tests/unit/test_model_adapter_usage_normalization.py
tests/integration/test_provider_runtime_policy.py
```

## 3. Deep Checkpoint Resume

### Current State

Checkpointing currently supports:

- checkpoint records;
- output reuse;
- retry;
- generic operation checkpoint schema;
- rollback/quarantine metadata.

The missing capability is service-internal mid-step resume. A long model operation that has completed prompt preparation but failed during provider call cannot continue from the exact mid-state without rerunning earlier service logic.

### Target State

Each long-running operation must expose a resumable state machine:

```text
prepared_inputs
  -> context_built
  -> prompt_built
  -> provider_started
  -> provider_completed
  -> output_validated
  -> output_committed
  -> gates_completed
```

Resume should choose the cheapest safe stage:

```text
if output committed and valid -> reuse output
if provider completed and raw result stored -> validate and commit
if prompt built but provider failed -> restart provider only
if context stale -> rebuild context and rerun
```

### Implementation Plan

#### 3.1 Extend operation contracts

For both workflow processors and Agent operations:

```python
checkpoint_schema = {
    "version": "1.0",
    "stages": [...],
    "resume_points": [...],
    "idempotency_key_fields": [...],
    "safe_to_replay": bool,
}
```

Add methods:

```python
prepare_checkpoint_state(...)
resume_from_checkpoint(...)
validate_checkpoint_state(...)
```

#### 3.2 Store operation state as durable checkpoint assets

Checkpoint content should include:

- normalized input asset hashes;
- context bundle path and hash;
- prompt version and prompt hash;
- provider request id when available;
- raw provider output path if stored;
- validation errors;
- output asset paths;
- gate result paths;
- idempotency key.

#### 3.3 Add idempotency enforcement

Before rerunning an operation:

- calculate idempotency key from operation, input asset hashes, context bundle hash, prompt version, and model;
- search for previous successful checkpoint;
- reuse if valid and no upstream invalidation exists.

#### 3.4 Apply to first operations

Start with:

1. `draft`;
2. `review`;
3. `revision/rework`;
4. `analysis_run`;
5. `semantic_kg_extract`;
6. `model_benchmark`.

### Acceptance Criteria

- Simulated failure after prompt build resumes from provider call stage.
- Simulated failure after provider completion resumes from validation/commit stage.
- Stale input invalidates checkpoint reuse.
- Idempotency prevents duplicate draft/version assets.
- Add tests:

```text
tests/unit/test_operation_checkpoint_resume.py
tests/integration/test_deep_checkpoint_resume.py
```

## 4. Business-level Rollback

### Current State

The runtime can mark outputs as:

- quarantined;
- rolled_back;
- rollback_required;
- superseded.

This is enough for first-slice safety, but it is not full business rollback.

Missing:

- multi-asset transaction groups;
- restore previous version as active;
- rollback across workflow/node/agent/cost/KG/index side effects;
- UI one-click rollback with preview;
- clear distinction between physical delete, logical rollback, and supersede.

### Target State

Every production operation should write an `operation_transaction` record:

```json
{
  "transaction_id": "",
  "operation": "",
  "workflow_run_id": "",
  "agent_run_id": "",
  "input_assets": [],
  "created_assets": [],
  "updated_assets": [],
  "previous_versions": [],
  "indexes_touched": [],
  "ledger_paths": [],
  "rollback_plan": {},
  "rollback_status": "available|applied|manual_required|unsafe"
}
```

Rollback should support:

```text
preview -> apply -> verify -> trace -> report
```

### Implementation Plan

#### 4.1 Add transaction asset schema

New asset types:

```text
operation_transaction
rollback_plan
rollback_result
```

Directory:

```text
data/runs/
```

#### 4.2 Add write-set tracking to LocalStorage

LocalStorage should support an optional transaction recorder:

```python
with operation_transaction(storage, operation, trace) as tx:
    storage.write_asset(...)
    storage.update_asset(...)
```

The recorder should capture:

- asset path;
- previous content hash;
- new content hash;
- asset type;
- mutation kind.

#### 4.3 Implement rollback strategies

| Strategy | Behavior |
|---|---|
| `supersede_outputs` | mark generated outputs superseded; restore previous active version |
| `quarantine_outputs` | mark unsafe outputs quarantined |
| `restore_previous_version` | copy previous version to active state through new version record |
| `manual_reconciliation_required` | write rollback plan but do not apply |
| `ledger_adjustment` | write negative or compensating ledger row, never delete ledger history |

#### 4.4 Integrate with Web OS Console

Add to:

- Workflow Runtime Console;
- Agent Dispatch Center;
- Review Rework Board;
- Invalidation Map.

UI should show:

- transaction summary;
- rollback preview;
- affected assets;
- unsafe rollback reasons;
- apply rollback action.

### Acceptance Criteria

- A failed post-gate rollback restores previous active draft version.
- Cost ledger is compensated, not deleted.
- KG dirty index is marked after rollback touches story assets.
- Rollback result has trace span and references transaction.
- UI route exposes rollback preview and apply action.
- Add tests:

```text
tests/unit/test_operation_transaction.py
tests/integration/test_business_rollback.py
```

## 5. KG Semantic Depth

### Current State

Novel KG first slice exists:

- typed ontology collections;
- structured projection;
- semantic projection;
- query/path/impact/conflict APIs;
- KG gate;
- dirty tracking;
- continuity preflight integration.

Current semantic extraction is still mostly local deterministic/rule-based. It does not yet provide strong model-assisted extraction, alias merge, confidence governance, or mandatory KG-backed context across all production paths.

### Target State

Novel KG should become a production memory and reasoning substrate:

```text
asset write
  -> semantic extraction
  -> entity/relation/event/rule merge
  -> confidence/evidence update
  -> KG snapshot/projection
  -> context builder source ranking
  -> review/continuity/publish gate
  -> downstream invalidation
```

### Implementation Plan

#### 5.1 Add semantic extractor contracts

New operation:

```text
semantic_kg_extract
```

Output:

```text
semantic_extraction_report
```

Report fields:

- entities;
- aliases;
- relations;
- events;
- state changes;
- rules;
- timeline anchors;
- foreshadowing events;
- evidence spans;
- confidence;
- extractor provider/model;
- prompt version.

#### 5.2 Alias merge and canonical identity

Add canonical merge service:

```text
src/novel_forge/modules/novel_kg/identity.py
```

Merge rules:

- exact normalized name;
- alias overlap;
- source lineage;
- embedding similarity when semantic provider exists;
- model-assisted merge recommendation for ambiguous cases;
- human gate for high-impact merge.

Store:

```text
kg_identity_resolution
```

#### 5.3 Evidence span model

Every KG node/edge should carry:

```json
{
  "evidence_spans": [
    {
      "source_path": "",
      "field_path": "",
      "start": 0,
      "end": 0,
      "snippet": "",
      "confidence": 0.0,
      "extractor": ""
    }
  ]
}
```

The gate should block high-impact conflicts that have high-confidence evidence.

#### 5.4 KG-backed context enforcement

Context Builder should have a required KG profile in OS mode:

```text
context_bundle
  -> kg_context
  -> chapter continuity facts
  -> open foreshadowing
  -> active rules
  -> character states
  -> power scale constraints
```

If KG context is missing in OS mode, draft/review/publish should block.

#### 5.5 Workbench improvements

Novel KG Workbench should add:

- canonical identity merge queue;
- conflict drilldown with evidence span;
- relationship network graph;
- timeline graph;
- foreshadowing lifecycle graph;
- impact query preview;
- KG context preview for selected target.

### Acceptance Criteria

- Drafting without required KG context blocks in OS mode.
- A semantic extraction report creates/updates typed KG nodes and edges.
- Alias merge produces canonical IDs and keeps evidence.
- KG gate includes evidence spans in blocking conflicts.
- Context bundle records KG facts used.
- Add tests:

```text
tests/unit/test_novel_kg_identity.py
tests/unit/test_semantic_kg_extraction.py
tests/integration/test_kg_backed_context_gate.py
```

## 6. Web OS Console Operational Hardening

### Current State

Routes exist for:

- `/os`;
- `/workflow-runtime`;
- `/agent-dispatch`;
- `/novel-kg`;
- `/trace-timeline`;
- `/cost-dashboard`;
- `/invalidation`;
- `/review-rework`.

Current tests prove route files and API endpoint strings exist. This is route/API contract coverage, not real browser operational smoke.

### Target State

The Web OS Console should be a true operator cockpit:

```text
See current state
  -> inspect evidence
  -> trigger scheduler/execute/resume/recover
  -> inspect gate/cost/trace/KG
  -> rollback or rework
  -> verify output
```

### Implementation Plan

#### 6.1 Add route-level Playwright smoke

Use deterministic backend fixture:

```text
scripts/web_os_fixture.py
```

Fixture should create:

- project;
- workflow definition/run;
- agent dispatch queue;
- KG snapshot/gate;
- trace spans;
- cost ledger;
- review/rework assets;
- invalidation report.

Then Playwright tests load each route and assert visible controls.

Routes:

```text
/os
/workflow-runtime
/agent-dispatch
/novel-kg
/trace-timeline
/cost-dashboard
/invalidation
/review-rework
```

#### 6.2 Add visual depth

Feature upgrades:

| Page | Needed depth |
|---|---|
| Workflow Runtime Console | DAG graph, ready-node queue lease state, blocked node detail, processor contract drawer |
| Agent Dispatch Center | Agent timeline, checkpoint detail, retry/dead-letter drilldown, operation contract evidence |
| Novel KG Workbench | network graph, timeline, identity merge queue, evidence span drilldown |
| Trace Timeline | parent/child waterfall, filters by trace/span type, linked node/agent/model call |
| Cost Dashboard | provider/model/operation trends, budget alerts, cost-quality scatter/table |
| Invalidation Map | upstream/downstream graph, stale asset list, resume candidates |
| Review Rework Board | issue-to-task-to-patch-to-version lineage, apply/re-review/publish gate status |

#### 6.3 Add operator actions with confirmation

Every destructive or state-changing action should require:

- preview;
- affected assets;
- expected result;
- confirmation;
- trace span after action.

### Acceptance Criteria

- `npm --prefix web/admin run smoke:browser` can run against fixture backend.
- Every OS route loads without console errors.
- Each route renders at least one real fixture row.
- Execute/resume/recover/rework actions work against fixture.
- Mobile and desktop layouts do not overflow key tables/buttons.

## 7. Feedback-to-plan Automatic Backflow

### Current State

Reader feedback assets and analysis exist. The system can produce feedback insights, sentiment/trend reports, and operational metrics.

Missing:

- stable mapping from feedback cluster to chapter plan/review rule/KG node;
- automatic creation of revision tasks or future planning tasks;
- workflow integration for feedback-driven plan updates;
- human gate before feedback changes canonical plans.

### Target State

Reader feedback should become a controlled planning input:

```text
reader_feedback
  -> feedback_cluster
  -> feedback_insight
  -> affected chapter/character/thread/KG node
  -> plan_adjustment_proposal
  -> review_rule_update_proposal
  -> workflow node
  -> human gate
  -> chapter_plan_version / review_rule_pack / KG patch
```

### Implementation Plan

#### 7.1 Add feedback learning assets

New asset types:

```text
feedback_cluster
feedback_backflow_plan
plan_adjustment_proposal
review_rule_update_proposal
feedback_kg_patch
```

#### 7.2 Build mapping service

Create:

```text
src/novel_forge/modules/feedback_backflow/service.py
```

Responsibilities:

- cluster feedback by chapter, sentiment, toxicity, payoff, role, thread;
- map cluster to KG nodes and chapter plans;
- identify target action:
  - revise current draft;
  - adjust future chapter plan;
  - update review rule;
  - update KG/canon patch;
  - no action.

#### 7.3 Add workflow operations

Processor operations:

```text
feedback_cluster
feedback_backflow_plan
apply_plan_adjustment
apply_review_rule_update
apply_feedback_kg_patch
```

All apply operations require human gate by default.

#### 7.4 Add UI

Extend Feedback Center or add panel in OS Console:

- cluster list;
- affected assets;
- proposed changes;
- human approval;
- generated task/version evidence.

### Acceptance Criteria

- Feedback about weak hook creates `plan_adjustment_proposal`.
- Feedback about confusing rule maps to KG/rule candidate.
- Approved proposal creates new `chapter_plan_version` or `review_rule_pack` version.
- Workflow records trace/gate/backflow evidence.
- No feedback directly mutates outline/chapter plans without human gate.
- Add tests:

```text
tests/unit/test_feedback_backflow.py
tests/integration/test_feedback_to_plan_workflow.py
```

## 8. Long-chain Scale Acceptance

### Current State

The OS acceptance fixture proves a minimal one-project, one-chapter runtime chain.

That is correct for P0 runtime integrity, but it does not prove:

- multi-chapter continuity stability;
- quality drift;
- cost drift;
- provider timeout behavior over long runs;
- foreshadowing lifecycle;
- reader feedback backflow;
- scheduler health under repeated runs;
- rollback/recovery under mixed failures.

### Target State

Add long-chain acceptance suites at three scales:

| Scale | Purpose | Suggested size |
|---|---|---|
| S | deterministic local chain | 3 chapters |
| M | scheduler/cost/KG drift | 12 chapters |
| L | long-form pressure | 50+ chapters or simulated 1M-word plan |

The long-chain test should not require real external providers by default. It should run with deterministic mock/local workers, with optional provider-backed smoke behind environment flags.

### Implementation Plan

#### 8.1 Add fixture generator

Create:

```text
tests/fixtures/long_chain/
scripts/create_long_chain_fixture.py
```

Fixture should include:

- project/workspace;
- world bible;
- characters;
- outline;
- chapter plans;
- continuity rules;
- foreshadowing threads;
- reader feedback sample;
- budget policy;
- workflow definitions.

#### 8.2 Add long-chain report

Extend `long_chain_acceptance_report` or add:

```text
novel_os_scale_acceptance_report
```

Metrics:

- chapter count;
- workflow success rate;
- agent success/retry/dead-letter count;
- average review score;
- quality drift;
- continuity conflict count;
- KG dirty count;
- unresolved foreshadowing count;
- cost total and cost per chapter;
- model call count;
- rollback/recovery count;
- feedback backflow count.

#### 8.3 Add test profiles

Commands:

```bash
python3 -m unittest tests.integration.test_novel_os_acceptance
python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
NOVEL_FORGE_LONG_CHAIN=1 python3 -m unittest tests.integration.test_novel_os_long_chain_pressure
```

Default CI should run the smoke profile, not the pressure profile.

#### 8.4 Add failure injection

Simulate:

- provider timeout;
- budget exceeded;
- KG conflict;
- stale context;
- failed review gate;
- rollback after post-gate failure;
- scheduler lease collision.

### Acceptance Criteria

- 3-chapter smoke completes locally under deterministic providers.
- 12-chapter profile records cost/quality/KG trends.
- Failure injection produces recovery evidence and no silent asset corruption.
- Long-chain report recommends pass/warn/block with actionable findings.

## Cross-cutting Architecture Changes

### New or Expanded Asset Types

Recommended new assets:

```text
operation_transaction
rollback_plan
rollback_result
semantic_extraction_report
kg_identity_resolution
feedback_cluster
feedback_backflow_plan
plan_adjustment_proposal
review_rule_update_proposal
feedback_kg_patch
novel_os_scale_acceptance_report
```

### New Service Modules

```text
src/novel_forge/modules/runtime_policy/
src/novel_forge/model_adapters/runtime.py
src/novel_forge/modules/operation_transactions/
src/novel_forge/modules/novel_kg/identity.py
src/novel_forge/modules/feedback_backflow/
```

### API Additions

```text
GET  /product/runtime/policy/status
POST /product/runtime/policy/check
GET  /product/provider/runtime/status
POST /product/operations/rollback/preview
POST /product/operations/rollback/apply
GET  /product/novel-kg/identity/merge-queue
POST /product/novel-kg/identity/merge
POST /product/feedback/backflow/plan
POST /product/feedback/backflow/apply
POST /product/os/scale-acceptance
```

### Web Additions

```text
/workflow-runtime      rollback preview, transaction drawer
/agent-dispatch        checkpoint stage timeline
/novel-kg              identity merge and evidence spans
/trace-timeline        waterfall view
/cost-dashboard        trend and alert views
/invalidation          stale asset graph
/review-rework         lineage graph
/feedback              backflow proposals
/os                    scale acceptance summary
```

## Final Acceptance Definition

The project should be considered a complete Novel Operating System only when these are true:

1. Every model-producing path is covered by Universal Runtime Policy.
2. Every provider returns normalized usage and participates in budget/timeout/cancel enforcement.
3. Long-running operations can resume from meaningful checkpoints, not only rerun or reuse completed outputs.
4. Multi-asset operations have previewable, traceable business rollback.
5. Novel KG drives context, review, continuity, publishing, and invalidation gates.
6. Web OS Console can operate the system, not only inspect it.
7. Reader feedback can create traceable, human-gated plan/rule/KG updates.
8. Long-chain acceptance proves multi-chapter stability, cost control, quality drift handling, and recovery.

Until then, the correct label remains:

```text
Novel Forge v6 = local-first AI novel production platform + early Novel Operating System runtime
```

After these closure tasks pass:

```text
Novel Forge = Novel Operating System implementation
```
