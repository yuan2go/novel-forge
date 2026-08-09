# WP-LF-01 Unified Real Long-form Runtime Closure Design

## Status

Approved by the operator on 2026-08-08. The approval selects the minimal
vertical-convergence approach described here and authorizes implementation
without another design gate.

## Goal

Prove one real three-chapter short-longform run on the existing Production
Execution Plane:

```text
Story Planning -> Book Production -> Chapter Production -> Reader Outcome
-> Longform Recap -> PlanChange/Replan -> Resume
```

The target claim is `SHORT_LONGFORM_RUNTIME_PROVEN=true`. This work must not
promote longform, production, multi-book, quality calibration, or Reader Judge
qualification claims.

## Architecture

The implementation reuses the existing Command Kernel Attempt/Lease/Fence and
ExternalEffect runtime, Capability Pack Authority, Agent WorkOrder/runtime
binding, `ProductionExecutionGateway`, and `CodexCliExecutionBackend`.
Planning and Reader Outcome retain separate domain binders. A small
backend-neutral ExternalEffect bridge may share only execution mechanics such
as dispatch, recovery, receipts, usage, and cost; it may not own Planning,
Chapter, or Reader semantics. No second Gateway, provider runtime, Attempt
runtime, Planning runtime, or longform orchestrator is introduced.

Planning is composed through the existing `PlanningExecutionPreparer` seam.
Each of the five planning generators freezes a governed Capability Snapshot,
Agent WorkOrder/runtime binding, materialized prompt/skill/context policy, and
an Attempt-bound PEP request before Codex invocation. Structured output is
validated by both the PEP contract and Story Planning structural/semantic
validators before candidate approval and Authority activation.

Reader Outcome receives an independent Book Followup Capability Pack and
domain binding. An accepted chapter schedules the existing Reader Outcome
Authority operation; the operation invokes real Codex through the same
execution plane and materializes `ReaderOutcomeReport`,
`ReaderStateTransition`, and `ReaderIssueSet`. Reader Judge remains `SHADOW`,
non-publish-blocking, and unable to commit Authority state or activate plan
changes.

## Book Mutation Boundary

External/model work uses the existing Attempt, Lease, Fence, ExternalEffect,
receipt, and recovery contracts. Deterministic Book mutations use the existing
transaction-command mechanism with stable idempotency, one database
transaction, explicit CAS/concurrency checks, Authority audit, and event/outbox
records. Existing SQL already satisfying that contract remains in place. Only
uncovered start, chapter request/reserve/link, acceptance, pause/resume/abort,
and checkpoint mutations are changed. Book does not receive its own Attempt
runtime.

## Retry And Proof

A proof-only fault injector marks the result of the first real Codex process as
retryable after measured usage/cost evidence is available but before a Planning
candidate can be accepted. The scheduler creates a different Attempt for the
same Operation. Capability resolution must reuse the prior frozen Snapshot and
equivalent materialization even if a different deployment becomes active.
Only the successful candidate may commit.

The E2E proof uses PostgreSQL and MinIO provider-validation infrastructure and
binds every claim to exact HEAD, project/workspace/book identity, trace,
Capability Snapshot, ExternalEffect, process receipt, usage/cost evidence, and
Authority output. Replan uses a deterministic `CONTROLLED_PROOF` deviation
through the formal Recap/Replan input path so control-flow proof is independent
of Reader model randomness. It must preserve executed chapters and plans,
supersede only future plans, bind a new production input snapshot, resume, and
remain idempotent on replay.

## Public Test Seams

- `StoryPlanningGenerationApplication` production composition and five
  generator operations.
- `PostgresBookProductionSupervisor` and `PostgresBookAuthority` public
  commands/status.
- `BookFollowupAuthorityApplication` Reader Outcome and Longform Recap
  operations.
- Production Execution request/receipt/evidence queries.
- The WP-LF-01 real-provider proof command and its schema-backed report.

## Acceptance

Unit, architecture, PostgreSQL integration, formatting/lint, and the real Codex
proof must pass at the final committed HEAD. Fixture evidence may verify
contracts but cannot set a real-provider or runtime-proven flag. Controlled
deviation proves only Replan control flow and Authority semantics.
