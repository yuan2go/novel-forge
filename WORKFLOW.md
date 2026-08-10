# Canonical Production Workflow

This document describes the current PostgreSQL Authority workflow. Legacy local
pipelines and generic workflow/loop runtimes remain compatibility surfaces and
are not the canonical Book production path.

## Book production chain

The Authority API and Book Worker both receive the same
`BookProductionComposition` from
`build_book_production_composition`:

```text
Authority API admission
→ PostgresBookAuthority
→ StoryPlanningGenerationApplication
→ active Planning version and frozen Book input snapshot
→ PostgresChapterGroupAuthority
→ ChapterPlan
→ Chapter Authority
→ Command Kernel Operation / Saga / Attempt
→ Production Execution Gateway / Provider
→ result validation
→ PostgreSQL Authority commit
→ acceptance
→ Narrative Checkpoint / Ending Reachability
→ Reader Outcome
→ Recap when cadence or Authority policy requires it
→ next Chapter or Replan
```

API manual ticks and Worker automatic ticks invoke the same supervisor and
domain applications. Missing production dependencies are startup failures, not
runtime fallbacks.

## Replan approval gate

Replan is a proposal-and-approval flow:

```text
Recap / Checkpoint evidence
→ Replan required
→ replacement Planning candidate
→ PlanChange proposal
→ APPROVAL_PENDING
→ formal Authority approval command/API
→ PlanChange activation
→ new Book input snapshot
→ Book resume
```

`APPROVAL_PENDING` is a normal durable wait state. The Worker does not have the
approval permission and cannot use fixtures, SQL, or risk policy to bypass it.
Candidate/proposal identities are deterministic so restart and repeated ticks do
not create duplicates. Approval, activation, snapshot update, and resume are
idempotent.

## Execution and recovery ownership

| Concern | Owner |
|---|---|
| Business command, idempotency, Saga | Command Kernel and Domain Authority |
| Attempt, Lease, Fence, retry | Command Kernel |
| Provider request, query/cancel, receipt | ExternalEffect plus Production Execution Gateway |
| Result validation and accepted commit | owning Domain Authority |
| Book/maintenance polling envelope | RuntimeJob Authority |
| Runtime process freshness | Worker Health / readiness |

RuntimeJob accepts only `BOOK_COORDINATION_TICK` and the governed maintenance
scans. It cannot carry Chapter generation, Provider effects, or domain commit
semantics. A RuntimeJob handler invokes the owning Authority; it does not become
a second business runtime.

Unknown external outcomes remain unresolved until adapter query/reconciliation
or an explicit operator decision establishes the result. They are not blindly
retried.

## Provider composition

Chapter, Planning, Reader, and Agent execution share the same Provider adapter
registry and Production Execution Gateway within a process. Provider identities
come from the stage environment keys; `mock`, `local`, and `offline` normalize to
the scripted fixture adapter and are rejected in controlled environments.

The current formal adapter routes are:

- `scripted_provider_v2`: development/test fixture only;
- `openai`: requires `OPENAI_API_KEY` during controlled composition;
- `codex-cli`: governed execution backend, not a Registry adapter.

Provider qualification is separate from configuration and runtime environment.
A buildable route is not evidence that a real Provider call succeeded.

## Context and Knowledge contract

Production Preparation freezes typed inputs for each stage. Raw source
expression is forbidden for generation stages. The project `knowledge_pack` is
`CAPABILITY_OPTIONAL` by default: a Pack may require it for selected stages or
capabilities, but every generation stage is not forced to load irrelevant
knowledge.

If a Capability Pack marks `knowledge_pack` required, Preparation fails closed
when it is absent. It must not fabricate an empty pack. When present, the pack is
traceable through its Authority asset/version and frozen input snapshot.

## Evidence boundaries

Every durable production result is traceable to command identity, frozen input,
provider/pack binding where applicable, Attempt/Fence, validation, Authority
commit, and recovery evidence. Evidence labels remain independent:

```text
fixture_only
real_provider_qualified
real_provider_proven
longform_proven
production_verified
```

No lower level may imply a higher one.
