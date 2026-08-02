# Autonomous Novel OS Architecture Closure Epic

更新时间：2026-08-02  
目标分支：`feat/v7-content-intelligence-and-longform-proof`  
审计代码基线：`aa991b53039cdf2e4e7911d4483052b9a6a752a1`  
文档状态：`TARGET_ARCHITECTURE_AND_IMPLEMENTATION_PROGRAM`  
实现证明：本文不构成代码、迁移、测试或生产验证证明。

## 1. Epic 目标

本 Epic 用于完成 Autonomous Novel OS 的整体架构闭合。目标不是一次性实现所有未来功能，也不是先清空全部 Legacy LocalStorage，而是固定后续最容易造成系统级返工的核心契约：

- 正式生产状态的唯一 Authority；
- 统一的 Operation、Saga、Attempt、Lease、Fence、Effect、Receipt 执行模型；
- 统一的 Asset、AssetVersion、Dependency、Decision、Activation、Supersession 模型；
- Book、Volume、Arc、ChapterGroup、Chapter 的分层规划与委托模型；
- Canon、ChapterOutcome、StoryState、Reducer、Snapshot、Replay 模型；
- 所有模型任务共享的 ContextManifest 与 ActualSentContext 模型；
- Agent Candidate 与 Authority Commit 的严格边界；
- Provider、Codex CLI 和外部平台调用的统一 Production Execution Plane；
- 质量证据、校准、Release Gate 和正式发布决策模型；
- Authority-only 部署、安全、恢复、可观测性和迁移治理。

架构闭合后的核心判断是：新增 Agent、Provider、质量评估、规划层级、平台适配器或多书调度时，不再需要重构 Authority、Saga、AssetVersion、StoryState、Context、Agent 和 Provider 的基础边界。

## 2. 非目标

本 Epic 不要求在 Architecture Closure Gate 前完成：

- 十个真实 Provider；
- 全部官方发布平台 SDK；
- 十本小说并行生产；
- 百万字真实长篇证明；
- 完整多租户 SaaS；
- 全量历史数据迁移；
- 所有 Web Admin 页面产品化；
- Reader Outcome 商业概率校准；
- 所有 Legacy 文件、缓存和开发工具删除。

这些能力可以在架构闭合后沿稳定契约逐步实现。

## 3. 目标架构

```text
Product / Operator / API / UI
                |
Application Commands and Queries
                |
Domain Authorities
Project / Source / MKAOS / Book Design / Planning
Chapter / Longform / Quality / Publishing
                |
Command Kernel and Production Execution Plane
Operation / Saga / Attempt / Lease / Fence
ExternalEffect / Receipt / Reconciliation / Outbox
                |
Asset and Evidence Authority
AssetVersion / Snapshot / Decision / Lineage / Gate
                |
Infrastructure
PostgreSQL / Object Store / Queue / Vector Store
Provider Backends / External Platforms / Observability
```

正式生产链统一为：

```text
Command
→ Authority Admission
→ Operation
→ Saga
→ Attempt
→ Frozen Input and Context Build
→ Production Execution Gateway
→ External Effect and Receipt
→ Candidate
→ Domain Validation
→ Authority Decision
→ Asset Commit
→ State Reduce
→ Projection / Outbox / Next Operation
```

任何模块不得绕开这条主干自行推进正式生产状态。

## 4. Architecture Closure 原则

1. **一个正式状态只有一个 Authority 和一个正式 Writer。**
2. **所有不确定执行复用同一套 Production Execution Plane。**
3. **所有正式内容对象使用不可变 AssetVersion。**
4. **Agent 只能产生 Candidate，Authority 才能 Commit。**
5. **所有生产上下文必须冻结、版本化并保留 ActualSentContext。**
6. **已 Final Release 的小说历史不可静默重写。**
7. **重规划必须产生 PlanDiff、ImpactAnalysis 和 EffectiveRange。**
8. **Canon 与动态 StoryState 分离，状态更新必须通过可重放 Reducer。**
9. **Provider、CLI、平台 API 和凭据不能进入业务领域模块。**
10. **设计、代码存在、Fixture 证明、真实运行证明和生产证明必须分开表述。**

## 5. 工作包

| ID | 工作包 | 核心交付 |
|---|---|---|
| AC-00 | 仓库与 HEAD 完整性 | 同一 SHA 可导入、迁移、构建、启动和测试 |
| AC-01 | 架构原则与 ADR | 固定不可逆架构决策和例外机制 |
| AC-02 | 领域边界与依赖规则 | Bounded Context、依赖方向和所有权地图 |
| AC-03 | Authority 与存储边界 | PostgreSQL、Object Store、Local、Vector 的权威边界 |
| AC-04 | Project、Workspace、Book 与 Scope | 统一身份、隔离、权限和生产作用域 |
| AC-05 | Command Kernel 与执行语义 | Operation/Saga/Attempt/UNKNOWN/Cancel/Recovery 闭合 |
| AC-06 | 统一资产版本模型 | AssetVersion、Dependency、Decision、Activation、Supersession |
| AC-07 | 分层规划 Authority | Book→Volume→Arc→ChapterGroup→Chapter 计划契约 |
| AC-08 | Canon 与 StoryState | ChapterOutcome、Reducer、Snapshot、Replay、Correction |
| AC-09 | Context Builder | StageProfile、ContextManifest、ActualSentContext、预算与隔离 |
| AC-10 | Source 与 MKAOS Authority | 来源、资格、知识资产、KnowledgePack 和使用反馈边界 |
| AC-11 | Agent Collaboration | WorkOrder、Scope、Candidate Graph、Conflict、Decision、Commit |
| AC-12 | Provider 与外部执行 | Backend Registry、RouteSnapshot、Receipt、Cost 和资格治理 |
| AC-13 | Quality、Eval 与 Release | Judge Evidence、Calibration、ReviewIssue 和 Gate Aggregate |
| AC-14 | Book Production Supervisor | 全书 Root Saga、Cursor、委托、Recap、Replan 和完成治理 |
| AC-15 | API、事件与契约 | Command/Query API、Event Envelope、Outbox 和版本兼容 |
| AC-16 | 部署、运维与安全 | Authority-only 拓扑、健康、池化、备份、身份和审计 |
| AC-17 | Legacy 迁移与退役 | 分类、导入、验证、冻结 Writer、观察和删除 |
| AC-18 | Architecture Fitness Tests | 自动阻止跨层依赖、直连 Provider、Legacy 写入和契约漂移 |
| AC-19 | 文档与变更治理 | Blueprint、ADR、Current State、Report 和 PR 变更纪律 |

详细索引见 [`README.md`](README.md)。

## 6. 实施阶段

### Phase 0：基线可信

范围：AC-00、AC-01、AC-18 的第一批检查。

必须先解决当前审计发现的 HEAD 完整性风险。所有后续工作必须绑定一个可本地 checkout、可导入、可运行迁移、可启动 API/Worker 的完整 SHA。

退出条件：

```text
head_integrity_verified=true
current_head_import_verified=true
current_head_migration_chain_verified=true
architecture_baseline_recorded=true
```

### Phase 1：系统共同骨架

范围：AC-02、AC-03、AC-04、AC-05、AC-06。

固定领域边界、数据所有权、统一作用域、Command Kernel 和 AssetVersion。此阶段优先于继续增加新的 Authority 模块。

### Phase 2：小说核心状态模型

范围：AC-07、AC-08、AC-09、AC-10。

固定分层规划、Canon/StoryState、Context Builder、Source/MKAOS 生产输入。完成后才具备低返工建设全书自治的基础。

### Phase 3：智能执行与质量决策

范围：AC-11、AC-12、AC-13。

固定 Agent Candidate、Provider Gateway、Judge Evidence、Calibration 和 Release Gate。

### Phase 4：全书生产与运行拓扑

范围：AC-14、AC-15、AC-16。

形成 Book Production Supervisor、异步 API/Event 契约和 Authority-only 部署。

### Phase 5：迁移和架构证明

范围：AC-17、AC-18、AC-19，以及 L3/L10/L30 证明。

Architecture Closure 不是纸面设计完成，而是需要通过真实迁移、故障注入和连续章节生产验证。

## 7. 跨工作包关键路径

```text
AC-00
→ AC-01 / AC-18 foundation
→ AC-02 / AC-03 / AC-04
→ AC-05 / AC-06
→ AC-07 / AC-08 / AC-09 / AC-10
→ AC-11 / AC-12 / AC-13
→ AC-14 / AC-15 / AC-16
→ AC-17 full migration waves
→ L3 → L10 → L30
```

禁止绕过 AC-00 继续扩大未验证的 migration registry、Authority imports 或 worker surface。

## 8. 统一交付物要求

每个 AC 工作包必须交付：

1. ADR：背景、决策、替代方案、后果、例外；
2. 实施计划：按依赖排序的 Work Package；
3. 代码位置：当前证据路径、目标路径、禁止位置；
4. 迁移脚本规范：SQL/Python/校验/回滚或明确无数据迁移；
5. 测试矩阵：单元、集成、PostgreSQL、故障注入、架构、验收；
6. Acceptance Gate：可机器检查的完成条件；
7. 当前状态更新：只在实际验证后更新证明标志。

迁移文件不得在文档中预占具体序号。实施时必须从当前唯一 migration head 分配：

```text
src/novel_forge/storage/migrations/versions/v<date>_<sequence>_<slug>.py
```

## 9. 证据等级

| 等级 | 含义 | 可使用的声明 |
|---|---|---|
| D0 | 文档设计 | architecture_defined |
| D1 | 代码存在并可导入 | implementation_present |
| D2 | 单元/静态测试 | locally_verified |
| D3 | PostgreSQL/沙箱集成 | integration_proven |
| D4 | 当前 SHA 完整部署验证 | deployment_verified |
| D5 | 真实 Provider/平台 | external_execution_proven |
| D6 | 长篇、多书、恢复和运维证明 | production_verified |

D0-D3 不得被表述为真实 Provider 或生产证明。

## 10. 总体验收 Gate

Architecture Closure Gate 只有在下列条件全部满足时才可通过：

### Authority

- 每类正式生产状态具有唯一 Owner 和 Writer；
- 生产模式禁止 LocalStorage 正式写入和静默 fallback；
- Object Store、Vector Store 和缓存不能反向覆盖 Authority。

### Execution

- 所有正式副作用复用 Operation/Saga/Attempt；
- Retry、Timeout、Cancel、UNKNOWN、Late Result、Receipt 和 Reconciliation 语义统一；
- 不存在第二套生产任务状态机。

### Assets and Planning

- 核心内容使用不可变 AssetVersion；
- Book、Volume、Arc、ChapterGroup、Chapter 契约稳定；
- 已发布历史冻结，重规划具有 Diff、Impact 和 EffectiveRange。

### Longform and Context

- ChapterOutcome 和 StoryState Reducer 可重放；
- Canon 与动态状态分离；
- 所有正式模型输入经过 Context Builder 并可审计 ActualSentContext。

### Agent and Provider

- Agent 只产生 Candidate；
- Provider/CLI/外部平台由统一 Gateway 调用；
- Route、Budget、Timeout、Cancel、Receipt 和 Cost 具有正式证据。

### Quality and Release

- Judge Evidence 结构统一；
- 未校准结果不得声称概率；
- Final Release 必须通过统一 Gate Aggregate。

### Operations

- Authority-only 栈在无 Legacy 工作区条件下启动；
- Worker 具备租约、恢复、健康投影和故障注入证据；
- PostgreSQL 具备连接池、超时、备份、PITR 和迁移演练方案；
- 生产 API 具备真实身份、Scope 和 RBAC。

### Governance

- Architecture Fitness Tests 在 CI 中阻止架构违规；
- 当前文档、ADR 和代码证据一致；
- 完成至少 L3 和 L10，开始 L30 Arc 级证明。

## 11. Architecture Closure 后的下一阶段

通过本 Epic 后，下一阶段进入：

```text
Autonomous Book Production V1
→ Real Provider Single-Book Proof
→ L30 / L100 / L300 / L1M
→ 3 / 5 / 10 Books Portfolio Proof
→ Platform Feedback and Commercial Operations
```

在 Architecture Closure 通过前，不应将增加更多孤立功能、更多 UI 页面或更多 Legacy 兼容层作为主要进度指标。