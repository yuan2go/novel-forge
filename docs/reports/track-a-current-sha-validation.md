# Track A Current-SHA Validation

Updated: 2026-08-03

```text
branch=feat/v7-content-intelligence-and-longform-proof
commit_sha=ea6876476287e90a206ec4a10b2345a881f67656
evidence_scope=code/config/migration/test behavior
python=3.12.2
postgresql_client=16.14
postgresql_image=pgvector/pgvector:pg16
node=v26.3.1
npm=11.16.0
docker=24.0.7
docker_compose=v2.23.3-desktop.2
```

## Test matrix

| Command | Result | Passed | Failed | Errors | Skipped | Notes |
|---|---|---:|---:|---:|---:|---|
| `python -m compileall -q src tests` | PASS | n/a | 0 | 0 | 0 | 670 Python files were also scanned by head-integrity |
| `python -c "import novel_forge"` | PASS | 1 | 0 | 0 | 0 | package import |
| `python -m novel_forge.cli --help` | PASS | 1 | 0 | 0 | 0 | development selector displays isolated Legacy CLI; production authority CLI was exercised by Compose migration/API |
| `make head-integrity-check` | PASS | 670 | 0 | 0 | 0 | 1,768 tracked files after staging reports; no missing imports/exports/registry targets/tests |
| `make architecture-manifests-check` | PASS | 4 inventories | 0 | 0 | 0 | 16 modules, 51 migrations, 8 workers, 7 scripts; all required test patterns non-zero |
| `make architecture-fitness-check` | PASS | 25 domain files + 72 production files | 0 | 0 | 0 | 12 classified production entries; zero violations |
| `make authority-parity-check` | PASS | 12 mapped Legacy capabilities | 0 | 0 | 0 | zero direct-write bypasses; production proof remains false |
| `make check-skills` | PASS | 1 drift check | 0 | 0 | 0 | root Skills and generated runtime copies agree |
| `make validate` | PASS | 1 local workspace | 0 | 0 | 0 | ignored local validation workspace; no production evidence |
| `python -m unittest discover -s tests/architecture -p 'test_*.py'` | PASS | 60 | 0 | 0 | 0 | final documentation-aware rerun: 21.369 s |
| `python -m unittest discover -s tests/unit -p 'test_*.py'` | PASS | 1,169 | 0 | 0 | 0 | 455.502 s |
| `python -m unittest discover -s tests/acceptance -p 'test_*.py'` | PASS | 2 | 0 | 0 | 0 | 0.331 s |
| `python scripts/run_authority_postgres_tests.py` | PASS | 141 | 0 | 0 | 0 | 138.818 s; strict Current-SHA rerun |
| `python -m unittest discover -s tests/integration -p 'test_*.py'` | PASS_WITH_SKIPS | 222 | 0 | 0 | 9 | 682.175 s; skips are optional online backends, not core Authority |
| `npm --prefix web/admin ci` | PASS | n/a | 0 | 0 | 0 | 29 packages installed; one install-script approval warning |
| `npm --prefix web/admin test` | PASS_WITH_SKIP | 11 | 0 | 0 | 1 | Playwright absent; browser smoke not executed |
| `npm --prefix web/admin run build` | PASS | 74 routes | 0 | 0 | 0 | Next.js compile, TypeScript and static generation pass |
| `docker compose config --quiet` | PASS | 1 | 0 | 0 | 0 | default topology parses |
| `docker compose build` | PASS | 3 images | 0 | 0 | 0 | API, worker and web images built |
| `docker compose -f compose.authority-only.yml config --quiet` | PASS | 1 | 0 | 0 | 0 | fail-closed Track B settings parse |
| `docker compose -f compose.authority-only.yml build` | PASS | 4 service images | 0 | 0 | 0 | migrate/API/authority/maintenance images built |
| `docker compose -f compose.authority-only.yml up -d --wait` | PASS | 7 services | 0 | 0 | 0 | migration exited 0; API/PostgreSQL/Redis ready; MinIO reachable; workers running |
| Track B HTTP command/query/restart smoke | PASS | 1 vertical chain | 0 | 0 | 0 | duplicate replay and post-restart active projection proved |
| `python scripts/run_d0_provider_probe.py` | BLOCKED_EXPECTED | 11 fixture contract checks | 0 | 0 | 0 | exit 2, `BLOCKED_MISSING_CREDENTIALS`; all real gates false |
| `npm --prefix web/admin audit --omit=dev --json` | FAIL_SECURITY | 0 | 3 high | 0 | 0 | Next.js/PostCSS/sharp; Track E blocker |

## Track A gate

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
```

The Track A gate is true for the implementation evidence SHA. It does not imply Provider, long-form, public-security or production-scale proof.

The Docker runtime proof used dedicated Compose project volumes. After evidence capture, `docker compose -f compose.authority-only.yml down -v` and `docker compose -f compose.postgres-test.yml down -v` removed the dedicated test containers, networks and volumes.

## Proof classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
deployment_verified=true  # local isolated Track B runtime
external_execution_proven=false
longform_proven=false
production_verified=false
```
