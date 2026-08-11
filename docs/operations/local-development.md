# Local development

## Requirements

- Python 3.12+
- Node.js suitable for the versions locked by `web/admin/package-lock.json`
- Docker with Compose v2 for PostgreSQL, MinIO, and integration validation

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm --prefix web/admin ci
```

## Fast local checks

```bash
make validate
make authority-test
npm --prefix web/admin run lint
npm --prefix web/admin test
```

`make authority-test` compiles Python, runs Ruff gates, validates architecture manifests/fitness and HEAD integrity, then runs unit, architecture, and acceptance tests. It does not run the non-skippable PostgreSQL suite.

## PostgreSQL integration

```bash
make postgres-authority-test-up
make authority-postgres-test
make authority-query-plan-release
make postgres-authority-test-down
```

The isolated database listens on port `55432` by default. The runner creates a temporary database, applies the full migration chain, executes PostgreSQL integration tests, and drops the database. Do not replace this gate with fixture tests.

## Full runtime

```bash
make authority-compose-config-check
make authority-up
curl -fsS http://localhost:8000/liveness
curl -fsS http://localhost:8000/readiness
curl -fsS http://localhost:8000/runtime/readiness
```

Use `make authority-logs` while the stack is running and `make authority-down` when finished. The default provider is scripted; the stack is intended for local fixture validation.

## Admin console

```bash
npm --prefix web/admin run dev
```

The console normally runs at `http://localhost:3000` and calls the Authority API at port 8000. Browser smoke requires Playwright and a running local application; `npm test` alone is route/component proof, not end-to-end production proof.
