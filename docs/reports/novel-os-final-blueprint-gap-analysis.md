# Novel OS 最终蓝图差距分析报告

> 审计日期：2026-07-11
> 审计分支：`feat/v7-content-intelligence-and-longform-proof`
> 审计基线：`f66ebb7`（工作区另有用户未提交改动，本报告未将其回退或当作已发布能力）
> 目标基线：`docs/blueprint/autonomous-novel-os-full-blueprint.md`、`docs/blueprint/novel-os-project-blueprint.md`

## 1. 执行摘要

当前代码库已经超出“一次性小说 Prompt 工具”的范围，具备一个本地优先、Schema 驱动、可追踪的早期 Novel OS 运行时。已形成的真实基础包括：JSON 资产与版本、PostgreSQL 投影、MKAOS、来源治理、统一 Context Builder、模型路由与调用账本、ReviewIssue、章节生产总线、受限 Agent 执行器、发布门禁、反馈导入及较广的 Web 控制台。

但系统还不能被认定为最终蓝图中的 Autonomous Novel OS。核心原因不是“代码数量不足”，而是以下闭环尚未成立：

1. 同一业务存在旧 Pipeline、Workflow Runtime、Chapter Production Bus、Agent Scheduler 多个执行平面，尚无唯一生产内核。
2. 10 章验收只证明 16 类资产覆盖；实际导出章节正文除标题外完全相同，未证明故事推进、人物变化或长篇质量。
3. Topic、World、Character 等前置生产能力仍含固定示例或固定字段，创意孵化、主题意义、结局、连载策略等蓝图引擎缺失。
4. Canon/Character/Arc/Foreshadow 数据类型广，但大量状态抽取和判断仍依赖关键词、正则、摘要或固定示例，没有形成可信的长篇状态归约器。
5. Agent Runtime 已是较强的有界任务执行器，但没有持续目标分解、动态计划和跨 Agent 策略闭环，属于 A2 级执行自动化而非 A3/A4 自治。
6. Eval、原创性、AI 味和质量评分主要是规则/关键词启发式；没有提交的生产 Golden Dataset、真实 Provider 校准和长期人工标注证据。
7. UI 页面广，但 Source Center、Portfolio、Canon/Character/Arc 等核心页面的治理深度不足；部分页面是通用 JSON 编辑器或共用页面。
8. 发布适配器有两套路径，真实平台协议和审批边界未统一；反馈学习的置信度、污染隔离与因果归因不足。
9. 当前工作区验证存在 3 个未绑定项目的运行资产；Python 全量回归不是绿色基线，增强后的来源/质量门禁已使若干旧调用方和夹具失败。
10. API 缺少用户身份认证、RBAC、生产级限流和 Secrets 管理；备份未覆盖 PostgreSQL、MinIO、Qdrant 的自动演练。

按本报告定义的最终蓝图口径，综合成熟度为 **45/100（不确定区间约 +/-5）**。历史报告中的 86% 左右更多衡量既定切片和资产覆盖，不能等价为最终产品成熟度。

**当前可以稳定完成的事项**：在本地/Mock 或受控 Provider 下创建 Schema 资产，执行单章有界任务，构建隔离上下文，记录模型调用、成本和 Trace，生成审稿问题及修订资产，运行来源、质量和发布门禁，并由操作员查看和恢复部分执行状态。

**当前尚不能稳定完成的事项**：从创意发现开始自动生成一部内容持续推进、人物与 Canon 可信、质量经真实标注校准、可发布且可根据真实读者反馈优化的精品长篇；也不能证明三本以上作品的资源隔离和并行生产。

## 2. 审计范围与方法

### 2.1 范围

审计覆盖以下实际边界：

- 两份最终蓝图和当前路线图、历史报告；
- `src/novel_forge/` 下的 Schema、存储、服务、API、Workflow、Agent、模型、MKAOS、来源治理、章节生产、长篇稳定性、质量、反馈、发布和运维模块；
- `web/admin/` 下的 72 个 Next.js 页面路由及 API 客户端；
- 数据库迁移、Docker Compose、环境配置、Makefile、备份/恢复及 CI；
- `tests/` 下的 Unit、Integration、Acceptance 和 Web 静态/浏览器测试；
- 当前 `.local/workspace` 的可验证运行资产及已提交验收报告。

### 2.2 Evidence-first 判定流程

每项需求按以下链路检查：

```text
Schema/领域模型 -> 服务逻辑 -> 生产调用入口 -> 状态机 -> 持久化
-> Context/模型边界 -> 校验与门禁 -> 错误恢复 -> Trace/成本 -> 测试 -> UI
```

仅有 README、规划、Prompt、空类、单一页面、孤立 API、Mock 或测试夹具，不作为“完整实现”证据。实际分类同时使用成熟度 `L0-L5` 和状态：`complete`、`partial`、`skeleton`、`missing`、`divergent`、`blocked`、`evidence-insufficient`。

本报告中的“已实现”仅说明在审计环境中找到了调用链或可重复测试；没有真实生产流量、真实平台、真实付费 Provider 或百万字运行证据的能力不会评为 L5。

### 2.3 实际执行的检查

已执行项目事实基线命令、全库文件/符号搜索、核心调用链阅读，并进行以下验证：

| 检查 | 结果 | 说明 |
|---|---|---|
| `make lint` | 通过 | Python 静态/格式检查基线可用 |
| `npm --prefix web/admin test` | 11 通过、0 失败、1 跳过 | Playwright 未安装，浏览器 E2E 被跳过；其余主要为静态架构检查 |
| `make check-skills` | 通过 | Root Skill 与运行时副本无漂移 |
| 临时空工作区 `validate` | 通过 | Schema/存储能在干净根目录初始化 |
| 当前 `.local/workspace` `validate` | 失败 | 3 个运行资产无 `project_id`/`workspace_path` |
| `make test` | 未完成全量绿色运行 | 初次运行出现多处错误/失败；随后以 fail-fast/聚焦测试定位 |
| 来源/Context 聚焦测试 | 18 个中 1 个错误 | 新来源治理门禁阻断旧夹具，报告 3 条 blocking rows |
| MKAOS/Review 聚焦测试 | 10 个中 1 个错误 | `project_metric_snapshot` 缺必填 `project_id` |
| Provider Runtime Guard 聚焦测试 | 10 个通过 | 硬停、预算、Provider 治理的局部契约成立 |
| 12 章压力测试首个失败 | 失败 | 发布包被 2 条 protagonist agency ReviewIssue 阻断 |
| V1 章节序列单测 | 失败 | 预期 `succeeded`，实际 `failed` |
| `git diff --check`（写报告前） | 通过 | 已有工作区改动无空白错误 |

因此，当前不能引用历史“全部测试通过”作为本分支的发布证据。失败中的一部分是 fail-closed 门禁增强后旧夹具未迁移，但这仍然属于集成缺陷，而非可以忽略的测试噪声。

## 3. 当前工程事实基线

### 3.1 规模和技术栈

- Python 源文件 378 个，约 93 个业务模块目录；`BaseAsset` 子类 289 个。
- Product API 路由处理器约 705 个；Python 测试文件 177 个、测试方法约 779 个。
- Web Admin 有 72 个页面路由、141 个 TypeScript/TSX 应用文件。
- 核心为 Python 3.11 模块化单体；FastAPI、PostgreSQL/pgvector、Redis/Celery、Qdrant、MinIO、Neo4j、ClickHouse 均为可选或部署组件。
- Next.js Web Admin 是当前主要人工控制界面。

代码规模不等于成熟度。若干超大服务表明边界正在形成但尚未收敛，例如 `src/novel_forge/modules/mkaos/service.py`、`src/novel_forge/modules/workflow_nodes/service.py`、`src/novel_forge/api/services/product.py`、`src/novel_forge/modules/agent_scheduler/service.py` 和 `src/novel_forge/modules/context_builder/service.py`。

### 3.2 当前持久化事实

- `LocalStorage` 的版本化 JSON 资产仍是默认本地权威数据；PostgreSQL 主要是可选 write-through/index 投影。
- `schemas/assets.py` 中大量类型只是声明 `type` 的空 dataclass；业务必填字段集中在 `schemas/base.py::CONTENT_REQUIRED_FIELDS` 和大段条件校验。
- 已有 `nf_assets`、版本、任务、项目、MKAOS 规范化表和 ReviewIssue 表等迁移。
- 资产系统具备项目写入守卫，但允许部分无项目资产；当前工作区已有 3 个不符合隔离要求的运行资产。
- Qdrant、MinIO、Neo4j 不是所有关键路径的强依赖，生产一致性和恢复契约没有端到端证明。

### 3.3 当前真实产品切片

最完整的切片是“受控单章生产”：章节计划 -> 稳定性预检 -> ContextBundle -> 草稿 -> 审稿 -> 修订 -> 质量修复 -> Canon/Longform 回写 -> 本地导出 -> 下一章计划。对应 `modules/chapter_production_bus/service.py`。

但已提交的 10 章慢验收报告 `docs/reports/v1-chapter-sequence-slow-acceptance.md` 仅证明每章 16 类输出资产齐全。对 `.local/v1-chapter-sequence-acceptance-run3` 的正文进行比较后，章节 1 与章节 10 除标题外完全一致，每个导出正文仅约 20 个 `wc -w` 词项。该运行新增约 7,615 个资产，单章耗时从 22.6 秒增长到 306.9 秒。它是有效的“资产覆盖/恢复链”证据，不是“长篇小说内容”证据。

## 4. 两份蓝图的统一目标模型

两份蓝图没有发现必须二选一的根本冲突。`autonomous-novel-os-full-blueprint.md` 定义产品与 OS 能力全景，`novel-os-project-blueprint.md` 补充分期交付、UI、并行作品和规模验收。统一模型如下：

```text
战略与作品组合层
  -> 创意发现、立项、平台与商业目标、Portfolio
知识与证据层
  -> Source/Evidence -> Analysis -> MKAOS -> Production Asset
创作领域层
  -> Theme/Meaning -> World -> Character -> Outline/Arc -> Chapter -> Ending
运行控制层
  -> OS Envelope -> Workflow/Task -> Agent Harness -> Provider -> Artifact
长篇状态层
  -> Canon/Timeline/Character/Arc/Foreshadow/Promise/Reward/Villain
质量治理层
  -> ReviewIssue -> Revision -> Eval/Golden/Human Gate -> Release Gate
反馈与平台层
  -> Platform Adapter -> Publish/Receipt/Rollback -> Feedback -> Governed Learning
人工控制与运营层
  -> Workbench/Approval/Trace/Cost/Recovery/Security/DR/Multi-project
```

统一需求按十一类编号：愿景与产品、数据协议、来源、MKAOS、Context、创意、世界与人物、结构与生产、长篇稳定性、质量与 Agent、反馈发布与平台、UI 与工程运行。重复命名已合并；不同粒度的描述保留为子需求。

## 5. 当前系统架构全貌

### 5.1 已形成的模块

| 平面 | 主要实现 | 当前性质 |
|---|---|---|
| 资产/协议 | `schemas/`、`storage/local.py`、`storage/postgres.py` | 类型数量广，字段协议仍偏通用 JSON |
| 知识/来源 | `source_intake/`、`analysis/`、`mkaos*/` | 覆盖较深，生产治理和调用迁移尚未完全统一 |
| 上下文 | `context_builder/service.py` | 当前最接近 OS 级共享能力的模块 |
| 创作 | `topics/`、`worldbuilding/`、`characters/`、`outline/`、`drafting/` | 大纲/草稿较真；前置模块仍含固定样例 |
| 章节生产 | `chapter_production_bus/`、`content_quality_loop/` | 单章闭环较完整，但内容质量和规模证据不足 |
| 长篇状态 | `longform_stability/`、`canon_graph/`、`long_chain_proof/` | 模型广，推理/抽取和真实长链验证浅 |
| Agent/Harness | `agent_runs/`、`agent_scheduler/`、`operation_transactions/` | 有界执行、恢复、门禁较强；自治规划缺失 |
| 质量/Eval | `review_issue/`、`quality_eval/`、`evaluation_center/` | 资产与门禁存在，校准和真实数据不足 |
| 发布/反馈 | `publishing/`、`publishing_feedback_adapters/`、`feedback/` | 本地闭环与模拟适配存在，生产适配分裂 |
| Portfolio/UI/Ops | `portfolio_os/`、`web/admin/`、`operations/` | 展示覆盖广，实际多书调度、权限和 DR 不足 |

### 5.2 当前关键调用链

存在四条有重叠的执行路径：

1. `workflows/pipeline.py`：早期顺序式生产链，仍可由 CLI/Celery 使用。
2. Workflow Runtime：有节点、运行记录和策略，但 V1 模板主要把 Chapter Bus 包成单节点。
3. `chapter_production_bus/service.py`：当前最完整的章节级业务编排。
4. Agent Scheduler：通过 Operation Registry 调用本地业务服务，处理租约、重试、死信和恢复。

这四者没有明确的单一权威状态机。能力可能在某条路径上存在，而在另一条路径上绕过 Context、Envelope、审批或回写；这也是历史报告与实际验收不一致的主要结构性原因。

## 6. 蓝图需求追踪矩阵

成熟度含义：L0 未实现；L1 仅概念/文档；L2 骨架；L3 局部可用；L4 已接入主流程且有状态、持久化、错误处理和基本测试；L5 生产成熟。本审计没有发现足以评为 L5 的能力。

为控制表格宽度，代码证据中的 `modules/`、`storage/`、`api/`、`workflows/` 和 `model_adapters/` 均相对于 `src/novel_forge/`；未缩写的 `web/`、`tests/`、`docs/`、`.github/` 和 `.local/` 均相对于仓库根目录。

| Requirement ID | 层级 | 蓝图要求 | 当前实现 | 代码证据 | 成熟度 | 状态 | 主要差距 | 风险 |
|---|---|---|---|---|---|---|---|---|
| NOS-VISION-001 | 产品 | 本地优先的小说生产 OS，而非单次生成器 | 版本化资产、任务、工作流、Agent 和 Web 控制台已存在 | `storage/local.py`; `modules/chapter_production_bus/service.py`; `web/admin/app/production/page.tsx` | L3 | partial | 多执行平面和最终内容验收未统一 | 高 |
| NOS-VISION-002 | 产品 | 从创意到发布反馈的全生命周期 | 有旧 Pipeline、章节总线、发布和反馈模块 | `workflows/pipeline.py`; `modules/publishing/service.py`; `modules/feedback/service.py` | L3 | partial | 创意立项、真实发布、反馈学习未形成同一闭环 | 严重 |
| NOS-VISION-003 | OS | 自治、可恢复、可审计的长期运行 | 有 AgentRun、Scheduler、Checkpoint、Gate、Trace | `modules/agent_runs/service.py`; `modules/agent_scheduler/service.py` | L3 | partial | 无持续目标规划/周期控制器/生产规模证明 | 严重 |
| NOS-VISION-004 | 产品 | 以作品质量和商业结果为最终结果 | 有规则质量分、平台字段和反馈指标 | `modules/content_quality_loop/service.py`; `modules/platform_strategy/service.py`; `modules/feedback/service.py` | L2 | skeleton | 当前验收以资产覆盖为主，缺内容与商业结果校准 | 严重 |
| NOS-DATA-001 | 数据 | Asset/Artifact/Evidence/Task/Workflow 核心对象统一 | BaseAsset 和多类资产已建立 | `schemas/base.py::BaseAsset`; `schemas/assets.py` | L3 | partial | 289 类多数为空 dataclass，必填字段集中式分支校验 | 高 |
| NOS-DATA-002 | 数据 | 强类型领域模型和明确状态转换 | 部分服务有状态枚举/转换 | `modules/agent_runs/service.py`; `modules/review_issue/service.py`; `modules/mkaos/lifecycle.py` | L3 | partial | 跨模块状态词和字段仍不一致；通用 `content` 承载过多 | 高 |
| NOS-DATA-003 | OS | 所有执行使用统一 OS Envelope | 有 Envelope 规范化/门禁和多处引用 | `modules/os_envelope/service.py`; `tests/unit/test_mkaos_os_envelope.py` | L3 | partial | 不是独立持久化一等对象；旧 Pipeline/部分 API 未强制 | 严重 |
| NOS-DATA-004 | 数据 | 项目/工作区/小说隔离 | LocalStorage 有写入守卫和项目字段 | `storage/local.py`; `tests/unit/test_mkaos_isolation.py` | L2 | blocked | 当前工作区有 3 个无项目运行资产；多书并发未验收 | 严重 |
| NOS-DATA-005 | 数据 | 唯一数据权威、版本、迁移与兼容 | JSON 有版本；Postgres 有迁移/投影 | `storage/local.py`; `storage/postgres.py`; `storage/migrations/` | L3 | divergent | 本地/工业模式的权威边界和双写失败策略不清晰 | 高 |
| NOS-DATA-006 | 数据 | 统一 ReviewIssue/RevisionTask 协议 | ReviewIssue 服务、迁移和阻断语义真实存在 | `modules/review_issue/service.py`; `storage/migrations/versions/v20260703_0004_review_issue.py` | L4 | partial | 部分审稿器仍产生临时 dict，生产者未全部迁移 | 中 |
| NOS-SOURCE-001 | 知识 | SourceDocument、快照、清洗、分块、权利元数据 | 来源摄取、快照、分块和 rights 模块已存在 | `modules/source_intake/service.py`; `modules/mkaos_ingestion/source_rights.py` | L3 | partial | 外部连接器覆盖和真实语料规模证据不足 | 高 |
| NOS-SOURCE-002 | 安全 | 原始 Evidence 与生产资产物理/逻辑隔离 | Context 禁止原文类型；MKAOS 有 lineage/risk | `modules/context_builder/service.py::BASE_FORBIDDEN_CONTEXT_TYPES`; `modules/mkaos_lineage/service.py` | L4 | partial | 所有旧调用方未证明强制经过 Context Builder | 严重 |
| NOS-SOURCE-003 | 安全 | 版权、许可、来源风险和使用资格治理 | SourcePolicy、LicenseCheck、Risk、Eligibility 已实现 | `modules/source_intake/service.py`; `modules/mkaos_quality/source_risk_gate.py` | L3 | partial | 来源注册多为手工/固定元数据，缺法律策略版本和真实审计样本 | 高 |
| NOS-SOURCE-004 | 安全 | 引用 Span、证据链、置信度与可追溯抽取 | EvidenceSpan、候选、lineage、置信度存在 | `modules/mkaos_model_extraction/`; `tests/unit/test_mkaos_evidence_span.py` | L3 | partial | 真实 Provider 抽取准确率、跨格式 span 稳定性未校准 | 高 |
| NOS-SOURCE-005 | 安全 | 反照抄抽象和原文泄漏检测 | quote/source leakage、near duplicate 和上下文负例存在 | `modules/mkaos_quality/quote_leakage_detector.py`; `tests/unit/test_mkaos_source_leakage_regression.py` | L3 | partial | 启发式检测为主，缺外部语料回归集和真实正文验证 | 严重 |
| NOS-SOURCE-006 | 工作流 | Source 变更、失效、修复、回滚和再生成 | 有 diff repair、stale/quarantine sweep、审批应用和回滚 | `modules/source_intake/diff_repair.py`; `modules/source_intake/stale_sweep.py` | L3 | partial | 连接器实际执行和下游再生成仍多为计划/证据资产 | 高 |
| NOS-SOURCE-007 | 平台 | 本地/网络连接器可控执行 | 本地沙箱、allowlist、审批存在；网络主动阻断 | `modules/source_intake/connector_runner.py`; `connector_adapters.py` | L2 | skeleton | 无受控网络获取实现、速率/凭据/内容签名闭环 | 中 |
| NOS-SOURCE-008 | 工作流 | 来源治理在所有生产入口 fail-closed | Context、Workflow、Scheduler 已增加 runtime gate | `modules/source_intake/runtime_gate.py`; `modules/context_builder/service.py` | L3 | blocked | 现有 Context/Scheduler/章节测试被 3 条旧数据阻断，迁移未完成 | 严重 |
| NOS-ANALYSIS-001 | 领域 | 网文、出版、经典、商业机制多层拆解 | 多种分析报告和语义 rubric 存在 | `modules/analysis/service.py`; `schemas/assets.py` analysis types | L3 | partial | 真实语料的准确性、跨作品对照和人工校准不足 | 中 |
| NOS-ANALYSIS-002 | 知识 | 分析转知识、素材、模板、审稿规则 | 有转换服务和多种 converter | `modules/mkaos_converters/`; `modules/creative_assets/service.py` | L3 | partial | 转换质量/去重/审批未形成统一批处理闭环 | 高 |
| NOS-ANALYSIS-003 | 安全 | 分析结果保持抽象且不得进入正文 | Context profile 排除 analysis/decomposition；风险门禁存在 | `modules/context_builder/service.py`; `modules/mkaos_quality/service.py` | L4 | partial | 旧 Pipeline 和手工资产选择未全部证明受控 | 高 |
| NOS-MKAOS-001 | 知识 | 多学科知识资产 OS | 知识卡、规则、模板、Pack、图谱和 API/UI 较广 | `modules/mkaos/service.py`; `web/admin/app/mkaos/` | L3 | partial | 单体服务过大，生产规模和质量校准不足 | 高 |
| NOS-MKAOS-002 | 数据 | Raw Evidence -> Candidate -> Approved Knowledge 生命周期 | 候选审批、激活、隔离、弃用和回滚存在 | `modules/mkaos/lifecycle.py`; model extraction modules | L3 | partial | 部分历史卡未统一走候选和审批链 | 高 |
| NOS-MKAOS-003 | 知识 | 去重、冲突、质量和可创作用性评估 | near duplicate、conflict、quality、creative usability gate 存在 | `modules/mkaos_quality/`; `modules/mkaos/quality.py` | L3 | partial | 阈值启发式，缺 Golden/人工一致性和生产漂移监控 | 高 |
| NOS-MKAOS-004 | 知识 | 图谱、lineage、版本、影响分析 | KG、lineage、diff、impact、usage 都有资产/服务 | `modules/mkaos_lineage/service.py`; `modules/mkaos/service.py` | L3 | partial | 图谱推理深度和大规模存储一致性未证明 | 中 |
| NOS-MKAOS-005 | 工作流 | MKAOS 自动选择并进入 Context Builder | Selector、Pack、Context 自动接入和 fail-closed 门禁存在 | `modules/mkaos/selector_governance.py`; `modules/context_builder/service.py` | L4 | partial | 部分阶段/旧路径仍可绕过；现有回归因治理门禁失败 | 严重 |
| NOS-MKAOS-006 | 质量 | 使用效果、反馈归因、权重演化 | Usage、impact、feedback attribution、weight governance 存在 | `modules/mkaos/service.py`; `tests/unit/test_mkaos_feedback_attribution.py` | L3 | partial | 相关性/因果性弱，自动应用多为 metadata 和人工审批 | 高 |
| NOS-MKAOS-007 | 安全 | Pack 来源风险和生产准入门禁 | Pack policy、production gate、source risk gate 存在 | `modules/mkaos/pack_policy.py`; `modules/mkaos_production_gate/service.py` | L3 | partial | 生产数据、误杀漏检和回滚阈值未验证 | 高 |
| NOS-MKAOS-008 | UI | 可治理的知识资产工作台 | 导入、抽取、审核、质量、lineage、KG 页面存在 | `web/admin/app/mkaos/` | L3 | partial | 图谱预览截断，批量治理/差异/冲突处理深度不足 | 中 |
| NOS-CONTEXT-001 | OS | 所有生产上下文由统一 Context Builder 构建 | 计划、Bundle、stage profile、实际发送上下文已实现 | `modules/context_builder/service.py` | L4 | partial | 旧 Pipeline/少数手工调用未证明强制迁移 | 严重 |
| NOS-CONTEXT-002 | 安全 | Context Source Isolation 和泄漏硬停 | 禁止 raw/source/cleaned/decomposition/analysis 等类型 | `context_builder/service.py::BASE_FORBIDDEN_CONTEXT_TYPES` | L4 | partial | 仍需真实 corpus 负例和发布前全文泄漏验证 | 严重 |
| NOS-CONTEXT-003 | 数据 | Canon/Arc/Foreshadow/Character/World/Style 分层上下文 | 多 stage profile、优先级和预算选择存在 | `context_builder/service.py::_stage_profiles` | L3 | partial | 状态来源本身质量不足，部分层只是摘要/通用资产 | 高 |
| NOS-CONTEXT-004 | 运行 | Token 预算、压缩、截断、超限阻断 | 预算、rank、compress、warning/fail-closed 存在 | `modules/context_builder/service.py` | L4 | partial | 真实模型 tokenizer 和长链成本/命中率校准不足 | 中 |
| NOS-CONTEXT-005 | 可观察性 | 记录 Actual Sent Context、digest、Replay、Diff | 相关资产和服务/API 已存在 | `modules/context_builder/service.py`; `api/routers/context_builder.py` | L4 | partial | 生产级隐私遮蔽、长期保留和可视 diff 深度不足 | 中 |
| NOS-CONTEXT-006 | 知识 | RAG、KG、结构化状态混合检索 | Qdrant/向量、KG 和结构化资产可进入选择 | `modules/context_builder/service.py`; `modules/canon_graph/service.py` | L3 | partial | 可选后端一致性、召回评测和降级策略未规模验证 | 高 |
| NOS-CONTEXT-007 | 工作流 | 上下文失效、缓存和依赖回放 | 有 bundle ref、replay、invalidation/impact 资产 | `modules/context_builder/service.py`; `modules/change_impact/service.py::mark_downstream_assets_stale` | L3 | partial | 缺统一内容寻址缓存和状态变更后的自动失效协议 | 高 |
| NOS-CONTEXT-008 | UI | 操作员可查看选择理由、预算、发送内容和阻断项 | Context 页面/API 已连通 | `web/admin/app/context/page.tsx`; `api/routers/context_builder.py` | L3 | partial | 缺对 Canon 事实/证据的深度编辑与重新构建控制 | 中 |
| NOS-IDEA-001 | 产品 | 输入平台、受众、题材、篇幅和商业目标 | PlatformProfile/策略、项目目标字段分散存在 | `modules/platform_strategy/service.py`; `modules/project_operations/service.py` | L2 | partial | 缺统一 CreativeBrief/ProjectGoal 作为立项输入契约 | 高 |
| NOS-IDEA-002 | Agent | 题材发现、创意候选批量生成 | Topic 服务能调用模型并写 topic | `modules/topics/service.py::create_topic` | L2 | skeleton | 无候选池、批量探索和来源/市场证据；写入内容部分固定 | 严重 |
| NOS-IDEA-003 | 领域 | 创意聚类、去重、新颖性和原创风险 | MKAOS 有 near-duplicate，质量模块有相似度启发式 | `modules/mkaos_quality/near_duplicate_detector.py`; `modules/quality_eval/service.py` | L1 | missing | 没有 ConceptCandidate 聚类/新颖性服务和立项调用链 | 高 |
| NOS-IDEA-004 | 产品 | 市场适配、风险、潜力和多维评分 | 平台策略、Portfolio 潜力分数存在 | `modules/platform_strategy/service.py`; `modules/portfolio_os/service.py` | L2 | partial | 评分不是创意候选门禁，数据来源/校准不明确 | 高 |
| NOS-IDEA-005 | 治理 | 人工审批的立项门禁和可追踪决策 | ApprovalRequest 通用资产存在 | `schemas/assets.py::ApprovalRequest`; `modules/permission_center/service.py` | L2 | skeleton | 未接 Topic 候选排序和项目创建事务 | 严重 |
| NOS-IDEA-006 | 产品 | 从获批创意生成完整项目蓝图 | 大纲/世界/人物服务可分别运行 | `modules/outline/service.py`; `modules/worldbuilding/service.py`; `modules/characters/service.py` | L2 | skeleton | 无统一 ProjectBlueprint 生成、版本、审批和依赖关系 | 严重 |
| NOS-THEME-001 | 领域 | Theme/Meaning/哲学/价值冲突引擎 | 分析和大纲字段中出现 theme/value | `modules/analysis/service.py`; `modules/outline/service.py` | L1 | missing | 没有一等 Theme/Meaning 模型、演化状态或章节兑现检查 | 高 |
| NOS-WORLD-001 | 领域 | 世界规则、力量体系、地理、历史、社会、经济和组织 | WorldBible 类型与服务存在 | `schemas/assets.py`; `modules/worldbuilding/service.py` | L2 | skeleton | 服务写入固定 “Echo Clock City” 样例，缺目标驱动生成 | 严重 |
| NOS-WORLD-002 | 领域 | 规则约束、冲突检测和变化影响 | Canon/continuity graph 有事实和冲突检查 | `modules/canon_graph/service.py`; `modules/continuity_graph/service.py` | L3 | partial | 规则语义和变更影响多为通用图/关键词，未贯通世界编辑 | 高 |
| NOS-WORLD-003 | 数据 | 世界实体、关系、资源、制度可结构化查询 | KG/WorldBible content 可表达 | `modules/novel_kg/service.py`; `schemas/assets.py::WorldBible` | L2 | partial | 缺稳定的 WorldEntity/Rule typed schema 和时间有效性 | 高 |
| NOS-WORLD-004 | UI | World 控制台可编辑、校验和查看影响 | 有通用资产/编辑页面，没有独立深度 World route | `web/admin/app/assets/page.tsx`; `web/admin/app/features/` | L2 | skeleton | 不能以关系、规则和时间线方式治理世界状态 | 中 |
| NOS-CHAR-001 | 领域 | 角色档案、欲望、恐惧、缺陷、秘密和成长弧 | CharacterCard 类型与服务存在 | `schemas/assets.py`; `modules/characters/service.py` | L2 | skeleton | 默认写入固定 “Lin Qiao” 样例；字段和生成未形成真实链 | 严重 |
| NOS-CHAR-002 | 领域 | 人物关系、主角机制、配角功能 | Character/relationship 内容和角色压力模块有部分规则 | `modules/characters/service.py`; `modules/character_pressure/service.py` | L2 | partial | 没有统一关系状态、功能约束和随章节演化模型 | 高 |
| NOS-CHAR-003 | 领域 | 反派压力系统 | `character_pressure` 可评分 protagonist/villain pressure | `modules/character_pressure/service.py` | L3 | partial | 主要是规则评分，未成为反派目标/资源/行动状态机 | 高 |
| NOS-CHAR-004 | 长篇 | 角色状态机和一致性约束 | CharacterStateLedger、Canon 检查和 drift issue 存在 | `modules/longform_stability/service.py`; `modules/longform_recap/service.py` | L3 | partial | 抽取启发式、状态事件弱，缺人工校准的角色漂移评测 | 严重 |
| NOS-CHAR-005 | UI | Character 控制台支持关系、状态、弧和冲突治理 | Character console 为通用 EditableAssetConsole | `web/admin/app/character-console/page.tsx`; `web/admin/app/features/os/EditableAssetConsolePage.tsx` | L2 | skeleton | 缺关系图、状态历史、冲突合并和影响预览 | 中 |
| NOS-OUTLINE-001 | 领域 | 长篇/卷级大纲和故事弧 | Outline 服务真实调用模型，LongPlanning/Arc 类型存在 | `modules/outline/service.py`; `modules/long_planning/service.py` | L3 | partial | 上游世界/人物不真实，卷级状态与章节进度同步不足 | 高 |
| NOS-OUTLINE-002 | 领域 | 节拍、细纲、场景目标/冲突/反转 | ChapterPlan 有 scene beats、conflict、reversal、hook 等契约 | `modules/chapter_plan/service.py`; `schemas/base.py` validators | L4 | partial | 真实输出质量和长链差异化尚未证明 | 高 |
| NOS-OUTLINE-003 | 长篇 | 伏笔设计和回收计划 | Foreshadow ledger/console/生命周期检查存在 | `modules/longform_stability/service.py`; `web/admin/app/foreshadowing-console/page.tsx` | L3 | partial | 自动抽取和回收匹配依赖关键词/显式字段，长篇证据不足 | 高 |
| NOS-OUTLINE-004 | 领域 | 爽点、悬念、情绪曲线和读者承诺 | ChapterPlan、reader promise、chapter economy 模块存在 | `modules/reader_promise/service.py`; `modules/chapter_economy/service.py` | L3 | partial | 主要为规则/字段覆盖，未由真实读者数据校准 | 高 |
| NOS-OUTLINE-005 | 领域 | Ending/Closure 设计与前置回收 | 未找到一等 Ending/Closure 引擎 | 蓝图存在；代码搜索仅见通用 ending 文本字段 | L0 | missing | 无结局模型、收束检查、主题/角色弧/伏笔回收门禁 | 严重 |
| NOS-PROD-001 | 工作流 | 从项目到章节发布的唯一生产主流程 | 旧 Pipeline、Workflow、Chapter Bus、Scheduler 并存 | `workflows/pipeline.py`; `modules/chapter_production_bus/service.py`; `modules/agent_scheduler/service.py` | L3 | divergent | 无唯一权威编排、状态机和门禁入口 | 严重 |
| NOS-PROD-002 | 工作流 | 章节任务生成和依赖检查 | ChapterPlan、AgentTask、next chapter plan 均可生成 | `modules/chapter_plan/service.py`; `modules/chapter_production_bus/service.py` | L3 | partial | 任务、Workflow Node、AgentTask 三套状态未统一 | 高 |
| NOS-PROD-003 | Agent | Prompt/Skill 选择、版本和输入输出协议 | Prompt registry、27 Agent profiles、Skill map 存在 | `modules/prompt_registry/service.py`; `modules/agent_registry/service.py`; `docs/09-skills/agent-skill-map.md` | L3 | partial | Prompt/Skill 版本未在所有模型输出和旧调用链强制记录 | 高 |
| NOS-PROD-004 | 平台 | Model Strategy/provider 抽象 | ModelAdapter、ModelRouter、Fallback 和 Provider profiles 存在 | `model_adapters/providers.py`; `modules/model_router/service.py` | L4 | partial | 真实生产 Provider/成本/质量证据不足；审批来源可由请求伪造 | 严重 |
| NOS-PROD-005 | 领域 | 场景/草稿生成和版本化 | Drafting、DraftVersion、Editor patch/diff/rollback 可运行 | `modules/drafting/service.py`; `modules/editor/service.py` | L4 | partial | 10 章正文重复，未证明场景推进和长篇内容质量 | 严重 |
| NOS-PROD-006 | 工作流 | 审稿、修订、再审的受控循环 | Review -> RevisionPlan -> EditorPatch -> re-review 在总线存在 | `modules/chapter_production_bus/service.py`; `modules/editor/service.py` | L4 | partial | 本地 deterministic quality repair 会拼接固定文本；真实模型校准不足 | 严重 |
| NOS-PROD-007 | 运行 | 状态、版本、幂等、重试、取消、超时和恢复 | Chapter run 和 Agent Scheduler 均有相关控制 | `modules/chapter_production_bus/service.py`; `modules/agent_scheduler/` | L4 | partial | 跨执行平面幂等键和取消语义不统一，长期运行未证明 | 高 |
| NOS-PROD-008 | 运行 | Token、成本和预算硬停 | Guarded adapter、CostLedger、Budget/SLA 存在且聚焦测试通过 | `modules/model_router/service.py`; `modules/agent_runs/service.py`; `tests/unit/test_provider_runtime_guard.py` | L4 | partial | 部分调用链可能不经 guarded adapter；无真实账单对账 | 严重 |
| NOS-PROD-009 | 治理 | 人工干预、审批、回滚和发布候选 | Editor workbench、ApprovalRequest、Rollback、export package 存在 | `modules/manuscript_workbench/service.py`; `modules/operation_transactions/service.py` | L3 | partial | Agent rollback 与物理 rollback 分裂，审批身份边界不可信 | 严重 |
| NOS-PROD-010 | 产品 | 可审阅的发布版本和 Release Package | 本地 markdown、manifest、provenance、release package 存在 | `modules/publishing/release_package.py`; `chapter_production_bus/service.py` | L3 | partial | 当前正文不可用，真实平台包/签名/回滚未验收 | 严重 |
| NOS-LONG-001 | 长篇 | Canon 事实库、来源、有效期和冲突 | CanonDatabase/FactLedger/KG/冲突检查存在 | `modules/longform_stability/service.py`; `modules/canon_graph/service.py` | L3 | partial | 多为字符串/关键词事实，缺事件溯源、时间有效性和可信抽取 | 严重 |
| NOS-LONG-002 | 长篇 | 时间线、地理、位置、物品、资源和战力状态 | Schema/ledger 中有部分字段和检查 | `modules/longform_stability/service.py`; `modules/continuity_graph/service.py` | L2 | partial | 没有统一 typed state reducer；战力/库存变化缺事务语义 | 严重 |
| NOS-LONG-003 | 长篇 | 人物状态、关系和成长弧持续回写 | Longform recap 写 CharacterStateLedger/Arc | `modules/longform_recap/service.py` | L3 | partial | 每章强制 recap、抽取启发式，状态增长和置信度未治理 | 严重 |
| NOS-LONG-004 | 长篇 | 伏笔全生命周期、遗漏和回收 | 伏笔资产、状态和 ReviewIssue 可生成 | `modules/longform_stability/service.py`; `modules/longform_recap/service.py` | L3 | partial | 无真实 30/100 章回收证据；匹配语义浅 | 高 |
| NOS-LONG-005 | 长篇 | 故事弧、卷级状态和节奏趋势 | Arc ledger、long planning、质量趋势存在 | `modules/long_planning/service.py`; `modules/long_chain_proof/service.py` | L2 | partial | 非 Provider 长链趋势为程序生成，不能证明真实故事状态 | 严重 |
| NOS-LONG-006 | 长篇 | 章节/卷摘要和长期记忆 | LongMemory、recap 和摘要资产存在 | `modules/long_memory/service.py`; `modules/longform_recap/service.py` | L3 | partial | 仍偏摘要/RAG，没有与结构化事实的稳定优先级和压缩评测 | 高 |
| NOS-LONG-007 | Agent | 每 5/10 章和卷末复盘 Agent | Longform recap 和 Agent operation 存在 | `modules/longform_recap/service.py`; Agent operation registry | L3 | divergent | Chapter Bus 当前 `force=True` 每章执行，绕过蓝图节奏并造成资产增长 | 高 |
| NOS-LONG-008 | 质量 | 漂移、崩坏、重复、战力膨胀、节奏失衡检测 | 多类规则和 ReviewIssue 生产器存在 | `modules/longform_stability/service.py`; `modules/content_quality_loop/service.py` | L3 | partial | 启发式、固定样例和无校准阈值，缺真实长链召回率 | 严重 |
| NOS-LONG-009 | 规模 | 100 章/百万字级稳定持续生产 | 有 deterministic_50/mock_100/state_only_300 proof 模式 | `modules/long_chain_proof/service.py`; integration tests | L2 | evidence-insufficient | 非 Provider 模式不生成真实章节，publish gate 明示 not_executed | 严重 |
| NOS-LONG-010 | 性能 | 长链运行成本和资产增长受控 | 有 runtime growth/热点/策略证据模块 | `modules/chapter_runtime_growth/`; `docs/reports/v1-chapter-sequence-slow-acceptance.md` | L2 | blocked | 10 章约新增 7,615 资产，耗时单调增至 306.9 秒 | 严重 |
| NOS-QUALITY-001 | 质量 | 通用、平台、内容安全、原创性和版权审稿 | Review、platform、source/originality 规则均有 | `modules/review/service.py`; `modules/content_quality_loop/service.py`; `modules/mkaos_quality/` | L3 | partial | 原创/安全多为启发式，无生产语料和人工召回/精度证据 | 严重 |
| NOS-QUALITY-002 | 质量 | AI 味、重复、模板化和文风检测 | marker、token/Jaccard、StyleOS 和 readability 存在 | `modules/quality_eval/service.py`; `modules/style_os/service.py` | L2 | partial | 无可靠分类器/Golden，10 章正文重复仍通过资产覆盖 | 严重 |
| NOS-QUALITY-003 | 质量 | 情节逻辑、人物一致性、节奏、钩子、爽点、情绪和主题 | 多个规则模块及 ChapterPlan 字段覆盖 | `modules/content_quality_loop/service.py`; `modules/chapter_economy/service.py` | L3 | partial | 主题深度缺模型；各分数缺统一校准和置信度 | 高 |
| NOS-QUALITY-004 | 数据 | ReviewIssue 标准化、生命周期、阻断和归属 | 中央服务、迁移、API/UI 和发布阻断均存在 | `modules/review_issue/service.py`; `web/admin/app/review-issues/page.tsx` | L4 | partial | 仍有临时 issue dict 和生产者字段漂移 | 中 |
| NOS-QUALITY-005 | 工作流 | 质量门禁、修订策略和回归门禁 | Chapter Bus/Publish/MKAOS/Provider 门禁真实存在 | `modules/content_quality_loop/service.py`; `modules/publishing/release_gate.py` | L4 | blocked | 当前 12 章/V1 回归失败；门禁加强未完成调用方迁移 | 严重 |
| NOS-QUALITY-006 | 评测 | Eval Center：Prompt/Skill/Agent/Model/Workflow 离线在线评测 | Evaluation Center、Quality Eval、Model Benchmark、Prompt Regression 存在 | `modules/evaluation_center/service.py`; `modules/quality_eval/service.py` | L3 | partial | 大多为规则和夹具，在线质量趋势/生产实验不足 | 严重 |
| NOS-QUALITY-007 | 评测 | Golden Dataset、人工标注、一致性和校准 | 相关 Schema/服务/readiness gate 存在 | `modules/evaluation_center/service.py`; tests | L2 | skeleton | 无提交的生产 Golden Dataset 和真实标注一致性结果 | 严重 |
| NOS-QUALITY-008 | 发布 | 发布前综合质量报告和可解释阻断 | Release gate 汇总 ReviewIssue/风险/Context/MKAOS | `modules/publishing/release_gate.py`; `modules/publishing/release_package.py` | L3 | partial | 真实内容、真实 Provider 与真实平台验收缺失 | 高 |
| NOS-AGENT-001 | Agent | Agent Registry、角色、能力声明和版本 | Registry、27 个 profile、Agent/Skill map 存在 | `modules/agent_registry/service.py`; `docs/09-skills/agent-skill-map.md` | L3 | partial | 能力声明静态，缺基于评测和运行环境的动态准入 | 中 |
| NOS-AGENT-002 | 数据 | Agent 输入输出、权限、工具和禁止行为协议 | Contract、tool allowlist、permission guard、forbidden actions 存在 | `modules/agent_runs/service.py`; `modules/tool_gateway/service.py` | L4 | partial | 旧服务直调和部分 `*` operation contract 弱化最小权限 | 高 |
| NOS-AGENT-003 | 工作流 | Task/Workflow/Handoff 的标准协议 | AgentTask、WorkflowRun/NodeRun、HandoffPacket 均有 | `modules/agent_messages/service.py`; `modules/handoff/service.py`; `modules/workflow_nodes/service.py` | L3 | partial | 三者的状态、关联和所有权未收敛为一套执行图 | 高 |
| NOS-AGENT-004 | Harness | Checkpoint、预算、超时、取消、重试、死信和恢复 | Scheduler 有 queue lease、retry、dead-letter、recovery、SLA | `modules/agent_scheduler/`; `modules/agent_runs/service.py` | L4 | partial | 跨 Provider 的主动取消、业务补偿和长运行规模证据不足 | 高 |
| NOS-AGENT-005 | Harness | 幂等、回滚和接受门禁 | Queue/operation 幂等、Gate、rollback rehearsal 存在 | `modules/agent_scheduler/service.py`; `modules/operation_transactions/service.py` | L3 | partial | Scheduler rollback 多为 metadata；物理回滚服务未普遍接入 | 严重 |
| NOS-AGENT-006 | 自治 | 目标分解、计划、优先级和动态重规划 | 有模板任务和 Editor Chief 建议 | `modules/editor_chief/service.py`; `modules/portfolio_os/service.py` | L1 | missing | 无 GoalPlan/Planner、受限分解器和可验证计划状态机 | 严重 |
| NOS-AGENT-007 | 自治 | 持续自治循环和周期调度 | Scheduler loop 可执行有限 tick | `modules/agent_scheduler/scheduler_tick.py` | L2 | skeleton | 无持久 recurring schedule、触发条件和战略停止规则 | 严重 |
| NOS-AGENT-008 | 自治 | 多 Agent 协作、Handoff 和冲突处理 | Handoff packet 和 operation registry 存在 | `modules/handoff/service.py`; `modules/agent_messages/service.py` | L3 | partial | 主要为串行资产交接，缺并发协作、仲裁和共享计划语义 | 高 |
| NOS-AGENT-009 | 治理 | 人机协同、审批门禁和行为审计 | ApprovalRequest、Permission Center、Audit/Trace 存在 | `modules/permission_center/service.py`; `modules/audit_log/service.py` | L3 | divergent | Provider API/UI 可自报 approved，未强制解析真实 ApprovalRequest | 严重 |
| NOS-AGENT-010 | 评测 | Agent 级成功率、质量、成本和回归评测 | AgentMetric、Evaluation Center、operation coverage 存在 | `modules/agent_scheduler/service.py`; `web/admin/app/agent-operation-coverage/page.tsx` | L3 | partial | 无按任务族的生产 Golden、长期 SLO 和版本比较 | 高 |
| NOS-AGENT-011 | UI | Agent Center 是可操作控制台 | Registry/Center/Dispatch/coverage 页面和 API 存在 | `web/admin/app/agent-center/page.tsx`; `agent-dispatch/page.tsx` | L2 | partial | Agent Center 与 Dispatch 实际返回同一页面，操作覆盖有限 | 高 |
| NOS-FEEDBACK-001 | 反馈 | 导入编辑、读者、评论、章节和平台指标 | CSV/metric/comment 导入与反馈资产存在 | `modules/feedback/service.py`; `web/admin/app/feedback-console/page.tsx` | L3 | partial | 连接器/数据质量/身份去重和生产来源证明不足 | 高 |
| NOS-FEEDBACK-002 | 反馈 | 完读、追读、留存、掉点、角色热度和情绪结构化 | retention/dropoff、reader simulation、聚类存在 | `modules/feedback/service.py`; `modules/feedback_backflow/service.py` | L3 | partial | 主要为小样本/启发式，没有 cohort 与显著性约束 | 高 |
| NOS-FEEDBACK-003 | 反馈 | 问题归因到章节、角色、情节、知识和生产决策 | Feedback attribution、impact、mutation proposal 存在 | `modules/feedback_backflow/service.py`; `modules/mkaos/service.py` | L3 | partial | 相关性易被当因果，证据置信度和反事实不足 | 严重 |
| NOS-FEEDBACK-004 | 治理 | 反馈到 Prompt/Skill/大纲/质量权重前必须审批 | Mutation proposal、Approval、invalidation/task 资产存在 | `tests/integration/test_feedback_to_mutation_proposal.py`; `modules/feedback_backflow/service.py` | L3 | partial | 各目标的应用器、回滚和在线实验未统一 | 高 |
| NOS-FEEDBACK-005 | 安全 | 反馈污染、操纵和错误学习防护 | 有 confidence/row count 和人工 gate | `modules/feedback/service.py`; `modules/mkaos/selector_governance.py` | L2 | skeleton | 缺来源信誉、异常检测、cohort、最小样本和隔离区 | 严重 |
| NOS-FEEDBACK-006 | 学习 | 跨作品经验迁移且保持隔离 | MKAOS 可跨项目使用，Portfolio 可比较作品 | `modules/mkaos/service.py`; `modules/portfolio_os/service.py` | L2 | partial | 无租户/版权策略驱动的迁移范围、效果评测和污染回滚 | 高 |
| NOS-PUBLISH-001 | 平台 | 平台策略、题材、节奏、长度、标题和简介适配 | Platform Strategy、Genre、Mobile、Chapter Economy 模块存在 | `modules/platform_strategy/service.py`; `modules/mobile_reading/service.py` | L3 | partial | 规则多为手工 profile，缺平台版本、数据证据和校准 | 高 |
| NOS-PUBLISH-002 | 平台 | 书名、简介、封面、章节标题优化工具 | Release/Publishing 内容中有标题、简介和 `cover_asset` 字段 | `modules/publishing/service.py` | L1 | skeleton | `image_prompts` 只有包骨架；没有候选生成、评分、审批和平台结果回流 | 中 |
| NOS-PUBLISH-003 | 发布 | Release Package、发布门禁、版本和记录 | Package/Gate/PublishingLog/Calendar 已实现 | `modules/publishing/`; `web/admin/app/publish-gate/page.tsx` | L3 | partial | 真实平台上传和内容可用性证据不足 | 严重 |
| NOS-PUBLISH-004 | 平台 | 可替换 Platform Adapter、幂等、回执和错误映射 | 手工 Fanqie/Qidian profile、generic HTTP client、fake client 测试存在 | `modules/publishing_feedback_adapters/service.py` | L2 | divergent | 与 `publishing/adapters.py` 形成两套接口；官方 SDK 未接入 | 严重 |
| NOS-PUBLISH-005 | 治理 | 发布审批、回滚和补偿 | 旧适配器创建 ApprovalRequest，package 有 rollback snapshot | `modules/publishing/adapters.py`; `modules/publishing/release_package.py` | L2 | divergent | 新 HTTP 发布路径未强制 ApprovalRequest；外部撤回/补偿未实现 | 严重 |
| NOS-PUBLISH-006 | 产品 | 多平台差异、连载日历和商业目标跟踪 | 平台 profile、calendar、metrics 有字段 | `modules/publishing/service.py`; `modules/platform_strategy/service.py` | L2 | partial | 无真实跨平台版本分支、连载策略引擎和收入归因 | 高 |
| NOS-PUBLISH-007 | 领域 | Trope fatigue、生命周期和连载策略 | 仅策略/规则文本中出现相关概念 | `modules/platform_strategy/service.py` | L1 | missing | 无一等 detector、状态和生产门禁 | 中 |
| NOS-PORTFOLIO-001 | 产品 | 多小说项目组合、潜力评分和生命周期 | PortfolioProject、BookPotentialScore 和 lifecycle 资产存在 | `modules/portfolio_os/service.py`; `schemas/assets.py` | L3 | partial | 生命周期建议不实际更新项目，评分缺真实商业数据 | 高 |
| NOS-PORTFOLIO-002 | 产品 | 跨书相似度、资源冲突和原创隔离 | CrossBookSimilarity/资源计划存在 | `modules/portfolio_os/service.py` | L2 | partial | 主要为计划/规则，无正文级跨书泄漏评测 | 高 |
| NOS-PORTFOLIO-003 | 自治 | 作品级排程和资源分配 | 计划中明确 `book_level_scheduler_enabled=False` | `modules/portfolio_os/service.py` | L1 | missing | 无作品级队列、配额、公平性和优先级执行器 | 严重 |
| NOS-PORTFOLIO-004 | 自治 | 多书自动 dispatch 和隔离执行 | 输出明确 `automatic_dispatch=False`、队列为空 | `modules/portfolio_os/service.py` | L1 | missing | 无实际多书并发执行链 | 严重 |
| NOS-PORTFOLIO-005 | 验收 | 至少三本长篇并行生产验证 | 未找到真实并行验收 | Portfolio 单测仅验证规划资产 | L0 | missing | 无数据隔离、资源抢占、成本和恢复证据 | 严重 |
| NOS-UI-001 | UI | Novel OS 工作台和多项目管理 | 首页、OS、Projects、Production 页面 API 连通 | `web/admin/app/os/page.tsx`; `projects/page.tsx` | L3 | partial | 缺跨模块任务视图和作品级行动队列 | 中 |
| NOS-UI-002 | UI | Source Center 和来源治理工作台 | 有来源治理 API/局部 cockpit 数据 | `api/routers/`; `web/admin/app/permission-center/page.tsx` | L1 | missing | 无独立 Source Center 路由、摄取/rights/diff/repair 全流程 UI | 高 |
| NOS-UI-003 | UI | 大纲、细纲、章节生产和 AI 编辑器 | Production、Manuscript、Editor、Review 页面存在 | `web/admin/app/production/page.tsx`; `editor/page.tsx` | L3 | partial | 领域结构编辑、依赖影响和多人/Agent 冲突处理不足 | 高 |
| NOS-UI-004 | UI | Canon/Arc/Foreshadow/Character/World 深度控制台 | Canon/Arc/Foreshadow/Character 页面存在 | `web/admin/app/canon-console/page.tsx`; `web/admin/app/features/os/EditableAssetConsolePage.tsx` | L2 | skeleton | 多数是通用 JSON/文本编辑，非关系/时间线/状态机控制台 | 高 |
| NOS-UI-005 | UI | Review/Eval/Golden/Human Calibration 控制台 | Review、Quality、Evaluation 页面存在 | `web/admin/app/evaluation/page.tsx`; `quality-eval-v2/page.tsx` | L2 | partial | 缺 Golden 管理、标注任务、一致性与校准操作面 | 严重 |
| NOS-UI-006 | UI | Workflow/Task/失败恢复/成本/Trace 可视化 | 对应页面均存在且调用 API | `web/admin/app/workflow-runtime/`; `tasks/`; `trace-timeline/`; `cost-dashboard/` | L3 | partial | 状态跨执行平面，缺统一 run graph 和业务补偿操作 | 高 |
| NOS-UI-007 | UI | Portfolio 与多小说并行控制台 | OS 页面有只读 Portfolio 表 | `web/admin/app/os/page.tsx`; `modules/portfolio_os/service.py` | L1 | skeleton | 无专用 route、调度、配额和跨书风险操作 | 严重 |
| NOS-UI-008 | UI | UI E2E、可访问性和行为验收 | Web 测试通过静态架构检查，Playwright 可选 | `web/admin/tests/`; Web test script | L2 | evidence-insufficient | 浏览器 E2E 本次跳过；无法证明页面操作与后端闭环 | 高 |
| NOS-OPS-001 | 工程 | 模块化单体和清晰领域边界 | 约 93 个模块目录，整体方向正确 | `src/novel_forge/modules/` | L3 | partial | 多个 2k-7k 行服务、705 路由，职责和依赖过密 | 高 |
| NOS-OPS-002 | 工程 | Postgres、向量、对象、缓存和图数据库生产配置 | Compose 提供 Postgres/Redis/Qdrant/MinIO/Neo4j 等 | `docker-compose.yml`; `Makefile` | L2 | partial | 多为可选后端，端到端一致性、迁移和故障切换未证明 | 高 |
| NOS-OPS-003 | 工程 | Worker、队列、并发和任务可靠性 | Celery 与 Agent queue 均有超时、ack/retry 配置 | `src/novel_forge/workers/celery_app.py`; `modules/agent_scheduler/` | L3 | partial | 两套队列语义、吞吐/背压/长期负载未验证 | 高 |
| NOS-OPS-004 | 可观察性 | 结构化日志、Metrics、Trace、模型调用和成本账本 | TraceSpan、Metric、ModelCallLog、CostLedger、ClickHouse 投影存在 | `modules/runtime_ledger/`; `modules/metrics/`; `modules/clickhouse_analytics/` | L3 | partial | 未找到完整 OpenTelemetry/Prometheus 导出和 SLO 告警闭环 | 高 |
| NOS-OPS-005 | 运行 | 健康检查、限流、性能和容量管理 | Compose health 和部分 runtime policy 存在 | `docker-compose.yml`; `modules/runtime_policy/service.py` | L2 | partial | API 无系统级限流；章节性能随资产增长明显退化 | 严重 |
| NOS-OPS-006 | 安全 | 身份认证、RBAC、最小权限和 Secret 管理 | Agent permission/tool policy 存在 | `modules/permission_center/service.py`; API middleware | L1 | missing | 未发现用户认证/JWT/API key/RBAC；默认开发 Secret，无 Vault/TLS | 严重 |
| NOS-OPS-007 | 运维 | 备份、恢复、灾难恢复和演练 | 有本地 ZIP backup/restore | backup/restore CLI and operations code | L2 | skeleton | manifest 明示 pg_dump、MinIO mirror、Qdrant snapshot 需外部处理 | 严重 |
| NOS-OPS-008 | 运维 | 业务回滚和补偿执行 | OperationTransactions 可恢复版本文件和隔离新资产 | `modules/operation_transactions/service.py` | L3 | partial | 未成为所有 Agent/发布/反馈变更的统一事务边界 | 高 |
| NOS-OPS-009 | 测试 | Unit/Schema/Contract/Integration/Workflow/E2E 测试金字塔 | 测试数量大、层级较广 | `tests/unit/`; `tests/integration/`; `tests/acceptance/` | L3 | blocked | 当前全量回归不绿；浏览器 E2E 跳过；生产 Provider/平台缺失 | 严重 |
| NOS-OPS-010 | CI/CD | CI、迁移、发布和回滚门禁 | 仅发现 Web Cockpit workflow | `.github/workflows/web-cockpit-smoke.yml` | L1 | missing | 无 Python 全量测试/lint/schema/skills/迁移/镜像供应链门禁 | 严重 |
| NOS-OPS-011 | 安全 | 审计日志、防篡改、数据保留和删除 | AuditEvent、retention sweep、版本资产存在 | `modules/audit_log/service.py`; `modules/source_intake/retention_sweep.py` | L2 | partial | 本地 JSON 可直接修改；无签名/WORM/用户审计/数据删除证明 | 高 |
| NOS-OPS-012 | 工程 | 文档与代码持续一致 | 大量切片报告和索引存在 | `docs/reports/`; `docs/README.md` | L2 | divergent | 历史百分比/完成声明与当前最终蓝图口径及回归状态不一致 | 高 |

### 6.1 矩阵结论

- **接近 L4 的共享底座**：Context Builder、来源隔离、ReviewIssue、受控模型调用、章节草稿版本/修订、Agent 有界执行和部分门禁。
- **L3 的主要系统**：MKAOS、分析转换、章节生产总线、长篇资产、发布包、反馈导入、Agent Scheduler、广度型 UI。
- **L2 或更低的决定性能力**：创意孵化、真实世界/人物生成、主题意义、结局、自治规划、真实平台适配、多书调度、用户安全、生产 DR。
- **L4 不代表生产成熟**：上述能力仍缺真实 Provider、真实长篇、校准、SLO、E2E 和生产运维证据，因此没有 L5。

## 7. 已完整或基本完成的能力

这里的“基本完成”仅针对当前子能力边界，不表示最终产品闭环完成。

1. **版本化 JSON 资产和通用校验**：`storage/local.py`、`schemas/base.py` 能创建、读取、版本化和校验资产；空工作区验证通过。
2. **中央 ReviewIssue 生命周期**：`modules/review_issue/service.py` 提供创建、状态、严重级别、归属和阻断；迁移和 UI/API 均存在。
3. **统一 Context Builder 第一生产版**：`modules/context_builder/service.py` 支持阶段 profile、选择/压缩/预算、实际发送内容、Replay/Diff、RAG/KG 和来源门禁。
4. **原始来源隔离第一生产版**：Context 明确禁止原始、清洗、分块、拆解和分析资产进入正文阶段；负向测试覆盖多个 V1 stage profile。
5. **模型调用治理第一生产版**：`modules/model_router/service.py`、guarded adapter、ModelCallLog、CostLedger 可做前后硬停、超时和成本记录；聚焦测试 10/10 通过。
6. **有界 Agent 执行器第一生产版**：AgentContract/Run/Checkpoint/Budget/Gate/Metric、queue lease、retry/dead-letter/recovery 均有代码和测试。
7. **草稿版本和编辑回滚**：DraftVersion、EditorPatch、Diff、rollback 和 re-review 形成了可追踪局部修改路径。
8. **发布前本地证据包**：ReleasePackage、manifest、provenance、known risks、rollback snapshot 和发布门禁已形成可审阅资产。
9. **MKAOS 的核心资产治理**：知识候选、证据 Span、lineage、Pack、selector、quality、lifecycle、usage 和反馈归因覆盖较广。
10. **Skills 治理**：Root Skills 与 `.claude/skills` 同步规则明确，本次 `make check-skills` 通过。

这些能力最适合作为后续补全的保留基础，不应全量重写。

## 8. 部分实现和骨架能力

| 能力 | 已完成部分 | 仍缺部分 | 结论 |
|---|---|---|---|
| Topic | 模型调用、资产写入、Trace | 候选池、聚类、新颖性、真实模型结果驱动字段 | L2 骨架 |
| World | WorldBible 资产、调用入口 | 当前固定 Echo Clock City；缺结构化规则生成和影响治理 | L2 骨架 |
| Character | CharacterCard、压力评分、长篇 ledger | 当前固定 Lin Qiao；缺关系/状态机和真实生成 | L2 骨架 |
| Outline | 模型生成、长纲和 ChapterPlan 契约 | 上游输入不真实、长期同步和 Ending 缺失 | L3 局部可用 |
| Chapter Bus | 12 步、暂停/恢复、审稿/修订/回写/导出 | 内容重复、性能退化、与 Workflow/Agent 状态未统一 | L3 系统切片 |
| Canon/Longform | 数据类型、回顾、图、冲突/漂移问题 | typed state reducer、可信抽取、真实长链、节奏化 recap | L3 局部可用 |
| Quality/Eval | 多 rubric、Gate、ReviewIssue、benchmark 资产 | Golden、人工校准、真实 Provider、内容质量门槛 | L3 局部可用 |
| Publishing | 本地包、门禁、日志、手工平台规则 | 单一 adapter、真实上传、审批/回执/补偿 | L2-L3 |
| Feedback | CSV/指标/评论、聚类、mutation proposal | 数据质量、因果归因、污染防护和在线实验 | L3 局部可用 |
| Portfolio | 潜力、相似度、资源和 lifecycle 计划 | 自动 dispatch、项目状态变更和三书并行 | L2 骨架 |
| Agent Center | Registry、Run、Queue、恢复、页面 | Planner、持续循环、操作深度、真实审批身份 | L3 有界执行器 |
| Web Admin | 页面/API 广度、Trace/Cost/Review/Context 控制面 | Source/Portfolio/typed Canon/Eval 操作和浏览器 E2E | L2-L3 |

## 9. 完全缺失的功能

1. 一等 `ConceptCandidate`/Creative Center：批量发现、聚类、去重、新颖性、市场适配、风险评分和立项审批。
2. 一等 Theme/Meaning/Philosophy Engine，以及主题在章/卷/结局中的兑现追踪。
3. Ending/Closure Engine：角色弧、主题、伏笔和读者承诺的收束规划及门禁。
4. Trope Fatigue Detector 和可追踪的套路生命周期模型。
5. 作品级持续自治 Planner：受限目标分解、动态重排、停止条件和周期触发。
6. 三本或以上作品的真实并行调度、配额、公平性、隔离和恢复验收。
7. 生产级用户认证、RBAC、API key/JWT、Secret manager 和系统级限流。
8. 覆盖 PostgreSQL、MinIO、Qdrant 的自动备份、恢复校验和灾难恢复演练。
9. 真实平台官方 Adapter 的端到端验收，包括上传、回执、撤回/补偿和失败映射。
10. 提交到仓库且可版本化的生产 Golden Dataset 与人工标注一致性基线。
11. 内容真实推进的 30/100 章以及百万字级长链验收。
12. 专用 Source Center 和可执行 Portfolio 调度控制台。

“未实现”依据是未找到领域模型、核心服务和生产调用链的组合，而不是仅根据页面或文件名判断。

## 10. 多处存在但尚未统一的能力

### 10.1 执行编排

- `workflows/pipeline.py` 仍是可调用的早期顺序链。
- Workflow Runtime 有独立 NodeRun/WorkflowRun 状态。
- Chapter Production Bus 有自己的 12 步状态、暂停和恢复。
- Agent Scheduler 又有 AgentRun/DispatchQueue/Checkpoint 状态。

建议最终只保留一个 Production Kernel 作为业务状态权威：Workflow 负责图，Agent Scheduler 负责执行，Chapter Bus 作为标准 workflow template/领域 facade；旧 Pipeline 降级为兼容/demo adapter。

### 10.2 发布适配

- `modules/publishing/adapters.py` 偏手工/本地，创建 ApprovalRequest 但不执行真实 webhook。
- `modules/publishing_feedback_adapters/service.py` 有 generic HTTP client 和平台 profile，却未强制解析 ApprovalRequest。

两者在审批、幂等、回执和补偿语义上冲突，应合并为单一 `PlatformAdapter` 契约。

### 10.3 回滚

- Agent Scheduler rollback runner 多数将输出标记为 `rolled_back`/`rollback_required`。
- `operation_transactions/service.py` 能物理恢复版本文件、隔离新建输出并验证结果。
- Source 和 MKAOS 又各自有 metadata rollback。

应由统一 OperationTransaction 持有业务补偿计划，AgentRun 只引用其结果。

### 10.4 质量问题模型

中央 ReviewIssue 已存在，但若干 review/quality producer 仍先生成临时 dict 或自己的 issue shape，再由调用方转换。应强制所有门禁消费同一 `ReviewIssueRef[]`。

### 10.5 运行数据与权威存储

JSON、本地目录、Postgres 投影、Qdrant、Neo4j 和 ClickHouse 都能保存某类信息，但缺“每种运行模式的唯一权威”定义。当前 best-effort write-through 允许业务成功而投影失败，工业模式下会造成查询和恢复歧义。

## 11. 与蓝图方向不一致的实现

1. **固定内容伪装成领域能力**：World 和 Character 服务固定写 Echo Clock City/Lin Qiao；Topic 的主要业务字段也并非完全由模型输出驱动。这与“目标约束驱动的创作引擎”相反。
2. **资产覆盖替代内容验收**：V1 报告以 16 类资产齐全判定成功，但正文重复，和蓝图强调的故事推进、质量与长篇稳定相反。
3. **每章强制 Longform Recap**：Chapter Bus 以 `force=True` 每章运行，绕过 5/10 章及卷级复盘节奏，造成状态资产膨胀。
4. **确定性质量修复写正文**：Chapter Bus 的本地修复路径拼接固定文本。这可做测试 fixture，不应成为内容生产 fallback。
5. **客户端自报审批**：Provider API 和 Web UI 可提交 `approval_status=approved` 和固定 `ui-operator-approval`，与审批必须可验证、不可伪造的治理目标冲突。
6. **长链证明不生成长链内容**：`deterministic_50`/`state_only_300` 主要生成 checkpoint 和程序化趋势，发布门禁标记 `not_executed`，不应被解读为 50/300 章小说验收。
7. **Portfolio 只规划不执行**：输出明确关闭 book-level scheduler 和 automatic dispatch，与多书自治目标存在方向差距。

## 12. 产品闭环缺口

最终闭环应是：目标/市场 -> 创意候选 -> 立项审批 -> 世界/人物/结构 -> 章节生产 -> 长篇状态 -> 质量/修订 -> 发布 -> 反馈 -> 受控学习。当前在以下位置断开：

- 项目创建前没有候选发现和立项事务；
- 世界/人物固定样例使下游大纲即使运行也不代表真实项目生成；
- 单章资产链不能证明多章内容推进；
- 发布前门禁可以运行，但被评估的内容尚不具备有效性证据；
- 平台上传和回执无真实证据；
- 反馈 mutation proposal 未形成受控在线实验和效果回滚；
- Portfolio 无法将策略转成多书执行。

因此当前产品是一组较强的生产与治理切片，而不是已经闭合的 Novel OS 产品生命周期。

## 13. Agent 与 Harness 缺口

### 13.1 已有 Harness

70 个注册 operation contract（其中一个通配）、27 个运行 profile；AgentRun、Checkpoint、Budget、Gate、Metric、DispatchQueue；queue leasing、retry、dead-letter、recovery、acceptance gate 和部分 rollback 均有实际代码。这些足以支持受控、有界、可恢复的任务执行。

### 13.2 尚缺自治层

- 无 `GoalPlan`、目标分解器和计划版本；
- 无定时/事件驱动的持久 recurring controller；
- 无跨作品/跨 Agent 资源仲裁；
- 无基于 Eval、预算和风险的动态 operation 选择；
- 无策略停止、退化和人工接管 SLO；
- Agent Center 页面尚不能完成上述操作。

当前合理定位为 **A2：有界任务自动执行**。要进入 **A3：受治理的项目自治**，必须先统一执行协议、真实审批和内容验收，不能直接增加一个自由规划 Prompt。

## 14. MKAOS 和知识资产缺口

MKAOS 是当前最丰富的子系统之一，但仍有四类关键差距：

1. **生命周期迁移不完整**：历史 KnowledgeCard 可能未经过 Candidate/EvidenceSpan/Approval 链。
2. **质量校准不足**：去重、quote leakage、creative usability、confidence 多为启发式；缺真实语料 Golden 和人工一致性。
3. **生产效果归因不足**：Usage 和 feedback attribution 可记录关联，但不能证明某知识资产造成质量提升。
4. **服务边界过大**：核心 service 超过 7,000 行，摄取、选择、治理、反馈和图谱依赖容易形成隐式耦合。

MKAOS 不是“缺功能”，而是需要从广覆盖实现收敛为可校准、可迁移、可证明的知识供应链。

## 15. Context Builder 与生产上下文缺口

Context Builder 已达到 L4 的主要条件，但其完整性受上游和调用迁移制约：

- World/Character/Canon 状态本身若不可信，统一打包也不会产生可信上下文；
- 新来源 runtime gate 已 fail-closed，但旧夹具和部分调用链未迁移，当前回归失败；
- 缺统一内容 digest、缓存、依赖变更后的自动失效和重新构建策略；
- RAG/KG 的召回率、精度、降级和 Provider tokenizer 预算未用真实长篇校准；
- 所有模型调用是否强制记录 ActualSentContext 尚无全库 contract test；
- UI 可以查看 bundle，但不能对事实冲突进行结构化解决后原地 replay。

## 16. 长篇稳定性缺口

当前系统拥有 Canon、Fact、Character、Arc、Foreshadow、Promise、Reward、Villain 等丰富资产名，但主要风险是“类型存在，状态语义不够强”：

- 事实没有统一的 subject/predicate/object、有效时间、证据、置信度和 supersedes 关系；
- 章节状态主要由正则、关键词或精确扫描提取，难以处理隐含变化和否定；
- 长篇记忆仍较依赖摘要/RAG，没有事件日志 + 快照的确定性 replay；
- 伏笔回收、角色漂移和战力变化未用真实 30/100 章标注集测量 precision/recall；
- 每章强制 recap 造成写放大，10 章运行的资产和耗时增长已成为阻塞；
- 现有 50/100/300 模式不能替代真实正文、状态变化和发布门禁验收。

当前没有证据证明百万字级持续生产能力。

## 17. 审稿、质量和 Eval 缺口

质量体系的强项是 ReviewIssue 和多门禁，弱点是“测量值是否代表质量”：

- 许多分数由长度、关键词、marker 或 token/Jaccard 计算；
- 10 章重复正文未被“资产覆盖”验收阻断，说明验收目标错位；
- `Evaluation Center` 已定义 Golden/Human/Calibration readiness，但仓库中没有生产 Golden 资产基线；
- 没有真实 Provider judge 与人工标注的一致性、偏差和成本报告；
- Prompt/Skill/Agent/Model/Workflow 的版本回归没有统一 benchmark suite；
- 12 章集成测试因 protagonist agency 新规则阻断，说明规则升级没有完成夹具/阈值迁移。

发布门禁必须分开计算“资产完整性”和“内容质量”，前者不能为后者兜底。

## 18. UI 和人工控制缺口

Web Admin 的覆盖广度是真实能力，但还不是蓝图中的操作系统控制台：

- Agent Center 与 Agent Dispatch 使用同一页面，角色边界不清；
- Canon/Character/Arc/Foreshadow 控制台主要是通用资产编辑器；
- 缺独立 Source Center 和 Portfolio 调度路由；
- Eval 缺 Golden、人工标注、校准、阈值发布和回滚工作台；
- MKAOS 图谱预览仅取少量节点/边，不能治理大图冲突；
- 没有统一 Run Graph 展示 Workflow Node、AgentRun、ModelCall、Gate、Artifact 和 Compensation；
- 本次 Playwright 跳过，页面交互和失败恢复未形成浏览器级证据。

## 19. 平台适配、发布与反馈闭环缺口

- Fanqie/Qidian 规则明示 `manual_profile_not_official_sdk`，不是生产平台适配证据；
- generic HTTP client 与旧 publishing adapter 的审批和错误语义不一致；
- 缺发布幂等键、平台 receipt、remote version、撤回/补偿和重试矩阵的统一契约；
- 标题/简介/封面/章节名仅有字段或单点工具，没有候选实验和平台结果归因；
- 反馈导入没有严格的 connector provenance、cohort、bot/异常检测和统计显著性；
- 反馈可生成 mutation proposal，但未证明变更 -> A/B/回归 -> 效果 -> 保留/回滚的闭环。

## 20. 工程、测试和运维缺口

1. **性能**：10 章运行从 22.6 秒增长至 306.9 秒，新增约 7,615 个资产；存在全目录扫描、每章强制 recap 和重复证据写入。
2. **回归**：当前 Python 全量基线不绿；来源门禁、质量规则和 Schema 必填字段升级后旧调用方/夹具未同步。
3. **CI**：仅发现 Web Cockpit workflow；Python、Schema、Skill、迁移、Compose smoke 和安全扫描未成为 PR 门禁。
4. **存储**：JSON/Postgres/向量/对象/图谱的权威、事务、outbox 和恢复契约不清。
5. **可观察性**：内部 Trace/Cost 资产丰富，但外部 Metrics/Trace exporter、SLO 和告警缺失。
6. **安全**：API 用户认证、RBAC、限流、Secret、TLS 和审计不可篡改缺失。
7. **DR**：本地 ZIP 备份不覆盖完整工业部署；无定期 restore rehearsal 证据。
8. **E2E**：Playwright 跳过；无真实 Provider/平台/多书的 nightly 或 release acceptance。

## 21. 数据模型和协议一致性问题

### 21.1 通用 content 容器过载

`schemas/assets.py` 中大量类只有 `type` 常量；真实字段由 `BaseAsset.content` 和 `CONTENT_REQUIRED_FIELDS` 管理。这种方式便于快速扩展，却有以下后果：

- IDE/类型检查不能发现字段漂移；
- 同名资产在不同服务中可能有不同 shape；
- 状态转换和引用完整性只能在运行时发现；
- 2,000 行以上条件校验难以拆分所有权；
- API model、asset content 和数据库列容易形成三套契约。

### 21.2 核心对象关系未统一

建议重点收敛以下关系：

```text
Project -> Novel -> Volume -> Chapter -> Scene
GoalPlan -> WorkflowRun -> NodeRun -> AgentRun -> ModelCall
AgentRun -> InputArtifactRef[] -> OutputArtifactRef[] -> GateResult[]
EvidenceSpan -> KnowledgeCandidate -> KnowledgeAsset -> ProductionAsset
ChapterStateEvent -> StateSnapshot -> Canon/Character/Arc/Foreshadow projections
ReviewIssue -> RevisionTask -> Patch -> ReReview -> Gate
Release -> PlatformSubmission -> Receipt -> Compensation
```

当前这些对象大多存在，但引用字段、状态和权威服务不完全一致。

### 21.3 OS Envelope 不是一等持久对象

现有 Envelope 主要是 metadata normalizer/enforcer。最终协议需要固定 schema/version、project/workspace、task/run、input/output refs、source policy、permission、budget、deadline、idempotency key、trace、prompt/skill/model refs 和 acceptance contract，并由每个关键执行入口持久化引用。

### 21.4 项目隔离不闭合

当前验证失败的运行资产：

```text
data/runs/workflow-definition-local-smoke-workflow-9d4c2115.json
data/runs/agent_scheduler-lease.json
data/runs/workflow-definition-local-smoke-workflow-b6eae3a7.json
```

它们缺 `project_id`/`workspace_path`。若多书并行，类似全局运行资产会导致检索、成本、恢复和删除边界混乱。

## 22. 文档与代码失真情况

### 22.1 历史百分比口径不可直接沿用

`docs/reports/novel-os-gap-analysis.md` 曾给出 P0 86%-88%、产品 75%-80%、自治 65%-70%；`docs/reports/v6-final-current-state.md` 曾给出 86/100 和“最终测试通过”等声明。这些文档可能在其时间点、分支和既定切片口径下成立，但与本报告的最终蓝图分母不同，并且当前分支回归不是绿色。

### 22.2 V1 章节验收名称强于实际证据

`docs/reports/v1-chapter-sequence-slow-acceptance.md` 的真实证据是：10 章任务完成、16 类资产覆盖、Mock Provider、运行耗时和资产增长。报告自身的 `quality_trends.mode` 为 `artifact_coverage`。直接检查导出文件后，章节正文除标题外相同。因此它不能支持“稳定生成 10 章连续小说”的结论。

### 22.3 Long-chain proof 容易被误读

`modules/long_chain_proof/service.py` 的非 Provider 模式生成确定性 checkpoint/趋势，且 `publish_gate_summary.status=not_executed`。相关测试证明状态和报告协议，而非真实 50/100/300 章内容质量。

### 22.4 页面存在不等于控制能力存在

72 个页面路由证明 UI 覆盖广，但 Agent Center/Dispatch 共用页面、多个长篇控制台使用通用编辑器、缺 Source/Portfolio 深度页面，不能据路由数量判断 UI 完成。

## 23. 关键技术债务

| 债务 | 直接后果 | 处置方向 |
|---|---|---|
| 多执行平面 | 状态、门禁、恢复和验收不一致 | 建立唯一 Production Kernel |
| 通用 JSON Schema 过载 | 字段漂移、运行时才失败 | 渐进 typed domain model + schema compatibility |
| 超大 service/API | 隐式耦合、难以测试和维护 | 按领域 capability 拆模块内边界，不拆微服务 |
| 固定示例写入生产路径 | 假阳性能力、重复正文 | 限定为 fixture adapter；生产路径必须模型/人工输入驱动 |
| 每章全量回顾和目录扫描 | O(n) 写放大和延迟增长 | 事件增量、索引、快照和节奏化 recap |
| 规则分数无校准 | 误阻断/漏检、质量分不可信 | Golden + 人工标注 + Provider judge 校准 |
| 审批由客户端声明 | 可绕过付费模型/发布治理 | 服务端解析 ApprovalRequest + 用户身份 |
| JSON/Postgres 双权威模糊 | 查询、事务、恢复歧义 | 按运行模式明确 authority + outbox/projection |
| 发布 Adapter 分裂 | 审批/重试/回滚不一致 | 单一 adapter/receipt/compensation contract |
| CI/DR/安全薄弱 | 无法安全发布和恢复 | Phase 0/6 硬化并成为门禁 |

## 24. 关键阻塞关系

```text
当前回归不绿 / 项目隔离失败
  -> 无法建立可信基线

协议与状态不统一
  -> Context/Agent/Workflow/Chapter Bus 无法成为唯一闭环

Topic/World/Character 固定样例
  -> 大纲和章节即使运行也不代表目标作品

长篇状态抽取与质量评测未校准
  -> 无法判断 30/100 章是否稳定

审批身份与 Provider/发布 Adapter 不可信
  -> 无法开展真实付费 Provider 和平台验收

真实长篇未通过
  -> Portfolio 自动调度和多书并行没有合格工作负载
```

正确顺序不是先增加更多 Agent，而是先修复基线、统一协议和生产内核，再补真实内容与长篇质量，之后才提高自治和并行度。

## 25. 当前成熟度评分

### 25.1 权重和结果

| 维度 | 权重 | 得分 | 加权分 | 主要证据与扣分原因 |
|---|---:|---:|---:|---|
| 功能覆盖度 | 15% | 64 | 9.60 | 模块/Schema/UI 覆盖广；Creative/Meaning/Ending/Trope/Security 缺失 |
| 功能成熟度 | 12% | 43 | 5.16 | 多数 L2-L3；固定样例、启发式和测试夹具多 |
| 系统集成度 | 13% | 51 | 6.63 | 单章链、Context、ReviewIssue 已接入；四个执行平面分裂 |
| 长篇生产闭环 | 15% | 29 | 4.35 | 10 章正文重复；50/100/300 为状态/Mock proof；性能退化 |
| Agent 自治能力 | 10% | 45 | 4.50 | 有界 Harness 较强；Goal decomposition/持续 loop 缺失 |
| 质量与评测能力 | 10% | 46 | 4.60 | Gate/Issue/Eval 广；Golden/人工/真实 Provider 校准缺失 |
| UI 和人工治理 | 7% | 49 | 3.43 | 页面/API 广；核心控制台深度与 E2E 不足 |
| 工程生产成熟度 | 8% | 40 | 3.20 | Compose/trace/tests 有基础；回归、CI、安全、DR、性能不足 |
| 多小说并行能力 | 5% | 23 | 1.15 | Portfolio 计划存在，自动 dispatch 明确关闭 |
| 反馈和自我优化 | 5% | 38 | 1.90 | 反馈/提案存在；污染、因果、在线实验闭环不足 |
| **综合** | **100%** |  | **44.52 -> 45** | **最终蓝图口径** |

### 25.2 不确定性

评分不确定区间约 **+/-5**：

- 本次未使用真实外部 Provider、官方平台账户或生产数据，相关能力只能基于代码和测试判断；
- 全量 `make test` 未取得完整结束报告，只能根据 fail-fast 和聚焦结果判定“当前不是绿色基线”；
- `.local` 中存在多批历史运行数据，未将所有报告逐一重放；
- 某些可选基础设施只有配置和单元测试，没有部署运行证据。

即使将所有证据不足项按乐观口径处理，也不足以消除真实长篇、自治、平台和多书并行四个核心缺口。

### 25.3 表面存在但未闭环的典型能力

- `WorldBible`/`CharacterCard` 存在，但当前生成内容固定；
- 10 章资产存在，但正文重复；
- Long-chain report 存在，但未执行发布门禁和真实章节生成；
- Agent Center 存在，但没有自治 Planner，且 Center/Dispatch 共页；
- Portfolio 资产存在，但自动调度关闭；
- Platform Adapter 名称存在，但是手工规则或 fake client；
- Golden/Calibration schema 存在，但没有生产数据集；
- Approval 字段存在，但 Provider/UI 路径可由客户端自报。

## 26. 距离最终 Novel OS 的总体判断

### 26.1 当前定位

当前 Novel Forge 是 **早期 Novel OS runtime + 较广的生产治理组件库**，而不是最终 Autonomous Novel OS。它已经越过“单 Prompt 小说生成器”的阶段，但尚未越过“内容有效性、状态可信性和持续自治”的分界线。

### 26.2 是否能稳定生成一本精品长篇

**不能据现有证据认定具备。** 系统能稳定生成和管理单章级资产链，但已检查的 10 章正文重复，世界/人物上游固定，长篇检测与 Eval 未经真实数据校准，当前回归基线也不绿。要回答“可以”，至少需要 30 章真实差异化正文通过 Canon、人物、时间线、伏笔、质量、成本和人工盲评验收。

### 26.3 是否能并行生产多本精品长篇

**不能。** Portfolio 当前只产生规划/建议，`book_level_scheduler_enabled=False`、`automatic_dispatch=False`，没有三书并行、隔离、资源调度和恢复证据。

### 26.4 关键分界点

从“小说生成平台”升级为“Novel Operating System”的关键分界点不是新增页面或 Agent 名称，而是：

> 一个项目能经唯一 Production Kernel，在不可绕过的 Envelope、Context、来源、预算、质量和审批约束下持续生成内容；每章变化能可靠归约到结构化长篇状态；失败可恢复；效果可用 Golden、人工和真实反馈验证；同一协议可安全复制到多作品。

## 27. 最优先解决的 16 个问题

| 顺序 | 问题 | 优先级 | 为什么先做 | 完成信号 |
|---:|---|---|---|---|
| 1 | 恢复绿色回归和清洁工作区校验 | P0 | 所有后续证据的前提 | 全量测试/validate/skills/lint 通过，0 个无项目运行资产 |
| 2 | 统一 ExecutionEnvelope 和核心引用协议 | P0 | 消除调用绕过和审计缺口 | 所有生产入口 contract test 强制 envelope |
| 3 | 建立唯一 Production Kernel | P0 | 解决四个执行平面的状态分裂 | 单一 Workflow/Run/Task/Agent 状态图 |
| 4 | 移除生产路径固定 Topic/World/Character | P0 | 当前内容无效的直接根因 | fixture 与 production adapter 分离，目标驱动输出 |
| 5 | 修复 Context/来源门禁迁移 | P0 | 当前旧夹具和调用链被新 gate 阻断 | 所有阶段 fail-closed 且回归绿色 |
| 6 | 分开资产完整性和内容质量验收 | P0 | 防止重复正文被判成功 | body uniqueness/progression/human gate 成为 release blocker |
| 7 | 限制每章写放大和全目录扫描 | P0 | 10 章性能已不可持续 | p95 稳定、每章证据写入有预算 |
| 8 | 建立 typed 长篇 StateEvent/Snapshot reducer | P0 | Canon/Character/Timeline 可信性的基础 | replay 可重建且冲突/状态有证据和置信度 |
| 9 | 建立 Golden + Human Calibration | P1 | 当前质量分不可解释 | 版本化数据集、标注一致性、阈值发布 |
| 10 | 执行 10/30 章真实 Provider 内容验收 | P1 | 证明精品长篇最小闭环 | 差异化、推进、状态、质量、成本全部过门禁 |
| 11 | 服务端验证 ApprovalRequest | P1 | 防止 Provider/发布治理被伪造 | 请求只传 approval ref，服务端校验身份/范围/时效 |
| 12 | 合并发布 Adapter/Receipt/Compensation | P1 | 为真实平台和反馈提供稳定边界 | sandbox adapter contract/E2E 通过 |
| 13 | 增加受限 Goal Planner 和 recurring controller | P1 | 从 A2 执行器进入 A3 自治 | 计划版本、预算、停止/接管和恢复可审计 |
| 14 | 建设 Source/Canon/Eval/Portfolio 深度控制台 | P1 | UI 从展示升级为治理 | 浏览器 E2E 能完成审批、冲突处理、回放 |
| 15 | 明确工业模式存储权威和 outbox | P1 | 消除双写和恢复歧义 | 故障注入下无不可解释状态 |
| 16 | 三书并行、CI、安全和 DR 硬化 | P2 | 规模化前最后门槛 | 多书隔离、RBAC、restore rehearsal、发布门禁全部通过 |

## 28. 附录：证据索引

### 28.1 蓝图与治理

- `docs/blueprint/autonomous-novel-os-full-blueprint.md`
- `docs/blueprint/novel-os-project-blueprint.md`
- `AGENTS.md`
- `docs/09-skills/agent-skill-map.md`
- `skills/novel-os-engineering-audit/SKILL.md`

### 28.2 Schema、存储和协议

- `src/novel_forge/schemas/base.py`：`BaseAsset`、`CONTENT_REQUIRED_FIELDS`、条件验证。
- `src/novel_forge/schemas/assets.py`：289 类资产声明，包括 Canon、Context、ReviewIssue、Agent、Portfolio、Approval、Ledger。
- `src/novel_forge/storage/local.py`：版本化 JSON、写入和项目隔离守卫。
- `src/novel_forge/storage/postgres.py`、`src/novel_forge/storage/migrations/`：可选投影和数据库迁移。
- `src/novel_forge/modules/os_envelope/service.py`：Envelope 规范化/门禁。

### 28.3 知识、来源和 Context

- `src/novel_forge/modules/source_intake/`：policy、risk、snapshot、connector、diff、stale/quarantine、runtime gate。
- `src/novel_forge/modules/analysis/service.py`：拆解和分析。
- `src/novel_forge/modules/mkaos/`、`mkaos_ingestion/`、`mkaos_model_extraction/`、`mkaos_quality/`、`mkaos_lineage/`。
- `src/novel_forge/modules/context_builder/service.py`：stage profile、选择、预算、来源隔离、Actual Sent Context、Replay/Diff。

### 28.4 生产、长篇和质量

- `src/novel_forge/workflows/pipeline.py`：旧生产链。
- `src/novel_forge/modules/chapter_production_bus/service.py`：12 步章节总线和 V1 资产覆盖。
- `src/novel_forge/modules/topics/service.py`、`worldbuilding/service.py`、`characters/service.py`：前置创作实现及固定样例证据。
- `src/novel_forge/modules/outline/service.py`、`chapter_plan/service.py`、`drafting/service.py`、`editor/service.py`。
- `src/novel_forge/modules/longform_stability/service.py`、`longform_recap/service.py`、`long_chain_proof/service.py`。
- `src/novel_forge/modules/review_issue/service.py`、`content_quality_loop/service.py`、`quality_eval/service.py`、`evaluation_center/service.py`。

### 28.5 Agent、发布、反馈、Portfolio 和 UI

- `src/novel_forge/modules/agent_registry/service.py`、`agent_runs/service.py`、`agent_scheduler/`、`operation_transactions/service.py`。
- `src/novel_forge/modules/model_router/service.py`、`src/novel_forge/api/provider_adapters.py`。
- `src/novel_forge/modules/publishing/`、`publishing_feedback_adapters/`、`feedback/`、`feedback_backflow/`。
- `src/novel_forge/modules/portfolio_os/service.py`。
- `web/admin/app/` 和 `web/admin/app/features/content-intelligence/ContentIntelligencePages.tsx`。

### 28.6 验收和反证

- `docs/reports/v1-chapter-sequence-slow-acceptance.md`：10 章资产覆盖、Mock Provider、耗时和增长。
- `.local/v1-chapter-sequence-acceptance-run3`：导出正文重复的直接运行证据。
- `tests/integration/test_novel_os_12_chapter_industrial_pressure.py`：当前被 ReviewIssue 阻断。
- `tests/integration/test_long_chain_50_chapter_content_intelligence.py`：确定性状态 proof，非真实章节 proof。
- `tests/unit/test_provider_runtime_guard.py`：Provider 硬停局部通过。
- `tests/unit/test_agent_scheduler.py`、`test_context_and_production_chain.py`：当前来源门禁/章节序列回归失败证据。
- `.github/workflows/web-cockpit-smoke.yml`：当前唯一发现的 CI workflow。

本报告只修改审计文档，不修改业务代码、数据库迁移、API 或生产配置。补全方案见 `docs/plans/novel-os-final-blueprint-completion-plan.md`。
