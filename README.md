# Novel Forge

Novel Forge is a local-first AI novel production runtime with PostgreSQL business
authority, governed external effects, versioned artifacts and bounded workers.

Executable code, schema, migrations, runtime composition and tests are the only current
system authority. Start with:

- `docs/current-system.md` — architecture, ownership, runtime paths and evidence ceiling.
- `docs/runtime-operations.md` — setup, migrations, validation and recovery.
- `docs/development.md` — repository, documentation and comment rules.
- `architecture/reality-evidence.json` — machine-readable evidence inventory.

## Local setup

```bash
uv venv --python 3.12
uv pip install -e '.[api,postgres,provider-openai,test,object,ingestion,industrial]'
npm --prefix web/admin ci
make authority-test
```

Start the PostgreSQL and object-store composition with:

```bash
make authority-up
```

The default `mock` Provider route is a fixture. It does not establish real-Provider,
long-form, human/editorial or production proof.

Validate documentation and evidence references with:

```bash
make documentation-reality-check
```
