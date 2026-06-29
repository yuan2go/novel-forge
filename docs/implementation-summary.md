# Implementation Summary

Date: 2026-06-30

## Source Document

Primary optimization document:

- `docs/08-roadmap/novel-os-remaining-closure-plan.md`
- `docs/architecture/novel-operating-system-new-capabilities.md`

Execution tracking documents:

- `docs/auto-implementation-plan.md`
- `docs/08-roadmap/novel-os-remaining-closure-plan1.md`

## Completed Optimization Items

| Area | Status | Evidence |
|---|---|---|
| Universal Runtime Policy | Hardened runtime boundary | Runtime policy registry, strict/compat mode, `RuntimePolicyEnvelope`, KG-context requirement, enforcement report API, zero review-required legacy entrypoint audit, GuardedModelAdapter and ModelGateway model-call ledger capture, `tests/unit/test_runtime_policy.py` |
| Provider Runtime Guard | Hardened runtime boundary | `ProviderRuntimeController`, OpenAI-compatible SSE streaming usage, streaming delta cutoff, cancel/timeout/postflight guard, local Codex/Claude Code polling cancel, provider guard gate results, failed model-call logs, runtime events, `tests/unit/test_provider_runtime_guard.py` |
| Deep Checkpoint Resume | Hardened adapter/gateway boundary | Stage schema, idempotency, resume plan, durable stage checkpoints persisted as `agent_checkpoint`, GuardedModelAdapter and ModelGateway prompt/provider/output stage checkpoints, raw provider output segment persistence, raw-output manifest assembly, validation-stage resume without rerunning provider, checkpoint chain view, `tests/unit/test_operation_checkpoint.py` |
| Business Rollback | Hardened first production slice | `operation_transaction`, `rollback_plan`, `rollback_result`, version-restore rollback action, ledger compensation, KG/index dirty marker, preview/apply/verify APIs, two-phase coordinated multi-transaction rollback, `tests/unit/test_operation_transactions.py` |
| KG Semantic Depth | Hardened first production slice | Semantic extraction report asset/API, model-assisted entity/relation/event validation, identity resolution and merge queue, evidence/confidence, KG gate/preflight integration, KG-backed context enforcement, context build plan -> context bundle KG propagation, workbench action |
| Feedback Backflow | Completed first production slice | `src/novel_forge/modules/feedback_backflow/`, feedback backflow API endpoints, Feedback Agent permissions, `tests/unit/test_feedback_backflow.py` |
| Long-chain Scale Acceptance | Completed smoke plus opt-in pressure profile | `tests/integration/test_novel_os_long_chain_smoke.py`, `tests/integration/test_novel_os_long_chain_pressure.py`, long-chain scale metrics in `modules/operations` |
| Runtime Performance Hardening | Completed targeted fixes | KG gate avoids repeated graph builds; project reference filtering avoids full scans for non-asset trace references |
| Test Provider Isolation | Completed | Unit/integration tests force deterministic `mock` provider where needed; default production provider remains Claude Code Codex |
| P1/P2 Novel OS Capabilities | Completed local-first first production slice | ModelRouter/ModelGateway, PromptRegistry, ToolGateway/MCP registry, StateBus, AgentMessageBus, L0-L5 memory, pgvector schema plan, deterministic local embedding projection, hybrid retrieval, `/product/os/*` APIs, Workflow ProcessorRegistry operations, AgentOperationRegistry operations, `tests/unit/test_os_new_capabilities.py` |
| Provider SDK Streaming | Hardened provider-native path | OpenAI-compatible SDK streaming guard with usage chunk normalization, live delta observation, token/cost cutoff, stream close on cancel/failure, and `tests/unit/test_model_adapter.py` |
| Physical Multi-Asset Rollback | Hardened transactional rollback | `physical_restore` rollback strategy, rollback archive quarantine, pre-restore backup, previous-version restore, dirty-index verification, immutable ledger compensation, and two-phase cross-transaction coordination tests in `tests/unit/test_operation_transactions.py` |
| Pgvector Online Query | Completed online first production slice | PostgreSQL/pgvector schema creation, online migration dry-run/apply contract, chunk upsert, online similarity query, strict/fallback modes, hybrid retrieval evidence, operations/pressure plan, and `tests/unit/test_os_new_capabilities.py` |
| Pgvector-First Context Retrieval | Hardened OS retrieval boundary | Context Builder `backend=auto` now tries pgvector internal knowledge/memory retrieval before Qdrant, preserves source-asset paths from chunk results, deduplicates memory/vector hits by source, and treats Qdrant as optional high-performance service; `tests/unit/test_storage.py` |
| MCP Remote Tool Adapter | Completed HTTP JSON-RPC first production slice | Remote MCP server registration, remote tool definition materialization, `tools/list` discovery, `tools/call` invocation, invocation trace evidence, and `tests/unit/test_os_new_capabilities.py` |
| Playwright Cockpit Smoke | Hardened optional smoke | Browser route smoke now also probes a running backend fixture for Workflow, Agent, KG, Trace, Cost, Runtime Policy, and Publishing JSON endpoints when `NOVEL_FORGE_API_BASE_URL` or strict mode is set; CI has a normal architecture job and an opt-in strict Chromium smoke job; `web/admin/tests/playwright-smoke.test.mjs`, `.github/workflows/web-cockpit-smoke.yml` |
| Web OS Cockpit Deep Interaction | Hardened operator surface | Workflow console includes a DAG graph and edge table; Agent console includes a timeline; KG workbench shows relation edges; Cost dashboard has a ledger trend view; OS console has coordinated rollback preview/apply controls; `web/admin/tests/feature-architecture.test.mjs` |
| Protected Reference Intake | Hardened first production slice | TXT/MD encoding detection for UTF-8/GB18030/GBK/Big5, `analyze-reference` CLI, oral-performance style metrics for pingshu/xiangsheng-like narration, abstract-only analysis assets, `tests/unit/test_cli.py` |
| Context Builder Policy Evidence | Hardened runtime boundary | Context bundles and RAG quality reports now persist `policy_rejections` / `manual_policy_rejections` when manual selections try to include raw sources, analysis reports, explicit no-RAG assets, or high-risk material; `tests/unit/test_context_and_production_chain.py` |

## Remaining Items

These are not blocked for the current deliverable, but remain future hardening work:

| Item | Reason |
|---|---|
| Additional provider SDK streaming | OpenAI-compatible SSE/SDK and local process polling are implemented; non-OpenAI-native SDKs still need adapter-specific streaming/cancel bindings when those providers are added. |
| Mandatory browser Playwright smoke | CI now has an opt-in strict browser-smoke job for real Chromium + live backend fixtures. It remains label/manual-gated because installing browsers on every push is slow and unnecessary for non-UI changes. |
| Provider-backed KG extraction | Model-assisted extraction candidates are locally validated and merged into reports; provider-backed extraction must use the same GuardedModelAdapter/ModelGateway runtime evidence boundary. |
| Deep service-internal checkpoint for non-standard long tasks | GuardedModelAdapter and ModelGateway now record prompt/provider/output stages and raw-output segments; any future custom long task that bypasses those boundaries must explicitly use the same checkpoint contract. |
| Cross-workflow rollback orchestration | Two-phase coordinated rollback exists for multiple transactions. Future hardening is richer operator diff review and rollback rehearsal against large live workspaces. |
| Local Codex CLI host permissions | The adapter now runs with `--ignore-user-config --ignore-rules --ephemeral --sandbox read-only`; this project records provider failure and falls back safely if the installed Codex CLI still cannot initialize in the current OS sandbox. |

## New Modules

- `src/novel_forge/modules/runtime_policy/`
- `src/novel_forge/model_adapters/runtime.py`
- `src/novel_forge/modules/operation_checkpoint/`
- `src/novel_forge/modules/operation_transactions/`
- `src/novel_forge/modules/feedback_backflow/`
- `src/novel_forge/modules/novel_kg/identity.py`
- `src/novel_forge/modules/semantic_enhancement/`
- `src/novel_forge/modules/model_router/`
- `src/novel_forge/modules/prompt_registry/`
- `src/novel_forge/modules/tool_gateway/`
- `src/novel_forge/modules/state_bus/`
- `src/novel_forge/modules/agent_messages/`
- `src/novel_forge/modules/long_memory/`
- `src/novel_forge/modules/pgvector_store/`
- `src/novel_forge/api/routers/os_capabilities.py`

## Modified Modules

- Runtime and scheduling: `agent_runs`, `agent_scheduler`, `workflow_nodes`, `runtime_ledger`
- Model adapters: `providers`, `guarded`, adapter exports, ModelGateway runtime evidence
- KG and continuity: `novel_kg`, `continuity_graph`, `production_context`, `context_builder` KG-backed bundle propagation
- Intake and analysis: `ingestion` encoding detection, `analysis` oral-performance abstraction, CLI `analyze-reference`
- Feedback and review: `feedback`, `audit`, review rework related services
- Schemas/constants: new asset mappings and dataclasses for rollback, checkpoints, feedback backflow, KG identity
- Web Admin: OS console route set and navigation
- CI: Web cockpit architecture and opt-in strict Chromium smoke workflow
- Tests and docs

## Deleted Or Deprecated Modules

None. Existing APIs and assets remain compatible. Long-running route smoke tests were split from full acceptance tests rather than removed.

## Data And Schema Changes

New asset types include:

- `operation_transaction`
- `operation_raw_output_segment`
- `operation_raw_output_manifest`
- `rollback_plan`
- `rollback_result`
- `rollback_coordination_report`
- `kg_identity_resolution`
- `feedback_cluster`
- `feedback_backflow_plan`
- `plan_adjustment_proposal`
- `review_rule_update_proposal`
- `feedback_kg_patch`
- `semantic_extraction_report`
- `model_route`
- `model_route_resolution`
- `prompt_template`
- `prompt_release`
- `prompt_node_binding`
- `tool_definition`
- `tool_invocation`
- `tool_permission_policy`
- `mcp_server_registry`
- `state_event`
- `state_snapshot`
- `state_replay`
- `state_conflict_report`
- `agent_message`
- `agent_inbox`
- `agent_outbox`
- `agent_handoff`
- `agent_conversation_trace`
- `memory_record`
- `memory_selection`
- `memory_retrieval_report`
- `memory_chunk`
- `knowledge_chunk`
- `artifact_embedding`
- `review_memory_chunk`
- `entity_memory_chunk`
- `pgvector_schema_plan`
- `pgvector_operations_plan`
- `embedding_job`
- `hybrid_retrieval_report`

Runtime service tables created when online pgvector is enabled:

- `nf_pgvector_chunks` with `vector(64)` embeddings and ivfflat cosine index.

All are local JSON asset types mapped through `ASSET_DIR_BY_TYPE`; no destructive migration is required.

## API Changes

New or extended endpoints:

- `GET /product/runtime/policy/status`
- `GET /product/runtime/policy/enforcement-report`
- `POST /product/runtime/policy/check`
- `POST /product/runtime/rollback/coordinate`
- `POST /product/runtime/rollback/verify`
- `POST /product/novel-kg/semantic-extraction`
- `POST /product/feedback/backflow-plan`
- `POST /product/feedback/backflow-apply`
- `/product/os/model-router/*`
- `/product/os/prompts/*`
- `/product/os/tools/*`
- `/product/os/state/*`
- `/product/os/messages/*`
- `/product/os/memory/*`
- `/product/os/retrieval/*`

ToolGateway MCP behavior is available through the existing `/product/os/tools/*` route family. Registered HTTP JSON-RPC MCP servers can expose remote `tool_definition` assets and invoke `tools/call`.

Existing workflow, agent, KG, trace, cost, feedback, and production endpoints remain available.

## UI Changes

The Web Admin OS console first slice remains wired through:

- `/os`
- `/workflow-runtime`
- `/agent-dispatch`
- `/novel-kg`
- `/trace-timeline`
- `/cost-dashboard`
- `/invalidation`
- `/review-rework`

Navigation and architecture tests verify these routes and API contracts.

The OS console now includes runtime policy coverage, rollback verification, and coordinated multi-transaction rollback preview/apply panels. The Workflow console includes a compact DAG graph and dependency edge table. The Agent console includes a scheduler timeline. The Cost dashboard includes a ledger trend view. The Novel KG workbench can create semantic extraction reports and displays relation edges from the graph. The optional Playwright smoke can also verify a live backend fixture by setting `NOVEL_FORGE_API_BASE_URL`; strict mode defaults to `http://127.0.0.1:8000`.

## Test Results

Passed on 2026-06-30:

```bash
python3 -m compileall -q src tests
python3 -m unittest tests.unit.test_operation_checkpoint tests.unit.test_operation_transactions tests.unit.test_os_new_capabilities tests.unit.test_product_api_routes
python3 -m unittest tests.unit.test_model_adapter tests.unit.test_provider_runtime_guard tests.unit.test_operation_transactions tests.unit.test_os_new_capabilities
python3 -m unittest tests.unit.test_model_adapter tests.unit.test_provider_runtime_guard tests.unit.test_storage tests.unit.test_os_new_capabilities
python3 -m unittest tests.unit.test_model_adapter tests.unit.test_provider_runtime_guard tests.unit.test_storage tests.unit.test_os_new_capabilities tests.unit.test_product_api_routes
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest tests.integration.test_novel_os_acceptance
git diff --check
npm --prefix web/admin test
npm --prefix web/admin run lint
```

Observed counts:

- Latest focused runtime test batch: 20 passed for checkpoint raw segments, coordinated rollback, pgvector operations, and API route contracts.
- Focused Python tests: 31 passed for runtime integrations, then 39 passed for provider SDK cutoff, storage retrieval, and OS capabilities.
- Route-focused Python tests: 40 passed.
- Full Python unit discovery: 229 passed.
- Full Python repository discovery on 2026-06-30 after this closure: 238 passed, 1 skipped.
- Core OS acceptance: 1 passed.
- Web Admin tests: 7 passed, 1 browser smoke skipped because Playwright is not installed locally. `npm --prefix web/admin run lint` passed.

## Known Risks

- Real Claude Code/Codex execution can fail in restricted sandboxes; deterministic tests set `NOVEL_FORGE_MODEL_PROVIDER=mock`.
- Future provider streaming cutoff needs provider-specific streaming adapters beyond OpenAI-compatible SSE/SDK and local process polling.
- Long-chain pressure tests should be run locally with explicit resource budget and not as default CI.
- Online pgvector requires PostgreSQL with the `vector` extension and optional `psycopg`; local fallback remains available unless strict mode is enabled.

## Startup

Local deterministic validation:

```bash
make test
make validate
```

Local production-style stack:

```bash
make local-up
```

Default production model runtime:

```bash
CODEX_HOME=~/.codex-claude codex
```

Use deterministic mock provider for tests or offline demos:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=mock
```

Enable optional online/runtime smokes:

```bash
export NOVEL_FORGE_PROVIDER_SDK_STREAMING=1
export NOVEL_FORGE_PGVECTOR_ONLINE=1
export NOVEL_FORGE_API_BASE_URL=http://127.0.0.1:8000
```

## Core Flow Verification

Runtime OS acceptance:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
```

Long-chain scale smoke:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
```

Opt-in 12/50 chapter pressure acceptance:

```bash
NOVEL_FORGE_RUN_LONG_CHAIN_PRESSURE=1 NOVEL_FORGE_LONG_CHAIN_CHAPTERS=12 PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_pressure
```

Web Admin contract tests:

```bash
npm --prefix web/admin test
npm --prefix web/admin run lint
```
