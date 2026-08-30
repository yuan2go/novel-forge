# Current system

## Reality boundary

Novel Forge is a local-first AI novel production runtime. The production composition is
PostgreSQL-authoritative, uses MinIO-compatible object storage for object payloads, and
routes external model work through governed execution and ExternalEffect records.

This document describes only code reachable from the current repository. The detailed,
machine-checked map is `architecture/reality-evidence.json`.

Evidence states mean:

| State | Meaning |
|---|---|
| `CODE_EXISTS` | A concrete implementation symbol exists. |
| `WIRED` | A production composition, router, CLI, worker, or manifest references it. |
| `EXECUTABLE` | A declared runtime entry can invoke it. |
| `QUALIFIED` | Current repository tests exercise the cited behavior at this revision. |
| `PRODUCTION_PROVEN` | Current live production evidence is bound to this revision and configuration. |

No capability in the current inventory is `PRODUCTION_PROVEN`.
`src/novel_forge/api/authority_app.py` returns `runtime_ready=false`,
`real_provider_qualified=false`, `real_provider_proven=false`,
`longform_proven=false`, and `production_verified=false` from its readiness projection.
The CI workflow also excludes credentialed real-Provider execution.

## Executable topology

```text
CLI / FastAPI / worker
        -> application or coordinator
        -> owning domain Authority
        -> Command Kernel Operation
        -> Attempt + Lease + Fence
        -> Production Execution / ExternalEffect when I/O is required
        -> owning Authority commit
        -> PostgreSQL evidence, outbox and accepted projections
```

The principal composition points are:

- `pyproject.toml` declares the CLI and worker entry points.
- `src/novel_forge/cli/authority.py` owns the primary CLI.
- `src/novel_forge/api/authority_app.py` builds the FastAPI application and routers.
- `src/novel_forge/api/authority_dependencies.py` constructs applications and shared
  execution dependencies.
- `src/novel_forge/infrastructure/production_execution_composition.py` carries the
  process-shared execution gateway, object-store adapter and budget configuration.
- `compose.yml` deploys PostgreSQL, object storage, migration, API and worker processes.
- `architecture/manifests/production-entry-manifest.yaml` and
  `architecture/manifests/worker-manifest.yaml` enumerate checked production entries.

## Authority and mutation boundaries

| Fact | Owner and mutation boundary |
|---|---|
| Operation admission, lifecycle and idempotency | Command Kernel through `src/novel_forge/modules/command_kernel/service.py` and PostgreSQL repositories. |
| Attempt, lease and fencing state | Command Kernel through `src/novel_forge/modules/command_kernel/attempt_runtime.py`; workers must present the current fence. |
| External request intent, dispatch and receipt | ExternalEffect runtime in `src/novel_forge/modules/command_kernel/external_effect_runtime.py`; ambiguous outcomes require reconciliation. |
| RuntimeJob coordination | `src/novel_forge/modules/runtime_job/application.py`; it coordinates execution and does not own business truth. |
| Provider routing and execution evidence | Production Execution plus `src/novel_forge/modules/provider_control/`; domain activation remains outside the gateway. |
| Project and workspace state | Project Authority. |
| Story-design candidates and decisions | Story Design Authority; generation does not activate plans. |
| Active typed plans and plan changes | Hierarchical Planning and Plan Change Authority. |
| Chapter candidates, review and release artifacts | Chapter Authority saga and its typed handlers. |
| Book progress and accepted chapter cursor | Book Authority. Chapter acceptance is a Book mutation, not a worker-local fact. |
| Canon decisions | Canon approval authority; extraction output alone is not accepted Canon. |
| Current Narrative State | Deterministic projection from Book-accepted ChapterOutcome evidence. |
| Agent definitions, sessions and transcript provenance | Agent Runtime; domain assets are committed only by the owning domain Authority. |
| Source documents and reusable knowledge | Source Authority and MKAOS Authority; raw source text is not draft authority. |

Repositories are cursor-bound mechanics inside `AuthorityUnitOfWork`. A repository does
not gain business ownership by writing a table. Cross-owner changes must enter through
the owning application or an explicitly composed transaction.

## Chapter runtime

The durable API path enters `ChapterAuthorityApplication.admit`, persists a root Saga
and the first node with `admit_single_chapter_saga`, and lets
`ChapterAuthorityScheduler` advance bounded work. The synchronous `run` method is
guarded by `allow_synchronous_fixture` and is not the production execution proof.

`ChapterNode` orders the typed plan, execution-intent, memo, retrieval, context, draft,
review/revision, Canon, quality, publish, export and final-release stages. Model or
object-store I/O is represented as ExternalEffect work. Quality correction is bounded;
release gates do not accept a missing or failed prerequisite.

## Book opening and book production

`build_book_opening_workflow` creates five durable layers: `BOOK_PLAN`,
`VOLUME_PORTFOLIO`, `CURRENT_VOLUME`, `INITIAL_ARC_SCOPE`, and `INPUT_SNAPSHOT`.
PostgreSQL constraints introduced by migration
`20260829_0104_book_opening_workflow_nodes` bind graph, execution, semantic checkpoint,
receipt and input-snapshot identities. Parent completion exposes only the next eligible
layer.

Book production delegates chapter execution to Chapter Authority. `PostgresBookAuthority`
accepts a chapter only after exact Chapter evidence exists. One acceptance transaction
binds the accepted ChapterOutcome, Story State, Canon snapshot, long-form projection set,
book cursor and audit/outbox evidence. Reader Outcome and recap follow-up are advisory
side work and cannot rewrite accepted facts or activate future plans directly.

## Persistence and schemas

`AuthorityUnitOfWork` is the common PostgreSQL transaction boundary. Its normal exit
rolls back unless `commit()` completed. Coordinated nesting uses savepoints; independent
network I/O is kept outside business transactions.

`src/novel_forge/storage/migrations/runner.py` owns the linear migration registry and
the `nf_schema_migrations` table. The current registered head is
`20260829_0104_book_opening_workflow_nodes`. Migration preflight rows fail closed when a
non-zero blocker count is returned.

MinIO-compatible storage is reached through an ExternalEffect adapter. PostgreSQL stores
immutable object identity, hash, size and receipt evidence rather than treating a local
path as authority.

## Failure, retry and replay

- Idempotency replay requires the same request digest; a reused key with different input
  is a conflict.
- A worker retry uses a current Attempt lease and fencing token. A stale owner cannot
  complete work.
- Serialization failure and deadlock are the database retry classes declared safe by
  `classify_sqlstate`. An unknown transaction outcome requires reconciliation.
- A Provider request that may have started is never blindly resent. Its frozen
  ExternalEffect capability, request identity, receipt and budget are queried or
  reconciled first.
- Recovery appends attempts, assessments, receipts or replacement lineage; it does not
  rewrite terminal history.
- Book Opening recovery jointly validates Opening, RuntimeJob, Attempt, Lease, semantic
  execution, ExternalEffect, checkpoint and budget ownership.

## Current qualification and gaps

The repository contains unit, architecture, acceptance and PostgreSQL integration tests,
Compose fixture/recovery checks, worker scenario checks, query-plan checks and web tests.
Passing them establishes engineering qualification only for their fixtures and scope.

At the frozen start revision `6b8ed04928bc40a7b347c93db4adaf1db72435d7`, the
non-skippable PostgreSQL gate has 35 reproducible failures even on a newly created tmpfs
database: 20 migration/constraint tests, two legacy-planning lineage tests, 11 Book
production tests and two Book Opening hardening/replay tests. The exact groups and
representative executable tests are recorded in `architecture/reality-evidence.json`.
The complete 2,127-test repository run has 55 failures: 11 are duplicate collection of
the same Book vertical failures, while six Chapter model-effect, one Plan Change and two
Story Design tests add independent failing symbols. Consequently Provider effect control,
Story Design/Plan Change activation, Book Opening, Book acceptance, migration and their
combined recovery claims remain `EXECUTABLE`, not `QUALIFIED`. This documentation reset
does not change those business paths.

Current boundaries, encoded in executable readiness and release-evidence code, are:

- credentialed real-Provider proof: not established;
- human editorial or reader proof: not established for the current revision;
- stable long-form and multi-book production: not established;
- autonomous end-to-end book operation: not established;
- production deployment verification: not established;
- backup restore and point-in-time recovery proof: not established.

The only next architecture work should begin from a failing executable gate or a missing
runtime path in `architecture/reality-evidence.json`. Future design text cannot change
these boundaries.
