# Authority Compose Runbook

## Default backend

```bash
docker compose up -d --build --wait
docker compose ps
curl -fsS http://localhost:8000/readiness
curl -fsS http://localhost:8000/runtime/readiness
```

The migration service must reach
`20260806_0073_core_functional_loops` before API/Workers become
ready. Legacy compatibility is not started by this topology.

`/readiness` reports API dependencies and `api_ready`.
`/runtime/readiness` additionally requires fresh Chapter, Agent, Content,
Source, MKAOS, Book, Outbox, and Maintenance Worker heartbeats. Provider and
evidence fields remain explicit; a fixture route never reports real-provider,
long-form, or production proof.

## Configuration checks

```bash
make authority-compose-config-check
make authority-only-config-check
make architecture-manifests-check
```

Production forbids mock providers and fixture MKAOS activation. Never set
`NOVEL_FORGE_MKAOS_ALLOW_FIXTURE_ACTIVATION=true` outside an explicit non-
production E2E environment.

Runtime environments are `development`, `test`, `validation`, and `production`.
The latter two are controlled and reject fixture Provider/MKAOS composition.
Provider qualification is evidence, not an environment named
`provider-validation`.

To inspect code-derived deployment reachability before startup:

```bash
PYTHONPATH=src python -m novel_forge.tools.production_reachability
```

This is static architecture evidence only. Verify `/runtime/readiness`, worker
freshness, and the SHA-bound scenarios for runtime evidence.

## Authority runtime smoke

```bash
make authority-smoke
```

This clean-volume check proves API readiness, complete required Worker fleet
readiness, Content execution, forced Worker restart, expired-lease recovery,
stale-fence rejection, Outbox/Audit evidence, graceful drain of all eight Worker
kinds, and connection cleanup. It uses deterministic Provider routes and is not
real-provider, long-form, or production verification.

## Seven durable Worker E2E scenarios

Run one isolated scenario:

```bash
.venv/bin/python scripts/verify_authority_worker_e2e.py \
  --worker chapter \
  --output /tmp/worker-e2e-chapter-$(git rev-parse HEAD).json
```

Allowed worker values are `chapter`, `content`, `source`, `mkaos`, `book`,
`outbox`, and `maintenance`. Each invocation owns a fresh Compose project and
must remove it unless diagnostic retention was explicitly requested. CI runs the
seven values as independent matrix jobs and builds the fleet summary with:

```bash
.venv/bin/python scripts/build_worker_fleet_summary.py \
  --input-dir /tmp/worker-evidence \
  --commit-sha "$(git rev-parse HEAD)" \
  --output "/tmp/worker-fleet-summary-$(git rev-parse HEAD).json"
```

Do not substitute process health, heartbeat or worker-row existence for the
scenario's domain and recovery assertions.

The Agent worker is part of the eight-process readiness fleet and has its own
AgentRuntime integration coverage; it is not one of this seven-scenario script's
accepted values.

## PostgreSQL qualification

```bash
make authority-postgres-test
make authority-query-plan-release
```

The query-plan qualification uses representative cardinalities and leaves
`enable_seqscan` enabled. Clean migration and schema tests replay 0001→0067.

## Failure handling

- Migration failure: remain unready; apply a forward fix. Do not edit 0001–0058.
- Worker loss: wait for lease expiry/release; replacement must have a higher
  fence and the old worker must be rejected.
- Unknown transaction outcome: reconcile by business identity before replay.
- Unknown ExternalEffect: keep query/manual-required without a real adapter.
- Poison Outbox delivery: dead-letter with durable error and receipt history.
- Database outage: use heartbeat/database-success staleness to infer unavailable.

After a failed diagnostic run, inspect `docker compose -p <project> ps`, service
logs, Worker Health, Runtime Job/Attempt/Lease/Event, Outbox delivery and metrics
projections. Never expose the full database URL when collecting evidence.

## Release evidence

Core OS CI emits SHA-bound artifacts for coverage, tests, migration, Compose,
query plans, Worker Fleet, Docker digest and environment metadata. Only after the
release-qualification artifact passes and every Required Job is green may an
annotated qualification tag be created on that same SHA.
