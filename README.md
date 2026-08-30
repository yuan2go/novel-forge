# Novel Forge

Novel Forge is a local-first, PostgreSQL-authoritative AI novel production platform and an early Novel Operating System runtime. It coordinates versioned plans, governed chapter production, reader/recap follow-up, narrative state, source intelligence, knowledge assets, and bounded Agent execution through auditable operations rather than an interactive prompt workflow.

The production backend has one runtime family:

```text
FastAPI / CLI / workers
        ↓
Authority applications and Book/Chapter coordinators
        ↓
ProductionExecutionComposition
        ↓
Command Kernel · Attempt/Lease/Fence · ExternalEffect · RuntimeJob
        ↓
PostgreSQL Authority + MinIO object storage + governed providers
```

Interactive Legacy API, CLI, Celery, workflow, Agent scheduler, production kernel, LocalStorage runtime, and their UI were retired. The only retained Legacy surface is the offline `novel-forge-migrate` utility for importing frozen snapshots into PostgreSQL Authority.

## Start here

- [Documentation index](docs/README.md)
- [Architecture overview](docs/architecture/overview.md)
- [Novel production flow](docs/product/novel-production-flow.md)
- [Local development](docs/operations/local-development.md)
- [Testing and proof levels](docs/development/testing.md)
- [Bounded Quality Qualification](docs/operations/quality-qualification.md)
- [Legacy snapshot migration](docs/operations/legacy-migration.md)

## Local verification

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,industrial]'
make p0-backend-list-gates
P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-p0 \
  make p0-backend-qualification
```

`p0-backend-qualification` is the canonical backend engineering gate locally and
in CI. It requires a clean exact-revision worktree, executes every declared
backend and PostgreSQL collection, performs migration/query-plan checks, and
runs the scripted Authority Compose recovery/restart proof. PostgreSQL, API, and
object-store host ports are Docker-assigned; every destructive resource is
bound to a UUID run identity and ownership-checked before cleanup.

The report records a resolved dependency digest. Git SHA alone cannot fully
reproduce the currently unlocked dependency ranges; do not interpret an exact
source revision as an exact dependency environment.

For ordinary backend development outside qualification, start the Authority
stack with:

```bash
make authority-up
```

The default Compose profile uses the scripted `mock` provider. It is a development fixture and is not evidence of real-provider operation or production verification. See [configuration](docs/operations/configuration.md) and [testing](docs/development/testing.md) before interpreting a green run.

## Deferred Admin UI

The current files under `web/admin` are an unsupported historical snapshot and
will be replaced by a dedicated UI reconstruction. They are not an Authority
client, are not part of backend qualification, and remain
`DEFERRED / NOT_RUN_BY_SCOPE`. A backend PASS is not UI or product-experience
evidence.

## Source of truth

Runtime reachability is declared in `architecture/manifests/production-entry-manifest.yaml` and `worker-manifest.yaml`; database evolution is declared in `migration-manifest.yaml`. Architecture fitness tests fail when production imports the migration-only Legacy surface or bypasses protected boundaries.
