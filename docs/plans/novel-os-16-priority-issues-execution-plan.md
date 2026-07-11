# Novel OS 16 项优先问题实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 按真实依赖修复16项优先问题，先恢复可信基线，再逐阶段建立可验证的精品长篇最小生产闭环。

**Architecture:** 保留模块化单体和现有资产/服务，使用兼容适配和垂直切片逐步收敛。Phase 0只修复回归、项目隔离和证据语义；后续依次统一执行内核、长篇状态与存储、质量与真实Provider、发布自治UI、三书与生产硬化。

**Tech Stack:** Python 3.11+、stdlib `unittest`、FastAPI、版本化JSON LocalStorage、可选PostgreSQL/Redis/Qdrant/MinIO、Next.js/TypeScript、Node test runner。

## Global Constraints

- 代码和测试是事实来源；历史报告不构成完成证据。
- 不关闭 Source、Context、Approval、ReviewIssue 或质量门禁来制造绿色。
- 不让 fixture/demo 内容进入生产路径。
- 不创建第五套执行状态，不进行全量重写或微服务化。
- 每个工作包必须有正常、失败、边界和绕过测试。
- 当前工作区已有未提交改动；编辑前必须检查并保留不相关用户修改。
- 真实Provider、平台外部动作和破坏性操作需要独立授权与预算。

---

## 总体依赖路线

| Phase | Issues | 进入条件 | 完成证据 |
|---|---|---|---|
| 0 可信基线 | 1 | 当前代码事实 | 两次确定性全量绿色、workspace validate绿色 |
| 1 生产执行内核 | 2-7 | Phase 0绿色 | Envelope覆盖、唯一Kernel、fixture隔离、Context覆盖、质量分离、性能预算 |
| 2 长篇状态和存储 | 8、15 | Phase 1单章Kernel通过 | typed events/replay、Snapshot、authority、transactional outbox故障注入 |
| 3 质量与真实内容 | 9、11、10 | Phase 2状态可重建 | Golden/Human、Approval verifier、真实10/30章报告 |
| 4 发布自治治理 | 12-14 | 单书30章闭环通过 | Adapter contract、受限Planner、治理E2E |
| 5 规模化硬化 | 16 | 单书闭环和受限自治通过 | 三书隔离、分层CI、安全、restore rehearsal |

Phase 1-5在进入各阶段前重新读取当前代码，并为该阶段追加同等精度的任务；不得用本计划中的高层路线替代文件级设计。

---

## Phase 0：可信工程基线

### Task 0.1：固定基线证据和失败分类

**Files:**
- Modify: `docs/reports/novel-os-priority-issues-rebaseline.md`
- Create: `docs/reports/novel-os-16-priority-issues-progress.md`
- Modify: `docs/quality/regression-tests.md`

**Interfaces:**
- Consumes: 当前分支、工作区状态、Makefile命令和全量测试输出。
- Produces: `baseline-v1`命令矩阵及四类失败根因，不改变业务行为。

- [ ] **Step 1: 记录当前精确命令和结果**

在进度报告写入：Python 779/7F/35E/2S、workspace 3 unscoped、Web 11 pass/1 skip、lint/type/skills/diff通过。

- [ ] **Step 2: 为四个共同根因建立聚焦命令**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_source_intake tests.unit.test_publish_feedback_loop tests.unit.test_agent_scheduler
PYTHONPATH=src python3 -m unittest tests.integration.test_pipeline tests.integration.test_novel_os_acceptance
PYTHONPATH=src python3 -m unittest tests.unit.test_context_and_production_chain tests.unit.test_loop_kernel
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_12_chapter_industrial_pressure
```

Expected: 当前失败被归入 Source Gate、项目隔离、旧运行期望、质量门禁四组；不得出现无法归类的静默错误。

- [ ] **Step 3: 更新测试分层说明**

在 `docs/quality/regression-tests.md` 明确：deterministic local、sandbox integration、browser E2E、real provider、real platform五层及其默认命令。

- [ ] **Step 4: 验证文档**

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 5: 提交独立文档变更**

```bash
git add docs/reports/novel-os-priority-issues-rebaseline.md docs/reports/novel-os-16-priority-issues-progress.md docs/quality/regression-tests.md
git commit -m "docs: record phase zero regression baseline"
```

### Task 0.2：修复 Source Guarded Readiness 空项目Schema回归

**Files:**
- Modify: `src/novel_forge/modules/source_intake/guarded_apply_readiness.py`
- Modify: `tests/unit/test_source_intake.py`
- Test: `tests/unit/test_review_issue.py`

**Interfaces:**
- Consumes: `build_source_guarded_apply_readiness_report(storage, project_id, persist)`。
- Produces: workspace级报告仍满足 `ProjectMetricSnapshot` Schema，项目级报告保持真实project归属。

- [ ] **Step 1: 写失败测试**

增加测试：`project_id=""`且`persist=False`时返回合法报告，`content.project_id`使用明确的system/workspace scope值，metadata不伪造小说项目。

- [ ] **Step 2: 验证测试先失败**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_source_intake.SourceIntakeTests.test_guarded_apply_readiness_supports_workspace_scope
```

Expected: FAIL，错误包含`project_metric_snapshot content missing required field: project_id`。

- [ ] **Step 3: 最小实现**

在报告构建处区分查询filter和持久scope：查询仍允许空project，Schema内容使用明确`system:workspace`标识；metadata记录`scope_kind=workspace`。不得让该标识匹配任意小说项目。

- [ ] **Step 4: 运行正负回归**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_source_intake tests.unit.test_review_issue
```

Expected: PASS，原有缺来源/高风险负例仍阻断。

- [ ] **Step 5: 提交**

```bash
git add src/novel_forge/modules/source_intake/guarded_apply_readiness.py tests/unit/test_source_intake.py
git commit -m "fix: preserve workspace scope in source readiness"
```

### Task 0.3：迁移生产就绪测试夹具的Source Gate证据

**Files:**
- Modify: `tests/unit/publishing_fixtures.py`
- Modify: `tests/unit/test_publish_feedback_loop.py`
- Modify: `tests/unit/test_agent_scheduler.py`
- Modify: `tests/unit/test_agent_editor_continuity_evaluation.py`
- Modify: `tests/unit/test_analysis_services.py`
- Reuse: `src/novel_forge/modules/source_intake/`

**Interfaces:**
- Consumes: strict Context/Publish flow需要stale sweep、retention sweep和source-derived eligibility证据。
- Produces: `create_production_ready_release_inputs`创建完整合法治理证据；非法fixture仍缺证据并被阻断。

- [ ] **Step 1: 增加共享fixture断言**

断言生产就绪fixture运行`run_source_governance_runtime_gate(..., environment="production")`得到`passed`和`blocking_count == 0`。

- [ ] **Step 2: 验证先失败**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop.PublishFeedbackLoopTests.test_release_package_production_ready_fixture_creates_ready_package
```

Expected: FAIL，Source Runtime Gate报告3条blocking rows。

- [ ] **Step 3: 扩展共享fixture builder**

通过现有Source Intake API创建项目级SourcePolicy、SourceRiskReport、eligibility以及clean stale/retention sweep证据；不直接把所有资产标成trusted，不添加Gate bypass。

- [ ] **Step 4: 修复错误优先级测试**

`test_production_analysis_conversion_requires_source_eligibility_evidence`必须先构建其他必需生产治理证据，使断言仍验证目标错误`Analysis source eligibility blocks production conversion`，而非被更早的无关Gate遮蔽。

- [ ] **Step 5: 运行聚焦套件**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_agent_scheduler tests.unit.test_agent_editor_continuity_evaluation tests.unit.test_analysis_services
```

Expected: PASS；缺证据、stale、R4和raw source负例继续PASS其阻断断言。

- [ ] **Step 6: 提交**

```bash
git add tests/unit/publishing_fixtures.py tests/unit/test_publish_feedback_loop.py tests/unit/test_agent_scheduler.py tests/unit/test_agent_editor_continuity_evaluation.py tests/unit/test_analysis_services.py
git commit -m "test: migrate production fixtures to source governance"
```

### Task 0.4：修复项目隔离和系统运行资产归属

**Files:**
- Modify: `src/novel_forge/modules/agent_registry/service.py`
- Modify: `src/novel_forge/modules/agent_scheduler/service.py`
- Modify: `src/novel_forge/modules/workflow_nodes/service.py`
- Modify: `src/novel_forge/workflows/pipeline.py`
- Modify: `tests/integration/test_pipeline.py`
- Modify: `tests/unit/test_agent_scheduler.py`
- Modify: `tests/unit/test_workflow_nodes.py`

**Interfaces:**
- Consumes: `validate_project_scope`及LocalStorage项目引用守卫。
- Produces: 小说资产绑定真实project；全局注册表/lease绑定明确system workspace且不参与小说lineage。

- [ ] **Step 1: 写项目隔离负例和system scope测试**

增加断言：Agent Registry和Scheduler lease不再是unscoped；project A不能引用project B资产；system运行资产不能被Context选择为小说输入。

- [ ] **Step 2: 验证先失败**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_pipeline tests.unit.test_agent_scheduler tests.unit.test_workflow_nodes
```

Expected: FAIL并复现unscoped/cross-project lineage。

- [ ] **Step 3: 实现统一system scope helper**

复用或新增单一helper返回`project_id="system"`、明确`workspace_path`及`scope_kind="system"`；只用于Registry、lease等基础设施资产。小说WorkflowRun/NodeRun继续继承真实project。

- [ ] **Step 4: 修复Pipeline引用创建**

在写ReaderPromise、PleasurePoint、Canon和Review资产时使用当前workspace project scope和`filter_project_safe_references`，禁止引用前一次sample run遗留project资产。

- [ ] **Step 5: 验证临时双运行**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_pipeline
```

Expected: 两次sample运行均通过，第二次清理旧sample资产且无cross-project lineage。

- [ ] **Step 6: 处理当前workspace历史资产**

使用项目已有迁移/隔离接口生成报告，将3个无归属资产标记为system scope或隔离；不得手工伪造小说project归属。

- [ ] **Step 7: 验证workspace**

Run: `make validate`

Expected: PASS，0 unscoped business/runtime assets。

- [ ] **Step 8: 提交**

仅添加本任务实际修改文件后提交：

```bash
git commit -m "fix: enforce project and system runtime scopes"
```

### Task 0.5：修复质量门禁升级后的成功/阻断夹具

**Files:**
- Modify: `tests/integration/test_novel_os_12_chapter_industrial_pressure.py`
- Modify: `tests/unit/test_context_and_production_chain.py`
- Modify: `tests/unit/test_loop_kernel.py`
- Modify: `tests/integration/test_novel_os_acceptance.py`
- Reuse: `src/novel_forge/modules/review_issue/service.py`
- Reuse: `src/novel_forge/modules/character_pressure/service.py`

**Interfaces:**
- Consumes: protagonist agency和其他内容质量ReviewIssue policy。
- Produces: 合格成功fixture和明确阻断fixture；不更改生产阈值。

- [ ] **Step 1: 为质量规则写直接边界测试**

增加合格文本达到当前agency rubric、边界文本产生warning/blocking语义、不合格文本生成blocking ReviewIssue的断言。

- [ ] **Step 2: 运行当前失败测试**

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_12_chapter_industrial_pressure tests.integration.test_novel_os_acceptance tests.unit.test_context_and_production_chain tests.unit.test_loop_kernel
```

Expected: 复现release blocked、run failed和sequence failed。

- [ ] **Step 3: 修复成功fixture内容**

成功样本必须给主角明确目标、主动选择、付出代价并改变局面；不得只注入marker或降低阈值。

- [ ] **Step 4: 修复阻断测试期望**

专门测试低agency、Source Gate或budget hard-stop的用例应断言`failed/waiting_human`、ReviewIssue和recovery instruction，不再期待`running/succeeded`。

- [ ] **Step 5: 运行聚焦测试**

Run同Step 2。

Expected: PASS，发布包只在无blocking issue时生成。

- [ ] **Step 6: 提交**

```bash
git add tests/integration/test_novel_os_12_chapter_industrial_pressure.py tests/integration/test_novel_os_acceptance.py tests/unit/test_context_and_production_chain.py tests/unit/test_loop_kernel.py
git commit -m "test: align acceptance fixtures with quality gates"
```

### Task 0.6：完整回归、证据更新和Phase 0关闭

**Files:**
- Modify: `docs/reports/novel-os-16-priority-issues-progress.md`
- Modify: `docs/reports/novel-os-priority-issues-rebaseline.md`
- Modify: `docs/reports/module-maturity-matrix.md`（仅更新被证据改变的状态）
- Modify: `docs/reports/next-production-slices.md`（保留现有用户修改）

**Interfaces:**
- Consumes: Tasks 0.1-0.5全部测试结果。
- Produces: Phase 0可重放验收记录和Phase 1进入决定。

- [ ] **Step 1: 运行第一遍完整确定性套件**

```bash
make lint
make check-skills
make validate
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
npm --prefix web/admin run lint
npm --prefix web/admin test
git diff --check
```

Expected: 所有确定性必测项0 failure/0 error；Playwright若未安装继续明确标记为未执行而非通过。

- [ ] **Step 2: 运行第二遍Python和workspace验证**

```bash
make validate
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: 与第一遍相同，证明无顺序污染和历史资产漂移。

- [ ] **Step 3: 更新进度和重基线**

记录每个根因、修改文件、测试命令、计数、耗时、外部未执行项和Phase 1前置条件。

- [ ] **Step 4: 提交Phase 0证据**

```bash
git add docs/reports/novel-os-16-priority-issues-progress.md docs/reports/novel-os-priority-issues-rebaseline.md docs/reports/module-maturity-matrix.md docs/reports/next-production-slices.md
git commit -m "docs: close trusted phase zero baseline"
```

---

## Phase 1-5后续工作包索引

| ID | 工作包 | 依赖 | 进入时必须补充的精确计划 |
|---|---|---|---|
| WP-01 | ExecutionEnvelope v2和核心Ref | Phase 0 | Schema、compat adapter、入口枚举、bypass contract |
| WP-02 | 唯一Production Kernel | WP-01 | Workflow/Node/AgentAttempt权威和旧Pipeline迁移 |
| WP-03 | Fixture隔离和双目标创作验收 | WP-02 | Topic/World/Character Provider/人工输入adapter |
| WP-04 | Context/Source全入口迁移 | WP-01/02 | Context coverage manifest和fail-closed contract |
| WP-05 | Integrity/Quality/Release Gate分离 | WP-02/04 | uniqueness/progression/state/human release blockers |
| WP-06 | 章节运行预算和索引 | WP-02 | 写入、扫描、Context、vector、token、p95 budgets |
| WP-07 | 小说领域StateEvent/Snapshot | WP-02/04 | typed event union、accepted后提交、replay/migration |
| WP-08 | Industrial authority和Outbox | WP-02/07 | UoW、artifact finalize、outbox failure injection |
| WP-09 | Golden/Human Calibration | WP-05/07 | versioned corpus、annotation agreement、policy release |
| WP-10 | ApprovalRef verifier | WP-01/08 | actor/scope/expiry/version/consumption/revocation |
| WP-11 | 真实Provider 10/30章 | WP-03..10 | 固定目标、预算、Rubric、人工评审、运行报告 |
| WP-12 | Release Adapter统一 | WP-10/11 | prepare/validate/publish/verify/compensate/receipt |
| WP-13 | Bounded Planner/Recurring | WP-07..12 | PlanVersion、stop/takeover、missed run、circuit breaker |
| WP-14 | 深度治理控制台 | 后端能力就绪 | Source/Canon/Eval/Portfolio typed UI与Playwright E2E |
| WP-15 | 三书、CI、安全、DR | 单书30章通过 | 隔离、分层CI、安全套件、restore rehearsal |

## Phase 1A：ExecutionEnvelope v2（当前工作包）

### Task 1.1：契约与兼容适配

**Files:** `modules/os_envelope/service.py`、`tests/unit/test_os_envelope_v2.py`

- [ ] 增加 canonical refs、`schema_version`、correlation/causation 和稳定 idempotency key。
- [ ] 保留 v0.1 legacy shadow，旧请求标记 `legacy_derived`，字段冲突 fail-closed。
- [ ] 增加 native v2、legacy、缺字段、冲突、稳定幂等和父子因果测试。

### Task 1.2：入口 Manifest 与旁路契约

**Files:** `modules/production_kernel/entrypoints.py`、`tests/unit/test_production_entrypoint_contract.py`

- [ ] 登记章节生产、Workflow、Agent dispatch、Loop、Review/Revision/Release等生产入口。
- [ ] Contract test 验证每个登记入口的 envelope policy、状态 owner 和 Kernel route。
- [ ] 未登记生产入口和 direct bypass 必须失败；普通治理 CRUD 不纳入执行入口。

### Task 1.3：Chapter Production Kernel tracer bullet

**Files:** `modules/production_kernel/`、`modules/chapter_production_bus/service.py`、API/Worker调用方及测试。

- [ ] Chapter Bus 在任何业务写入前 enforce v2 Envelope。
- [ ] Kernel facade 复用 ChapterProductionRun，不创建新状态机。
- [ ] API、Worker、Workflow processor通过同一 Kernel command dispatch。
- [ ] 增加缺Envelope零副作用、幂等重放、scope冲突和恢复测试。

### Task 1.4：Phase 1A验证

- [ ] 聚焦 contract/workflow/scheduler/production-chain 测试通过。
- [ ] 两轮完整确定性回归、validate、lint、skills、Web和diff通过。
- [ ] 更新重基线与进度文档后进入WP-02。

## Phase 3A：跨章证据与Golden/Human Calibration（当前已执行）

### Task 3A.1：Provider-aware跨章相似度

**Files:** `src/novel_forge/modules/longform_stability/semantic_similarity.py`、`src/novel_forge/modules/longform_stability/service.py`、`tests/unit/test_longform_stability.py`

- [x] 保留HashEmbedding作为离线确定性回归信号，并在报告中标记`regression_only`。
- [x] 支持注入或配置真实Embedding Provider；健康检查通过时标记`verified`，失败时显式记录fallback原因。
- [x] 保留lexical/embedding/composite三类证据和质量声明边界；不把相似度单指标升级为精品质量结论。

### Task 3A.2：Human/Golden校准与阈值发布

**Files:** `src/novel_forge/modules/evaluation_center/service.py`、`src/novel_forge/modules/quality_eval/service.py`、`tests/unit/test_quality_eval_v2.py`

- [x] Human annotation支持版本、角色、置信度；Golden case支持多标注路径和预期verdict。
- [x] Calibration report记录人类共识、多人agreement、MAE和保守阈值建议。
- [x] `create_calibrated_quality_rubric`只创建新Rubric版本，不修改旧版本，并绑定`calibration_ref`。
- [x] Provider judge请求和结果记录Rubric版本、阈值来源和校准引用；生产调用可启用`require_calibrated_thresholds=True`。
- [x] 生产模式拒绝只有单案例/单标注者的校准基线；生产证据至少需要两个人工标注案例、两名标注者和agreement≥0.8。

### Task 3A.3：进入真实Provider验收的前置条件

- [ ] 以自有/公版/人工构造样本扩充跨题材正负Golden cases，并完成至少双人标注。
- [ ] 运行外部Provider 10章和30章验收，使用校准Rubric；记录Token、成本、延迟、失败、状态漂移和人工评分。
- [ ] 在真实Provider报告通过前，不得把本地HashEmbedding或单次人工标注描述为精品长篇质量证明。
