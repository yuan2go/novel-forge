# Current Engineering Progress And Feature Documentation

## 2026-07-22 Production execution gateway update

WP-03 implements the Attempt/fence-bound ProductionExecutionGateway, explicit
Backend Registry and admission/probe layer, Codex CLI/Remote Provider v2/scripted
backends, result normalization/structural validation/reconciliation, stable
ModelProfile and RoutePolicy resolution, and PostgreSQL read adapters over the
existing Authority Attempt/Lease and AssetVersion schema. Model Router has no direct
legacy adapter calls; repository-owned legacy Provider implementations fail closed in
controlled environments.

Evidence is fixture/protocol plus PostgreSQL admission integration only. Chapter
Authority has not yet migrated, no paid/real Provider request ran, and real Provider,
Book delegation, long-form, behavioral calibration, causal validation, and
production verification flags remain false.

## 2026-07-18 Pre-provider production architecture v2

Source evidence is bound to `98a7e003cd2b7b4821737fe3b22d0c35fe415b8a`.
Provider v2 production routing, durable callbacks, ChapterPlan v3, multi-entity and
budgeted Quality Context, PostgreSQL Calibration operations, trusted Typed Empty
creation, governed Canon re-extraction, Catalog supersession, a Book Root Saga
fixture, Creative generator boundary, and persistent worker health are present.

Maturity is `PRE_PROVIDER_PRODUCTION_ARCHITECTURE_COMPLETE`; all Provider and Book
proofs remain mock/fixture protocol. Real Provider, long-form, multi-book and
production verification remain false.

## 2026-07-18 Pre-provider functional convergence update

The current active branch is `feat/v7-content-intelligence-and-longform-proof`.
Current source evidence is bound to commit
`2e506f1467321e688d82365ef2734c9f70b7caaa`; older V6 progress below is retained as
historical detail, not as the current Authority verdict.

The PostgreSQL chapter slice now preserves full ChapterPlan fidelity, supports nine
typed empty state declarations, uses Provider Adapter v2 control contracts and five
stage-specific Quality views, and recovers Canon DEFER/reopen/re-extraction through
versioned commands and generations. Deterministic calibration contracts, worker
supervision, split CI, migration tests, and architecture boundaries are present.

Maturity is `FUNCTIONALLY_READY_FOR_PROVIDER_VALIDATION`; real Provider validation
has not started and `real_provider_proven`, `longform_proven`, and
`production_verified` remain false. See the focused reports linked from
`pre-provider-functional-convergence.md`.

日期：2026-07-03

## 1. 当前工程进度结论

当前分支：`feat/v6-post-mkaos-industrialization`

当前状态：

- Post-MKAOS Novel OS v6 工业化 Phase 0-12 已完成本地实现、测试、文档和分阶段提交。
- 分支已推送到 GitHub：`origin/feat/v6-post-mkaos-industrialization`。
- Novel OS v6 当前工业化完成度：**86/100**。
- MKAOS P0 已从“有条件完成”推进为：**完成**。
- 当前剩余工作主要是 P1/P2 深化，不是 P0 blocker。

2026-07-04 P1/P2 治理深化更新：

- 新增 Agent Registry：从 `AGENT_RUNTIME_PROFILES` 同步 registry entry，支持 lifecycle、version、capability、evaluation binding 和 scheduler active-only 调度校验。
- 新增 Audit Log / Audit Trail：AgentRun start/status 自动 best-effort 记录 audit event，并支持 project/trace 查询、trail report 和 source-isolated export package。
- 深化 Evaluation Center：从模型 benchmark 扩展为通用 `evaluation_suite` / `evaluation_case` / `evaluation_result` / `evaluation_gate`，EvaluationGate 阻断时可生成 ReviewIssue。
- 深化 pgvector PoC：schema plan 增加 source risk / license / permission / flow allowlist / evidence span / dirty index / quality score，新增 verify、dirty index rebuild 和 pgvector vs Qdrant comparison。
- 新增 ClickHouse Analytics 可选 OLAP 层：默认 offline projection，不写回业务主数据，真实 ClickHouse 通过环境变量 opt-in。
- 新增治理闭环集成测试：`Agent Registry -> Context Builder/pgvector -> AgentRun -> Audit Log -> Evaluation -> ReviewIssue -> Analytics -> Editor-in-Chief Console`。
- Web Admin 新增 `/agent-registry`、`/audit-log`、`/retrieval`、`/analytics`，并在 `/editor-chief` 显示 governance loop 摘要。
- 本轮未实现 Permission Center；保留现有 ToolPermissionPolicy / runtime profile 兼容逻辑，不新增 RBAC、用户、组织或 SaaS 权限体系。

2026-07-05 MKAOS P1 稳定化更新：

- 新增 `mkaos_model_extraction`：模型级深度抽取治理链路，包含 prompt version、provider runner、provider output sanitizer、schema validator、confidence scoring、human review queue、benchmark/regression、candidate approve/reject 和 provider evidence hash。
- 新增 `mkaos_production_gate`：统一生产门禁报告，Context Builder 自动执行 MKAOS gate；production/strict/operating_system 下 source leakage、blocking ReviewIssue、弱知识卡等风险 fail closed。
- 新增 `mkaos_lineage`：LocalStorage 本地图谱血缘索引，支持 source -> knowledge -> pack -> context -> draft -> review issue -> feedback -> weight governance 的路径查询、影响分析、反馈归因和调权 dry-run。
- 新增 MKAOS gate coverage、lineage diff/export 和显式 weight governance apply：历史非 ContextBuilder 入口可被 coverage report 标记，LocalStorage lineage 支持安全 diff/export/semantic ranking，权重写回必须显式 `apply_policy`。
- Editor-in-Chief Console 的 governance loop 已增加 MKAOS Gate Summary，可显示 latest gate status、blocking issue count、weak knowledge card、leakage risk、lineage coverage 和 recommendation。

2026-07-26 Production Execution WP-10 更新：

- MKAOS 的模型分析、知识/规则/模板抽取已改为通过统一执行端口返回候选；Rights、Source Eligibility、Source Isolation、Schema、Lineage、Review、Approval、Weight Governance 仍归 MKAOS。
- 受控 Qdrant 远程 Embedding 必须通过 Retrieval Execution Port，证据冻结模型、维度、源块 Hash、批次、索引版本、Usage/Cost 与 partial/dirty 状态；Rerank 冻结候选集版本和排序证据。
- 本轮仅完成 Fixture/本地集成证明，未执行真实 Embedding、Rerank 或付费 Provider 请求。

2026-07-26 Production Execution WP-11 更新：

- Longform Recap、Plan-vs-Actual、Drift、Arc Closure、Ending Reachability、PlanChange、关系抽取和 Forecast 已有统一候选执行合同；长链 Provider 章节候选不再直接调用 Model Router。
- 远程语义相似度必须通过 Retrieval Execution Port；本地 Hash 只作为确定性回归信号。
- Recap 不再原地修改 ArcPlan，而是生成含 Semantic Diff、Impact Analysis、Approval 和版本迁移约束的 `plan_adjustment_proposal`。
- 12/50 章测试均为确定性 Fixture 回归，`longform_proven=false`，未执行真实长篇 Provider 验证。

2026-07-26 Production Execution WP-12 更新：

- Agent Runtime 不再授予 `call_model_adapter`，模型型角色只能请求 `agent.workspace.execute`，且不得自行选择 Provider、模型、Backend、Route 或 reasoning effort。
- Agent Workspace 合同冻结 Snapshot、Read/Write Set、工具/命令白名单、网络、Git Base、输出合同、Hop/文件/成本上限及审批策略；结果只能是候选或 `proposed_only` Manifest。
- Review/Revision/Re-review Loop 拒绝直接 ModelAdapter payload，改为接收受控 ExecutionPort；确定性编排、领域校验和提交仍留在原模块。
- 51 项 Agent Scheduler/Loop/权限回归与 7 项 Agent Workspace/Backend 定向测试通过；未运行真实 Agent 进程、Provider 或工作区提交。

2026-07-26 Production Execution WP-13 更新：

- 发布提交/查询/撤稿、反馈抓取、远程源抓取、通知/Webhook 类行为统一为非模型 External Action 合同，绑定稳定幂等键、外部请求身份、Query/Cancel/Callback、外部回执、数据分类和隐私/限流/配额策略。
- Publishing 领域不再构造 HTTP 请求或读取平台 Token；Endpoint、超时和凭据归 RouteSnapshot/Backend，领域只接收候选和执行证据。
- 旧 API、Agent 本地 Runner 和 Workflow 本地 Runner 均 fail closed；平台 Gate、审批、发布决定、反馈导入、Source Eligibility/License/Isolation 仍留在领域模块。
- Backend Conformance 10 项、External/Publishing 定向 22 项、Publishing/Source/Feedback 回归 42 项通过；未发送任何真实外部请求。
- Web Admin 新增 `/mkaos/model-extraction/*`、`/mkaos/production-gate/*`、`/mkaos/knowledge-graph`、`/mkaos/lineage`、`/mkaos/impact`、`/mkaos/feedback-attribution` first-slice 页面。

2026-07-26 Production Execution WP-14 更新：

- 执行合同、内存/Authority 恢复记录和外部动作命令在持久化前递归拒绝明文 Secret；仅允许 `auth_profile_ref`、`credential_scope`、`secret_version_ref`。
- Codex Process 保持显式环境白名单，并在解析前执行结果文件大小上限；明文凭据无法经 Payload、环境覆盖或 Process 输入进入执行路径。
- Agent Workspace 新增冻结输出目录和单文件大小上限；修改文件、文件大小、输出路径均由 Backend 在 Runner 返回后校验。
- 93 项 PEP Security/Contract/Routing/Backend/Workspace 聚焦测试通过；未解析真实凭据，未调用真实 Provider 或外部平台。

最终验证：

| 测试命令 | 当前结果 |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` | 477 tests OK, skipped=2, 383.986s |
| `PYTHONPATH=src python3 -m unittest tests.integration.test_pipeline` | 1 test OK; sample pipeline second-run idempotency preserved |
| `python3 -m unittest tests.unit.test_longform_recap_agent tests.unit.test_loop_kernel tests.unit.test_publish_feedback_loop tests.unit.test_provider_hard_stop_proof tests.integration.test_novel_os_12_chapter_industrial_pressure` | 13 tests OK |
| `NOVEL_FORGE_MODEL_PROVIDER=mock python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_loop_kernel tests.unit.test_permission_center tests.unit.test_agent_runtime_profiles` | 51 tests OK |
| `python3 -m unittest tests.unit.test_agent_workspace_execution_migration tests.unit.test_execution_backend_conformance`（Agent workspace 定向用例） | 7 tests OK |
| `.venv/bin/python -m unittest tests.architecture.test_production_execution_security_boundaries tests.architecture.test_production_execution_gateway_boundaries tests.architecture.test_production_execution_plane_boundaries tests.unit.test_external_action_execution_migration tests.unit.test_production_execution_gateway tests.unit.test_production_execution_routing tests.unit.test_production_execution_contracts tests.unit.test_production_execution_capabilities tests.unit.test_production_execution_inventory tests.unit.test_execution_backend_conformance tests.unit.test_agent_workspace_execution_migration tests.unit.test_production_execution_bundles` | 93 tests OK |
| `npm --prefix web/admin test` | 10 pass, 1 Playwright smoke skipped |
| `npm --prefix web/admin run build` | OK, 67 routes generated |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_registry tests.unit.test_agent_registry_scheduler_integration tests.unit.test_audit_log tests.unit.test_pgvector_source_isolation tests.unit.test_clickhouse_analytics tests.unit.test_evaluation_center_general tests.integration.test_novel_os_governance_loop tests.unit.test_schemas tests.unit.test_product_api_routes` | 32 tests OK |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_model_extraction_schema tests.unit.test_mkaos_model_extraction_sanitizer tests.unit.test_mkaos_model_extraction_confidence tests.unit.test_mkaos_model_extraction_prompt_registry tests.unit.test_mkaos_model_extraction_review_queue tests.unit.test_mkaos_production_gate_runner tests.unit.test_mkaos_lineage_index tests.unit.test_mkaos_asset_impact_analysis tests.unit.test_mkaos_feedback_attribution` | 17 tests OK |
| `PYTHONPATH=src python3 -m unittest tests.integration.test_mkaos_model_extraction_to_knowledge_card tests.integration.test_mkaos_gate_context_builder_auto tests.integration.test_mkaos_gate_publish_release_package_auto tests.integration.test_mkaos_source_to_draft_lineage tests.integration.test_mkaos_feedback_to_weight_governance tests.integration.test_mkaos_novel_os_full_chain` | 6 tests OK |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_extraction_quality tests.integration.test_mkaos_ingestion_knowledge_pack_gate tests.integration.test_pipeline` | 6 tests OK, 57.531s |
| `npm --prefix web/admin test` | 10 pass, 1 optional Playwright smoke skipped |
| `npm --prefix web/admin run build` | OK, 67 routes generated |

## 2. 工程能力分层

### 2.1 P0 已完成能力

| 能力 | 说明 | 主要证据 |
| -- | -- | -- |
| MKAOS 知识资产治理 | Source Document / Source Chunk / Knowledge Card / Usage Binding / Rule Card / Template Card / Knowledge Pack / Usage / Feedback | `src/novel_forge/modules/mkaos/service.py`, `web/admin/app/features/mkaos/MkaosConsolePage.tsx` |
| RAG 与 source isolation | runtime assets 不污染 generation RAG；`source_chunk.raw_text` 不进入 prose、prompt preview、chapter prompt、publish package、recap context | `tests/unit/test_mkaos_isolation.py`, `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` |
| OS Envelope | MKAOS mutation/query/convert、Loop、Publish Gate、Release Package 进入 envelope；production 缺 envelope fail closed | `src/novel_forge/modules/os_envelope/service.py`, `tests/unit/test_mkaos_os_envelope.py` |
| Context Builder | Outline / ChapterOutline / Prose / Review 统一通过 Context Builder 获取上下文；MKAOS Pack 由 Context Builder 注入 | `src/novel_forge/modules/context_builder/service.py`, `tests/unit/test_context_builder_mkaos_flow.py` |
| ReviewIssue 阻断系统 | MKAOS、Canon、Review issue 统一结构化，并阻断 canonical/final draft 与 release package | `src/novel_forge/modules/review_issue/service.py`, `tests/unit/test_review_issue.py` |
| Loop Engineering Kernel | LoopRun / LoopStep / LoopCheckpoint / LoopReport，支持 quality、blocking、budget、provider timeout、human stop | `src/novel_forge/modules/loop_kernel/service.py`, `tests/unit/test_loop_kernel.py` |
| Longform Recap Agent | 12 章触发，读取 ContextBundle / ReviewIssue / MKAOS，写回 Canon / Character / Arc / Foreshadowing / RevisionTask / MKAOS feedback | `src/novel_forge/modules/longform_recap/service.py`, `tests/unit/test_longform_recap_agent.py` |
| Agent Center | AgentTask / AgentRun / AgentHandoff / capability registry / center snapshot / issue dispatch | `src/novel_forge/modules/agent_scheduler/service.py`, `src/novel_forge/api/routers/agents.py` |
| UI 可编辑控制台 | Canon、Character、Arc、Foreshadowing、ReviewIssue、Longform Recap、LoopRun、Agent Center、Publish Gate、Feedback Console | `web/admin/app/*/page.tsx`, `web/admin/tests/feature-architecture.test.mjs` |
| Publish / Feedback 闭环 | Publish Gate、Release Package、ReviewIssue/MKAOS risk 阻断、Reader Feedback、Backflow Plan、MKAOS weight update | `src/novel_forge/modules/audit/service.py`, `src/novel_forge/modules/feedback/service.py`, `tests/unit/test_publish_feedback_loop.py` |
| Platform Strategy OS | 起点/番茄/飞卢/晋江/知乎盐选/微信读书出版向平台策略包、节奏规则、开篇/章节门禁、留存风险、发布适配、反馈回流 | `src/novel_forge/modules/platform_strategy/service.py`, `tests/unit/test_platform_strategy_os.py` |
| Editor-in-Chief Console | 聚合 Canon / Character / Arc / Foreshadowing / ReviewIssue / Recap / Loop / Agent / Publish Gate，给出可继续生产、暂停修复或可发布的总编判断 | `src/novel_forge/modules/editor_chief/service.py`, `web/admin/app/features/os/EditorChiefConsolePage.tsx`, `tests/unit/test_editor_chief_console.py` |
| Provider hard-stop | token/cost/timeout/cancel proof，hard-stop 后不 silent retry/fallback | `src/novel_forge/modules/runtime_policy/service.py`, `tests/unit/test_provider_hard_stop_proof.py` |
| 12 章压力测试 | MKAOS、Context Builder、ReviewIssue、LoopRun、Longform Recap、Publish Gate、Release Package 同链路证明 | `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` |

### 2.2 P1/P2 未完成深化

| 领域 | 当前缺口 | 优先级 |
| -- | -- | -- |
| Canon Graph | Canon / Character / Arc / Foreshadowing / WorldRule 仍需完整图谱级语义推理 | P1 |
| Agent Center | Workspace 不确定执行已具备 PEP 候选合同；真实 Agent runner、operation coverage、硬停止 UI、rollback depth 仍不足 | P1 |
| Loop Kernel | review -> revision -> re-review 的模型步骤拒绝直连 Adapter 并接收 ExecutionPort；确定性提交仍在 Loop/领域，非主链 operation 分批迁移 | P2 |
| UI 领域表单 | 当前是最小可编辑控制台，专用表单、批量治理、血缘图仍不足 | P1/P2 |
| Provider fallback | hard-stop 后 fail closed 已证明，但显式 fallback 策略尚未治理化 | P1 |
| Publishing adapters | Platform Strategy OS 已有平台发布适配契约；外部真实平台 API 和回执 schema 仍需深化 | P2 |
| Feedback metrics | Platform retention/backflow 已建 first slice；真实平台指标导入、评论热度和回执仍需深化 | P2 |
| 长链压力 | 12 章已证明，50/100 章仍应保持 opt-in 慢测试 | P2 |
| Permission Center | 本轮明确不实现；现有 ToolPermissionPolicy 保持兼容 | 暂不做 |

## 3. 详细功能文档

### 3.1 项目与工作区管理

功能：

- 创建项目；
- 查看项目列表和 operating dashboard；
- 暂停、恢复、归档、复制、删除项目；
- 项目级资产列表；
- project scope audit。

API：

- `GET /product/projects`
- `GET /product/projects/operating-dashboard`
- `POST /product/projects`
- `PATCH /product/projects/{project_id}/config`
- `POST /product/projects/{project_id}/duplicate`
- `POST /product/projects/{project_id}/archive`
- `POST /product/projects/{project_id}/pause`
- `POST /product/projects/{project_id}/restore`
- `DELETE /product/projects/{project_id}`
- `GET /product/projects/{project_id}/assets`
- `GET /product/projects/audit/scope`
- `POST /product/projects/audit/scope`

UI：

- `/projects`
- `/os`
- `/health`

核心文件：

- `src/novel_forge/api/routers/projects.py`
- `src/novel_forge/modules/workspace/service.py`
- `src/novel_forge/modules/project_operations/service.py`

### 3.2 MKAOS 知识资产操作系统

功能：

- 来源文档导入；
- 来源切块；
- 知识卡创建/编辑；
- 用途绑定；
- Rule Card / Template Card；
- Knowledge Pack 构建；
- Query / Convert；
- Multidisciplinary Knowledge Graph；
- Effect Feedback Learning Snapshot；
- Artifact validation；
- Canon conflict check；
- Usage event；
- Review feedback；
- weight update；
- risk knowledge 列表；
- P0 acceptance fixture。

支持 flow：

- `outline`
- `chapter_outline`
- `prose`
- `review`
- `revision`
- `recap`
- `publish`
- `feedback`

核心 API：

- `GET /product/mkaos/overview`
- `POST /product/mkaos/query/knowledge`
- `POST /product/mkaos/knowledge-graph/build`
- `POST /product/mkaos/knowledge-graph/query`
- `POST /product/mkaos/knowledge-graph/paths`
- `POST /product/mkaos/learning/effects`
- `POST /product/mkaos/convert/assets`
- `POST /product/mkaos/convert/rules`
- `POST /product/mkaos/sources`
- `GET /product/mkaos/sources`
- `POST /product/mkaos/knowledge`
- `PATCH /product/mkaos/knowledge/{knowledge_id}`
- `POST /product/mkaos/knowledge/{knowledge_id}/usage-bindings`
- `GET /product/mkaos/usage-bindings`
- `POST /product/mkaos/rules`
- `POST /product/mkaos/templates`
- `POST /product/mkaos/packs/build`
- `GET /product/mkaos/packs/{pack_id}/prompt-preview`
- `POST /product/mkaos/validate/artifact`
- `POST /product/mkaos/validate/canon-conflict`
- `POST /product/mkaos/model-extraction/jobs`
- `GET /product/mkaos/model-extraction/review-queue`
- `POST /product/mkaos/production-gate/run`
- `GET /product/mkaos/production-gate/coverage`
- `POST /product/mkaos/lineage/build-index`
- `POST /product/mkaos/lineage/query-path`
- `POST /product/mkaos/lineage/diff`
- `POST /product/mkaos/lineage/export`
- `POST /product/mkaos/lineage/weight-governance`
- `POST /product/mkaos/usage-events`
- `POST /product/mkaos/feedback/review`
- `POST /product/mkaos/feedback/apply-weight-update`
- `GET /product/mkaos/risks`
- `POST /product/mkaos/acceptance/minimal`

UI：

- `/mkaos`
- `/mkaos/model-extraction/*`
- `/mkaos/production-gate/*`
- `/mkaos/knowledge-graph`
- `/mkaos/lineage`
- `/mkaos/impact`
- `/mkaos/feedback-attribution`

核心文件：

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/modules/mkaos_model_extraction/service.py`
- `src/novel_forge/modules/mkaos_production_gate/service.py`
- `src/novel_forge/modules/mkaos_lineage/service.py`
- `src/novel_forge/api/routers/mkaos.py`
- `web/admin/app/features/mkaos/MkaosConsolePage.tsx`
- `web/admin/app/features/mkaos/MkaosIngestionPages.tsx`

测试：

- `tests/unit/test_mkaos.py`
- `tests/unit/test_mkaos_isolation.py`
- `tests/unit/test_mkaos_os_envelope.py`
- `tests/unit/test_mkaos_selector_canon.py`
- `tests/unit/test_mkaos_knowledge_graph_learning.py`
- `tests/unit/test_mkaos_model_extraction_schema.py`
- `tests/unit/test_mkaos_production_gate_coverage.py`
- `tests/unit/test_mkaos_lineage_diff_export.py`
- `tests/unit/test_mkaos_weight_governance_apply_policy.py`

### 3.3 Context Builder 与 RAG 隔离

功能：

- Context build plan；
- Context bundle；
- MKAOS pack 注入；
- token budget；
- source isolation；
- RAG candidate selection；
- context diff；
- flow context：outline / chapter_outline / prose / review / revision / recap / publish / feedback。

API：

- `GET /product/context/assets`
- `POST /product/context/build-plan`
- `POST /product/context/bundle`
- `POST /product/context/diff`

UI：

- `/context`

核心文件：

- `src/novel_forge/modules/context_builder/service.py`
- `src/novel_forge/storage/rag_context.py`
- `src/novel_forge/api/routers/context_builder.py`

测试：

- `tests/unit/test_context_builder_mkaos_flow.py`
- `tests/unit/test_mkaos_isolation.py`

### 3.4 创作生产主链

功能：

- Topic / material / worldbuilding / character / outline / chapter plan / draft / review / revision；
- Draft 生成；
- Draft 保存；
- Draft diff；
- Draft export；
- 章节生产 run；
- pause / cancel / resume / recover；
- 下游 invalidation；
- version registry。

API：

- `GET /product/drafts`
- `POST /product/drafts/generate`
- `POST /product/drafts/save`
- `GET /product/drafts/diff`
- `POST /product/drafts/export`
- `GET /product/production/chapter-runs`
- `POST /product/production/chapter-run/start`
- `POST /product/production/chapter-run/resume`
- `POST /product/production/chapter-run/pause`
- `POST /product/production/chapter-run/cancel`
- `POST /product/production/chapter-run/recover`
- `POST /product/production/invalidate-downstream`
- `POST /product/production/outline-version`
- `POST /product/production/chapter-plan-version`
- `POST /product/production/draft-version`
- `POST /product/production/generation-run`

UI：

- `/production`
- `/editor`
- `/manuscript`
- `/review`
- `/review-rework`

核心文件：

- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`
- `src/novel_forge/modules/drafting/service.py`
- `src/novel_forge/modules/review/service.py`
- `src/novel_forge/modules/revision/service.py`
- `src/novel_forge/modules/editor/service.py`
- `src/novel_forge/modules/production_chain/service.py`

测试：

- `tests.integration.test_pipeline`
- `tests/unit/test_context_and_production_chain.py`
- `tests/unit/test_module_services.py`

### 3.5 ReviewIssue 阻断系统

功能：

- Review/MKAOS/Canon issue 统一为 `review_issue`；
- severity；
- blocking；
- status lifecycle；
- ReviewIssue -> RevisionTask candidate；
- 阻断 final/canonical draft；
- 阻断 release package；
- 作为 Longform Recap 输入；
- Agent Center 可见并可派发任务。

API：

- `GET /product/review-issues`
- `POST /product/review-issues`
- `PATCH /product/review-issues/status`
- `POST /product/revisions/plan`
- `POST /product/revisions/apply`
- `POST /product/revisions/rework-loop`

UI：

- `/review-issues`
- `/review-rework`

核心文件：

- `src/novel_forge/modules/review_issue/service.py`
- `src/novel_forge/api/routers/reviews.py`

测试：

- `tests/unit/test_review_issue.py`

### 3.6 Loop Engineering Kernel

功能：

- LoopRun；
- LoopStep；
- LoopCheckpoint；
- LoopReport；
- loop state；
- budget；
- stop condition；
- chapter review loop；
- outline revision loop；
- longform recap loop；
- cancel。

API：

- `GET /product/loops`
- `GET /product/loops/{loop_ref}`
- `POST /product/loops/run`
- `POST /product/loops/cancel`

UI：

- `/loop-runs`

核心文件：

- `src/novel_forge/modules/loop_kernel/service.py`
- `src/novel_forge/api/routers/loops.py`

测试：

- `tests/unit/test_loop_kernel.py`

### 3.7 Longform Stability 与 Longform Recap Agent

功能：

- 长篇稳定性 dashboard；
- 长篇状态抽取；
- Canon / Arc / Foreshadowing 控制资产；
- Longform acceptance；
- extraction calibration；
- 10 章/卷结束/blocking issue/重大设定变更触发 recap；
- recap 写回 Canon Patch、Character State、Arc Plan、Foreshadowing Graph、ReviewIssue、RevisionTask、MKAOS feedback。

API：

- `GET /product/longform-stability/dashboard`
- `POST /product/longform-stability/extract`
- `POST /product/longform-stability/acceptance`
- `POST /product/longform-stability/control-asset`
- `POST /product/longform-stability/calibrate`
- `GET /product/longform-recap/reports`
- `POST /product/longform-recap/trigger`
- `POST /product/longform-recap/run`

UI：

- `/longform-stability`
- `/longform-recap`

核心文件：

- `src/novel_forge/modules/longform_stability/service.py`
- `src/novel_forge/modules/longform_recap/service.py`

测试：

- `tests/unit/test_longform_stability.py`
- `tests/unit/test_longform_recap_agent.py`
- `tests/integration/test_novel_os_12_chapter_industrial_pressure.py`

### 3.8 Agent Center

功能：

- Agent contract；
- Agent run；
- Agent event；
- Agent task；
- Agent handoff；
- dispatch queue；
- scheduler tick；
- recover；
- issue -> revision task/agent task；
- Agent Center snapshot；
- operation contracts。

API：

- `GET /product/agents/runs`
- `GET /product/agents/events`
- `POST /product/agents/contracts`
- `POST /product/agents/runs`
- `PATCH /product/agents/runs/status`
- `POST /product/agents/events`
- `GET /product/agents/scheduler/status`
- `GET /product/agents/scheduler/queue`
- `GET /product/agents/operation-contracts`
- `GET /product/agents/center`
- `POST /product/agents/tasks`
- `POST /product/agents/tasks/from-issue`
- `POST /product/agents/dispatch`
- `POST /product/agents/recover`
- `POST /product/agents/scheduler/tick`

UI：

- `/agent-center`
- `/agent-dispatch`

核心文件：

- `src/novel_forge/modules/agent_scheduler/service.py`
- `src/novel_forge/modules/agent_runs/service.py`
- `src/novel_forge/api/routers/agents.py`

测试：

- `tests/unit/test_agent_scheduler.py`

### 3.9 Novel KG / Continuity / Canon

功能：

- Novel KG graph；
- semantic extraction；
- identity resolution；
- conflicts；
- impact；
- paths；
- continuity graph；
- canon snapshot；
- chapter continuity report；
- canon patch apply。

API：

- `GET /product/novel-kg/graph`
- `POST /product/novel-kg/snapshot`
- `GET /product/novel-kg/query`
- `GET /product/novel-kg/paths`
- `GET /product/novel-kg/impact`
- `GET /product/novel-kg/conflicts`
- `POST /product/novel-kg/gate`
- `POST /product/novel-kg/semantic-extraction`
- `POST /product/novel-kg/identity-resolution`
- `POST /product/novel-kg/identity-resolution/adjudicate`
- `POST /product/novel-kg/refresh`
- `GET /product/continuity/graph`
- `POST /product/continuity/graph-snapshot`
- `POST /product/continuity/canon-snapshot`
- `POST /product/continuity/chapter-report`
- `POST /product/continuity/canon-patch`
- `POST /product/continuity/canon-patch/apply`

UI：

- `/kg`
- `/novel-kg`
- `/canon-console`
- `/character-console`
- `/arc-console`
- `/foreshadowing-console`

核心文件：

- `src/novel_forge/modules/novel_kg/service.py`
- `src/novel_forge/modules/continuity_graph/service.py`
- `src/novel_forge/api/routers/novel_kg.py`
- `src/novel_forge/api/routers/continuity.py`

当前限制：

- 具备结构化资产和检查入口，但完整 Canon Graph 语义推理仍是 P1。

### 3.10 Publishing / Feedback

功能：

- chapter audit；
- originality report；
- publish gate；
- release package；
- publishing plan；
- publishing log；
- adapter release；
- feedback import；
- reader sentiment report；
- operational snapshot；
- feedback insight；
- strategy apply；
- backflow plan；
- backflow apply；
- publish feedback loop；
- feedback -> MKAOS weight update。

API：

- `POST /product/audits/chapter`
- `POST /product/audits/originality`
- `POST /product/publishing/gate`
- `POST /product/publishing/release-package`
- `POST /product/publishing/plan`
- `POST /product/publishing/log`
- `POST /product/publishing/adapter-release`
- `GET /product/feedback/assets`
- `POST /product/feedback/import-batch`
- `POST /product/feedback/sentiment-report`
- `POST /product/feedback/operational-snapshot`
- `POST /product/feedback/insight`
- `POST /product/feedback/apply-strategy`
- `POST /product/feedback/backflow-plan`
- `POST /product/feedback/backflow-apply`
- `POST /product/feedback/publish-loop`

UI：

- `/publish-gate`
- `/quality`
- `/feedback`
- `/feedback-console`

核心文件：

- `src/novel_forge/modules/audit/service.py`
- `src/novel_forge/modules/publishing/service.py`
- `src/novel_forge/modules/feedback/service.py`
- `src/novel_forge/modules/feedback_backflow/service.py`

测试：

- `tests/unit/test_publish_feedback_loop.py`
- `tests/unit/test_publishing_center.py`

### 3.11 Platform Strategy OS

功能：

- 默认平台策略库：起点、番茄、飞卢、晋江、知乎盐选、微信读书/出版向；
- `PlatformProfile`；
- `PlatformRhythmRule`；
- `PlatformOpeningGate`；
- `PlatformChapterGate`；
- `PlatformRetentionRisk`；
- `PlatformPublishAdapter`；
- `PlatformFeedbackBackflow`；
- `PlatformStrategyPack`；
- 同题材多平台策略包构建；
- 开篇门禁；
- 章节门禁；
- 平台留存风险评估；
- 发布适配契约；
- 平台反馈回流映射；
- planning context 注入；
- Outline / ChapterPlan fallback 读取平台节奏、必需 beat、风险控制和字数预算。

核心 API：

- `GET /product/platform-strategy/assets`
- `POST /product/platform-strategy/defaults`
- `POST /product/platform-strategy/pack`
- `POST /product/platform-strategy/opening-gate`
- `POST /product/platform-strategy/chapter-gate`
- `POST /product/platform-strategy/retention-risk`
- `POST /product/platform-strategy/publish-adapter`
- `POST /product/platform-strategy/feedback-backflow`

核心文件：

- `src/novel_forge/modules/platform_strategy/service.py`
- `src/novel_forge/api/routers/platform_strategy.py`
- `src/novel_forge/modules/planning_context.py`
- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`

测试：

- `tests/unit/test_platform_strategy_os.py`
- `tests/unit/test_product_api_routes.py`
- `tests/unit/test_context_and_production_chain.py`

### 3.12 Editor-in-Chief Console

功能：

- 全书健康度、风险等级、可继续生产 / 暂停修复 / 可发布判断；
- 主线 Arc Progress 与 Canon Graph 偏移报警；
- Character Drift、人物负债、动机/状态风险聚合；
- Foreshadowing Graph、未回收伏笔、过期伏笔、失效伏笔聚合；
- 最近 10 章 Pattern Similarity、Motif Budget、Reader Fatigue 聚合；
- Next-10-Chapter Strategy；
- Blocking ReviewIssue + RevisionTask 必修队列；
- Publish Gate + Platform Fit 发布判断；
- 一屏跳转 Canon、Character、Arc、Foreshadowing、ReviewIssue、Longform Recap、LoopRun、Agent Center、Publish Gate。

核心 API：

- `GET /product/editor-chief/snapshot`

UI：

- `/editor-chief`

核心文件：

- `src/novel_forge/modules/editor_chief/service.py`
- `src/novel_forge/api/routers/editor_chief.py`
- `web/admin/app/features/os/EditorChiefConsolePage.tsx`

测试：

- `tests/unit/test_editor_chief_console.py`
- `tests/unit/test_product_api_routes.py`
- `web/admin/tests/feature-architecture.test.mjs`

### 3.13 Runtime / Provider / Cost / Rollback

功能：

- runtime policy status；
- enforcement report；
- legacy entrypoint audit；
- surface coverage；
- provider hard-stop evidence；
- policy check；
- trace timeline；
- cost ledger；
- cost dashboard；
- cost snapshot；
- rollback verify / preview / apply / coordinate。

API：

- `GET /product/runtime/policy/status`
- `GET /product/runtime/policy/enforcement-report`
- `GET /product/runtime/policy/legacy-entrypoint-audit`
- `GET /product/runtime/policy/surface-coverage`
- `GET /product/runtime/provider-hard-stop-evidence`
- `POST /product/runtime/policy/check`
- `GET /product/runtime/trace-timeline`
- `GET /product/runtime/cost-ledger`
- `GET /product/runtime/cost-dashboard`
- `POST /product/runtime/cost-snapshot`
- `POST /product/runtime/rollback/verify`
- `POST /product/runtime/rollback/preview`
- `POST /product/runtime/rollback/apply`
- `POST /product/runtime/rollback/coordinate`

UI：

- `/trace-timeline`
- `/cost-dashboard`
- `/control`
- `/invalidation`
- `/os`

核心文件：

- `src/novel_forge/modules/runtime_policy/service.py`
- `src/novel_forge/modules/runtime_ledger/service.py`
- `src/novel_forge/modules/model_router/service.py`
- `src/novel_forge/model_adapters/runtime.py`

测试：

- `tests/unit/test_provider_runtime_guard.py`
- `tests/unit/test_runtime_policy.py`
- `tests/unit/test_provider_hard_stop_proof.py`

### 3.12 Model Router / Prompt Registry / Tools / State / Memory

功能：

- model route；
- model route resolution；
- model gateway call；
- prompt template / version / release / binding / resolve；
- internal tools；
- MCP server registry；
- tool permission policy；
- tool invocation；
- state event/snapshot/replay/conflict；
- agent messages；
- memory record / select / retrieve；
- pgvector schema plan / migrate / capabilities / hybrid retrieval。

API group：

- `/product/os/model-router/*`
- `/product/os/prompts/*`
- `/product/os/tools/*`
- `/product/os/state/*`
- `/product/os/messages/*`
- `/product/os/memory/*`
- `/product/os/retrieval/*`

UI：

- `/evaluation`
- `/settings`
- `/os`

核心文件：

- `src/novel_forge/modules/model_router/service.py`
- `src/novel_forge/modules/prompt_registry/service.py`
- `src/novel_forge/modules/tool_gateway/service.py`
- `src/novel_forge/modules/state_bus/service.py`
- `src/novel_forge/modules/agent_messages/service.py`
- `src/novel_forge/modules/long_memory/service.py`
- `src/novel_forge/modules/pgvector_store/service.py`

### 3.13 Analysis / Decomposition / Asset Library

功能：

- source ingestion / cleaning；
- deconstruction；
- analysis run；
- analysis convert；
- handoff；
- creative asset libraries；
- style decompose/review/trend；
- quality score；
- asset detail/content/typed edit；
- asset versions；
- asset graph；
- asset collections。

API：

- `POST /product/batch/deconstruct`
- `POST /product/analysis/run`
- `POST /product/analysis/convert`
- `POST /product/analysis/handoff`
- `GET /product/libraries/creative`
- `POST /product/creative-assets`
- `POST /product/styles/decompose`
- `POST /product/styles/review`
- `GET /product/styles/trend`
- `POST /product/quality/score`
- `GET /product/assets/detail`
- `PATCH /product/assets/detail`
- `PATCH /product/assets/content`
- `PATCH /product/assets/typed`
- `GET /product/assets/versions`
- `GET /product/assets/graph`
- `POST /product/assets/collections`

UI：

- `/analysis`
- `/assets`
- `/batch`
- `/templates`

核心文件：

- `src/novel_forge/modules/analysis/service.py`
- `src/novel_forge/modules/decomposition/service.py`
- `src/novel_forge/modules/creative_assets/service.py`
- `src/novel_forge/api/routers/analysis.py`
- `src/novel_forge/api/routers/assets.py`
- `src/novel_forge/api/routers/libraries.py`

## 4. Web 控制台路由总览

当前 admin build 生成 45 个 route。核心功能路由：

| 路由 | 功能 |
| -- | -- |
| `/` | 本地小说工厂入口 |
| `/projects` | 项目管理 |
| `/editor-chief` | 总编控制台 |
| `/mkaos` | MKAOS 管理台 |
| `/context` | Context Builder |
| `/production` | 生产链 |
| `/editor` | 编辑器 |
| `/review` | 审稿 |
| `/review-issues` | ReviewIssue 控制台 |
| `/review-rework` | 审稿返工 |
| `/loop-runs` | LoopRun 监控 |
| `/longform-stability` | 长篇稳定性 |
| `/longform-recap` | 长篇复盘 |
| `/agent-center` | Agent Center |
| `/agent-dispatch` | Agent Dispatch |
| `/publish-gate` | 发布门禁 |
| `/feedback` | 读者反馈中心 |
| `/feedback-console` | Feedback Console |
| `/canon-console` | Canon 控制台 |
| `/character-console` | Character 控制台 |
| `/arc-console` | Arc 控制台 |
| `/foreshadowing-console` | Foreshadowing 控制台 |
| `/kg` | KG 页面 |
| `/novel-kg` | Novel KG |
| `/trace-timeline` | Trace Timeline |
| `/cost-dashboard` | Cost Dashboard |
| `/control` | 生产控制 |
| `/quality` | 质量与发布 |
| `/evaluation` | 模型评测 |
| `/settings` | 设置中心 |
| `/health` | 健康检查 |

## 5. 当前权威文档索引

### 5.1 最终状态与路线

- `docs/reports/v6-final-current-state.md`
- `docs/reports/v6-final-implementation-matrix.md`
- `docs/reports/v6-final-test-summary.md`
- `docs/reports/v6-industrial-novel-os-gap-analysis.md`
- `docs/reports/v6-next-roadmap-p1-p2.md`

### 5.2 Phase 报告

- `docs/reports/phase-0-post-mkaos-baseline.md`
- `docs/reports/phase-1-rag-source-leakage-report.md`
- `docs/reports/phase-2-os-envelope-mkaos-report.md`
- `docs/reports/phase-3-mkaos-selector-canon-report.md`
- `docs/reports/phase-4-context-builder-report.md`
- `docs/reports/phase-5-review-issue-report.md`
- `docs/reports/phase-6-loop-kernel-report.md`
- `docs/reports/phase-7-longform-recap-agent-report.md`
- `docs/reports/phase-8-agent-center-report.md`
- `docs/reports/phase-9-ui-console-report.md`
- `docs/reports/phase-10-publish-feedback-report.md`
- `docs/reports/phase-11-pressure-test-report.md`

### 5.3 核心设计文档

- `docs/design/os-envelope-design.md`
- `docs/design/mkaos-selector-and-canon-conflict-design.md`
- `docs/design/context-builder-design.md`
- `docs/design/review-issue-system-design.md`
- `docs/design/loop-engineering-kernel-design.md`
- `docs/design/longform-recap-agent-design.md`
- `docs/design/agent-center-design.md`
- `docs/design/novel-os-ui-console-design.md`
- `docs/design/publish-feedback-loop-design.md`
- `docs/design/novel-os-v6-industrialization-design.md`

### 5.4 证明类报告

- `docs/reports/rag-isolation-proof.md`
- `docs/reports/os-envelope-enforcement-audit.md`
- `docs/reports/mkaos-feedback-weight-proof.md`
- `docs/reports/context-builder-migration-proof.md`
- `docs/reports/review-issue-blocking-proof.md`
- `docs/reports/loop-stop-and-budget-proof.md`
- `docs/reports/longform-recap-writeback-proof.md`
- `docs/reports/provider-hard-stop-proof.md`
- `docs/reports/v6-test-summary.md`

### 5.5 MKAOS 审计基线

- `docs/reports/mkaos-docs-index.md`
- `docs/reports/mkaos-docs-vs-implementation-audit.md`
- `docs/reports/mkaos-gap-and-risk-register.md`
- `docs/reports/mkaos-remediation-plan.md`

## 6. 建议下一步

建议按 P1 优先级继续：

1. Canon Graph 深化：统一 Canon / Character / Arc / Foreshadowing / WorldRule 查询与冲突检测。
2. Agent Center operation coverage：把更多生产操作纳入 AgentTask / AgentRun。
3. Loop Kernel 主链迁移：把 review -> revision -> re-review -> publish gate 变成标准 LoopRun。
4. Provider fallback policy：保持 hard-stop fail closed，增加显式 fallback 审批和成本预测。
5. UI 领域编辑器：把 JSON asset 控制台升级为 Canon/Character/Arc/Issue 专用表单和批量治理工具。
