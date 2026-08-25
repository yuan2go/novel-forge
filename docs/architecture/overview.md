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
- planning supports multiple Arc plan versions at a chapter cursor and cross-Arc planning semantics; accepted `chapter-outcome-v3` evidence now materializes the explicit Arc Actual/Progress/Outcome/Checkpoint contract at Book Acceptance.
- Book Planning derives a bounded Arc Working Set from the immediately preceding complete accepted projection. ChapterGroup `arc_cadence` is a preference: lifecycle, dependency legality, checkpoint correction, obligation debt, dormancy, Narrative Load and reader intent may deterministically correct it before Chapter planning and production admission.
- ChapterPlan, ChapterExecutionIntent v2 and ChapterMemo v2 jointly carry Chapter Mission and multi-Arc composition semantics; Context consumes the locked Mission instead of rebuilding expectations directly from the Plan.
- Planning Context performs governed, structured MKAOS Narrative Intelligence selection for Book/Volume/Arc/ChapterGroup/Chapter stages. Selected cards remain possibilities, are source-isolated, repetition-aware, and retain Context/Candidate/Plan usage lineage.
- Legacy remains migration-only.

## Current Narrative Evolution runtime

At this baseline `book-design.v4` still contains a monolithic Creative/World/
Character design and projects component assets after BookDesign activation.
This has lifecycle evidence but does not establish the required upstream
Creative → World → Character → BookDesign Authority chain. New production must
converge on separately qualified Foundation contracts and a reference-only
BookDesign v5; v4 remains replay/migration compatibility.

`BookProductionComposition.open_book` exists and has bounded PostgreSQL fixture
coverage, but no durable command/admission API invokes it. It is therefore code
and test reachable, not a complete operator-reachable Book opening flow. The
closure must admit a durable Operation and let a worker coordinate existing
Authorities rather than running provider work in an HTTP lifecycle.

Story Planning persists each search at one exact parent/accepted boundary, its
immutable branch candidates, structured future projections, independent
qualification hashes, deterministic comparison and rejected lineage. Only the
selected candidate can pass the normal approval/activation gate. The Book
Supervisor uses this path for consequential ChapterGroup planning; governed
Replan uses it for Book/Volume/Arc/ChapterGroup replacement. Operational Chapter
planning remains just-in-time and single-candidate.

The current search and replay fixture does not establish a closed Foundation
hierarchy or literary quality. Real-provider search behavior, human preference
and long-form stability remain explicitly unqualified until a later bounded
campaign.

## Current converged production shape

The converged target moves chapter production from broad context-driven generation toward:

```text
Progressive Plan + Arc Working Set
→ Qualified / Approved / Frozen Narrative Realization
→ active ChapterPlan
→ ChapterExecutionIntent / ChapterMemo
→ Retrieval Query Plan / immutable RetrievalResult at the frozen Accepted Boundary
→ governed Context Manifest v3
→ PROTECTED / RETRIEVABLE / COMPRESSIBLE / EPHEMERAL Context
→ Draft / Review / Revision / Best Candidate
→ provisional Canon/Arc/Obligation evidence
→ verification / quality
→ atomic Accepted Outcome projection set
```

The baseline Book Supervisor currently skips the Narrative Realization step and
creates ChapterPlan directly from ChapterGroup. Closing that gap extends
existing Planning/Narrative State/Context/Chapter Authority; it does not create
a second narrative runtime or another `PlanContractType` scale.

The current implementation realizes the working-set, composition/Mission and
structured Narrative Intelligence links in this chain. The 2026-08-24
exact-SHA qualification exercised a three-Chapter PostgreSQL fixture from
initial accepted state through corrected Working Sets, Chapter
Intent/Memo/Context, accepted Arc/Obligation projection and the next scheduling
decision. It also proved frozen Planning Context retry, MKAOS revocation
fail-closed behavior and persisted usage lineage. This is bounded fixture
evidence, not real-provider, long-form campaign or production qualification.

Current Context compilation enforces all four classes. Protected overflow
fails before Provider execution; compressed evidence retains source and
compression provenance; provider-visible ephemeral input is Attempt evidence
but never long-lived Memory/Search. Retrieval candidate discovery is
lexical-first (`ts_rank`, not BM25) plus exact structured channels; compatible
semantic similarity may only rerank that frozen bounded set and deterministically
falls back when unavailable.

Committed Chapter acceptance rebuilds two writer-facing projections in the
existing retrieval store: Recent Trail from typed accepted outcomes and Hook
Debt from accepted Narrative Obligations. The Chapter Transaction Workspace API
joins these projections with existing Plan/Intent/Memo/Context/Candidate/Review/
Quality/Acceptance and stale PlanBinding evidence. These are read models with no
activation permission, not new narrative Authorities.

The target hierarchy is four-dimensional: optional organization/IP scopes, narrative containment, cross-cutting Arc Graph and ChapterGroup production coordination. The current runtime has no independent Narrative Segment consumer, shared-Universe Canon Authority or reason to add empty persistence roots.

## Current liveness implementation and evidence boundary

WP-LIVE-01 removes the code-proven structural coupling identified at the 2026-08-20 baseline:

- accepted-chapter Reader/Long-form work is admitted and executed by the isolated Book Followup worker;
- Book acceptance commits AcceptedOutcome, Story State, Canon and accepted cursor before next-chapter eligibility, without synchronous sidecar execution;
- Book worker claim states now derive from the Domain `ACTIONABLE` classification, while durable waits and terminals carry explicit semantics;
- ChapterGroup production closure depends on committed accepted narrative truth, not Recap completion;
- the PostgreSQL progress projection reports narrative progress and sidecar backlog separately.

The historical structure is consistent with the observed failure mode “Chapter 1 completes, Chapter 2 does not advance for hours.” The exact incident database was not available at implementation time, so this remains a code-confirmed failure chain rather than a claim that every historical incident fact was reconstructed.

The two architecture assertions found stale at the audit baseline now test the
actual contracts: claimability derives from Domain state semantics and
follow-up completion remains in the isolated sidecar Authority. Obsolete
worker-local `ACTIVE_STATES` and Book-owned `book.followup.completed` ownership
were not restored.

The audit's P0 Plan-to-Actual Arc defect is closed in the current code.
ChapterPlan declarations cannot create actual progress; accepted Arc evidence
materializes progress, while missing evidence remains `NOT_OBSERVED`,
`NOT_MATERIALIZED`, or `UNKNOWN` according to the explicit contract.

Bounded fixture Chapter 1→2 and PostgreSQL replay are smoke-tested. Runtime
hardening closes canonical Arc follow-up terminal handling, embedding
unknown-effect reconciliation, frozen Agent execution identity/aggregate
budgeting, and independent PostgreSQL vector candidate discovery. An exact-SHA
small qualification ran one real Agent Session, document/query embeddings with
receipt-backed crash recovery, and one Memo→Retrieval→Context→Draft slice.
Those bounded paths are `PROVIDER_PROVEN`; sustained real Provider operation and
unattended long-form campaigns remain unqualified. `LONGFORM_PROVEN` and
`PRODUCTION_QUALIFIED` are false.

WP-LIVE-02 owns engineering, PostgreSQL, migration, failure, real-Provider and
campaign qualification for this closure. Its proof runners observe Book and
Followup workers as separate deployment executors, bind every receipt to the
exact release SHA, and reject fixture or intermediate state as runtime proof.
Qualification results remain external evidence attached to the candidate PR;
this current-runtime document does not promote an evidence level by itself.

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
- multi-turn Agent Harness transcript contracts, explicit frozen-catalog Skill
  activation, and recovery wiring;
- Memo-driven governed Context four-class selection, immutable retrieval
  results, lexical/structured-first candidate discovery, bounded semantic
  reranking and layered-memory contracts;
- ChapterExecutionIntent/ChapterMemo and Best Candidate selection;
- accepted Arc/Obligation projection sets and semantic invalidation;
- quality/reader surfaces;
- qualification infrastructure.

Current documentation does **not** establish by itself:

- sustained real-provider Book production;
- long-running real-provider Chapter-to-Chapter liveness;
- 30/100/300-chapter correctness/quality;
- independent PostgreSQL vector candidate retrieval at production scale;
- sustained or production-qualified real-provider Agent Harness operation (the
  exact-SHA bounded qualification proves one real Agent Session only);
- real-reader learning closure;
- multi-book production;
- Production Admission.

Use the evidence vocabulary in [`../README.md`](../README.md). Exact status must be re-established at the SHA under qualification.
