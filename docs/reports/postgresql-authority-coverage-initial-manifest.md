# PostgreSQL Authority Coverage: Initial Inventory

Date: 2026-07-12

This is a planning inventory, not a passing `AuthorityCoverageManifest`. It was
derived from static repository scans and must become build-generated immutable
JSON at implementation time.

## Baseline evidence

- `src/novel_forge` currently has **199** Python files importing or constructing
  `LocalStorage`.
- The largest groups are API routers (**44** files), `source_intake` (**10**),
  Agent Scheduler (**9**), MKAOS (**6**), and publishing (**5**).
- Existing Kernel registration covers only five definitions:
  `chapter_production.start`, `workflow.execute`, `agent.dispatch`, `loop.run`,
  and `review_revision_publish`.
- Existing production ingress is distributed across API routers, `cli`,
  `workers/tasks.py`, `workers/runtime.py`, workflow pipeline/industrial code,
  scheduler runners, provider adapters, and publishing/feedback callbacks.

## Required enabled-entrypoint inventory

| Kind | Current locations to inventory/replace | Required final route |
|---|---|---|
| API commands | `src/novel_forge/api/routers/*.py`, especially `assets.py`, `projects.py`, `production_chain.py`, `agents.py`, `loops.py`, `workflow_nodes.py`, `mkaos.py`, `context_builder.py`, `reviews.py`, `publishing_feedback_adapters.py` | typed Kernel command adapter |
| CLI commands | `src/novel_forge/cli/__init__.py`, workflow CLI surfaces | typed Kernel command adapter |
| Worker execution | `src/novel_forge/workers/tasks.py`, `runtime.py`, `dispatch.py` | Outbox claim -> Attempt/Lease -> Kernel result command |
| Scheduler/recovery | `src/novel_forge/modules/agent_scheduler/*.py` | Kernel lifecycle/recovery/compensation commands |
| Workflow/loop | `src/novel_forge/workflows/*.py`, `modules/workflow_nodes/*.py`, `modules/loop_kernel/service.py` | parent/child Operation/Saga handlers |
| Provider/tool calls | `modules/model_router/service.py`, `modules/tool_gateway/service.py`, `api/provider_adapters.py` | ExternalEffectDispatch worker only |
| Object/blob writes | `storage/object_store.py`, asset write paths | Blob intent/upload/verify result commands |
| Publishing/feedback callbacks | `modules/publishing/*.py`, `modules/publishing_feedback_adapters/*.py`, matching routers | ExternalEffect receipt Inbox command |
| Event consumers | `modules/state_bus/*.py`, worker consumers, analytics projections | transactional Inbox consumer |

## Current known bypass classes

1. `LocalStorage.write_json`/`write_asset` performs JSON authority writes and
   write-through PostgreSQL synchronization.
2. `PostgresAssetStore.sync_from_local` and worker post-task sync make
   PostgreSQL a secondary index.
3. `api/services/postgres_fallback_policy.py`, `api/app.py`, and
   `api/services/product.py` permit JSON/local fallback reads.
4. `production_kernel/service.py` itself accepts `LocalStorage` and persists
   parent operations as JSON assets.
5. Most router and domain-service mutation paths construct LocalStorage and
   call services directly.

## Passing manifest requirements

The generated manifest must enumerate every enabled command/callback/consumer
symbol and map it to an enabled `OperationDefinition`. Static architecture
tests, runtime registry discovery, and E2E evidence must report both
`unknown_write_paths=[]` and `kernel_bypasses=[]`.
