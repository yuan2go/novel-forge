# Current Roadmap

Updated: 2026-08-04

Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`

Implementation evidence SHA: `8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`

Execution model: `SIX_TRACK_VERTICAL_DELIVERY`

This roadmap is ordered by dependency, vertical proof value and rework risk. It replaces the former P0-P8 horizontal capability roadmap for current execution.

The authoritative Epic is:

- [`../architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](../architecture-closure/autonomous-novel-os-architecture-closure-epic.md)
- [`../architecture-closure/README.md`](../architecture-closure/README.md)

## 1. Roadmap Principle

The current bottleneck is not missing isolated features. It is the absence of one fully proven path from a complete repository HEAD through Authority deployment, real Provider execution, whole-book progression and Arc-level acceptance.

Required order:

```text
Track A — Trusted Baseline And Governance
→ Track B — Shared Authority Kernel And Storage
→ D0 — Real Provider Qualification Probe
→ Track C — Novel Domain And Context
→ Track D — Intelligence, Execution And Quality
→ Track E — Autonomous Book Runtime And Operations
→ Track F — Migration, Long-form And Scale Proof
```

Progress is measured by completed vertical Slices, not by modules, tables, pages or documents.

## 2. Current Position

Current execution is stopped at the D0 gate:

```text
Track A Gate = PASS
Track B Book + BookDesign minimal slice = PASS
Track B.5 execution semantics = PASS
Track C convergence ADR = ACCEPTED
D0 Real Provider Qualification Probe = BLOCKED_MISSING_CREDENTIALS
C1 = NOT_STARTED
```

Track C1 must not begin as an accepted implementation stage until the real D0 probe records Provider evidence. Design preparation may continue without changing shared contracts or claiming the gate.

Current flags:

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
minimal_authority_only_runtime_verified=true
transaction_command_atomicity_proven=true
inflight_command_recovery_semantics_proven=true
execution_classification_consistent=true
architecture_fitness_scope_hardened=true
asset_scope_database_constraints_proven=true
book_design_planning_convergence_adr_accepted=true

authority_only_runtime_verified=false
single_chapter_real_provider_proven=false
book_coordinator_l10_proven=false
l30_arc_proven=false
architecture_closure_gate_passed=false
```

Track B slice flags:

```text
project_book_scope_authority_proven=true
typed_book_design_asset_proven=true
production_legacy_write_blocked=true
duplicate_replay_proven=true
query_projection_proven=true
```

D0 real-provider flags are all false. The PostgreSQL/Object Store harness does
not promote Fixture evidence. See
[`../reports/d0-authority-provider-qualification.md`](../reports/d0-authority-provider-qualification.md).

## 3. Track A — Trusted Baseline And Governance

### Slice A1 — Repository Integrity

**Goal:** make one exact repository SHA structurally complete and machine-verifiable.

Required work:

1. produce module, migration, worker, console-script and required-test manifests;
2. verify every import referenced by API, CLI, workers and migration registry;
3. verify Project/Task/Source/MKAOS Authority files and remove invalid references or commit missing files;
4. verify migrations `0043` through `0050` and establish one migration head;
5. verify every required test pattern matches a non-zero test count;
6. add CI checks for manifest drift and exact-SHA binding.

Required commands include:

```bash
python -m compileall -q src tests
python -c "import novel_forge"
python -m novel_forge.cli --help
python scripts/check_module_manifest.py
python scripts/check_migration_manifest.py
python scripts/check_worker_manifest.py
python scripts/check_required_test_manifest.py
```

Scripts may be introduced under `scripts/` during implementation; names are targets, not claims that they currently exist.

Acceptance:

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
required_test_inventory_passed=true
```

### Slice A2 — Current-SHA Validation Baseline

**Goal:** execute all relevant validation against the same complete SHA.

Required evidence:

- Python dependency versions;
- PostgreSQL version;
- Node/npm versions;
- exact commands;
- discovered/passed/failed/error/skipped counts;
- API and worker startup results;
- Docker config/build result;
- immutable report bound to commit SHA.

Minimum matrix:

```bash
python -m unittest discover -s tests/architecture -p 'test_*.py'
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m unittest discover -s tests/acceptance -p 'test_*.py'
python scripts/run_authority_postgres_tests.py
python -m unittest discover -s tests/integration -p 'test_*.py'
npm --prefix web/admin ci
npm --prefix web/admin test
npm --prefix web/admin run build
docker compose config
docker compose build
```

Acceptance:

```text
current_sha_test_baseline_recorded=true
api_startup_verified=true
worker_startup_inventory_verified=true
web_build_verified=true
```

The baseline may contain known failures, but they must be enumerated and prioritized. An incomplete or mixed-SHA result is not a baseline.

### Slice A3 — ADR And Fitness Foundation

**Goal:** prevent the architecture from returning to direct Provider calls, Legacy writes and cross-layer coupling.

Required ADRs and fitness checks:

- modular monolith and process-separated workers;
- PostgreSQL single Authority;
- production LocalStorage write/fallback prohibition;
- Domain import boundaries;
- direct Provider/HTTP/subprocess scan;
- migration registry integrity;
- non-zero required test discovery;
- current-SHA evidence binding;
- documentation truth hierarchy.

Track A Gate:

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
```

## 4. Track B — Shared Authority Kernel And Storage

Track B starts only after Track A Gate.

### Slice B1 — Project/Book Scope Authority

End-to-end path:

```text
Create Project/Book Command
→ Principal and Scope validation
→ idempotent PostgreSQL commit
→ duplicate replay/conflict rejection
→ query projection
→ production boot without LocalStorage
```

Required domain objects:

- Project;
- Workspace;
- Book;
- ProductionProfile;
- RuntimePolicy;
- ReleaseIdentity;
- Principal/ServiceIdentity;
- ProjectScope/BookScope.

### Slice B2 — Typed Asset Registry

End-to-end proof using BookDesign as the first domain asset:

```text
BookDesign Candidate
→ strong schema validation
→ AssetVersion
→ Approval Decision
→ Activation
→ Supersession
→ dependency and lineage query
```

Required rule:

```text
common metadata
+ strong typed domain payload
+ schema_version
+ content_hash
```

Do not implement a universal unvalidated JSON asset store.

### Slice B3 — Execution Classification And Kernel

Formalize four execution types:

```text
Transaction Command
Durable Job
Saga
External Effect
```

Only use Saga when multi-step cross-transaction recovery is required.

Prove:

- idempotency and digest conflict;
- Attempt/Lease/Fence;
- transaction rollback;
- External UNKNOWN and reconciliation;
- cancel and late result;
- outbox atomicity;
- recovery after worker restart.

### Slice B4 — Storage, Budget And Readiness

Prove:

- PostgreSQL Authority metadata;
- Object Store large immutable content and hash verification;
- rebuildable Vector/Search projection;
- Budget reservation and actual cost ledger;
- connection pooling and timeouts;
- dependency-aware readiness.

### Slice B5 — Minimal Authority-only Runtime And Slice Cutover

Run before Track C:

```text
Authority API + Authority Worker
+ PostgreSQL Authority + Object Store
+ transactional Outbox + Reconciliation
+ no Legacy write + no silent fallback
```

PostgreSQL owns Task/State; Outbox is the reliable notification source; Queue/Celery/Redis is delivery only. Worker groups are `authority`、`execution`、`integration` and `maintenance` rather than one process per domain.

Every B Slice records `legacy_source / authority_target / import / validation / writer_cutover / reader_compatibility / retirement_deadline`. Critical Writer cutover is part of the Slice, not deferred to Track F.

Track B Gate:

```text
project_book_scope_authority_proven=true
typed_book_design_asset_proven=true
execution_classification_enforced=true
minimal_authority_only_runtime_verified=true
production_legacy_write_blocked=true
duplicate_replay_proven=true
query_projection_proven=true
```

These values are verified for the Book/BookDesign minimum only. The broader production `authority_only_runtime_verified` flag remains false pending Track E hardening.

## 4A. D0 — Real Provider Qualification Probe

D0 starts only after the Track B minimal runtime is usable and precedes Track C implementation. It uses one explicit Provider, model and structured capability to record auth, request identity, timeout, retrieve/query, cancel, usage, cost, receipt, UNKNOWN reconciliation, late result and restart recovery. It is not chapter or fiction-quality proof.

Missing credentials produce `BLOCKED_MISSING_CREDENTIALS`; fixture conformance cannot turn any real-provider Gate true.

```text
real_provider_auth_proven=true|false
provider_request_receipt_proven=true|false
provider_usage_proven=true|false
provider_cost_proven=true|false
provider_timeout_query_cancel_behavior_recorded=true|false
unknown_reconciliation_proven=true|false
```

Current result at `ea687647...`:

```text
status=BLOCKED_MISSING_CREDENTIALS
real_provider_auth_proven=false
provider_request_receipt_proven=false
provider_usage_proven=false
provider_cost_proven=false
provider_timeout_query_cancel_behavior_recorded=false
unknown_reconciliation_proven=false
```

## 5. Track C — Novel Domain And Context

Track C may begin domain modeling near the end of Track B, but shared schemas cannot be changed concurrently without an accepted ADR.

### Slice C1 — Book Design To Active Plan

```text
Book Intent
→ BookDesign Candidate
→ Approval/Activation
→ BookPlan Candidate
→ PlanVersion Activation
→ Dependency/Impact Query
```

Required separation:

- Book Design defines genre, theme, reader promise, ending, world, character and core conflict;
- Planning defines Book/Volume/Arc/ChapterGroup/Chapter progression;
- design changes create impact analysis instead of silently modifying plans.

Planning uses controlled node types:

```text
BOOK
VOLUME
ARC
CHAPTER_GROUP
CHAPTER
```

Layers may be optional for shorter formats, but custom uncontrolled node types are not allowed.

### Slice C2 — ChapterOutcome To StoryState Replay

```text
Final ChapterOutcome
+ Approved Canon Changes
+ Previous StoryState Snapshot
+ Reducer Version
→ New StoryState Snapshot
→ Replay Checksum
```

Required semantics:

- ChapterOutcome is a change declaration;
- Canon is approved stable truth;
- StoryState is the current dynamic projection;
- Recap is read-only analysis, not a formal state source.

### Slice C3 — Context Compiler

```text
Domain Context Requirement
→ frozen AssetVersions
→ Canon/StoryState
→ eligible Source/Material/Knowledge
→ selection and budget
→ compression and validation
→ ContextManifest
→ ActualSentContext
```

Required separation:

```text
Source = origin, rights, risk, eligibility
Material = creative facts and reusable subject matter
Knowledge = methods, rules, templates and review criteria
```

### Slice C4 — Replan And Historical Freeze

```text
Deviation
→ ReplanRequest
→ PlanDiff Candidate
→ ImpactAnalysis
→ Decision
→ Future PlanVersion
→ EffectiveRange
→ Context invalidation
```

Final Release history cannot be silently rewritten. Retcon/Correction uses a separate Operation and replay/impact workflow.

Track C Gate:

```text
book_design_to_plan_proven=true
planning_version_and_effective_range_proven=true
story_state_replay_proven=true
context_reproducibility_proven=true
source_material_knowledge_boundary_proven=true
historical_freeze_and_replan_proven=true
```

## 6. Track D — Intelligence, Execution And Quality

Track D begins only after ContextManifest, StoryState and Asset Commit contracts are stable.

### Slice D1 — Qualified Real Provider Capability

Start with one capability:

```text
chapter.draft.generate
```

Required proof:

```text
ExecutionRequest
→ Capability qualification
→ RouteSnapshot
→ ActualSentContext
→ real Provider request
→ usage/cost
→ normalized Candidate
→ Receipt
→ recovery projection
```

### Slice D2 — Real Provider Chapter

Expand through:

```text
Draft
→ Review
→ Revision
→ Re-review
→ Canon Extraction
→ Quality Groups
→ Gate Aggregate
→ Final Release
```

Must prove:

- timeout;
- retrieve/query;
- cancel when supported;
- duplicate callback;
- UNKNOWN reconciliation;
- late result;
- worker restart;
- actual usage and cost;
- Chinese web-fiction editorial acceptance.

### Slice D3 — Agent Candidate And Commit

```text
AgentWorkOrder
→ frozen ScopeSnapshot
→ Candidate v1
→ Challenge/Conflict
→ Candidate v2
→ Authority Decision
→ Asset Commit Reference
```

Agent cannot directly update formal plans, Canon, StoryState, Book Cursor or publishing state.

### Slice D4 — Production Quality And Eval Lab

Separate:

- Production Quality Gate;
- Evaluation And Calibration Lab.

Until calibration passes, Reader Outcome remains SHADOW and uncalibrated scores remain raw/ordinal/pairwise evidence.

Track D Gate:

```text
single_capability_real_provider_proven=true
single_chapter_real_provider_proven=true
real_usage_proven=true
real_cost_proven=true
agent_candidate_commit_boundary_proven=true
production_quality_eval_separation_proven=true
```

## 7. Track E — Autonomous Book Runtime And Operations

### Slice E1 — L3 Book Coordinator

```text
Active BookDesign/Plan
→ Coordinator reserves Chapter 1
→ Chapter Production
→ ChapterOutcome
→ StoryState Reduce
→ Cursor Advance
→ Chapter 2
→ Chapter 3
```

The Coordinator owns Root Saga, Cursor, child Operation references and blocked state. It does not own generation, Canon, StoryState, quality or planning computation.

### Slice E2 — L10 Recap And Replan

Add:

- Recap cadence;
- Deviation and Replan;
- PlanDiff/Impact;
- pause/resume;
- duplicate command;
- stale fence;
- Provider failure;
- worker/database restart;
- Context growth;
- Book/Chapter budget caps;
- human InterventionTask.

### Slice E3 — Production Runtime Hardening

Track B already owns the minimal Authority-only runtime. Track E adds only production hardening:

- migration-aware readiness;
- worker heartbeat;
- queue/outbox lag;
- stuck Saga detection;
- Service Identity and Project/Book RBAC;
- secret references;
- backup/PITR/restore rehearsal;
- operator-visible blocked reason and recovery action.

Track E Gate:

```text
book_coordinator_l3_proven=true
book_coordinator_l10_proven=true
recap_replan_loop_proven=true
production_runtime_hardening_verified=true
persistent_state_restart_proven=true
inflight_durable_job_recovery_proven=true
provider_external_effect_restart_recovery_proven=true
operator_intervention_flow_proven=true
```

## 8. Track F — Migration, Long-form And Scale Proof

### Slice F1 — Residual Legacy Retirement

Critical-path Writer cutover belongs to each earlier vertical Slice. Track F retires remaining non-critical Legacy readers, expired compatibility paths and observed archives by business chain:

```text
Project/Book
→ BookDesign/Plan
→ Context
→ Chapter
→ Canon/StoryState
→ Quality/Outcome/Recap
```

Per wave:

```text
Discover
→ Classify
→ Dry-run Convert
→ Validate
→ Authority Import
→ Verify
→ Freeze Legacy Writer
→ Observe
→ Delete Writer
→ Archive/Delete Reader
```

No long-term double write.

### Slice F2 — L30 Arc Proof

Prove one meaningful Arc with:

- plan progression and replan;
- character/relationship state;
- foreshadowing and payoff;
- Reader Promise;
- Canon/StoryState drift control;
- quality, cost and latency trends;
- human samples;
- recovery and operator load.

### Slice F3 — Post-closure Readiness

After Architecture Closure:

```text
L100 → L300 → L1M
3 → 5 → 10 Books
Official Publishing Adapter
Feedback And Controlled Learning
Multi-user Productization
```

Track F Gate:

```text
critical_legacy_writers_retired=true
l30_arc_proven=true
cross_book_contamination_baseline_passed=true
architecture_closure_gate_passed=true
```

## 9. WIP And Delivery Policy

- one primary vertical Slice at a time;
- one additional stabilization/defect lane is allowed;
- no parallel cross-kernel redesigns;
- no Slice advances without its Gate Report;
- no deferred testing debt for shared Authority contracts;
- no independent AC completion percentage;
- no real-provider or long-form claim without exact-SHA evidence;
- no new isolated module expansion unrelated to the active Slice.

## 10. Architecture Closure Exit

Architecture Closure is complete only when:

```text
one complete current SHA builds and deploys
one Authority-only Runtime starts without Legacy
one real Provider Chapter records usage, cost and recovery
one Book Coordinator chain completes L10 with Recap/Replan
one real L30 Arc passes state, quality and recovery review
critical Legacy Writers on the production path are retired
Architecture Fitness Tests block regression
```

## 11. Current Non-goals

Until Track D and Track E are complete:

- no repository/package rename;
- no third production runtime;
- no broad new feature modules unrelated to closure;
- no public SaaS deployment;
- no automatic irreversible publishing;
- no ten-book scheduling program;
- no claim that Fixture, UI or design evidence is production proof.
