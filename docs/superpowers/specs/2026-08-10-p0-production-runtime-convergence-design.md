# P0 Production Runtime Convergence Design

**Status:** approved for implementation on 2026-08-10  
**Baseline:** `79f06c19033d12374ec4fda6f066a46f59bf51a1`  
**Scope:** converge existing runtime paths; do not add Novel OS capabilities.

## Decision

Novel Forge will expose one PostgreSQL-backed Book production composition to both
the Authority API and the Book Worker. The composition owns the existing Book,
Planning, ChapterGroup, Chapter, preparation, follow-up, PlanChange, Replan, and
Supervisor services. API and Worker entrypoints may differ in transport and
polling, but they must invoke the same Book production tick and observe the same
domain state transitions.

PostgreSQL remains the only production state authority. The composition object is
not a new workflow framework or state holder; it only assembles existing domain
authorities and exposes the canonical tick/approval operations.

## Canonical Book Runtime

```text
Authority API admission / Book Worker polling
  -> BookProductionComposition (startup-validated dependencies)
  -> PostgresBookProductionSupervisor.tick
  -> StoryPlanningGenerationApplication
  -> PostgresChapterGroupAuthority
  -> ProductionPreparationService
  -> PostgresBookAuthority.submit_chapter
  -> canonical Chapter Worker / Chapter Command Kernel runtime
  -> PostgresBookAuthority reconcile + accept
  -> BookFollowupAuthority (Reader Outcome / Longform Recap)
  -> checkpoint decision
  -> BookReplanCoordinator.start when required
  -> APPROVAL_PENDING
  -> explicit Authority approval command/API
  -> BookReplanCoordinator.activate
  -> PlanChange activation + new input snapshot + Book READY
  -> the same Supervisor tick continues the next chapter
```

The Worker never approves a PlanChange. `APPROVAL_PENDING` is a normal durable
waiting state. Repeated ticks and process restarts must find the existing Replan
record by stable idempotency key and must not create another candidate or proposal.
After formal approval, a later canonical tick performs activation and resume
idempotently; API and Worker do not carry transient activation state.

## Capability Pack Contract

Capability Packs freeze an execution identity for every governed workflow node.
The final Chapter `quality` node is a deterministic in-process Authority fan-in
over five independently produced quality reports. It has no Provider call and its
OperationDefinition has no required external effect.

Therefore:

- the final `quality` Pack node binds `quality.aggregate`, whose only allowed
  runtime is the in-process Chapter Authority;
- its timeout remains the deterministic aggregate operation timeout;
- compiler and validator distinguish this aggregate from Provider-backed judges;
- the five provider-backed quality group nodes retain their actual capabilities.

This removes the false `quality.intrinsic.judge` binding without weakening timeout
validation or claiming that the aggregate creates an ExternalEffect.

## Test Gate

Pytest becomes the canonical Python runner because it executes existing unittest
classes and top-level pytest functions. Make and CI entrypoints will run pytest
for unit, architecture, acceptance, and PostgreSQL/integration suites. Required
module gates must prove that pytest collected at least one test; file existence is
not evidence of execution.

The implementation starts by adding failing contract tests for:

1. deterministic Pack nodes and the final quality fan-in;
2. a shared API/Worker Book composition;
3. READY resolved-input Worker progression;
4. Replan idempotency, approval waiting, activation, resume, and restart;
5. no-Replan and Replan two-chapter production proofs.

## Readiness Semantics

Readiness is split into evidence-backed dimensions:

- `api_ready`: API composition and required dependencies build successfully;
- `runtime_ready`: required workers are fresh, PostgreSQL/migrations and MinIO are
  reachable, required Packs compile/activate, and configured Provider routes build;
- `fixture_only`: the active route is fixture/mock-backed;
- `real_provider_qualified`: qualification evidence exists for the configured route;
- `real_provider_proven`: current-SHA runtime evidence contains a real call;
- `longform_proven`: current-SHA formal Book proof reaches the declared horizon;
- `production_verified`: all required production checks and evidence are satisfied.

Configuration presence alone cannot set any proof flag. P0 may finish with real
provider and large long-form proof flags false; the evidence ceiling must say so.

## Failure and Recovery Rules

- Composition fails closed at startup when a required Book dependency cannot be
  built; the API route has no runtime `getattr` fallback.
- All Book business transitions remain inside existing PostgreSQL Authorities and
  Command Kernel commands.
- Worker RuntimeJob state is an operational lease/checkpoint envelope only; it does
  not duplicate Chapter Attempt, Lease, Fence, or ExternalEffect state.
- API manual tick and Worker automatic tick return the same domain action/status
  for the same durable Book state.
- Retry, restart/resume, stale lease/fence, and UNKNOWN ExternalEffect proofs use
  formal compositions rather than a test-only Supervisor assembly.

## Explicit Non-Goals

- no new Manager, Engine, Workflow Framework, Scheduler, Authority, or Agent;
- no policy-based or fixture-only automatic Replan approval;
- no new Provider, quality group, narrative feature, or long-form capability;
- no broad documentation rewrite;
- no evidence-ceiling increase without current-SHA runtime proof.

## Acceptance

The change is accepted only when the current environment's static/lint, pytest
unit, architecture, acceptance, PostgreSQL integration, migration, Worker
integration, and Compose checks are executed. Unavailable external dependencies
are reported as `NOT_VERIFIED`, never replaced by historical results. The final
branch is self-reviewed, committed, pushed, and opened as a Draft PR.
