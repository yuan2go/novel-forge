# Architecture And Module Map

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

This map describes current code boundaries and evidence limits. A module being present does not mean real-provider, long-form or production proof exists.

## 1. Top-level Runtime Map

```text
Web Admin / CLI / API
        │
        ├── Legacy Local-first Surface
        │     ├── LocalStorage
        │     ├── workflows.pipeline compatibility facade
        │     ├── product service/router facade
        │     └── Celery worker
        │
        └── PostgreSQL Authority Surface
              ├── Trusted Principal
              ├── Production Preparation
              ├── Command Kernel
              ├── Domain Authority Applications
              ├── Durable Authority Workers
              ├── Production Execution Gateway
              ├── External Effects / Receipts
              ├── AssetVersion / Blob Authority
              └── Strong Queries / Projections
```

Target dependency direction:

```text
UI/API
→ Application/Authority facade
→ Operation/Saga orchestration
→ Domain handler or Production Execution Gateway
→ PostgreSQL repositories / controlled external effects
→ projections and operator queries
```

New production paths must not write directly to LocalStorage or call Provider/platform adapters outside the governed execution plane.

## 2. Entrypoints

| Area | Path | Responsibility | Current status |
|---|---|---|---|
| Runtime selector | `src/novel_forge/api/app.py` | Select Authority or Legacy API from settings | Implemented; default development selection remains Legacy |
| Authority API | `src/novel_forge/api/authority_app.py` | PostgreSQL-only command/query surface | Implemented composition root, but current imported module integrity needs verification |
| Legacy API | `src/novel_forge/api/legacy_app.py` | local-first compatibility/product runtime | Still active in development and default Compose |
| CLI selector | `src/novel_forge/cli/__init__.py` | Authority/Legacy CLI selection | Implemented; command surfaces differ |
| Authority workers | `src/novel_forge/workers/*authority*.py` | poll, recover and execute durable Authority work | Chapter worker exists; default deployment wiring incomplete |
| Web Admin | `web/admin/` | operator console | Broad route coverage; auth/browser E2E incomplete |

## 3. Core Authority Layer

### 3.1 Command Kernel

| Module | Path | Responsibility | Maturity |
|---|---|---|---|
| Command admission | `modules/command_kernel/service.py` | schema, definition, permission, approval, idempotency and frozen input validation | High |
| Operation lifecycle | `modules/command_kernel/runtime.py` | compare-and-set state transitions | High |
| Saga graph | `modules/command_kernel/operation_graph.py` | dependencies, Saga steps, gate and completion coordination | Medium-high |
| Attempt runtime | `modules/command_kernel/attempt_runtime.py` | Attempt create/queue/lease/start/result/retry | High |
| Cancellation | `modules/command_kernel/cancellation.py` | cancellation command and worker signal | Medium-high |
| External effects | `modules/command_kernel/external_effect_runtime.py` | effect dispatch, query, cancellation, reconciliation | Medium-high, fixture/real-provider boundary remains |
| Deadline runtime | `modules/command_kernel/deadline_runtime.py` | business deadline scanning and timeout handling | Medium |
| Worker boundary | `modules/command_kernel/worker_execution.py` | isolate task failures and fatal programming errors | Medium-high |

### 3.2 Authority persistence

| Module | Path | Responsibility | Maturity |
|---|---|---|---|
| Unit of Work | `storage/authority_uow.py` | short PostgreSQL transaction boundary | Implemented; no production connection pool shown |
| Repositories | `storage/authority_repositories.py` | definitions, operations, attempts, effects, evidence, assets and projections | Broad implementation |
| Migrations | `storage/migrations/` | sequential PostgreSQL schema evolution | 50 migrations indexed; latest targets require integrity verification |
| Worker health | `storage/worker_health.py` | durable worker observation | Implemented projection slice |

Database-level invariants include idempotency uniqueness, one active Attempt, one held Lease, monotonic Attempt/fence values, project-scoped references and acyclic dependencies.

## 4. Chapter Production Authority

| Module | Path | Responsibility | Maturity |
|---|---|---|---|
| Application | `modules/chapter_authority/application.py` | command admission, synchronous fixture boundary and scheduler construction | Medium-high |
| Orchestrator | `modules/chapter_authority/orchestrator.py` | Root Operation, Saga, 18-node execution and fixture recovery | Medium-high |
| Contracts | `modules/chapter_authority/contracts.py` | Chapter nodes, typed inputs/outputs and handler registry | High |
| Handlers | `modules/chapter_authority/handlers.py` | Plan, Context, model stages, Canon, Quality and release handlers | Medium-high; semantic quality unproven |
| Scheduler | `modules/chapter_authority/scheduler.py` | durable asynchronous execution/recovery | Implemented; deployment proof incomplete |
| Queries | `modules/chapter_authority/queries.py` | strong run and evidence queries | Implemented |
| Execution gateway binding | `modules/chapter_authority/execution_gateway.py` | bind Chapter stages to PEP routes and recovery records | Medium-high fixture proof |
| Export delivery | `modules/chapter_authority/export_delivery.py` | object effect, reconciliation and receipt evidence | Fixture proof |

Authoritative chain:

```text
Plan
→ Context
→ Draft
→ Review
→ Revision
→ Re-review
→ Canon Extraction
→ Canon Proposal
→ Canon Update
→ 5 Quality groups
→ Quality Aggregate
→ Publish Gate
→ Export
→ Final Release Gate
```

## 5. Book And Long-form Authority

| Module | Path | Responsibility | Maturity |
|---|---|---|---|
| Book Authority | `modules/book_authority/production.py` | Book root, sequential cursor, Chapter delegation, acceptance and control | Medium |
| Chapter Outcome | `modules/chapter_outcome/` | accepted Chapter output and Story State reduction | Medium |
| Book follow-up | `modules/book_followup_authority/` | Reader Outcome and Longform Recap Operations | Medium-low semantic maturity |
| Story state reducer registry | `modules/story_state_reducer*` and migration `0037` | reducer identity and state evolution | Foundation |
| Story Design Authority | migration/module references around `0038` | semantic generator lifecycle | Foundation/partial |
| Hierarchical planning | migration/module references around `0039` | Book/Volume/Arc/ChapterGroup planning | Foundation/partial |
| Chapter Group Authority | migration/module references around `0040` | group checkpoint and child references | Foundation/partial |
| Plan Change Authority | migration/module references around `0041` | diff, impact, decision and activation | Foundation/partial |
| Reader calibration | migration/module references around `0042` | preference, exposure, outcome and drift | Fixture foundation |

Book Authority currently coordinates versioned Chapter work. It is not yet a complete autonomous whole-book supervisor.

## 6. Production Execution And Provider Control

| Module | Path | Responsibility | Maturity |
|---|---|---|---|
| Production Execution | `modules/production_execution/` | request contracts, route snapshots, admission, backend registry, validation, commit and recovery | Medium-high protocol maturity |
| Provider Control | `modules/provider_control/` | Provider v2 registry, capabilities, qualification, query/cancel/callback | Medium |
| OpenAI v2 | `modules/provider_control/openai_v2.py` | explicit OpenAI SDK transport seam | Implemented code seam; real composition/cost proof missing |
| Model Router compatibility | `modules/model_router/`, `model_adapters/` | legacy/development routing and fail-closed boundaries | Migration/compatibility only for production |
| Runtime ledger | `modules/runtime_ledger/` | call, token, cost and trace evidence | Partial universal coverage |
| Runtime policy | `modules/runtime_policy/` | provider/environment/gate policy | Partial universal coverage |

Controlled environments must use explicitly registered V2 adapters. Scripted providers are fixture-only. Automatic CI does not establish real-provider proof.

## 7. Content, Knowledge And Source Modules

| Group | Main paths | Current role | Authority state |
|---|---|---|---|
| Source intake/governance | `modules/source_intake/`, `modules/ingestion/` | source metadata, rights, risk, snapshots and import | broad Legacy foundation; Source Authority migration in progress |
| MKAOS | `modules/mkaos/`, `mkaos_*` | knowledge candidates/cards/packs, quality, lineage, conversion and feedback | broad Legacy foundation; MKAOS Authority migration in progress |
| Context Builder | `modules/context_builder/` | stage-aware selection, source isolation and token budgeting | meaningful implementation; universal Authority use still converging |
| Retrieval | storage vector/Qdrant/pgvector modules | local and controlled remote retrieval | partial production evaluation |
| Materials | `modules/materials/` | reusable material cards | implemented Legacy/domain slice |
| Analysis/decomposition | `modules/analysis/`, `modules/decomposition/` | abstract craft/business analysis | partial provider quality and Authority migration |
| Genre/Style | `modules/genre_os/`, `modules/style_os/` | profiles, strategy, policy and drift evidence | implemented foundation, calibration partial |

Current HEAD imports new `project_authority`, `task_authority`, `source_authority` and `mkaos_authority` modules. Their complete file set must be verified before Authority API build claims.

## 8. Canon, Quality And Creative Domains

| Domain | Main paths | Current status |
|---|---|---|
| Canon Graph | `modules/canon_graph/` | conflict/proposal/snapshot foundations; repair UX partial |
| Continuity / KG | `modules/continuity_graph/`, `modules/novel_kg/` | partial graph and continuity workbench |
| Quality Authority | `modules/chapter_quality_authority/`, Chapter handlers | five groups and aggregate evidence; calibration incomplete |
| Evaluation Center | `modules/evaluation_center/`, `modules/quality_eval/` | golden-set/calibration foundations; real premium Judge proof absent |
| Reader Promise | `modules/reader_promise/` | promise/payoff ledger foundation |
| Chapter Economy | `modules/chapter_economy/` | pleasure/repetition/water risk foundation |
| Character Pressure | `modules/character_pressure/` | agency/charm/antagonist pressure foundation |
| Mobile Reading | `modules/mobile_reading/` | paragraph density and scanability foundation |
| Topic/World/Character/Outline | corresponding `modules/*` | broad local/domain generation slices |
| Draft/Review/Revision | corresponding `modules/*` plus Chapter Authority | Legacy/domain services plus Authority production stages |

Heuristic and fixture outputs must not be described as production-calibrated quality judgments.

## 9. Product And Operations Modules

| Group | Main paths | Current status |
|---|---|---|
| Web API routers | `api/routers/` | broad surface; Authority and Legacy routers coexist |
| Product service facade | `api/services/` | compatibility and orchestration concentration remains |
| Workflow nodes | `modules/workflow_nodes/` | broad execution registry; legacy concentration remains |
| Agent Registry/Scheduler | `modules/agent_registry/`, `modules/agent_scheduler/` | first production slices, not complete autonomy |
| Agent Collaboration | `modules/agent_collaboration/` | frozen-scope deliberation fixture protocol |
| Permission Center | `modules/permission_center/` | approval lifecycle foundation, not complete multi-user RBAC |
| Publishing | `modules/publishing/`, `publishing_feedback_adapters/` | local/manual/generic adapter foundations; real platform proof absent |
| Portfolio OS | `modules/portfolio_os/` | scoring, isolation and allocation planning foundation; dispatch proof absent |
| Cockpit | `modules/novel_os_cockpit/`, `web/admin/app/features/os/` | broad evidence dashboard; guided repair and auth incomplete |

## 10. Current Architecture Risks

1. **HEAD integrity:** new Authority imports and migration registrations may not have all target files committed.
2. **Dual runtime:** Legacy and Authority can diverge in behavior and evidence.
3. **Deployment mismatch:** default Compose does not run the intended Authority API and durable worker topology.
4. **Security boundary:** trusted local Principal is not HTTP user authentication or multi-tenant authorization.
5. **Provider proof:** real adapter composition, usage, cost and cancellation remain unverified.
6. **Whole-book autonomy:** Book Authority coordinates Chapters but does not yet own continuous plan-generation/production/replan/ending progression.
7. **Database operations:** migrations are mostly forward-only and direct psycopg connections are used without a visible pool.
8. **Service concentration:** Legacy product, MKAOS, workflow and scheduler facades remain large and expensive to change.

## 11. Extension Rule

A new production capability is complete only when it has:

```text
OperationDefinition
+ permission/approval contract
+ frozen input AssetVersions
+ idempotency and concurrency identity
+ durable Attempt/Lease/Fence
+ governed execution or deterministic handler
+ output AssetVersions and qualification
+ audit/event/outbox evidence
+ strong query/API/UI exposure
+ recovery/cancel behavior
+ focused tests
+ current documentation update
```

Do not count a schema, class, route, page, fixture or design document alone as product completion.
