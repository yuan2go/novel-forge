# Long-form Narrative Proof Campaign Design

## Purpose

Run one cumulative 300-chapter book through the current PostgreSQL Production
Runtime and preserve enough immutable evidence to distinguish engineering,
real-provider, 30/100/300-chapter, A/B, reader-calibration, and production
claims. The Campaign must fail closed when a required observation is missing.

## Baseline

- Repository baseline: `origin/main@3d89e805175ccb4a40c208ce434ed3fe946b38d0`.
- Migration head: `20260812_0086_corrective_generation_terminal_lineage`.
- Qualified runtime: PostgreSQL Authority, MinIO, Command Kernel,
  Operation/Attempt/Lease/Fence, ExternalEffect, Production Execution Gateway,
  Chapter/Book Authority, Story Planning, Narrative State, Context, Canon,
  Quality, Corrective Action, Replan, MKAOS, Trace, Measurement, and Cost.
- Real Provider candidate: authenticated Codex CLI through the existing
  Production Execution Gateway. The OpenAI Responses D0 route is independently
  blocked because `OPENAI_API_KEY` is absent.

## Selected approach

Extend the existing exact-HEAD short-longform proof tooling into a resumable
Campaign harness. The harness is an operator and evidence-export surface only:
it may admit commands, tick existing schedulers, query Authority projections,
and export immutable results, but it owns no business state and creates no
second workflow, retry plane, Provider, database, or Proof Authority.

Rejected alternatives:

1. Reuse `generated/longchain-webnovel`: rejected because its 119 chapters were
   produced by a retired LocalStorage/legacy adapter path.
2. Generate prose directly from Codex: rejected because it bypasses Chapter
   Authority, Context Manifest, Provider lineage, Quality, and acceptance.
3. Add a new longform workflow engine: rejected because Book/Chapter Authority
   already owns the lifecycle.

## Proof book

The book is the original near-future civic mystery **The Ledger Under Rain**.
Ten 30-chapter volumes follow archive clerk Lin Qiao through a flood-threatened
city whose official records preserve revision traces and whose public
corrections impose named civic debt. The design carries typed character,
knowledge, belief, relationship, location, faction, resource, power, conflict,
mystery, foreshadowing, obligation, promise/payoff, and cause/effect state.

The frozen contract contains ten volume arcs, a deterministic 300-row chapter
function matrix, a knowledge matrix, an obligation ledger, state checkpoints,
context MUST_INCLUDE/MUST_EXCLUDE rules, long-distance probes, and thresholds.
Contract files are canonical JSON; every file and the aggregate manifest have
SHA-256 identities. Ground Truth and thresholds are immutable within Campaign
version `longform-narrative-v1`.

## Runtime flow

```text
Frozen Contract
  -> Project and Book Design Authority
  -> Story Planning candidate, approval, activation
  -> Book Production Supervisor
  -> Chapter Authority 18-node Saga
  -> Context + real Provider effects + Quality/Correction + Canon/StoryState
  -> Book acceptance + Reader Outcome + cadence Recap/Replan
  -> checkpoint evaluation at 30, 100, and 300
  -> paired MKAOS/Quality/Replan experiments from frozen checkpoints
  -> final regression and evidence freeze
```

The Campaign keeps one project, one book, one sequential Book run, and one
accepted chapter cursor. A rerun resumes durable Authority state; it never
deletes or edits failed lineage and never regenerates an accepted chapter.

## Evidence and validation

Raw Authority data remains in PostgreSQL/MinIO under the Campaign project and
bucket namespace. Machine-readable snapshots and reports are exported under
`proof-campaigns/longform-narrative-v1/evidence/`; prose is exported separately
under `proof-campaigns/longform-narrative-v1/novel/`.

Each checkpoint verifies sequential acceptance, unique logical chapters,
eligible immutable outputs, Canon/StoryState temporal bounds, Context Manifest
selection and consumption, knowledge exclusions, obligation transitions,
planning drift, Quality/correction outcomes, retry/recovery lineage, Provider
receipts, measured tokens, and cost semantics. Missing evidence is
`NOT_OBSERVED` or `NOT_AVAILABLE`, never zero.

## Failure policy

Failures are append-only and classified as `RUNTIME_DEFECT`,
`NARRATIVE_MODEL_DEFECT`, `CONTEXT_DEFECT`, `PROOF_HARNESS_DEFECT`,
`PROVIDER_FAILURE`, `CONTENT_CORRECTNESS_FAILURE`,
`CONTENT_QUALITY_FAILURE`, `ENVIRONMENT_BLOCKER`, or `EXPECTED_BEHAVIOR`.
Code fixes require a new commit, complete Engineering Qualification, and rerun
of the affected proof. Provider or reader-data blockers do not authorize mock
substitution.

## A/B and reader calibration

MKAOS, Quality, and Replan experiments use immutable pre-intervention inputs and
paired future segments. Only the named treatment changes; Provider/model,
sampling, plan, state, Context budget, and Capability Pack remain frozen.
Reports include sample count, paired differences, dispersion, and uncertainty;
they do not claim population causality.

Real Reader Calibration consumes only pre-existing or newly supplied human
outcomes with prediction timestamps preceding outcomes and a separate holdout.
When none exist, the Campaign emits a BLOCKED report and may only prove the
data contract, builder, split, and evaluation protocol.

## Claim ceilings

Passing the complete frozen 300-chapter contract may establish
`SINGLE_BOOK_LONGFORM_PROVEN=true`. It never implies multibook or production
proof. `MULTIBOOK_PROVEN` and `PRODUCTION_PROVEN` remain false unless separate
matching evidence is supplied.
