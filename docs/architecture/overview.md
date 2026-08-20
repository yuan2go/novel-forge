# Architecture overview

Novel Forge's target architecture is defined only by [`canonical-overall-design.md`](canonical-overall-design.md). This file is a current-runtime view and must not promote target design to current proof.

## Current runtime shape

```text
Operator / API / workers
        ↓
Domain Authority applications
        ↓
Command Kernel / RuntimeJob
        ↓
specialized workers
        ↓
ProductionExecutionComposition
  ├ governed model/provider gateway
  └ object/artifact effects
        ↓
PostgreSQL Authority + object storage + configured provider
```

Stable current boundaries:

- PostgreSQL is the production business Authority; memory implementations are fixtures.
- Domain mutations go through owning applications/command semantics rather than Agent direct writes.
- ProductionExecutionComposition is shared execution infrastructure, not Chapter-owned infrastructure.
- Chapter/Book, Planning, Agent, Source/MKAOS, Quality/Reader and Provider systems are peer users of the shared execution plane.
- accepted Chapter/Book lineage is the boundary from candidate output to story truth.
- Narrative State is projected from accepted evidence; Context/retrieval are derived.
- current planning already supports multiple Arc plan versions at a chapter cursor and cross-Arc planning semantics; this is not yet the complete target Narrative Arc OS described in the Canonical Design.
- Legacy remains migration-only.

## Target semantic shift

The converged target moves chapter production from broad context-driven generation toward:

```text
Progressive Plan + Arc Working Set
→ active ChapterPlan
→ ChapterExecutionIntent / ChapterMemo
→ Context v2 at the complete Accepted Boundary
→ Protected Context + hybrid retrieval
→ Draft / Review / Revision / Best Candidate
→ provisional Canon/Arc/Obligation evidence
→ verification / quality
→ atomic Accepted Outcome projection set
```

This should extend existing Planning/Narrative State/Context/Chapter Authority rather than create a second narrative runtime.

The target hierarchy is four-dimensional: optional organization/IP scopes, narrative containment, cross-cutting Arc Graph and ChapterGroup production coordination. The current runtime has no independent Narrative Segment consumer, shared-Universe Canon Authority or reason to add empty persistence roots.

## Current liveness implementation and evidence boundary

WP-LIVE-01 removes the code-proven structural coupling identified at the 2026-08-20 baseline:

- accepted-chapter Reader/Long-form work is admitted and executed by the isolated Book Followup worker;
- Book acceptance commits AcceptedOutcome, Story State, Canon and accepted cursor before next-chapter eligibility, without synchronous sidecar execution;
- Book worker claim states now derive from the Domain `ACTIONABLE` classification, while durable waits and terminals carry explicit semantics;
- ChapterGroup production closure depends on committed accepted narrative truth, not Recap completion;
- the PostgreSQL progress projection reports narrative progress and sidecar backlog separately.

The historical structure is consistent with the observed failure mode “Chapter 1 completes, Chapter 2 does not advance for hours.” The exact incident database was not available at implementation time, so this remains a code-confirmed failure chain rather than a claim that every historical incident fact was reconstructed.

The 2026-08-20 Industrial Novel OS audit baseline executed the relevant bounded unit suites (`139 passed`) and four architecture files (`19 passed, 2 failed`). The two failures assert ownership removed by the liveness convergence: worker-local `ACTIVE_STATES` and Book-owned `book.followup.completed`. Current behavior instead derives claimability from Domain state semantics and keeps follow-up completion in the isolated sidecar Authority. The tests must be converted to behavioral/contract assertions during convergence; they must not restore obsolete ownership.

The audit also found a P0 correctness defect: Arc checkpointing treats ChapterPlan declarations as `ACTUAL` when ChapterOutcome carries no actual contribution field. Until explicit accepted Arc evidence and fail-closed observation status replace that fallback, authoritative Arc progress is not proven.

Bounded Chapter 1→2 integration, sidecar failure isolation, restart/fencing/replay, real Provider, and unattended campaigns remain unqualified. `LONGFORM_PROVEN` and `PRODUCTION_QUALIFIED` are false.

## Evidence boundary

The repository contains substantial implementation/runtime/test evidence for:

- Command Kernel, Operation/Attempt/Lease/Fence, ExternalEffect, RuntimeJob;
- PostgreSQL Authorities and migrations;
- Chapter/Book production and acceptance;
- progressive planning and semantic evaluation;
- Narrative State / temporal replay / accepted lineage;
- PlanChange/Replan;
- Source/MKAOS;
- Agent Collaboration/Runtime;
- quality/reader surfaces;
- qualification infrastructure.

Current documentation does **not** establish by itself:

- sustained real-provider Book production;
- Chapter-to-Chapter bounded liveness;
- 30/100/300-chapter correctness/quality;
- ChapterExecutionIntent/ChapterMemo, Context v2 hybrid retrieval, Best Candidate and full Narrative Arc OS semantics;
- complete atomic accepted Arc/Obligation projection set;
- multi-turn dynamic Tool-calling Agent Harness;
- real-reader learning closure;
- multi-book production;
- Production Admission.

Use the evidence vocabulary in [`../README.md`](../README.md). Exact status must be re-established at the SHA under qualification.
