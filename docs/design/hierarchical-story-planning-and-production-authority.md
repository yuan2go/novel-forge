# Hierarchical Story Planning and Production Authority

> 全书—卷—剧情弧—章节组—章节分层规划与生产权威设计  
> 更新日期：2026-07-22  
> 适用分支：`feat/v7-content-intelligence-and-longform-proof`  
> 文档状态：`ACTIVE TARGET DESIGN`，不代表已经实现或通过生产验证

## 0. 文档定位与优先级

本文定义 Novel Forge 的分层故事规划与长篇生产委托模型，重点解决：

- 全书设计如何逐层展开为可执行 ChapterPlan；
- Book Authority 如何动态委托真实 Chapter Saga；
- 卷、剧情弧、章节组与章节之间如何分工；
- 已执行历史、冻结窗口和未来规划如何隔离；
- 复盘、反馈和状态变化如何形成受控的未来计划调整。

本文是以下文档的子设计：

- `docs/design/book-design-authority-and-longform-closed-loop.md`：产品与领域主设计；
- `docs/architecture/production-execution-plane.md`：所有模型和外部执行的统一运行基础；
- `docs/blueprint/reader-outcome-judge/README.md`：读者结果评估与校准子系统。

发生冲突时遵循：

```text
代码与自动化证据
→ PostgreSQL Authority 不变量
→ Production Execution Plane
→ Book Design Authority
→ 本文
→ UI / Projection
```

## 1. 当前事实边界

当前代码已经具备：

- PostgreSQL Command Kernel、Operation、Saga、Attempt；
- 幂等、Lease、Fencing、Retry、Audit、Outbox；
- 十八节点 Chapter Authority；
- ChapterPlan V3 的规范化和 Qualification；
- Canon、五组 Quality、Publish Gate、Export、Final Release Gate；
- Book Root Saga 骨架；
- Longform Recap、PlanAdjustmentProposal 和部分 Story State 能力。

当前尚未证明：

```text
book_to_real_chapter_delegation_proven = false
hierarchical_planning_proven = false
real_provider_proven = false
longform_proven = false
production_verified = false
```

当前 `book.chapter.dispatch` 仍不能作为真实章节生产证明；启动一本书时预创建全部章节步骤也不符合滚动规划和动态委托目标。

## 2. 核心架构决策

### 2.1 Authority 与 Generator 分离

Authority 负责：

- Command 准入；
- 状态机；
- 版本绑定与冻结；
- 子 Saga 委托；
- 预算、审批、恢复和审计；
- Acceptance / Closure；
- 正式资产激活。

Generator 负责：

- 多候选生成；
- 机制和情节设计；
- 语义扩写；
- 局部重规划候选。

Validator / Judge 负责：

- Schema、Semantic、Structural、Policy 检查；
- 长篇一致性和商业节奏；
- 原创性、来源安全和平台适配。

Reducer 负责：

- 只消费已接受 Evidence；
- 确定性提交 Story State；
- 不调用 LLM；
- 可重放且幂等。

禁止把 `materialize`、`normalize`、`validate`、`persist` 命名为真正的 `generate`。

### 2.2 生产包含树与语义 Arc 图分离

长篇系统不能把所有剧情弧强制塞进单一树形层级。

生产范围使用包含树：

```text
Book
└─ Volume
   └─ ChapterGroup
      └─ Chapter
```

剧情意义使用跨层图：

```text
Arc
↔ Volume
↔ ChapterGroup
↔ Chapter
```

原因：

- 人物弧、关系弧、主题弧和谜团弧可以跨卷；
- 一章可以同时推进多条 Arc；
- 一个 ChapterGroup 可以承担主线、人物和关系等多个 Arc Contribution；
- Arc Closure 依赖语义状态和兑现条件，不等同于某个章节容器结束。

因此，首期 Arc 是一等版本化语义资产和状态图，不强制成为独立运行 Root Saga。

### 2.3 首期只建立三层运行 Authority

首期运行边界：

```text
Book Production Authority
→ ChapterGroup Production Authority
→ Chapter Authority
```

Volume 和 Arc 首期实现为：

```text
Versioned Planning Contract
+ State Projection
+ Closure Evaluator
+ Impact Target
```

只有当真实生产证明 Volume 或 Arc 需要独立暂停、预算、恢复、并发和生命周期时，才升级为独立 Root Saga。

### 2.4 动态委托，不预建整书任务图

禁止：

```text
启动一本书
→ 一次创建 300—500 个 Chapter Operation
```

要求：

```text
接受当前执行单元
→ 提交实际状态
→ 复盘或刷新窗口
→ 锁定下一执行单元
→ 创建下一 Child Saga
```

Book 启动只创建当前可执行窗口，不展开整书全部 Operation。

### 2.5 Plan、Canon、State、Evidence 分离

| 对象 | 含义 | 是否代表正式事实 |
|---|---|---:|
| Plan | 未来准备发生什么 | 否 |
| Canon | 已批准且已发生的故事事实 | 是 |
| Story State | 由 Canon/Event 确定性派生的当前状态 | 是，派生事实 |
| Draft / Review / Judge | 实际文本和分析证据 | 否，需验收或审批 |

禁止：

- 未来 Plan 覆盖 Canon；
- Draft 未经审批直接修改 Story State；
- 复盘直接覆盖未来 Active Plan；
- 上游新版本静默改变已 admitted Operation 的冻结输入。

## 3. 正交状态模型

不得使用一个巨型枚举同时表达生命周期、审批、执行范围和依赖新鲜度。

### 3.1 Lifecycle

```text
CANDIDATE
ACTIVE
SUPERSEDED
RETIRED
```

### 3.2 Qualification

```text
UNQUALIFIED
QUALIFIED
REJECTED
```

### 3.3 Approval

```text
NOT_REQUIRED
PENDING
APPROVED
REJECTED
```

### 3.4 Planning Scope

```text
SPECULATIVE
PLANNED
FROZEN
EXECUTED
```

### 3.5 Freshness

```text
CURRENT
STALE
IMPACTED
INVALID
```

一个当前可执行计划应类似：

```text
ACTIVE + QUALIFIED + APPROVED + FROZEN + CURRENT
```

已执行计划：

```text
ACTIVE/SUPERSEDED + QUALIFIED + APPROVED + EXECUTED
```

历史版本可被 Supersede，但不得删除或自动重写。

## 4. 分层规划合同

所有规划资产使用现有 `authority_asset` / `authority_asset_version` 保存内容，并通过关系表记录层级、活动版本和执行范围。

### 4.1 PlanningContractHeader

```text
contract_id
contract_type
project_id
book_id
logical_key
parent_contract_id
parent_version_id
version_id
schema_version
objective
entry_state_ref
exit_state_spec
hard_constraints
soft_constraints
required_events
forbidden_events
required_payoffs
forbidden_payoffs
character_deltas
world_deltas
arc_contributions
canon_dependencies
quality_targets
budget_policy_ref
context_profile_ref
created_by_operation_id
```

每个下层合同必须绑定：

- Parent Plan Version；
- Canon Snapshot Version；
- Story State Version；
- Context Manifest；
- Quality Profile；
- Provider / Runtime Policy；
- Budget Reservation；
- Approval 和 Freshness 状态。

### 4.2 BookPlan

负责全书长期承诺：

- 核心前提和 Reader Promise；
- 中央冲突引擎；
- 主角完整变化方向；
- 反派升级路线；
- 世界、关系和主题演化；
- EndingContract 绑定；
- 卷功能骨架；
- 主要转折和高潮分布；
- 长期 Promise / Payoff 策略；
- 连载策略、长度和风险登记。

### 4.3 VolumePlan

Volume 是阶段性兑现单位，不只是标题。

必须定义：

- 卷功能、目标和阶段冲突；
- 入口和出口 Story State；
- 阶段对手和压力；
- 不可逆变化；
- 中点、高潮、结算和下一卷桥梁；
- Reader Promise、Payoff 和 Foreshadow 责任；
- 预算和章节范围。

### 4.4 ArcPlan

Arc 是具有因果闭环的语义变化单元。

必须定义：

- Arc 类型和长期目标；
- Objective、Resistance、Escalation；
- Turn、Choice、Cost、Result、Consequence；
- Character / World / Relationship / Theme Delta；
- Promise / Payoff；
- 依赖 Arc；
- Closure Conditions；
- 可跨 Volume 范围。

至少支持：

- 主线推进；
- 人物成长；
- 关系；
- 悬疑调查；
- 对抗；
- 世界探索；
- 失败与反转；
- 主题价值冲突。

### 4.5 ChapterGroupPlan

ChapterGroup 是长篇生产的主要批次，默认 `3—8` 章。

必须定义：

- 局部目标；
- 起始和结束状态；
- 触发事件、阻力升级、转折和局部高潮；
- 信息释放顺序；
- 情绪曲线；
- Promise / Payoff 和 Foreshadow 分配；
- Antagonist Actions；
- Arc Contributions；
- ChapterFunctionMatrix；
- 章节和成本范围。

### 4.6 ChapterFunctionMatrix

每章只能有一个主功能和有限辅助功能：

```text
chapter_number
primary_function
secondary_functions
required_state_delta
required_arc_contributions
promise_action
foreshadow_action
reward_action
ending_hook
prohibited_outcomes
```

组内不得连续多章主功能重复且没有升级。

### 4.7 ChapterPlan V3

Chapter Authority 继续消费冻结的 ChapterPlan V3。

ChapterPlan 必须增加或明确绑定：

```text
parent_group_version_id
volume_version_id
arc_contributions
expected_arc_deltas
story_state_version_id
canon_snapshot_version_id
planning_scope = FROZEN
freshness = CURRENT
```

Chapter Authority 不负责决定全书、卷和章节组宏观方向。

## 5. 滚动规划窗口

### 5.1 默认范围

| 范围 | 精度 | 可变性 |
|---|---|---|
| 全书 | 长期合同和终局方向 | 高层稳定 |
| 全部卷 | 功能骨架 | 可调整 |
| 当前卷 | 详细合同 | 中低可变 |
| 当前 ChapterGroup | 3—8 章功能矩阵 | 执行中不可变 |
| Executable ChapterPlan | 当前 1 章 | 不可变 |
| Detailed ChapterPlan | 未来 3—7 章 | 低可变 |
| Broader Planning Horizon | 未来 10—20 章 | 可调整 |
| 更远章节 | 功能占位 | 高可变 |

### 5.2 PlanningHorizon

```text
project_id
book_id
executed_through_chapter
frozen_through_chapter
planned_through_chapter
speculative_through_chapter
active_book_plan_version_id
active_volume_plan_version_id
active_group_plan_version_id
active_chapter_plan_version_id
active_arc_ids
window_version
based_on_canon_version
based_on_story_state_version
policy_version
```

推进步骤：

```text
accept current chapter/group
→ commit ChapterOutcome and Story State
→ run required recap
→ apply approved plan changes
→ revalidate next contracts
→ lock next execution unit
→ dispatch next child
```

## 6. Book → Chapter 真实委托

这是分层生产链的第一个 P0 闭环。

### 6.1 Operation 拆分

```text
book.chapter.resolve_plan
book.chapter.dispatch
book.chapter.reconcile
book.chapter.accept
```

`book.chapter.dispatch` 不得同步循环运行完整 Chapter Saga。

### 6.2 Resolve Plan

负责：

- 读取 Production Cursor；
- 解析当前目标 ChapterPlan Version；
- 验证 Parent Contract；
- 验证 `ACTIVE + QUALIFIED + APPROVED + FROZEN + CURRENT`；
- 验证 Canon、Story State、Context 和预算前置条件；
- 生成 ProductionInputManifest。

### 6.3 Dispatch

负责：

- 预算预留；
- admission `chapter.slice.run`；
- 记录 ChildDelegation；
- 返回 `DISPATCHED` Receipt；
- 不伪造 Acceptance。

### 6.4 Reconcile

负责：

- 查询 Child Root Operation 和 Saga；
- 处理重复 Callback、Worker Crash 和状态缺口；
- Child 未终态时保持等待；
- Child 终态后生成 Acceptance Candidate。

### 6.5 Accept

只有全部满足时才能推进游标：

1. Child Root Operation 和 Saga 成功；
2. Final Release Gate 通过；
3. Export Receipt 已验证；
4. Quality Aggregate 通过；
5. Blocking ReviewIssue 为零；
6. Canon 决策明确；
7. ChapterOutcome 已生成；
8. Story State Reducers 已提交或进入明确审批等待；
9. Usage / Cost 已结算；
10. 产物绑定正确的 ChapterPlan 和 Parent Version。

### 6.6 幂等与双写

稳定键建议：

```text
{book_id}:{child_level}:{logical_key}:{plan_version}:{attempt_generation}
```

优先使用同一 Authority UnitOfWork 完成 Child Admission 和 Delegation；若暂时不能原子完成，则必须：

- 使用稳定 Idempotency Key；
- Crash 后按稳定键找回 Child；
- 幂等补写 Delegation；
- Reconcile 后再决定是否重派。

## 7. ChapterGroup Production Authority

完成 Book → Chapter 后，将逐章控制下沉到 ChapterGroup。

```text
chapter_group.production.run
├─ prepare
├─ plan.resolve
├─ function_matrix.validate
├─ chapter.dispatch / reconcile / accept × N
├─ recap.run
├─ plan_vs_actual.evaluate
├─ plan_adjustment.propose
└─ production.close
```

Group Closure 必须验证：

- 每章主功能和 Arc Contribution；
- 局部目标或合理失败；
- 情绪曲线和信息释放；
- Promise、Payoff、Foreshadow；
- Character / Relationship / World Delta；
- Narrative Debt；
- 下一组入口。

Retrospective 只能提出 Proposal，不得直接修改下一组。

## 8. Volume 与 Arc 的首期实现

### 8.1 Volume

首期实现：

- Versioned VolumePlan；
- Volume Progress Projection；
- Volume Closure Evaluator；
- Volume Recap；
- Rebaseline Proposal。

首期不强制建立独立 Volume Scheduler。

### 8.2 Arc

首期实现：

- ArcPlan Version；
- Arc Dependency Graph；
- Chapter / Group Contribution；
- Arc State Projection；
- Arc Closure Evaluator；
- Arc Replan Proposal。

首期不强制建立每条 Arc 的 Root Saga。

## 9. 计划变更与影响传播

```text
Recap / Feedback / Quality / State Evidence
→ PlanChangeProposal
→ Semantic Diff
→ Impact Analysis
→ Approval
→ New Plan Versions
→ Future descendants STALE / IMPACTED
→ Revalidate or Regenerate
→ Activate
```

规则：

- `EXECUTED`：不可自动改写；
- `FROZEN`：替换必须审批；
- `PLANNED`：新版本需要影响分析；
- `SPECULATIVE`：低风险情况下允许自动候选重生成。

影响传播必须以具体字段和 Dependency Edge 为依据，不能只按资产类型全量失效。

## 10. 数据模型复用

计划正文继续存储于：

```text
authority_asset
authority_asset_version
```

首期新增关系和运行表：

```text
story_plan_binding
story_plan_hierarchy
active_story_plan_version
planning_horizon
asset_dependency_edge
story_production_cursor
authority_child_delegation
authority_child_acceptance_receipt
chapter_outcome
```

禁止再创建第二套完整 `story_plan_version.contract_payload` 权威内容表。

频繁查询、需要唯一约束和事务完整性的关系进入 typed table；可读内容和大 Payload 进入 AssetVersion。

## 11. 调度、预算与停止策略

### 11.1 Scheduler Scope

Book / Group Scheduler 查询必须限定：

- `project_id`；
- `root_operation_id`；
- `saga_id`；
- 当前活动 Delegation；
- 依赖已满足；
- Lease / Fencing Token。

不得从项目级 Pending Queue 任意取一个 Content Operation 当作当前 Book 子步骤。

### 11.2 Budget

首期至少落实：

```text
Book Budget
→ ChapterGroup Budget
→ Chapter / Provider Budget
```

任何真实 Child Saga：

```text
estimate
→ reserve
→ admit
→ settle actual
→ release unused
```

### 11.3 Pause / Resume / Cancel

- Pause：停止创建新 Child；活动 Child 按策略完成或进入 Gate；
- Resume：先 Reconcile 已存在 Child；
- Cancel：传播到活动 Child，并记录不可逆 ExternalEffect；
- Recovery：禁止盲目重派，先查询和 Reconcile。

## 12. 实施顺序

```text
Phase 0  真实 Provider 单章基线（条件允许时）
Phase 1  Production Execution Plane Core
Phase 2  Book Design / Planning Contract Core
Phase 3  Book → Chapter 真实委托
Phase 4  ChapterGroup Authority
Phase 5  ChapterPlan / GroupPlan Semantic Generator
Phase 6  World / Character / Book / Volume Generator
Phase 7  Arc Semantic Graph and Closure
Phase 8  ChapterOutcome / Reducers / Recap / Impact
Phase 9  Reader Outcome Judge Shadow
Phase 10 Real Longform Proof
```

不得等待所有上游 Generator 完成后才打通 Book → Chapter；允许首个纵向证明消费经过验证和审批的 Legacy Import Asset。

## 13. 验收阶梯

### 13.1 Book → Chapter

- 两章连续 Child Saga；
- 幂等 Dispatch；
- Acceptance 多证据门禁；
- Budget 实际参与；
- Pause / Resume / Cancel / Recovery；
- 不预建整书 Operation。

### 13.2 ChapterGroup

- 一个 3—5 章完整 Group；
- FunctionMatrix；
- Plan-vs-Actual；
- Group Retrospective；
- 下一组 Proposal；
- Rolling Horizon。

### 13.3 Longform

```text
3 chapters
→ 10 chapters with formal recap
→ 30 chapters
→ complete ChapterGroup
→ complete Arc closure
→ complete Volume closure
```

成熟度必须分别标记：

```text
documented
handler_bound
fixture_proven
integration_proven
real_provider_proven
longform_proven
production_verified
```

## 14. 明确非目标

第一阶段不做：

- 五套独立 Scheduler 和 Root Saga；
- 一次生成数百章详细 ChapterPlan；
- 多书 Portfolio 调度；
- 无审批整卷自动重写；
- Reader Outcome 自动阻断发布；
- 因页面和 Schema 存在而声明成熟；
- Fixture 证明冒充真实长篇证明。

## 15. 最终目标

```text
Approved Book Design
→ Book / Volume Planning
→ Arc Semantic Graph
→ ChapterGroup Function Matrix
→ Frozen ChapterPlan
→ Real Chapter Saga
→ ChapterOutcome
→ Deterministic Story State
→ Recap and Plan-vs-Actual
→ Proposal / Impact / Approval
→ New Future Plan Versions
→ Continue / Pause / Close
```

最终系统必须能够在不改写已执行历史的前提下，持续设计、生产、复盘和调整一本长篇小说。