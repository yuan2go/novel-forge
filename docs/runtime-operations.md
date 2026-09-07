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

The runner first records exact-identity credential and complete-request admission
preflight. A missing API key, an unsupported qualification transport and unproven Codex
request accounting are distinct blockers; a ChatGPT login is not a token-admission
contract. Blocked preflight writes evidence without creating runtime or database state.
It cannot confer current Provider or real-Chapter qualification.

After successful preflight, the supported runner admits a D0 qualification Operation, creates one durable ExternalEffect intent,
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

The ContextBundle estimate is only an assembly limit. Admission separately counts the
serialized system instruction, template, Skill, tool/schema material, Context projection,
knowledge projection, request framing, output reserve and safety margin against the
route/model context window. Book Opening additionally uses its frozen per-call token
policy as the stricter limit. The admitted exact or conservative total is the token amount
reserved in the Provider budget ledger; a ContextBundle that fits can therefore still be
rejected before any ExternalEffect exists.

## Narrative qualification and completion

The read-only narrative report consumes a real PostgreSQL Book scope and the exact tested
implementation identity. It has no fixture fallback:

```bash
PYTHONPATH=src .venv/bin/python -m novel_forge.tools.narrative_qualification \
  --repo-root . --project-id <project-id> --book-id <book-id> \
  --expected-sha <tested-sha> --implementation-tree-sha <sha256-identity> \
  --p0-report <canonical-p0-report> --output /tmp/narrative-qualification.json
```

Set `NOVEL_FORGE_DATABASE_URL` to the owned evidence database. Exit status 2 means the
written report is not proven or failed; it is not permission to ignore blockers. A fixture
Book retains fixture and historical receipt identity. Upper-layer failure prevents
downstream qualification; chapter count only describes the sample. Human Editorial waits
for independent human evidence, while Reader, Longitudinal and Production proof remain
separate. A real-Provider runtime probe alone cannot establish an accepted real chapter.

The trusted Book Completion API creates immutable cases, queries exact scoped cases and
records version-checked decisions. Assessment reads accepted history; it cannot complete
a Book cursor or repair Canon. A new case/version is required after changed source
evidence. Whole-book acceptance remains blocked until its native editorial authorization
contract is defined; generic Chapter/Arc preferences and AI review do not substitute.

## Narrative Reality and editorial control

The Book Authority API prefix is `/product/production/book-authority`.
Read `/runs/{book_run_id}/reality` for an exact accepted frontier, optionally with
`chapter_number`. `/reality/views/{view}` supports world, characters, epistemic,
reader, obligations and why views. Pages are bounded to 200 entries; Why queries
require an accepted `event_id` and expose unresolved references instead of inventing
causes. Reader response evidence remains advisory and separate from narrated Reader
Knowledge. `/reality/context` requires a declared role and token budget; character
roles also require an explicit character scope.

Native Book production generates and evaluates world candidates before Chapter planning.
Its resolved input snapshot must bind an approved compiled World Foundation and active
plans. The first Chapter uses those initial conditions without a synthetic acceptance.
`/runs/{book_run_id}/causal-plans` remains an explicitly manual proposal entry, with the
current Reality revision and active Creative Foundation version. Its result is planning
input; a stale revision cannot mutate accepted state.

An authorized production smoke uses the native Book/Chapter workers through
`scripts/run_world_production_smoke.py`. It consumes an approved input snapshot produced
by Book opening/input resolution, whose Foundation, intent, policies and initial plans
must already exist in the isolated PostgreSQL database. The command has no candidate,
requirement, score or prose override. A new evidence directory is required on each
invocation; keep the same run key and input snapshot when recovering.

```bash
source config/provider/world-production-smoke.env.example
PYTHONPATH=src .venv/bin/python scripts/run_world_production_smoke.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --input-snapshot-id "$NOVEL_FORGE_SMOKE_INPUT_SNAPSHOT_ID" \
  --run-key "$NOVEL_FORGE_SMOKE_RUN_KEY" \
  --root "$NOVEL_FORGE_SMOKE_RUNTIME_ROOT" \
  --evidence-dir "$NOVEL_FORGE_SMOKE_EVIDENCE_DIR" --chapters 3 --execute
```

The example requires existing reviewed route, credential, budget, Principal and input
configuration; it supplies no spending authorization or credential. Missing configuration
fails before execution. The runner requires a disposable database name and controlled
runtime, rejects scripted routes, respects pending approvals and bounded tick/time limits,
and does not approve its own changes. Chapter count is only the experiment bound.

The same command exercises Creative Memo, directed revision and grounded Canon on the
current Chapter route. `NOVEL_FORGE_MEMO_PROVIDER`/`NOVEL_FORGE_MEMO_MODEL` and
`NOVEL_FORGE_CANON_SUPPORT_PROVIDER`/`NOVEL_FORGE_CANON_SUPPORT_MODEL` select their
routes; if omitted they inherit the explicitly configured Review route. They use the
existing Provider admission, token and cost limits. Memo has the Planning capability's
60-second operation bound; Canon support uses the Canon capability's frozen bound.

The export also writes `chapter-workspaces.json`, including candidate prose, diagnoses,
claim support, accepted state references, attempt errors and receipt/cost references.
The live read is `GET /product/production/chapter-authority/run` with `project_id`,
`root_operation_id` and `include_workspace=true` under existing query permission.
For a short comparison, retain a baseline export from a separately frozen implementation
and use the same approved input and model settings in an isolated new run. Preserve
failed runs; these exports do not establish independent literary or human qualification.

`events.jsonl` retains tick and failure results; the export includes exact world source,
generation/evaluation artifacts, execution recovery sessions, request admission,
model/usage/cost evidence and accepted Realities. Inspect that original preparation
steps continued across chapters and a historical background event was later disclosed to
only its authorized audiences. A model may produce NO_OP or a blocked plan: reaching a
sample size alone does not prove these behaviors or confer Provider, editorial,
longitudinal or production qualification. Keep the database and failed export when
reconciliation or a further evidence page is required.

Configure the versioned Book Control policy through `/policies/book-control`, then
inspect `/runs/{book_run_id}/control-readiness`. A pending decision identifies the
exact boundary, subject and frozen policy. Operator decisions enter through
`/runs/{book_run_id}/control-decisions`; scheduler workers cannot approve themselves.
Resume the existing production job after approval. Decisions do not waive quality,
Canon reconciliation or acceptance invariants.

Chapter workflow contract 3.4.1 and Capability Pack 2.3.1 require structured
realization slots and the current quality dimensions. Published text-only Scene beats
use an explicitly marked frozen representation adapter; their source digest and
ordinal identities remain replayable. Scene v2 continues to require typed Beat IDs.
Unaccepted older model-backed Chapter contracts fail with
`CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED`; they need a new Chapter command on the current contract with grounded evidence. Preserve their frozen inputs and confirmed effects for audit.
This includes 3.4.0 payoff payloads: 3.4.1 binds prose payoff references in Authority,
so prior Provider-authored IDs are not silently reinterpreted as verified citations.
Already accepted history is replayed as history, without fabricated grounding evidence.
Other frozen Authority operations keep their existing `AUTHORITY_HANDLER_CONTRACT_STALE`
guard and require their matching release for recovery.

Chapter workers discover pending roots on every poll, including after process takeover.
ChapterGroup records changing child status while waiting and freezes its reconciliation
step only when the child succeeds. Recovery consumes confirmed Memo and Canon support
receipts under the original reservation policy, then completes the missing domain commit.

Provider Context projection rejects an eligible segment count or relevant fact count
that exceeds its declared budget. A passing Context correctness receipt does not permit
the renderer to discard those facts. Rebuild the governed selection before dispatch;
the limit error is not permission to expand the budget or retry a different payload
under the same frozen operation.

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

When an Opening node returns its committed result and a late heartbeat observes the
released lease, the worker verifies the exact node receipt before preserving that
result. A lost completion response still resolves from the receipt as a replay.

Provider retry first reloads any existing ExternalEffect intent and reuses its frozen
request/admission identity. A historical remote intent that predates complete admission
is not upgraded in place or reinterpreted with the current meter; dispatch remains
fail-closed and recovery follows the owning effect policy.

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
