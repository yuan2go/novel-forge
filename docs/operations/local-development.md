# Local development

## Requirements

- Python 3.12+
- Docker with Compose v2 for PostgreSQL, MinIO, and integration validation

Node.js and the current Admin sources are not required for backend work. The
Admin UI is deferred and is not part of the qualification described here.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,industrial]'
```

There is no repository lock or constraints file yet. The qualification report
therefore records the resolved dependency digest, Python identity, and resolved
package set. Git SHA alone cannot reproduce unlocked dependency ranges.

## Canonical backend qualification

```bash
test -z "$(git status --porcelain --untracked-files=all)"
make p0-backend-list-gates
P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-p0 \
  make p0-backend-qualification
```

The command is the same public entry used by the authoritative CI job. It
requires a clean exact-revision worktree and refuses a mismatched `GITHUB_SHA`,
real-provider routes, or provider credentials. Do not source `.env` or supply a
pre-existing database DSN to qualification; the runner creates its own
run-scoped resources.

Each run derives a lowercase UUID identity for its Compose project, database,
and artifact directory. PostgreSQL, MinIO, and API host ports are
Docker-assigned after container creation, so parallel runs do not share a fixed
port, project, database, network, or volume.

The output layout is:

```text
<P0_EVIDENCE_DIR>/p0-backend-qualification-<full-sha>.json
<P0_EVIDENCE_DIR>/novel-forge-p0-<sha12>-<uuid>/
  backend-pytest.xml
  backend-pytest-collection.json
  postgresql-pytest.xml
  postgresql-pytest-collection.json
  query-plan.json
  compose-runtime.json
  *-process.json
  compose-resource-ownership-*.json
```

JUnit XML and collection JSON are the Authority for counts, duration, skips,
and complete collection membership; terminal summaries are informational only.

Cleanup is fail closed. The runner captures exact Docker IDs and both project
and run labels before any destructive cleanup. If cleanup reports `FAIL`, keep
the evidence directory, inspect its ownership receipt and current Docker
labels, and resolve the mismatch explicitly. Never run an unscoped
`docker compose down --volumes`, prune, or deletion command as recovery.

## Focused backend checks

For iteration before the final clean run:

```bash
make p0-backend-static
make authority-test
make authority-compose-config-check
```

These are useful diagnostics, but they do not replace the complete canonical
qualification. Manual PostgreSQL/query-plan targets require an explicit
`NOVEL_FORGE_DATABASE_URL`; they have no fixed-port fallback and their results
are not the final P0 report.

## Full runtime

```bash
make authority-compose-config-check
make authority-up
curl -fsS http://localhost:8000/liveness
curl -fsS http://localhost:8000/readiness
curl -fsS http://localhost:8000/runtime/readiness
```

Use `make authority-logs` while the stack is running and `make authority-down` when finished. The default provider is scripted; the stack is intended for local fixture validation.

## Deferred Admin UI

The current `web/admin` pages are an unsupported snapshot scheduled for a
separate whole-UI reconstruction. They are not maintained as an Authority
client in this work package and remain `DEFERRED / NOT_RUN_BY_SCOPE`. Do not add
Admin build, lint, or test commands to backend qualification and do not infer UI
or product evidence from a backend PASS.
