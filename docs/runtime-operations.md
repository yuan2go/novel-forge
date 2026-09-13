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

The Source convergence segment includes two distinct `0121` entries connected by
declared parents. Use full identities and the registry's parent chain, not numeric
filename prefixes, to determine order.

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

## Corpus metadata commands

The existing Authority API accepts `POST /product/source-governance/corpus/commands`.
The envelope requires `project_id`, `workspace_id`, `idempotency_key` and a typed `action`;
the trusted Principal supplies the actor. The existing Project/Workspace must be active.
`source.authority.execute` permits writes and `source.authority.query` permits reads.
Run migrations, the Authority API and the existing Source worker using the same database
and release identity. No Provider or download adapter is invoked by these commands.

Classical analysis validates its frozen sample budget when analysis needs that budget;
constructing the Source Import query/metadata runtime does not require a large model
context. An insufficient analysis route still fails closed at the sampling boundary.
The existing Source integration fixture explicitly supplies its scripted model's context
limit; it does not establish a real Provider's capacity.

```bash
PYTHONPATH=src .venv/bin/python -m novel_forge.workers.source_authority
```

Actions, in dependency order:

| Action | Frozen input | Result |
| --- | --- | --- |
| `register_source` | `source_kind`, `external_identity`, immutable `purpose` | `source_id` |
| `declare_rights` | `source_id`, `previous_rights_id`, dataset/underlying-work rights, purposes, restrictions, evidence and scope | `rights_id` |
| `freeze_snapshot` | source, rights, previous snapshot, DatasetManifest and acquisition identity | `snapshot_id` |
| `import_batch` | snapshot, stable `batch_key`, 1–100 book/edition metadata entries | existing import job, Edition IDs, admission decisions and allowed memberships |
| `evaluate_admission` | exact Edition ID and requested purpose | immutable ALLOW/DENY evidence |
| `retire_source` | source and reason | preserved lineage plus retirement |

For example, after setting the existing project/workspace IDs and API origin:

```bash
export NF_CORPUS_API=http://127.0.0.1:8000
curl --fail-with-body "$NF_CORPUS_API/product/source-governance/corpus/commands" \
  -H 'Content-Type: application/json' \
  --data "{\"project_id\":\"$NF_PROJECT_ID\",\"workspace_id\":\"$NF_WORKSPACE_ID\",\"idempotency_key\":\"catalog-register-1\",\"action\":{\"action\":\"register_source\",\"source_kind\":\"operator_manifest\",\"external_identity\":\"catalog:research-1\",\"purpose\":\"RESEARCH\"}}"
```

Poll `GET /product/source-governance/corpus/operations/{operation_id}?project_id=...`;
only `SUCCEEDED` establishes a complete result. The OpenAPI discriminated action schema
defines required fields. A rights declaration needs independent `dataset_license`,
`underlying_rights`, `underlying_license` when LICENSED, `allowed_purposes`,
`denied_purposes`, `restrictions`, `evidence_refs`, `copyright_boundary`, and
`scope=ALL_WORKS_IN_SNAPSHOT` or exact `SELECTED_WORKS` grants. Use UNKNOWN rather than invent underlying rights.
`previous_rights_id`/`previous_snapshot_id` is null only for the first revision.

The manifest supplies `origin_uri`, `external_version`, `format`, `checksum`,
`adapter_profile`, `adapter_contract_version` and optional metadata. Acquisition supplies
`locator`, a timezone-aware `acquired_at`, `receipt_ref` and matching `checksum`;
an existing Git acquisition may also bind `repository_snapshot_asset_version_id`.
Each edition entry supplies `external_work_id`, `external_edition_id`, `title`, `checksum`,
`locator` and optional metadata. These are metadata declarations, not uploaded novel text.

Inspect `GET /product/source-governance/corpus/imports/{import_job_id}` for the frozen
input, exact definition, attempt/failure history, effective status and result. The existing
`GET /product/source-imports/{import_job_id}` also resolves foundation jobs.
`POST /product/source-imports/{import_job_id}/resume?project_id=...` identifies resumable
work without creating new Provider work; the Source worker resumes it. Restarting the
worker reuses committed output or acquires an expired lease. Terminal failures/cancellation
are not reopened: corrected input uses a new batch key and reuses unchanged Editions.
An import can finish its Operation successfully while its membership outcome is BLOCKED;
inspect the per-Edition admission reasons, not just Operation status.

`GET /product/source-governance/corpus/lineage/{edition_id}` returns exact source,
snapshot, rights, work identity, Edition and admission/membership evidence. Lists use
`GET /product/source-governance/corpus/records/{kind}` with `project_id`, `parent_id`,
`after` and `limit` (1–100). Parent is source for rights/snapshots/book identities, snapshot
for Editions and Edition for admissions/memberships. `after` is the last record's stable
ID. Continue paging admission history when a lineage response reaches its 100-record cap.

## Corpus content ingestion

Install `.[industrial,ingestion]` in the local virtual environment and migrate using
`novel-forge authority-migrate`. Use the existing active Project/Workspace and trusted
Principal (`source.authority.execute` and `source.authority.query`). The API and workers
must share the database, release identity, object store and explicit local roots. Keep
cache/object storage outside Git and production works out of test databases.

```bash
export NOVEL_FORGE_CORPUS_CACHE_ROOT="$HOME/Library/Caches/NovelForge/corpus"
export NOVEL_FORGE_CORPUS_LOCAL_ROOTS="[\"$PWD/examples/sample_inputs\"]"
# Use an existing isolated project/workspace; these are the only business IDs needed.
novel-forge corpus preview --project-id "$NF_PROJECT_ID" --workspace-id "$NF_WORKSPACE_ID" \
  --manifest config/corpus/local-original.json --run-key local-preview-1
novel-forge corpus run --project-id "$NF_PROJECT_ID" --job-id "$NF_PREVIEW_JOB_ID"
novel-forge corpus import --project-id "$NF_PROJECT_ID" --workspace-id "$NF_WORKSPACE_ID" \
  --manifest config/corpus/local-original.json --run-key local-import-1
# Copy import_job_id from the JSON response; run executes the same native worker handlers.
novel-forge corpus run --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID" --max-stages 20
novel-forge corpus status --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID"
novel-forge corpus lineage --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID" --limit 20
novel-forge corpus pause --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID" --reason 'operator review'
novel-forge corpus resume --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID"
# Cancellation is a separate irreversible execution decision; it preserves imported facts.
novel-forge corpus cancel --project-id "$NF_PROJECT_ID" --job-id "$NF_IMPORT_JOB_ID" --reason 'stop remaining work'
```

The continuously running alternative is `python -m novel_forge.workers.source_import`.
HTTP admission is `POST /product/source-imports/corpus` (or `/corpus/preview`) with
`project_id`, `workspace_id`, `run_key`, `manifest` and optional frozen
`intelligence_policy`. Existing job, work and resume queries apply;
`GET /product/source-imports/{import_job_id}/corpus-lineage` pages Editions and exact
bridges. Pause/resume/cancel use the existing Corpus `control_import` action with the
observed `expected_status`, preventing an outdated control decision from overwriting one.

Preview lists bounded local files or accesses remote metadata, without downloading selected
content, calling analysis models or approving knowledge. Git metadata discovery may fetch
Git objects needed to resolve the fixed tree. Import fetches actual bytes. Inspect
`content_verified`, `actual_bytes`, per-work failures and `analysis_scheduled`; metadata
or Operation success alone is not knowledge availability. An interruption is resumed with
the same job; a changed manifest/parser/rights requires a new run key. Unknown Effects need
receipt reconciliation, and final failures are not reopened. Local spool receipts and
objects remain referenced evidence, not disposable caches while their snapshots are used.

| Configuration | Source/format | Boundaries |
| --- | --- | --- |
| `config/corpus/local-original.json` | repository-authored Chinese JSONL excerpt | two explicit chapter records; no model call |
| `config/corpus/github-fixed.json` | fixed char-rnn commit, TXT | verified byte digest; research only; no underlying rights inferred from repository license |
| `config/corpus/huggingface-fixed.json` | fixed testing_self_instruct_small commit, Parquet | small transport/mapping example, not a novel corpus; Benchmark only; the mapped prompt hash is the explicit record identity |
| `config/corpus/internet-archive.json` | explicit Alice item/file, TXT | preview must verify availability; checksum/metadata drift checked during import; no inferred production grant |

Remote examples retain UNKNOWN underlying rights and permit only bounded local processing.
They do not establish a license to analyze or generate. HF credentials may be supplied via
`HF_TOKEN`; never put them in the manifest/URL. A gated or missing resource stays blocked.
The HTTPS adapter only accepts public DNS addresses on its allowlist; proxy/synthetic DNS
that maps a public service into private/reserved addresses must be corrected by the operator,
not bypassed by disabling SSRF checks.

To opt into analysis, declare the corresponding explicit underlying-work and use rights,
set `analyze=true`, and configure the existing governed Source model route, Capability Pack,
Principal and per-run call/token/cost policy. This can incur costs and is not authorized by
an example file. MKAOS approval is a later explicit command, never an import side effect.
A scripted engineering run may prove Candidate/Decision/Pack connectivity; its Cards cannot
be promoted past the existing fixture ceiling into production Planning.

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
preflight. A missing API key, an unsupported qualification transport and unproven request
accounting are distinct blockers; a ChatGPT login alone is not a token-admission
contract. Blocked preflight writes evidence without creating runtime or database state.
It cannot confer current Provider or real-Chapter qualification. The dedicated
qualification runner remains a priced API-key path; account-entitlement Codex validation
uses the ordinary production Gateway and records its narrower proof scope.

After successful preflight, the supported runner admits a D0 qualification Operation, creates one durable ExternalEffect intent,
executes one frozen Production Execution route, injects response loss after Provider
completion, reconciles from the persistent execution receipt, and requires one dispatch,
one receipt and one execution identity. Only `D0QualificationAuthority.execute_live` may
write `decision=QUALIFIED`. Usage, estimated cost with immutable pricing identity, latency,
route/model, prompt/instruction/Skill hashes and object-store evidence references are
retained. The result establishes Provider runtime qualification only; it does not establish
chapter acceptance, literary quality, human evidence, long-form stability or production
operation.

The default D0 `model.retrieval` scenario qualifies only that declared capability. Source
production knowledge approval requires a separate exact `mkaos.knowledge.extract`,
`mkaos.rule.extract` or `mkaos.template.extract` scenario through the same runner and
Gateway; it cannot inherit retrieval qualification. D0 reports are evidence-only
`INELIGIBLE` assets. A completed report Operation does not turn a blocked fixture report
into `QUALIFIED` or make the report creative context. The Source procedure below reuses
one native extraction stage and its original call/token/cost authorization.

Every non-fixture Provider route also requires a route-bound admission contract before an
ExternalEffect can be created. Configure the actual model context limit, accounting
method, immutable evidence reference, framing allowance, safety margin and Source output
reserve through the corresponding `NOVEL_FORGE_PROVIDER_*` and
`NOVEL_FORGE_SOURCE_PROVIDER_OUTPUT_TOKEN_RESERVE` settings in `.env.example`. The
implemented OpenAI method is `OPENAI_UTF8_BYTES_UPPER_BOUND_V1`: UTF-8 input
bytes are treated as a conservative provider/model-bound input-token upper bound, and the
frozen evidence reference must justify the route's framing and limit assumptions. Generic
character estimates are never used for admission. Missing or unproven accounting fails
before Provider effect creation.

The controlled Codex account-entitlement route may instead use
`CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1`. This is explicitly an
`APPLICATION_VISIBLE_UPPER_BOUND`: it bounds the serialized stdin Novel Forge passes to
the CLI, including visible instruction, schema and context, plus the configured reserve
and margin. It does not prove or precisely limit hidden CLI framing, injected provider
context, or the final remote request. The route therefore freezes the absolute executable,
binary hash, observed CLI version, explicit `NOVEL_FORGE_CODEX_HOME`,
account/configuration references, model and reasoning setting, and reconciles observable terminal usage after execution. Reports must preserve
that proof ceiling rather than describing the post-call usage as a precise pre-call hard
limit.

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

### Creating the inputs through native Formation

`scripts.run_creation_synthesis` coordinates existing Content, Story Formation,
Book Opening and Book Supervisor commands. `--initialize --workspace-id ...` registers
an isolated Project and Book through their existing Commands, idempotently. Existing
Books must carry the identical frozen pilot configuration. PostgreSQL must be migrated
through `0120`, with the normal
configured operator/worker permissions. The approved current Planning Capability Pack
must include the six Foundation generation capabilities and their qualification Skills;
the Chapter pack must include Memo, Review/Revision and Canon support. It does not seed
qualified story assets or call a Provider SDK directly.

BookDesign v5 semantic evaluation resolves the exact six active Foundation bindings,
including native `planning_generation_candidate` assets. Both dependency resolution and
Provider projection check their generator role, project, Book and candidate contract;
qualification verdicts remain provenance rather than evaluator input. The aggregate
projection has a `CONFIGURABLE_POLICY` limit of 131,072 serialized characters. Other
evaluation projections retain 65,536 characters. These bounds do not grant tokens or
calls: frozen route capacity and native budget admission still apply before dispatch.

The `short-arc-*` files remain the small English engineering smoke. The separate
`chinese-pilot-*` files freeze an original three-chapter Chinese Arc, limited third-person
POV, character voice constraints, information asymmetry, a costly choice and setup/payoff.
Each chapter requires 2000–3500 Han characters. `HAN_CHARACTERS_V1` counts Unicode
CJK unified/compatibility ideographs, including supplementary planes; punctuation,
Latin letters, numbers and whitespace do not count. This deterministic gate precedes
model evidence and cannot be waived by a high model score. Profiles without an explicit
unit retain their historical contract. These files contain author intent and policies,
not prequalified Foundation or chapter assets.

The checked-in files are complete inputs. Validate them without PostgreSQL or
paid model access:

```bash
PYTHONPATH=src .venv/bin/python -m scripts.run_creation_synthesis \
  --brief config/production/chinese-pilot-brief.json \
  --policy config/production/chinese-pilot-creation.json \
  --formation-policy config/production/chinese-pilot-formation.json \
  --project-id example-project --book-id example-book \
  --root /tmp/novel-creation-runtime --run-key creation-control \
  --evidence-dir /tmp/novel-creation-config-check
```

For a credentialed run, first load an explicitly authorized route, credentials,
Principals and spending caps. Credential availability alone does not authorize spending.
`config/provider/creation-synthesis.env.example` asserts required settings and supplies
neither credentials nor budget amounts. The chapter count is a bounded sample. Only the retained English `short-arc-*`
configuration has small engineering smoke limits; the Chinese pilot retains its
2000–3500 Han-character requirement. Edit and freeze the policies before execution if a
different bounded sample is authorized.

```bash
source config/provider/creation-synthesis.env.example
PYTHONPATH=src .venv/bin/python -m scripts.run_creation_synthesis \
  --brief config/production/chinese-pilot-brief.json \
  --policy config/production/chinese-pilot-creation.json \
  --formation-policy config/production/chinese-pilot-formation.json \
  --project-id "$NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE" \
  --book-id "$NOVEL_FORGE_CREATION_BOOK_ID" \
  --initialize --workspace-id "$NOVEL_FORGE_CREATION_WORKSPACE_ID" \
  --authorized-total-usd "$NOVEL_FORGE_CREATION_AUTHORIZED_TOTAL_USD" \
  --authorization-ref "$NOVEL_FORGE_CREATION_AUTHORIZATION_REF" \
  --root "$NOVEL_FORGE_CREATION_RUNTIME_ROOT" \
  --run-key "$NOVEL_FORGE_CREATION_RUN_KEY" \
  --evidence-dir "$NOVEL_FORGE_CREATION_EVIDENCE_DIR" \
  --expected-sha "$(git rev-parse HEAD)" --max-seconds 1800 --execute
```

Each invocation requires a new evidence directory. On interruption, keep the runtime,
database, run key, model routes, authorization and policies; rerun the same command
with a new evidence directory. Formation and Opening are located by their native
idempotency keys; Book Run start reuses its frozen snapshot. An optional
`--resume-formation-run-id` must match that key. Book runtime policy freezes the brief
hash, creation/Formation policy, implementation, model and routing contracts, Prompt/Skill
hashes, token accounting and budgets. Changed input is rejected before generation.
The explicit total USD cap uses the existing atomic `project_total` reservation dimension,
including settled and unknown effects across days and all books in the dedicated project.
Baseline, revisions and retries share this cap; a lower configured cap is never raised. Failed/approval-waiting Formation uses its
existing resume/approval commands before the driver continues; a live lease is not
stolen. Confirmed generation/evaluation receipts are reused, including evaluation whose
candidate has subsequently been approved. New generation under a changed source uses a
new run; old terminal tasks and accepted history are not reopened.
For `EXECUTION_CONTRACT_FROZEN_CONFLICT` before the first Provider dispatch, inspect the
retained Effect and release its reservation only after the native ledger proves the
result is known not to have been dispatched. Request native cancellation and resolve it
with `never_dispatched_effects`; the Kernel requires every Effect to have zero dispatch
records and every reservation to be `RELEASED`. Install the repaired release and approve
its exact Capability Pack compilation with duties separation preserved. The existing
trusted local operator then registers a successor at
`POST /product/production/book-authority/books/{book_id}/planning-generations/{operation_id}/runtime-continuation`,
passing `project_id`, the cancelled source's `expected_source_version`,
`decision_evidence` with the actual `authorization_ref`, `reason` and
`authorized_reasoning_effort`, and `trace_id`/`correlation_id`. Reasoning is explicitly
authorized by the current decision; missing fields in the old pre-dispatch request
are not treated as historical proof. The original Book runtime policy binds the
account, backend and CLI configuration. Registration binds the unchanged story task to the exact
new runtime and permits at most two causal successors. Resume the same Formation with
its observed CAS version; its original node follows the registered successor. Ordinary
retries still enforce the old frozen runtime, and dispatched or unknown outcomes do not
qualify for this path. A budget reallocation remains a separate native policy append;
preserve the prior frozen driver configuration and continue through native step commands.

Exports include Foundation candidates/diagnoses, model/usage/cost records, request
admission and recovery artifacts even if Formation fails before Book production.
The project-scoped export is bounded; use a dedicated isolated project, and retain
PostgreSQL for paged export if a bound is reached. Completed chapters include their
actual text, Memo, edits, grounding and exact next-input sources.
Export reads immutable versions, including candidates with no current locator and
superseded outputs. A failed export returns a nonzero exit code and retains the partial
files and error; it does not report a complete evidence package.

Preserve a baseline export from an isolated frozen old implementation. After both runs
exist, compare actual accepted manuscripts without adding another product pipeline:

```bash
PYTHONPATH=src .venv/bin/python -m scripts.compare_creation_exports \
  "$NOVEL_FORGE_BASELINE_EXPORT" "$NOVEL_FORGE_CREATION_EVIDENCE_DIR" \
  --output "$NOVEL_FORGE_COMPARISON_DIR"
```

The workspace and comparer follow committed Book Acceptance → immutable ChapterOutcome
→ exact selected Candidate, Quality, Review, Canon and Context → Memo. They verify
project/book/chapter identity, content and prose hashes, plan lineage and Grounding.
Historical Quality targets, original drafts and discarded revisions remain available.
Missing/conflicting bindings produce per-chapter errors; partial exports retain successful
chapters and return nonzero. `accepted-chapter-N.txt` is extracted from that binding.
The comparer exports prose and unified diffs,
Memo/diagnoses/support evidence and records plan hashes and accepted boundaries.
Comparison remains NONCOMPARABLE unless frozen inputs and model settings are independently
matched; equal plan hashes alone do not establish creative improvement. Costs remain per-currency estimates from uniquely identified effect receipts,
not invoices. The explicit unavailable list includes legacy operation-only receipts;
when nonempty, reported sums are partial and must not be treated as the run total. Independent editorial judgments are left awaiting evidence; model scores
are not converted into accuracy or human opinions. Missing authorized budget leaves
the real experiment NOT_RUN while configuration and scripted wiring remain runnable.

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

## Corpus structure, review and reprocessing

Install the `ingestion` extra and use the same local object store, cache root, local-root
allowlist and Source principal described above. Deterministic processing requires no model.
Start with `config/corpus/chinese-longform-local.json`; its supplied small original fixture
is only a control-flow example. Replace the source with a lawfully acquired local book:

```bash
novel-forge corpus import --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
  --manifest config/corpus/chinese-longform-local.json --source "$LOCAL_BOOK" --run-key first-parse
novel-forge corpus run --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus lineage --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus inspect --project-id "$PROJECT" --edition-id "$EDITION"
novel-forge corpus discover --project-id "$PROJECT" --processing-id "$PROCESSING" --limit 20
novel-forge corpus compare --project-id "$PROJECT" --processing-id "$PROCESSING" --compare-to "$OTHER_PROCESSING"
```

The import response supplies JOB; lineage supplies Edition and Bridge identities; inspect
supplies processing/issue/review identities. `review` accepts `--decision review.json`,
`--workspace-id` and a stable `--run-key`. For example, a scoped decision document is:

```json
{"action":"review_processing","processing_id":"<inspect.processing_id>","previous_id":null,
 "decisions":[{"issue_id":"<inspect.assessment.issues[0].issue_id>","resolution":"MARK_NON_BODY",
 "reason":"Exact source framing inspected"}],"reason":"Preserve source; exclude framing from analysis"}
```

CONFIRM_EXCERPT handles missing selected coverage; CONFIRM_BOUNDARY handles a short unit;
REJECT_CORRUPT keeps analysis blocked. Missing raw evidence and rights cannot be waived.
A parser profile may supply `normalization.boundaries` with exact path, checksum, start/end
raw byte offsets, title, kind and evidence. It must cover the entire selected input.
Export the `profile` object from inspect, edit its versioned normalization rules, and run:

```bash
novel-forge corpus reprocess --project-id "$PROJECT" --edition-id "$EDITION" \
  --manifest parser.json --run-key reviewed-parser
novel-forge corpus run --project-id "$PROJECT" --job-id "$REPROCESS_JOB"
```

No downloader runs on this path. Pause/resume/cancel/status use the same job commands.
Same-key requests preserve frozen input; changed profiles need a new key. A stale parent or changed review
fails explicitly at both preparation and atomic publication and requires inspecting/replanning against the current processing revision.
`equivalence --decision pair.json` accepts action `decide_equivalence`, exact left_id/right_id,
previous_id, decision ACCEPT/REJECT/REVOKE, evidence_refs and reason. Querying a pair returns
its latest decision; it does not select a generation-authorized canonical representative.
All responses are JSON; retain these and source receipts outside Git for audit.


## Canonical works and curated analysis

New imports use parser v3 (`config/corpus/chinese-longform-local.json`). For an old Edition,
inspect its frozen `profile`, change parser version to `corpus-parser.v3` and normalization
version to `chinese-longform.v2`, then use `reprocess`. Acquisition bytes are reused; do not
invent another source. Failed terminal jobs remain terminal: a corrected input requires a
new run key. Store operator exports outside Git.

`compare` and `discover` return bounded JSON pages. Pass their `next_cursor` to `--after`;
comparison cursors are inside `comparison`. A changed target/review/catalog returns a stale
cursor error. `discover --historical` explicitly includes historical processing. Scores
and a page of candidates are not global Top K or an automatic equivalence decision.

Scoped review adds `CONFIRM_LEGITIMATE_REPETITION`, `CONFIRM_TOC_VARIANT` and
`ANNOTATE_TOC_DIFFERENCE`; each requires `classification`, `evidence_refs` and a reason.
The first two apply only to their specific located issues. Missing chapter content cannot
be accepted as a title variant. Annotation retains blocking uncertainty. Excluding a
verified title-only duplicate with `MARK_NON_BODY` requires reprocessing and retains raw
bytes; do not exclude a spine-leading prose continuation as publisher framing.

This native CLI sequence derives internal identities from command results. It assumes an
already imported, inspected Edition whose current rights explicitly permit SOURCE_ANALYSIS;
the default local-processing example intentionally does not grant that use. `jq` is used
only to construct typed operator requests. Set the title/evidence to the actual inspected
source; these are operator identity decisions, not model inferences.

```bash
novel-forge corpus inspect --project-id "$PROJECT" --edition-id "$EDITION" > /tmp/processing.json
jq --arg title "$TITLE" --arg evidence "$SOURCE_EVIDENCE" '
 {action:"resolve_canonical_works", reason:"Explicit source identity resolution",
  changes:[{work_key:.edition_id,title:$title,language:"zh",metadata_evidence:[$evidence],
  members:[{processing_id:.processing_id,relation:"SAME_WORK",evidence_refs:[$evidence]}]}]}'  /tmp/processing.json > /tmp/work-decision.json
novel-forge corpus resolve-work --project-id "$PROJECT" --workspace-id "$WORKSPACE"  --decision /tmp/work-decision.json --run-key "$RUN-work" > /tmp/work-result.json
jq -n --slurpfile work /tmp/work-result.json '{action:"revise_curated_corpus",
 corpus_key:"selected-research",title:"Inspected research subset",purpose:"RESEARCH",
 filters:{work_ids:[$work[0].revisions[0].work_id]},reason:"Inspect exact members"}' > /tmp/curate.json
novel-forge corpus curate --project-id "$PROJECT" --workspace-id "$WORKSPACE"  --decision /tmp/curate.json --run-key "$RUN-candidates" > /tmp/candidates.json
novel-forge corpus curated --project-id "$PROJECT"  --corpus-id "$(jq -r .corpus_id /tmp/candidates.json)"
```

After examining availability, explicitly choose a member; a blocked member fails freeze.
Keep unselected members in the candidate manifest rather than silently skipping them.

```bash
jq --slurpfile c /tmp/candidates.json --slurpfile p /tmp/processing.json  --arg evidence "$SELECTION_EVIDENCE" '. + {previous_id:$c[0].revision_id,state:"FROZEN",
 choices:[{processing_id:$p[0].processing_id,selected:true,reason:"Scoped selection reviewed",
 evidence_refs:[$evidence]}]}' /tmp/curate.json > /tmp/freeze.json
novel-forge corpus curate --project-id "$PROJECT" --workspace-id "$WORKSPACE"  --decision /tmp/freeze.json --run-key "$RUN-freeze" > /tmp/frozen.json
novel-forge corpus analyze --project-id "$PROJECT"  --revision-id "$(jq -r .revision_id /tmp/frozen.json)" --run-key "$RUN-analysis"  --limit 1 --max-calls "$AUTHORIZED_CALLS" --max-tokens "$AUTHORIZED_TOKENS"  --authorization-ref "$AUTHORIZATION_REF" > /tmp/analysis-job.json
novel-forge corpus run --project-id "$PROJECT"  --job-id "$(jq -r .import_job_id /tmp/analysis-job.json)" --max-stages 50
```

The analysis commands require explicitly authorized model execution and current Provider
configuration; credentials/subscriptions alone are insufficient. Mock transport proves
engineering only. Inspect `status`, `/work` and receipts for each stage and failure;
`SOURCE_ANALYSIS_SCHEDULED` does not mean analysis or MKAOS approval succeeded. Curated runs
retain per-member terminal failures while attempting other eligible members. Same-key
requests replay the original job; changing budget/policy/members under that key is rejected.
Current selection changes stop new worker/Provider execution; committed results remain
replayable. Use `pause`, `resume`, `cancel` and `run --job-id` on the original job.

HTTP equivalents are Source corpus commands (`resolve_canonical_works`, `declare_relation`,
`revise_curated_corpus`), GET `/product/source-imports/corpus/catalog/{work|curated}/{identity}`
with project and optional `revision=true`, and POST `/product/source-imports/corpus/analyze`.
Work and curated corrections use exact `previous_id`; inspect before submitting another
revision. To split/merge groups, submit all affected complete memberships in one command.
Retired groups keep their historical revisions. Rights, Benchmark labels, processing issues
and knowledge approvals remain independent for every source Edition.


## Curated analysis operations

Use the same database, object store, local roots and trusted Source principal as ingestion.
The analysis request freezes a selected curated revision and the existing project ledger
ceiling. `--manifest` on `analyze` optionally supplies a bounded `SourceIntelligencePolicy`
JSON; it does not authorize a model or change the given call/token allowance.

```bash
novel-forge corpus curated --project-id "$PROJECT" --revision-id "$CURATED_REVISION"
novel-forge corpus analyze --project-id "$PROJECT" --revision-id "$CURATED_REVISION" \
  --run-key "$ANALYSIS_KEY" --limit 2 --max-calls "$AUTHORIZED_CALLS" \
  --max-tokens "$AUTHORIZED_TOKENS" --authorization-ref "$AUTHORIZATION_REF"
novel-forge corpus status --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus run --project-id "$PROJECT" --job-id "$JOB" --max-stages 10
novel-forge corpus pause --project-id "$PROJECT" --job-id "$JOB" --reason 'inspect remaining members'
novel-forge corpus resume --project-id "$PROJECT" --job-id "$JOB"
novel-forge corpus results --project-id "$PROJECT" --job-id "$JOB" --limit 20
novel-forge corpus results --project-id "$PROJECT" --job-id "$JOB" --format text
novel-forge corpus lineage --project-id "$PROJECT" --job-id "$JOB" --limit 20
novel-forge corpus cancel --project-id "$PROJECT" --job-id "$JOB" --reason 'stop remaining stages'
```

`run` exit 0 means execution completed, 2 means a bounded/in-progress/paused or leased
stop, and 3 means partial, blocked, failed or cancelled work. CLI errors use exit 1.
Inspect `stop_reason`, `remaining_stages` and `next_action`; completing model stages does
not approve knowledge. A persisted failed stage is not retried repeatedly within one
invocation. Subsequent recovery uses the same Kernel history and frozen budget.
`results` supports `--processing-id`, `--after` and `--limit`; restart pagination from the
beginning after new stages have been expanded. It excludes raw source/output bodies.
HTTP queries are `GET /product/source-imports/{job}/analysis-results` with `project_id`,
`processing_id`, `after`, `limit`; status and corpus-lineage retain their existing routes.
Control uses the existing Source `control_import` command. Missing frozen lineage is an
explicit query error, never an inferred Research grant.

For acquired EPUB, start with `config/corpus/epub-logical-chapters.json`, retain the
original parser's `constants` identifying the work, and append exact continuation evidence
only when a TOC interval or title awaiting its body is insufficient. Each
`epub_continuations` entry requires `left_href`, `right_href`, the EPUB `checksum` and an
`evidence` locator; the resources must be adjacent in the frozen spine. No default
concatenation of unheaded text is enabled.

```bash
novel-forge corpus reprocess --project-id "$PROJECT" --edition-id "$EDITION" \
  --manifest "$EXACT_EPUB_PROFILE" --run-key "$REPROCESS_KEY"
novel-forge corpus run --project-id "$PROJECT" --job-id "$REPROCESS_JOB"
novel-forge corpus inspect --project-id "$PROJECT" --edition-id "$EDITION"
```

Inspect unresolved issues, use the existing scoped `review` command, and reprocess its exact
input to apply exclusions. Updating a Processing, review, canonical membership or relation
requires re-inspection and a new explicit curated freeze before new analysis. Neither
rights nor MKAOS approval transfers through a work group or identical text.

## Bounded chapter deconstruction

For each currently selected curated member, inspect exact unit IDs and create a range.
This example selects five available chapters. A multi-member selection needs one scope per
member; the service verifies continuity, version, rights, review and all input bounds.

```bash
novel-forge corpus chapters --project-id "$PROJECT" --processing-id "$PROCESSING" --limit 100 > units.json
python3 - "$PROCESSING" <<'PY'
import json, sys
units = [u for u in json.load(open("units.json"))["units"] if u["kind"] == "chapter" and u["status"] == "AVAILABLE"][:5]
assert len(units) == 5, "inspect structure or explicitly choose a smaller range"
json.dump([{"processing_id": sys.argv[1], "first_unit_version_id": units[0]["source_unit_version_id"],
 "last_unit_version_id": units[-1]["source_unit_version_id"], "max_chapters": 5,
 "max_input_bytes_per_chapter": 48000, "max_total_input_bytes": 240000,
 "context_before": 0, "context_after": 0, "max_repairs": 1,
 "dimensions": ["causal_constraints", "character_choice_cost", "information_gap"]}], open("reading-scopes.json", "w"))
PY
novel-forge corpus reading-preview --project-id "$PROJECT" --revision-id "$CURATED_REVISION" --reading-scopes reading-scopes.json --inspect-local-codex
novel-forge corpus analyze --project-id "$PROJECT" --revision-id "$CURATED_REVISION" \
  --reading-scopes reading-scopes.json --run-key "$ANALYSIS_KEY" --limit 1 \
  --max-calls "$AUTHORIZED_CALLS" --max-tokens "$AUTHORIZED_TOKENS" --authorization-ref "$AUTHORIZATION_REF"
novel-forge corpus run --project-id "$PROJECT" --job-id "$JOB" --max-stages 10
novel-forge corpus results --project-id "$PROJECT" --job-id "$JOB" --limit 10
novel-forge corpus evidence --project-id "$PROJECT" --job-id "$JOB" \
  --operation-id "$STAGE_OPERATION" --chunk-id "$ACTUAL_CHUNK" --byte-start 0 --byte-end 300
```

Only execute `analyze` and `run` with actual authorization for the purpose, backend and total
allowance. Preview grants none. Calls without repairs are estimated; classification,
review, repair, synthesis and extraction share the actual ledger ceiling. Token admission
meters the final materialized request; byte limits are not token estimates. Budget
exhaustion is partial/blocked, never implicit scope reduction. Inspect `reading_quality`,
per-stage `narrative.coverage`, diagnostics and output IDs. Each target request includes
its declared `context_before` / `context_after` neighbors from the frozen units. The final
manifest distinguishes `target_units`, `supporting_units` and chunk `unit_ranges`; a
supporting unit does not become another processed target. A finding needs target evidence
and may additionally cite delivered supporting evidence. Unread units remain unknown;
synthesis reads verified lower observations without rereading or enlarging source coverage.

Professional sections may use `core_concept`, `causal_constraints`, `credibility_rule`,
`misuse_risk`, `review_check`, `assumption` and `source_reliability`. Professional
classification selects the mechanism observation contract within the same bounded reading,
review, repair and synthesis path. It retains concepts, mechanisms, premises, applicability,
exceptions, failure conditions, misuse risks and explicit/inferred/hypothetical/unknown
claims. Fiction dimensions retain choices, costs, consequences, information and delayed
payoffs. Literal support spans are checked against delivered bytes and passed with the
candidate execution version to review; matching bytes alone do not prove semantic truth.

Evidence offsets address the actual input chunk, not original EPUB bytes or chapter
numbers. Both endpoints must be UTF-8 boundaries, with at most 4096 bytes per request.
Current Source query permission and curated eligibility are required for raw evidence.
HTTP equivalents are POST `/product/source-imports/corpus/reading-preview`, GET
`/product/source-imports/corpus/processing/{processing_id}/chapters`, and GET
`/product/source-imports/corpus/jobs/{job_id}/reading-evidence` with project, operation,
chunk and byte boundaries. Analysis extends the existing `/corpus/analyze` request.

Automatic directed repair stays within frozen `max_repairs`. Repair receives the immutable
prior observation, issue targets and preservation requirements. An unresolved blocking
issue cannot be silently downgraded or retargeted; explicit resolution is required.

`status` and `results` separate frozen targets, expanded targets, confirmed input, reviewed
and accepted targets. Use `corpus targets --project-id "$PROJECT" --job-id "$JOB"
--limit 20 --after 0` for the bounded target page (HTTP GET
`/product/source-imports/corpus/jobs/{job_id}/reading-targets`). Status embeds at most 20
targets; result assets remain separate references. An absent chapter task has outcome
`NOT_EXPANDED`, never “no findings”. An empty observation requires an explicit bounded
explanation and a valid accepting review before `NO_APPLICABLE_FINDINGS`; it creates no
knowledge candidate. Generic document analysis also retains an explained empty observation
and skips extraction, but the explicit reading-scope path supplies the review cycle.
Target counts deduplicate retries, revisions and overlapping supporting reads.

Planning success, first reading Operation/Work and READY registration share the owning
transaction. Observation/review/revision/next-chapter transitions and synthesis-to-MKAOS
registration also commit with their parent stage. A historical successful plan without its
expected reading work appears in `expansion_diagnostics`. `corpus resume` admits a
stable, causally linked reconciliation Operation through the existing Kernel, then
`corpus run` executes it. It leaves terminal Operations and their recorded results intact.
Current Source/selection authorization is rechecked; stale authorization blocks repair
and new dispatch. A changed scope, Prompt, model, or allowance requires a new request and
frozen selection as applicable. Resume and result queries never reset the budget.

Each stage exposes `input_receipts`, `output_validation` and semantic review independently.
The actual input manifest binds final assembled chunks and UTF-8 ranges, unit versions,
Processing, request hash, Prompt/Skill/runtime policy, lower observations and token
admission. `CONFIRMED_RETURNED` input remains queryable through `evidence` when output
format, quotation, range or review validation fails. `PREPARED` has no send proof;
`UNKNOWN` requires reconciliation. Older receipts lacking the manifest report
`NOT_RECORDED`; current source files cannot fill in historical proof. Reused receipts
retain the origin Effect and are not new sends. Synthesis of lower observations does not
increase source-text reading coverage.

Rejected Provider output retains a restricted diagnostic reference, separate from accepted
Observations and Candidates. Directed repair consumes that exact return, prior issues,
preservation requirements and the original evidence scope. Deleting a challenged finding
cannot resolve its blocker. Returned receipts are replayed before another invocation;
new revisions consume the original shared call/token budget. Missing observed usage
holds its reservation as unknown, including unobserved CLI overhead. Account-entitlement
preflight bounds application-visible input only; it does not prove a hard remote limit.
Invalid review output retries only that review within the same repair allowance. A stopped semantic issue
requires review and a new explicitly bounded request if further analysis is authorized;
query/resume cannot reset budgets. Transient failures resume the original job; confirmed
Effects survive lease takeover, unknown outcomes reconcile. `attempt_count` and
`fence_reacquisitions` distinguish a new attempt from a new lease on the same attempt.
Candidates follow existing MKAOS decisions and Pack selection; successful analysis does
not approve a Card or authorize production consumption.

The original professional and fiction fixtures for the six-chapter comparison live under
`config/production/knowledge-closure/`. Freeze them with the existing preparation helper;
its import manifests disable automatic analysis. Set `FROZEN_SOURCE_DIR` to a new directory,
`SOURCE_EVIDENCE` to a separate output directory, and use the configured local Corpus roots,
project/workspace and Source principal described above. No model authorization is needed
for this import/inspection sequence. The files describe synthetic resource/information
models and original fiction, not validated real-world professional advice.

The helper declares `PRODUCTION_REFERENCE` with explicit original-fixture rights for
`LOCAL_PROCESSING`, `SOURCE_ANALYSIS` and `ABSTRACT_GENERATION`. Historical `RESEARCH`
sources and curated revisions stay immutable. A real source needs its own exact license
and purpose evidence; matching content or a repository license cannot supply those rights.
Before authorizing analysis for a book, pass `--intended-use ABSTRACT_GENERATION
--target-book-id "$BOOK"` to both `reading-preview` and `analyze` (the API uses the same
field names). This checks current source rights, curated membership and Book scope/policy
before admission and every dispatch. A declared Book may still be absent: the result
reports `PENDING_BOOK_CREATION` and `PENDING_CARD_REVIEW`, never approval. Pure research
without a target retains the existing `SOURCE_ANALYSIS` behavior.

```bash
PYTHONPATH=src .venv/bin/python -m scripts.prepare_knowledge_closure prepare --output "$FROZEN_SOURCE_DIR"
mkdir -p "$SOURCE_EVIDENCE"
for kind in professional fiction; do
  novel-forge corpus import --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
    --manifest "$FROZEN_SOURCE_DIR/$kind-import.json" --run-key "$RUN-$kind-import" > "$SOURCE_EVIDENCE/$kind-job.json"
  SOURCE_JOB=$(jq -r .import_job_id "$SOURCE_EVIDENCE/$kind-job.json")
  novel-forge corpus run --project-id "$PROJECT" --job-id "$SOURCE_JOB" --max-stages 10
  novel-forge corpus lineage --project-id "$PROJECT" --job-id "$SOURCE_JOB" > "$SOURCE_EVIDENCE/$kind-lineage.json"
  SOURCE_EDITION=$(jq -r '.editions[0].edition_id' "$SOURCE_EVIDENCE/$kind-lineage.json")
  novel-forge corpus inspect --project-id "$PROJECT" --edition-id "$SOURCE_EDITION" > "$SOURCE_EVIDENCE/$kind-processing.json"
  novel-forge corpus chapters --project-id "$PROJECT" \
    --processing-id "$(jq -r .processing_id "$SOURCE_EVIDENCE/$kind-processing.json")" --limit 100 > "$SOURCE_EVIDENCE/$kind-units.json"
done
```

Inspect both returned assessments and the source files before the identity/selection
commands below. Stop on blocking structure or rights issues and use the existing scoped
review/reprocessing commands. This sample freezes the two inspected fixture members only.

```bash
for kind in professional fiction; do
  SOURCE_HASH=$(jq -r --arg name "$kind.jsonl" '.files[$name]' "$FROZEN_SOURCE_DIR/freeze.json")
  jq --arg key "knowledge-closure-$kind" --arg evidence "$SOURCE_HASH" '
    {action:"resolve_canonical_works",reason:"Inspected original fixture identity",
     changes:[{work_key:$key,title:$key,language:"zh",metadata_evidence:[$evidence],
       members:[{processing_id:.processing_id,relation:"SAME_WORK",evidence_refs:[$evidence]}]}]}' \
    "$SOURCE_EVIDENCE/$kind-processing.json" > "$SOURCE_EVIDENCE/$kind-work-decision.json"
  novel-forge corpus resolve-work --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
    --decision "$SOURCE_EVIDENCE/$kind-work-decision.json" --run-key "$RUN-$kind-work" > "$SOURCE_EVIDENCE/$kind-work.json"
done
jq -n --slurpfile p "$SOURCE_EVIDENCE/professional-work.json" --slurpfile f "$SOURCE_EVIDENCE/fiction-work.json" \
  '{action:"revise_curated_corpus",corpus_key:"knowledge-closure-sources",title:"Original closure fixtures",
    purpose:"PRODUCTION_REFERENCE",filters:{work_ids:[$p[0].revisions[0].work_id,$f[0].revisions[0].work_id]},
    reason:"Inspected bounded fixture sources"}' > "$SOURCE_EVIDENCE/curate.json"
novel-forge corpus curate --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
  --decision "$SOURCE_EVIDENCE/curate.json" --run-key "$RUN-source-candidates" > "$SOURCE_EVIDENCE/curated.json"
jq --slurpfile c "$SOURCE_EVIDENCE/curated.json" --slurpfile p "$SOURCE_EVIDENCE/professional-processing.json" \
  --slurpfile f "$SOURCE_EVIDENCE/fiction-processing.json" '. + {previous_id:$c[0].revision_id,state:"FROZEN",
    choices:[$p[0],$f[0]] | map({processing_id:.processing_id,selected:true,
      reason:"Original fixture scope inspected",evidence_refs:[.processing_id]})}' \
  "$SOURCE_EVIDENCE/curate.json" > "$SOURCE_EVIDENCE/freeze-selection.json"
novel-forge corpus curate --project-id "$PROJECT" --workspace-id "$WORKSPACE" \
  --decision "$SOURCE_EVIDENCE/freeze-selection.json" --run-key "$RUN-source-freeze" > "$SOURCE_EVIDENCE/selection.json"
CURATED_REVISION=$(jq -r .revision_id "$SOURCE_EVIDENCE/selection.json")
python3 - "$SOURCE_EVIDENCE" <<'PY_SCOPE'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
scopes = []
for kind, count, dimensions in (
    ("professional", 3, ["core_concept", "causal_constraints", "misuse_risk"]),
    ("fiction", 6, ["character_choice_cost", "information_gap", "foreshadowing_payoff"]),
):
    processing = json.loads((root / f"{kind}-processing.json").read_text())
    units = [u for u in json.loads((root / f"{kind}-units.json").read_text())["units"]
             if u["kind"] == "chapter" and u["status"] == "AVAILABLE"]
    assert len(units) == count, "inspect source structure before changing the frozen range"
    scopes.append({"processing_id": processing["processing_id"],
                   "first_unit_version_id": units[0]["source_unit_version_id"],
                   "last_unit_version_id": units[-1]["source_unit_version_id"],
                   "max_chapters": count, "context_before": 1, "context_after": 1,
                   "max_repairs": 1, "dimensions": dimensions})
(root / "reading-scopes.json").write_text(json.dumps(scopes, indent=2))
PY_SCOPE
novel-forge corpus reading-preview --project-id "$PROJECT" --revision-id "$CURATED_REVISION" \
  --reading-scopes "$SOURCE_EVIDENCE/reading-scopes.json" > "$SOURCE_EVIDENCE/reading-preview.json"
```

After actual authorization, use the `analyze` / `run` commands above with this
`CURATED_REVISION`, `--reading-scopes "$SOURCE_EVIDENCE/reading-scopes.json"` and `--limit 2`.
Without it retain the preview and `READY_FOR_AUTHORIZATION` / `NOT_RUN` evidence. The same
frozen request budgets include both sources and every review/repair/extraction call.

For production approval of real Source candidates, qualify the exact extraction capability
on the current authorized Source route. Keep the standalone `source-import-worker` stopped
while using this operator-controlled stage (`docker compose stop source-import-worker`),
and run the authorized analysis one stage at a time until `corpus results` exposes a
`MKAOS_EXTRACTION` stage with `operation_status=READY`. Existing Observations must already
exist; the qualification command does not fabricate them or start a second extraction.

```bash
novel-forge corpus run --project-id "$PROJECT" --job-id "$JOB" --max-stages 1
novel-forge corpus results --project-id "$PROJECT" --job-id "$JOB" --limit 100 > "$SOURCE_EVIDENCE/stages.json"
jq '.stages[] | select(.kind=="MKAOS_EXTRACTION" and .operation_status=="READY") | {operation_id,capability}' "$SOURCE_EVIDENCE/stages.json"
```

Inspect each page and follow `next_after` with `corpus results --after` when needed. Set
`SOURCE_EXTRACTION_OPERATION` and `SOURCE_CAPABILITY` to the selected exact pair. With a
clean current checkout and the same configured Source environment, preview the existing
qualification runner. `SOURCE_RUNTIME_ROOT` must be outside the repository and contain
the existing `NOVEL_FORGE_CODEX_EXECUTION_ROOT` at `codex-executions`; the runner preserves
the configured account, runtime identity and budget settings.

```bash
PYTHONPATH=src:. .venv/bin/python -m scripts.run_real_provider_qualification \
  --source-project-id "$PROJECT" --source-operation-id "$SOURCE_EXTRACTION_OPERATION" \
  --source-capability "$SOURCE_CAPABILITY" --expected-sha "$(git rev-parse HEAD)" \
  --provider "$AUTHORIZED_PROVIDER" --model "$AUTHORIZED_MODEL" --reasoning-effort "$AUTHORIZED_EFFORT" \
  --database-url "$NOVEL_FORGE_DATABASE_URL" --runtime-root "$SOURCE_RUNTIME_ROOT" \
  --minio-endpoint "$NOVEL_FORGE_MINIO_ENDPOINT" --output "$SOURCE_EVIDENCE/source-qualification.json"
```

Without `--execute` this remains `NOT_RUN` / `READY_FOR_AUTHORIZATION` after preflight;
missing credentials, accounting or release identity remain explicit preflight blockers.
Both `PRICED` and `ACCOUNT_ENTITLEMENT` are supported by the existing Source D0 path.
Entitlement requires the exact authorization, account identity and immutable entitlement
snapshot. Preview records the required Provider/model/profile, account/runtime, purpose
and shared total call/token/cost/repair fields without granting any allowance.
Add `--execute` only under existing explicit authorization for this Source stage and its
total allowance. Priced accounting retains immutable pricing evidence. Account entitlement requires a
settled reservation, measured usage and finite project call/token caps under the same
authorization; monetary amounts remain null and `UNKNOWN`. Missing usage remains
unqualified. The probe consumes the original Source job budget. Native Kernel lease/fence
ownership prevents competition; active leases block takeover. A returned result is
checkpointed, deliberately loses its immediate response, then reconciles the original
receipt without resend. Unknown outcomes must recover the same operation. An ordinary
successful stage without the required recovery evidence cannot be relabeled as this
probe or resent just to acquire qualification. Resume the worker after this bounded step
with `docker compose start source-import-worker`.

The resulting D0 qualification binds the actual Source capability, Provider/model,
account/runtime host, release, model profile, route, instruction/Prompt/Skill/schema hashes
and immutable effect/receipt. Production approval freezes that binding at admission and
rechecks it at commit. A changed or revoked qualification blocks approval and future
knowledge consumption without rewriting accepted history. A missing qualification leaves
the Candidate pending review. `production_verified` remains false: runtime qualification
and a successful structured output do not establish semantic correctness, literary
benefit or production effects. Scripted Source fixtures cannot acquire this qualification.

Knowledge approval uses the existing MKAOS API and worker, not a Corpus CLI approval
command. With the local API and MKAOS worker running, inspect candidate content and
Observation lineage, then set `CANDIDATE_VERSION` to the exact candidate actually reviewed
and `REVIEW_RATIONALE` to that decision. Do not bulk-approve all project candidates.

```bash
curl -fsS --get "$API/product/mkaos/knowledge-candidates" --data-urlencode "project_id=$PROJECT" > "$SOURCE_EVIDENCE/knowledge-candidates.json"
jq -n --arg project "$PROJECT" --arg workspace "$WORKSPACE" --arg key "$RUN-approve-$CANDIDATE_VERSION" \
  --arg rationale "$REVIEW_RATIONALE" '{project_id:$project,workspace_id:$workspace,
    policy_version:"knowledge-closure-review.v1",rationale:$rationale,idempotency_key:$key}' > "$SOURCE_EVIDENCE/knowledge-approval.json"
curl -fsS -H 'Content-Type: application/json' --data-binary @"$SOURCE_EVIDENCE/knowledge-approval.json" \
  "$API/product/mkaos/knowledge-candidates/$CANDIDATE_VERSION/approve" > "$SOURCE_EVIDENCE/approval-operation.json"
curl -fsS --get "$API/product/mkaos/knowledge-cards" --data-urlencode "project_id=$PROJECT" > "$SOURCE_EVIDENCE/knowledge-cards.json"
```

HTTP 202 is admission, not approval completion. Requery after the existing MKAOS worker
finishes; require the matching candidate, `operation_status=SUCCEEDED`, `card_status=ACTIVE`,
`lifecycle=ACTIVE`, `eligibility=ELIGIBLE` and `governance=CLEAR`. Retain only those explicitly
reviewed Card AssetVersion IDs in the JSON array supplied to preparation's
`--approved-card-versions`; they become arm A's exact allowlist. Empty findings need no
approval. Source analysis, Card approval, delivered context and correct prose realization
remain separate evidence states; no command above records human literary approval.

The EPUB logical profile example selects v5. Copy it locally, retain original work constants
and any validated continuation declarations, then use `corpus reprocess --edition-id
"$EDITION" --manifest "$LOCAL_PROFILE" --run-key "$REPROCESS_KEY"`. This appends Processing
and Bridge to acquired bytes without new download, changed rights or rewritten history.


Corpus `reading-preview` verifies the selected Blob and Chunk bytes, complete UTF-8
unit coverage and current selection through the same Source readers used by execution.
`prepared_source_checks` is `NOT_SENT`; it never supplies historical reading evidence.
Optional `--inspect-local-codex` (HTTP `inspect_local_codex=true`) observes only the
explicit executable's version/digest and local configuration gaps. It does not inspect
credentials, call a model or verify a user grant. A metadata-only runtime may use `mock`
while inspecting a proposed Codex executable; the response keeps those identities separate.
The real route must be explicitly configured and previewed again before admission.

Controlled Codex invocations freeze the designated account directory and override inherited
`CODEX_HOME`. They ignore user config/rules, suppress host Skill/AGENTS discovery and
explicitly disable shell, web search, apps, plugins, browser/computer access, images,
memories, hooks and autonomous agents. Account entitlement also requires ChatGPT login
mode. Local configuration and tool policy are part of route identity; changed bindings
require a new governed request. Returned tool-use evidence remains checked independently.
Local checks do not establish remote availability or bound unobserved CLI overhead.

For multiple corrected requests under one grant, retain the same project and absolute
`NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT` / `NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT`.
The existing budget ledger conservatively includes unknown reservations, and Source uses
the stricter of those absolute caps and the request ceiling. A new run key does not reset
those project caps. Supply only the remaining authorized allowance to a corrected request;
do not increase the project caps to compensate for consumed calls.

Codex structured output uses a versioned wire-schema projection: `uniqueItems` remains
in the frozen local validation Schema and is omitted only from the Provider Schema.
Primitive enum/const types are explicit in the wire Schema. The native reading preview
compiles observation, review, classification and extraction schemas without a model call;
it retains their hashes and distinguishes local compilation from remote acceptance.
Both schema hashes are retained with execution evidence. A remote `invalid_json_schema`
400 is a protocol rejection requiring a corrected frozen request, not a transient retry.

Source status includes `budget.project_cumulative`, derived from the project ledger and
process receipts across jobs. A started CLI with missing measured usage retains its
estimated tokens and call allowance. Legacy released reservations with a recorded process
start remain conservatively counted without rewriting their history; pre-start failures
remain distinguishable. Unknown use is never reported as measured zero. New requests must
use the remaining allowance while keeping the original absolute project caps.

Source Codex requests allocate the Effect deadline to one local invocation, retaining
settlement headroom. The preview reports both the Effect timeout and actual local process
timeout. A local CLI timeout/cancellation without a final usage receipt is an unknown
remote outcome, not permission to resend. Source preflight/status exposes the original
Effect and process receipt; admission and pre-send checks block new requests until governed
reconciliation resolves it. Legacy retryable Effects with these receipts are diagnosed
without rewriting their terminal history. Local process termination is not proof of remote
cancellation; missing remote identifiers or receipts can require external evidence.
Paused jobs with an unresolved CLI outcome report `RECONCILE_CLI_OUTCOME` before
`RESUME`; pausing does not clear the unresolved outcome or its budget reservation.

## Author-guided single-Book production

Use `config/production/author-guided-twelve` explicitly, retaining existing corpus data,
A/B policies and historical freezes. Its `creative-brief-v3` embeds versioned author
sources and selected spans. Full source files are archival inputs; final requests use
frozen role/range projections and protected budgets. Private cause stays in BOOK/VOLUME/ARC
intent. Each generated candidate records scoped adoption/adaptation/rejection or private
retention; only the existing Story Design/Planning decisions activate candidates.

Freeze a new directory with `scripts.prepare_knowledge_closure prepare`, verify it, and
pin its final manifest byte hash. Run `scripts.run_creation_synthesis` with the usual
brief/creation/Formation inputs, `--production-budget .../experiment.json` (an alias for
`--comparison-budget`), exact `--freeze-dir` and `--freeze-manifest-hash`. Without
`--execute` this is a preview. `--register-input-only` registers the precise brief through
Content at a clean expected SHA; it invokes neither Provider nor Formation and is not
approval. Actual production reuses that brief and the original run key.

`creative-single-book-budget.v2` has SOURCE, DESIGN, CREATION_EARLY (1–6), CREATION_LATE
(7–12), and REPAIR cumulative caps. Register only confirmed grants with
`authority-creative-budget configure`; `authorization.business_scope` limits Source,
design and maximum chapter. Scope and phase are checked on the actual native request
before reservation/dispatch, including repair origins. Existing design may be resumed
under a later chapter-only grant. Proposal files, a subscription and available Tokens
do not authorize execution. Account-entitlement monetary usage remains UNKNOWN.

For a newly authorized production Book, `creative-book-production-budget.v3` uses the
same configure command. Read the current `budget_binding` first and bind its exact
`policy_version`, `policy_hash` and `contract_hash` in `previous_policy`. Preserve the
experiment identity, project and cumulative total; supply the new Book, authorization
reference, evidence hash, explicit phase allocations and contiguous chapter ranges.
Every allocation must still cover its historical charges and outstanding reservations.
Configuration appends a policy version; it does not copy a fresh initial allowance.
Estimate the actual wired Provider calls before production, including planning and
quality nodes. A maximum chapter authorization does not prove that the budget can
complete that many chapters.

Each Workspace remains bound to one Book. Under a v3 production contract,
`--initialize --workspace-id ...` can create an independent Workspace in the existing
Project through `project_workspace.create`. Its API is
`POST /product/projects/{project_id}/workspaces`; the command requires the current
Project version and AssetVersion, the primary Workspace as its command scope, and
an explicit new Workspace identity. Creation preserves the primary Workspace and its
Book. Reuse requires an ACTIVE Workspace owned by the same Project and bound to no
Book or the requested Book. Earlier production contracts retain their primary
Workspace requirement.

For Planning output rejected before a Candidate exists, retry the exact frozen
generation command through `StoryPlanningGenerationApplication.generate`. The runtime
requires retained raw result evidence, a verified successful Provider receipt and
settled original usage. Only an explicit result-contract failure can create a linked
repair Operation, with at most two repairs and the complete original task retained.
The failed Operation remains terminal. Missing or unknown receipts require
reconciliation; valid raw output with a persistence failure is not regenerated by this
contract-repair path. World diagnostics identify the field path, expected type and
actual type, including fields inside `world_foundation_json`.

`pilot_stop_after_chapter` is independent of the full Book target. Frozen
`reading_checkpoints: [3,6,9,12]` makes the official driver pause after closed native
ChapterGroups. `python -m scripts.creation_checkpoint_review preview` exports accepted
prose and a NOT_REVIEWED template; `register` records a completed, located review through
Content; `decide` creates the existing BookControl decision. These commands take
`--project-id` and `--book-run-id`; preview also takes a new `--output` directory.
Registration and decision bind the exact accepted text, lineage, previous issues and
pause version. Issues retain severity, repair target and preservation requirements;
resolution evidence must locate the rechecked accepted version and preservation check. Unresolved issues cannot disappear by omission, and an old approval does
not undo a subsequent operator pause. Regenerate/read/register/decide if the paused
Book version changed.

For longer volumes, `reading_review_template(..., reading_start_chapter=N)` creates a
v2 review covering every chapter from N through the current checkpoint. Earlier
chapters require exact prior reading evidence; this avoids gaps between distant
checkpoints. Explicit nonblocking minor opinions may remain OPEN, while hard issues
still block continuation. The original v1 review contract retains its historical
coverage rules. Checkpoints and the final stop must coincide with actual ChapterGroup
boundaries; the existing supervisor permits a shorter final group at the Volume end.

Resume the same runner with `--resume-after-checkpoint N` and
`--checkpoint-review-decision-id VERSION`. At the configured third-chapter intervention,
also supply the original native `--plan-change-proposal-id` after a justified future
change. The first six chapters are reviewed as a whole before seven starts; at twelve,
retain the stop without declaring the 180-chapter Book finished. Reading gates coordinate
the official creation driver; they are not global gates on separate AUTO Book operations.
Native Provider stage/scope budget enforcement remains independent.

Exports `accepted-manuscript.md`, `accepted-manuscript.json` and per-chapter Markdown in the reading directory
use real acceptance and ChapterGroup lineage for the requested prefix. Candidates and
engineering fixtures never fill missing accepted chapters. This single-Book path does
not use the six-chapter two-arm blind-export completion check. AI_EDITORIAL_REVIEW,
author input and independent human review are distinct; no human feedback means
NOT_REVIEWED. The work-specific, relative-path command sequence is linked from the
current novel entry above.

## Knowledge-grounded six-chapter comparison

For the retained six-chapter A/B experiment, use
`config/production/first-novel-creative-execution` explicitly. The current author-guided
single-Book entry is `novels/yu-xian-zhi-wai/current/README.md`. The adjacent archived raw
materials, fixture chapters, backups and historical reports are inert records, not active
configuration discovery roots or Agent instructions. The A-only author design is a draft;
it is neither an approved native asset nor a shared input for B.

`prepare` publishes a new freeze directory atomically and never overwrites an existing
directory. It rejects reserved output names (`freeze.json`, `review-form.json`,
`allow-only.json`), symlinks and source/destination overlap before publication. The default
input names are explicit; custom names require an exact `--input-names` list. Do not pass
an old output directory back as inputs. `verify DIRECTORY` checks the complete final-byte
manifest read-only; legacy freezes retain the narrower `LEGACY_FILE_HASHES_ONLY` evidence.
Save the returned manifest byte hash outside the directory. For an experiment runner use
`--comparison-budget .../experiment.json --freeze-dir ... --freeze-manifest-hash sha256:...`;
the bytes validated are the bytes parsed for execution and resume.

The comparison plan separates fixed Source, creation and repair opportunities from each
project's total and the shared experiment total. A may have a larger project total because
it includes Source. The native CLI `authority-creative-budget configure` takes an explicit
operator policy and matching authorization evidence file; `query` returns the selected
grant and cumulative ledger usage. The existing Book API exposes the same configuration
at `PUT /product/production/book-authority/policies/creative-experiment-budget` and readout
at `GET /product/production/book-authority/projects/{project_id}/creative-experiment-budget`.
Only an authenticated local operator may configure a phase grant. Zero grants keep later
phases closed. Additional grants append versions under the same immutable allocation plan;
they do not clear previous calls, transfer unused Source allowance, or recreate the shared
ceiling in another project. Unknown outcomes retain reservations and require existing
Effect reconciliation. Monetary cost remains UNKNOWN for account entitlement.

Blind export classifies all frozen fields rather than equating whole runtime/accounting
objects. Models, prompts, Skills, context policy, word targets and creation/repair
opportunities remain comparable; identities and documented Source/project totals may
differ. Missing important fields, unequal creative opportunity, or unresolved usage block
the fairness conclusion. The first actual creation reservation must already have sufficient
creative and repair authorization; a later grant does not retroactively prove equal
opportunity. Genuine treatment additionally requires native request receipts and a check
against the accepted prose. Independent editorial status remains NOT_REVIEWED until actual
reviewers supply evidence.

`config/production/knowledge-closure` contains original synthetic professional and fiction
fixtures, one shared brief, six-chapter Formation/creation policies and an empty external
knowledge control. These fixtures are test inputs, not real-world professional evidence.
Preparation makes no Provider call and invents no approved Card or human verdict:

```bash
PYTHONPATH=src .venv/bin/python -m scripts.prepare_knowledge_closure prepare --output /tmp/kg-frozen
PYTHONPATH=src .venv/bin/python -m scripts.run_creation_synthesis \
  --brief /tmp/kg-frozen/brief.json --policy /tmp/kg-frozen/creation.json \
  --formation-policy /tmp/kg-frozen/formation.json --knowledge-policy /tmp/kg-frozen/deny-all.json \
  --project-id kg-control --book-id kg-control-book --workspace-id kg-control-workspace \
  --root /tmp/kg-control-runtime --run-key kg-control-01 --evidence-dir /tmp/kg-control-config
```

Follow the bounded deconstruction commands above to import, inspect, analyze and review
the samples in the treatment project. After actual knowledge approval, save the exact
Card AssetVersion IDs as a JSON string array. Freeze another directory with
`prepare --approved-card-versions approved-card-versions.json --output /tmp/kg-approved`.
This creates `allow-only.json`; execution rechecks ownership, version, withdrawal, rights
and Book access. Do not give the control project any treatment plans. `DENY_ALL` removes
external knowledge while retaining its own accepted Canon and memory.

For a long-novel pilot, use `config/production/first-novel-pilot` through the same helper:

```bash
PYTHONPATH=src:. .venv/bin/python -m scripts.prepare_knowledge_closure prepare \
  --input-dir config/production/first-novel-pilot --target-book-id "$TREATMENT_BOOK" \
  --output "$FROZEN_PILOT_INPUTS"
```

An explicit input directory freezes existing files only; it never gives real materials
the synthetic sample's CC0/OWNED declaration. The proposed brief has a 180-chapter
direction and three broad volumes, with only the near window refined. Top-level
`pilot_stop_after_chapter: 6` is frozen separately from the 180-chapter production and
Formation targets. At that cursor the runner closes the completed ChapterGroup and
pauses the Book; `full_book_completion` stays `NOT_PROVEN`. An intervention or pilot
boundary inside a group blocks dispatch until a legal scope change resolves it.

The native scope binds one Book to each workspace. Reuse the existing Source project
and primary workspace for A; create an independent project/workspace for B. Initialization
checks the existing project's active status and workspace ownership and preserves all
source assets and ledger history. It never reassigns an already bound workspace.

Partition the one authorized total into explicit project sublimits whose sum stays within
that total. Include Source and A's design/reviews/repairs in A's sublimit, and B's
corresponding work in B's sublimit. Freeze `NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT` and
`NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT` for every process in its project. Do not give
each project the full shared allowance, transfer unused budget automatically, or create a
replacement project to reset usage. Book-specific ALLOW_ONLY/DENY_ALL separates external
knowledge; both Books retain only their own Canon and independently generated upper plans.

For a small real-material catalogue, save original files and individual license evidence,
then admit each `analyze:false` manifest under a stable batch-prefixed run key. Use the
existing import/run/status/lineage/pause/resume commands per item, so one failed item
does not stop other imports. Reusing the exact key and manifest returns the existing job;
changed inputs require a new key or native reprocessing of the acquired Edition.

```bash
novel-forge corpus jobs --project-id "$PROJECT" --run-key-prefix 'materials-01:' --limit 10
novel-forge corpus jobs --project-id "$PROJECT" --run-key-prefix 'materials-01:' \
  --status IMPORTED --after "$LAST_IMPORT_JOB_ID" --limit 10
```

The CLI returns `items` and `next_after`; continue until the cursor is empty. HTTP GET
`/product/source-imports` accepts the same `after`, `status`, `source_type`,
`run_key_prefix` and `limit` filters and retains its list response. Prefix matching is
literal and applies only to Corpus import/preview run keys, never Git refs. Cursors must
belong to the requested project. Preserve each native job and per-item lineage export in
the operator catalogue; the catalogue is an input/export index, not another state store.
Count bibliographic works separately from acquired sections and editions. An imported
HTML section with unparsed diagrams or a contradictory formula is not automatically
ready for knowledge extraction; record the limitation and exclude it from the first
selection. Freeze the inspected subset through native canonical-work and curated-corpus
commands before a bounded reading preview. Candidate approval remains a separate exact
version decision by an authorized reviewer.

For retained front matter or license blocks, inspect the exact processing, submit
`MARK_NON_BODY` with its source spans, then reprocess the acquired Edition to produce
excluded units. A review alone does not rewrite the processed text. Boundary changes
must preserve original work/edition metadata; resegmentation retains new non-body
findings for explicit review. Do not infer complete coverage from a usable structure.

Before either real run, bind both arms to the same explicitly authorized backend, model,
account, Prompt/Skill versions, word targets and revision budget. Supply the total call,
token and monetary/account allowances through the existing Provider controls. The frozen
manifest is `READY_FOR_AUTHORIZATION`; a preview, arbitrary authorization string or
subscription availability supplies no grant. No deterministic seed is assumed.

Execute the same runner command separately for the two Book identities, adding
`--initialize --execute --expected-sha "$SHA" --authorization-ref "$AUTHORIZATION_REF"`
and, for priced execution, `--authorized-total-usd "$ARM_AUTHORIZED_USD"`. Treatment uses
`--knowledge-policy /tmp/kg-approved/allow-only.json`; control uses `deny-all.json`.
The two arm allocations plus source analysis and repairs must fit the authorized total.
Use new evidence directories for every invocation and retain each export. Resume keeps
the same brief, policies, run key, Book and frozen routes; changing them requires an
explicit new experiment rather than silently continuing an old run.

After Chapter 3 acceptance, the runner prepares the wholly future ChapterGroup, pauses
before Chapter 4 dispatch and reports `FUTURE_PLAN_CHANGE_REQUIRED`. Its event records
the target plan, accepted boundary and input snapshot. The directive is frozen in
`creation.json` at `future_plan_change.directive`. Apply it using the existing native
authorities; all paths below are relative to the local API URL:

| Step | Native operation and required input |
|---|---|
| Record the change | POST `/product/content-authority/commands`, `definition_name: planning.change_request.author`, project/workspace/actor/idempotency/trace/correlation fields, no input assets, `payload.content` containing `book_id`, `target_plan_version_id`, `accepted_through_chapter: 3`, `affected_scope: CHAPTER_GROUP`, `safe_summary` set to the frozen directive, `structured_facts: []`, the frozen `directive` and nonempty `preserved_invariants` |
| Inspect the old plan | GET `/product/production/book-authority/books/{book}/planning-candidates/{target_plan_version_id}?project_id={project}`; retain candidate and `frozen_command` |
| Generate the replacement | Clone `frozen_command`, set a fresh `idempotency_key`, set `change_evidence_version_ids` to the completed change-request AssetVersion, clear the old `narrative_search_` fields (`id`, `branch_key`, `parent_state_asset_version_id`, `strategy_directive` to empty strings; `accepted_through_chapter` to 0; `planning_horizon`/`desired_transformation` to empty objects; `hard_constraints` to an empty list), and keep `auto_approve_low_risk: false`; POST `/product/production/book-authority/books/{book}/planning-generations` |
| Inspect generation | GET `/product/production/book-authority/books/{book}/planning-generations/{operation_id}?project_id={project}`; workers perform existing Provider and semantic qualification stages; inspect failures before proceeding |
| Propose | POST `/product/production/book-authority/books/{book}/plan-changes` with project/workspace/book/actor/trace/correlation, fresh `stable_idempotency_key`, `source_type: HUMAN_FEEDBACK`, `source_evidence_version_id`, `target_asset_version_id` and qualified `proposed_asset_version_id` |
| Decide and activate | POST the proposal's `/decisions` with `{project_id, actor_id, approved, reason}`; only after approval POST its `/activate` with `{project_id, actor_id}` |
| Resume | Reinvoke the creation runner with the same frozen inputs and `--plan-change-proposal-id "$PROPOSAL"`; it verifies the directive and original boundary, rebinds the existing Book snapshot and continues Chapters 4–6 |

The lower-level resume API is POST
`/product/production/book-authority/runs/{run}/plan-changes/{proposal}/resume` with
`{project_id, actor_id}`. It accepts an owned active wholly future ChapterGroup change;
replay after later acceptance returns the prior binding receipt without resetting Book
state. Accepted Chapters 1–3 remain immutable. Rejection leaves the Book paused for a
new candidate; unknown Provider effects require reconciliation before another dispatch.

The runner's `creation-run.json`, `events.jsonl`, `chapter-workspaces.json`, exported
Context/Card/Pack assets and ledger preserve originals, diagnoses, revisions, selection,
acceptance and later state. Inspect `knowledge_trace` in Chapter workspaces, or query an
exact Card from either direction:

```bash
novel-forge authority-knowledge-trace --project-id "$PROJECT" \
  --knowledge-card-asset-version-id "$CARD_VERSION" --book-id "$BOOK" --limit 50
PYTHONPATH=src .venv/bin/python -m scripts.prepare_knowledge_closure blind \
  /tmp/kg-treatment-export /tmp/kg-control-export --output /tmp/kg-blind
```

The HTTP trace is GET `/product/mkaos/knowledge-cards/{version}/trace` with `project_id`,
optional `book_id` and `limit`. It separates selection, actual delivery receipts,
planning claims, checks against exact candidate prose and the formally accepted version.
It reports bounded results explicitly; it cannot certify independent editorial approval.

Blind export requires six exactly bound accepted manuscripts per arm, distinct Books and
plans, matching frozen routes, targets and budgets, and the applied third-chapter change.
`chapter-groups.json` comes from GET
`/product/production/book-authority/runs/{run}/chapter-groups?offset=0&limit=100`.
It binds actual Group runs and exact plan ranges to Chapter requests, normalized plans,
committed Book acceptances and resulting Canon/StoryState. Two completed groups may
share one Arc; multiple Arc versions never turn one group into two. Incomplete pages or
acceptance lineage cannot qualify a comparison.
It validates each accepted Context against the frozen Book knowledge policy and rejects
external Card deliveries outside the treatment allowlist or inside the control arm.
`knowledge-runtime-usage.json` binds deliveries to actual creative-request receipts;
the private treatment status also checks located evidence against exact accepted prose.
A whitelist or adoption claim alone leaves `TREATMENT_NOT_ESTABLISHED` and
`CREATIVE_BENEFIT_NOT_EVALUABLE`. Recorded realization, fixture evidence and independent
editorial judgment remain separate.
It emits randomized chapter/arc packs and empty seven-axis forms for knowledge accuracy,
natural integration, causality, character, pacing, voice and desire to continue. Keep the
private mappings away from reviewers. Assign actual reviewers and collect their own
responses; generated empty forms are `NOT_REVIEWED`. A completed six-chapter comparison
can establish a bounded result, not long-novel stability or real-reader benefit.
