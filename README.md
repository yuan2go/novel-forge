# Novel Forge

Novel Forge is a local-first, PostgreSQL-authoritative novel production runtime.
The repository still contains a development-only local product surface, but the
canonical production path is the Authority API plus the durable Authority worker
fleet in `compose.yml`.

## Current engineering state

The strongest current proof is a deterministic, PostgreSQL-backed two-chapter
Book vertical slice. It covers both uninterrupted progression and explicit Replan
approval:

```text
Book admission
→ Planning activation
→ ChapterGroup / ChapterPlan
→ Chapter Authority Operation / Attempt / ExternalEffect
→ Acceptance / Reader Outcome / Recap
→ next chapter

or

→ replacement Planning candidate
→ PlanChange proposal
→ APPROVAL_PENDING
→ Authority approval command
→ activation / new input snapshot / resume
→ next chapter
```

The Worker may create a Replan proposal, but it cannot approve one. PostgreSQL is
the only production state authority. Deterministic Provider evidence is fixture
evidence; it is not real-provider, sustained-longform, or production-deployment
proof.

See [Project Current State](docs/project-current-state.md) and
[Current Implementation](docs/01-architecture/current-implementation.md).

## Canonical composition

`novel_forge.api.authority_dependencies.build_book_production_composition` is
the Book composition root shared by the Authority API and Book Worker. It
composes the existing Book, Planning, ChapterGroup, Chapter, Preparation,
Followup, PlanChange, input-resolution, and Replan components. Required
dependencies are resolved at startup and fail closed.

Provider-backed Chapter, Planning, Reader, and Agent work shares one
`ProviderAdapterRegistry` built through the existing Provider factory and the
Production Execution Gateway. Controlled environments do not admit scripted
providers or missing credentials.

Runtime environments are exactly:

| Environment | Control level | Fixtures |
|---|---|---|
| `development` | local | allowed |
| `test` | local | allowed |
| `validation` | controlled | forbidden |
| `production` | controlled | forbidden |

`provider-validation` is not a runtime environment. Provider qualification and
proof level are evidence dimensions, not deployment environments.

## Quick verification

Python 3.11+ and pytest are required. Pytest is the canonical runner and also
collects the retained `unittest.TestCase` suites.

```bash
make test
make validate
make authority-test
npm --prefix web/admin test
make sync-skills-dry-run
make check-skills
```

Run the PostgreSQL and Compose qualifications when Docker is available:

```bash
make authority-postgres-test
make authority-compose-config-check
make authority-smoke
```

Generate the current-SHA reachability manifest from code, imports, console
scripts, and `compose.yml`:

```bash
PYTHONPATH=src python -m novel_forge.tools.production_reachability
```

The manifest's highest claim is static architecture reachability. It does not
promote Provider, long-form, or production evidence.

## Local Authority stack

```bash
docker compose up -d --build --wait
curl -fsS http://localhost:8000/readiness
curl -fsS http://localhost:8000/runtime/readiness
```

The default Compose topology includes PostgreSQL, MinIO, migrations, the
Authority API, and the Chapter, Agent, Content, Source, MKAOS, Book, Outbox, and
Maintenance workers. Default local composition uses deterministic Providers and
therefore remains fixture-only.

For exact startup, recovery, and evidence procedures, use the
[Authority Compose Runbook](docs/06-operations/authority-compose-runbook.md).

## Repository boundaries

- `src/novel_forge/modules/command_kernel/` owns business Operation, Saga,
  Attempt, Lease, Fence, ExternalEffect, validation, and commit durability.
- `src/novel_forge/modules/runtime_job/` is only an operational scheduling
  envelope for Book ticks and maintenance scans.
- `src/novel_forge/modules/provider_control/` owns Provider adapter composition;
  production call sites execute through the Production Execution Gateway.
- `src/novel_forge/storage/migrations/` is the PostgreSQL migration authority.
- `compose.legacy.yml`, LocalStorage, Celery/local workflow services, and legacy
  schedulers are development, migration, or isolated compatibility surfaces.
- `skills/` is the Skill source of truth. `.claude/skills/` is generated with
  `make sync-skills`.

Generated runtime assets belong under ignored `.local/` paths. Only deterministic
fixtures in `tests/fixtures/` and `examples/sample_inputs/` are repository data.

## Documentation truth order

```text
current code and migrations
→ current-SHA runtime/test evidence
→ accepted ADRs
→ canonical current docs
→ historical reports, plans, blueprints, and prompts
```

Historical reports describe their original SHA and are navigation material only.

## Copyright boundary

Reference works may contribute abstract structure, pacing, conflict mechanisms,
emotion curves, and craft principles. Novel Forge must not copy protected
expression, distinctive characters, settings, scenes, or plot combinations.
Raw reference text cannot enter generation context as draft expression.
