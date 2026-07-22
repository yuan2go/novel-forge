# Production Execution Plane Implementation Report

Updated: 2026-07-22  
Branch: `feat/v7-content-intelligence-and-longform-proof`

## Scope

This is the cumulative evidence report for Gate-00 and WP-01 through WP-04. A row is
updated only from code, tests, migrations, or a real execution receipt. Design
documents and fixture output are not production evidence.

## Gate-00 — Pre-Migration Real Provider Chapter Baseline

### Verdict

```text
gate = Gate-00
evaluated_at = 2026-07-22
source_commit = 451ff381ab33335234cb74155de8c9cea1d8149c
status = NOT_RUN_PRECONDITIONS_UNMET
real_provider_baseline_run = false
real_provider_proven = false
production_verified = false
```

No Provider request was sent. The user did not authorize a paid model call, and the
runtime prerequisites were independently incomplete. Gate-00 therefore records an
honest blocked baseline and does not block subsequent local architecture work.

### Qualification checklist

| Requirement | Status | Evidence / blocker |
|---|---|---|
| Qualified real Provider route | false | no chapter Provider/model variables are configured; the production dependency builder receives no real `ProviderAdapterRegistry` by default |
| Trusted principal | false | `NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID` is unset |
| Explicit project scope | false | `NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE` is unset; the development default `*` is not accepted as controlled proof configuration |
| Approved budget | false | per-call, project, operation, provider, global, and chapter Provider caps are unset |
| Full release SHA | partial / not runnable | Git supplies full SHA `451ff381ab33335234cb74155de8c9cea1d8149c`, but `NOVEL_FORGE_APPLICATION_BUILD_ID` and `NOVEL_FORGE_COMMIT_SHA` are unset, so Authority release identity fails closed |
| Qualified frozen ChapterPlan | unknown | PostgreSQL is configured in `.env` but was unreachable; no Authority AssetVersion was inferred from files or fixtures |
| Governed Context input | unknown | same unreachable Authority database; no Context evidence was fabricated |
| Legal Provider credentials | false / unverified | `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are unset; `CODEX_HOME` exists in the process environment but current Chapter Provider v2 does not register a Codex backend and authentication/usage authorization was not assumed |
| Authority object store | false | `NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT` is unset |
| Worker identity | false | `NOVEL_FORGE_AUTHORITY_WORKER_ID` is unset |
| PostgreSQL availability | false | configured URL failed a read-only `SELECT 1` connection attempt with `OperationalError`; Docker Compose reported no running project services |
| Paid-call authorization | false | no user authorization was provided; this alone prohibits the call even if technical prerequisites later become true |

The environment audit reported only whether a setting was present. It did not print
credential, database, or token values.

### Receipt inventory

Because no real call occurred, no fake or fixture receipt was substituted:

| Evidence | Receipt |
|---|---|
| Provider Request | none |
| Provider Callback | none |
| Provider Query | none |
| Provider Cancel | none |
| Usage / Cost | none |
| Timeout / Latency | none |
| RouteSnapshot | not implemented at this gate |
| AssetVersion lineage | none from a Gate-00 run |
| Canon / Quality / Export / Final Release | none from a Gate-00 run |
| Attempt / Lease / Fencing | none from a Gate-00 run |

### Recovery instruction

Gate-00 can be rerun only after all of the following are true:

1. an operator explicitly authorizes the bounded paid call;
2. a real Provider-v2 adapter is registered and qualifies all Chapter stages;
3. trusted operator/worker identities and a single project scope are configured;
4. application build ID and the current full commit SHA are configured;
5. all Provider budget caps and object storage are configured;
6. PostgreSQL is reachable and contains an eligible, governed, frozen ChapterPlan
   plus the complete Context/typed-empty inputs;
7. credentials are lawful for the selected Provider and are checked without exposing
   their values.

## Work Package Ledger

| Package | Status | Commit | Runtime behavior changed | Verification |
|---|---|---|---|---|
| WP-00 | complete | `451ff38` | no | 7 architecture tests, compile, Skill drift, workspace validation |
| Gate-00 | not run: prerequisites unmet | this report commit | no | configuration-presence and read-only database reachability checks |
| WP-01 | complete: contract layer | `60c685a` | no | contract/architecture tests, PostgreSQL Authority regression, clean/upgrade migration |
| WP-02 | complete: persistent local process supervision | `cea7a25`, `ac80c31` | yes, local Codex CLI only | 15 supervisor/boundary tests, 53 focused tests, 992 unit tests, 101 PostgreSQL Authority tests |
| WP-03 | pending | — | — | — |
| WP-04 | pending | — | — | — |
| Gate-01 | pending | — | — | — |

## Current Fact Flags

```text
fixture_proven = true
integration_proven = true
real_provider_proven = false
single_chapter_real_provider_proven = false
book_to_chapter_delegation_proven = false
longform_proven = false
human_anchored = false
behavior_calibrated = false
causal_validated = false
production_verified = false
```

## WP-01 — Production Execution Plane Contracts

### Delivered

`src/novel_forge/modules/production_execution/` now exports:

- `ExecutionRequest`, `ExecutionHandle`, `ExecutionResult`, and
  `ExecutionCancellationResult`;
- `ExecutionBackend` and `ExecutionCapabilityProfile`;
- `ModelProfile`, `RoutePolicy`, and immutable/hashable `RouteSnapshot`;
- `InputManifest`, `ExecutionManifest`, `OutputManifest`,
  `ValidationManifest`, and `CommitManifest`;
- typed artifact, validation, transport, capability, cancellation, and outcome
  values required to avoid synthetic evidence.

All execution-specific contracts carry `operation_id`, `attempt_id`, and positive
`fencing_token`. RouteSnapshot binds its creating Authority Attempt and may be reused
by reference for retry only when the frozen routing fingerprint is unchanged. A route
change requires both a new RouteDecision and RouteSnapshot identity.

### Contract invariants

| Invariant | Enforcement |
|---|---|
| Authority Attempt is unique | no execution Attempt type/table/repository; architecture guard scans migrations and contract source |
| stable model alias | `ModelProfile.profile_id` accepts a logical alias and separates actual provider/model ID |
| active profile qualification | ACTIVE requires Capability Probe; qualification requires exact probe, backend ID/version, runtime class, and reasoning effort |
| no silent reasoning downgrade | RouteSnapshot requires requested and actual effort equality; RoutePolicy only permits `PROHIBITED` downgrade policy |
| no fake Provider ID | Provider request and receipt refs are nullable; scripted fixture cannot claim a Provider request ID |
| local/remote cancel separation | local termination and upstream cancellation have independent enums and receipts; `ALREADY_COMPLETED` cannot be reported as `CANCELLED` |
| frozen validation | ValidationManifest binds policy, required checks, output, Attempt, and fence; ACCEPTED requires all declared checks to pass |
| Authority hash compatibility | artifact/output hashes accept the existing `sha256:<64hex>` format |
| generalized production scope | InputManifest uses typed `target_scope`, not a mandatory Chapter field |
| commit evidence | COMMITTED requires AssetVersion and Authority commit refs; REJECTED requires rejected-output evidence |

### Runtime and schema impact

```text
production_behavior_changed = false
provider_call_executed = false
database_schema_changed = false
new_attempt_authority_created = false
operation_definition_added = false
operation_catalog_metadata_repaired = true
```

No migration was added because WP-01 is deliberately a pure contract phase. Existing
clean-install and upgrade migrations were executed to prove compatibility. Book
fixture OperationDefinitions received missing schema-version/projection/migration
metadata exposed by the complete Catalog contract test; no Book runtime behavior was
changed.

### Verification

```text
new contract + boundary tests: 22 passed
full architecture suite with regenerated baseline: 11 passed
focused contract/provider/catalog/API tests: 51 passed
full unit discovery: 980 passed
PostgreSQL Command Kernel/Authority suite: 101 passed
focused Book Authority + clean/upgrade migration: 3 passed
compileall: passed
Skill drift: passed
architecture coverage/catalog: regenerated at source commit 60c685a
```

The first PostgreSQL run found a stale output-count assertion (`71` versus the actual
`76`). The five additional outputs are the already-implemented per-Quality-Group
`quality_context_coverage_report` assets. The assertion now derives the protocol
families explicitly and the full 101-test suite passes. Full unit discovery also
exposed three pre-existing fixture/Catalog/CI characterization drifts; they were
repaired in `921e775`; the subsequent full discovery passed all 980 tests. No failed
test was skipped.

### Review receipt

The code-review quality and specification passes initially found incomplete Probe and
backend-version binding, ambiguous cancellation evidence, Chapter-only input scope,
incomplete validation coverage, and Authority hash incompatibility. Each issue was
fixed and re-reviewed. The specification re-review reported no remaining WP-01
blocker; the final cancellation re-review issue was then closed by requiring terminal
local/upstream evidence and a Provider cancellation receipt.

### WP-01 close blockers

The persistent process directory, ProcessReceipt, process-group control, timeout,
recovery, PID-reuse guard, and environment allowlist items were resolved by WP-02
below. Gateway/backend execution, Chapter migration, and real-provider evidence remain
open.

## WP-02 — Persistent Process Supervisor

### Delivered

`modules/production_execution/process_supervisor.py` now provides:

- `PersistentExecutionDirectory` with stable hashed execution paths, atomic JSON
  writes, request-digest binding, path-containment checks, and cross-process file
  locking;
- `CodexProcessSupervisor`, `ProcessReceipt`, `ProcessGroup`, `ProcessTimeout`, and
  explicit `STARTING`, `START_FAILED`, `RUNNING`, success, failure, cancellation,
  timeout, orphan, and corrupt-result states;
- stdout, stderr, schema, result, metadata, and receipt files that survive worker
  restart instead of disappearing with a temporary directory;
- POSIX process groups (`start_new_session=True`) with bounded SIGTERM grace followed
  by SIGKILL escalation;
- duplicate-launch suppression and reconciliation against the original receipt;
- worker/supervisor liveness evidence, PID/start-token comparison, fail-closed
  `PROCESS_IDENTITY_UNVERIFIABLE`, and `PID_REUSE_DETECTED` recovery outcomes;
- JSON-object result integrity checks and recoverable-result reporting after a worker
  crash;
- the exact default environment allowlist required by the design:
  `PATH`, `HOME`, `CODEX_HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `SSL_CERT_FILE`,
  `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`.

`LocalCodexCliWorkerMixin` now launches exclusively through the supervisor. It no
longer uses `TemporaryDirectory`, no longer passes the full parent environment, and
no longer synthesizes a Provider response identifier. A local result now records:

```text
transport = LOCAL_CLI_REMOTE_INFERENCE
local_execution_receipt_id = process-receipt:<digest>
provider_request_id = null
provider_response_id = null
```

Local termination is explicitly local-only. It does not claim that remote inference
was cancelled. When an Authority binding is supplied, the receipt records the real
`operation_id`, `attempt_id`, and fencing token. Legacy calls remain possible during
migration, but their receipts carry `authority_bound=false` and are not eligible as
production Authority proof.

### Failure and recovery behavior

| Injection / race | Verified result |
|---|---|
| worker restart after result write | result remains on disk; recovery reports `ORPHANED` plus `result_recoverable=true` rather than accepting it silently |
| duplicate or concurrent submit | one process starts; duplicate waits/reconciles the same receipt |
| timeout with SIGTERM ignored | process group escalates to SIGKILL and records `TIMED_OUT` |
| local cancellation | process group terminates; Provider request/cancel evidence remains null |
| process launch failure | durable `START_FAILED` receipt with no fabricated PID/PGID |
| valid exit with missing/corrupt result | `CORRUPT_RESULT`, never success |
| reused PID | `PID_REUSE_DETECTED`; unrelated process is not signalled |
| unverifiable OS process identity | fail closed with `PROCESS_IDENTITY_UNVERIFIABLE` and `safe_to_signal=false` |
| request drift under same execution ID | rejected before a second process is launched |
| unlisted secret environment key | absent from child environment; unlisted override is rejected |

### Runtime, migration, and catalog impact

```text
production_behavior_changed = local Codex CLI execution only
real_provider_call_executed = false
database_schema_changed = false
new_attempt_authority_created = false
new_operation_definition_added = false
persistent_process_supervisor_proven = true
production_execution_gateway_proven = false
codex_cli_backend_proven = false
```

No database migration was added: WP-02 persists local crash-recovery files under the
configured runtime workspace, while PostgreSQL Authority persistence remains the
responsibility of the WP-03 Gateway/ExternalEffect integration. The existing clean
install and upgrade migrations passed unchanged. The OperationDefinition Catalog and
Authority coverage artifacts were regenerated and bind to source commit
`ac80c31fcf6682cd705936d6f68bf5c3576c9f61`.

### Verification

```text
supervisor unit tests: 12 passed
process boundary tests: 3 passed
focused execution/provider tests: 53 passed
concurrent duplicate stress: 8 consecutive passes
full unit discovery: 992 passed
full architecture discovery: 14 passed
Authority coverage/catalog tests: 16 passed
PostgreSQL Command Kernel/Authority suite: 101 passed
clean install + upgrade migrations: passed inside PostgreSQL suite
compileall: passed
real/paid Provider calls: 0
```

No failed test was skipped. The first full architecture pass correctly failed on the
checked-in source-tree hash after source changes; the generated baseline/catalog were
then regenerated against the committed source and the 14-test architecture suite
passed.

### Remaining blockers

- `ProcessReceipt` files are not yet materialized through the PostgreSQL
  ExternalEffect/Receipt authority; unbound legacy receipts remain non-production;
- `ProductionExecutionGateway`, Backend Registry, Admission Controller, Capability
  Probe, result normalizer/validator, and execution reconciler are not implemented;
- Provider v2 is not yet adapted as `RemoteProviderExecutionBackend`;
- Model Router and Legacy Adapter still own old execution entry paths outside the
  migrated local process seam;
- Chapter Authority still uses its current Provider v2/model ports;
- old external-provider proof code still expects a Provider response ID, so local CLI
  evidence correctly remains ineligible until WP-03 introduces transport-aware proof;
- Gate-00 remains not run and every real-provider/production flag remains false.

The next authorized step is WP-03 ProductionExecutionGateway and backend convergence.
