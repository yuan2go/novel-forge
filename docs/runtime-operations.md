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

Before starting Provider-capable processes against an existing installation, resolve the
actual launcher/private configuration, container or service, persistent volume, database
name and object bucket. A missing default database is not evidence that historical data
is absent. The read-only CLI can inspect the intended ledger without building Provider
routes or bootstrapping a replacement:

```bash
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-runtime-inspect \
  --project-id "$PROJECT_ID" --expected-database "$EXPECTED_DATABASE" > ledger-inspection.json
```

Use the existing trusted principal with `book.authority.query`. The output includes
server/database identity, registered migration head, Book/cursor state, unresolved Effects,
expired scopes and null/unknown cost totals. It neither proves production authorization nor
resends/reconciles Effects. Keep expired grants and unknown account-entitlement costs;
inspect exact owner-specific receipts before using existing recovery commands. Back up
persistent data, exercise upgrades against a restore, verify object references and compare
ledger identity before/after service restart. Dynamically published container ports must be
resolved from the same verified volume; never substitute a fresh database at the old port.

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

For creative-requirement changes, focused regression coverage includes
`test_work_intent_consistency.py`, `test_work_foundation_contract.py` and
`test_work_realization_contract.py`, plus existing Pack materialization, Provider
transport/admission, quality calibration and legacy-recovery tests. Use actual stage
assemblers with external I/O substitutes. Disposable PostgreSQL checks cover native
Book acceptance, zero-increment realization/rebuild, accepted history, exact replay and
UNKNOWN reconciliation. Independent author-supervision approval tests must retain their
`NOT_PROVEN` literary ceiling. Record synthetic inputs as `SYNTHETIC`, reconstructed
inputs as `RECONSTRUCTED`, and keep failed attempts with the final focused results.

A focused pass does not substitute for release qualification below. Before rollout of
work contracts, run migration clean-install/upgrade and the applicable same-release
matrix, register/compile/approve/deploy the coherent Pack and routing profiles, and
verify existing frozen requests remain recoverable. Do not upgrade historical plans or
quality receipts silently. Context budgets must admit all required inputs and the final
complete Provider envelope; increasing a declared test budget cannot waive overflow
checks or establish production capacity. Real Provider and anonymized literary
comparison remain separate authorized activities.

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


## Task Context capacity and assembly

At the work-package starting revision `4948d9b3a1ca22a78daffb4f4ab1cbf46180ac52`,
semantic overflow effects existed but formal Router selection rejected context tasks
with `ROUTING_TASK_POLICY_REQUIRED`. Current policy `quality-constrained-routing.v13`
classifies `context_compress` and `context_fidelity` as HIGH-risk tasks using independent
`DOMAIN_GATE_ACCEPTANCE` qualification (20 effective samples and the existing conservative
quality floor). A cold or failed cohort blocks before dispatch; no direct Provider path
is added. This is extract/reconstruction engineering qualification, not literary fidelity
calibration. Budget, timeout, retry, PEP admission and frozen native receipts remain owned
by the existing production execution and Command Kernel.

Compression freezes source version/hash, Book and accepted frontier, original required
units and selected units. Independent fidelity checks a separate Effect. Missing mandatory
units are restored from that exact frozen source and fidelity rechecked independently;
failed fidelity or mandatory overflow fails closed. Positive feedback requires a successful
Context output and matching native verified receipts. Every fidelity assessment and failed
Context terminal outcome remains in the feedback denominator. Dispatch generation and receipt
integrity determine which native result is used; retry failure history cannot be washed away.
Context qualification retains negative domain outcomes from retried independent samples;
retried successes cannot add positive qualification. A positive native assessment requires
both Effects to be successful at their latest dispatch generation and matching dispatch
and verified receipt hashes. Pending or UNKNOWN generations require reconciliation before
their older receipts can supply positive feedback. Frozen routing decisions retain their
original policy snapshots and accounting rules.
Restoration reconstructs original attributed units for the normal Draft/Review Context.
Replay uses the durable Effect result and exact Pack, Prompt, Skill, Schema and baseline;
changed sources, cross-Book frontier or stale binding cannot silently replace them.

Scoped verification uses a caller-owned disposable PostgreSQL instance and formal author,
Formation, Planning, Book and Chapter assemblers. Controlled candidate qualification observations
and scripted Provider output are `MOCK_E2E`, never reusable native real qualification. Their
fixture waivers are explicitly scoped, and no paid Provider is authorized by this diagnostic.
The audit delivery records exact inputs, effects, accepted projections, next-unit reads and
recovery results; global backend qualification and literary proof remain separate.

For future Chapter work, author `book-chapter-context.v1` with
`draft_profile: draft-context-profile-v4`, a positive `draft_token_budget` at most
512,000, and the desired quality task budget. World/Director roles may use
`world-production-policy.v4` with independently chosen Context allocation. Deploy
and select Chapter Generation Pack `2.7.0` through the existing Pack Authority;
then verify its compiled snapshot and the Chapter preparation report's
`stage_context_profile_versions.draft`. Its frozen Context policy explicitly sets
the Planning task target to 64,000 tokens; this does not increase the authorized
Provider token or money ledger. Changing process defaults does not update
an old Book, Pack, preparation report or sent request. Old frozen contracts recover
with their original hashes and semantics.

Configure each actual route with its confirmed model Context and output limits,
accounting method/evidence, and supported high reasoning. The system supports a
maximum of 512,000 tokens; the effective complete-request window is the minimum
of that maximum, the selected model window and the existing authorized execution
limit. Output reservation is independent of the task Context target. API stages
use their stage output target, bounded by confirmed model capacity and enforced
in the sent request. OpenAI reasoning shares that output reserve; DeepSeek uses
its supported reasoning budget semantics. Codex CLI has no enforced per-request
output ceiling, so new task contracts reserve the full confirmed model output
capacity, including reasoning once. Unknown CLI output capacity, insufficient
authorization or a final route whose output capacity exceeds the frozen reserve
blocks before dispatch. CLI admission labels application-visible coverage.
A static Planning model may inherit capacity evidence only when it uses the
same confirmed model as Draft. To select a different real Planning model, use
the existing router with that candidate's own verified capacity and permission;
changing only its model identifier leaves capacity unknown and blocks new work.
Missing capacity, unsupported reasoning or an unqualified route blocks before
external dispatch. Context compression uses the same authorized Provider and
cumulative cost/token ledger; it does not grant extra calls or silently change models.

A derived World Context uses its own frozen World policy for the selection budget
and accounting method. A newer base Planning Pack does not reinterpret the legacy
World estimate or replace its allocation with the Planning target. World v4 uses
explicit conservative token accounting; complete Provider admission remains a
separate check for every rendered request.

For task-scoped World work, frozen hard-rule entity references identify necessary
background. The existing accepted-lineage repository fetches that entity's first
and latest unconfirmed background events using accepted chapter and frozen entity
versions, plus exact causal dependencies, even
when they fall outside the recent discovery page. Intermediate and unrelated
history stays outside the task. When a boundary chapter lacks a unique causal
order, its original events are retained; hashes and input array positions do not
stand in for semantic order. Current reader knowledge and disclosure evidence
keep confirmation separate from hints and misdirection. Typed required event
references are validated before lookup. A necessary set exceeding the explicit
2,048-event or 32-round host bound blocks rather than losing dependencies. These
are bounded task policy limits, not new story Authorities.

Inspect the frozen Context `task_context_receipt` and role `task_workset` for task,
source version/hash, accepted boundary, necessary refs, selected/excluded history,
estimated token method, fast path and compression/recovery trace. Prompt/Skill/Schema
and protocol overhead are checked again in the materialized Provider admission
receipt. A local compressor parse/coverage problem reuses a durable successful Effect;
UNKNOWN outcomes require reconciliation. Source changes require a new versioned
request, not mutation of the dispatched identity. Keep exact Review/Revision text
and citations; faithful required overflow is an explicit block.

The compatibility tests construct current Runtime evidence separately from exact
historical 0103 schema assertions, upgrade that window through the real migration,
and only then run the current Runtime. They do not add later tables to the old
window or promise current Runtime support for every historical schema.
On the current schema, recovery of the published formal model-required Chapter
`3.4.1` contract retains its original Operation, workflow/Pack snapshot, 60-second
Context policy and successful Provider Effect. The current handler codec accepts
that exact predecessor alongside the current contract; other stale versions,
handler/name mismatches and stale Fences remain rejected. It does not recreate
historical definitions or update the frozen request to a current definition.

For credentialed prose verification, read the selected author Foundation, typed
Book chapter target, production profile, Pack snapshot, author-supervised permission,
route/model/reasoning and finite budget expiry before execution. Preserve dispatch
brakes until authorized conditions hold. The formal proof remains generation,
Review, necessary edits-only Revision/ReReview, Book Acceptance and next-chapter
consumption of accepted Canon/Narrative State. A missing or expired grant keeps
real execution `NOT_RUN`. Finite paired Context comparisons must retain original
and revised text, independent evaluation, exact task/source/model boundaries, full
chain token/cost receipts and latency. Controlled fixture success cannot establish
literary gain or long-term production.

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

## Narrative Craft operations

The existing trusted principal must have project-scoped `mkaos.authority.query`,
`mkaos.authority.execute` or `mkaos.authority.approve` as appropriate. Inspect the catalog
and its hash before explicitly authoring or approving exact versions:

```sh
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-craft catalog --project-id "$PROJECT_ID"
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-craft author --project-id "$PROJECT_ID" --workspace-id "$WORKSPACE_ID" --mechanism-id attention-relay --catalog-hash "$CATALOG_HASH" --idempotency-key "$AUTHOR_KEY"
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-craft approve-core --project-id "$PROJECT_ID" --workspace-id "$WORKSPACE_ID" --candidate-asset-version-id "$CANDIDATE_VERSION" --catalog-hash "$CATALOG_HASH" --rationale "$EDITORIAL_RATIONALE" --idempotency-key "$APPROVAL_KEY"
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-craft cards --project-id "$PROJECT_ID" --mechanism-id attention-relay
PYTHONPATH=src .venv/bin/python -m novel_forge.cli.authority authority-craft trace --project-id "$PROJECT_ID" --knowledge-card-asset-version-id "$CARD_VERSION" --book-id "$BOOK_ID"
```

HTTP exposes `GET /product/mkaos/craft-catalog?project_id=...` and
`POST /product/mkaos/craft-candidates`; approval uses the existing candidate approval
endpoint. These are existing MKAOS permissions and Kernel jobs, not direct table writes.
Catalog inspection neither imports nor activates Cards. For a later mechanism version,
pass `--supersedes-card-asset-version-id` (HTTP `supersedes_card_asset_version_id`) with
the exact immediate active predecessor in that project. Review the candidate's frozen
catalog hash for approval, including after a newer application catalog is deployed.
Existing Book knowledge-access
policy must permit an approved Card before Planning can retrieve it.

To request Source discovery, pass `intelligence_policy.routing_policy_version` as
`source-analysis-routing.craft.v1` in the existing Source import request. Keep Source rights,
Provider authorization, budget and review gates unchanged. New candidates remain
`NEEDS_REVIEW`; review the Observation, abstraction/isolation, applicability and duplicate
mechanisms before approving. Do not treat a source hypothesis as reader-effect evidence.

The Planning Context records selected/rejected candidates, match and applicability reasons,
receipt-backed recent usage and frozen Craft policy. Chapter run queries with
`include_workspace=true` expose `craft_trace` and the existing `knowledge_trace`:
use exact Card/use/selection/strategy hashes to compare Plan, Intent, Memo, realized prose,
Review, targeted edits, ReReview, candidate comparison and accepted manuscript. Missing
receipt or reader evidence remains missing. Draft task and Context delivery are separately
observable; a planning claim alone is not proof of received input.

Focused Craft tests are classified in the `narrative_craft_engineering` backend semantic
slice. Run the complete applicable validation matrix above after production changes,
including fresh and previous-head migration compatibility, all PostgreSQL integration,
query-plan and Compose runtime gates. The eight-domain controlled prose corpus is original
fixture data; its scripted expectations are not calibrated semantic evaluation. Only a
separately authorized real-Provider/editorial campaign can establish creative quality.

## Creative validation resource operations

Treat the campaign commands and quota examples below as historical/strict contracts.
They do not require a membership-only Book to allocate per-phase budgets. Paid DeepSeek
execution must inherit an already authorized template; never infer spending permission
from a credential or model name. Inspect the selected account and currency before send.

For policy succession, preserve old frozen commands, Pack snapshots, Provider identities,
usage and accepted chapters. Apply a successor only to unstarted work through its owning
Authority. Reconcile RESERVED/HELD_UNKNOWN effects before replacement; cancellation
without proof of no remote execution cannot release a paid reservation. Resuming the
same Operation reuses its durable receipts and accepted cursor. A new task, release or
run key cannot create a fresh spending allowance for the same work.

Validation results advance internal production only with a native versioned validation
admission receipt. Strict certification rejects missing required proofs. Omitted literary
calibration, blind review and publication checks retain `NOT_RUN` and their reason.
The shipped files are `config/execution_templates/creative_validation.json` and
`config/execution_templates/creation_inputs.json`. The first selects optional objectives,
allowed authenticated routes and inherited paid authorization; the second supplies genesis
state and quality floors. `creation-request.v1` supplies the current work's brief, title,
target chapter count, required language and optional chapter-length bounds. These inputs
are frozen together as `formation-generation.v5`; continue uses that snapshot even if the
template file later changes. `creative_candidates` optionally selects two to four direction
alternatives (default two); it does not multiply every lower planning layer or chapter.
An optional `author_creative_foundation` binds the exact asset version/hash of an already
approved original author direction. Native validation verifies its active receipt; no
creative candidate generation occurs on that path. The existing author page offers both. A yield at the CLI execution-window boundary is a saved
checkpoint, not budget exhaustion, Book completion or permission to shorten the work.

Configure the deployment once with the existing trusted local operator, exact release,
PostgreSQL, MinIO and authenticated Codex configuration. The operator still needs native
Project, Book, content, Pack compiler/deployer and Agent-admin permissions in the selected
project. Workers retain their own existing scoped roles. The CLI uses the existing Project
and Workspace Authorities to create missing scope; it rejects another Book's workspace,
paused projects, another project's Formation and a replacement task key for an admitted
Book. It never infers authority from the request's actor text.

Set these mode selectors in that deployment configuration:

```bash
export NOVEL_FORGE_ENVIRONMENT=validation
export NOVEL_FORGE_RESOURCE_CONTROL_VERSION=billing-channel-resources.v1
export NOVEL_FORGE_PROVIDER_ROUTER=quality-cost-v1
export NOVEL_FORGE_ROUTER_CODEX_ESCALATION=true
export NOVEL_FORGE_ROUTER_PROVIDERS=codex-cli
export NOVEL_FORGE_MODEL_PROVIDER=codex-cli
export NOVEL_FORGE_PLANNING_PROVIDER=codex-cli
export NOVEL_FORGE_CODEX_ACCOUNTING_MODE=ACCOUNT_ENTITLEMENT
export NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND=minio
```

Bind the already authorized primary model through `NOVEL_FORGE_CODEX_ROUTER_MODELS`
(`codex-router-models.v1`: model, reasoning, PRIMARY/REFERENCE role, authorized task names,
context and output limits) and `NOVEL_FORGE_CODEX_ESCALATION_MODEL`. Set the base model and
Planning model consistently. Model limits are actual per-request capacity; they are not
all-book token budgets. The deployment must supply the absolute Codex executable, existing
authenticated `NOVEL_FORGE_CODEX_HOME`, empty isolated `NOVEL_FORGE_CODEX_WORKSPACE`, durable
`NOVEL_FORGE_CODEX_EXECUTION_ROOT`, observed CLI version and executable digest, configuration
identity, membership authorization reference, runtime host, auth profile and token-accounting
evidence. Existing transport admission checks remain active. Do not invent a budget contract,
call ceiling, token ceiling or an API pricing record for membership. The account reference
can be obtained without exposing tokens or calling the Provider:

```bash
python -c 'import os; from novel_forge.modules.production_execution.membership_identity import observe_membership_identity; print(observe_membership_identity(os.environ["NOVEL_FORGE_CODEX_HOME"])["account_ref"])'
```

Store that observed reference as `NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF`; account drift or
API-key authentication fails closed. A member-service error retains the current checkpoint
and service cooldown. It cannot authorize a paid API substitution.

For already authorized DeepSeek usage, also configure its actual credential privately,
`NOVEL_FORGE_DEEPSEEK_BILLING_ACCOUNT_REF` and
`NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE`, and include `deepseek` in the allowed Router
providers. The paid template is an object containing `account_ref`, `currency: "USD"`,
positive decimal-string `maximum_amount`, and the existing `authorization_ref`. The native
template command copies that approved configuration into this Book's immutable policy.
Without the file or matching account, DeepSeek is unavailable and Codex remains usable.
Modern mixed-channel composition also disables DeepSeek when the inherited template file
or credential is absent, before constructing paid adapters. Its configured per-call
ceiling defaults to the inherited maximum; rendered cost reservations still use the
actual request bound. Disabled-channel reasons are frozen in routing resource evidence.
The deployment account declaration is bound to the actual credential fingerprint in each
frozen route; the runtime rejects a changed key before send. This is a trusted local
configuration binding, not an independently queried proof of the remote account owner.
A credential rotation requires an explicit unexecuted successor; it never resets costs.
The cap is maximum allowed spending, never a spending target. Settlement, reservations and
held unknown results for the same Book count together across every phase and policy version.
If a reported paid charge exceeds its reservation, the held amount is the greater of
reservation and reported actual charge; further paid work cannot exploit an understated
reservation. The anomaly requires reconciliation and never becomes a successful settlement.
Engineering model-reference/benchmark consumption has a separate reporting category in the
rolling work estimate but still contributes to the same paid ceiling. Phase lanes do not
provide independent hard allowances. Neither a new Task nor a policy successor raises or
resets the Book's paid ceiling.

Save the current author request as a JSON file. Its closed shape is:

```json
{
  "version": "creation-request.v1",
  "title": "Current author title",
  "target_chapters": 180,
  "language_contract": {"required_language": "zh-CN"},
  "chapter_length": {"minimum": 1500, "maximum": 4000},
  "brief": {
    "creative_brief_contract_version": "creative-brief-v2",
    "idea": "The current author's original premise and intended ending",
    "genre": "The current author's genre and style",
    "audience": "The current author's intended readers",
    "constraints": ["The author's required structure and quality constraints"],
    "source_boundaries": ["Original expression; references supply governed abstractions only"]
  }
}
```

Replace the illustrative values with the original work requirements; the CLI supplies no
sample target or genre. Omitting chapter length retains the selected template's floor.
Run from the repository with its installed Python environment and configured resources:

```bash
novel-forge authority-migrate
novel-forge authority-creation start \
  --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-id "$BOOK" \
  --input-file "$WORK_REQUEST" --idempotency-key "$CREATION_KEY" \
  --repository-root "$PWD"
python -m novel_forge.workers.book_authority
```

Run the worker in a second terminal with the same deployment environment.
Read progress and choose after comparing the returned exact direction texts:

```bash
novel-forge authority-creation status \
  --project-id "$PROJECT" --formation-run-id "$FORMATION_RUN"
novel-forge authority-creation choose \
  --project-id "$PROJECT" --formation-run-id "$FORMATION_RUN" \
  --candidate-number "$CANDIDATE_NUMBER" --reason "$COMPARISON_REASON" \
  --idempotency-key "$DIRECTION_DECISION_KEY"
novel-forge authority-creation continue \
  --project-id "$PROJECT" --formation-run-id "$FORMATION_RUN" \
  --repository-root "$PWD" --maximum-ticks 100 --work-window-seconds 300
```

The start result supplies the original Formation identity. Preserve it and the same
creation key. Start now returns after durable admission; the existing Book worker owns
continuous phase handoffs. `continue` schedules the same work and `--foreground` optionally
drives a bounded local window. Ordinary technical waits need no author continuation call.
The existing author production page sends `production_intent` with its saved Brief to the
same Formation endpoint and uses this same application coordinator. It displays the
Formation decision, worker progress and cancellation; reader/editor/Edition interfaces
continue to own exact text changes and export.

`AUTHOR_DECISION` waits for a content-bound choice. Author comparison must explain current
intent, motive, cause, conflict, differentiation, scope and later writability, including
uncertainty. Failed directions remain diagnostics. Selecting the sole admitted alternative
requires a specific decision and retained bounded failure evidence; the result cannot be
called a best-of-two comparison. `TECHNICAL_WAIT` uses bounded exponential delay (5–300
seconds). Twelve unchanged coordination windows stop at `CREATION_NO_PROGRESS`; native
retryable Formation recovery is limited to three distinct failed source versions.
`RECONCILIATION_REQUIRED` retains the original external identity; no fresh ID is dispatched.
`OWNER_RECOVERY_REQUIRED` explains an unresolved configuration, terminal effect or
unrecoverable stage failure. Inspect the native failure/effect before using recovery:

```bash
novel-forge authority-creation recover \
  --project-id "$PROJECT" --formation-run-id "$FORMATION_RUN" --reason "$RESOLVED_BLOCKER" \
  --idempotency-key "$RECOVERY_DECISION_KEY"
novel-forge authority-creation cancel \
  --project-id "$PROJECT" --formation-run-id "$FORMATION_RUN" \
  --idempotency-key "$CANCELLATION_KEY" --reason "$CANCELLATION_REASON"
```

Recovery can wake the same source after an owner-resolved no-progress stop without
changing business inputs. Preserve its reason and decision key on an uncertain response;
replay returns the original recovery job, while a changed reason is rejected. A later
independent recovery decision needs its own key. The UI retains this frozen request
through reload, using the existing Formation resume endpoint.

Cancellation binds the frozen digest, appends intent before forwarding to the active
Formation/Opening/Book owner and prevents automatic revival. It does not rewrite completed
history. `COMPLETED` means native internal Book acceptance completion. The author status
labels this `INTERNAL_ACCEPTANCE_COMPLETE`: exact Edition selection and export remain
separate, as do strict qualification and long-form literary proof. Membership execution
has no cumulative money/token/call cap. Paid DeepSeek still uses the existing inherited
Book ceiling, including retries, restarts and UNKNOWN occupancy. Independent review remains
required when selected; resource shortage cannot replace it with ineligible self-review.

Historical Formation v4 freezes first-admitted selection. Repeating an existing v4/v5
start validates the original work request and consumes its saved profiles, without
installing new Packs or changing its selection policy. `--creative-selection FIRST_ADMITTED`
is available only to deliberately create a compatible v4 task; it is not literary selection.

Historical Formation v1-v3 continuation requires its original creation-input policy through
`--creation-policy-file`; historical successful effects retain their frozen routing and
Pack snapshots. Bind a native resource successor for *new work* through the existing
policy owner before continuing an older finite-cap Opening:

```bash
novel-forge authority-execution-template \
  --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-id "$BOOK" \
  --policy-version "$RESOURCE_POLICY_VERSION" --idempotency-key "$RESOURCE_POLICY_KEY"
novel-forge authority-opening-resource-successor \
  --project-id "$PROJECT" --opening-run-id "$OPENING_RUN" \
  --expected-version "$OPENING_VERSION" --idempotency-key "$OPENING_RESOURCE_KEY"
```

This appends `book-opening-resource-successor.v1` while preserving the original scope,
policy hash, node receipts and completed content. Continue adopts it automatically when
the configured runtime is modern and the exact native template permits it. Existing
operations keep their former policy; only operations created after admission select the
successor. Live leases and unresolved effects/reservations require native reconciliation
before adoption. Failed Opening continuation uses the existing versioned assessment and
recovery fence; failures remain in history. A zero-work capacity continuation also supports
the versioned membership policy, retaining its original causal/fencing requirements.
Pay-reservation races cancel only a proven never-sent intent without dispatch or reservation,
record its denial, and create a distinct frozen route intent. Unknown sends cannot enter
that path. No terminal history or accepted content is rewritten.

The applicable engineering matrix is the focused routing, budget, Pack, owner/output-contract
and quality tests; PostgreSQL channel accounting, native Pack admission, Opening succession,
clean installation and previous-head migration; native CLI admission; and the controlled
process `test_creative_validation_native_controlled_process_to_internal_acceptance` in
`tests/integration/test_synthesis_formation_postgres.py`. Run integration modules serially
in a disposable database because their cleanup shares Authority tables. The controlled
process supplies synthetic auth and responses, exercising the real entry, renderer,
process protocol, state owners and recovery; it proves no real membership entitlement,
paid-account permission, literary quality or strict release qualification. Before deployment,
run the separately governed full same-release matrix below and authorized real main-chain
validation. Real-call evidence that was not collected remains `NOT_RUN`.

## Credentialed Provider qualification

The cost-aware router replacement is not release-qualified. In `production`, model
selection is centralized in the Provider gateway composition; in `validation`, the
existing explicit-profile qualification path remains available. Setting
`NOVEL_FORGE_PROVIDER_ROUTER=quality-cost-v1` also selects the router in an isolated
validation environment. DeepSeek requires `DEEPSEEK_API_KEY` from the process secret
environment, a positive `NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL` and
`NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT`. Never put credentials into task contexts,
model-call assets, pricing policies or command-line arguments.

DeepSeek JSON mode requires both the API `json_object` setting and an explicit JSON
output example in the prompt ([official guidance](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)).
The opt-in `config/capability_packs/artifacts/story_planning_creative_json_template.md`
provides a schema-valid creative output shape without story facts. Bind it as a new
Prompt Template artifact in a reviewed Pack version, retaining the existing system,
Skill, inputs and output schema. Compile, approve and activate the exact release before
freezing a new Producer-scoped diagnostic grant. Existing default and frozen templates
remain unchanged; their qualification cannot silently cover the changed prompt.
Malformed or multiple-object responses fail strict parsing and retain the final text,
hash, parser location and billable usage. Do not strip a format header to accept a
failed result or retry it automatically. Thinking `low` remains an explicit route
choice; changing the prompt does not authorize a different model or spending limit.

A reviewed Planning Context Policy may explicitly set
`provider_output_modes` to
`{"creative.candidates.generate":{"deepseek":"STRICT_TOOL_V1"}}`.
Bind `config/capability_packs/artifacts/story_planning_strict_tool_template.md`
with that policy before compiling the new Pack. This freezes a distinct
`deepseek-chat-completions-strict-tool-v1` envelope with the full output schema.
Its Beta request supplies one strict `submit_structured_result` function; function
arguments carry the result and do not execute another tool or Authority operation.
Thinking mode keeps its chosen effort and uses no forced `tool_choice`.
The conservative request bound includes the serialized tool/schema overhead before
routing and again at admission. The transport accepts only closed objects whose
properties are all required; unsupported schema shapes fail before dispatch. DeepSeek's
unsupported string-length/array-cardinality keywords stay in the frozen full schema
and the original native validator, although the transport projection omits them.
Missing, multiple, wrong-name or malformed tool results fail with retained usage.
Strict results retain exact final tool arguments and their hash before domain validation;
this is unapproved Provider evidence, not accepted prose. Downstream schema rejection
retains the parsed result, bounded validation error and original usage/cost receipt.
No JSON-message fallback, output repair, automatic retry or qualification transfer
occurs. Tasks without this explicit policy and previously frozen requests retain their
original protocol. See the [official strict-mode contract](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/).

`novel-forge authority-provider-routing explain --project-id <id>
--task-context-file <path>` performs no inference. It projects current benchmark and
retry evidence through the canonical runtime composition and current ledger; actual
dispatch rechecks locked authoritative budgets. The context includes a stable key, work,
operation, attempt, task type, input/output estimates and declared quality requirements.
Optional `request_input` and `cache_prefix` bind the business input and reusable prefix. `replay --project-id <id> --decision-id <id>`
reads the immutable decision. `metrics --project-id <id>` projects routing counts,
settled/reserved cost, usage and benchmark statistics. These read operations require
the existing `content.authority.query` permission. Estimated upper bounds must not be
reported as actual billed cost. Missing calibrated benchmark evidence blocks routing;
operators must not seed fixture scores as production quality evidence.

To consume an independent sampling Project, configure its native `PROVIDER_ROUTING`
policy with `benchmark_exports`, then configure the production Project with
`benchmark_source_bindings`. Use the existing routing-policy configure entry, as an
authenticated operator authorized for both Projects. Each binding includes the exact
export and `source_policy: {policy_version, content_hash, operation_id}` returned by
the source configuration. Exports identify the target Book, task, candidate/model revision,
producer hash, campaign/manifest, finite expiry, and exact observation asset/hash pairs.
Keep the source's other policy fields and grants when selecting the new version.
Query or explain before dispatch; missing independent evaluation still blocks admission.
Removing an export from a newly selected source policy revokes new use without rewriting
old policy Operations or Effect receipts. Do not replace exact observations with `latest`.

For a current scoped explanation, copy `producer_contract` from a native frozen
RoutingDecision into the task context. Native dispatch builds it from its
actual Prompt/Skill, Context policy, provider view and Schema identities; a workflow does
not choose its model through this field. Omitting this contract keeps prospective
selection cold-start blocked. `metrics` reports separate `producer_contract_hash` cohorts;
`LEGACY_PRODUCER_SCOPE_UNKNOWN` is historical diagnostics, not reusable qualification.
Ordinary Planning generator schemas contain sample-specific const/enum bindings. Their
routing identity preserves types/cardinalities, the schema family and owning factory
source hashes, while Provider admission retains the complete bound schema. Changing
factory code invalidates that cohort; changing only input IDs does not. Provider-stage
review/evaluation schemas keep their exact schema hash. Judge calibration and risk/length
compatibility still need their own governed evidence; producer identity does not supply it.

`EFFECT_RETRY_DEFERRED` means the latest durable dispatch has an active rate-limit or
availability backoff. Do not create a parallel task to evade it. Inspect the referenced
dispatch and retry after its deadline. Availability snapshots cover the same project and
model; Pro high and max share that model's cooldown. Historical decisions keep the
original availability evidence. Current cooldown defaults are runtime policy, not a
Provider service guarantee.

`configure --project-id <id> --workspace-id <id> --idempotency-key <key>
--policy-file <path>` uses the existing versioned policy command and requires a local
operator with `book.authority.execute`. Policy content contains `policy_version`, an
audit `reason`, and `task_overrides` with `work_id`, `task_type`, `risk`, `quality_floor`,
optional `chapter`, positive `latency_sla_seconds` and `escalation_reason`. Overrides
cannot lower the default floor/risk or select a Provider/model.

For initial Planning evidence collection, the same policy may contain
`bootstrap_authorizations`. Each grant requires `authorization_id`, audit `reason`,
`environment: validation`, `purpose: BENCHMARK_CHALLENGER`, `production_eligible: false`,
exact `book_id`, generation `task_type`, `logical_key`, `generation_idempotency_key`,
the canonical `input_versions_hash`, `command_hash`, `producer_contract_hash`, `candidate_id`, `model_revision`, timezone-aware
`expires_at`, positive `maximum_calls`, `maximum_tokens`, `maximum_amount`, and `currency:
USD`. The current challenger lane supports priced DeepSeek execution. A local operator
passes only `routing_bootstrap_authorization_id` to the existing Planning generation
command; admission freezes the governed grant. Production environments reject it.
`command_hash` covers the normalized public Planning command, including default fields,
with only the authorization ID and server snapshot omitted. Multi-stage world preparation
requires its own governed evidence and is excluded from this single-stage sampling grant.
The router emits `BENCHMARK_SELECTED` with the original quality exclusions preserved;
Kernel checks immutable decision identity, expiry and locked aggregate quota before send.
Reusing an authorization ID in a later policy version does not reset its quota.
Historical replay uses the frozen grant, while a new send must still precede expiry.
New sampling admission requires the producer contract hash. Router selection and Kernel
dispatch compare it with the actual Prompt/Context/Schema contract; changing that contract
requires a new sample version. Historical unbound grants remain readable for reconciliation
but cannot authorize another inference. Arms sharing one sample bind the same producer
contract as well as equivalent input identities.
Candidates remain ineligible for production even after an explicit independent evaluation.
No automatic judge or repair is authorized by the generator grant. Independent calibrated
evaluation remains necessary; a model cannot establish its own qualification.

For cumulative sampling, every new grant in a campaign project includes `campaign` with
exact `campaign_id`, `manifest_hash` (SHA-256), `sample_id`, `group_id`, `partition`
(`DEVELOPMENT`, `CALIBRATION`, or `HOLDOUT`), positive `maximum_calls`, `maximum_tokens`,
decimal-string `maximum_amount` and timezone-aware `expires_at`. Grant limits cannot
exceed campaign limits. Policy versions retain authorization and campaign identity;
renaming a run, sample or authorization does not reset the cumulative budget. A data group
or identical input-version set cannot cross partitions, and identical inputs cannot
acquire another data group. Changing sample IDs inside one group does not increase
independent qualification counts. These checks do not detect
semantic paraphrases or replace an independently frozen dataset.
Reference-evaluation arms also retain the exact label binding and protocol within one
sample; changing labels after a failed arm requires a new declared experiment sample.
`novel-forge authority-provider-routing campaign --project-id <id> --campaign-id <id>`
reads all historical grants, Operation states, output/hash references and native
reservation/effect references, including failures and unresolved outcomes. `RECONCILIATION_REQUIRED` requires native ExternalEffect recovery,
never a new grant to resend. This command reports bootstrap sampling usage only. For a
whole campaign, select `creative-provider-campaign-budget.v4` through the existing
`authority-creative-budget configure` command. Its immutable `comparison_budget` binds
`experiment_id`, `manifest_hash`, `expires_at`, `accounting_basis: MIXED`, one `SINGLE`
project/Book arm and `chapter_ranges.PRODUCTION`. `shared_total`, `project_total`, each
phase allocation and each `authorized_cumulative_caps` entry contain `calls`, `tokens`
and decimal-string `priced_usd`. Phases are `REFERENCE`, `SCREENING`, `CALIBRATION`,
`HOLDOUT`, `SOURCE`, `DESIGN`, `PRODUCTION`, and `REPAIR`; phase allocations sum to the
project and shared totals. `entitlements` contains separately capped `provider`,
`authorization_ref`, `calls` and `tokens` lanes. The Codex lane must match the configured
account authorization. Existing project/Book controls continue to apply as additional
constraints. This plan does not itself authorize payment or confer A/B independence.

An explicitly authorized monetary increase appends `comparison_budget.previous_policy`
with the selected `policy_version`, `policy_hash` and `contract_hash`, and new authorization
and evidence references. Only priced allowances may increase; manifest, expiry, Book,
calls, tokens and entitlement lanes remain frozen. The same configure command validates
this lineage, and campaign queries include earlier grants, reservations and settlements.
Old requests retain their original limits. An increased ceiling is never reported as usage.

To move allowance between phases without increasing the approved ceiling, select
`creative-provider-campaign-budget.v6` through the same native configure command
(`creative.experiment_budget.configure@1.7.0`). Retain campaign, manifest, Book, expiry,
aggregate caps, entitlement lanes and business permissions. Bind `previous_policy` to the
exact selected v4 or v6 policy; `reallocation` contains timezone-aware `authorized_at`
and `carry_forward` from the native ledger, with accounted reservation IDs, totals, phases
and entitlement usage. Every authorized phase cap must equal its new allocation. Selection
rejects stale usage and allocations below consumed or unresolved reservations. A production
renewal cannot use this contract to acquire diagnostic allowance. Dispatch checks the current
shared ceiling and the request's frozen authorization against consumption in its own policy
lineage; successor reservations cannot retroactively consume an earlier phase cap. Old
request identities, expiry and unresolved outcomes remain frozen. This contract grants
neither model qualification nor spending beyond the existing ceiling.

For a new, explicitly approved finite production window, use
`creative-provider-campaign-budget.v5` through the same configure command. Preserve the
campaign, manifest, project and Book and bind `previous_policy` to the selected native
policy. `renewal` records the original timezone-aware `authorized_at`, `additional_total`
and `carry_forward` (accounted reservation IDs, shared total, phases and entitlement
lanes). Read that snapshot from the native ledger; a concurrent ledger change rejects
selection and requires a refreshed snapshot. The new cumulative total equals conservative
historical usage plus the approved addition, with additional allocations only in DESIGN,
PRODUCTION and REPAIR. Retain old account lanes at their carried usage and bind the new
lane to the new authorization reference. New-window consumption has its own shared cap;
settling or releasing old reservations cannot enlarge it. Use a new evidence hash and
reference for the actual author approval. Expiry runs from that approval, not deployment.
Old frozen reservations cannot borrow the new expiry. UNKNOWN still needs reconciliation.
Do not substitute a new campaign, rename a reservation or release historical holds to
configure a renewal. Separate model grants and Book review boundaries remain required.

The configure command verifies the existing authorization-evidence file; phase grants
retain explicit Source/design/chapter business scope. `authority-creative-budget query`
returns cumulative native-ledger usage by phase, priced USD, unknown-cost entitlement
calls and account lanes, including prior usage and unresolved calls. Changing a run key,
policy version or evidence directory cannot reset consumption or rename its frozen plan.
Expiry is rechecked before send. Settlement after expiry remains possible; actual usage
above the authorized ceiling is recorded and held for reconciliation. Model-side token
consumption remains observable only to the extent supported by its actual receipt.
Development and holdout
observations are excluded from automatic qualification feedback. Release of held-out
evidence and full-family reference-evaluator bootstrap remain implementation gaps.

For an explicitly authorized Codex validation control, the existing bootstrap grant
sets `accounting_basis: ACCOUNT_ENTITLEMENT`, `cost_authorization_ref` to the configured
account authorization, `maximum_amount: null`, and `currency: UNKNOWN`. Its finite
`maximum_calls`/`maximum_tokens`, campaign identity, manifest and expiry must match the
selected `creative-provider-campaign-budget.v4` policy and fit its Codex entitlement
lane. The common campaign `maximum_amount` still caps priced USD; it does not price
subscription usage. Omitting the whole-campaign authorization fails before reservation.
Use the existing governed task policy for a justified high-risk control; bootstrap
does not relax the production escalation threshold, account capacity, model revision,
availability or Provider admission. Kernel rejects cross-account or priced/subscription
substitution. Expired calls can still reconcile and settle their original reservations.
The campaign query's `priced_settled_or_reserved_usd` excludes subscription use;
`settled_or_reserved_usd` is null when entitlement use is present, and `entitlements`
reports its calls/tokens with unknown USD. Neither field verifies an invoice.

For Source sampling, POST `/product/source-imports/provider-samples?dry_run=true` with
`project_id`, `source_operation_id`, `authorization_id` and `idempotency_key`. The local
operator preflight reads an existing frozen Source Provider task and returns its exact
command/input hashes without admission or a Provider call. Register the matching grant
through the same routing policy command, with `book_id: source-corpus:<project_id>` and
the returned native task (`source.content.classify`, `source.deconstruction.observe`, or
`source.mkaos.extract`). Source grants require a campaign. POST the identical request
without `dry_run` to admit the sample; the existing Source Import worker executes it.
The current chapter-reading observation and review handlers retain their original
Context, Schema and source-consumption gates. Reprocessing commands are not sample inputs.
Read sample outputs through the existing import work and campaign queries. Replaying the
same request preserves its Operation and settlement; `SOURCE_SAMPLE_RECOVERY_REQUIRED`
blocks a new request for the same campaign/sample/model arm, including unknown outcomes.
For a terminal arm with no ExternalEffects or proven terminal Effect/Dispatch failure,
pass its exact `predecessor_operation_id`
in a new explicitly granted request. The replacement preserves operator, input versions,
original Source task and full campaign sample, and appends native causation lineage.
Successful, in-flight or unknown Effects cannot be replaced; use existing receipt
reconciliation. Failure usage remains settled or held under the original reservation,
and a successor consumes remaining campaign allowance. Successful sample receipts may
be projected after grant expiry, but new sends still require unexpired authorization.
Sample outputs never advance the original Source import or become production knowledge.
The current sampler does not automatically release Source observations into Router quality
qualification; independent task-specific evaluation and feedback admission remain required.

Chapter generator sampling uses `POST /product/production/chapter-authority/provider-samples?dry_run=true`
with `project_id`, `actor_id`, `source_operation_id`, `authorization_id`, `idempotency_key`
and optional `predecessor_operation_id`. The trusted Principal supplies the effective actor.
The source must be an existing frozen native `chapter.memo.generate`, `chapter.draft.generate`,
`chapter.revision.apply` or `chapter.canon.extract` Operation at the current formal
definition version `3.8.0` or its frozen published predecessors `3.4.1`/`3.5.0`/`3.6.0`/`3.7.0`.
The returned task types are respectively `memo`, `draft`, `revision` and `canon_extraction`;
use the returned book, command and input identities in the same campaign grant. Dry-run
performs no admission or Provider call. Admit the identical request without `dry_run`.
The existing Chapter worker consumes its own root Operation through the original handler,
Router, Provider admission, Attempt, ExternalEffect and Agent Runtime. It does not join or
advance the source Chapter Saga. The worker root is the single registered Saga step;
Saga coordination follows terminal worker completion, so ordinary Chapter orchestration
cannot admit production descendants from a sample.

Install the separately approved `chapter_provider_sampling@2.2.0` binding through
`install_chapter_validation_pack(..., provider_sampling=True)` in the existing Capability
Pack authority workflow. It derives `<configured_chapter_pack_id>.provider_sampling`
from the supplied Chapter pack and retains its Prompt, Skill, Schema and source isolation.
New sampler definitions use version `2.2.0`; sample-target review/rereview use `2.3.0`.
Their source handler semantics bind the exact native source version separately from
the sampler Operation version; frozen `2.0.0`/`2.1.0` keep their original codec and policy.
Their derived Pack advances the supplied Pack major version (currently `2.12.0` to
`3.12.0`) under its distinct sampler Pack ID. Published `1.0.0`/`1.1.0` and `2.0.0`/`2.1.0` definitions,
original source `3.4.1`, and frozen Pack snapshots retain their original identities and
hashes. Idempotent replay selects the persisted definition and successful receipts; it
does not register a replacement definition or dispatch another call. Unknown definition
versions fail closed before materialized-result recovery. Reference preflight uses the
persisted request version and its earlier frozen Pack when a recovery Attempt has no
snapshot. Without any snapshot it requires that exact version's approved deployment;
a newer binding cannot substitute for a missing historical binding.
Only the four generator nodes remain; their typed completion requires an `INELIGIBLE`
`chapter_provider_sample` and its successful model Effect. The expanded external input
contract accepts the frozen predecessor artifacts but never commits those sampled outputs
as formal Chapter/Canon assets. Formal Chapter definitions and quality gates are unchanged.
Chapter producer compatibility projects Context allowance onto the exact physical types
reachable by that stage and Tool allowance onto that stage's default-deny permissions;
Prompt, Schema, remaining Context policy and all original materialization hashes remain
bound. This prevents administrative workflow differences from fragmenting identical
producer evidence without borrowing quality from different semantic contracts.

`GET /product/production/chapter-authority/provider-samples/{operation_id}?project_id=<id>`
returns the frozen command, sample content, output hashes, Attempts and Effect references.
Successful replay materializes no second Provider call. Unknown outcomes retain their
reservation and use the same native receipt reconciliation; they cannot be replaced.
A terminal no-effect/proven-failed arm may have an explicitly granted successor preserving
its predecessor, actor, input and campaign identity. Failure model-call evidence is retained
separately from later successful recovery evidence. Kernel receipt recovery and Chapter
synchronous completion use the same settlement policy: missing real receipts retain
conservative usage, explicit fixture receipts remain fixtures, and subscription charges
remain unknown rather than zero. A successful sample alone supplies no quality score.
Current independent adjudications are projected separately into Router observations as
described below; the sample itself remains ineligible.

World sampling uses `POST /product/production/book-authority/books/{book_id}/world-provider-samples?dry_run=true`.
Supply `project_id`, `book_id`, the authenticated `actor_id`, `source_operation_id`,
`stage` (`world_candidates.generate` or `world_candidates.evaluate`), `authorization_id`
and a stable `idempotency_key`. The source is the original native ChapterPlan Operation
with its persisted World source, Context and producer materialization. The read-only
response supplies exact input/command hashes and `producer_contract_hash`; it performs
no Provider call and does not grant spending authority. An unprepared source fails closed.
Install a separately approved validation Pack with `build_world_sampling_pack_profile`
and the existing `install_longform_validation_pack`; its ID is the configured Planning
Pack ID plus `.world_sampling`. Keep its Prompt, Skill, Schema and policy artifacts equal
to the source producer, and register the matching native sample definitions.

Freeze a campaign grant for the returned hashes and producer identity. World generation
requires `BENCHMARK_CHALLENGER`; World evaluation requires `REFERENCE_EVALUATION` and
native adjudications for every `<transition_id>:<Director dimension>`. Each adjudication
binds the exact generation target, chapter, protocol and independent blind authors.
Label scores use 0–100; observed native Director scores use 0–1 and are multiplied by 100
only for agreement comparison. Labels stay outside Provider Context. Recorded disagreement
is retained; neither agreement nor World rule validation activates a calibrated reviewer.

To evaluate a calibration generation directly, supply `generation_sample:
{asset_version_id, content_hash}` for its exact native `world_provider_sample` output.
Its originating grant must be `BENCHMARK_CHALLENGER`, and its original ChapterPlan,
World source and generator Context must match this request. Record independent native
human evaluations and adjudications with the same `reference_sample` binding; Content
uses version `2.3.0` for this World annotation scope. Reuse their exact references in
`reference_evaluation`. No label enters the Provider prompt.
Install `build_world_sampling_pack_profile(..., reference_samples=True)` through the
same Pack authority; it binds `world_provider_sampling@1.1.0` and
`world.provider.sample.evaluate@1.1.0` under `.world_reference_sampling`. Its approved
producer artifacts remain those of the original Planning pack. Preflight derives and
hashes the Director Context using the native World task factory; execution freezes it
under the sample Operation as `INELIGIBLE`. No formal generation or earlier Director
Context is required. Invalid or mismatched source samples fail before dispatch; their
original sample records remain available for failure accounting.

Replay the POST without `dry_run=true` to run or resume through the native Content
scheduler and Planning execution port. Query
`GET /product/production/book-authority/books/{book_id}/world-provider-samples/{operation_id}?project_id=<id>`
for frozen inputs, Attempts, Effects, raw sample and validation/reference results.
Successful replay consumes its existing result. Unknown outcomes retain their budget
and reconcile; a renamed request cannot replace them. An explicitly granted terminal
no-effect/proven-failed successor supplies `predecessor_operation_id` and preserves
the actor, task, reference labels and campaign arm. Kernel causation and cumulative
campaign accounting retain every predecessor. These samples cannot create a World action,
active plan or production knowledge. Trusted evaluator activation and publishing qualified
World feedback remain required work; a successful reference sample alone supplies neither.

The same Chapter endpoint supports native `review`, `rereview`, `quality_structural`,
`quality_commercial`, `quality_source_originality`, `quality_longform`, and
`quality_platform` reference tasks. Supply an existing frozen native reviewer Operation
and `reference_evaluation: {protocol_version, adjudications: [{asset_version_id,
content_hash}]}`. Each reference must be the successful immutable output of
`quality.adjudication.record`, supported by at least two blind
`quality.human_evaluation.record` outputs for the exact target draft, chapter, dimension,
protocol and evaluation version. Native author identities must match the recorded human
and adjudicator identities and differ from the candidate generator and sampling operator;
the adjudicator is separate from the blind evaluators. These records require actual
independent human input. A coding agent's labels cannot be submitted as human evaluations.
The software checks provenance and declared independence; it cannot certify a person's
judgment or turn subjective labels into universal truth.

Model-only references are a separate requested contract, not HumanEvaluation or human
calibration. The current native reference path requires human annotations. An explicit
`codex-router-models.v1` catalog can configure task-scoped Codex models, but it does not
create model reference evidence. A frozen model panel requires two isolated
blind executions and a third adjudication, all binding the exact subject, author baseline,
policy, Producer, actual ModelCallLog and Kernel receipt. Same-model executions remain
correlated model consensus; selection alone cannot qualify a model. Do not replace an old
human reference, frozen route or budget when enabling a model panel. Model reference
creation, native record/adjudication and reference feedback
must be implemented and verified before dispatch or production admission can use that basis.

The model-only contract uses separate `model_reference_evaluation` and
`model_reference_adjudication` assets. Each evaluation binds the exact subject, author
baseline, policy, Producer contract, and a successful native ModelCallLog/ExternalEffect
receipt. Two blind evaluations require distinct native Operations, Attempts, Effects and
model sessions; a third independent execution adjudicates their frozen outputs. A panel
using one model family declares its correlation and remains `MODEL_CONSENSUS`, never
HumanEvaluation or reader preference. Reference consumers validate the native source
chain again and keep model-consensus qualification separate from human calibration.

Planning bootstrap and reference provenance must read the exact admitted execution
version, rather than assuming the historical `1.16.0` contract. The current supported
candidate-only versions are `1.16.0`, `1.17.0` and `1.18.0`; each retains its frozen
schema, requirements and semantic profile. Future or adjacent version strings are not
compatible by inference. Registry, World sample origin and reference subject checks
must agree on that bounded version set. This compatibility repair does not reinterpret
older assets under the current profile or waive a profile hash mismatch.

Reference coverage must include every dimension of the selected Quality group; review
and rereview use respectively `review_decision` and `rereview_decision`. Freeze an explicit
`REFERENCE_EVALUATION` grant with the exact binding and producer contract. Install the
approved `<configured_chapter_pack_id>.reference_sampling` pack with
`install_chapter_validation_pack(..., provider_sampling=True, reference_sampling=True)`;
its native binding is `chapter_reference_sampling@2.2.0`. Reference labels are checked
before inference and compared with the exact successful ModelCallLog afterward. They
never enter Provider task inputs. The sample retains status agreement, score-range
agreement and all reference hashes separately, with `calibration_claim_allowed: false`
and `production_qualification_eligible: false`. Replay and unknown-result reconciliation
retain the same Kernel budget and reference scope. This entry reuses existing native
review tasks and labeled drafts; authoring a new reference corpus, admitting a calibrated
evaluator and closing generator feedback are not implied by this sampling path.

The same Chapter sample preparation endpoint supports `chapter.canon.propose` as the
`canon_support` task. Preparation without reference labels returns the exact extracted
claims, source prose/hash, evaluation dimensions and required annotation fields under
`canon-support-independent-reference.v1`; it does not dispatch. Record two actual blind
evaluations plus a distinct adjudicator for every claim (or the explicit no-change
dimension), with source Unicode locations and reasoning, then supply their immutable
adjudications as `reference_evaluation`. Admission refuses missing labels. Negative and
uncertain support samples remain inspectable and never advance Canon. New v12 Router
decisions require independent HIGH-risk reference agreement for this task.

To annotate a completed Chapter generator sample, use the existing
`POST /product/content-authority/commands` with `quality.human_evaluation.record` or
`quality.adjudication.record`, the ordinary label payload and
`reference_sample: {asset_version_id, content_hash}` inside that payload. Freeze the
same sample in `input_assets`; adjudication also freezes its human records. The
authenticated local operator must match `evaluator_id` or `adjudicator_id`. Admission
selects the separate `2.2.0` definition and verifies the successful native sample,
its original campaign grant and exact hash again during execution. Other inputs retain
ordinary eligibility checks. The sample remains ineligible and cannot become accepted
prose, Canon or production knowledge. Record actual independent labels only: this
input exception supplies no human expertise, reader preference or reviewer admission.
To review that sample, use the Chapter provider-sample endpoint with the original
generator `source_operation_id`, `generation_sample: {asset_version_id, content_hash}`,
`reference_stage: "review"` for a draft sample or `"rereview"` for a revision sample,
and independent `reference_evaluation` adjudications targeting that sample. The original
native generator must be respectively `chapter.draft.generate` or `chapter.revision.apply`.
Install the approved Pack with `install_chapter_validation_pack(...,
provider_sampling=True, reference_sampling=True, reference_samples=True)`; this uses
`.reference_samples`, `chapter_reference_sampling@2.3.0` and version `2.3.0` of the
native review sample definitions. Preflight returns the actual reviewer producer identity,
including its Skill and Schema, for the grant. It performs no persistent admission or
Provider call; any provisional Pack canary assignment is rolled back with its read unit
of work. Existing attempts reuse their frozen Pack instead of resolving a new deployment.
The original generator inputs and sample stay bound through input hashes, Kernel lineage,
Provider admission and shared campaign accounting. Each review consumes the `REFERENCE`
allocation; its business Chapter still comes from the original generator. No formal
review Operation or accepted draft is required for this sampling call, and the ordinary
Chapter Authority still refuses the ineligible sample as a production input. Quality-group
sample targets remain a separate gap. `novel-forge authority-provider-routing metrics` reads the
same native reference outcome projection used by later decisions. For reviewer tasks,
inspect `REFERENCE_AGREEMENT`, `reference_label_strata`, evidence class, producer hash
and outcome references separately from generation quality or accepted prose. Fixture
human labels, broad score ranges, absent positive/negative strata, duplicate prose,
retries and holdout evidence cannot establish reviewer eligibility. A disagreement is
retained as an evaluator failure. This native feedback supplies routing evidence; it does
not activate a formal Quality profile or promote any sample.

For semantic evaluator reference sampling, first register independent operator labels
through `story_design.review.author` with the exact benchmark candidate as its only
candidate input. This authoring command may read the ineligible candidate solely for
review; it cannot activate the candidate. Its successful immutable output must have
`ground_truth_claimed: false`, `human_preference_evidence: false` and
`provider_evidence_claimed: false`. Its native author must differ from the generation
and evaluator actors. Changing a caller-supplied actor string is not authentication.

To bind trusted semantic references, record actual independent HumanEvaluation and
AdjudicatedEvaluation assets through the same Content commands, using
`reference_sample: {asset_version_id, content_hash}` for the exact Planning benchmark
candidate. Admission chooses `2.4.0`, validates its native generation/grant and preserves
`CANDIDATE / INELIGIBLE`. Use dimension `<layer>:<criterion>` for every canonical
qualification criterion, `PASSED` or `FAILED`, and one consistent protocol and Chapter/Arc
scope. Freeze at least two independent human records per adjudication; the evaluator
and generator cannot author those labels. These commands record real supplied labels;
the Coding Agent must not manufacture human evidence.

The production page exposes an authenticated author form for native Planning diagnostic
samples. `GET /product/content-authority/reference-samples` resolves exact candidate and
Producer contracts; `POST /product/content-authority/reference-evaluations` derives the
workspace, subject and author on the server and uses the existing Content operation.
The form requires an exact quotation, rationale, preserved strengths, actual reviewer
role, scope and explicit human confirmation. It does not preselect a judgment or claim
blindness. Local drafts survive sample switches and reloads; an ambiguous submission
keeps its original request and idempotency key for query or replay. An empty lookup is
not proof of rejection; only a conclusive validation rejection or an exact terminal
operation permits correction under a new key. Saving one annotation
does not replace independent human records or adjudication, qualify a model, or promote
the candidate. Never enter agent-generated judgments as human annotations.

Extend the ordinary `reference_evaluation` binding with
`adjudicated_reference: {adjudications: [{asset_version_id, content_hash}], scope:
{scope_type, chapter_start, chapter_end}}`. Its original operator review must agree with
every adjudicated criterion. Preflight rejects missing dimensions, scope drift and
overlapping authors before a Provider call. The immutable grant binds the entire extended
reference object. Successful outputs use `narrative-reference-agreement.v2`; subsequent
native routing reads that outcome through the same `REFERENCE_AGREEMENT` metric with
separate positive/negative coverage, producer/protocol/risk/context scope and fixture
exclusion. This does not promote a sample or establish literary quality or reader preference.

Generator feedback uses `native-generator-quality.v1`, not business acceptance or the
reviewer's own score. Chapter sampling preflight returns `generator_evaluation_contract`
when its original frozen producer identity is available. Its evaluation version binds
the task and producer hash; all labels for that score must use that exact version. Draft
and Revision use independently sampled Review/Rereview references; World and Planning use
their existing independent reference evaluation paths. Generator and model evaluator must
have different model identities. Memo and Canon use native sample annotations with the
contract's required semantic dimensions. At least two independent evidenced human records
and an independent adjudicator are required; never manufacture these records in a runner.

`GENERATOR_SCORE` uses the conservative minimum adjudicated lower endpoint. Broad or
unknown protocols remain unscored, and an unadjudicated calibration sample prevents
qualification of a selectively labeled positive subset. Failures and retries remain in
native evidence. The Registry groups frozen Provider inputs independently of campaign
names and also deduplicates observed content. A group or content used in development or
holdout is excluded from calibration. Current producer, model, risk and context scope must
match; replay of an older frozen decision does not confer new qualification. Inspect
`unadjudicated_generator_sample_count`, `generator_protocol_hashes`,
`partition_conflicted_sample_identities` and the frozen RoutingDecision before dispatch.
No sampling output becomes an active plan, Canon mutation, accepted draft or reader proof.

World sample preparation also supports `actor_0`, `actor_1` and `actor_2` with the frozen
original Actor contract and its private input. Use the returned generator evaluation
contract to annotate the exact sample through Content Authority; all four dimensions
(goal consistency, epistemic isolation, commitment continuity and action causality) are
required. Sample Actor proposals cannot enter formal World/Director preparation. Formal
World/Actor producer identity binds the schema factory and semantic shape, retaining
instance identifier type/cardinality while excluding only enumerated instance IDs.
Old incompatible schema identities do not acquire current qualification.

Longform reviewer sampling uses the Book prose-review `provider-samples` endpoint,
first with `dry_run=true`, against an existing exact frozen review Operation/window.
Install the separately approved reference sampling Pack, then register a matching
`REFERENCE_EVALUATION` grant with the returned command/input/producer hashes and full
reference binding. Native Content annotations require two blind humans and an independent
adjudicator across finding precision, missed relationships, evidence fidelity and disposition
fit. The resulting `INDEPENDENT_REVIEWER_SCORE` is distinct from generator score and
reviewer agreement. Sampling writes an ineligible report without official findings or
source mutation. Query the native operation output and routing registry; existing Effect
reconciliation and cumulative reference-budget accounting apply. Historical longform
`chapter=0` metadata derives scope only from the verified immutable accepted window,
never from a caller-supplied chapter number.

Use the existing `POST /product/production/book-authority/books/{book_id}/planning-evaluations?dry_run=true`
with the ordinary evaluation command plus `routing_bootstrap_authorization_id` and
`reference_evaluation: {asset_version_id, content_hash, protocol_version}`. The read-only
preflight validates candidate/reference lineage and returns the exact admitted payload,
`command_hash` and `input_versions_hash`; it grants no spending authority. Register a
versioned routing grant with `purpose: REFERENCE_EVALUATION`,
`task_type: narrative_semantic_evaluation`, the same reference binding and mandatory
campaign membership, candidate/model revision, cumulative quota and expiry. Its
`logical_key` is the candidate AssetVersion ID and `generation_idempotency_key` is the
evaluation request key. Then replay the same POST without `dry_run=true` in the validation
runtime. Existing Generator grants never authorize the evaluator's call.

The evaluator uses `story_design.semantic_evaluate@1.0.0`, a native Kernel Operation,
Attempt, Router, Provider admission, ExternalEffect and settlement. Each authorized
evaluator model arm has its own Operation without a production qualification head.
Migration 0139 enforces the reference grant/candidate/label gate and rejects reference
Operations from the domain qualification table. Only the candidate
and canonical dependencies reach Provider context; the service reads labels separately.
The materialized evaluation contains `narrative-reference-agreement.v1`, all criterion
agreements/disagreements and reference provenance. It remains `BENCHMARK_ONLY`, cannot
write domain qualification or advance/repair the candidate, and is returned by the
campaign query. Successful request replay performs no new Provider call. Unknown effects
still require reconciliation. For an immutable terminal no-effect/failure, submit a new
explicit grant and request with `reference_predecessor_operation_id` naming the latest
Operation for that candidate/model revision. Preserve the evaluator actor, candidate,
labels, campaign and sample. The grant binds the new exact command hash; Kernel causation
retains the predecessor and campaign usage stays cumulative. A renamed request without
this lineage is rejected. A succeeded Operation, known successful Effect awaiting result
projection, live retry or ambiguous remote outcome cannot be replaced by a fresh call;
recover/reconcile the original Operation first. Ordinary production evaluations retain
the existing candidate qualification head and Book Opening recovery gates.
Operator-proxy label agreement is not a trusted human label, literary quality, reader
preference or general evaluator admission score; it is not automatically promoted into
Router quality qualification. Trusted reference validation and scoped feedback admission
remain required before evaluator calibration can be claimed.

Optional Codex escalation requires `NOVEL_FORGE_ROUTER_CODEX_ESCALATION=true`, an explicit
`NOVEL_FORGE_CODEX_ESCALATION_MODEL`, positive `NOVEL_FORGE_CODEX_ESCALATION_CALL_LIMIT`,
`NOVEL_FORGE_CODEX_ESCALATION_CONTEXT_LIMIT`, `NOVEL_FORGE_CODEX_ESCALATION_OUTPUT_LIMIT`,
and timezone-aware `NOVEL_FORGE_CODEX_ESCALATION_VALID_FROM` / `VALID_UNTIL`, together with
the existing verified CLI/entitlement configuration.
`NOVEL_FORGE_CODEX_ROUTER_REASONING_EFFORT` selects the
Codex candidate effort explicitly (`low`, `medium`, `high`, `xhigh`, or `max`). Absence
retains `high` for historical compatibility; an invalid explicit value must fail closed.
The selected effort binds candidate identity, the routed request,
and the frozen creation configuration. A recovery must retain that identity. This does not
qualify a candidate or waive independent review. Unavailable configured lanes fail
closed; disabling the lane does not authorize a quality downgrade. Call limits count
accounted reservation generations, including paid retries, while released unsent calls
do not consume capacity. Shared usage locks prevent USD and entitlement reservations
from racing through global token/call caps.
Mixed Provider availability and phase USD allowances do not impose generation/review
role separation. A named model in a route template is still subject to Router selection.
Deployments requiring a restricted Provider authorization must use
`NOVEL_FORGE_ROUTER_PROVIDER_TASK_SCOPE`: a JSON object mapping every configured Provider
to a list of allowed formal task taxonomy names. An explicit empty list denies that
Provider all tasks; malformed, unknown or incomplete scopes fail closed. The Router
must reject a candidate outside its scope before cost/quality selection, including
benchmark and author-supervised decisions. Scope binds each routing request and the
creation freeze; changed scope cannot replay an old decision. Absence preserves legacy
unrestricted routing and is insufficient evidence of role separation. This restriction
does not replace legitimate qualification samples, independent blind evaluations,
adjudication or Capability Pack approval by a principal distinct from its compiler.
Without an explicit model catalog, the Codex Router candidate retains its historical
escalation semantics: two semantic failures, or HIGH risk with an explicit escalation
reason. `NOVEL_FORGE_CODEX_ROUTER_MODELS` accepts the exact `codex-router-models.v1`
contract with model, reasoning, role, tasks and context/output limits. Its `PRIMARY`
and `REFERENCE` roles require a matching finite account entitlement and ordinary
qualification. Model task scope is checked during selection, route materialization and
Kernel reservation. Models sharing an account authorization consume the same call
allowance; adding a model does not multiply quota. Catalog entries bind model revision
and the creation freeze. An unqualified primary still fails closed. This support alone
does not establish a model panel, literary qualification or a real first-chapter run.
Book Opening's immutable budget policy may explicitly add an `account_entitlement_lane`
with its Codex model, authorization reference/version and finite call/token quota. The
deployment supplies it through `NOVEL_FORGE_BOOK_OPENING_ACCOUNT_ENTITLEMENT_POLICY` as
JSON; composition requires an exact match with the configured Codex escalation or explicit
primary identity.
A priced envelope without that lane still rejects entitlement execution. Both lanes consume
the parent call/token budget; progress reports retain unknown entitlement monetary cost
separately from priced USD expenditure.

The native whole-campaign budget (`creative-provider-campaign-budget.v4` and its renewal)
separates priced USD allowance from account entitlement. The creation entry's frozen
accounting and resume adapter retains that distinction and validates the exact native
campaign grant, entitlement identity and business scope. A zero priced allowance permits
only entitled execution; it does not mean the entitlement has zero monetary cost.
The real creation entry validates the frozen campaign against the native budget before
checking mixed configuration caps. Codex retains its exact entitlement reference and
unknown monetary cost. A native positive priced allowance requires explicit positive
priced caps, each no larger than that allowance; it does not price the Codex lane.
Standalone entitlement smoke runs without a validated mixed campaign still reject
monetary caps. These configuration checks never replace Kernel reservations or native
phase and cumulative budget enforcement.
The adapter rejects a campaign presented as a legacy single-account budget before
initializing a Book. Historical single-account freezes retain their original semantics.

The current routing migration extends the existing versioned policy owner constraint
and adds a chain lookup index. It does not rewrite Provider identities or backfill
historical decisions. Planning semantic repair follows durable predecessor relationships
and freezes their Operation identities into subsequent routing decisions; task budgets and
failure/escalation bounds span that lineage. Unfinished legacy Provider executions retain
their original identity and require reconciliation. Independent quality calibration is
still missing for several task families, and no accepted real-Provider Chapter chain has
qualified this router replacement; production readiness remains `NO`.

Credentialed Provider qualification is intentionally separate from P0. The dedicated
runtime-qualification entry is `make real-provider-qualification`; native Source and
creation commands below also execute authorized real Providers. The D0 contract probe
and worker remain fixture-only and cannot send with a credential. The live runner requires a clean worktree,
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
evidence. `POST /api/book-completion/editorial-events` appends explicit POLICY,
SIGNATURE or REVOCATION events with expected-version CAS and trusted human identity.
`GET /api/book-completion/editorial-history` exposes current readiness. Signatures require
the exact current case source digest, complete prose review manifest/report and release
identity. Missing policy, named signatures, coverage or key-issue dispositions blocks
acceptance; generic Chapter/Arc preferences and AI review do not substitute. Changes
invalidate current signatures, preserve historical decisions and require reassessment.

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
Books must carry the identical frozen pilot configuration. PostgreSQL must match the registered migration head in
`architecture/manifests/migration-manifest.yaml`, with the normal
configured operator/worker permissions. The approved current Planning Capability Pack
must include the six Foundation generation capabilities and their qualification Skills;
the Chapter pack must include Memo, Review/Revision and Canon support. It does not seed
qualified story assets or call a Provider SDK directly.

Foundation-bound BookDesign v5/v6 semantic evaluation resolves the exact six active Foundation bindings,
including native `planning_generation_candidate` assets. Both dependency resolution and
Provider projection check their generator role, project, Book and candidate contract;
qualification verdicts remain provenance rather than evaluator input. The aggregate
projection has a `CONFIGURABLE_POLICY` limit of 131,072 serialized characters. Other
evaluation projections retain 65,536 characters. These bounds do not grant tokens or
calls: frozen route capacity and native budget admission still apply before dispatch.

Migration `0133` adds bounded semantic evaluation continuation for Formation's
`BOOK_DESIGN` stage. After an explicit native Formation resume, the same stage may
append at most two evaluation successors for the three named dependency/context
preflight failures, provided the failed Operation has no ExternalEffect. The same
candidate, frozen inputs and independent evaluator are retained. A current Formation
worker lease gates Operation, Attempt, Effect and dispatch transitions; the failed
Operation and prior evaluation generation remain terminal. Opening-bound recovery uses
its existing RecoveryIntent path. Other failures and unknown Provider outcomes do not
acquire this continuation policy.

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
For native v5 membership creation, a terminal `PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED`
with no external intent, reservation or frozen Context uses the existing Planning continuation
Authority automatically. The retained source remains terminal; a linked successor keeps its exact
story inputs and Pack while increasing only the single-task allocation within the configured
model capacity. Preflight must succeed before registration; no more than two successors are
allowed. An external intent of any status, including UNKNOWN, excludes this capacity path. Migration 0158 permits reconciliation of a previously admitted capacity successor with its verified candidate-repair cause; it requires the exact registered command and terminal zero-intent source. New successors use the failed capacity Operation as their causal source. Neither path rewrites terminal Operations or candidate provenance.
Planning repair routing retains failed model history. A native receipt binds the failed candidate or raw result, diagnosis hash, bounded repair number, exact lineage and changed Provider input. Only diagnosed content failures from that lineage cease to exclude the same authorized model for the new repair; identical requests, UNKNOWN, service failures, capacity limits and retry waits remain blocked. The send path revalidates the receipt against Planning facts. Generic Book ticks back off failed attempts for 30 seconds and do not rearm a dead letter against
unchanged Book/dependency evidence. Owner recovery uses the original creation `recover` command
after resolving the retained cause; author status shows `OWNER_RECOVERY_REQUIRED` with its error.

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

## Exact author edits and bounded closure campaigns

Use the existing Admin Editor after starting API, native workers and Web. Select a
project and exact Chapter asset, edit the text or selection, inspect before/after and
save a candidate. Adopt or reject that candidate explicitly; adoption does not accept a
chapter. The separate native-review action binds the candidate and decision versions to
Chapter admission. Review work and any Provider call still require the existing
qualification and budget authority. On a stale-version conflict retain the visible author
input and reload the base before creating a new candidate. Retrying an interrupted save
uses its pending idempotency key, rather than creating a duplicate candidate. When the
base belongs to the current unaccepted Book request, the review action uses
`/product/editor/book-reviews` to append a replacement generation. The previous run must
be terminal, its external effects settled and its budget reservations settled, released
or rejected; finish or explicitly cancel/reconcile it
first. Interrupted reservation/admission resumes through the same native Book request.
The replacement remains unaccepted until the ordinary Book acceptance gates succeed.

The backend `POST /product/editor/commands` accepts `scene_artifacts` and optional
`scene_separators` on `action: save`. Use one whitespace string per adjacent slot;
`[""]` joins two mapped slots without a paragraph break. The serialized text must equal
`text` byte-for-byte, while `allowed_ranges` uses the base text's Unicode code-point
coordinates. Preserve existing slot IDs/order and `used_fact_ids` within the retained
knowledge contract. `edit_intent: PLAN_STRUCTURE_CHANGE` returns
`AUTHOR_PLAN_CHANGE_REQUIRED`; submit the change through native Planning before editing
a replacement plan's prose. A save is still a candidate and must be adopted and reviewed.
Book cancellation retains successful unaccepted candidates and accepted history; it does
not authorize replacement or erase pending reconciliation.

The Editor's manuscript review panel consumes
`/product/production/book-authority/runs/{book_run_id}/prose-reviews`. Start freezes an
explicit `policy_version`, `window_codepoints`, `overlap_codepoints`,
`context_token_budget` and `maximum_windows`. Set `execution_mode=AUTOMATIC` for the Book
Follow-up worker to admit and execute the next bounded window for active runs; omitted
mode remains `MANUAL`, and the versioned Advance API remains available. Pause excludes
dispatch, resume continues the same frozen run,
and pending or unknown Effects reconcile before a newer accepted manifest is appended.
Incremental child runs retain valid old window evidence and freeze the new exact prefix.
Optional `relation_window_limit` adds bounded nonadjacent passage pairs retrieved by shared
text anchors. A hypothesis is unverified until the model report cites both exact passages;
missing evidence stays explicit. Query the report for covered/excluded ranges, unreviewed
pairs, unsupported relation classes, errors, Effects and dispositions. Text coverage never
means that all global relationships are verified. Use `/control` to
pause/resume and `/findings/{lineage_id}/disposition` for a version-bound author decision.
The Plan Change action requires exact target/proposed plan versions, current evidence
and a rationale. It creates a proposal, retaining the existing approval and future-only
invalidation boundary. A new source or policy requires a new frozen review run; identical
valid windows can be reused without pretending unreviewed text was read.

For a finding disposition, obtain `finding_digest` and `expected_version` from the current
report. `KEEP_HISTORY`, `CURRENT_CANDIDATE_REVISION` and `FUTURE_PLAN_PROPOSAL` retain an
unresolved issue until the appropriate review/approval consumer completes. A candidate
must bind the exact source run, lineage, finding and manuscript. `MINOR_EXCEPTION` requires
an enabled current policy naming the authenticated reviewer and permitting minor exceptions;
conflicting, major and blocking issues cannot use it. For `DISMISSED_WITH_EVIDENCE`, set
`consumer_asset_version_id` to the successful report in this same run whose located
counterevidence covers every challenged member. Unknown evidence or a rationale-only
request is rejected. Signatures may include `expires_at` in timezone-aware ISO 8601;
inspect editorial history and completion readiness for the valid group and exact blockers.

Original pilot and exploration materials and the separate Craft protocol are under
`config/production/narrative-closure/`. The authorization request there is a proposal,
not a grant. Register inputs through native author/Content/Formation commands and prepare
independent Book runs, accepted histories and adopted exact candidates before freezing a
manifest. Paired arms select `creative-paired-samples-budget.v5`; the separately published
Provider-calibration campaign retains `creative-provider-campaign-budget.v4`. Its participant versions, route policy, implementation and native stage caps
must match the selected finite authorization. Initialization, qualification, failures,
repairs and evaluation are included. No directory reset supplies new allowance.

```bash
PYTHONPATH=src .venv/bin/python -m scripts.narrative_closure_campaign freeze \
  --manifest <native-manifest.json> --output <retained-frozen-manifest.json>
PYTHONPATH=src .venv/bin/python -m scripts.narrative_closure_campaign run \
  --manifest <retained-frozen-manifest.json> --manifest-hash <sha256-digest> \
  --root <runtime-directory> --stage PILOT --output <new-evidence-directory> --execute
PYTHONPATH=src .venv/bin/python -m scripts.narrative_closure_campaign resume \
  --manifest <retained-frozen-manifest.json> --manifest-hash <sha256-digest> \
  --root <same-runtime-directory> --stage PILOT --output <new-resume-evidence-directory> --execute
PYTHONPATH=src .venv/bin/python -m scripts.narrative_closure_review export \
  --manifest <retained-frozen-manifest.json> --results <campaign-output-directory> \
  --reviewer <first-human-id> --reviewer <second-human-id> --output <blind-pack-directory>
```

Run six-task EXPLORATION only after exact pilot reading decisions and the native positive
stage grant. A system contract failure stops expansion. UNKNOWN effects must reconcile;
the runner never silently changes account, model or billing. Resume writes a new evidence
directory while retaining the same native manifest, database identities and ledger; changing
the output location grants no allowance. Offline reviewer responses
are recorded with `PYTHONPATH=src .venv/bin/python -m scripts.narrative_closure_review record --packs <blind-pack-directory>
--response <first.json> --response <second.json> --output <comparison.json>`; disagreement
and missing human review remain visible. These packs do not satisfy editorial signatures.

To try the corrected recurrence classification, explicitly set the frozen production
profile's `craft_budget_policy.schema_version` to `narrative-craft-budget.v2`. Selection
fills and freezes the complete `mechanism_cadence` map: `spatial-anchor` is CONTINUOUS;
`exchange-response-cost`, `subtext-pressure` and `choice-exposes-value` are EXPRESSIVE.
Unknown mechanisms remain EXPRESSIVE. V1 remains the default. This selection policy
change needs a separately frozen Craft intervention; it is not benefit evidence.

Optional actor isolation is configured in the frozen production profile, never enabled
by default: set `world_production_policy.version` to `world-production-policy.v2`,
`max_provider_stages` to actor count plus two, `max_candidates` no greater than actor
count, and `max_paths_per_candidate`, `max_preparation_steps`,
`planning_window_chapters` to one. Set `world_actor_experiment` to
`{"version":"world-actor-experiment.v1","actor_ids":["<approved-character-id>"],
"max_rounds":1,"max_actions_per_actor":1}`. Keep the existing bounded Context and native
budget limits. Each actor needs its own knowledge/belief entry in the frozen initial
StoryState or accepted reality, plus its approved goal. Missing private evidence blocks
before any actor call; another actor's knowledge cannot substitute. Actor source/proposal receipts persist under the same World Preparation
operation; resume that operation after reconciliation. Changing to unified generation
on a failed actor run is forbidden. A separate controlled comparison and finite model
allowance are needed to assess benefit, leakage, naturalness, cost and latency.

For accepted-state persistent intentions, freeze `world-actor-experiment.v2`; its
`world-actor-task.v3` keeps goals, steps and commitments across accepted windows. Only
Book acceptance completes an observed step. Deferred or abandoned commitments retain
their disposition lineage. If the complete required private/World projection exceeds
the v2 policy's 16,000-token ceiling, a new approved profile may explicitly select
`world-production-policy.v3`, with a context budget no greater than 24,000 tokens.
This changes only the configurable context ceiling: actor, round, action and window
bounds remain enforced. It does not change old frozen v1/v2 requests, add allowance to
their ledgers, or establish model qualification for the new input contract. The joint
engineering scenario freezes 20,000 tokens; Provider usage is still settled from receipts.

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

The recovery snapshot also resolves the current Narrative Search branch's latest
Planning generation when no semantic Evaluation exists yet. Its durable Effect,
Dispatch and Receipt evidence is required even before a Candidate is saved. A local
timeout without a proven Provider outcome remains `UNKNOWN_AMBIGUOUS`; missing
Candidate or checkpoint rows are not evidence that no request was sent.

When an Opening node returns its committed result and a late heartbeat observes the
released lease, the worker verifies the exact node receipt before preserving that
result. A lost completion response still resolves from the receipt as a replay.

Provider retry first reloads any existing ExternalEffect intent and reuses its frozen
request/admission identity. A historical remote intent that predates complete admission
is not upgraded in place or reinterpreted with the current meter; dispatch remains
fail-closed and recovery follows the owning effect policy.
Remote Provider and Codex CLI receipts preserve the returned raw response before local
Schema validation and normalization. A local crash after receipt persistence reuses
that response under its frozen output Schema identity; it does not authorize a second
generation call. Protocol or semantic rejection retains the raw result and failure
evidence for explicit, bounded repair. A remote `UNKNOWN` outcome still requires
reconciliation under its original idempotency identity.

Remote submit, query and callback use the host's persisted output contract: Schema,
Schema reference, request hash and execution identity. Provider evidence cannot replace
those fields. Conflicts retain the original response and rejection evidence; conflicting
or cancelled late callbacks cannot replace terminal results. Repeated callbacks bind
both the receipt identity and actual evidence hash. Older records recover their contract
from the original frozen request through existing admission and payload resolution,
without another generation call. Downstream normalization uses that recorded contract
rather than a generic domain asset Schema. Pack-free scripted fixtures retain the
explicit legacy Provider semantic contract and cannot prove real Provider behavior.
An observed Provider result is checkpointed before response processing; restart completes
that checkpoint from the saved result even when response-artifact persistence was
interrupted. Chapter, Planning and Source treat this phase as a sent request, and budget
accounting holds an unresolved reservation until reconciliation rather than releasing it.

The signed callback API persists the original body and verified receipt. Gateway-backed
Effects remain unresolved at ingress. The existing worker consumes that receipt through
the remote Backend under the original frozen contract and a current recovery Lease/Fence.
Kernel reconciliation moves recoverable work to `EXECUTING` before evidence processing;
local failure checkpoints it again without another generation. Duplicate payloads replay
their original receipt, and a conflicting message appends rejection evidence without
rewriting successful callback history. This path does not qualify a Provider whose
configured capability profile disables callbacks.

Changing repository Pack, Prompt or Skill files does not activate them in an existing
database or change an old request. Inspect the actual deployment, activation and frozen
materialization before an authorized run. Chapter Pack 2.12.0 requires System v3,
Template v9 and prose-generation-v4 identities; new Planning Pack 2.10.0 binds Operation 1.18.0, System v8,
long-outline-v3 and narrative-beat-design-qualification-v3, with unchanged stage methods
retaining qualification-v2 identities. Qualification profile v3 includes work applicability
semantics in its hash. New longform windows v2 include per-candidate creative baselines;
legacy v1 source identity must be explicitly selected when checking or resuming a v1 manifest. Screenplay requires prose-generation-v4 or quality-review-v3
and its separate adaptation schema. Historical artifacts remain available for recovery.
For new Chapter 3.8 work, selected style must be foundation-style-projection.v4 with
source-bound Book applicability. An explicit preparation asset override does not waive
this requirement. STYLE_PROJECTION_MIGRATION_REQUIRED blocks legacy v2/v3 before Writer;
inspect and explicitly migrate through the owning Content/Book commands. Frozen older
Chapter tasks retain their exact style and baseline rather than substituting the new one.
New retrieval plans bind writer_projection_version=accepted-writer-history.v2. Inspect
the exact semantic view and source/projection hashes: narrative history should contain
accepted prose and visible facts, with historical review/comparison/Provider evidence
outside Writer input. Current Revision diagnostics and authorized Quality evidence are
stage-bound exceptions. Malformed accepted prose rejects before dispatch.
For task compression, verify accepted-writer-history.v2 on the exact extractive trace,
its source content hash and selected-result hash. Do not relabel an old compressed
summary as a clean source; rebuild its Context from the original. Frozen requests still
recover under their original contracts; switching contracts requires an explicit new
owner command and new request identity after the original work is reconciled or stopped.
No resume command silently substitutes the current Pack.

Writer derived-index repair uses the existing PostgreSQL retrieval table. With an
authorized database URL in NOVEL_FORGE_DATABASE_URL, inspect a bounded batch first:

```sh
PYTHONPATH=src .venv/bin/python scripts/rebuild_writer_retrieval.py \
  --project-id PROJECT --book-id BOOK --from-chapter 1 --to-chapter 20 \
  --limit 100 --manifest .local/writer-rebuild/batch-001.json
```

Dry-run is the default and opens a read-only transaction. The private manifest contains
source/story data; retain it outside published evidence. Apply only the reviewed manifest:

```sh
PYTHONPATH=src .venv/bin/python scripts/rebuild_writer_retrieval.py \
  --manifest .local/writer-rebuild/batch-001.json --apply
```

For the next batch, repeat dry-run with the same explicit scope, --after-id equal to the
previous next_after_id and a new manifest path. Repeated apply is idempotent. A changed
source, scope or derived row rejects the entire batch; create and review a new dry-run.
Rollback only that manifest's derived changes, with the same conflict protection:

```sh
PYTHONPATH=src .venv/bin/python scripts/rebuild_writer_retrieval.py \
  --manifest .local/writer-rebuild/batch-001.json --apply --rollback
```

Rollback restores derived text/metadata/hash and leaves inline embedding invalidated;
new Writer discovery blocks again on legacy projection versions. Original accepted
assets, audit evidence and frozen requests are never rewritten. Old vector slots remain
as recovery evidence; new retrieval accepts only the current source/projection hash.
The repair tool makes no Provider call. Real vector regeneration remains
REBUILD_PENDING_REQUIRES_AUTHORIZED_PROVIDER through the existing embedding worker;
FALLBACK_ALLOWED permits the existing FTS fallback, while REQUIRED blocks until ready.
Do not mark vectors ready from a dry-run or scripted test.
Sample Pack versions follow the formal prose-review or screenplay Producer without
changing sample Workflow/Operation definitions or granting sample output eligibility.
Complete-request admission remains authoritative; a smaller projection or passing
Context receipt does not qualify the instructions or prove literary quality.

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
For an authorized diagnostic that must stop at its first failed or unknown call, set
`NOVEL_FORGE_CODEX_RETRY_POLICY=codex-no-transport-retry.v1` before freezing the route.
This opt-in policy uses the existing ChatGPT account and Codex backend with zero HTTP
and stream retries. Pair it with a one-call native grant per diagnostic sample and stop
the runner on failure; never change a frozen request to acquire this policy afterward.

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

New Book requests needing more than the legacy draft Context ceiling must explicitly set
`NOVEL_FORGE_BOOK_DRAFT_CONTEXT_PROFILE_VERSION=draft-context-profile-v3` before
Supervisor preparation, together with the bounded Book token budget and a compatible
approved Pack policy. The request freezes that profile; replay without this field stays
on v2. Increasing an environment budget alone does not upgrade an old frozen request.
The v3 owner maximum is 24,000 tokens, and effective Pack/request limits still apply.

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
The failed Operation remains terminal. Migration 0159 extends this contract to a
terminal DEAD_LETTER with retained known result evidence, an exact frozen native
lineage and no unresolved external effect. It preserves that terminal status and
its attempts; it cannot reopen a cancelled or unknown task. Missing or unknown receipts require
reconciliation; valid raw output with a persistence failure is not regenerated by this
contract-repair path. World diagnostics identify the field path, expected type and
actual type, including fields inside `world_foundation_json`. The World transition
request includes the complete inner typed contract, including ordered story time,
causal predicates and epistemic bases. A retained failed World proposal is repaired
within the same Chapter Planning allowance, against its exact source, Actor proposals,
knowledge selection and accepted frontier. It does not enter Chapter constraints as
accepted fact. A raw Chapter Plan repair reuses its already selected World action;
it does not repeat successful World preparation. A structurally valid proposal with a
blocked causal plan can use the same bounded repair chain only after the runtime
reproduces the exact hard gate from the frozen Reality and verifies the retained
Director receipt and settled usage. It does not convert a blocked action to NO_OP,
add accepted support or relax a causal predicate. The owning Planning result becomes
terminal with `WORLD_PREPARATION_RESULT_INVALID` and can create its diagnosed repair;
older `WORLD_PREPARATION_BLOCKED` retry checkpoints retain their history and replay
the original receipt before this classification, without another Provider request.
A new World proposal can obtain its necessary Director evaluation within that same
allowance only with the current generation's verified settled receipt, exact source
and frozen knowledge selection. This dependent evaluation receipt cannot authorize
another stage or repeat an unchanged request. Changed-input repair routing excludes
verified rejected results from transport retry counting while retaining all receipts
and the native two-repair bound. UNKNOWN, in-flight effects, service failures and
unchanged requests keep their existing blocks.

An exhausted Planning repair allowance is a durable owner wait, not a transport
retry. Creation completes only its coordination window with
`OWNER_RECOVERY_REQUIRED`, retaining the precise error and recovery instruction;
the Book remains incomplete. Automatic scheduling does not rearm that unchanged
checkpoint. Repeating owner recovery cannot grant another content repair. A genuine
author-intent change uses the existing approved future input path. An implementation
or execution-contract defect requires an accounted native contract successor; it is
not an author decision and cannot be fixed by increasing the old repair allowance.

The initial creation Story State is empty and is not chapter-zero acceptance. Current
World validation requires a knowledge/belief predicate for every approved character
actor, including ordinary actions and first perception. This is an
`UNRESOLVED_DESIGN_CONSTRAINT`: the original isolated Book is blocked before Chapter 1
because the requirement cannot distinguish information-dependent decisions from
initial actions. Missing structured knowledge is not evidence of an ignorant character.
Foundation approval alone does not supply an acquired fact. `NO_OP` and `DEFER` remain
actual narrative dispositions; they are not an initialization workaround. The retained
failed proposals, receipts and original two-repair bound must remain immutable while
this contract is repaired. No author approval is required to correct this engineering
classification within the already authorized original work.

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

## Controlled deployment and Book edition operations

Keep `NOVEL_FORGE_NO_MODEL_DISPATCH=1` while restoring/upgrading and checking a release.
The process brake applies before Effect preparation and immediately before transport send;
reconciliation remains available. Official workers emit health but do not claim historical
work under that brake. A project PAUSED decision also persists across process reconstruction.
Native no-send pauses retain their immutable RuntimeJob attempts and a guarded pause count;
they do not consume failure retries. Ordinary failures and UNKNOWN remain subject to their
original recovery and budget rules. Status/export list jobs waiting for dispatch control.
Resume is scheduling permission only; it never grants Provider qualification, account quota
or budget. Check the expected database identity, historical source and persistent volume;
a database name containing `test` is not sufficient evidence of a disposable ledger.

```sh
novel-forge authority-runtime status --project-id "$PROJECT" --expected-database "$LEDGER_DB"
novel-forge authority-runtime pause --project-id "$PROJECT" --expected-database "$LEDGER_DB" --expected-version "$CONTROL_VERSION" --idempotency-key "$PAUSE_KEY" --reason "$REASON"
novel-forge authority-runtime export --project-id "$PROJECT" --expected-database "$LEDGER_DB" --output "$NEW_PRIVATE_EXPORT_PATH"
```

Take a private backup and verify its restore before forward migration. Check object hashes
and native references, run/Effect/reservation fingerprints, release/Schema/Pack/Provider
identities, health and process rebuild under the brake. Preserve unknown costs/effects and
isolate their exact scope; do not replay a timed-out external call merely to obtain a clean
status. Resume strict or historical scopes only with their exact required authorization and
qualification. A native creative template uses its scoped admission and authenticated
resource contract; membership has no cumulative budget, and paid caps remain unchanged.
Do not roll back accepted history; compatible code recovery or forward repair is required.
After checking those native records, use `authority-runtime resume` with the same project
and expected database plus its current `--expected-version`, a new `--idempotency-key`
and `--reason`. This records a new scheduling decision; the process brake must also be
explicitly disabled in the intended release process configuration before a send is possible.

Use the existing Editor's **整稿版本** panel, or the same CLI/API operations:

```sh
novel-forge authority-edition query --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN"
novel-forge authority-edition create --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --payload-file "$CREATE_JSON" --idempotency-key "$CREATE_KEY"
novel-forge authority-edition save --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --payload-file "$SAVE_JSON" --idempotency-key "$SAVE_KEY"
novel-forge authority-edition start-validation --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --revision-id "$REVISION"
novel-forge authority-edition validate --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --payload-file "$VALIDATION_JSON" --idempotency-key "$VALIDATION_KEY"
novel-forge authority-edition select --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --payload-file "$SELECTION_JSON" --idempotency-key "$SELECTION_KEY"
novel-forge authority-edition export --project-id "$PROJECT" --workspace-id "$WORKSPACE" --book-run-id "$BOOK_RUN" --revision-id "$REVISION" --format text --output "$NEW_MANUSCRIPT_PATH"
```

Create binds `base_manifest_digest` and optional `base_revision_id`. Save binds `revision_id`,
`expected_version`, exact `base_manifest_digest`, mapped `units`, `reason`, and `change_kind`
(EXPRESSION/STRUCTURE/NARRATIVE_FACT/UNKNOWN). Source ranges use Unicode offsets and exact
source/hash/span hash; deletions require `removed_source_ranges`. Scene mappings bind stable realization slots to explicit Scene identities, separately from prose artifacts. Do not identify a chapter
by its display number. Query returns differences, native events, validation bindings and
inherited-prefix proof. Start-validation admits a separate native Book run and dispatches
nothing itself. If upper plans changed or structural edits exceed the frozen production scope, provide an approved same-Book `input_snapshot_id`; its profile and plan versions are resolved and checked by the existing native gates. Resume that run through normal workers or production controls. Validation
binds its `validation_book_run_id` and current candidate version. If native review changes
the saved text, validation remains blocked for that original candidate. Query exposes
`validation_result` with the exact accepted manuscript and differences. The Editor's
**保存审改后的版本**, or existing `create` with `source_validation_revision_id`,
`validation_book_run_id`, `expected_version`, that result's `base_manifest_digest` and
`reason`, captures a new immutable version with the submitted candidate as its predecessor.
Its validation proof comes from actual native acceptances; the original frozen request and
candidate remain unchanged. Selection remains a separate action.
Selection needs the current `expected_head_version` and reason. Conflicts retain input;
reconcile an uncertain response by querying/retrying the same idempotency key.
Edition export defaults to `FORMAL` and requires immutable `VALIDATED` and `SELECTED`
events for the requested exact revision. A previously selected revision can be exported
as a historical formal version; export never silently substitutes the current head.
Use CLI `--export-kind CANDIDATE` or API `export_kind=CANDIDATE` for an unadopted
candidate. The Editor labels these downloads separately. Responses retain the exact
revision, manifest digest and export kind; neither kind grants publication or literary qualification.
Historical callers that exported arbitrary candidates must now specify that kind explicitly.
Subsequent saves retain existing explicit removal mappings unless replacement mappings
are supplied. Reject applies to an editing candidate; switching the current formal
manuscript requires a separately validated selection. Neither action erases the old draft.
Default accepted-fact and quality queries use the selected manifest's exact acceptance
list. An explicit ongoing `book_run_id` is required to inspect subsequent accepted work
that has not yet been captured in that immutable manuscript.
If an old two-chapter revision's run has since accepted a third chapter, direct selection
returns `EDITION_FRONTIER_STALE`. To return to that earlier text, create a new candidate
with the old `base_revision_id` and exact manifest digest, then start its separate
validation run, inspect native review, validate or capture the reviewed result, and select
with the current head version and reason. Continue from the returned
`continuation_book_run_id`; the old run and its later acceptances remain intact.

The panel **从此稿改编场景剧本** reads exact allowed knowledge with
GET `/product/editor/editions/knowledge` (explicit selected unit IDs), freezes a scene plan,
and submits `/product/editor/screenplays/stages`. CLI `authority-screenplay` exposes
prepare/generate/review/revise/accept/update/run/status/export. Prepared source contracts
bind the exact edition; stage commands reference exact source/candidate/review assets.
`run` resumes the original Operation and its Effects. A review with unresolved findings
cannot authorize acceptance. The Editor lists source-update tasks after edition selection;
a replacement source requires its exact `update_task_asset_version_id` and predecessor.
Export does not grant publication rights. Native screenplay Provider sampling uses the
existing production Book API's `/product/production/book-authority/runs/{book_run_id}/screenplay/provider-samples` entry; `dry_run=true` checks
scope/grant without calls, and all sample outputs remain INELIGIBLE.

For author-supervised production, the existing production Book panel exposes
`/product/production/book-authority/books/{book_id}/author-supervision`. Select the Book
mode, then approve an actual prepared task's Producer/model scope, expiry and finite
limits. This policy does not grant account access, add budget, activate a Pack, release a
dispatch pause or settle an UNKNOWN Effect. The panel freezes the prior policy hash to
detect concurrent changes and retains the original request/idempotency key after a lost
response. Strict mode remains available, and previously admitted requests keep their
frozen policy. New selections on an explicitly supervised Book are blocked without an
exact task/Producer grant, including candidates that would pass strict qualification.
Strict-purpose semantic review keeps strict qualification and must also match its grant;
a trial grant does not relax it. Migration 0148 requires the normal private backup and forward-upgrade
boundary before deploying code that emits supervised production snapshots.
An explicit policy-version conflict retains the rejected request locally and refreshes
the policy for a new confirmation. Uncertain outcomes keep the original pending key.
Rejected plan decisions also replay with their original expected version; changing the
decision or target under that key remains an idempotency conflict.

For an adopted author draft or edition, select the prepared `review` task and authorize
its exact reviewer model before dispatch. The source-aware contract binds the new text
and native adoption evidence without inventing a generation Effect. A
`CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED` routing reason requires reviewer authorization;
`CROSS_MODEL_REVIEW_SOURCE_INVALID` requires correction or reconciliation of the named
source, not another generation call. A direct model draft still requires the opposite
Provider. The project Book Control policy and each request's frozen review boundaries
remain separate from Book mode and task authorization.

The original-direction controls save `/author-creative-input` and approve its exact
version through `/author-creative-input/{asset_version_id}/decisions`; workspace and
source identities are resolved by the API. Formation v3 then references the approved
direction and keeps `REVIEW_PLAN`. This does not import diagnostic candidates. For a
supervised generated plan, `/planning-candidates/{asset_version_id}/model-reviews` resolves
the configured trusted evaluator and the native generation identity. It uses the governed
Router/Pack/Effect path and the opposite Provider under its own valid task authorization.
Absent authorization or budget remains a task-specific stop; do not rename a failed or
unknown operation to resend it. Existing semantic Evaluation recovery owns continuation.
The panel displays exact model findings and retains per-finding author dispositions.
Model advice cannot authorize publication or confer independent literary qualification.

The applicable WP02 checks are focused Craft selection/repair/phase, Actor private intents,
Book edition/source isolation and in-flight recovery, screenplay production/sampling,
runtime dispatch control, fresh/upgrade migration and the same-Book native vertical.
Run actual Editor/API operations after relevant changes. Scripted outputs must stay outside
real qualification and production statistics. Full P0/backend/PostgreSQL/Compose/UI/remote
CI matrices are not implied by this targeted package evidence.

Creation namespaces its command keys by project and Book. Default project-owned Pack
identities use a deterministic project digest; configured explicit Pack IDs are retained.
The same IDs are supplied to all native runtime compositions on start and continuation,
so another project's private Pack cannot be borrowed accidentally.

Historical compatibility: the foreground v4 creation driver consumes a frozen Formation `formation-generation.v4`
request. Its work title, chapter target, language contract and creation-input profiles
come from the current request; it does not infer a short sample target. The driver
advances existing Formation and Opening RuntimeJobs, then starts the resolved Book
once and drives its existing coordination and Chapter workers. Continuation looks up
the same Formation-derived Opening and Book identity before creating any genesis
inputs. Bounded worker ticks save an existing checkpoint; the CLI renews its execution window
and continues by default until completion or a dependency/failure. Technical waits
also return to the caller; this is not durable end-to-end execution ownership. Use
`--yield-after-window` for an external scheduler that owns subsequent invocation. Three
windows without durable Formation/Provider/accepted-cursor progress return
`CREATION_NO_PROGRESS`. Windows are execution controls, never Book resource budgets.
They never reduce the Book target or declare completion at a pilot cursor. Frozen profiles remain unchanged on
resume. Historical v1-v3 Formation runs without a frozen creation-input profile require
`--creation-policy-file "$ORIGINAL_CREATION_POLICY"` on continuation. The current shipped
default cannot silently replace that historical profile.

Absent an explicit context policy, creation derives its context plan from the authorized
PRIMARY Codex catalog windows, subtracting each output allowance. World execution uses
`world-production-policy.v4` within its existing 512000 configurable ceiling. Explicit
policies remain frozen. These estimates never override complete rendered-request admission.

Native `blob.upload` export uses the Command Kernel's Authority-bound storage admission,
not a model route or a model budget. The exact built-in MinIO adapter must match the frozen
Effect and Blob reservation's project, operation, provider, key, size and hash. Admission
is journaled separately from gateway evidence; dispatch, lease, fence, receipt verification
and unknown reconciliation remain mandatory. Other adapters retain the controlled gateway
requirement, including every model and external tool action.

Native Chapter quality fanout continues ready independent groups while a sibling waits
for retry, qualification or reconciliation. It cannot aggregate or accept without every
required result. The driver returns the durable checkpoint and owning error code only
when no remaining independent group can run; terminal and security failures retain their
existing failure handling.

Creation continuation may invoke the existing native Formation resume command for an
AUTO-authorized creative run with the same operator and frozen inputs. It performs at
most one recovery per invocation and counts durable failures for the same stage across
all RuntimeJobs; three failures without stage progress require intervention. Unknown,
in-flight, terminally failed Effects and live leases block automatic retry. Worker errors
return the stored checkpoint with the original error code. Exact approval waits and
semantic/contract failures retain their owning Authority recovery requirements.

An unstarted failed historical Opening can receive a resource-policy successor through
its existing `continue_unstarted_with_budget` Authority command. Version 2 binds the
exact native creative template, new per-call resource policy and zero-work evidence.
The historical Opening, budget snapshot and failure remain immutable. An Opening with
any dispatched Effect, reservation, output or completed node requires its ordinary
reconciliation/recovery path; the zero-work successor cannot discard that evidence.
