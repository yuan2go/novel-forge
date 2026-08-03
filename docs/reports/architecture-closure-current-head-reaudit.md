# Architecture Closure Current-HEAD Re-audit

Updated: 2026-08-03

## Audit identity

```text
branch=feat/v7-content-intelligence-and-longform-proof
remote_baseline_sha=5188e1ffb87ec4f42b9ca3e51f3a7ec17ecdf737
implementation_evidence_sha=ea6876476287e90a206ec4a10b2345a881f67656
historical_audit_sha=aa991b53039cdf2e4e7911d4483052b9a6a752a1
environment=macOS/Docker Desktop, Asia/Shanghai
python=3.12.2
postgresql_client=16.14
postgresql_test_image=pgvector/pgvector:pg16
node=v26.3.1
npm=11.16.0
docker=24.0.7
docker_compose=v2.23.3-desktop.2
```

The branch was fast-forwarded from the historical audit baseline to the current remote baseline before implementation. The implementation evidence is the later local commit above. The report commit may be newer because reports do not change `src/` behavior.

## Commands executed

The following were executed against the local checkout; exact results are in [track-a-current-sha-validation.md](track-a-current-sha-validation.md).

```bash
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
python -m compileall -q src tests
python -c "import novel_forge"
python -m novel_forge.cli --help
make head-integrity-check
make architecture-manifests-check
make architecture-fitness-check
make authority-parity-check
make check-skills
make validate
python -m unittest discover -s tests/architecture -p 'test_*.py'
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m unittest discover -s tests/acceptance -p 'test_*.py'
python scripts/run_authority_postgres_tests.py
python -m unittest discover -s tests/integration -p 'test_*.py'
npm --prefix web/admin ci
npm --prefix web/admin test
npm --prefix web/admin run build
npm --prefix web/admin audit --omit=dev --json
docker compose config --quiet
docker compose build
docker compose -f compose.authority-only.yml config --quiet
docker compose -f compose.authority-only.yml build
docker compose -f compose.authority-only.yml up -d --wait
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
python scripts/run_d0_provider_probe.py
```

## Code facts

### Module and entry inventory

The machine authority is `architecture/manifests/` rather than this prose summary.

- 16 required modules import, including Project, Task, Source, MKAOS, Chapter, Book, BookDesign, Provider Control, Provider Qualification and Legacy Migration.
- 7 console-script targets import.
- 12 production entries are classified as Transaction Command, Durable Job, Saga or External Effect.
- CLI selection is deliberate: development without PostgreSQL uses the isolated Legacy CLI; production/`authority-*` commands select the PostgreSQL Authority CLI.
- Authority API has a `track-b-minimal` composition root that does not construct Provider or Legacy services.

Authoritative files:

- `architecture/manifests/module-manifest.yaml`
- `architecture/manifests/console-script-manifest.yaml`
- `architecture/manifests/production-entry-manifest.yaml`
- `architecture/manifests/fitness-policy.yaml`

### Migration inventory

- Registry count: 51.
- Unique head: `20260803_0051_book_design_authority_slice`.
- Clean PostgreSQL 16 migration and an upgrade from the supported `0007` baseline pass.
- Migration 0051 adds Project/Workspace-scoped Book and BookDesign Authority data, typed asset lifecycle records, dependency/decision/activation/supersession/evidence records, object lifecycle metadata and Legacy cutover state.
- All new foreign keys have indexes required by the repository migration fitness tests.

Authority: `architecture/manifests/migration-manifest.yaml` and `src/novel_forge/storage/migrations/versions/__init__.py`.

### Worker inventory

Eight importable worker targets are recorded. The Track B runtime deploys four execution-nature groups, of which `authority-worker` and `maintenance-worker` are active in the minimal profile; `execution-worker` and `integration-worker` are explicit opt-in profiles. PostgreSQL remains task/state Authority and Redis is labelled delivery-only.

Authority: `architecture/manifests/worker-manifest.yaml` and `src/novel_forge/workers/runtime_groups.py`.

### Test inventory

Required discovery is non-zero and machine checked:

| Collection | Discovered |
|---|---:|
| architecture | 60 |
| unit | 1,169 |
| acceptance | 2 |
| integration | 231 |

The PostgreSQL Authority focused runner separately discovers and passes 141 tests with zero skips.

Authority: `architecture/manifests/test-manifest.yaml`.

## Runtime verified

```text
repository_file_integrity=PASS
current_head_import=PASS
migration_chain=PASS
required_test_discovery=PASS
architecture_fitness=PASS
default_compose_config_and_build=PASS
track_b_authority_only_compose_config_build_start=PASS
track_b_health_and_dependency_readiness=PASS
track_b_api_worker_restart_recovery=PASS
book_bookdesign_http_vertical_slice=PASS
d0_fixture_contract=PASS
d0_real_provider=BLOCKED_MISSING_CREDENTIALS
```

The running Track B stack reported PostgreSQL Authority at migration 0051, reachable MinIO, PostgreSQL Outbox, Redis delivery-only, Legacy writes disabled and silent fallback disabled. Both grouped workers persisted fresh `READY` health projections.

## Not executed

- Required Playwright browser smoke: Playwright is not installed; Node test reported one explicit skip.
- Real Provider network execution: no SDK, API key or provider auth profile was available.
- Real platform publish/withdraw/callback.
- Backup restore/PITR, load, capacity, SLO and public authentication drills.
- L3/L10/L30/L100/L300/L1M real-provider long-form acceptance.

## Blocked preconditions

1. `BLOCKED_MISSING_CREDENTIALS`: D0 cannot prove auth, Provider receipts, actual usage/cost, query/cancel/timeout or real UNKNOWN reconciliation.
2. `BLOCKED_SECURITY_HARDENING`: `npm audit --omit=dev` reports three high-severity production dependency findings affecting Next.js 16.2.9 and its PostCSS/sharp dependency graph; fixes are available. This is a Track E deployment-security blocker, not a silently accepted production pass.
3. Public/multi-user authentication is not implemented; the verified runtime is a trusted local-operator deployment with server-configured identity.
4. The default `docker-compose.yml` remains the broader Legacy-oriented development topology. `compose.authority-only.yml` is the verified Track B production-minimal topology; default topology retirement is not claimed.

## Document conflicts

The 2026-08-01 current-state documents said Project/Task/Source/MKAOS targets might be absent and no current-SHA local validation existed. Local code inspection showed those targets in the working tree but not yet committed at the historical SHA. They are committed and import-verified at `ea687647...`.

The pre-revision Architecture Closure order placed most Authority-only runtime work in Track E, Provider qualification in later Track D work, and critical Legacy retirement mostly in Track F. The limited revision now places:

```text
Track B minimal Authority-only runtime
→ D0 real Provider qualification
→ Track C
```

and requires critical Legacy writer cutover in every vertical Slice. Track E now owns hardening; Track F owns residual non-critical cleanup and scale proof.

## Evidence classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
deployment_verified=true  # isolated Track B local deployment only
external_execution_proven=false
longform_proven=false
production_verified=false
```
