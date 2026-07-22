# Next Authority Implementation Baseline

Date: 2026-07-22  
Branch: `feat/v7-content-intelligence-and-longform-proof`  
Source commit: `12f3ff7` (`docs: revise reader outcome governance and roadmap`)  
Baseline state: `PRE_PROVIDER_PRODUCTION_ARCHITECTURE_COMPLETE`

## Verdict

The repository has a PostgreSQL Command Kernel and a real eighteen-node Chapter
Authority protocol, but model execution is not yet unified and Book production does
not yet delegate real Chapter Sagas. The next safe boundary is therefore the planned
execution-plane migration, followed by Book Design Authority and dynamic child Saga
delegation.

The following claims remain false at this baseline:

```text
real_provider_baseline_run = false
single_chapter_real_provider_proven = false
book_to_chapter_delegation_proven = false
longform_proven = false
reader_outcome_behavior_calibrated = false
causal_experiment_validated = false
production_verified = false
```

This report is a code-fact inventory. It does not treat a schema, handler binding,
fixture result, UI route, or blueprint as production proof.

## Scope And Method

The audit read the required architecture/design/blueprint/current-state documents and
inspected the requested source trees. The requested path
`src/novel_forge/provider_control/` does not exist; the implemented package is
`src/novel_forge/modules/provider_control/`, which was audited instead.

Focused source size at the baseline:

| Source tree | Python lines | Finding |
|---|---:|---|
| `model_adapters/` | 2,679 | legacy provider implementations and the only Codex CLI launcher |
| `modules/provider_control/` | 1,103 | Provider v2 contracts, registry, scripted adapter, OpenAI adapter |
| `modules/model_router/` | 1,087 | LocalStorage route registry plus direct legacy Adapter execution |
| `modules/command_kernel/` | 6,334 | PostgreSQL Authority admission, effects, budget, callbacks, cancel/reconcile |
| `modules/production_kernel/` | 867 | LocalStorage convergence facade; not the PostgreSQL Command Kernel |
| `modules/chapter_authority/` | 5,477 | eighteen-node chapter Saga and effect-backed model stages |
| `modules/book_authority/` | 403 | fixture Book Saga and scheduler |
| `modules/context_builder/` | 3,001 | LocalStorage context assets and in-place updates |
| `modules/evaluation_center/` | 1,798 | LocalStorage evaluation tasks plus direct model execution |
| `storage/` | 10,239 | LocalStorage, PostgreSQL repositories, and migrations |

The Authority coverage manifest at source-tree SHA
`f77a8b6e0cbe8a221aecc6d27e0cb847c8b73a49` found 2,148 classified findings in
531 files, with no unmapped side effect. In the requested trees it found 111
Authority reads, 21 Authority writes, 37 external effects, two fallbacks, two sync
boundaries, and four unknown findings. These are static occurrences, not runtime
execution counts.

## Migration Baseline Matrix

`Runtime call count` means statically identifiable execution/write entry points in
the audited code, not observed production traffic.

| Concern | Current path | Target path | Migration adapter | Removal gate | Runtime call count | Existing test coverage | Risk |
|---|---|---|---|---|---:|---|---|
| Model execution | Business services use `GuardedModelAdapter`; Model Router and Evaluation Center call legacy Adapter methods directly | `ProductionExecutionGateway -> ExecutionBackend`, always bound to an `authority_attempt` | `LegacyRequestMapper` and `LegacyResultMapper` around the Gateway | no production call reaches `ProviderAdapter.generate/analyze/review/revise` outside a backend; architecture guard is green | 3 direct execution owners / 13 action call sites in requested trees | model-operation governance, provider fallback/hard-stop, quality eval, chapter fixture tests | critical: multiple execution authorities and incomplete receipt semantics |
| Codex CLI | `LocalCodexCliWorkerMixin` creates a `TemporaryDirectory`, copies all `os.environ`, and starts a subprocess without a process group | persistent execution directory plus `CodexProcessSupervisor` and `CodexCliExecutionBackend` | preserve legacy Adapter facade while mapping it into the Gateway | crash/orphan/PID-reuse/corrupt-result/SIGTERM-to-SIGKILL tests pass and legacy launcher call count is zero | 1 launch path plus 1 CLI capability-probe subprocess | local worker runtime-guard and option tests; no crash-recovery contract | critical: results disappear on worker crash and child processes can survive |
| Provider v2 | `ChapterProviderV2Gateway` dispatches registered `ProviderAdapterV2`; OpenAI transport calls `responses.create/retrieve/cancel` | `RemoteProviderExecutionBackend` behind the Gateway | Provider-v2 request/result mapper retaining its capability declarations | Chapter Authority uses only Gateway contracts and callback/query/cancel conformance is green | 1 Chapter Provider gateway; 1 SDK create/query/cancel transport | Provider v2 conformance, callbacks, fallback hard-stop, budget tests | high: production app builds an empty real-provider registry unless injected |
| Provider cost | OpenAI v2 emits `amount=0` with `source=not_provided`; several legacy paths default absent cost to zero | unknown cost remains unknown, then reconciles to measured or operator-resolved evidence | normalizer maps missing cost to `null/UNKNOWN`, never zero | no `not_provided` cost is materialized as measured zero | 3 default-zero families: OpenAI v2, Model Router/Gateway, Chapter model effect | budget lifecycle and cost-ledger fixture tests | high: false zero can incorrectly satisfy budget settlement |
| LocalStorage production writes | Production Kernel, Model Router, Context Builder, and Evaluation Center write JSON assets; LocalStorage optionally writes through to PostgreSQL | PostgreSQL Command Kernel and Authority AssetVersion/Snapshot are sole production writers | development/read-only compatibility adapters; Candidate import for legacy plans | strict production architecture guard reports zero LocalStorage writes in production paths | 17 explicit write call sites in the requested modules | broad unit coverage, runtime coverage report; no universal production-write prohibition | critical: dual authority and non-transactional in-place mutation |
| Workflow/Agent runner entry | registered child runners are routed through `dispatch_production_operation`; static audit finds no direct registered child runner | Command Kernel Operation/Saga/Attempt admission | existing Production Kernel facade may translate legacy envelopes during migration | all production callers use PostgreSQL admissions; LocalStorage parent is read-only legacy projection | 4 candidates, all kernel-internal; 0 registered-runner bypasses | production entrypoint contract and runtime coverage tests | medium: facade itself persists a second LocalStorage parent record |
| Workflow/Agent model bypass | legacy Agents/Workflows can construct `GuardedModelAdapter`, call `call_model_via_router`, or call logging-only `execute_model_gateway_call` | Agent/Workflow Operation invokes Gateway under its Authority Attempt | per-operation legacy request mapper | runtime call count outside execution backends reaches zero | 5 `call_model_via_router` consumers; at least 4 external logging-gateway consumers; 9 Guarded constructions | individual service tests, but no single unified execution guard | high: execution evidence and task state can diverge |
| Attempt | `authority_attempt` is active; older `operation_attempt` remains in schema and its repository alias is not a functional attempt repository | `authority_attempt` only | read-only migration/report adapter for historical rows | clean/upgrade migration proves no new writes to `operation_attempt`; repository references are removed | active Authority repository has many call sites; legacy table has 0 non-repository runtime consumers | attempt lease schema, scheduler, completion, cancel/retry PostgreSQL tests | high if a new execution attempt table is introduced |
| Receipt | Authority ExternalEffect has dispatch, callback, receipt, reconciliation, and late-result evidence; local Codex returns a synthetic provider-looking ID | ExternalEffect plus typed `ProcessReceipt`/`ProviderReceipt` bound to the same Attempt | result normalizer splits local execution receipt from provider request ID | local CLI has `provider_request_id=null` unless supplied by a real provider | 1 synthetic local evidence builder | external-effect/callback tests; no local process receipt recovery test | critical: local process identity is confused with provider identity |
| Route | Model Router stores mutable LocalStorage route/resolution assets; Provider v2 has separate route definitions | stable `ModelProfile`, `RoutePolicy`, immutable `RouteSnapshot` | Model Router becomes a recommendation/read model and route mapper | every model effect references a frozen RouteSnapshot; route change creates a new snapshot | 1 direct router executor and 2 route families | router/provider route tests | high: actual model/prompt/context/release is not frozen as one object |
| Budget | Authority provider budget reservation exists, while legacy LocalStorage write/model budget evidence remains separate | Authority budget reservation and settlement for every execution | legacy budget mapper into Authority reservation | all execution costs settle or remain explicitly unknown; no independent execution budget authority | 1 Authority provider-budget path plus legacy logging/write-budget paths | provider budget lifecycle, reservation failure and completion tests | high: fragmented budget evidence and unknown-as-zero |
| Approval | Authority canon approval exists; legacy permission/asset approvals exist outside Story Design Authority | domain approval policies materialize Authority approval evidence without a new approval state machine | legacy asset import/approval mapper | Story Design activation and high-risk Canon changes point to Authority approval records | 1 Canon Authority plus legacy approval services | canon approval/re-extraction PostgreSQL tests | high when Book Design is added without reusing Authority gates |
| Book scheduling | `BookAuthorityScheduler.tick` asks the shared content scheduler for one project operation, then filters by project rather than the Book root | root-scoped Book scheduler with dynamic child delegation | root-operation filter and child-delegation repository | concurrent unrelated project operation cannot be consumed by Book scheduler | 1 tick entry point | fixture Book scheduler PostgreSQL tests | high: wrong-root work can be advanced or book work can starve |
| Book chapter dispatch | admission pre-creates all `book.chapter.dispatch` operations; handler returns `ACCEPTED_FIXTURE_PROTOCOL` | resolve, dispatch, reconcile, accept; one real child `chapter.slice.run` at a time | Legacy Plan Candidate Import supplies first validated/frozen ChapterPlan | two dynamically created child Sagas pass final release/export/quality/canon/cost/binding acceptance | 1 fixture dispatch definition and N pre-created chapter operations | Book fixture integration and pause/resume tests | critical: no child Saga, delegation, receipt, or real acceptance exists |
| Chapter model effects | `ExternalEffectChapterModelPort` creates/fences/dispatches Authority effects and materializes logs/ledgers; a legacy direct adapter remains | same Chapter Saga, with its model port implemented by Gateway | `ChapterExecutionGatewayPort` preserving current handler contracts | fixture, unknown, callback, cancel/retry, restart, commit-manifest tests pass; legacy port unused | 1 effect-backed port; 1 legacy port with 5 direct action calls | broad Chapter Authority PostgreSQL and Provider v2 tests | high but bounded: preserve the Saga and swap only the execution seam |

## Direct Model Call Inventory

### Actual execution owners in the requested trees

1. `modules/chapter_authority/model_effects.py`
   - `ChapterModelExternalEffectAdapter` directly calls legacy Adapter
     `generate/review/revise` methods for Draft, Review, Revision, Canon, and Quality.
   - `ExternalEffectChapterModelPort` is the current PostgreSQL-safe production seam;
     it must be retained while its provider implementation is replaced by the
     Production Execution Gateway.
2. `modules/model_router/service.py`
   - `call_model_via_router` resolves a mutable route, directly invokes the Adapter,
     then calls `execute_model_gateway_call` to record policy/log evidence.
   - The function named `execute_model_gateway_call` does not execute the model; it is
     a policy and evidence logger.
3. `modules/evaluation_center/service.py`
   - `_run_adapter` directly invokes all four legacy Adapter actions.
4. `model_adapters/guarded.py`
   - `GuardedModelAdapter` is a logging/policy decorator that delegates directly to
     the wrapped Adapter. It is not an execution authority.

Outside the requested trees, direct construction/use remains in topic, outline,
chapter plan, drafting, review, revision, editor, decomposition, and analysis
services. Router consumers also exist in product handoff review, V7 provider proof,
quality evaluation, evaluation calibration, and long-chain proof.

### Codex CLI launch inventory

The only model-related Codex CLI launcher is
`model_adapters/providers.py::LocalCodexCliWorkerMixin`:

- one `subprocess.Popen` execution path;
- one `subprocess.run` option/capability probe;
- ephemeral schema/output paths under `TemporaryDirectory`;
- full inherited environment via `dict(os.environ)`;
- single-process `kill()` without an owned process group;
- no persistent receipt, orphan recovery, PID start-time check, or corrupt-result
  quarantine;
- a locally generated response identifier that looks like provider evidence.

Generic subprocess usage elsewhere in the repository is not counted as a model or
Codex launch.

### Provider v2 entry inventory

- `ChapterProviderV2Gateway.invoke/query/cancel` maps Chapter ExternalEffects to a
  qualified Provider route.
- `OpenAIProviderAdapterV2` implements the Provider-v2 contract.
- `OpenAISdkTransport` is the only audited real SDK transport and calls
  `responses.create`, `responses.retrieve`, and `responses.cancel`.
- `ScriptedProviderAdapterV2` is a fixture and correctly keeps all real-provider
  proof flags false.
- `create_authority_dependencies` registers the scripted provider only in
  development/test. In production, the default application construction does not
  inject or construct a real provider registry, so the real route is not runnable by
  default.

## LocalStorage And Bypass Inventory

The 17 explicit writes in the requested business modules are:

| Module | Count | Meaning |
|---|---:|---|
| Context Builder | 10 | creates bundles/manifests/reports and mutates existing JSON bundle files |
| Production Kernel | 4 | creates and updates LocalStorage parent/reconciliation/coverage assets |
| Evaluation Center | 2 | updates a task JSON and writes evaluation assets |
| Model Router | 1 | writes route/gateway evidence assets |
| Chapter Authority | 0 | PostgreSQL repositories only in the audited authority path |
| Book Authority | 0 | PostgreSQL repositories only |

LocalStorage's `_sync_postgres_write_through` does not make the JSON write
transactional Authority: the file is written first and remains independently
mutable. It is therefore a compatibility/storage projection, not an acceptable
production write route for the target architecture.

The registered Production Kernel entrypoint audit returned:

```text
candidate_count = 4
kernel_internal_count = 4
review_required_count = 0
```

This proves only that the four recognized child runner symbols are not called around
the facade. It does not prove unified model execution, PostgreSQL production
authority, or absence of unregistered semantic bypasses.

## Book Authority Facts

### Scheduler scope

`BookAuthorityScheduler.tick` invokes the shared `ContentAuthorityScheduler` with
`pending_operations(limit=1)` and then filters only by project. It does not constrain
the claim to the Book root operation or Book Saga. The removal gate is a root-scoped
claim/query plus a concurrency test containing unrelated work in the same project.

### Fixture dispatch

`admit_book_production` builds `prepare`, one dispatch step per requested chapter,
recap, and plan-adjustment operations up front. `book.chapter.dispatch` returns a
`ChapterAcceptanceRecord` containing `ACCEPTED_FIXTURE_PROTOCOL` and a
`scripted-fixture:no-prose-generated` child identifier. It creates no child root
operation, child Saga, delegation, budget reservation, receipt, or acceptance proof.

### Required migration

The replacement must preserve the Book root while implementing separate
`book.chapter.resolve_plan`, `book.chapter.dispatch`, `book.chapter.reconcile`, and
`book.chapter.accept` definitions. Dispatch must admit one child `chapter.slice.run`
and return `DISPATCHED`; only Accept may advance the cursor. The next chapter
operation must be created after acceptance, not during Book admission.

## Chapter Authority ExternalEffect Path

The current effect-backed model flow is:

```text
Chapter handler
-> ExternalEffectChapterModelPort.invoke
-> plan model.invoke ExternalEffect
-> reserve provider budget
-> acquire effect dispatch lease and fencing token
-> dispatch ChapterProviderV2Gateway
-> accept receipt or persist UNKNOWN
-> settle cost
-> materialize model_call_log / cost_ledger through Authority AssetVersion
-> handler materializes the stage candidate/output
```

This is the correct Authority seam. WP-04 must not rewrite the eighteen-node Saga;
it must replace the port implementation under this seam and preserve Frozen Inputs,
lineage, Canon approvals, five Quality groups, Aggregate, Publish Gate, Export, and
Final Release Gate.

Known gaps at the seam:

- absent cost defaults to zero in several mappings;
- a cost ledger is created only for a positive amount;
- legacy direct Adapter IDs and local Codex IDs can look like provider IDs;
- there is no Execution Manifest / Commit Manifest or immutable RouteSnapshot;
- local process cancellation and remote provider cancellation are not distinct.

## Attempt, Receipt, Route, Budget, And Approval Duplication

| Semantic | Active Authority | Duplicate/legacy semantic | Disposition |
|---|---|---|---|
| Operation | `authority_operation` | PostgreSQL `production_operation`; LocalStorage `production_operation` asset | freeze legacy creation, adapt reads, then retire production writes |
| Attempt | `authority_attempt` | `operation_attempt`; `OperationAttemptRepository` is only an alias | Authority Attempt remains unique; prohibit new writes and later archive/drop only through an approved migration |
| Lease/fencing | `authority_lease_acquisition`, `authority_effect_dispatch_lease` | `operation_lease` lacks Authority fencing semantics | stop new legacy lease acquisition after caller migration |
| Idempotency | `authority_idempotency_record` | `idempotency_record` scoped to old production operation | translate legacy commands into Command Kernel admission |
| Receipt | `authority_external_receipt`, provider callback/attempt, reconciliation evidence | legacy model logs and synthetic local response IDs | normalize into typed Process/Provider receipts on the same effect/attempt |
| Route | Provider v2 route definitions | LocalStorage Model Router route/resolution | Model Router becomes registry/recommendation projection only |
| Budget | `authority_budget_reservation`, operation cost evidence | LocalStorage write budgets and model call logs | retain write budgets as resource guards, not execution cost authority |
| Approval | Authority completion/canon approvals | permission-center and asset-local approval fields | reuse Authority gates and typed approval policies; do not create another approval machine |

## Migration And Table Reuse Matrix

| Existing table/family | Reuse decision | Planned addition/use | Removal or compatibility gate |
|---|---|---|---|
| `authority_operation_definition`, `authority_operation`, dependency graph | reuse unchanged | register execution, planning, delegation, outcome, recap, and ROJ operations | Catalog binding and migration upgrade tests |
| `authority_attempt`, `authority_lease_acquisition`, late result/recovery/cancel tables | reuse as sole Attempt authority | bind every ExecutionRequest/Handle/Result to `attempt_id`; add no execution-attempt table | architecture guard rejects parallel Attempt schema/repository |
| `authority_external_effect`, dispatch, receipt, callback, reconciliation, command rejection | reuse | store provider/process effect evidence and reconcile UNKNOWN | query/cancel/callback/restart/fencing tests |
| `authority_budget_reservation`, operation cost evidence | reuse | reserve/settle all model and delegated Chapter execution | unknown cost and overrun tests pass |
| `authority_asset`, `authority_asset_version`, qualification, output binding, locator | reuse | all plan/design/outcome/state/judge payloads remain versioned Authority assets | no domain-specific payload-version table |
| completion gate/approval/aggregate, Canon approval tables | reuse | planning activation, Chapter acceptance, risky Canon changes | no new generic gate/approval state machine |
| Saga and Saga step tables | reuse | Book/ChapterGroup/ROJ root protocols and child delegation state | dynamic child and recovery tests |
| Blob and release evidence tables | reuse | manifests, export, process output references | verified Blob and Final Release Gate |
| old `production_operation*`, `operation_attempt`, `operation_lease`, `idempotency_record` | legacy/read-only migration source | no new feature writes | caller count zero, clean/upgrade migration, explicit later retirement decision |
| `nf_assets`, `nf_asset_versions`, `nf_task_statuses` | legacy compatibility/import source | Candidate Import only where required | no production fallback or direct business mutation |
| new Story Planning relationships | add minimal typed relational tables | `story_plan_binding`, `story_plan_hierarchy`, `active_story_plan_version`, `planning_horizon`, `asset_dependency_edge`, `story_production_cursor` | payload stays in Authority AssetVersion; clean/upgrade/replay tests |
| execution-plane persistence | prefer Authority assets/effects first | persistent execution directory and typed process receipt storage; add a table only if evidence cannot be represented safely by current Authority tables | WP-01 contracts decide before WP-02 migration |

## Existing Test Coverage And Required Additions

Existing relevant coverage includes:

- Authority admission, Attempt/lease/fencing, Saga dependencies, completion, cancel,
  retry, late results, budget lifecycle, callbacks, and ExternalEffect reconciliation;
- full Chapter fixture integration, scheduler, Canon approval/re-extraction, Quality,
  Export, Blob, and Final Release behavior;
- Provider-v2 scripted conformance, production fallback hard-stop, and capability
  qualification;
- Book fixture Saga and pause/resume;
- clean and legacy migration suites;
- Authority coverage, blob protocol, and pre-provider convergence architecture
  guards.

Missing tests that are removal gates, not optional polish:

1. Execution contract binding to Authority Attempt and immutable RouteSnapshot.
2. Model alias resolution with an explicit `xhigh` unsupported failure.
3. Persistent local process crash/orphan/PID-reuse/corrupt-result recovery.
4. Environment allowlist and process-group SIGTERM/SIGKILL behavior.
5. Local process cancel versus remote provider cancel semantics.
6. Gateway duplicate/query/callback/cancel/retry/reconcile conformance across all
   three backend classes.
7. Chapter Commit Manifest and zero legacy production runtime calls.
8. Dynamic Book child creation, missing-delegation/missing-receipt reconciliation,
   plan binding, acceptance, and two-Chapter cursor proof.
9. Story-plan orthogonal state, dependency impact, replay, and frozen-plan mutation.
10. Deterministic ChapterOutcome reducers and append-only Story State replay.
11. ROJ mutation/metamorphic/A-B-B-A/OOD/evidence-span/shadow-budget tests proving
    Publish remains unchanged.

## Sequenced Removal Gates

The implementation order cannot be safely compressed:

1. Gate-00 records the real-provider pre-migration truth without blocking local work.
2. WP-01 defines immutable, Attempt-bound execution contracts without changing
   runtime behavior.
3. WP-02 makes local process execution recoverable and correctly identified.
4. WP-03 centralizes all backends and adapts legacy and Provider-v2 callers.
5. WP-04 migrates Chapter model nodes without rewriting Chapter Authority.
6. Gate-01 may claim proof only from a real receipt.
7. WP-05 establishes Story Design/Planning Authority and validated Legacy Import.
8. WP-06 replaces fixture dispatch with dynamic real Chapter Saga delegation.
9. WP-07 through WP-09 add rolling plans, generators, outcomes, deterministic state,
   and governed plan change.
10. WP-10 and WP-11 add ROJ as shadow evidence before human anchoring, behavioral
    calibration, or causal claims.
11. WP-12 records each long-form proof tier independently.

## Baseline Blockers

- No paid provider call has been authorized for this task.
- The default production Authority application does not construct a real provider
  registry/route.
- No evidence has yet established a trusted principal, approved project/provider
  budget, qualified frozen ChapterPlan and Context input, legal credentials, and a
  runnable database together for Gate-00.
- Book chapter dispatch is fixture-only.
- No persistent local process receipt/recovery plane exists.
- Story Design/Planning Authority relationship tables and lifecycle policies do not
  yet exist.
- ROJ blueprint artifacts are design inputs only; no calibrated probability or
  causal experiment may be claimed.

## WP-00 Acceptance

```text
docs_consistency_checked = true
code_fact_baseline_written = true
provider_call_executed = false
database_migration_changed = false
operation_definition_catalog_changed = false
production_behavior_changed = false
```

WP-00 is complete only after the documentation/architecture validation commands
recorded in its commit pass. PostgreSQL integration, migration changes, and Operation
Definition changes are not applicable to this read-only/docs-only package; no such
change is implied.

### Verification receipt

```text
.venv/bin/python -m unittest discover -s tests/architecture -p 'test_*.py'
7 passed

make lint
passed

make check-skills
passed

make validate
passed
```

An initial architecture invocation with the system `python3` failed during import
because that interpreter does not contain the repository's `psycopg` dependency. It
was rerun with the project's `.venv/bin/python`; all seven architecture tests passed.
No failed test was skipped or reclassified as passing.
