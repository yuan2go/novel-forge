# Novel Forge

Novel Forge is a local-first AI novel production runtime with PostgreSQL business
authority, governed external effects, versioned artifacts and bounded workers.

Executable code, schema, migrations, runtime composition and tests are the only current
system authority. Start with:

- `docs/current-system.md` — architecture, ownership, runtime paths and evidence ceiling.
- `docs/runtime-operations.md` — setup, migrations, validation and recovery.
- `docs/development.md` — repository, documentation and comment rules.
- `architecture/reality-evidence.json` — machine-readable evidence inventory.

## Backend qualification

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
backend and PostgreSQL collection, performs migration and query-plan checks, and
runs the scripted Authority Compose recovery proof. Its report records the
resolved dependency digest; Git SHA alone does not freeze unlocked dependency
ranges.

For ordinary backend development, start the PostgreSQL Authority stack with:

```bash
make authority-up
```

The default `mock` Provider route is a fixture. It does not establish real-Provider,
long-form, human/editorial or production proof.

## Deferred Admin UI

The current `web/admin` tree is an unsupported historical snapshot pending a
dedicated reconstruction. It is not part of backend qualification, and a backend
PASS is not UI or product-experience evidence.

Validate documentation and evidence references with:

```bash
make documentation-reality-check
```
