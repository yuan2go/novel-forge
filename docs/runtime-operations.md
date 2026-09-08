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

## Corpus metadata commands

The existing Authority API accepts `POST /product/source-governance/corpus/commands`.
The envelope requires `project_id`, `workspace_id`, `idempotency_key` and a typed `action`;
the trusted Principal supplies the actor. The existing Project/Workspace must be active.
`source.authority.execute` permits writes and `source.authority.query` permits reads.
Run migrations, the Authority API and the existing Source worker using the same database
and release identity. No Provider or download adapter is invoked by these commands.

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
`scope=ALL_WORKS_IN_SNAPSHOT`. Use UNKNOWN rather than invent underlying rights.
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
