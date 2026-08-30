# P0 Backend Engineering Qualification and CI Closure Design

> **Status:** Approved for implementation planning
>
> **Date:** 2026-08-30
>
> **Base revision:** `origin/main@483486f4d2609c0870ff4772cad8d592fb69d999`
>
> **Work branch:** `codex/p0-backend-qualification-ci-closure-01`
>
> **Evidence class:** engineering qualification only

## 1. Context

Novel Forge has a substantial PostgreSQL-authoritative backend, including the
Command Kernel, RuntimeJob execution, domain Authorities, Book/Chapter
coordination, Agent Runtime, Source/MKAOS, Narrative State, Quality/Reader
surfaces, provider governance, and Book Opening recovery. The current main tree
declares 104 migrations with
`20260829_0104_book_opening_workflow_nodes` as its head.

The current engineering gap is not the absence of backend structure. It is the
absence of one repeatable, exact-revision qualification path that proves the
current main tree against:

- a clean source identity;
- fresh and upgrade PostgreSQL migration paths;
- unit, architecture, acceptance, and dependency-backed integration suites;
- the backend business vertical slice;
- Compose/runtime readiness;
- a CI definition that only calls repository-supported gates; and
- a machine-readable evidence artifact that preserves what was and was not
  proven.

The existing Admin UI is explicitly outside this phase. All current pages will
be replaced in a later dedicated UI program. They must not drive API design,
block backend qualification, or be cited as current product evidence.

## 2. Decision summary

This work adopts a backend-first, Authority-first qualification model.

1. Create a reusable qualification orchestrator instead of relying on an
   operator remembering a loose list of shell commands.
2. Treat the FastAPI/CLI/worker and PostgreSQL Authority boundaries as the
   public business seams.
3. Use a dedicated PostgreSQL test service on host port `55432`; never reuse the
   repository `.env` DSN or a historical evidence database.
4. Exercise both fresh migration and declared historical upgrade boundaries.
5. Preserve the existing detailed test suites and add tests only where the
   qualification contract exposes a real gap.
6. Make CI fail closed on missing commands, dirty source identity, migration
   drift, database-identity ambiguity, missing evidence, or backend gate
   failure.
7. Remove the obsolete `authority-parity-check` invocation rather than
   recreating the retired Legacy parity plane.
8. Quarantine the current Admin UI from required backend CI without deleting or
   repairing its source.
9. Do not execute real Provider work, mutate the historical orphan, run the
   eight-Chapter campaign, collect human review, or claim production readiness.

## 3. Goals

### 3.1 Engineering qualification

- Qualify the exact final source revision, tree identity, migration manifest,
  module manifest, worker manifest, production-entry manifest, and test
  manifest.
- Prove that a fresh disposable PostgreSQL database reaches migration `0104`.
- Prove supported upgrade paths into `0104`, including the Book Opening
  recovery and workflow-node transitions introduced by `0102`, `0103`, and
  `0104`.
- Run the complete backend unit, architecture, acceptance, and PostgreSQL
  integration gates.
- Run the representative query-plan release gate against an isolated database.
- Prove the scripted-provider Compose runtime can become ready with its required
  worker groups.
- Exercise the minimal backend Novel OS vertical slice through public
  application/API/worker seams, including accepted-state and recovery behavior
  already declared by the repository acceptance standard.

### 3.2 CI closure

- Ensure every workflow command exists in the checked-out revision.
- Ensure local canonical targets and CI invoke the same backend gates.
- Produce deterministic, machine-readable qualification evidence as a CI
  artifact.
- Separate source-level CI correctness from repository-level Actions enablement.
- Correct local-development commands so a new checkout can install the actual
  declared extras.

### 3.3 Evidence integrity

- Record exact commit, tree, dirty state, migration head, manifest digests,
  toolchain versions, dependency snapshot digest, command exit status,
  duration, collected/passed/skipped counts, and artifact hashes.
- Record every deliberately unexecuted evidence class explicitly.
- Never infer real-provider, human, long-form, multibook, or production proof
  from backend fixture qualification.

## 4. Non-goals

- Repairing, redesigning, deleting, or reconnecting any current Admin UI page.
- Designing the future UI information architecture or frontend API client.
- Adding compatibility API endpoints for current Admin calls.
- Enabling real Provider routes or using Provider credentials.
- Recovering or otherwise mutating historical Book Opening databases.
- Running the bounded real-provider 4+4 campaign or human blind review.
- Refactoring large domain modules unless a demonstrated qualification defect
  cannot be fixed safely at an existing boundary.
- Migrating the project to a new package manager or dependency-locking strategy.
  The qualification report will freeze and hash the resolved environment; a
  packaging migration requires its own design decision.
- Declaring `LONGFORM_PROVEN`, `PRODUCTION_QUALIFIED`, or autonomous Agent Center
  completion.

## 5. Engineering principles

### 5.1 Authority and source identity

- The checked-out Git commit and tree are immutable qualification inputs.
- A dirty worktree is rejected before qualification begins.
- Runtime configuration must name PostgreSQL Authority explicitly.
- Memory implementations and scripted providers remain fixtures.
- Historical evidence databases are read-only and never test targets.

### 5.2 Isolation

- Qualification uses an isolated worktree based on the fetched remote main.
- PostgreSQL integration uses the dedicated test service on `55432`.
- Each test run creates uniquely named disposable databases with a recognizable
  qualification prefix.
- Database name, server address, port, user, and server identity are checked
  before the first migration or write.
- The runner refuses DSNs whose database identity is missing, ambiguous,
  historical, or outside the allowed disposable naming policy.

### 5.3 Fail-closed execution

- A missing command, missing dependency, stale manifest, timeout, failed test,
  incomplete report, or runtime-readiness failure makes the qualification fail.
- No gate is silently skipped because Docker, PostgreSQL, MinIO, or a worker is
  unavailable.
- Environment-blocked gates are reported as blocked, not passed.
- Cleanup failure is reported separately and cannot overwrite the primary gate
  failure.

### 5.4 No hidden external effects

- The qualification profile uses the scripted/mock provider only.
- The runner rejects a configured real-provider route or provider credential
  requirement.
- Recovery tests operate on disposable fixtures and do not target the recorded
  orphan.
- No command directly repairs Authority rows with ad hoc SQL.

## 6. Architecture

### 6.1 Qualification orchestrator

Add a repository-owned orchestration entry that coordinates existing gates and
emits one evidence report. The intended public entry is:

```text
make p0-backend-qualification
  -> scripts/run_p0_backend_qualification.py
  -> preflight
  -> static and manifest gates
  -> unit/architecture/acceptance gates
  -> PostgreSQL fresh/upgrade/integration gates
  -> query-plan gate
  -> Compose/runtime gate when requested by the execution profile
  -> evidence finalization
```

The orchestrator is not a second workflow engine. It is a bounded engineering
test runner that invokes existing repository commands, records their results,
and enforces qualification policy.

Required CLI behavior:

- explicit `--profile` with at least `local` and `ci`;
- explicit `--database-url` or approved environment variable;
- explicit `--output` path;
- bounded per-phase and total timeouts;
- no implicit fallback to the repository `.env`;
- no shell-string execution for dynamically constructed arguments;
- structured stdout summary and stable process exit codes;
- signal-aware child termination and cleanup;
- atomic evidence write using a temporary sibling followed by rename; and
- a `--list-gates` or equivalent read-only inspection mode.

The runner may compose existing scripts but must not duplicate their domain
logic. PostgreSQL database creation/drop, migration application, query-plan
qualification, and Compose verification remain owned by their existing
utilities.

### 6.2 Machine-readable evidence

Define a versioned report contract, conceptually:

```text
novel-forge.p0-backend-qualification-report.v1
```

Required top-level data:

- qualification identity and timestamps;
- source commit, source tree, branch/ref, dirty state;
- host/runtime profile without credentials;
- Python, pytest, Ruff, Node, npm, Docker, Compose, PostgreSQL, and MinIO
  versions where applicable;
- a cryptographic digest of the resolved Python package snapshot;
- expected and observed migration head;
- manifest paths and content digests;
- ordered gate results;
- test counts and durations parsed from machine-readable test output where
  available;
- Compose service/readiness evidence;
- cleanup status;
- final decision and failure reason;
- explicit evidence ceilings and `NOT_RUN` classes.

Secrets, DSNs, Provider keys, database passwords, MinIO secrets, and raw
narrative payloads are forbidden from the report. Database and environment
identities use safe labels or one-way digests where needed.

The report is written outside tracked source by default. CI uploads it as an
artifact associated with the exact workflow SHA. A later evidence publication
step may summarize it, but a summary commit is not automatically the tested
SHA.

### 6.3 PostgreSQL qualification matrix

The matrix contains separate, observable gates:

1. **Fresh migration**
   - create disposable database;
   - apply the complete manifest in order;
   - assert `nf_schema_migrations` head is exactly `0104`;
   - run schema and migration invariants;
   - drop the disposable database.
2. **Upgrade boundary: pre-recovery to `0102` and current head**
   - construct the supported historical fixture through migration tooling;
   - apply `0102` through `0104`;
   - verify loss/recovery state and constraints.
3. **Upgrade boundary: `0102` to current head**
   - apply `0103` and `0104`;
   - verify semantic-runtime replacement and workflow-node state.
4. **Upgrade boundary: `0103` to current head**
   - apply `0104`;
   - verify five-node workflow records, constraints, replay, and BookRun
     completion requirements.
5. **Full PostgreSQL integration**
   - run the repository integration suite against disposable databases;
   - include Book Opening concurrency/failure-injection, RuntimeJob,
     ExternalEffect, worker, Chapter/Book, Agent, Source/MKAOS, Narrative State,
     Quality, and provider-callback tests.
6. **Query-plan release**
   - run representative-scale query-plan assertions in its own disposable
     database and retain the structured result.

Upgrade tests must use repository migration fixtures and public migration
commands. They must not clone or modify the historical real-provider database.

### 6.4 Backend business vertical slice

Qualification must include the smallest meaningful Novel OS backend flow,
using existing public seams and scripted provider behavior:

```text
Project/Foundation/Formation
  -> Book Design and Book Opening
  -> five persistent Opening workflow nodes
  -> exact InputSnapshot binding
  -> BookRun/ChapterGroup/Planning admission
  -> Agent/Context/model boundary under provider hard-stop policy
  -> Chapter candidate and review/rework gate
  -> accepted Chapter outcome
  -> Canon/Narrative State/Arc/Obligation projection
  -> publish release gate
  -> invalidation and resumable recovery checks
```

This requirement is satisfied only by executable tests through Authority
applications, APIs, workers, or registered operations. File existence, route
strings, direct repository mutations, or isolated pure-domain assertions are
not sufficient by themselves.

The slice may be distributed across several focused integration tests when a
single test would create an unmaintainable mega-fixture. The evidence report
must name the tests that jointly establish the slice.

### 6.5 Runtime/Compose qualification

The runtime gate uses the current Compose definition and scripted provider.

Required checks:

- Compose configuration validation;
- successful image build for the migration, API, and required workers;
- migration service completion at `0104`;
- API liveness and dependency readiness;
- runtime readiness with all required worker groups healthy;
- PostgreSQL and MinIO reachability;
- declared production-entry and worker manifests matching the running release;
- controlled smoke operations that create only disposable qualification data;
- graceful teardown; and
- retained logs/evidence when readiness fails.

The gate must not reuse a running stack from another checkout as proof. Compose
project name, ports, volumes, and artifact paths must be qualification-scoped so
parallel local services are not overwritten.

### 6.6 CI structure

The existing Core OS workflow remains the source-level CI entry, but is
corrected and made internally coherent.

Required backend jobs:

1. source identity, compile, lint, manifests, and architecture fitness;
2. unit and acceptance;
3. PostgreSQL Authority integration and migration matrix;
4. Book Opening workflow/recovery/concurrency focused gate;
5. provider hard-stop and callback gate using fixtures only;
6. query-plan release;
7. Compose/runtime readiness; and
8. qualification evidence summary/artifact publication.

CI commands must reference existing Make targets. The deleted Legacy
`authority-parity-check` is removed from the workflow and is not recreated.

The current Admin build/test job is excluded from required P0 backend CI. This
does not mean the UI is green. It means the UI is explicitly deferred and
provides no evidence for this phase. The future UI program must restore its own
build, type, contract, accessibility, and browser gates before UI acceptance.

Repository-level GitHub Actions enablement is an external operational gate.
Source CI closure is complete when the workflow is correct and locally
reproducible; remote CI remains `BLOCKED_BY_REPOSITORY_CONFIGURATION / NOT_RUN`
until Actions are explicitly enabled and a run for the final SHA succeeds.

### 6.7 Admin UI quarantine

Current UI source remains unchanged except for an optional boundary notice or
repository documentation link. No current UI endpoint is implemented, adapted,
or declared supported.

The documentation must state:

- current Admin pages are a deferred snapshot;
- they are not a supported Authority client;
- their tests are not backend or product qualification;
- no current page/API pairing may be used as completion evidence; and
- the future UI rebuild requires a separate canonical design and acceptance
  program.

### 6.8 Local development closure

Replace the nonexistent `.[dev]` installation instruction with the actual
backend development extras required by the documented gates. The canonical
backend setup is based on the existing `test` and `industrial` extras.

Documentation must distinguish:

- host Python checks;
- isolated PostgreSQL tests on `55432`;
- qualification-scoped Compose runtime;
- the repository `.env` from an explicit test DSN; and
- scripted-provider engineering proof from real-provider qualification.

## 7. Public seams under test

The approved TDD seams are:

| Seam | Observable behavior | Forbidden shortcut |
|---|---|---|
| Qualification CLI/Make target | deterministic phases, exit status, evidence report | testing private helper functions only |
| Migration CLI/manifest | fresh and historical upgrade reach exact `0104` | editing migration tables directly |
| FastAPI Authority API | registered command/query behavior and fail-closed errors | asserting only that route strings exist |
| Worker/RuntimeJob | claim, lease/fence, checkpoint, retry/dead-letter/recovery behavior | invoking domain repositories directly |
| Command Kernel/provider boundary | dispatch, receipt, budget, hard-stop and replay semantics | real Provider invocation |
| Book/Chapter acceptance | accepted outcome advances authoritative projections exactly once | fixture file creation without Authority commit |
| Runtime readiness | required services and worker groups are actually ready | Compose config validation alone |
| CI workflow | every named command exists and produces required evidence | a workflow that is syntactically valid but unrunnable |

Tests added during implementation must target one of these public seams.

## 8. TDD and defect-handling policy

For every newly discovered backend defect:

1. reproduce it at the nearest approved public seam;
2. add one failing regression test with an independently specified expected
   result;
3. confirm the failure is caused by the defect rather than the environment;
4. implement the complete bounded correction, including state transitions,
   errors, recovery behavior, observability, and compatibility implications;
5. rerun the focused gate;
6. rerun the owning module and architecture gates; and
7. include the regression in the final qualification run.

“Complete bounded correction” is not synonymous with the fewest changed lines.
It includes every layer needed to make the public behavior durable and
operable, while avoiding unrelated refactors.

Tests must not mock away PostgreSQL, RuntimeJob, ExternalEffect, provider
hard-stop, or worker behavior when those dependencies are the subject of the
gate.

## 9. Failure and cleanup behavior

- Each gate records `PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN`.
- The first hard failure stops dependent gates but does not erase completed
  evidence.
- Independent diagnostic finalizers may still collect logs, versions, service
  state, and cleanup results.
- Child processes receive bounded graceful termination followed by explicit
  forced termination only for qualification-owned processes.
- Qualification-created databases, containers, networks, and temporary files
  are named and tracked before creation.
- Cleanup only targets those exact recorded resources.
- Historical volumes, databases, worktrees, and provider evidence are never
  cleanup candidates.
- A cleanup failure yields a non-success final decision and an operator recovery
  instruction.

## 10. Security and privacy

- Never print or persist raw DSNs, passwords, Provider keys, MinIO secrets, or
  database names that contain credential-like material.
- Sanitize subprocess output before embedding it in evidence.
- Store raw logs only in qualification-scoped local/CI artifact locations with
  bounded retention.
- Use one-way digests for sensitive environment identities when correlation is
  needed.
- Reject real-provider configuration in this profile before any worker starts.
- Keep source/MKAOS isolation and copyright boundaries active in all fixtures.

## 11. Verification matrix

The implementation plan must map concrete commands to this matrix:

| Gate | Required result |
|---|---|
| Git/source preflight | exact intended HEAD/tree, clean worktree |
| Compile and diff hygiene | success |
| Ruff Authority gate and ratchet | success, debt count recorded |
| Architecture manifests and fitness | success |
| Head integrity | success |
| Unit/architecture/acceptance | complete, counts recorded |
| Fresh migration | exact `0104` |
| `0101`/`0102`/`0103` upgrade coverage | success |
| Full PostgreSQL integration | complete, no environment skips |
| Book Opening workflow/recovery focused suites | success |
| Query-plan release | success |
| Compose configuration/build/runtime | success |
| API/runtime readiness | all required dependencies/groups healthy |
| Backend vertical slice | accepted-state and recovery invariants proven |
| Evidence report schema and redaction | success |
| UI | `DEFERRED / NOT_RUN_BY_SCOPE` |
| Real Provider | `NOT_RUN_BY_SCOPE` |
| Historical orphan recovery | `NOT_RUN_BY_SCOPE` |
| Eight-Chapter/human/long-form/production | `NOT_PROVEN` |

## 12. Delivery structure

Implementation should proceed in reviewable vertical batches:

1. qualification report contract and redaction tests;
2. qualification runner preflight/static phases;
3. PostgreSQL identity and migration-matrix integration;
4. backend business and runtime phases;
5. Make/CI wiring;
6. UI quarantine and local-development documentation;
7. exact-commit full qualification and final evidence handoff.

Each batch must remain independently testable. Intermediate commits must not
claim qualification completion.

## 13. Acceptance criteria

This work is complete only when all of the following are true:

1. The final branch is based on the intended fetched main revision and is clean.
2. The qualification runner is versioned, documented, bounded, fail-closed, and
   covered through its public CLI/Make seam.
3. Its machine-readable report validates against a stable schema/contract and
   contains no secrets.
4. Fresh and supported historical migration paths reach exact migration `0104`
   on isolated disposable databases.
5. Complete backend unit, architecture, acceptance, PostgreSQL integration,
   Book Opening focused, and query-plan gates pass.
6. Qualification-scoped Compose runtime reaches API and worker readiness with
   the scripted provider and shuts down cleanly.
7. The backend Novel OS vertical slice is evidenced through public runtime
   seams.
8. CI references only existing repository commands and uploads the
   qualification report.
9. The obsolete parity gate and invalid `.[dev]` instructions are removed.
10. Existing Admin UI is explicitly deferred and contributes no false evidence.
11. Remote Actions status is reported honestly; no remote green status is
    claimed while Actions are disabled.
12. Real Provider, historical recovery, eight-Chapter, human, long-form,
    multibook, and production evidence remain separately classified.

## 14. Rollback and recovery

The implementation consists of source changes on an isolated feature branch
and qualification-owned disposable resources.

- Source rollback is performed by reverting bounded commits, never resetting a
  user worktree.
- Database rollback means dropping only qualification-created databases after
  captured evidence and successful ownership checks.
- Compose rollback means tearing down only the qualification project name and
  its explicitly created volumes.
- CI rollback restores the previous workflow file but must not resurrect the
  retired Legacy parity tool.
- Any ambiguous resource ownership stops cleanup and produces an operator
  instruction.

## 15. Evidence ceiling

A successful result establishes:

```text
CURRENT_SOURCE_IDENTIFIED
CODE_IMPLEMENTED
BACKEND_TEST_EXECUTED
POSTGRESQL_MIGRATION_QUALIFIED
SCRIPTED_RUNTIME_PROVEN
CI_SOURCE_CLOSED
```

It does not establish:

```text
CURRENT_UI_QUALIFIED
REAL_PROVIDER_PROVEN
HISTORICAL_ORPHAN_RECOVERED
HUMAN_EVIDENCE_COMPLETE
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_QUALIFIED
```
