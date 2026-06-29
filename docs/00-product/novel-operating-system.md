# Novel Operating System Target

## Current Position

Novel Forge v6 is a local-first AI novel production platform with an early Novel Operating System runtime.

The repository, package, CLI, and public product name remain `novel-forge`. Novel Operating System is the architecture target: a system that can plan, execute, observe, gate, recover, and improve long-form fiction production through durable artifacts instead of informal prompt chains.

Current maturity estimate:

| Capability | Current maturity | Status |
|---|---:|---|
| Local novel production platform | 88%-90% | Core production workflow is usable |
| Workflow Engine | 86%-88% | DAG executor, state machine, gates, ready queue, scheduler, resume, invalidation, rollback markers, runtime console DAG view, and acceptance coverage exist |
| Agent Registry / Scheduler | 82%-84% | Contracts, runs, dispatch queue, leases, durable checkpoints, gates, budgets, retries, dead letters, service operation registry, and Agent timeline first slice exist |
| Trace / Metrics | 82%-84% | Trace spans, gate results, guarded model call logs, cost ledgers, snapshots, timeline payloads, and cost-quality assets exist |
| Novel Knowledge Graph | 81%-83% | Ontology, snapshots, query/path/impact/conflict APIs, KG gate, semantic extraction report, evidence/confidence, dirty tracking, and workbench action exist |
| Cost Dashboard | 80%-82% | Ledger, snapshots, dashboard assets, runtime policy coverage, cost trend, rollback verification, and OS console route exist; provider-native streaming cost precision remains provider-specific |
| Review Rework Loop | 78%-80% | Backend loop, workflow processor, acceptance coverage, and Review Rework Board first slice exist |
| Web OS Console | 81%-83% | Dedicated OS runtime routes, policy coverage, DAG graph, Agent timeline, KG relation table, cost trend, rollback coordination, and optional/CI-gated Playwright route smoke exist |
| Novel Operating System overall | 83%-86% | Early OS runtime with accepted vertical slice, hardened closure layer, cockpit first slice, and scale tests, not yet complete OS product |

## What Makes It An OS

Novel Forge becomes a Novel Operating System when the system can answer and act on these questions without manual glue:

- What production node is ready next?
- Which Agent or processor is allowed to execute it?
- Which input artifacts, context bundle, and KG facts were used?
- Which gate blocked or accepted the output?
- Which model call happened, how much did it cost, and did it stay under budget?
- Which trace spans explain the run?
- Which downstream assets became stale after an upstream change?
- Which checkpoint can resume a failed run?
- Which review issue created which revision task, patch, draft version, re-review, and publish decision?
- Which reader feedback should flow back into a plan, rule, or future chapter?

## OS Acceptance Chain

The OS end-to-end acceptance chain is not "generate a complete novel".

The P0 chain is a minimal vertical slice that proves the operating layer is coherent. It should use one project fixture and one chapter-sized production target:

```text
project fixture
  -> WorkflowDefinition
  -> execute_workflow
  -> workflow / agent scheduler tick or loop
  -> context bundle
  -> model call through the configured runtime boundary
  -> node_run / agent_run
  -> trace_span / gate_result / model_call_log / cost_ledger
  -> Novel KG gate / continuity preflight
  -> review_issue
  -> revision_task
  -> editor_patch
  -> draft_version
  -> re-review
  -> publish_gate
  -> downstream invalidation
  -> resume_workflow
  -> cost_quality_dashboard / acceptance report
```

Acceptance requires evidence, not only a generated text file:

- a completed or intentionally blocked workflow run;
- node and agent run records;
- checkpoint and recovery evidence when the fixture exercises failure;
- trace timeline with parent/child spans;
- gate results for KG/continuity/review/publish checks;
- model call log and cost ledger rows for model work;
- budget policy check or explicit no-budget fixture reason;
- draft version lineage after patch application;
- re-review output and publish gate result;
- invalidation record when upstream input changes;
- cost-quality dashboard or acceptance report.

Full-novel generation is a long-chain acceptance scenario after P0. It should test scale, quality drift, continuity over many chapters, cost control over long runs, and editorial throughput. It is deliberately not the first OS acceptance target because it is slow, expensive, and can fail for creative-quality reasons even when the runtime is correct.

## Current First-Slice Runtime

Implemented first slices include:

- Workflow runtime: `WorkflowDefinition`, DAG parser, dependency resolver, ready-node queue, `WorkflowRunStateMachine`, processor registry, pre/post gate pipeline, retry/pause/resume/cancel controls, scheduler tick/loop, invalidation, quarantine/rollback markers.
- Agent runtime: runtime profiles, permission guards, `agent_contract`, `agent_run`, `agent_dispatch_queue`, checkpoints, budgets, gates, metrics, operation registry, scheduler tick/loop, retry, dead-letter, recovery.
- Novel KG: typed ontology collections for entities, relations, events, rules, timelines, foreshadowing, factions, locations, props, power scales, review rules, and templates; snapshot/query/path/impact/conflict APIs; KG gate and continuity preflight integration.
- Trace and cost: `trace_span`, `gate_result`, `model_call_log`, `cost_ledger`, `budget_policy`, `cost_alert`, project/agent/chapter snapshots, and cost-quality dashboard assets.
- Runtime policy: strict/compat operation registry, `RuntimePolicyEnvelope`, KG-backed context requirement, model-call/cost/gate/budget evidence checks, enforcement report API, and static legacy-entrypoint bypass audit.
- Provider control: normalized usage, runtime controller events, OpenAI-compatible SSE streaming usage, streaming delta cutoff, timeout/cancel checks, and polling-based live cancel for local Codex/Claude Code workers.
- Checkpoint and rollback: operation checkpoint schema, durable stage checkpoint assets, raw provider output segment persistence, checkpoint chain/resume plan, rollback transactions/plans/results, version-restore actions, ledger compensation, dirty-index markers, two-phase coordinated rollback, and preview/apply/verify/coordinate APIs.
- Review rework: review issue to revision task, editor patch, draft version, re-review, and publish gate backend loop.
- Pgvector retrieval: PostgreSQL + pgvector is the default internal knowledge/memory retrieval base with migration dry-run/apply, operations/pressure planning, online sync/query, local fallback, and Qdrant as the optional high-performance vector service.
- Web cockpit: Workflow DAG graph, Agent timeline, KG relation table, cost trend, rollback coordinate panel, route-level architecture tests, and CI-gated strict Playwright fixture smoke.
- Local model boundary: Agent model calls default to the Claude Code Codex worker through `CODEX_HOME=~/.codex-claude codex`; tests use deterministic mock providers.

## Remaining Hardening Work

The OS skeleton, chapter-sized acceptance chain, and major closure layer now have hardened first-slice implementation. The remaining work is provider-specific and scale hardening:

1. Provider-native streaming adapters: keep extending streaming/cancel from OpenAI-compatible and local process workers to each future provider SDK.
2. Deeper task-internal checkpointing: standard model tasks now have prompt/provider/raw-output/validation/commit checkpoints; continue enforcing this contract for any future custom long task that bypasses GuardedModelAdapter or ModelGateway.
3. Full business transaction rollback: coordinated rollback exists; remaining depth is richer cross-node diff preview, rollback rehearsal, and large-workspace operator confirmation workflows.
4. Provider-backed KG extraction: run model-assisted entity/relation/event extraction behind runtime policy, then merge with deterministic semantic reports and identity merge queues.
5. Operator cockpit depth: first interactive views exist; add graph zoom/search/minimap, detailed drawers, and broader real-backend Playwright fixture coverage.
6. Long-chain pressure acceptance: run opt-in 12/50+ chapter profiles to prove continuity, cost drift, quality drift, recovery, rollback, and feedback backflow over scale.

Detailed implementation plan: [Novel OS Remaining Closure Plan](../08-roadmap/novel-os-remaining-closure-plan.md).

## P1 Semantic Layer

After the runtime acceptance chain is stable, deepen creative quality:

- stronger model-assisted entity and relation extraction;
- alias merge with confidence and evidence spans;
- motivation drift and character-state conflict detection;
- foreshadowing lifecycle and payoff quality scoring;
- power-scale and rule contradiction analysis;
- chapter hook, payoff, toxicity, and platform-fit semantic scoring;
- reader feedback clustering that creates traceable plan or review-rule updates.
