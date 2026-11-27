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
in CI. It requires a clean exact-revision worktree, makes Documentation Reality
an explicit fail-fast gate, executes every declared backend and PostgreSQL
collection, proves fresh and upgrade migration paths, performs query-plan checks,
and runs the scripted Authority Compose recovery proof. A separate resource-cleanup
gate verifies the PostgreSQL and Compose ownership receipts before evidence
finalization. PostgreSQL and Compose use run-scoped identities and Docker-assigned
loopback ports; successful finalization requires zero owned resources left behind.

The machine report binds the tested commit, source tree, manifest digests and
resolved dependency digest. Git SHA alone does not freeze unlocked dependency
ranges. A local PASS does not close remote branch governance; until required CI
for the same revision passes, that boundary remains `OPEN / NOT_CLOSED`.

For ordinary backend development, start the PostgreSQL Authority stack with:

```bash
make authority-up
```

The default `mock` Provider route is a fixture. It does not establish real-Provider,
long-form, human/editorial or production proof.

## Admin UI boundary

`web/admin` is outside the canonical backend qualification collection. A backend
PASS is not UI or product-experience evidence.

Validate documentation and evidence references with:

```bash
make documentation-reality-check
```
