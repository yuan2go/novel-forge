# Agent Scheduler Design

Status: P0 scheduler implemented; first real-service Agent operation registry is wired.

Last reviewed: 2026-06-28.

## Current Code Baseline

The Agent Registry is already strong enough to become a schedulable runtime boundary:

- Runtime profiles and skill mapping live in `src/novel_forge/agents/runtime.py`.
- Agent contracts, runs, events, checkpoints, budgets, gates, SLA reports, rollback reports, and failure reports live in `src/novel_forge/modules/agent_runs/service.py`.
- Workflow agent nodes already create `agent_contract`, prepared `agent_run`, and `agent_dispatch_queue` assets through `_dispatch_agent_node()` in `src/novel_forge/modules/workflow_nodes/service.py`.
- `execute_agent_run_once()` enforces tool/output allowlists, token budget, budget policy, provider runtime guard, checkpoint recording, budget assets, model call logs, cost ledger, SLA reports, and failure reports.
- `src/novel_forge/modules/agent_scheduler/service.py` provides the first independent Agent Scheduler: dispatch queue materialization, lease-protected tick/loop execution, claim/ack/retry/dead-letter/recover, output-reuse execution, real local-service operation runners, and Workflow resume adapter.
- Workflow scheduling already exists as `run_workflow_scheduler()` and `run_workflow_scheduler_loop()`. It scans blocked workflow runs, persists `ready_node_queue`, claims leases, and can resume prepared Agent runs when output assets are already available.
- Celery can run `novel_forge.workflow_scheduler_loop` and `novel_forge.agent_scheduler_loop`; the Web Admin Production Control page exposes Workflow Scheduler and Agent Scheduler controls.

This means the remaining architectural step is no longer "create Agent Scheduler" or "prove local-service dispatch". It is to deepen operation-level checkpoint resume/rollback and continue expanding provider-backed operations where adapters expose live usage/cancel data.

## Current Gaps

1. `AgentOperationRegistry` now wraps the first production services across decomposition, materials, outline, chapter plan, drafting, review/revision, analysis conversion, editor, continuity, quality/style/audit/publishing, versioning, and feedback metrics. Some specialized production modules and model-evaluation operations still need registry contracts.
2. Prepared `agent_run` execution no longer requires declared expected outputs for registered operations. Unregistered operations still fall back to verified output reuse and otherwise move to `waiting_human`.
3. Operation-level `checkpoint_schema`, `resume_from_checkpoint()`, and rollback are present as protocol shape but not yet implemented deeply for every service operation.
4. Provider streaming cutoff depends on adapters surfacing usage/cancel data consistently.
5. Agent Scheduler UI shows queue state and recover actions, but a deeper Agent Center evidence timeline is still needed.

## Target Boundary

Workflow remains the owner of DAG order and node state.

Agent Scheduler becomes the owner of AgentRun lifecycle after a workflow node has been prepared.

```text
Workflow Executor
  parses DAG
  resolves dependencies
  creates NodeRun(prepared)
  creates AgentContract
  creates AgentRun(prepared)
  enqueues AgentDispatchQueue

Agent Scheduler
  claims AgentDispatchQueue
  validates AgentContract
  runs Agent operation
  records budget/SLA/gates/checkpoints/model/cost/trace
  marks AgentRun succeeded/failed/waiting_human/dead_letter

Workflow Resume Adapter
  consumes succeeded AgentRun output assets
  calls resume_workflow(..., archive_previous=True)
  advances downstream DAG nodes
```

This keeps workflow orchestration deterministic while allowing Agent execution to be retried or recovered independently.

## Runtime Objects

### `agent_dispatch_queue`

New persisted queue asset under `data/runs`.

Required content:

```json
{
  "dispatch_id": "agent_dispatch_...",
  "idempotency_key": "workflow_run_id:node_id:agent_run_id:contract_id",
  "status": "queued|claimed|running|waiting_human|acked|retry_scheduled|dead_letter|cancelled",
  "agent_run_id": "",
  "agent_run_path": "",
  "agent_contract_path": "",
  "workflow_run_id": "",
  "workflow_run_path": "",
  "workflow_node_id": "",
  "operation": "",
  "agent_key": "",
  "priority": 100,
  "attempt_count": 0,
  "max_attempts": 3,
  "available_at": "",
  "lease_owner": "",
  "lease_expires_at": "",
  "claimed_at": "",
  "acked_at": "",
  "dead_lettered_at": "",
  "last_error": "",
  "checkpoint_path": "",
  "result": {},
  "trace": {
    "trace_id": "",
    "span_id": "",
    "parent_span_id": ""
  }
}
```

Queue rules:

- Queue ID must be deterministic from `workflow_run_id`, `workflow_node_id`, `agent_run_id`, and `contract_id`.
- A live `claimed` item cannot be claimed by another owner until its lease expires.
- `acked` and `cancelled` items are terminal.
- `dead_letter` can only be recovered through an explicit recovery action or a policy-backed recovery tick.
- Every claim increments `attempt_count`.
- `available_at` implements retry backoff without sleeping worker processes.

### `agent_operation_contract`

The existing `agent_contract` remains the persisted policy record. The scheduler adds an in-code registry contract:

```python
AgentOperationContract(
    operation="draft.generate",
    agent_key="draft",
    runner_kind="local_service|model_adapter|codex_cli|claude_code|human_handoff",
    input_types=["chapter_plan", "context_bundle"],
    output_types=["draft_chapter", "draft_version", "generation_run"],
    required_tools=["read_asset", "call_model_adapter", "write_draft_chapter", "run_validation"],
    input_schema={...},
    output_schema={...},
    checkpoint_schema={...},
    idempotency_key_template="...",
    resume_supported=True,
    rollback_strategy="mark_outputs_rolled_back",
    gates=["permission", "schema", "source_boundary", "originality", "quality"],
    budget_policy={"scope": "project", "max_tokens": 12000, "max_cost": 1.5},
    sla_seconds=1800,
)
```

First registry operations should wrap services that already use `AgentExecutionContext`, because they already produce traceable Agent runs and guard calls:

- analysis reports and analysis conversion;
- decomposition and knowledge/material generation;
- outline, chapter plan, drafting, review, revision, editor;
- continuity graph and publishing gate operations;
- model evaluation benchmark/comparison operations.

## AgentRun State Machine

Add `AgentRunStateMachine.apply_transition()`.

Allowed transitions:

```text
planned -> prepared
prepared -> running
prepared -> waiting_human
prepared -> cancelled
running -> checkpointed
running -> verifying
running -> waiting_human
running -> succeeded
running -> failed
running -> cancelled
checkpointed -> running
checkpointed -> failed
waiting_human -> prepared
waiting_human -> running
waiting_human -> cancelled
verifying -> succeeded
verifying -> needs_revision
verifying -> failed
needs_revision -> prepared
failed -> prepared
failed -> recovered
failed -> dead_letter
dead_letter -> prepared
recovered -> running
```

`queued` should remain a queue status, not an AgentRun status. The AgentRun stays `prepared` until a worker owns it.

All of these entry points must use the state machine:

- `start_agent_run()`
- `update_agent_run_status()`
- `execute_agent_run_once()`
- scheduler claim/start/fail/succeed paths
- handoff accept/fail/retry synchronization
- recovery actions

## Scheduler Tick

`run_agent_scheduler_tick()` should do this:

1. Acquire scheduler lease `agent_scheduler`.
2. Discover queue candidates:
   - existing `agent_dispatch_queue` items with `queued`, `retry_scheduled`, or expired `claimed`;
   - prepared `agent_run` assets with workflow binding but no queue item;
   - failed/dead-letter Agent runs only when recovery policy permits.
3. Materialize missing `agent_dispatch_queue` assets.
4. Claim up to `limit` queue items.
5. For each claim:
   - load `agent_run` and `agent_contract`;
   - validate project scope and input assets;
   - apply `prepared -> running`;
   - run pre-gates: permission, input schema, source boundary, stale input, budget preflight, SLA deadline;
   - execute via `AgentOperationRegistry`;
   - record provider usage through `model_call_log` and `cost_ledger`;
   - record checkpoint state;
   - run post-gates: output schema, project scope, originality, review/quality, publish/continuity where configured;
   - apply `running/verifying -> succeeded`, `needs_revision`, `waiting_human`, or `failed`;
   - ack, retry, or dead-letter the queue item.
6. For succeeded Agent runs linked to a workflow node, call Workflow Resume Adapter.
7. Release scheduler lease and record `last_tick`.

## Workflow Resume Adapter

The adapter is intentionally small:

```text
AgentRun succeeded
  -> read output_assets, token_used, cost_estimate, checkpoint
  -> resume_workflow(workflow_run_path, resume_node_id, agent_run_path, output_assets, token_used, cost_estimate, checkpoint, archive_previous=True)
```

It should not parse DAGs or make Agent policy decisions. Workflow state remains in Workflow Executor.

Failure behavior:

- If Agent execution fails before outputs exist, keep the workflow run blocked on the Agent node and write failure evidence to AgentRun, AgentFailureReport, AgentGate, trace spans, and queue `last_error`.
- If the failure is recoverable, schedule retry with backoff.
- If retry is exhausted, mark queue `dead_letter` and AgentRun `dead_letter`.
- A later recovery action can move `dead_letter -> prepared`, create a new queue attempt, and preserve lineage to the failed run.

## Runtime Guards

Budget/SLA/gates must be active runtime controls, not end-of-run reports:

- Budget preflight reads `budget_policy` and `cost_ledger` before execution.
- Provider guard receives streaming or returned usage from model adapters.
- Token cutoff cancels provider execution when possible; otherwise it fails the AgentRun immediately after usage is known.
- SLA deadline is computed before execution and checked at claim, checkpoint, provider call, and finalization.
- Gate failures are blocking by default and must write `agent_gate`, `gate_result`, and trace spans.

## Checkpoint Resume

Every registered operation must define:

- `checkpoint_schema`
- `idempotency_key`
- `checkpoint_interval`
- `resume_from_checkpoint(storage, agent_run, checkpoint)`
- `rollback(storage, agent_run, outputs)`

Checkpoint recovery order:

1. Use explicit latest `agent_checkpoint` for the run.
2. Reuse existing output assets if idempotency key and output schema match.
3. Resume operation-specific state.
4. If resume is unsupported, schedule a clean rerun with the original failed run recorded in lineage.

## API Surface

Add Agent Scheduler endpoints:

```text
GET  /product/agents/scheduler/status
GET  /product/agents/scheduler/queue
POST /product/agents/scheduler/tick
POST /product/agents/scheduler/loop
POST /product/agents/dispatch
POST /product/agents/recover
GET  /product/agents/operation-contracts
```

Workflow endpoints stay as they are. The Workflow Scheduler may continue to schedule non-Agent ready nodes, but Agent candidates should be delegated to Agent Scheduler once this module exists.

## UI Surface

Production Control should gain an Agent Scheduler console:

- lease owner, expiry, last tick, mode;
- dispatch queue table with status, attempt count, lease, workflow binding, AgentRun path, checkpoint, last error;
- Agent operation contract table;
- per-run evidence tabs: events, gates, budget, SLA, model calls, cost ledger, trace spans;
- actions: tick, enqueue loop, recover, cancel, retry, open waiting-human handoff.

## Implementation Order

1. Add `agent_dispatch_queue` schema mapping and validation.
2. Add `src/novel_forge/modules/agent_scheduler/service.py`.
3. Add `AgentRunStateMachine.apply_transition()` and route all Agent status writes through it.
4. Add `AgentOperationRegistry` with one deterministic test operation and one real service operation.
5. Integrate Workflow agent dispatch so `_dispatch_agent_node()` creates or references an `agent_dispatch_queue` item.
6. Add scheduler tick/loop with lease, claim, ack, retry, dead-letter, and recovery.
7. Add Workflow Resume Adapter for succeeded Agent runs.
8. Add API routes and Web Admin Agent Scheduler panel.
9. Expand tests to cover duplicate tick protection, budget/SLA kill, gate failure, checkpoint recovery, dead-letter recovery, and workflow resume.

## Acceptance Tests

Minimum P0 acceptance:

- Workflow agent node execution creates `agent_contract`, `agent_run(prepared)`, `node_run(prepared)`, and `agent_dispatch_queue(queued)`.
- Agent scheduler tick claims exactly one queue item and does not duplicate work under a second tick with an active lease.
- A successful registered operation writes output assets, checkpoint, budget, SLA, model/cost logs, gates, trace spans, and marks AgentRun `succeeded`.
- The succeeded AgentRun automatically resumes the blocked workflow node and supersedes the previous workflow run.
- A budget failure writes `agent_budget(exceeded)`, `agent_gate(failed)`, `agent_failure_report`, queue retry/dead-letter evidence, and keeps the workflow blocked.
- An SLA or provider token cutoff cancels/fails the AgentRun and does not attach unvalidated outputs to the workflow.
- A checkpointed failed run can be recovered without rerunning completed steps when the operation declares resume support.
- Web Admin can display queue status, lease, AgentRun, workflow binding, budget/SLA/gate/checkpoint evidence, and trigger tick/recover actions.
