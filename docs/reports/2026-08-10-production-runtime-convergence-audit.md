# Novel Forge 当前工程架构、Canonical Runtime 与文档收敛审计

- 审计日期：2026-08-10
- 目标分支：`feat/v7-content-intelligence-and-longform-proof`
- 证据提交：`7de2bdc91be03760ad14db5b1ecdcda6600201c0`
- 提交标题：`fix: align capability pack timeout authority`
- 审计范围：当前代码、配置、迁移、测试、Compose、CLI/API/Worker 组合、当前本地 proof 证据与仓库文档
- 变更边界：本轮只新增本审计报告，没有修改业务代码、配置、测试、迁移或既有文档

## 结论摘要

Novel Forge 当前真实形态不是“完整 Autonomous Novel OS”，也不是“一次性 Prompt 工具”。它已经形成了一个以 PostgreSQL 为状态权威、以 Command Kernel 为业务执行内核、以 MinIO 为对象证据存储、以具体 Authority Worker 为异步执行者的本地优先生产后端。这个后端最成熟、最清晰的业务垂直切片是单章 Chapter Saga。

当前结论必须分三层表达：

1. **基础设施 Canonical Runtime 已存在。** `compose.yml` 明确部署 PostgreSQL、MinIO、迁移服务、Authority API 和 8 个具体 Worker；正式 API/CLI 默认使用 PostgreSQL Authority，Legacy 只能显式进入，生产环境会 fail closed。
2. **单章 Canonical Production Runtime 已存在。** API 和 Chapter Worker 使用同一 `build_chapter_authority_application()` 组合根，执行链实际贯穿 Operation/Saga、Attempt、Lease、Fence、ExternalEffect、Production Execution Gateway、Provider、结构/语义校验、AssetVersion、Canon/Quality/Publish Gate 与恢复。
3. **整书 Autonomous Novel OS Canonical Runtime 尚不存在。** 完整 Book Supervisor、Story Planning、ChapterGroup 与 Replan 的代码已经存在，但没有注入正式 API 服务，也没有进入 Book Worker。正式 Book Worker 只负责已有 Chapter 的 reconcile/accept，以及 Reader Outcome、Longform Recap sidecar。`RESOLVED_AUTHORITY_INPUT` 的 Book 通过 API tick 会因为 Supervisor 未配置而失败，通过 Worker 则会在 `READY` 状态返回 `NOOP`。

因此，下一阶段不应继续横向增加能力。正确优先级是 **Production Runtime Convergence**：先使当前 HEAD 门禁恢复绿色，修复测试发现机制，建立唯一整书组合根，把已有 Planning/ChapterGroup/Supervisor/Replan 装入同一正式执行链，再进行当前 SHA 的真实 Provider 和长链证明。

## 证据口径

本文使用以下标签：

- **代码事实**：当前提交中的可定位实现、配置、入口或调用关系。
- **运行验证**：本轮实际执行命令得到的结果。
- **合理推断**：由代码事实和运行结果共同支持，但未在真实部署环境完成端到端证明。
- **尚未验证**：因本机服务、凭证或当前门禁失败，不能作肯定结论。

本文中的 `production_wired` 只表示进入正式组合根；不等于 `production_verified`。`code_exists`、可导入、被 manifest 列出或存在测试文件，都不构成生产接线证据。

## 1. 审计基线与运行验证

### 1.1 仓库基线

| 项目 | 结果 | 证据分类 |
|---|---|---|
| 分支与远端 | 本地 HEAD 与 `origin/feat/v7-content-intelligence-and-longform-proof` 同为 `7de2bdc...` | 运行验证 |
| 审计前工作树 | clean | 运行验证 |
| Python 生产代码 | 773 个 `.py`，270,663 行 | 运行验证 |
| Python 测试代码 | 411 个 `.py`，90,302 行 | 运行验证 |
| 一级模块目录 | 133 个 | 运行验证 |
| API router 文件 | 61 个 | 运行验证 |
| Worker 文件 | 16 个 | 运行验证 |
| 迁移版本模块 | 73 个版本，当前 head 为 `20260806_0073_core_functional_loops`；目录另含 `__init__.py` | 代码事实、运行验证 |
| 文档 | 413 个文件；382 个 Markdown；约 75,099 行 Markdown | 运行验证 |
| 阶段报告 | `docs/reports/` 195 个文件 | 运行验证 |

规模本身不是缺陷，但当前正式部署只使用其中一部分。维护风险来自“模块存在、manifest 声明、测试夹具接线、正式组合接线”四种状态没有被清楚区分。

### 1.2 本轮命令结果

| 命令/检查 | 结果 | 解释 |
|---|---|---|
| `make validate` | PASS | 编译、Ruff、lint ratchet、manifest、fitness、Compose 静态配置通过；它不运行完整业务测试 |
| `make authority-test` | FAIL | 运行 1,388 个 unit tests 后出现 5 failures、3 errors；默认 Capability Pack 无法编译 |
| `pytest -q tests/unit tests/architecture tests/acceptance` | FAIL：22 failed、1,631 passed、16 warnings，另有 2,014 subtests passed | 暴露 8 个 Pack 合同失败及 14 个 unittest 未执行的 Runtime Resolver 失败 |
| `python -m unittest discover -s tests/acceptance` | PASS：2 tests | 只证明当前两个 fixture acceptance 用例 |
| `npm --prefix web/admin test` | PASS：11 tests | 测试内容是源代码/路由静态 feature architecture，不是浏览器或运行栈 smoke |
| Docker daemon | 不可用 | 无法启动干净 PostgreSQL/MinIO/Compose 栈 |
| `pg_isready -h localhost -p 55432` | no response | 本轮无法重跑 PostgreSQL integration、迁移、恢复和 Compose smoke |

**尚未验证：** 当前提交的 PostgreSQL 集成、并发/租约/恢复、干净迁移、Compose 启动、浏览器 E2E 和真实 Provider 端到端不能在本轮标记为通过。

## 2. 当前真实系统架构

### 2.1 正式部署拓扑

`compose.yml` 是当前唯一明确的正式部署拓扑：

```text
PostgreSQL  <---- Authority API ----> operator / admin client
    ^                 |
    |                 +---- Provider callback
    |
    +---- Chapter Authority Worker ---- Provider / Codex CLI / fixture backend
    +---- Agent Authority Worker
    +---- Content Authority Worker
    +---- Source Authority Worker ------ MinIO
    +---- MKAOS Authority Worker
    +---- Book Authority Worker
    +---- Outbox Worker
    +---- Maintenance Worker

MinIO = Blob / execution evidence / export storage
PostgreSQL = Operation、Attempt、Lease、Fence、ExternalEffect、AssetVersion、
             Book/Chapter/Canon/StoryState、Gate、Projection、Outbox 的状态权威
```

**代码事实：** `compose.yml:4-37` 固定 `NOVEL_FORGE_STORAGE_AUTHORITY=postgresql`、关闭 Legacy/dual-write/silent fallback，配置 MinIO；`compose.yml:147-339` 部署 API 和 8 个具体 Worker。默认环境仍为 `development`，默认 Provider 为 `mock`，因此默认 Compose 是 Authority 架构的 fixture/development 拓扑，不是实时 Provider 生产证明。

**代码事实：** 当前 Compose 不部署 Redis、Celery、Qdrant、Neo4j、Web Admin 或 D0 Provider Worker。这些能力仍存在于 Legacy 配置、旧模块或单独脚本中，但不属于当前 Canonical Compose。

### 2.2 入口与组合根

| 入口 | 当前行为 | 正式性 |
|---|---|---|
| API `novel_forge.api.app:create_app` | `storage_authority=postgresql` 时构建 Authority App；production 遇到 Legacy 直接失败 | Canonical |
| CLI `novel-forge` | 默认只有 Authority 命令；Legacy 必须使用 `novel-forge legacy ...`，production 禁止 | Canonical；Legacy 隔离明确 |
| `authority-chapter-run` | 调用同一个 Chapter Application，但同步执行只在 test/development fixture 模式允许 | 操作/验证入口，不是生产 Worker 替代品 |
| Chapter API | durable admission，返回 202；不在请求线程执行整章 | Canonical |
| Chapter Worker | 从 PostgreSQL 查询 pending root，逐节点推进 Saga | Canonical |
| Book API/Worker | 使用 `PostgresBookAuthority`，但 API 与 Worker 对 resolved Book 的调度器不同 | 部分 Canonical，整书闭环未收敛 |

主要证据：

- `src/novel_forge/api/app.py:7-19`
- `src/novel_forge/cli/__init__.py:13-45, 231-267`
- `src/novel_forge/api/authority_app.py:114-134, 169-205`
- `src/novel_forge/api/authority_dependencies.py:206-824`
- `src/novel_forge/workers/chapter_authority.py:31-46`

### 2.3 PostgreSQL Authority 是否唯一

**代码事实：** 在 Authority API、Chapter Worker、Agent Worker、Book Worker、Content/Source/MKAOS Worker 的正式组合中，状态读写均通过 PostgreSQL Authority repository/UoW。`IndustrialSettings` 在 PostgreSQL Authority 模式禁止 Legacy write、silent fallback 和 write-through；生产环境禁止 `legacy_local`。

**代码事实：** MinIO 只承载对象、执行 payload/evidence 和 export，不决定 Operation、Attempt、资产激活或 Canon 状态。Production Execution Gateway 也明确“不拥有 Attempt state”，只验证已有 Authority Attempt/Fence 并执行 backend（`src/novel_forge/modules/production_execution/gateway.py:1-4`）。

**结论：** 对当前正式 Authority 路径，PostgreSQL 保持唯一状态权威。没有发现正式路径在 PostgreSQL 失败后回落 LocalStorage 的静默旁路。

**边界：** 仓库仍保留 `legacy_app.py`、`compose.legacy.yml`、LocalStorage、Celery 任务和大量旧业务模块；它们构成显式非生产平面，而不是第二个正式权威。当前 `legacy-surface-manifest.yaml` 没有完整覆盖所有这些旧平面，治理仍不闭合。

## 3. Canonical Production Runtime

### 3.1 单章正式执行链

当前最清晰且实际接线的 Canonical Runtime 是：

```text
FastAPI Chapter command / Authority CLI admission
  -> build_chapter_authority_application
  -> ChapterAuthorityApplication.admit
  -> admit_single_chapter_saga
  -> PostgreSQL Operation + Saga + first READY child
  -> Chapter Worker.pending_roots
  -> ChapterAuthorityScheduler.tick
  -> create/queue/lease/start Attempt + Fence
  -> Chapter handler
  -> plan ExternalEffect
  -> ProductionExecutionGatewayExternalEffectAdapter
  -> AdmissionController verifies Attempt/Fence/Route/Input/Pack
  -> Scripted Fixture / Codex CLI / injected Remote Provider backend
  -> receipt + usage + cost + model_call_log
  -> schema validation + semantic validation
  -> Agent Candidate binding（适用节点）
  -> Authority AssetVersion materialization
  -> Agent Domain Commit binding
  -> Canon approval / quality fan-out / publish gate / export
  -> Operation/Saga completion
  -> retry / lease takeover / UNKNOWN effect reconciliation / manual resolution
```

关键证据：

- Admission：`src/novel_forge/modules/chapter_authority/application.py:68-91`、`orchestrator.py:103-183`
- Worker polling：`src/novel_forge/modules/chapter_authority/scheduler.py:106-245`
- Attempt/Lease/Fence：`src/novel_forge/modules/command_kernel/attempt_runtime.py`
- ExternalEffect：`src/novel_forge/modules/command_kernel/external_effect_runtime.py:86-1113`
- PEP 不拥有 Attempt：`src/novel_forge/modules/production_execution/gateway.py:1-4`
- Provider/PEP 组合：`src/novel_forge/api/authority_dependencies.py:535-740`
- Agent Candidate 与已有 Chapter Attempt 共用 identity：`src/novel_forge/modules/agent_runtime/chapter_binding.py:623-686`
- Domain asset 后提交 Agent binding：`src/novel_forge/modules/chapter_authority/scheduler.py:728-768`
- 恢复/UNKNOWN effect：`src/novel_forge/modules/chapter_authority/scheduler.py:1068-1173`

### 3.2 Agent Runtime 的真实定位

当前有两种 Agent 语义：

1. 独立 `agent.candidate.execute` 是 PostgreSQL durable job，由 Agent Worker 执行，只产出 Candidate 与执行证据；OperationDefinition 明确 `domain_commit_required=true`。它不自动获得任意业务域写权限。
2. Chapter-bound Agent 不是第二套 Chapter Attempt。它复用 Chapter Operation/Attempt/Fence，先登记 Candidate，再由 Chapter handler 物化域资产，最后把已存在的域资产附着到 Collaboration Commit。

这说明新 Agent Runtime 与 Chapter 主链的边界基本正确：Agent 产生候选，Domain Authority 提交事实。但“Agent Center”仍不应被描述为完整自治中心，因为独立 Candidate 的下游 Domain Commit 编排、UI 深度、operation coverage 和真实 Provider 证明仍不完整。

### 3.3 Recovery 与执行平面的职责

| 平面 | 应有职责 | 当前事实 | 结论 |
|---|---|---|---|
| Command Kernel | 业务 Operation/Saga/Attempt/Lease/Fence/ExternalEffect、幂等、重试、取消、恢复 | Chapter/Agent/Content 等正式命令使用 | Canonical 业务执行权威 |
| Production Execution Plane | Attempt-bound admission、immutable route/input、backend、provider evidence | 不创建业务 Attempt；通过 ExternalEffect adapter 被 Chapter 调用 | 不是重复业务调度器 |
| Agent Runtime | Agent Definition/Binding、Candidate、Collaboration/Domain Commit evidence | 使用共享 Command Kernel；Chapter binding 共用 Attempt | 边界基本合理 |
| Runtime Job Authority | Worker 的可恢复 operational job、自己的 attempt/lease/fence/checkpoint | Book Worker 和通用 runtime group 使用 | 与业务 Attempt 形成双层可靠性 envelope，需明确适用范围 |
| Book Authority Scheduler | reconcile/accept 已提交 Chapter；Reader/Recap sidecar | 正式 Worker 使用 | 不是完整 Book Supervisor |
| Book Production Supervisor | Planning、ChapterGroup、Chapter dispatch、checkpoint、replan decision | 只在测试/proof 脚本实例化 | 未进入正式运行面 |

Command Kernel 与 PEP 并非重复执行平面；前者拥有业务状态，后者拥有受控外部执行。真正的重复复杂度集中在 Runtime Job Authority 与业务 Attempt 的双层租约/重试，以及仍保留的大量 Legacy scheduler/runtime。

### 3.4 Provider 正式装配

**代码事实：** `build_chapter_authority_application()` 在 development/test 自动注册 `ScriptedProviderAdapterV2`；在 controlled environment 不自动注册远端 Provider。API 和 Worker 都没有传入外部 `provider_registry`。

**代码事实：** OpenAI V2 adapter 和 SDK transport 已存在，但正式调用只见于 D0 runner 和测试。当前 Authority API/Chapter Worker 组合没有把 OpenAI adapter 注入 registry。因此 OpenAI 是 `code_exists`，不是 `production_wired`。

**代码事实：** Codex CLI 是例外。Chapter composition 直接构建 `CodexCliExecutionBackend`，并在 controlled environment 强制单一模型、绝对 executable、空隔离 workspace、持久 execution root、release SHA、auth/host、不可变 pricing、cost cap 和结构/语义验证。它是当前唯一真正进入 Chapter 正式组合根的实时模型 backend。

**代码事实：** D0 PostgreSQL Worker 的 scheduler 始终调用 `execute_fixture()`（`provider_qualification/scheduler.py:31-55`），模块文档也明确 fixture 只证明恢复协议。真实 OpenAI D0 调用是独立脚本路径，不是该 Worker 的正式执行路径。

**结论：** Provider 边界的控制策略较成熟，但“统一正式 Provider 装配”尚未完成：Codex CLI 已接线，OpenAI 远端 adapter 未接线，D0 Authority Worker 仍是 fixture-only，Compose 默认也是 mock。

### 3.5 Capability Pack 是否成为执行约束

Capability Pack 不只是配置资产。Controlled Chapter/Planning/Reader 执行会冻结 Pack/Deployment/Binding snapshot，并在 ExternalEffect 前校验 capability、operation、schema、tool、timeout、budget、model policy 和 provider qualification。这个方向符合执行约束要求。

但当前 HEAD 的默认 Chapter Pack 自身不合法：

- `config/capability_packs/chapter_generation_pack.json:397-406` 的 `quality` 节点绑定 `quality.intrinsic.judge`，却使用 `timeout:quality-aggregate:v1`；
- 同一 capability 的其他节点使用 `timeout:quality-intrinsic-judge:v1`；
- validator 依据 governed Capability Definition fail closed；
- `make authority-test` 和全量 pytest 都因此失败。

所以当前状态是：**Capability Pack 已 production-wired，但默认正式 Pack 在证据提交上不可通过合同门禁。** 这比“Pack 只是配置未生效”更严重，因为正式约束已经接线，错误会直接阻断 controlled execution。

### 3.6 Context、Knowledge、Memory、Canon 与长篇状态

**Context：** Chapter `_ContextHandler` 要求 context candidate 元数据与冻结 AssetVersion 输入完全一致，检查物理类型、manifest/selected/rejected 集合、token budget，并输出 `source_isolation_result`。Authority Context Bundle 已进入 Chapter Worker 主链。

**Knowledge：** `knowledge_pack` 是允许的 context 类型，也会记录版本，但 Draft 的 required inputs 是 `chapter_plan/style_policy/quality_rubric/platform_profile`，不是 Knowledge Pack。MKAOS 有独立 API/Worker/Authority，但不是每次核心生成的强制前置。因此“所有生产生成必须有 knowledge_pack_id”目前是目标设计，不是代码事实。

**Memory：** 正式 Chapter 路径没有把旧 L0-L5 Memory OS 或 Legacy KG service 当作状态权威。持续状态主要由 Authority AssetVersion、StoryState、Canon snapshot、Book acceptance 与 frozen context 承担。

**Canon/Long-form State：** `PostgresBookAuthority.accept_chapter()` 会持久化 ChapterOutcome、StoryState snapshot、Canon snapshot，并更新 active refs（`book_authority/production.py:717-905`）。这是一条真实的跨章状态链。但它只在 Chapter 已被 Book 接纳后成立，不能弥补下一章计划与 Replan 未自动装配的问题。

## 4. Book → Planning → ChapterGroup → Chapter → Reader → Recap / Replan 闭环

### 4.1 已真实接线的部分

- Book run、Chapter submission、reconcile、accept、state projection：PostgreSQL Authority。
- Book Worker：`PostgresBookAuthorityScheduler` + `RuntimeJobAuthority`。
- Chapter accept 后：Reader Outcome sidecar。
- cadence 或 group complete 时：Longform Recap sidecar。
- Chapter acceptance：更新 StoryState/Canon active snapshot。

### 4.2 未接线的部分

完整 `PostgresBookProductionSupervisor` 能够：

- 从 resolved Authority inputs 推进 Planning；
- 建立/推进 ChapterGroup；
- 为下一章准备输入并提交 Chapter；
- reconcile/accept Chapter；
- 建立 narrative checkpoint；
- 判断 `REPLAN_REQUIRED`。

但正式调用图不包含它：

- `AuthorityApiServices` 没有 `book_production_supervisor`、Story Planning、ChapterGroup、PlanChange 或 Replan service 字段（`authority_app.py:114-134`）。
- API 对 `RESOLVED_AUTHORITY_INPUT` 的 `/runs/{id}/tick` 使用 `getattr(..., "book_production_supervisor", None)`；未配置时抛 `BOOK_PRODUCTION_SUPERVISOR_NOT_CONFIGURED`（`api/routers/book_authority.py:258-279`）。
- Book Worker 直接构造 `PostgresBookAuthorityScheduler`，没有构造 Supervisor（`workers/book_authority.py:210-220`）。
- 该 Scheduler 在 `READY` 且没有已接纳章节 sidecar 时返回 `NOOP`（`book_authority/governed_scheduler.py:30-73`）。
- Supervisor 到达 `REPLAN_REQUIRED` 只返回 `START_REPLAN` action；不会执行 `BookReplanCoordinator`（`book_authority/supervisor.py:146-157`）。
- `PostgresBookProductionSupervisor(...)` 的非定义调用只存在于 `scripts/run_short_longform_runtime_proof.py` 和 `tests/integration/test_core_functional_loops_postgres.py`。
- `BookReplanCoordinator(...)` 只存在于同一 proof 脚本和测试。

### 4.3 闭环结论

**代码事实：** Book → 已提交 Chapter → Reader → Recap 的后半段 sidecar 链已接线。

**代码事实：** Planning → ChapterGroup → 下一章提交 → Recap 驱动 Replan 的前半段/回流链只在 proof harness 和测试组合中存在。

**结论：** 当前没有正式、自动、唯一的 Book 长篇闭环。Operator 可以手工提供冻结 ChapterPlan/context，并通过 Book Authority 顺序协调 Chapter；proof 脚本也可以自行组合完整 supervisor。但二者都不能证明生产 API/Worker 已形成 Autonomous Novel OS。

## 5. 架构问题分级

### Critical

#### C-01：整书自治执行链没有正式组合根

**代码事实：** resolved Book API tick 必然寻找一个未注入的 Supervisor；Book Worker 使用功能更窄的 Scheduler。API 与 Worker 对同一种 Book input mode 不是同一执行语义。

**影响：** “Book production.run” 可以 admission，但不能由正式 Worker 从 `READY` 自动进入 Planning/ChapterGroup/Chapter。Reader/Recap 的结果也没有正式 Replan consumer。继续新增 Reader、Planning 或长篇能力只会增加孤立模块。

**收敛方向：** 选择一个 Book Production composition root，把 Supervisor、StoryPlanning、ChapterGroup、PlanChange/Replan 和 Book Scheduler 作为明确子能力装入 API/Worker；API tick 与 Worker 必须调用同一个 application/supervisor interface。

#### C-02：当前 HEAD 的默认 Capability Pack 合同失败

**运行验证：** `make authority-test` 失败；全量 pytest 中 8 个失败直接来自 Pack compiler/validator。

**影响：** 受控 Chapter 执行的核心约束资产不一致。当前提交标题声称对齐 timeout authority，但证据提交仍是红的，不能被视为可发布基线。

**收敛方向：** 先决定 `quality` 聚合节点应使用独立 aggregate capability，还是继续使用 intrinsic judge；只修一个事实源并重新生成/同步派生 catalog、Pack、测试 fixture，禁止再手工多点对齐。

#### C-03：正式测试门禁漏跑 pytest 风格用例

**代码事实：** Makefile 与 CI 均使用 `unittest discover`。仓库已有 43 个文件、174 个顶层 `def test_*`；它们不会被 unittest 加载。`tests/integration/test_core_functional_loops_postgres.py` 被 Authority runner 显式列出，但 unittest loader 对该模块计数为 0。

**运行验证：** unittest 路径没有显示 Runtime Resolver 的 14 个失败；全量 pytest 显示这些用例仍期待 `chapter.draft.generate@2.2.0`，而 fixture 已迁到 `2.3.1`。`docs/adr/0001-stdlib-unittest-first.md` 仍为 Accepted，但其前提“pytest 未安装、pyproject dependency-free”已经失效。

**影响：** “核心功能循环测试文件存在”“Authority PostgreSQL suite 包含该文件”“CI green”都可能是假阳性。集成证明和长篇闭环证明目前不可依赖声明测试数。

**收敛方向：** P0 统一测试 runner。优先迁移为 pytest 并保留 unittest class 兼容；或者把所有顶层 pytest 测试改为 unittest，但不能继续混用。CI 必须按模块报告 collect count，并对每个必需文件断言 `>0` test cases。

### High

#### H-01：实时 Provider 正式装配未统一

Codex CLI 已进入 Chapter composition；OpenAI adapter 只存在于 D0 runner/测试；D0 Authority Worker 又只执行 fixture。Compose 默认 `development + mock`。Provider Registry 看似是扩展点，但 API/Worker 没有生产 factory 注入。

**影响：** “支持 OpenAI”与“正式 Chapter Runtime 可用 OpenAI”不是同一事实；readiness 也无法证明实际路由能构建并通过 qualification。

#### H-02：Readiness 可产生 Worker/Provider 假阳性

`/readiness` 只检查数据库、迁移、MinIO、非空 provider name 和 definition count；不检查 Worker heartbeat。Compose API healthcheck 正是 `/readiness`。`/runtime/readiness` 只要求“至少一个 worker 且所有已出现 worker 健康”，不检查 chapter/agent/content/source/mkaos/book/outbox/maintenance 必需集合。

**影响：** 只有一个新鲜 Worker 时整个 runtime 可返回 READY；任意非空 provider name 可被标为 CONFIGURED，即使 adapter 未装配、Pack 未通过或 real-provider qualification 为 false。

#### H-03：架构 manifest 把存在性误作生产可达性

`fitness-policy.yaml` 把 Story Planning、ChapterGroup、BookReplan 等未组合模块列入 production roots；`module-manifest.yaml` 只证明可导入和 authority_mode 声明；`production-entry-manifest.yaml` 又遗漏 Capability Pack、Content、Reader、Recap、ChapterGroup、Supervisor、Replan 等实际或目标入口。

**影响：** manifest PASS 不能回答“生产 Worker 是否能到达该能力”。当前 fitness 更接近 source-isolation policy，不是 composition reachability proof。

#### H-04：当前 SHA 没有成功的真实 Provider/长篇证明

本地 `.local/runtime-proof` 有 14 份 prior-commit final JSON，全部是 `novel-forge.short-longform-runtime-proof.failure.v1`；失败包括 retry exhausted、UNKNOWN effect、publish gate blocked、acceptance evidence blocked、ambiguous active input、snapshot mismatch、arc identity 和 token budget。它们证明系统确实执行过真实 Codex 阶段，也提供了有价值的失败证据，但没有一份成功闭环，且提交均早于当前 HEAD。

**尚未验证：** 不能据这些旧提交失败断言当前 HEAD 一定同样失败；只能断言当前 HEAD 没有成功、SHA-bound 的 real-provider/longform proof。

#### H-05：当前文档入口与当前代码直接冲突

根 `README.md`、`ARCHITECTURE.md`、`WORKFLOW.md`、`TESTING.md` 最后更新于 2026-07-30，仍把 Local JSON、Celery、Redis、Qdrant、可选 PostgreSQL 和旧 CLI 大命令面作为当前架构。`docs/architecture/overview.md` 更早，明确写 PostgreSQL“optional, partially integrated”。当前 Compose 已完全不同。

**影响：** 新开发者会从旧入口进入 Legacy mental model；运维可能启动不存在于 canonical compose 的服务；Provider 和完成度会被误读。

### Medium

#### M-01：Legacy 执行平面规模过大且清单覆盖不完整

下列旧模块仍保留约 18,552 行 Python：`agent_runs`、`agent_scheduler`、`workflow_nodes`、`loop_kernel`、`production_kernel`、`operation_transactions`、`operations`、`production_chain`。非 Authority router 约 8,487 行，Authority router 约 3,003 行。`legacy-surface-manifest.yaml` 没有逐项分类这些模块。

它们不构成正式状态旁路，但增加搜索噪声、命名冲突和误接线概率。应做 call graph 后删除、归档或移入明确 legacy namespace，而不是继续为两套模型补功能。

#### M-02：Runtime Job 与业务 Command Attempt 是双层可靠性模型

`RuntimeJobAuthority` 自己实现 job attempt、lease、fence、checkpoint、retry/dead-letter；Book Worker 再在 job 内调用 Book/Command Kernel。Operational job 与 business operation 可以合理分层，但目前适用规则不够窄，通用 authority/execution/integration/maintenance runtime-group console scripts 又扩大了表面积。

应明确：Runtime Job 只包装“无独立业务 Operation 的周期性维护/协调 tick”，不得复制业务结果、ExternalEffect 或 Chapter Attempt 状态；Book Supervisor 接线后重新评估 Book tick 是否仍需这一层。

#### M-03：Context/Knowledge 的目标合同与正式代码不一致

Authority Context 已真实接线并有来源隔离，但 Knowledge Pack 对 Draft 仍是 optional。旧 `context_builder/service.py` 又保留 LocalStorage/RAG/MKAOS 大型实现。

应选择并记录一个事实：若 Knowledge Pack 是所有生产模型调用的强制输入，就在 preparation/admission schema 中 fail closed；若它只对部分 action 必需，就修改文档和 Skill，不再泛化。

#### M-04：环境枚举存在双重语义

`IndustrialSettings` 只允许 `development/test/production`，而 Chapter builder、PEP 和 proof 使用 `validation/provider-validation` 作为 controlled environment。Proof 脚本只能通过绕开同一 settings 语义或组合不同环境值工作。

应建立单一环境枚举与 control-level 映射，避免 API readiness、provider policy 和 proof harness 对“生产约束”理解不同。

#### M-05：命名超过真实成熟度

`Book Production Supervisor`、`production-entry-manifest`、`D0 provider qualification worker`、`Autonomous Novel OS`、部分 “proof/current/complete” 文档名称都可能让人把 code existence、fixture recovery 或 proof harness 误读为 production runtime。

无需重命名全部代码，但 current-state 和 manifest 必须增加 `composition_root`、`deployment_unit`、`runtime_reachable`、`proof_level` 字段；未接线模块标为 `candidate` 或 `proof_harness_only`。

### Low

#### L-01：FastAPI 生命周期 API 已弃用

全量 pytest 报告 `authority_app.py:516,641` 的 `on_event("shutdown")` deprecation warning。应在 P2 收敛到 lifespan，不影响当前主链判断。

#### L-02：注释和兼容说明承担了过多架构约束

多个模块用 docstring/comment 声明“compatibility only”“production disabled”“PostgreSQL remains authority”，但 machine-readable legacy manifest、composition test 和 import boundary 没有完全覆盖。注释不能代替可执行边界；删除旧实现时也会造成历史说明滞留。

## 6. 模块成熟度

标记：`✓` 已由当前代码接线确认；`△` 部分/条件成立或本轮无法重跑真实集成；`✗` 不成立。这里的 `integration_proven` 要求当前 SHA 的正确 runner 与依赖环境，不复用旧 SHA 报告。

| 模块/能力 | code_exists | production_wired | runtime_reachable | authority_backed | worker_backed | integration_proven | real_provider_proven | longform_proven | production_verified |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PostgreSQL Authority + Command Kernel | ✓ | ✓ | ✓ | ✓ | ✓ | △ 本轮无 DB | ✗ | ✗ | ✗ |
| Chapter Saga Runtime | ✓ | ✓ | ✓ | ✓ | ✓ | △ 当前 Pack 红且无 DB | ✗ 当前 SHA | ✗ | ✗ |
| Book 手工协调/Chapter acceptance | ✓ | ✓ | ✓ | ✓ | ✓ | △ 本轮无 DB | ✗ | ✗ | ✗ |
| Book Production Supervisor | ✓ | ✗ | ✗ 正式路径 | ✓ 代码层 | ✗ | ✗ 主闭环测试漏跑 | ✗ | ✗ | ✗ |
| Story Planning Runtime | ✓ | ✗ | ✗ 正式路径 | ✓ 代码层 | ✗ | ✗ | ✗ | ✗ | ✗ |
| ChapterGroup Authority | ✓ | ✗ | ✗ 正式路径 | ✓ | ✗ | △ 独立测试存在 | ✗ | ✗ | ✗ |
| PlanChange / BookReplan | ✓ | ✗ | ✗ 正式路径 | ✓ 代码层 | ✗ | ✗ 主闭环测试漏跑 | ✗ | ✗ | ✗ |
| Reader Outcome / Longform Recap | ✓ | ✓ Book sidecar | ✓ 已有 accepted Chapter 后 | ✓ | ✓ Book Worker | △ 本轮无 DB | ✗ | ✗ | ✗ |
| Agent Candidate Runtime | ✓ | ✓ | ✓ | ✓ | ✓ Agent Worker | △ 本轮无 DB | ✗ 当前 SHA | ✗ | ✗ |
| Chapter-bound Agent Collaboration | ✓ | ✓ | ✓ | ✓ | ✓ Chapter Worker | △ 本轮无 DB | ✗ 当前 SHA | ✗ | ✗ |
| Capability Pack Authority/Binding | ✓ | ✓ | ✓ | ✓ | ✓ 运行时内联/Worker 消费 | ✗ 当前默认 Pack 合同失败 | ✗ | ✗ | ✗ |
| Authority Context Bundle | ✓ | ✓ | ✓ | ✓ AssetVersion | ✓ Chapter Worker | △ 本轮无 DB | ✗ | ✗ | ✗ |
| MKAOS/Knowledge Pack | ✓ | ✓ 独立 API/Worker | ✓ 独立链 | ✓ | ✓ | △ 本轮无 DB | ✗ | ✗ | ✗ |
| Codex CLI Chapter backend | ✓ | ✓ 条件配置 | ✓ 条件配置 | ✓ 执行证据 | ✓ Chapter Worker | △ prior-commit 实际运行过 | ✗ 当前 SHA 闭环 | ✗ | ✗ |
| OpenAI Remote Provider backend | ✓ | ✗ Chapter composition | ✗ 正式 Chapter | △ adapter 合同 | ✗ | △ adapter 单测 | ✗ | ✗ | ✗ |
| D0 Provider Qualification Authority | ✓ | ✗ 未进入 Compose/API | △ 显式 CLI/Worker，仅 fixture scheduler | ✓ | △ Worker 存在但未部署 | △ fixture recovery | ✗ | ✗ | ✗ |
| Legacy Local/Celery Runtime | ✓ | ✗ | △ 显式非生产入口 | ✗ 正式权威 | △ legacy worker | △ | ✗ | ✗ | ✗ |

关键说明：

- `real_provider_proven` 不是“曾发出过一次真实模型调用”；它要求当前 SHA、正式组合、真实 receipt/usage/cost、成功 Domain Commit 与 gate completion。
- `longform_proven` 不是“有 12 章脚本或生成了若干章”；它要求连续状态、Reader/Recap/Replan、恢复和 ending reachability 在同一正式链通过。
- `production_verified` 对所有模块仍为 false，符合 `analysis_outputs/status.json` 的历史非声明，也符合本轮当前证据。

## 7. AI 编程技术债

### 7.1 过度设计与重复抽象

- 133 个一级模块、61 个 router、12 个 worker manifest entry 对当前 8 个 Compose Worker 来说表面积过大。
- Story Planning、hierarchical planning、Book supervisor、Book replan、ChapterGroup、Book production checkpoint 已分别建模，但没有先形成唯一组合根。
- 旧 Agent Scheduler/Workflow/Loop/Production Kernel 与新 Command Kernel/Agent Runtime 并存，命名相近、状态模型不同。
- `RuntimeJobAuthority` 与业务 Command Kernel 都有 attempt/lease/fence/retry；边界只有约定，没有 architecture fitness 强制。

### 7.2 无效或未装配扩展点

- Provider Registry 支持 injected remote adapters，但正式 API/Worker 不注入 factory。
- 通用 runtime-group console scripts 被 manifest 标为 Worker，却不在 Compose 中部署，实际只是同一 maintenance loop 的别名入口。
- Book API 使用 `getattr` 探测未声明的 supervisor service，是“预留扩展点”替代正式 composition contract 的典型例子。
- production roots 中列出未组合模块，让 fitness PASS 成为存在性检查，而不是可达性检查。

### 7.3 Fixture/Compatibility 泄漏风险

正式 production policy 对 fixture 的 fail-close 边界总体良好，没有发现 silent fallback。但有三种认知泄漏：

- 默认 Compose 是 `development + mock`，却常被文档称为 production-style；
- D0 Authority Worker 名称像实时 qualification，实际 scheduler 固定 `execute_fixture`；
- 旧 README 把 Legacy CLI、Celery、Local JSON 与当前 Authority 命令混在同一使用说明中。

风险重点不是 fixture 静默进入 `production`，而是 fixture 证明被报告成 production proof。

### 7.4 历史兼容债务与可删除项

优先候选：

1. 删除或 archive `book_authority/application.py`、`book_authority/scheduler.py` 中明确 production-disabled 的旧 fixture protocol；保留 `production.py` + `governed_scheduler.py`，完成 call graph 后执行。
2. 对 `agent_runs`、`agent_scheduler`、`workflow_nodes`、`loop_kernel`、`production_kernel`、`operation_transactions`、`operations`、`production_chain` 做 import/call-site 分类；零 Authority consumer 的直接删除，其余迁入 `legacy` namespace 并设删除里程碑。
3. 删除未部署且无独特行为的 runtime-group alias entrypoint，保留具体 Worker。
4. 合并 `context_builder/service.py` 的仍需能力到 Authority domain/application；禁止继续维护 LocalStorage Context Builder 与 Authority Context Builder 两套业务规则。
5. 删除完全重复的 `docs/new/deep-research-report.md`；其内容与 `docs/deep-research-report.md` SHA1 完全一致。

### 7.5 过度注释与命名债

当前主要问题不是注释数量，而是注释承担运行政策。凡是“compatibility only”“fixture only”“does not own Attempt”“production disabled”的声明，应对应以下至少一种可执行约束：

- import/fitness boundary；
- environment fail-close；
- composition manifest classification；
- zero-production-call-site test；
- removal issue 与截止版本。

否则注释会在 AI 批量扩展中被复制，却无法阻止旁路重新出现。

## 8. 文档治理方案

### 8.1 当前问题

仓库有 413 个文档文件、195 份 reports、两套 architecture 目录、两套 operations/runbooks、多个 design/blueprint/plan/superpowers/new 层。`docs/README.md` 同时链接多个“current”报告，事实上建立了多个事实源。

文档治理原则：

```text
代码与当前 SHA 运行证据
  -> 当前系统状态
  -> Canonical Runtime / 模块边界
  -> ADR / 运维
  -> Roadmap

历史报告只提供 lineage，不再提供 current truth。
```

### 8.2 主要文档分类

| 文档/集合 | 动作 | 原因 |
|---|---|---|
| `AGENTS.md` | KEEP | 当前权限、Authority、版权与 rolling authority 边界准确，继续作为 agent policy |
| `docs/00-product/copyright-and-compliance.md` | KEEP | 长期合规事实；只需校验链接和术语 |
| `docs/09-skills/**` | KEEP | Skill 单一事实源与 runtime sync 规则仍有效 |
| `docs/adr/0002-*`、`0003-*`、`0004-*`、runtime/migration ADR | KEEP + REVIEW | ADR 应保留决策 lineage，但增加 current status、superseded-by 与 implementation evidence |
| `docs/adr/0001-stdlib-unittest-first.md` | REWRITE/SUPERSEDE | 前提已失效，并直接导致 pytest 测试漏跑；不能继续 Accepted |
| `README.md` | REWRITE | 只保留产品定位、当前真实拓扑、最小启动、事实文档索引；删除旧大 CLI/Legacy 能力清单 |
| `ARCHITECTURE.md` | MERGE + REWRITE | 合并进一个 `docs/architecture/core-architecture.md`；旧 Local JSON/Celery/Qdrant 默认架构过期 |
| `WORKFLOW.md` | MERGE + REWRITE | 改为 Canonical Chapter 与 Book state flow；旧 CLI pipeline 移入 Legacy 指南 |
| `TESTING.md` | MERGE + REWRITE | 与 `docs/quality/regression-tests.md` 合并；改用能实际 collect 全部测试的 runner |
| `docs/README.md` | REWRITE | 从多 current report 索引改为 6-8 个长期事实入口；不得把 reports 置于 current truth 链 |
| `docs/project-current-state.md` | REWRITE | 更新为本审计的 maturity 维度和当前 SHA；移除旧 Compose/迁移/证明数 |
| `docs/roadmap/current-roadmap.md` | REWRITE | 下一阶段改为 Runtime Convergence P0/P1/P2，不再按未收敛能力横向铺开 |
| `docs/01-architecture/**` + `docs/architecture/**` | MERGE | 合并成 core architecture、canonical runtime、module boundaries、provider/recovery 四份以内 |
| `docs/06-operations/**` + `docs/runbooks/**` | MERGE + REWRITE | 当前 runbook 仍写 Redis/queue，Compose runbook 固定迁移 0067；实际为 0073 |
| `architecture/manifests/**` | KEEP + REWRITE SCHEMA | 机器可读资产有价值，但要区分 source-owned、composition-wired、deployed、runtime-reachable |
| `docs/reports/**`（本报告除外） | ARCHIVE | 195 份阶段证据不得继续担任当前事实；保留 commit/date/gate/result 索引 |
| `docs/07-audits/**`、`docs/architecture-closure/**` | ARCHIVE | 历史收敛过程与审计 lineage，有价值但非当前事实 |
| `docs/design/**`、`docs/blueprint/**`、`docs/plans/**`、`docs/superpowers/**`、`docs/prompts/**` | ARCHIVE | 目标设计/提示/实施计划不等于当前系统；只把已接受决策提炼进 ADR |
| `docs/new/**` | ARCHIVE 后 DELETE 无引用内容 | 临时 AI 产物区不能长期存在；20 个 UI PNG 需绑定产品决策，否则删除 |
| `docs/new/deep-research-report.md` | DELETE | 与 `docs/deep-research-report.md` 完全重复 |
| `docs/reports/longform-12ch-pressure-acceptance.md` | ARCHIVE，改名标注 FAILED | 12/12 blocked，是失败证据，不是 longform acceptance proof |
| `analysis_outputs/status.json` | REWRITE 或 DELETE | 仍指向 2026-07-22 / `ac80c31` / 992 unit；`status=verified` 易被误读为当前系统 verified |

### 8.3 建议的最小长期文档树

```text
README.md
AGENTS.md
docs/
  current-system-status.md
  architecture/
    core-architecture.md
    canonical-runtime.md
    module-boundaries.md
    provider-and-recovery.md
  adr/
    ...accepted/superseded decisions...
  operations/
    startup-and-shutdown.md
    recovery-and-failure-drills.md
    provider-qualification.md
  quality/
    verification-matrix.md
  roadmap/
    current-roadmap.md
  archive/
    index.md
```

删除不应一次性丢失 lineage。先生成 archive index，记录原路径、commit/date、证据级别、replacement、是否含唯一决策；确认无唯一内容和无外链后再物理删除。

## 9. 下一阶段实施计划

### P0：Production Runtime Convergence（阻断新增功能）

#### WP-P0-1：恢复可信测试门禁

- 修复默认 Capability Pack 的 capability/timeout 单一事实源。
- 统一 pytest/unittest runner；全仓 collect count 固化到 CI。
- `test_core_functional_loops_postgres.py` 必须实际执行 6 个顶层测试，而不是“文件被 runner 列出”。
- 当前 22 个 pytest failure 清零。
- supersede ADR 0001，并更新 verification guide。

验收：当前 SHA 的 static、unit、architecture、acceptance 均由同一 runner 全量绿色；必需测试模块逐个报告非零 test count。

#### WP-P0-2：建立唯一 Book Production composition root

- 新建的不是新 Framework，而是把已有 `PostgresBookProductionSupervisor` 提升为唯一 application boundary。
- Authority API 和 Book Worker 注入同一个 Supervisor/application。
- 正式组合 StoryPlanning、ChapterGroup、Chapter、Reader、Recap、Checkpoint、PlanChange/Replan。
- 删除 API 的 `getattr` fallback；缺失依赖在启动时 fail closed，不在 tick 时才发现。
- 明确 `START_REPLAN` 的消费者：要么 Supervisor 自己 admission Replan Operation，要么提交一个现有 Command Kernel durable job；不得只返回枚举。

验收：从 API admission 一个 `RESOLVED_AUTHORITY_INPUT` Book 后，仅靠正式 Worker 即可完成 Planning → ChapterGroup → Chapter 1 → Reader → Recap → 触发/不触发 Replan → Chapter 2 admission；进程重启后继续。

#### WP-P0-3：使 readiness 与 composition 相符

- `/readiness` 校验默认 Capability Pack 可编译、实际 Provider route 可构建。
- `/runtime/readiness` 检查部署 profile 要求的完整 worker-kind 集合及 freshness。
- Compose API healthcheck 区分 API ready 与 whole-runtime ready，避免循环依赖。
- readiness 返回 `fixture_only`、`real_provider_qualified`、`longform_proven`，禁止用 provider 非空代替证明。

#### WP-P0-4：同一正式组合的 fixture vertical proof

- 测试不得自行手工组合只存在于 proof script 的 Supervisor。
- 通过 Authority API + 正式 Worker composition 运行最小两章 fixture。
- 覆盖 retry、lease takeover、UNKNOWN ExternalEffect、Canon gate、review rework、publish gate、invalidation 与 resume。

### P1：Provider、状态链与执行面收敛

#### WP-P1-1：统一 Provider factory

- 决定正式支持范围：若 OpenAI 是 production provider，就通过同一个 composition factory 注入 API/Chapter Worker/Agent Worker；否则明确标为 D0-only。
- 让 D0 Authority Worker 执行真实 adapter 或改名为 fixture protocol worker；不得保持模糊状态。
- Pack deployment 必须绑定 qualification snapshot、pricing、credential profile、model/effort 和 cost hard-stop。

验收：当前 SHA 的真实 Provider 单章成功，具有 provider receipt、measured usage、cost ledger、model_call_log、AssetVersion、gate result、恢复证据。

#### WP-P1-2：收敛双层 scheduler/recovery

- 为 Runtime Job Authority 写一页边界 ADR 和 architecture fitness rule。
- Book Supervisor 接线后判断 Runtime Job 是否仍需要；若只包装一个已有 durable Operation tick，应合并或删除。
- 删除未部署的 generic runtime-group aliases 与旧 Book fixture scheduler。

#### WP-P1-3：生产可达性 manifest

- 从 composition root/Compose 生成 deployment inventory。
- 每个 capability 标注 `code_exists / composed / deployed / reachable / authority / worker / proof_sha`。
- production entry manifest 覆盖 Capability Pack、Content、Reader、Recap、Supervisor/Replan，或明确标记 `not_wired`。

#### WP-P1-4：文档收敛迁移

- 重写最小长期文档树。
- 195 份 reports 移入 archive index，取消 current 链接。
- 删除精确重复和无引用临时产物。

### P2：真实长篇与生产验证

- 在当前 SHA、同一正式组合上完成 L3 → L10 → L30 分级 real-provider proof。
- 强制证明跨章 StoryState/Canon、Reader Outcome、Recap、Replan、Plan activation、ending reachability。
- 做 process kill、lease expiry、UNKNOWN effect、callback duplicate、MinIO/DB 短暂故障、PITR/restore 演练。
- 做多 Book 隔离、公平性、连接池/成本/延迟容量与安全验证。
- 完成浏览器 E2E 和运维 runbook drill。

只有 P0/P1 完成且 P2 最小 proof 通过后，才恢复新的能力开发。

## 10. 最终判断

### 当前 Novel Forge 到底是什么系统？

它是一个已经拥有真实 PostgreSQL Authority、Command Kernel、受控 ExternalEffect/Provider 边界、Agent Candidate 协作、单章 Saga、Canon/Quality/Publish Gate、Book acceptance 和 Reader/Recap sidecar 的本地优先 AI 小说生产后端。单章执行平面已经接近可维护的生产内核，PostgreSQL 在正式路径上保持唯一状态权威。

它同时也是一个尚在从“很多能力模块”收敛为“一个 Autonomous Novel OS runtime”的系统。完整整书自治能力目前主要存在于代码模块、集成 fixture 和 proof harness，而不是正式 API/Worker composition。当前 HEAD 的 Pack 合同和测试发现机制还使发布门禁不可信。

### 继续增加能力前必须先解决什么？

必须先解决四件事：

1. 让当前 Pack 与全量测试恢复绿色；
2. 让 CI 真正执行所有被声称为证明的测试；
3. 把已有 Book Supervisor/Planning/ChapterGroup/Replan 装入唯一正式组合，并让 API 与 Worker 共用；
4. 用同一正式组合完成当前 SHA 的 fixture vertical proof 和真实 Provider proof。

在此之前继续增加功能，会进一步扩大未装配模块、重复 scheduler、文档事实源和 fixture-proof 混淆。当前最有价值的工程工作不是再建一个 Manager、Registry、Authority 或 Agent，而是删除、合并、接线、验证并明确唯一生产路径。
