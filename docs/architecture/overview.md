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

New production now requires six exact qualified Foundation bindings (Creative,
Theme, Ending, Reader Promise, WorldBible and CharacterCast) and an active
reference-only BookDesign v5. Durable Story Formation binds exact parent
AssetVersions/hashes and generation input snapshots; mixed set generation or
an unfinished Formation fails closed. `book-design.v4` remains replay/migration
compatibility and is not a new-production Foundation root.

Book opening is an operator-reachable durable command surface. HTTP admits an
Operation and `BOOK_OPENING_EXECUTE` RuntimeJob, while the Book worker performs
the searched Book/Volume/Arc baseline and input-snapshot resolution. Query,
resume and abort operate on the persisted opening run. A worker crash after the
business commit reconciles the stored COMPLETE result on the same job retry;
the request lifecycle never owns Provider execution.

Story Planning persists each search at one exact parent/accepted boundary, its
immutable branch candidates, structured future projections, independent
qualification hashes, deterministic comparison and rejected lineage. Only the
selected candidate can pass the normal approval/activation gate. The Book
Supervisor uses this path for consequential ChapterGroup planning; governed
Replan uses it for Book/Volume/Arc/ChapterGroup replacement. Operational Chapter
planning remains just-in-time and single-candidate. The complete persisted
Search request—planning horizon, desired transformation and hard constraints—is
also frozen in each admitted generation command, Context Bundle and Provider
request and is rechecked on retry/recovery. A ChapterGroup Provider schema uses
the exact frozen range; structural validation requires the candidate range,
ordered Chapter Function Matrix and realization-event coverage to match it.
The range is also bounded by the current VolumePlan. Input resolution may retain
multiple non-overlapping historical/current ChapterGroupPlans, but binds only
the unique group covering the current Narrative cursor; overlap or a group that
crosses its parent Volume fails closed.

For operational ChapterPlan generation, the frozen Narrative Realization is
projected into the Provider's strict-schema dialect as exact object shape,
array cardinality and scalar vocabulary. Planning Authority remains the only
semantic owner and rejects any returned slice that is not byte-semantically
equal to the frozen realization, including sequence order and multiplicity.

The current PostgreSQL fixture establishes the closed Foundation hierarchy and
durable process/replay semantics. It does not establish literary quality,
real-provider search behavior, human preference or long-form stability; those
remain explicitly unqualified until a later bounded campaign.

## Current converged production shape

The converged production path is:

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

The Book Supervisor now qualifies, approves and freezes Narrative Realization
before ChapterPlan generation. Chapter generation and activation resolve the
current slice from Planning Authority and exact-compare caller transport; Book
production admission revalidates its lineage and digest. Realization remains a
causal correctness contract inside Hierarchical Planning, not another
`PlanContractType`, runtime or accepted-actual Authority.

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

## Current Quality Qualification runtime

Migration `20260826_0101_quality_qualification` adds one bounded evidence plane
adjacent to the existing Chapter Quality and Reader Calibration Authorities. It
does not add a second Chapter, Canon, Narrative State, Planning, Reader or
long-term-memory owner. The current composition root exposes:

- immutable exact-SHA campaign manifests and lifecycle;
- Chapter/Arc baseline-versus-Canonical subject bindings;
- source-bound L1 Hard Correctness, L2 Editorial and L3
  Reader/Longitudinal evidence;
- append-only qualification decisions with severe-correctness precedence and
  `NOT_PROVEN` for missing evidence;
- two independently addressed reviewer packs with balanced A/B order, no
  private mapping in reviewer export, A/B/Tie/Cannot Judge, dimension scores,
  confidence, disagreement and adjudication;
- Calibration v2 comparison between attributable Judge, human, adjudicated,
  blind-preference and Reader evidence without registering calibration-v1
  operations;
- accepted-history momentum, promise/payoff and semantic repetition evidence,
  plus causal Arc and non-averaged bounded Volume-slice evaluation.

`chapter-outcome-v3` is the canonical Chapter Quality projection boundary.
Post-acceptance Reader reports from the existing Book Followup Authority are
joined into that accepted sequence and remain `READER_PROXY_ADVISORY` evidence.
They can enter recap/trend/future recommendation but cannot mutate accepted
truth or activate a plan.

The bounded campaign harness permits only ChapterGroups 1–4 and 5–8 and stops
at eight acceptances. Its comparison uses the first draft and the accepted
revision from the same Chapter attempt, Story Foundation, goal, Context,
Provider/model and comparable budget; the controlled difference is the normal
review/revision/re-review/acceptance path. The scripted PostgreSQL campaign is
fixture/recovery evidence only. Real-provider and human conclusions belong
only to the exact-SHA report under `docs/qualification/`; documentation and a
high Judge score cannot establish them.

For production-generated ChapterGroups, the Supervisor deterministically turns
the Book target, current Volume boundary and preferred light-recap cadence into
a legal three-to-eight Chapter window without leaving a one- or two-Chapter
fragment inside that Volume. For the bounded Quality profile this yields exactly
`[1,4]` and `[5,8]`; all search branches receive and must obey the same frozen
window.

Real execution additionally materializes one source-bound Provider Runtime
artifact containing ModelCallLog and cost-ledger AssetVersions, external
effects/dispatches/receipts, failures/retries, measured usage, settled budget
reservations, Pack attempt snapshots and Prompt/Skill/route/context/evaluation
policy hashes. The campaign Project is dedicated to one BookRun; fixture calls,
unclassified routes, missing receipts/measurement, Pack drift, unresolved
budgets or another BookRun fail the final evidence gate. The state descriptor
is captured read-only from Authority and contains no credentials or narrative
truth.

The former 300-Chapter proof contract, score-only Quality helper, tracked
119-Chapter generated corpus and dead Admin proof consoles are retired from the
current tree. Git history preserves them as historical implementation context;
they are not current qualification evidence.

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
- Quality Outcome v3, Calibration v2, Reader Proxy and accepted longitudinal
  evidence surfaces;
- exact-SHA bounded Quality Qualification Authority and campaign
  infrastructure.

Current documentation does **not** establish by itself:

- sustained real-provider Book production;
- long-running real-provider Chapter-to-Chapter liveness;
- sustained long-form correctness/editorial/reader quality beyond the bounded
  campaign;
- statistically calibrated Judge-human agreement;
- independent PostgreSQL vector candidate retrieval at production scale;
- sustained or production-qualified real-provider Agent Harness operation (the
  exact-SHA bounded qualification proves one real Agent Session only);
- real-reader learning closure;
- multi-book production;
- Production Admission.

Use the evidence vocabulary in [`../README.md`](../README.md). Exact status must be re-established at the SHA under qualification.
