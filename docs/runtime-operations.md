# Runtime operations

## Local toolchain

Use Python 3.11 or newer; local and CI validation use Python 3.12. Install from the
extras declared in `pyproject.toml`:

```bash
uv venv --python 3.12
uv pip install -e '.[api,postgres,provider-openai,test,object,ingestion,industrial]'
npm --prefix web/admin ci
```

Configuration is read by `IndustrialSettings.from_env` from the environment and local
`.env` files. Start from `.env.example`. Never commit or print Provider, PostgreSQL or
object-store credentials.

## Start and inspect the stack

```bash
make authority-up
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/readiness
```

`/health` is process liveness. `/readiness` checks migration state, database pool and
connection budget, object storage, Provider route construction, Capability Pack
compilation/activation and registered operation definitions. A scripted `mock` route is
fixture-only. Do not reinterpret it as a real-Provider or production result.

The deployment in `compose.yml` includes migration, API, agent, chapter, content, source,
source-import, MKAOS, book, book-follow-up, outbox and maintenance processes. The checked
worker contract is `architecture/manifests/worker-manifest.yaml`.

Stop processes without deleting persistent data:

```bash
make authority-down
```

Volume deletion is not part of normal reset or test cleanup.

## Migrations

Inspect or apply the registered chain with:

```bash
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-migrate --status
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-migrate
```

The authoritative registry is `src/novel_forge/storage/migrations/versions/__init__.py`;
the head is also checked by `architecture/manifests/migration-manifest.yaml`. Applied IDs
live in `nf_schema_migrations`.

Do not edit an applied migration to repair live data. Respect its declared preflight,
forward-only, backup and downgrade properties. Run clean-install and upgrade tests before
using a new migration outside an isolated test database.

The offline snapshot importer is the separate `novel-forge-migrate` entry. Imported
records remain governed candidates; import does not infer approval or production
activation.

## Validation matrix

The only high-level backend engineering qualification entry is:

```bash
P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-p0 \
  make p0-backend-qualification
```

It executes this fail-fast chain:

```text
source-preflight
-> documentation-reality
-> static-and-manifests
-> pytest-backend
-> postgresql-start
-> migration-fresh
-> migration-compatibility
-> pytest-postgresql-integration
-> migration-head
-> query-plan-release
-> compose-runtime
-> resource-cleanup
-> evidence-finalization
```

The PostgreSQL database, Compose projects and evidence directory receive one run UUID.
Published service ports are Docker-assigned loopback ports. Cleanup is scoped to the
captured run labels and a PASS requires no remaining owned container, network, volume or
database service. The runner forbids Provider credentials, real-Provider routes, skipped
tests and incomplete declared collections.

The final JSON report binds the exact commit, source tree, manifest digests, migration
head, collection/JUnit artifacts and resolved dependency digest. Git SHA alone is not a
dependency lock. A local run does not close remote branch governance; without required
same-SHA CI evidence its state is `OPEN / NOT_CLOSED`.

The current accepted local report is retained under `architecture/evidence/` and is
referenced by `architecture/reality-evidence.json` with its content digest. The
Documentation Reality gate rejects missing, altered, stale or unreferenced retained
reports; detailed transient gate artifacts remain outside the repository.

These lower-level targets remain useful diagnostics, not alternate qualification
authorities:

```bash
make documentation-reality-check
make validate
make authority-test
make authority-compose-config-check
make authority-query-plan-release
```

The deterministic scale benchmark writes JSON only to an explicit path outside the
repository:

```bash
LONGFORM_RETRIEVAL_EVIDENCE_PATH=/tmp/longform-retrieval.json \
  make longform-retrieval-benchmark
```

It generates 50, 100, 300, 500 and 1,000-chapter profiles, with the largest corpus at
three million characters, and compares current round-zero retrieval with bounded query
expansion. Its report includes recall, leakage, candidate growth, Context tokens, round
and call bounds, latency observations and replay identity. This is synthetic retrieval
engineering evidence only; it does not establish real-Provider execution, narrative
quality, human evaluation, longitudinal production stability or production operation.

The complete PostgreSQL collection can be run only as a caller-owned diagnostic by
providing `NOVEL_FORGE_DATABASE_URL`, `NOVEL_FORGE_QUALIFICATION_DATABASE_NAME`, and an
absolute `NOVEL_FORGE_POSTGRES_EVIDENCE_DIR` to `make postgres-authority-test`. The
runner rejects fixed/shared database identity and repository-local evidence paths. This
diagnostic is not an alternate qualification authority; the P0 gate already executes
the complete architecture, unit, acceptance and PostgreSQL collections.

P0 evidence uses the typed `proof_scope` in the backend qualification manifest. A
passing exact-revision run proves the listed current backend capabilities at
`LOCAL_BACKEND_ENGINEERING`. It does not establish `ADMIN_UI_EXECUTION`,
`CREDENTIALED_PROVIDER_EXECUTION`, `HUMAN_EDITORIAL_EVIDENCE`,
`LONGITUDINAL_NARRATIVE_STABILITY`, or `PRODUCTION_OPERATION`. These are evidence
boundaries, not a product or narrative development sequence.

## Credentialed Provider qualification

Credentialed Provider qualification is intentionally separate from P0. The only live
runner is `make real-provider-qualification`; the D0 contract probe and worker remain
fixture-only and cannot send with a credential. The live runner requires a clean worktree,
an explicit expected SHA, caller-owned PostgreSQL and object storage, and evidence/runtime
paths outside the repository:

```bash
NOVEL_FORGE_DATABASE_URL='postgresql://...' \
NOVEL_FORGE_MINIO_ENDPOINT='127.0.0.1:9000' \
NOVEL_FORGE_REAL_PROVIDER_EXPECTED_SHA="$(git rev-parse HEAD)" \
NOVEL_FORGE_REAL_PROVIDER_RUNTIME_ROOT='/tmp/novel-forge-provider-runtime' \
NOVEL_FORGE_REAL_PROVIDER_EVIDENCE_PATH='/tmp/novel-forge-provider-evidence.json' \
make real-provider-qualification
```

The runner admits a D0 qualification Operation, creates one durable ExternalEffect intent,
executes one frozen Production Execution route, injects response loss after Provider
completion, reconciles from the persistent execution receipt, and requires one dispatch,
one receipt and one execution identity. Only `D0QualificationAuthority.execute_live` may
write `decision=QUALIFIED`. Usage, estimated cost with immutable pricing identity, latency,
route/model, prompt/instruction/Skill hashes and object-store evidence references are
retained. The result establishes Provider runtime qualification only; it does not establish
chapter acceptance, literary quality, human evidence, long-form stability or production
operation.

Every non-fixture Provider route also requires a route-bound admission contract before an
ExternalEffect can be created. Configure the actual model context limit, accounting
method, immutable evidence reference, framing allowance, safety margin and Source output
reserve through the corresponding `NOVEL_FORGE_PROVIDER_*` and
`NOVEL_FORGE_SOURCE_PROVIDER_OUTPUT_TOKEN_RESERVE` settings in `.env.example`. The
currently implemented OpenAI method is `OPENAI_UTF8_BYTES_UPPER_BOUND_V1`: UTF-8 input
bytes are treated as a conservative provider/model-bound input-token upper bound, and the
frozen evidence reference must justify the route's framing and limit assumptions. Generic
character estimates are never used for admission. Missing or unproven accounting fails
before Provider effect creation; Codex CLI remains fail-closed because its hidden request
framing cannot currently satisfy the complete-request identity contract.

## Failure and recovery procedure

1. Freeze the project, operation, attempt, lease, fence, RuntimeJob and ExternalEffect
   identities from PostgreSQL before acting.
2. Determine whether the external request definitely did not start, completed with a
   verified receipt, failed terminally, or has an ambiguous outcome.
3. Use the owning application or maintenance worker. Do not repair business state with
   ad-hoc SQL.
4. Preserve terminal attempts and effects. Resume or replace through new versioned
   records allowed by the owning recovery policy.
5. Re-query the complete state graph and verify audit/outbox/checkpoint convergence.

For Book Opening, use its progress query and recovery application. A process exit, an
expired lease, or a completed inner semantic operation alone is insufficient to decide
whether Provider work may be sent again.

For transaction errors, `DatabaseRetryClass.SAFE_RETRY` covers only explicitly safe
SQLSTATEs. `RECONCILIATION_REQUIRED` means the commit result may be unknown and must be
resolved from durable evidence before replay.

## Evidence interpretation

Local tests and Compose runs use fixtures unless a separately controlled route and live
evidence say otherwise. Keep these claims distinct:

- engineering qualification;
- migration and recovery qualification;
- real-Provider execution;
- human/editorial evidence;
- long-form stability;
- production operation.

The release-evidence builder in `src/novel_forge/tools/release_run_evidence.py` records
the current ceiling instead of upgrading one evidence class into another.
