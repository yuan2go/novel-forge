# Canonical hierarchy closure bounded qualification — 2026-08-26

This is an exact-SHA engineering qualification record. It is not an
architecture source, literary-quality evidence or production certification.
Target semantics remain in
[canonical-overall-design.md](../architecture/canonical-overall-design.md).

## Identity and environment

- Work Package: `WP-HIERARCHY-CLOSURE-01`
- qualified implementation SHA: `9dfe3d223ff2bbe33fb14a266a38bc613ebd57bf`
- starting `origin/main`: `6a6c86014bb70835ec3bda90fe535a79c11466ae`
- feature branch: `codex/hierarchy-closure-01`
- migration head: `20260825_0100_hierarchy_closure`
- database: isolated local `novel_forge_hierarchy_closure_test`
- PostgreSQL: Homebrew 16.14
- provider boundary: deterministic/scripted Provider fixtures only; no external
  real-provider call was performed
- campaign boundary: bounded 1–4 Chapter fixtures only; no 30/100/300 Chapter
  or other long-form campaign was performed

## Qualified runtime closure

The qualified implementation preserves current Authorities and closes these
production seams:

- Story Formation is a durable, idempotent, restartable coordinator over the
  existing Command Kernel and RuntimeJob worker. It advances six separately
  qualified Foundation contracts and activates reference-only BookDesign v5;
  it owns process lineage, not Story truth.
- Every child Foundation candidate and generation Operation freeze the same
  exact parent AssetVersion/content-hash set. Mixed Formation generation,
  unfinished Formation, parent drift and stale stage retries fail closed.
- Book opening is a durable command/admission API. The existing Book worker
  performs Narrative Search, hierarchical planning and production-input
  snapshot resolution outside the HTTP request lifecycle.
- Narrative Realization is a typed causal correctness contract governed by
  Hierarchical Planning. It is not a `PlanContractType`, narrative scale,
  Accepted Actual or parallel Authority.
- ChapterGroup qualification records an independent versioned realization
  proof with exact evidence for Canon/state, motivation, world rules,
  knowledge, causality, state transition, obligation, Arc, load and Chapter
  decomposition legality.
- A ChapterPlan resolves and exact-compares its current Frozen realization
  slice at generation, activation, replacement, materialization and production
  admission. Missing, stale, mixed or digest-drifted lineage fails closed.
- Accepted Chapter Outcome evidence consumes planned event slices. Causal,
  state-delta and disclosure drift creates deviation and future-only Replan
  evidence. A multi-Chapter realization becomes executed only after all
  required events and all terminal optional-event decisions are accepted.

## End-to-end proof A — Foundation to ChapterPlan

~~~text
Qualified Creative Foundation / Theme / Ending / Reader Promise
  -> Qualified WorldBible
  -> Qualified CharacterCast
  -> reference-only BookDesign v5
  -> durable Book Opening Operation / RuntimeJob
  -> searched Book / Volume / Arc / ChapterGroup contracts
  -> AEC2 typed causal Narrative Event Chain
  -> independent ARC Narrative Realization proof
  -> Approved/Frozen Narrative Realization slice
  -> ChapterPlan / ExecutionIntent / Context / Chapter production admission
~~~

The PostgreSQL vertical enters through the HTTP admission endpoint, persists
the opening run and job, executes through the Book worker, survives an injected
crash after the business commit, and reconciles the same persisted result on
attempt two. The request lifecycle never owns Provider or Planning execution.

## End-to-end proof B — Accepted Actual to future evolution

~~~text
Chapter candidate / Review / Revision / Quality
  -> Accepted Chapter Outcome
  -> observed-event evidence
  -> accepted realization slice coverage
  -> Canon / Narrative State / Arc Actual / obligation projection
  -> deviation and stale-future impact
  -> future-only PlanChange / Replan
  -> next Frozen production input
~~~

Plan declarations and unobserved events do not advance actual state. Chapter
acceptance executes only that ChapterPlan and its accepted event slice;
group-level coverage remains partial until every event reaches a terminal
accepted decision. Executed history remains immutable.

## Defects exposed and repaired

- The Foundation repository previously admitted individually active versions
  without proving one current completed Formation set. It now enforces one run
  and set generation, and consumers require the run to be ready.
- Child candidates froze parent lineage in content but did not require the
  generation Operation to freeze the identical input set. Both identities are
  now exact-compared.
- A stale Formation RuntimeJob could advance whatever semantic stage was
  current when retried. Jobs now freeze stage/version; resume replaces a stale
  pending job with a current-stage job.
- Book opening was callable as an application method but lacked durable
  operator admission/control. It now has persisted run state, API commands,
  RuntimeJob execution and post-commit reconciliation.
- ChapterGroup scheduling evidence could be mistaken for realization proof.
  The proof is now a separate design layer and requires all ten independent
  criterion decisions with rationale and evidence references.
- ChapterPlan callers could provide a valid-looking but authority-divergent
  realization slice. Every write/admission path now resolves the current
  Frozen slice and exact-compares it.
- Realization coverage checked event identity/status but not material causal,
  state-delta or disclosure drift. Accepted observations now enforce all three
  and create deviation evidence on mismatch.
- Migration 0100 initially omitted the new realization-proof layer from an
  existing PostgreSQL check constraint. Fresh/upgrade tests exposed and the
  migration corrected the constraint rather than bypassing it.
- Older hierarchy tests constructed Book or Chapter contracts without the new
  qualified Foundation/Realization boundary. They now seed canonical
  authoritative inputs; no fixture-only production admission was added.

No parallel Workflow Engine, Story Authority, Planning Authority, Agent
Runtime, Chapter Authority, retry engine or Accepted-Actual store was added.

## Commands and results

~~~text
make authority-test
-> 1317 passed, 0 failed, 14 warnings

make authority-postgres-test
-> 210 passed plus 60 subtests, 0 failed, 217.38s

make test
-> Python: 1665 passed, 0 failed, 16 warnings, 403.83s
-> Admin frontend: 11 passed, 0 failed

NOVEL_FORGE_DATABASE_URL=postgresql://yuan@localhost/novel_forge_hierarchy_closure_test \
  uv run --no-sync pytest -q tests/integration/test_authority_migrations_postgres.py
-> 4 passed, 0 failed, 5.30s

NOVEL_FORGE_DATABASE_URL=postgresql://yuan@localhost/novel_forge_hierarchy_closure_test \
  uv run pytest -q tests/integration/test_core_functional_loops_postgres.py::test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres
-> 1 passed, 0 failed, 8.79s

make validate
-> PASS; compile, lint ratchet, module/migration/worker/test/console manifests,
   architecture fitness and Docker Compose configuration all passed
-> migration manifest: 100 migrations, single head 0100
-> architecture reachability: 22/22 entries at the qualified SHA

git diff --check
-> PASS
~~~

The PostgreSQL suite includes fresh and previous-head upgrade migrations,
transaction/idempotency, concurrent admission, lease/fence/takeover, duplicate
delivery, cancellation, retry/recovery/replay, external-effect reconciliation
and failure-injection paths. The hierarchy vertical additionally covers
Foundation lineage/staleness, independent proof qualification, partial/full
realization coverage, accepted-state projection, deviation and future-only
Replan.

Initial regressions were not hidden: `authority-test` first exposed one stale
qualification-profile expectation; the PostgreSQL suite exposed six missing
check-constraint admissions; and the full suite exposed nine old hierarchy
fixtures that bypassed the now-required Foundation/Realization boundary. The
contracts/migration/fixtures were corrected and each complete suite was rerun
green.

## Evidence classification

| Classification | Status | Boundary |
|---|---|---|
| Code Exists | true | Typed contracts, applications, migration and tests are present at the qualified SHA. |
| Wired | true | API, composition root, RuntimeJob worker, Planning, Chapter and accepted-outcome consumers are connected. |
| Integration Proven | true | Full PostgreSQL suite and exact hierarchy vertical passed. |
| Runtime Proven | true — bounded fixture | Durable API/worker/recovery and 1–4 Chapter accepted-state loop passed with scripted Providers. |
| Real Provider Proven | false — NOT_RUN_BY_SCOPE | No external model call, receipt or cost evidence was generated. |
| Long-form Proven | false — NOT_RUN_BY_SCOPE | No 30/100/300 Chapter campaign was run. |
| Literary Quality Proven | false — NOT_PROVEN | Engineering correctness does not establish sustained reader quality. |
| Production Proven | false — NOT_PROVEN | Multi-Book, million-word and production operating evidence is absent. |

## Remaining qualification gaps

- BookDesign v4 and legacy schema remain for durable replay/migration
  compatibility; new production no longer admits them as the Foundation root.
- The bounded proof uses scripted creative/planning outputs. Real-provider
  causal-event quality and repair behavior remain unverified.
- Human blind comparison, reader outcomes, sustained Arc/Volume momentum,
  million-word stability and multi-Book concurrency remain unverified.
- A bounded real-provider Arc/Volume campaign is required before judging
  whether the hierarchy produces consistently compelling long-form fiction.
