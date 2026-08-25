# Creative Engineering Convergence bounded qualification — 2026-08-25

This is an exact-SHA engineering qualification record, not an architecture
source and not literary-quality evidence. Target semantics remain in
[canonical-overall-design.md](../architecture/canonical-overall-design.md).

## Identity and environment

- Work Package: InkOS Design Harvest + Creative Engineering Convergence
- qualified implementation SHA: `9fcb9b630eea9d7cfcaf0034f3f66d29fa5b9121`
- starting `origin/main`: `3be4f365ecb1a79d57e0e624f67874a3e38c6fc3`
- feature branch: `codex/inkos-creative-engineering-convergence`
- migration head: `20260825_0099_creative_engineering_convergence`
- reference InkOS SHA inspected: `5da9fad03d65882adc030dc0043da8e8bc197dbd`
- database: isolated local `novel_forge_cec_test`
- PostgreSQL: Homebrew 16.14 with pgvector
- provider boundary: deterministic/scripted providers in the engineering
  fixtures; no new external real-provider qualification was performed
- Docker Compose: unavailable on this host, so Compose configuration/runtime
  validation is recorded as environment-blocked rather than passed

InkOS was used only to identify useful design mechanisms. No InkOS runtime,
filesystem authority, PipelineRunner, SQLite authority or AGPL source code was
copied into Novel Forge.

## Qualified convergence

The qualified implementation preserves existing PostgreSQL Authorities and
adds vertical behavior at their current seams:

- legacy fixed-stage Agent admission is retired while old durable Operations
  remain queryable, retryable, recoverable, cancellable and replayable;
- the Unified Agent Harness freezes the Skill catalog and records every
  explicit activation with Skill identity, version, hash, catalog hash and
  transcript lineage without expanding tools or business Authority;
- Context Bundle v7 / Manifest v3 enforce `PROTECTED`, `COMPRESSIBLE`,
  `RETRIEVABLE` and `EPHEMERAL` as runtime invariants;
- retrieval is explicitly lexical-first PostgreSQL FTS, followed by an
  optional bounded semantic rerank that cannot introduce candidates outside
  the frozen lexical/structured set; it is not described as BM25;
- Recent Trail and Hook Debt are rebuildable projections of accepted Chapter
  outcomes and accepted Narrative Obligations, respectively;
- Chapter Transaction Workspace is a read/workbench projection over existing
  immutable Plan, Intent, Memo, Context, Candidate, Review, Quality, Canon and
  Acceptance evidence and has no activation permissions;
- Quality Calibration v2 separates Judge, Human, blind pair, adjudicated,
  reader-outcome, calibration and profile-version evidence. Subjective human
  opinion is not treated as GroundTruth, and reader evidence cannot mutate
  accepted narrative truth;
- existing Best Candidate and State Repair Authorities were surfaced through
  evidence and workspace reachability instead of being reimplemented.

## End-to-end proof A — accepted evidence to Provider

The PostgreSQL Narrative Orchestration fixture proves this chain:

~~~text
Accepted ChapterOutcome / accepted Narrative Obligation
  -> rebuildable Recent Trail / Hook Debt projections
  -> lexical-first bounded retrieval
  -> task-specific Context classification and budgeting
  -> frozen Context Bundle v7 / Manifest v3
  -> Planning Provider task view and frozen runtime usage
~~~

The proof asserts that protected entries cannot be omitted or compressed;
protected over-budget input fails before Provider dispatch; compressible
content retains source/provenance; and Provider-visible ephemeral content is
frozen in Attempt evidence but is rejected from long-lived retrieval indexes.
Semantic rerank escape fails closed, while semantic unavailability uses the
deterministic lexical/structured ordering.

## End-to-end proof B — Chapter transaction to accepted state

The same PostgreSQL fixture proves this chain through current Authorities:

~~~text
Chapter Operation
  -> Chapter Transaction Workspace
  -> active Plan / ExecutionIntent / Memo / frozen Context
  -> Draft and Revision Candidates / Reviews / Best Candidate comparison
  -> Canon and Narrative State proposals / Quality evidence
  -> Book Acceptance
  -> accepted StoryState and Arc/Obligation changes
  -> stale future Plan/Binding impact visible to the workspace
~~~

The workspace copies no narrative truth and grants no activation or acceptance
permission. It resolves immutable identities and authoritative evidence, and
explains why the Chapter exists, what Context was selected or omitted, why a
candidate won or lost, what was accepted, and which future planning evidence
became stale.

## Defects exposed and repaired

- Context priority was previously descriptive rather than enforced; protected
  omission/compression, protected over-budget admission and ephemeral replay
  evidence now fail closed at the Provider boundary.
- Optional compressible input could consume capacity ahead of mandatory
  retrievable quality evidence; required entries now precede optional entries
  within the governed selection order.
- Semantic retrieval could not prove it only reranked a bounded lexical set;
  candidate identity and escape validation are now frozen and replayable.
- Fresh legacy per-stage Agent admission remained reachable despite the
  Unified Harness; fresh registration/admission is retired without breaking
  recovery of historical Operations.
- Skill use lacked an explicit frozen-catalog activation event and hash
  lineage; it is now a governed Harness transcript action.
- Accepted Recent Trail, Hook Debt and Chapter lifecycle evidence lacked one
  author-facing projection, leading callers to reconstruct state ad hoc.
- Quality calibration mixed evidence roles too loosely; subjective human,
  adjudicated, reader and model evidence now have separate typed contracts and
  Authority operations.
- Migration, operation-definition, production-entry and projection-count
  regressions exposed by the full suite were updated to the converged runtime
  rather than hidden with skips or weakened gates.

No parallel Agent Runtime, Context Authority, Retrieval Authority, Narrative
Authority, Quality Authority, retry engine or filesystem truth was introduced.

## Commands and results

~~~text
PYTHON=.venv/bin/python RUFF=.venv/bin/ruff make authority-test
-> 1300 passed, 0 failed; architecture/acceptance/manifests/head-integrity PASS

NOVEL_FORGE_DATABASE_URL=postgresql://yuan@127.0.0.1:5432/novel_forge_cec_test
PYTHONPATH=src .venv/bin/python -m pytest tests
-> 1647 passed, 0 failed, 16 warnings, 409.70s

NOVEL_FORGE_DATABASE_URL=postgresql://yuan@127.0.0.1:5432/novel_forge_cec_test
PYTHONPATH=src .venv/bin/python scripts/run_authority_postgres_tests.py
-> 209 passed, 60 subtests passed, 0 failed, 229.62s

npm --prefix web/admin run lint
-> PASS (TypeScript compiler)

npm --prefix web/admin test
-> 11 passed, 0 failed, 0 skipped

PYTHON=.venv/bin/python make check-skills
-> PASS

git diff --check
-> PASS
~~~

The PostgreSQL runner includes fresh and previous-head upgrade migration,
transaction/idempotency, concurrent admission, lease takeover, stale fencing,
duplicate command, cancellation, provider timeout/malformed or semantically
invalid output, crash/recovery, replay, plan staleness, external-effect
reconciliation and object-store ambiguity coverage. Migration head integrity
reported all 99 migrations and a single current head at 0099.

`docker compose -f compose.yml config --quiet` could not complete because the
Docker runtime/CLI was unavailable. Consequently the aggregate `make validate`
invocation is not reported as passed; its preceding static, manifest and
architecture-fitness stages passed independently above.

## Evidence classification

| Classification | Status | Boundary |
|---|---|---|
| CODE_IMPLEMENTED | true | Vertical runtime and migrations are present at the qualified SHA. |
| POSTGRES_INTEGRATION_PROVEN | true | 209 PostgreSQL tests plus 60 subtests passed without skips. |
| FIXTURE_PROVEN | true | Deterministic/scripted Provider and bounded Chapter fixtures passed. |
| REAL_PROVIDER_PROVEN | false — NOT_RUN_BY_SCOPE | No new external Provider call or cost evidence. |
| LONGFORM_PROVEN | false — NOT_RUN_BY_SCOPE | No long-form campaign was run. |
| PRODUCTION_QUALIFIED | false | Engineering regression does not establish production literary quality. |

## Remaining qualification gaps

- Chapter Workspace has canonical API/read-model support, but the professional
  authoring UI is not yet implemented.
- Lexical-first retrieval relevance and Context behavior across a long novel
  require bounded real-provider Arc/Volume evidence.
- Calibration v2 has bounded engineering proof, not a representative corpus of
  blind human preference, adjudication or Reader Outcome evidence.
- Legacy Agent schema remains for historical migration/recovery compatibility;
  physical deletion requires a later usage audit and qualification.
- Million-word stability, multi-Book concurrency, sustained reader quality and
  long-form literary quality remain explicitly unverified.
