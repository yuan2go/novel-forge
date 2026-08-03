# Autonomous Novel OS Architecture Closure Epic

更新时间：2026-08-02  
目标分支：`feat/v7-content-intelligence-and-longform-proof`  
审计代码基线：`aa991b53039cdf2e4e7911d4483052b9a6a752a1`  
文档状态：`SIX_TRACK_VERTICAL_CLOSURE_PROGRAM`  
实现证明：本文定义下一阶段执行程序，不构成代码、迁移、测试、真实 Provider 或生产验证证明。

## 1. Epic 决策

Architecture Closure 不再按照 AC-00 至 AC-19 二十个工作包横向并行实施。

AC-00 至 AC-19 继续保留，作为：

- 架构决策参考；
- 代码位置清单；
- 迁移约束；
- 测试与验收检查表；
- Reviewer 审计索引。

它们不再是可以独立排期、独立宣布完成的开发单元。

后续实施统一收敛为六条架构轨道：

```text
Track A — Trusted Baseline And Governance
Track B — Shared Authority Kernel And Storage
Track C — Novel Domain And Context
Track D — Intelligence, Execution And Quality
Track E — Autonomous Book Runtime And Operations
Track F — Migration, Long-form And Scale Proof
```

每条轨道按纵向切片推进。一个有效切片必须从真实入口开始，经过正式执行和领域决策，最终落到 PostgreSQL Authority、查询投影、恢复证据和当前 SHA 测试结果。

禁止以“Schema 已增加”“接口已定义”“页面已存在”“Fixture 已通过”代替纵向闭环。

## 2. Epic 目标

本 Epic 的目标不是一次性实现所有未来功能，也不是先删除全部 Legacy LocalStorage，而是形成一套能够支撑后续全书自治、长篇证明和多书扩展的稳定骨架：

- 一个正式状态只有一个 Owner 和一个 Writer；
- PostgreSQL 是正式生产 Authority；
- Object Store 保存大型不可变内容，Vector/Search 是可重建投影；
- 系统只有一套正式 Command Kernel 和 Production Execution Plane；
- 内容资产采用统一元数据与强类型领域 Payload，而不是万能 JSON；
- Book Design、Planning、Chapter Production、Longform State、Quality 和 Publishing 职责清晰；
- Context Compiler 负责编译上下文，不成为拥有所有业务规则的 God Service；
- Agent 和 Provider 只产生 Candidate，领域 Authority 才能 Commit；
- Book Production Coordinator 只协调 Root Saga 和 Cursor，不直接生成或修改领域状态；
- Production Quality Gate 与 Evaluation And Calibration Lab 分离；
- Legacy 迁移通过纵向业务链逐波完成，不维持长期双写；
- Policy Registry 只管理共同生命周期，不解释全部领域规则；
- Asset Registry 只管理共同元数据，不替代强类型领域 Schema；
- Book Coordinator 只维护 Root Saga、Cursor 和子 Operation；
- Agent Center 不重新实现 Workflow、Scheduler、Provider 或 Commit；
- Production Quality Gate 与 Evaluation And Calibration Lab 使用显式 Judge 晋升边界；
- 每个关键架构决策都有 Architecture Fitness Test 保护。

架构闭合后的判断标准是：新增 Provider、Agent、质量评估、规划节点、发布平台或多书调度时，不需要重构 Authority、Execution、AssetVersion、StoryState、Context 和 Commit 边界。

八项最小稳定契约及 God Service 防线见 [`minimal-stable-contracts.md`](minimal-stable-contracts.md)。

## 3. 非目标

Architecture Closure Gate 前不要求完成：

- 多个真实 Provider 的全面接入；
- 全部官方发布平台 SDK；
- 十本小说并行生产；
- 百万字真实长篇证明；
- 完整多租户 SaaS；
- 全量历史数据迁移；
- 所有 Web Admin 页面产品化；
- Reader Outcome 商业概率校准；
- 删除所有开发 Fixture、缓存和本地导入工具。

当前阶段也不采用：

- 多微服务拆分；
- 全系统 Event Sourcing；
- 所有操作 Saga 化；
- 所有领域对象统一塞入无约束 JSONB；
- 每个领域独立 Worker 服务；
- 长期 PostgreSQL/LocalStorage 双写。

## 4. 目标系统形态

当前推荐形态是：

```text
Modular Monolith
+ Process-separated Workers
+ PostgreSQL Authority
+ Object Store
+ Durable Execution
+ Rebuildable Search/Vector Projections
```

目标分层：

```text
Operator / Web / CLI / API
              |
Application Commands, Queries And Coordinators
              |
Domain Modules
Project / Book Design / Planning / Knowledge And Context
Chapter Production / Longform State / Quality / Publishing
              |
Shared Authority Kernel
Scope / Policy Registry / Asset Registry
Operation / Saga / Attempt / Lease / Fence / Outbox
              |
Production Execution Plane
Model / Local Agent / External Action
Route / Budget / Timeout / Cancel / Receipt / Reconcile
              |
Infrastructure
PostgreSQL / Object Store / Queue / Vector / Observability / Secrets
```

正式生产链统一为：

```text
Command
→ Admission And Scope Validation
→ Transaction Command / Durable Job / Saga
→ Frozen Input And Context Compile
→ Production Execution Plane when needed
→ External Effect And Receipt when needed
→ Candidate
→ Domain Validation
→ Authority Decision
→ Asset/State Commit
→ Projection And Outbox
→ Query / Recovery / Next Command
```

## 5. 纵向切片完成定义

任何 Track Slice 必须至少覆盖：

1. **入口**：真实 CLI、API、Worker 或父级 Saga 委托；
2. **身份和作用域**：`project_id`、`workspace_id`、`book_id`、Principal、Scope；
3. **命令语义**：幂等键、Request Digest、定义版本、预算和截止时间；
4. **正式执行**：按复杂度选择 Transaction Command、Durable Job、Saga 或 External Effect；
5. **领域规则**：强类型输入、验证、Candidate、Decision；
6. **Authority Commit**：PostgreSQL 中不可变版本或正式状态转换；
7. **大型内容**：通过 Object Store 引用和内容哈希持久化；
8. **查询投影**：API/UI/Operator 可读取最终状态和阻塞原因；
9. **失败恢复**：至少覆盖重复请求、事务回滚、Worker 重启或 External UNKNOWN 中适用的场景；
10. **验证证据**：当前 SHA 的单元、PostgreSQL 集成、架构和必要的外部执行测试；
11. **文档更新**：只更新少量权威 Current State、Roadmap 和证明报告。

以下情况不构成纵向切片完成：

- 只增加数据库表；
- 只增加 Pydantic Schema；
- 只创建接口或抽象基类；
- 只创建 Web 页面；
- 只通过 Scripted Provider Fixture；
- 只记录历史提交的测试数量；
- 只完成 LocalStorage 路径，没有 Authority Commit。

## 6. 六条架构轨道

### Track A — Trusted Baseline And Governance

**目标：** 建立可信仓库基线和防止架构再次漂移的自动治理。

对应 AC 参考：AC-00、AC-01、AC-02、AC-18、AC-19。

#### Slice A1：Repository Integrity

```text
Repository HEAD
→ module/migration/worker/test manifest
→ import smoke
→ migration registry check
→ console script target check
→ required test count check
→ CI report bound to exact SHA
```

交付：

- 修复或删除无法解析的 Project、Task、Source、MKAOS Authority 引用；
- 唯一 migration head；
- 可执行的 module、worker、migration、test manifests；
- 当前 SHA 的 Python import 和 compile 证明。

#### Slice A2：Current-SHA Validation Baseline

```text
exact SHA checkout
→ unit/architecture tests
→ PostgreSQL integration
→ API and worker startup
→ Web build
→ Docker config/build
→ immutable verification report
```

#### Slice A3：ADR And Fitness Baseline

固化并自动检查：

- 模块化单体；
- PostgreSQL 单一 Authority；
- 禁止生产 LocalStorage 写入和静默 fallback；
- 禁止 Domain 依赖 Provider SDK、FastAPI、Next.js 或具体 Repository；
- 禁止未注册的直接模型调用；
- 禁止零测试匹配被当作通过。

**Track A Gate：**

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
```

Track A 未通过前，其他轨道只能进行设计和缺口分析，不得继续扩大 Authority Surface。

---

### Track B — Shared Authority Kernel And Storage

**目标：** 固定所有领域共享的身份、数据所有权、资产版本和执行语义，并形成一个最小 Authority-only 纵向切片。

对应 AC 参考：AC-02、AC-03、AC-04、AC-05、AC-06、AC-15、AC-16、AC-17、AC-18。

#### Slice B1：Project/Book Scope Authority

```text
Create Project/Book Command
→ scope and identity validation
→ PostgreSQL commit
→ duplicate replay
→ query projection
→ production mode without LocalStorage
```

必须形成统一：

- Project、Workspace、Book 身份；
- Principal 和 Service Identity；
- Project/Book Scope；
- Production Profile；
- Runtime Policy；
- Release Identity。

#### Slice B2：Typed Asset Registry

建立：

```text
Asset
AssetVersion
AssetDependency
AssetDecision
AssetActivation
AssetSupersession
AssetEvidence
```

但使用“统一元数据 + 强类型领域 Payload”，禁止退化成任意 `asset_type + payload_json`。

至少用一个真实领域资产证明：

```text
BookDesign Candidate
→ validation
→ AssetVersion
→ approval
→ activation
→ supersession
→ dependency query
```

#### Slice B3：Execution Classification And Kernel

正式区分：

| 类型 | 场景 |
|---|---|
| Transaction Command | 单事务、确定性、短写入 |
| Durable Job | 异步可重试、无复杂跨步骤协调 |
| Saga | 多步骤、跨事务、需要恢复和补偿 |
| External Effect | Provider、CLI、平台 API 等不确定副作用 |

Command Kernel 统一处理：

- idempotency；
- Request Digest；
- Attempt；
- Lease/Fence；
- UNKNOWN；
- Cancel/Late Result；
- Receipt；
- Outbox；
- Recovery。

#### Slice B4：Storage And Budget Evidence

固定：

- PostgreSQL 元数据和正式状态；
- Object Store 大对象引用、Hash、Retention；
- 可重建 Vector/Search 投影；
- Budget Reservation、Actual Usage 和 Cost Ledger；
- connection pool、timeout 和 readiness 约束。

Object Store 的最小生命周期必须包含 `content_hash`、`object_ref`、`content_type`、`size`、`retention_class`、`encryption_metadata`、Orphan Detection 和通过 External Effect 执行的 GC；扫描器不得直接物理删除对象。

#### Slice B5：Minimal Authority-only Runtime

在进入小说领域建模前，先运行最小生产组合：

```text
Authority API
Authority Worker
PostgreSQL Authority
Object Store
Transactional Outbox
Reconciliation
Legacy write disabled
Silent fallback disabled
```

初始 Worker 按执行性质分为 `authority-worker`、`execution-worker`、`integration-worker`、`maintenance-worker`，不按领域无限拆进程。权威关系固定为：PostgreSQL 保存 Task/State Authority，Outbox 是可靠通知源，Queue/Celery/Redis 仅负责投递，Worker 是获得 Lease/Fence 后回读 Authority 的消费者。

每个 Track B Slice 同时完成 Legacy Cutover 记录：`legacy_source`、`authority_target`、`import`、`validation`、`writer_cutover`、`reader_compatibility`、`retirement_deadline`。不得把关键 Writer 切换推迟到 Track F。

**Track B Gate：**

```text
project_book_scope_authority_proven=true
typed_asset_lifecycle_proven=true
execution_classification_enforced=true
authority_only_minimal_slice_proven=true
production_legacy_write_blocked=true
duplicate_replay_proven=true
query_projection_proven=true
```

---

### D0 — Real Provider Qualification Probe

D0 位于 `Track B → D0 → Track C`。它只验证一个 Provider、一个显式配置的模型和一个最小结构化能力：

```text
Qualified Capability Command
→ RouteSnapshot
→ External Effect
→ authentication/request id/timeout
→ Provider Receipt + usage + cost
→ retrieve/query + cancel
→ UNKNOWN reconciliation + late result
→ restart recovery
```

D0 必须保存 Provider request identity、backend/model/version、route policy、timeout、能力声明、raw/normalized usage、Provider/calculated cost、Receipt 和 request/response Object Reference。D0 不是小说质量或章节证明；缺少凭据时只允许 `BLOCKED_MISSING_CREDENTIALS`，Fixture Gate 必须保持 false。

```text
real_provider_auth_proven=true|false
provider_request_receipt_proven=true|false
provider_usage_proven=true|false
provider_cost_proven=true|false
provider_timeout_query_cancel_behavior_recorded=true|false
unknown_reconciliation_proven=true|false
```

---

### Track C — Novel Domain And Context

**目标：** 固定精品长篇生产所需的领域模型和确定性状态推进，不接入全书自治前先证明领域语义稳定。

对应 AC 参考：AC-06、AC-07、AC-08、AC-09、AC-10、AC-13、AC-18。

本 Track 明确三层知识边界：

```text
Source = 来源、授权、风险、资格
Material = 可用于创作的事实、案例、文化和场景素材
Knowledge = 指导设计、写作和评审的方法、规则和模板
```

#### Slice C1：Book Design To Active Plan

```text
Book Intent
→ BookDesign Candidate
→ validation/approval/activation
→ BookPlan Candidate
→ PlanVersion activation
→ dependency and impact query
```

Book Design 负责“写什么和为什么值得读”；Planning 负责“如何分层推进”。

规划内部使用受控 `PlanningNode`：

```text
BOOK / VOLUME / ARC / CHAPTER_GROUP / CHAPTER
```

标准层级可选，但不允许任意动态类型破坏契约。

#### Slice C2：ChapterOutcome To StoryState Replay

```text
Final ChapterOutcome
+ Approved Canon Changes
+ Previous StoryState Snapshot
+ Reducer Version
→ New StoryState Snapshot
→ replay checksum verification
```

明确唯一语义：

- ChapterOutcome：章节造成的结构化变化声明；
- Canon：已批准的稳定事实；
- StoryState：当前动态状态投影；
- Recap：只读分析和压缩，不是正式事实源。

#### Slice C3：Context Compiler

```text
Domain Context Requirement
→ frozen AssetVersions
→ Canon/StoryState
→ eligible Source/Material/KnowledgePack
→ selection
→ token allocation
→ compression
→ validation
→ ContextManifest + ActualSentContext
```

Context Compiler 不拥有领域业务规则；各领域声明需要什么，Compiler 负责编译、预算、隔离和留证。

Cache 与失效键至少固定 `context_input_hash`、`CompilationVersion`、`ContextDependency` 和 `ContextInvalidation`。依赖版本变化时保留历史 `ActualSentContext`，并使受影响的新编译失效，禁止原地改写已发送上下文。

#### Slice C4：Plan Change And Historical Freeze

```text
Deviation
→ ReplanRequest
→ PlanDiff Candidate
→ ImpactAnalysis
→ Authority Decision
→ future PlanVersion
→ effective_from_chapter
→ affected Context invalidation
```

Final Release 历史不可静默重写；历史修改必须走 Retcon/Correction Operation。

StoryState Correction 至少区分 `effective_from_chapter`、`effective_to_chapter`、`recorded_at`、`superseded_by` 和 `correction_reason`；当前阶段不要求完整双时态数据库。

**Track C Gate：**

```text
book_design_to_plan_proven=true
planning_version_and_effective_range_proven=true
story_state_replay_proven=true
context_reproducibility_proven=true
source_material_knowledge_boundary_proven=true
historical_freeze_and_replan_proven=true
```

---

### Track D — Intelligence, Execution And Quality

**目标：** 用真实 Provider 证明 Agent、执行平面和质量决策能够在不绕过 Authority 的前提下完成一个真实章节。

对应 AC 参考：AC-09、AC-11、AC-12、AC-13、AC-18。

#### Slice D1：One Qualified Real Provider Capability

从一个能力开始：

```text
chapter.draft.generate
```

完整证明：

```text
ExecutionRequest
→ Capability/Route qualification
→ RouteSnapshot
→ ActualSentContext
→ real Provider call
→ request/response identity
→ usage/cost
→ normalize/validate
→ Candidate
→ Receipt
→ recovery projection
```

#### Slice D2：Real Provider Chapter Vertical Slice

按顺序扩展：

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

必须覆盖：

- timeout；
- retrieve/query；
- cancel；
- duplicate callback；
- UNKNOWN reconciliation；
- late result；
- worker restart；
- real usage and cost。

#### Slice D3：Agent Candidate And Commit Boundary

```text
AgentWorkOrder
→ frozen ScopeSnapshot
→ Agent Turn
→ Candidate v1
→ challenge/conflict
→ Candidate v2
→ Authority Decision
→ Asset Commit Reference
```

Agent 不得修改正式资产、计划、Canon、StoryState、Cursor 或发布状态。

#### Slice D4：Production Quality Versus Eval Lab

拆分：

- Production Quality Gate：稳定、低延迟、版本化 JudgeProfile、阻塞生产；
- Evaluation And Calibration Lab：Golden Set、Human Annotation、Pairwise、Mutation、OOD、Provider Benchmark 和校准。

未校准结果只能声明 Raw Score、Ordinal Band 或 Pairwise Preference，不能声明商业概率。

JudgeProfile 的统一晋升生命周期为：

```text
DRAFT → BENCHMARKED → CALIBRATED → APPROVED → ACTIVE → SUSPENDED → RETIRED
```

Production Quality Gate 只能使用已批准并激活的 JudgeProfile；Eval Lab 只能产出实验和晋升证据，不能直接改写生产 Gate。

**Track D Gate：**

```text
single_capability_real_provider_proven=true
single_chapter_real_provider_proven=true
real_usage_proven=true
real_cost_proven=true
agent_candidate_commit_boundary_proven=true
production_quality_eval_separation_proven=true
```

---

### Track E — Autonomous Book Runtime And Operations

**目标：** 在共享内核和真实章节切片之上形成 Book→Chapter→Outcome→StoryState 的连续自治运行链。

对应 AC 参考：AC-04、AC-05、AC-07、AC-08、AC-09、AC-13、AC-14、AC-15、AC-16、AC-18。

采用 `Book Production Coordinator`，不再把它设计成拥有所有领域状态的 God Supervisor。

Coordinator 只负责：

- Book Root Operation/Saga；
- 当前阶段和 Cursor；
- 子 Operation 引用；
- 下一生产范围；
- 阻塞原因；
- Pause/Resume/Cancel/Recover；
- 委托 Planning、Chapter、Longform、Quality 和 Completion；
- 等待和协调，不直接计算领域结果。

#### Slice E1：L3 Autonomous Chain

```text
Active BookDesign/Plan
→ Coordinator reserves Chapter 1
→ Chapter Saga
→ ChapterOutcome
→ StoryState reduce
→ Cursor advance
→ Chapter 2
→ Chapter 3
```

不得人工构造每章全部 Command Payload。

#### Slice E2：L10 Recap And Replan

在 L3 基础上增加：

- Recap cadence；
- Deviation；
- ReplanRequest；
- PlanDiff/Impact；
- Pause/Resume；
- duplicate command；
- stale fence；
- Provider failure；
- Worker/DB restart；
- Context growth；
- Book/Chapter budget cap。

#### Slice E3：Production Runtime Hardening And Operator Control

Track B 已提供 Minimal Authority-only Runtime；Track E 只增加生产部署硬化：

- dependency-aware readiness；
- migration compatibility；
- worker heartbeat；
- queue/outbox lag；
- stuck Saga detection；
- Service Identity；
- Project/Book Scope；
- RBAC；
- InterventionTask 和 BlockedReason；
- backup/PITR/restore rehearsal。

统一 Human Intervention 使用 `InterventionRequest / BlockedReason / RequiredEvidence / AllowedAction / AssignedRole / Decision / ResumeToken / AuditTrail`，各领域不得发明不兼容的审批字段。

Book 终局必须由 `BookCompletionContract` 决定，至少验证 Ending、主冲突、人物弧、Reader Promise、必须伏笔、Blocking Issue、Canon 冲突、Final Volume Gate 和 Release Package。Coordinator 只等待该决策。

**Track E Gate：**

```text
book_coordinator_l3_proven=true
book_coordinator_l10_proven=true
recap_replan_loop_proven=true
production_runtime_hardening_verified=true
restart_recovery_proven=true
operator_intervention_flow_proven=true
```

---

### Track F — Migration, Long-form And Scale Proof

**目标：** 通过真实运行淘汰关键 Legacy，完成 Arc 级长篇证明，并为后续发布和多书扩展建立证据。

对应 AC 参考：AC-03、AC-07、AC-08、AC-10、AC-13、AC-15、AC-16、AC-17、AC-18、AC-19。

#### Slice F1：Residual Legacy Retirement

关键 Writer 已在各前序纵向 Slice 内完成切换。Track F 只清理剩余非关键 Legacy、过期兼容 Reader 和已观察完成的归档路径；仍按业务链而不是按表横向清理：

```text
Project/Book
→ BookDesign/Plan
→ Context
→ Chapter
→ Canon/StoryState
→ Quality/Outcome/Recap
```

每个前序 Slice 和 Track F 清理波都执行：

```text
Discover
→ Classify
→ Dry-run Convert
→ Validate
→ Authority Import Operation
→ Verify
→ Cut Over And Disable Legacy Writer
→ Observe
→ Delete Writer
→ Archive or delete Reader
```

禁止长期双写。LocalStorage 可保留导入暂存、开发 Fixture、可重建缓存和临时导出，但不再是正式 Writer。

#### Slice F2：L30 Arc Proof

至少证明一个有意义的 Arc：

- 计划推进和重规划；
- 人物状态与关系变化；
- 伏笔和兑现；
- Reader Promise；
- Canon 和 StoryState 漂移；
- Quality、Cost、Latency 趋势；
- 人工抽检；
- 恢复和 Operator 负载。

#### Slice F3：Post-closure Readiness

Architecture Closure 通过后才启动：

```text
L100 → L300 → L1M
3 books → 5 books → 10 books
official platform adapter
feedback and controlled learning
multi-user productization
```

**Track F Gate：**

```text
critical_legacy_writers_retired=true
l30_arc_proven=true
cross_book_contamination_baseline_passed=true
architecture_closure_gate_passed=true
```

L100、L300、L1M 和多书属于 Architecture Closure 之后的规模证明，不阻塞本 Epic 退出。

## 7. 轨道依赖与执行纪律

推荐顺序：

```text
Track A
→ Track B
→ Track C
→ Track D
→ Track E
→ Track F
```

允许的有限重叠：

- Track A 的 Fitness Tests 和文档治理贯穿全部轨道；
- Track B 后半段可与 Track C 的领域建模并行，但不得并行修改同一共享 Schema；
- Track D 可在 Track C 的 Context/StoryState 契约稳定后开始；
- Track F 的 Legacy inventory 可提前进行，但 Writer 切换必须等待对应纵向链通过。

WIP 规则：

- 同一时间最多一个主要纵向切片处于实施中；
- 可额外保留一个缺陷修复/稳定性通道；
- 禁止同时启动多个跨共享内核的重构；
- 每个 Slice 合并前必须完成其 Gate 报告；
- 未通过前一 Slice，不得以“后续一起补测试”为由进入下一 Slice。

## 8. AC-00 至 AC-19 的新定位

AC 文档不删除，映射到六条轨道：

| Track | 主要 AC 参考 |
|---|---|
| A | AC-00、AC-01、AC-02、AC-18、AC-19 |
| B | AC-02、AC-03、AC-04、AC-05、AC-06、AC-15、AC-16、AC-17、AC-18 |
| C | AC-06、AC-07、AC-08、AC-09、AC-10、AC-13、AC-18 |
| D | AC-09、AC-11、AC-12、AC-13、AC-18 |
| E | AC-04、AC-05、AC-07、AC-08、AC-09、AC-13、AC-14、AC-15、AC-16、AC-18 |
| F | AC-03、AC-07、AC-08、AC-10、AC-13、AC-15、AC-16、AC-17、AC-18、AC-19 |

一个 AC 可以服务多个 Track。AC 本身不维护独立“完成百分比”，完成度由对应 Track Slice 的当前 SHA 证据决定。

## 9. 证据等级

| 等级 | 含义 | 可使用的声明 |
|---|---|---|
| D0 | 文档设计 | architecture_defined |
| D1 | 代码存在并可导入 | implementation_present |
| D2 | 单元、静态和架构测试 | locally_verified |
| D3 | PostgreSQL/沙箱集成 | integration_proven |
| D4 | 当前 SHA 完整部署验证 | deployment_verified |
| D5 | 真实 Provider/平台执行 | external_execution_proven |
| D6 | 连续长篇、规模、恢复和运维证明 | production_proven |

任何 Slice 必须明确目标证据等级。D0-D3 不得被表述为真实 Provider 或生产证明。

## 10. Architecture Closure 总验收

本 Epic 通过至少要求：

### Trusted Baseline

- 当前完整 SHA 可导入、迁移、测试和启动；
- 所有入口、Worker、迁移和要求测试具有 manifest；
- Architecture Fitness Tests 已进入 CI。

### Shared Kernel

- Project/Book Scope、Typed Asset Lifecycle 和 Execution Classification 已证明；
- 正式生产禁止 LocalStorage Writer 和静默 fallback；
- PostgreSQL、Object Store、Vector/Search 的权威边界稳定。

### Novel Domain

- BookDesign→Plan、ChapterOutcome→StoryState、Context Compiler 和 Replan 链可重现；
- Source、Material、Knowledge 分离；
- 历史冻结和 EffectiveRange 有正式证据。

### Intelligence And Quality

- 一个真实 Provider 章节完成 Draft→Review→Revision→Canon→Quality→Final Release；
- 真实 Usage、Cost、Receipt 和恢复证据存在；
- Agent Candidate 与 Commit 分离；
- Production Gate 与 Eval Lab 分离。

### Autonomous Runtime

- Book Coordinator 完成 L3 和 L10；
- Recap/Replan、Pause/Resume、失败恢复和 Budget Gate 已证明；
- Authority-only Runtime 和 Operator Intervention 可运行。

### Migration And Proof

- 全书关键路径的 Legacy Writer 已退役；
- 完成一个真实 L30 Arc 证明；
- 当前文档只使用当前 SHA 证据更新成熟度。

最终标志：

```text
architecture_closure_gate_passed=true
single_chapter_real_provider_proven=true
book_coordinator_l10_proven=true
l30_arc_proven=true
critical_legacy_writers_retired=true
authority_only_runtime_verified=true
```

## 11. Architecture Closure 之后

通过本 Epic 后进入：

```text
Long-form Scale Proof
L100 → L300 → L1M

Portfolio Proof
3 → 5 → 10 Books

Commercial Operations
Official Publishing Adapter
Feedback And Controlled Learning
Multi-user Productization
```

下一阶段的进度指标不再是模块数量、文档数量或页面数量，而是：

```text
可运行纵向链
真实外部执行
可恢复性
内容质量
成本和吞吐
长期状态一致性
Operator 负担
```
