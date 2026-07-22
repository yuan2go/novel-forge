# Book Design Authority 与长篇闭环生产系统

> 文档类型：产品需求、领域设计、系统架构与验收规格  
> 更新日期：2026-07-22  
> 适用分支：`feat/v7-content-intelligence-and-longform-proof`  
> 产品目标：Autonomous Novel OS  
> 当前优先级：v1 单书生产闭环  
> 文档状态：`ACTIVE TARGET DESIGN`，不代表已实现或已通过生产验证

## 1. 文档目的

本文定义 Novel Forge 下一阶段的产品主链：把创作目标转化为可执行、版本化、可审计的全书设计，并让单章结果持续回写 Story State、触发复盘和未来规划调整，最终完成全书承诺和结局验收。

本文不重复定义模型执行基础设施。所有真实模型、Codex CLI、远程 Provider 和 Judge 调用必须通过：

```text
PostgreSQL Authority Operation
→ ProductionExecutionGateway
→ Qualified ExecutionBackend
```

分层规划和生产委托细节见：

- `docs/design/hierarchical-story-planning-and-production-authority.md`

Reader Outcome Judge 见：

- `docs/blueprint/reader-outcome-judge/README.md`

## 2. 当前事实边界

当前工程已经具备：

- PostgreSQL Authority、Command Kernel、Operation、Saga、Attempt；
- 幂等、Lease、Fencing、Retry、Audit、Outbox；
- AssetVersion、Qualification、Approval 和 ExternalEffect；
- ChapterPlan V3 与十八节点 Chapter Authority；
- Canon 提取、逐项审批和状态更新；
- 五组 Chapter Quality、Aggregate、Publish Gate、Export、Final Release Gate；
- Book Root Saga 骨架；
- Theme、Ending、World、Character、Outline、Longform 和 Feedback 的部分领域能力；
- Source Diff Repair 的影响分析、审批、Stale 和 Rollback 模式。

当前不得声称：

```text
real_provider_proven = false
book_to_chapter_delegation_proven = false
hierarchical_planning_proven = false
longform_proven = false
reader_outcome_behavior_calibrated = false
production_verified = false
```

当前最重要的语义缺口：

| 能力 | 当前真实职责 | 目标 |
|---|---|---|
| Creative | Scripted / materialized result | 多机制候选生成 |
| World | Builder / validator | 世界设计候选生成 |
| Character | Profile builder | 整体 Cast 生成 |
| Theme | 规则和 ThemeArc 构建 | Theme candidate generation |
| Ending | Closure / Payoff 构建和评估 | EndingIntent generation |
| Outline | Legacy LocalStorage 模型生成 | PostgreSQL Planning Generator |
| ChapterPlan | Legacy 模型生成；Authority 仅 materialize | Authority Candidate Generator |
| Book Authority | Fixture Saga | 真实 Child Chapter Saga 委托 |

不得继续把 Materializer 存在当作 Generator 完成。

## 3. 产品定义

### 3.1 Book Design Authority

Book Design Authority 是上游故事设计权威，负责把创作目标转化为：

- Creative Proposal；
- ThemeQuestion；
- EndingIntent / EndingContract；
- WorldBible；
- CharacterCast；
- BookPlan、VolumePlan、ArcPlan、ChapterGroupPlan；
- PlanningHorizon；
- Asset Dependency 和影响关系；
- 可供 Book Production 消费的 Approved Design Snapshot。

### 3.2 Longform Closed Loop

Longform Closed Loop 是从 Chapter Acceptance 回到长期状态和未来计划的反馈控制系统，负责：

- Canon 和时间线稳定；
- 人物动机和关系连续；
- 世界规则、资源和战力可信；
- 伏笔、谜团、承诺和奖励可追踪；
- 主题通过选择和代价演进；
- 反派持续适应；
- 结局具备可达性；
- 反馈只影响未来而不污染历史。

### 3.3 非目标

本系统不是：

- 一次 Prompt 生成整本大纲；
- 让 LLM 直接修改 Canon；
- 每次修订覆盖旧资产；
- 只靠 RAG 维持长篇一致性；
- 用 Schema、页面或 Fixture 证明生产成熟；
- 根据单次评论自动改变主线和结局。

## 4. 总体架构

```text
Project Goal
→ Creative Candidate Pool
→ Approved Project Proposal
→ ThemeQuestion + EndingIntent
→ World Design + Character Cast
→ Approved Book Design Snapshot
→ Hierarchical Planning
→ Frozen ChapterPlan
→ Book delegates real Chapter Saga
→ ChapterOutcome
→ Deterministic Story State Reducers
→ Longform Evaluation / Recap
→ PlanChangeProposal
→ Impact / Approval / Future Plan Versions
→ Continue / Pause / Close
```

基础设施分工：

```text
Production Execution Plane
= 统一模型和外部执行

Story Design Asset Authority
= 候选、校验、审批、激活和版本治理

Planning Authority
= Book / Volume / Arc / Group / ChapterPlan 关系与窗口

Book Production Authority
= 一本书的运行、预算、委托、停止和关闭

Story State Authority
= Canon / Timeline / Character / Relationship / Foreshadow 等状态

Longform Governance
= 漂移、债务、复盘、计划调整建议

Completion Authority
= Closure / Payoff / Ending / Final Approval
```

## 5. 核心设计原则

### 5.1 单一生产权威

生产环境正式资产只能通过 PostgreSQL Authority Operation 创建、校验、审批和激活。

Legacy LocalStorage 仅用于：

- 导入导出；
- 兼容读取；
- 开发样例；
- 一次性迁移；
- 非生产研究。

不得作为生产 fallback。

### 5.2 Generator 不直接写 Active Asset

标准链：

```text
Frozen Inputs
→ ProductionExecutionGateway
→ Provider / Process Receipt
→ Generation Candidate
→ Candidate AssetVersion
→ Materializer
→ Validator / Judge
→ Bounded Repair
→ Approval
→ Activation
```

禁止：

```text
LLM → Active WorldBible
LLM → Active BookPlan
LLM → Frozen ChapterPlan
```

### 5.3 Candidate 与正式资产分离

```text
WorldDesignCandidate != WorldBible
CharacterCastCandidate != CharacterCast
BookPlanCandidate != BookPlan
ChapterPlanCandidate != AuthoritativeChapterPlan
EndingIntentCandidate != EndingIntent
```

### 5.4 设计资产与运行状态分离

```text
CharacterProfile        != CharacterStateSnapshot
WorldBible              != WorldStateSnapshot
RelationshipDefinition != RelationshipStateSnapshot
ForeshadowPlan          != ForeshadowStateSnapshot
PromisePlan             != PromiseLedger
```

设计资产不随每章覆盖；运行状态由 Reducer 增量演进。

### 5.5 Append-only 与版本激活

```text
AssetVersion v1
→ Change Proposal
→ Candidate v2
→ Validation
→ Approval
→ Activation
→ v1 Superseded
```

旧版本保留用于 Replay、Audit、Diff、Rollback 和历史章节解释。

### 5.6 已执行历史不可自动重写

```text
EXECUTED
FROZEN
PLANNED
SPECULATIVE
```

- `EXECUTED`：只能通过 Retcon Proposal 解释或补救；
- `FROZEN`：替换必须审批；
- `PLANNED`：允许新版本，但必须影响分析；
- `SPECULATIVE`：低风险情况下允许自动候选重生成。

### 5.7 LLM 提议，Reducer 提交状态

```text
LLM Extraction / Proposal
→ Evidence Validation
→ Approval Policy
→ Deterministic Reducer
→ New Snapshot
```

Reducer 不调用 LLM，不覆盖旧 Snapshot，同一 ChapterOutcome 重放不得重复应用。

### 5.8 质量是门禁，不是展示分数

核心资产必须区分：

- Schema 完整性；
- 语义质量；
- 长篇一致性；
- 商业和连载能力；
- 原创与来源安全；
- 平台适配；
- 运行证据完整性。

缺少必要版本和证据必须 Fail Closed。

## 6. Story Design Asset Authority

首期不为 Creative、Theme、Ending、World、Character 和 Planning 建立六套重复 Authority 基础设施。

共用：

```text
Story Design Asset Authority
```

通用生命周期：

```text
Candidate
→ Materialize
→ Qualify
→ Repair
→ Approve
→ Activate
→ Supersede
```

各领域只提供：

```text
GeneratorDefinition
Input / Output Contract
Codec
Validator
RepairPolicy
ApprovalPolicy
ActivationPolicy
```

### 6.1 GeneratorDefinition

```text
operation_name
input_contract_version
output_candidate_type
output_schema_version
prompt_contract_version
skill_version
route_policy_ref
materializer_key
validator_keys
repair_policy_key
approval_policy_key
activation_policy_key
maximum_semantic_repairs
maximum_structural_regenerations
```

GeneratorDefinition 不实现 Provider、Timeout、Cancel、Reconcile、Usage 和 Cost；这些全部由 Production Execution Plane 提供。

### 6.2 Generator Operation

领域语义 Operation：

```text
creative.candidates.generate
theme.candidates.generate
ending.intent.generate
world.design.generate
character.cast.generate
book_plan.generate
volume_plan.generate
arc_plan.generate
chapter_group_plan.generate
chapter_plan.generate
```

通用生命周期 Operation 复用现有 Authority 能力，不再建设独立 ModelExternalEffectRuntime。

## 7. Book Design 核心资产

### 7.1 Creative

目标是至少生成三个机制真正不同的候选，而不是只替换名称和背景。

Creative Mechanism Fingerprint：

```text
protagonist_advantage_mechanism
conflict_loop
growth_loop
reward_loop
information_asymmetry
world_constraint
relationship_engine
antagonist_response_pattern
chapter_payoff_pattern
```

### 7.2 Theme

主题不是结论，而是角色在压力下围绕冲突价值做出选择、承担代价并发生变化。

核心资产：

```text
ThemeCandidate
ThemeQuestion
ThemePositionMap
ValueConflict
ThemeArc
ThemeMovementState
ThemeDriftReport
AntiPreachingReport
```

### 7.3 Ending

开书阶段建立方向明确、允许受控演化的 EndingIntent；BookPlan 激活前形成 EndingContract。

EndingContract 至少定义：

```text
mandatory_resolutions
mandatory_payoffs
forbidden_shortcuts
allowed_open_questions
required_protagonist_cost
required_antagonist_causality
required_world_terminal_state
required_theme_reanswer
epilogue_policy
```

### 7.4 World

World Generator 必须生成能够持续产生限制、冲突、选择和代价的系统，不是百科条目集合。

必须包含：

- 可观察规则；
- 资源和能力代价；
- 稀缺例外；
- 势力和制度；
- 资源流动和社会结构；
- 日常生活；
- 历史创伤；
- 可持续冲突源；
- 与主角机制和 EndingContract 的约束关系。

### 7.5 Character Cast

角色必须作为相互制约的 Cast 整体生成。

核心资产：

```text
CharacterCastCandidate
CharacterCast
CastFunctionMatrix
CharacterProfile
CharacterRoleContract
CharacterArc
CharacterVoiceProfile
RelationshipDefinition
RelationshipArc
```

Antagonist 至少包含：

```text
independent_goal
resource_base
worldview
adaptation_policy
information_access
escalation_ladder
counter_strategy
acceptable_cost
failure_blind_spot
terminal_causality
```

### 7.6 Hierarchical Planning

```text
BookPlan
→ VolumePlan
→ ChapterGroupPlan
→ ChapterPlan V3
```

Arc 作为跨层语义图：

```text
ArcPlan
↔ VolumePlan
↔ ChapterGroupPlan
↔ ChapterPlan
```

详细约束见分层规划文档。

## 8. Book Design Snapshot 与 Saga

### 8.1 Approved Book Design Snapshot

Book Production 启动前必须冻结一个 Design Snapshot，至少绑定：

```text
ProjectProposal Version
ThemeQuestion Version
EndingIntent / EndingContract Version
WorldBible Version
CharacterCast Version
BookPlan Version
Current VolumePlan Version
Initial ChapterGroupPlan Version
PlanningHorizon Version
Quality / Source / Platform Policy Versions
```

后续上游新版本不得静默改变已 admitted Book Operation。

### 8.2 Book Design Saga

```text
book.design.run
├─ creative.candidates.generate / evaluate / approve
├─ theme.candidates.generate / approve
├─ ending.intent.generate / compatibility / approve
├─ world.design.generate / validate / approve
├─ character.cast.generate / validate / approve
├─ book_plan.generate / validate / approve
├─ current_volume_plan.generate / approve
├─ initial_chapter_group_plan.generate / approve
├─ planning_horizon.initialize
└─ book.design.snapshot.activate
```

首个纵向闭环允许使用经过验证和审批的 Legacy Import Asset，不得等待所有 Generator 实现后才打通 Book → Chapter。

## 9. Book Production Saga

Book Production Authority 负责：

- 启动、暂停、恢复、取消和关闭；
- 冻结 Production Policy 和 Design Snapshot；
- 维护 Production Cursor；
- 动态委托 ChapterGroup / Chapter Saga；
- 汇总预算、失败、质量和进度；
- 触发 Recap、Plan Adjustment 和 Completion；
- 保证幂等、恢复和审计。

Book Authority 不直接生成 World、Character、Plan 或正文。

### 9.1 目标流程

```text
book.production.run
├─ prepare
├─ planning.ensure_horizon
├─ group/chapter.resolve
├─ group/chapter.dispatch
├─ group/chapter.reconcile
├─ group/chapter.accept
├─ chapter.outcome.reduce
├─ recap.light / formal / volume
├─ plan_adjustment.propose / review / apply
├─ planning.refresh_horizon
├─ completion_readiness.evaluate
└─ production.complete
```

不预创建整书所有章节 Operation。

## 10. ChapterOutcome 与 Story State

### 10.1 ChapterOutcome

单章完成后必须形成结构化实际结果：

```text
planned_objectives
achieved_objectives
failed_objectives
actual_state_changes
actual_reveals
actual_relationship_changes
actual_world_changes
actual_reward_delivery
new_promises
fulfilled_promises
new_foreshadows
resolved_foreshadows
arc_contributions
unexpected_deviations
quality_issues
reader_risks
```

### 10.2 Reducers

```text
ChapterOutcome
→ CanonReducer
→ TimelineReducer
→ WorldStateReducer
→ CharacterStateReducer
→ RelationshipStateReducer
→ ForeshadowReducer
→ PromiseReducer
→ RewardReducer
→ PowerReducer
→ MysteryReducer
→ ArcStateReducer
```

Reducer 规则：

- 仅消费 Accepted Chapter；
- 输入冻结；
- 输出新 Snapshot；
- 可 Replay；
- 幂等；
- 高风险 Canon 变化需审批；
- LLM 只提供 Candidate Evidence。

### 10.3 Plan-vs-Actual

每章生成：

```text
ChapterPlanActualDiff
```

至少包含：

- Objective Drift；
- Scene Omission；
- Unexpected Reveal；
- Unplanned State Change；
- Reward / Hook / Theme Mismatch；
- Arc Contribution Difference；
- Canon Divergence。

## 11. Longform Governance

### 11.1 评估维度

```text
motivation_drift
relationship_drift
canon_conflict
world_rule_conflict
power_conflict
foreshadow_debt
promise_debt
reward_cadence
antagonist_pressure
pattern_repetition
theme_movement
arc_progress
quality_trend
reader_fatigue
ending_feasibility
```

### 11.2 NarrativeDebt

统一表示尚未偿还的叙事义务：

```text
debt_type
source_asset_version_id
created_chapter
due_window
current_status
risk_level
payoff_requirement
blocking_scope
```

### 11.3 Recap

```text
Light Recap   每 3—5 章
Formal Recap  每 10 章或 ChapterGroup Closure
Volume Recap  Volume Closure
Exception     严重漂移、连续低质量、Canon 冲突
```

Recap 只能产生：

```text
ReviewIssue
RevisionTask
CanonProposal
PlanChangeProposal
AssetImpactReport
RegenerationPlan
ApprovalRequest
```

不得直接修改规划。

## 12. Asset Dependency 与影响传播

### 12.1 Dependency Edge

```text
parent_asset_version_id
child_asset_version_id
dependency_type
dependency_strength
consumed_fields
impact_policy
created_by_operation_id
```

Dependency Type：

```text
GENERATED_FROM
CONSTRAINED_BY
VALIDATED_AGAINST
DERIVED_FROM
EXECUTED_FROM
SUMMARIZES
SUPERSEDES
```

Strength：

```text
HARD
SOFT
REFERENCE
```

### 12.2 Change Saga

```text
New AssetVersion Candidate
→ Semantic Diff
→ Impact Analysis
→ Approval Decision
→ Regeneration Plan
→ Ordered Revalidation / Regeneration
→ Descendant Validation
→ Activation
```

影响必须基于具体字段和 Dependency Edge，不得按资产类型粗暴全量失效。

Executed History 永不进入自动 Regeneration。

## 13. Reader Feedback 与 ROJ 边界

Reader Feedback 负责真实信号的标准化、归因和调整提案。

Reader Outcome Judge 负责：

- 指定 Segment 的 Reader Outcome 预测；
- 不确定性和 OOD；
- 校准；
- Advisory / Publish Decision Evidence。

第一阶段 ROJ 为 Shadow Sidecar，不进入 Chapter Completion Contract，不自动阻断 Publish Gate。

真实反馈不得自动：

- 修改 Executed Horizon；
- 改变 EndingIntent；
- 删除主要人物；
- 改变世界核心规则；
- 覆盖 Frozen ChapterPlan；
- 修改 Canon；
- 自动发布。

## 14. Completion Authority

Completion 负责：

```text
ClosureMatrix
PayoffMatrix
NarrativeDebt
EndingFeasibility
EndingQuality
CompletionReadiness
Final Approval
```

Final Completion 必须验证：

- 主角外部目标、内部需要、最终选择和代价；
- 反派失败因果和终态；
- 主要关系终态；
- 世界核心问题和制度终态；
- 谜题证据链和答案；
- 伏笔、承诺、奖励和人物弧；
- Theme Re-answer；
- EndingContract。

决策：

```text
BLOCKED
READY_WITH_WARNINGS
READY_FOR_FINAL_APPROVAL
COMPLETED
```

## 15. 数据模型策略

优先复用：

```text
operation_definitions
operations
attempts
sagas
saga_steps
operation_dependencies
authority_asset
authority_asset_version
asset_qualifications
external_effects
provider receipts
budget reservations / settlements
approval records
audit / outbox / trace
```

首期新增最小关系表：

```text
story_plan_binding
active_story_plan_version
planning_horizon
asset_dependency_edge
asset_semantic_diff
asset_impact_report
asset_regeneration_plan
story_production_cursor
child_delegation
child_acceptance_receipt
chapter_outcome
```

禁止新增第二套 Task、Attempt、Approval、Provider Receipt 或完整 PlanVersion 内容权威。

## 16. 实施顺序

```text
Gate 0  现有真实 Provider 单章基线（条件允许时）
Phase 1 Production Execution Plane Core
Phase 2 Book Design / Planning Contract Core
Phase 3 Book → Chapter 真实委托
Phase 4 ChapterGroup Authority and Rolling Horizon
Phase 5 ChapterPlan / GroupPlan Semantic Generator
Phase 6 World / Character / Book / Volume Generator
Phase 7 Arc Semantic Graph and Closure
Phase 8 ChapterOutcome / Story State / Recap / Impact
Phase 9 Reader Outcome Judge Shadow
Phase 10 Human Anchor / Behavior Calibration / Experiment
Phase 11 Real Longform and Completion Proof
```

原则：先纵向打通真实生产闭环，再横向补齐所有 Generator 和高级自治。

## 17. 测试与验收

### 17.1 Generator DoD

```text
Real Execution Receipt
+ Candidate AssetVersion
+ Materializer
+ Semantic Validator
+ Bounded Repair
+ Approval Policy
+ Activation
+ Replay
+ Cost Evidence
```

### 17.2 Book Design DoD

```text
Creative
→ Theme
→ Ending
→ World
→ Character Cast
→ BookPlan
→ VolumePlan
→ Initial ChapterGroupPlan
→ Approved Design Snapshot
```

各 Generator 独立记录成熟度，不要求一次全部达到 Real Provider Proven。

### 17.3 Longform Closed Loop DoD

```text
ChapterPlan
→ Real Chapter Saga
→ ChapterOutcome
→ Deterministic Reducers
→ Longform Evaluation
→ Recap
→ PlanChangeProposal
→ Impact / Approval
→ New Future Plan Versions
```

### 17.4 验收阶梯

```text
L1  2—3 chapters
L2  10 chapters with formal recap
L3  30 chapters and multiple groups
L4  complete Arc closure
L5  complete Volume closure
L6  representative full-book / million-character state proof
```

### 17.5 成熟度标志

```text
documented
handler_bound
fixture_proven
integration_proven
real_provider_proven
human_anchored
behavior_calibrated
causal_validated
longform_proven
production_verified
```

任何 Flag 必须由测试、Receipt、运行报告和审计证据支持。

## 18. 明确后置项

第一阶段不做：

- 多书 Portfolio 调度；
- 多主机和多账号自动分配；
- 无审批整卷重写；
- Reader Outcome 自动控制所有发布；
- 强化学习直接修改生成模型；
- 全自动发布；
- 以页面数量证明完成度。

## 19. 最终目标

完成后系统应支持：

```text
启动一本书
→ 冻结 Approved Book Design Snapshot
→ 激活当前 Volume 和 ChapterGroup
→ 生成并冻结当前 ChapterPlan
→ 委托真实 Chapter Saga
→ 接受 Canon / Quality / Release / Cost
→ 提交 ChapterOutcome 和 Story State
→ 复盘和 Plan-vs-Actual
→ 受控调整未来计划
→ 完成 Arc / Volume / Book Closure
→ 最终全书验收
```

Novel Forge 的下一阶段重点不是继续增加外围模块，而是把已有能力串成真实、可恢复、可长期演化的单书生产闭环。