# Current Engineering Progress And Feature Documentation

日期：2026-07-03

## 1. 当前工程进度结论

当前分支：`feat/v6-post-mkaos-industrialization`

当前状态：

- Post-MKAOS Novel OS v6 工业化 Phase 0-12 已完成本地实现、测试、文档和分阶段提交。
- 分支已推送到 GitHub：`origin/feat/v6-post-mkaos-industrialization`。
- Novel OS v6 当前工业化完成度：**86/100**。
- MKAOS P0 已从“有条件完成”推进为：**完成**。
- 当前剩余工作主要是 P1/P2 深化，不是 P0 blocker。

最终验证：

| 测试命令 | 当前结果 |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | 297 tests OK, skipped=1 |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK |
| `python3 -m unittest tests.unit.test_longform_recap_agent tests.unit.test_loop_kernel tests.unit.test_publish_feedback_loop tests.unit.test_provider_hard_stop_proof tests.integration.test_novel_os_12_chapter_industrial_pressure` | 13 tests OK |
| `npm --prefix web/admin test` | 8 pass, 1 Playwright smoke skipped |
| `npm --prefix web/admin run build` | OK, 44 routes generated |

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
| Provider hard-stop | token/cost/timeout/cancel proof，hard-stop 后不 silent retry/fallback | `src/novel_forge/modules/runtime_policy/service.py`, `tests/unit/test_provider_hard_stop_proof.py` |
| 12 章压力测试 | MKAOS、Context Builder、ReviewIssue、LoopRun、Longform Recap、Publish Gate、Release Package 同链路证明 | `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` |

### 2.2 P1/P2 未完成深化

| 领域 | 当前缺口 | 优先级 |
| -- | -- | -- |
| Canon Graph | Canon / Character / Arc / Foreshadowing / WorldRule 仍需完整图谱级语义推理 | P1 |
| Agent Center | operation coverage、硬停止 UI、rollback depth 仍不足 | P1 |
| Loop Kernel | review -> revision -> re-review -> publish gate 主链已默认进入 LoopRun；非主链 operation 分批迁移 | P2 |
| UI 领域表单 | 当前是最小可编辑控制台，专用表单、批量治理、血缘图仍不足 | P1/P2 |
| Provider fallback | hard-stop 后 fail closed 已证明，但显式 fallback 策略尚未治理化 | P1 |
| Publishing adapters | 外部平台发布 adapter 仍是受限边界，平台回执 schema 需深化 | P2 |
| Feedback metrics | reader feedback 已闭环，平台指标/留存/评论 schema 仍较薄 | P2 |
| 长链压力 | 12 章已证明，50/100 章仍应保持 opt-in 慢测试 | P2 |

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
- `POST /product/mkaos/usage-events`
- `POST /product/mkaos/feedback/review`
- `POST /product/mkaos/feedback/apply-weight-update`
- `GET /product/mkaos/risks`
- `POST /product/mkaos/acceptance/minimal`

UI：

- `/mkaos`

核心文件：

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/api/routers/mkaos.py`
- `web/admin/app/features/mkaos/MkaosConsolePage.tsx`

测试：

- `tests/unit/test_mkaos.py`
- `tests/unit/test_mkaos_isolation.py`
- `tests/unit/test_mkaos_os_envelope.py`
- `tests/unit/test_mkaos_selector_canon.py`
- `tests/unit/test_mkaos_knowledge_graph_learning.py`

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

### 3.11 Runtime / Provider / Cost / Rollback

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

当前 admin build 生成 44 个 route。核心功能路由：

| 路由 | 功能 |
| -- | -- |
| `/` | 本地小说工厂入口 |
| `/projects` | 项目管理 |
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
