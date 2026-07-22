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
| WP-02 | pending | — | — | — |
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

### Remaining blockers

- contracts are not persisted or executed yet;
- there is no persistent process directory, ProcessReceipt, process group, timeout,
  orphan recovery, PID reuse detection, or environment allowlist implementation;
- no ProductionExecutionGateway, Backend Registry, Admission Controller, Capability
  Probe runner, or backend adapter exists;
- Chapter Authority still uses its current Provider v2/legacy model ports;
- Gate-00 remains not run and all real-provider/production flags remain false.

The next authorized step is WP-02 Persistent Process Supervisor.
