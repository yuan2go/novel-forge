# Book Design Authority 与长篇闭环工程实施计划

> 文档类型：工程执行计划、Epic/WP 拆解、迁移与验收方案  
> 更新日期：2026-07-22  
> 目标分支：`feat/v7-content-intelligence-and-longform-proof`  
> 上位设计：[`../design/book-design-authority-and-longform-closed-loop.md`](../design/book-design-authority-and-longform-closed-loop.md)  
> 状态：ACTIVE PLAN  

---

## 1. 实施目标

本计划将当前的 Pre-Provider Production Architecture 升级为一条真实可运行的单书生产链：

```text
Creative Brief
-> Semantic Candidate Generation
-> Theme / Ending
-> World / Character Cast
-> Book / Volume / Arc / ChapterGroup
-> ChapterPlan V3
-> Real Chapter Saga
-> ChapterOutcome / Reducers
-> Longform Recap / Future Replan
-> Completion Gate
```

本计划强调渐进改造：

- 不推倒 Command Kernel；
- 不新建第二套任务系统；
- 不新建第二套 Provider runtime；
- 不一次性重写全部 Asset Schema；
- 不先扩展多书和 SaaS；
- 不把 fixture proof 标记为 real provider proof。

---

## 2. 执行原则

### 2.1 最短生产闭环优先

优先顺序：

```text
ChapterPlan Authority Generator
-> Shared Generator Runtime
-> Hierarchical Planning
-> World / Character Generator
-> Book Design Saga
-> Real Book-to-Chapter Delegation
-> Asset Impact
-> Longform Adaptation
-> Completion
-> Feedback Authority
```

### 2.2 Contract First

每个 Work Package 先完成：

1. command contract；
2. output contract；
3. lifecycle；
4. failure taxonomy；
5. evidence requirements；
6. tests；
7. 再实现 handler 和 UI。

### 2.3 Characterization Before Refactor

重构以下现有模块前必须先补 characterization tests：

- `modules/chapter_authority/model_effects.py`；
- `modules/content_authority/`；
- `modules/outline/service.py`；
- `modules/chapter_plan/service.py`；
- `modules/book_authority/`；
- `modules/feedback/`；
- `modules/feedback_backflow/`。

### 2.4 新写入走 Authority，旧读取兼容

迁移策略：

```text
Read old + new
Write new only
Migrate selected old assets
Disable old production writes
Remove obsolete semantics last
```

### 2.5 每个阶段必须更新

- OperationDefinition catalog；
- maturity matrix；
- current state docs；
- API contract；
- tests；
- evidence report；
- Web Admin capability status。

---

## 3. 总体 Epic

| Epic | 名称 | 优先级 | 关键结果 |
|---|---|---:|---|
| E0 | Contract Rebaseline | P0 | 冻结统一语义和边界 |
| E1 | Shared Generator Runtime | P0 | 上游 Generator 共享 ExternalEffect |
| E2 | ChapterPlan Authority Generator | P0 | 真实生成 V3 ChapterPlan |
| E3 | Hierarchical Planning Authority | P0 | Book/Volume/Arc/ChapterGroup |
| E4 | World and Character Generators | P0 | 真实世界和角色群生成 |
| E5 | Creative, Theme and Ending Generators | P1 | 完整 Book Design 上游 |
| E6 | Book Design Root Saga | P0/P1 | 创意到初始规划闭环 |
| E7 | Asset Dependency and Impact | P1 | 变更传播和重生成 |
| E8 | Real Book-to-Chapter Delegation | P0 | Book Saga 调用真实 Chapter Saga |
| E9 | ChapterOutcome and Story Reducers | P0 | 单章结果回写长期状态 |
| E10 | Longform Adaptation | P1 | Recap 调整未来规划 |
| E11 | Completion Authority | P1 | 结局和 Payoff 验收 |
| E12 | Reader Feedback Authority | P2 | 真实反馈受控调整规划 |
| E13 | Product Consoles | P1/P2 | 可执行操作台 |
| E14 | Real Provider and Longform Proof | P0-P2 | 3/10/30/100 章证明 |

---

# 4. E0：Contract Rebaseline

## 4.1 目标

在继续编码前冻结以下概念：

```text
Generator
Candidate
Materializer
Validator
Repair
Approver
Activator
Reducer
Snapshot
Planning Horizon
```

## 4.2 WP-0.1 Generator Boundary Contract

### 修改范围

建议新增：

```text
src/novel_forge/modules/generator_runtime/contracts.py
src/novel_forge/modules/generator_runtime/failures.py
src/novel_forge/modules/generator_runtime/policies.py
```

### 主要类型

```text
GeneratorDefinition
GenerationRequest
GenerationReceipt
GenerationCandidateRef
GenerationValidationReport
GenerationRepairPlan
GenerationActivationDecision
```

### 错误码

```text
GENERATOR_INPUT_NOT_FROZEN
GENERATOR_ROUTE_NOT_QUALIFIED
GENERATOR_PROVIDER_RECEIPT_MISSING
GENERATOR_OUTPUT_SCHEMA_INVALID
GENERATOR_SEMANTIC_VALIDATION_FAILED
GENERATOR_REPAIR_LIMIT_EXCEEDED
GENERATOR_APPROVAL_REQUIRED
GENERATOR_ACTIVATION_CONFLICT
```

### 测试

```text
tests/unit/test_generator_runtime_contracts.py
tests/unit/test_generator_failure_taxonomy.py
```

### DoD

- 类型可序列化；
- contract version 明确；
- failure class 可稳定映射；
- 不依赖 LocalStorage；
- 不调用模型。

---

## 4.3 WP-0.2 Planning Contract

### 新增类型

```text
BookPlan
VolumePlan
ArcPlan V2
ChapterGroupPlan
PlanningHorizon
PlanAdjustmentProposal V2
PlanningSemanticDiff
```

### 原则

- 不立即重写 `schemas/assets.py` 全部轻类型；
- 先在 domain contract 中提供严格 dataclass/Pydantic model；
- Authority AssetVersion content 使用 contract version；
- 旧 `Outline`、`LongFormMacroPlan`、`ArcPlan` 通过 adapter 读取。

### 测试

```text
tests/unit/test_planning_contracts.py
tests/unit/test_planning_horizon_policy.py
tests/unit/test_legacy_outline_adapter.py
```

---

## 4.4 WP-0.3 ChapterPlan V3 Unification

### 目标

Authority `PLAN_FIELDS` 成为唯一新写入合同。

### 修改

- 提取 ChapterPlan V3 schema 到稳定 contract；
- Legacy `scene_beats`、`conflict_beats` 等映射到 V3；
- 增加无法无损映射的 warnings；
- 新 Generator 直接输出 V3 Candidate；
- `chapter.plan.materialize` 保持 Materializer 名称和职责。

### 禁止

- 不创建 `ChapterBlueprintV4`；
- 不保留两个新的生产 Schema；
- 不让 Chapter Materializer 内调用 Provider。

### 测试

```text
tests/unit/test_chapter_plan_v3_contract.py
tests/unit/test_chapter_plan_v3_legacy_mapping.py
tests/unit/test_chapter_plan_v3_qualification_profiles.py
```

---

# 5. E1：Shared Generator Runtime

## 5.1 目标

将 `chapter_authority/model_effects.py` 中可复用的 ModelProviderResult、budget 和 ExternalEffect 模式抽取为共享 Runtime。

## 5.2 WP-1.1 Shared Model Receipt

### 建议结构

```text
src/novel_forge/modules/model_effect_runtime/
  __init__.py
  contracts.py
  routes.py
  adapter.py
  runtime.py
  normalization.py
  reconciliation.py
```

### 迁移方式

1. 先把 `ModelProviderResult` 提取到 shared contracts；
2. Chapter 模块从新位置 import；
3. 保持旧 import shim 一段时间；
4. 所有现有 Chapter tests 必须无行为变化。

### DoD

- Chapter Authority 回归全部通过；
- 新 Runtime 不知道 World、Character 等业务；
- Provider receipt 字段与现有证据兼容；
- real provider eligibility 继续由 ProviderControl profile 决定。

---

## 5.3 WP-1.2 Content Model Route Registry

### 能力

```text
route by generator_definition
route qualification
prompt/skill version binding
provider capability binding
token and cost budget
production eligibility
```

### Operation

不新增业务 Operation，只提供内部 Runtime API。

### 测试

- route missing fail closed；
- legacy uncontrolled adapter 不能用于 production proof；
- route identity 不完整失败；
- prompt/skill version 缺失失败；
- budget reserve/settle 正确。

---

## 5.4 WP-1.3 Generic ExternalEffect Dispatch

### 流程

```text
plan_external_effect
-> reserve_provider_budget
-> dispatch_external_effect
-> accept/query/callback/reconcile
-> normalize receipt
-> settle budget
-> materialize receipt asset/evidence
```

### 测试

```text
tests/integration/test_content_model_external_effect_postgres.py
tests/integration/test_content_model_unknown_reconciliation.py
tests/integration/test_content_model_budget_serialization.py
```

---

## 5.5 WP-1.4 Generator Candidate Materialization

### 输出

每次模型调用首先写：

```text
GenerationReceipt AssetVersion
GenerationCandidate AssetVersion
```

不得直接写 Active domain asset。

### DoD

- 同一 receipt replay 不重复 materialize；
- response digest 冲突 fail；
- Candidate references frozen inputs 和 receipt；
- Candidate 默认 lifecycle=`CANDIDATE`；
- qualification 尚未发生时不能 activate。

---

# 6. E2：ChapterPlan Authority Generator

## 6.1 为什么最先实施

这是连接上游规划和现有十八节点 Chapter Authority 的最短生产缺口。当前 Chapter Authority 已能消费 Frozen ChapterPlan，但 Authority 没有真实生成该计划。

## 6.2 WP-2.1 ChapterPlan Generation Input View

### 输入

```text
Active BookPlan
Active VolumePlan
Active ArcPlan
Active ChapterGroupPlan
Previous ChapterOutcome
Current Story Snapshots
Platform Strategy
Quality Profile
Style Policy
Stage-specific ContextBundle
Feedback Constraints
```

### 输出

```text
ChapterPlanGenerationView
```

必须：

- 只包含冻结输入；
- 不包含 raw source；
- 有 digest；
- 有 token budget；
- 有 ContextBuilder evidence。

---

## 6.3 WP-2.2 `chapter_plan.generate`

### 新 OperationDefinition

```text
chapter_plan.generate
```

### 输出

```text
chapter_plan_candidate
```

### Provider contract

直接要求 V3 字段，不再先生成 Legacy objective/beats 后转换。

### Qualification

候选 materialize 后调用现有 profile：

- opening；
- ordinary；
- payoff；
- climax/ending。

---

## 6.4 WP-2.3 ChapterPlan Semantic Validators

除现有字段完整性外增加：

- opening_state -> closing_state 有变化；
- scene sequence 可执行；
- conflict escalation 非空；
- protagonist agency；
- antagonist pressure；
- reveal/withhold 平衡；
- reward setup/payoff 逻辑；
- promise/foreshadow 动作可追踪；
- Canon expected changes 可接受；
- world rule usage 合法；
- power change 合法；
- hook 与 next bridge 一致；
- 不违反 prohibited outcomes；
- 与 Arc/ChapterGroup 目标一致。

### 输出

```text
ChapterPlanSemanticReport
```

---

## 6.5 WP-2.4 ChapterPlan Repair

### Repair 分类

- missing semantic field；
- state transition invalid；
- weak conflict；
- passive protagonist；
- missing payoff；
- continuity conflict；
- unsupported world rule；
- hook mismatch。

### DoD

至少证明一个负例：

```text
Candidate blocked
-> RepairPlan
-> Provider repair
-> New Candidate
-> Eligible
-> Freeze
-> Chapter Authority consumes exact version/hash
```

---

## 6.6 WP-2.5 Product API and Projection

### API

```text
POST /product/planning/chapter-plans/generate
GET  /product/planning/chapter-plan-operations/{operation_id}
POST /product/planning/chapter-plans/{version_id}/approve
POST /product/planning/chapter-plans/{version_id}/freeze
```

### UI 最小能力

- 生成；
- 查看 Candidate；
- 查看 validation；
- 触发 repair；
- 审批；
- freeze；
- 查看将被哪个 Chapter Saga 使用。

---

# 7. E3：Hierarchical Planning Authority

## 7.1 WP-3.1 BookPlan Domain

### Builder/Validator

```text
build_book_plan
validate_book_plan_structure
validate_book_plan_theme_alignment
validate_book_plan_ending_alignment
validate_book_plan_serialization
```

### 关键负例

- 没有全书 reader promise；
- 冲突只能发生一次；
- 反派没有升级空间；
- 主角弧和结局无关；
- 卷目标重复；
- 重大 payoff 无落点。

---

## 7.2 WP-3.2 VolumePlan Domain

### 约束

- 每卷有独立功能和状态变化；
- 不允许只按章数机械切卷；
- 卷高潮必须改变世界/人物/关系至少一项；
- 卷末必须有下一卷桥梁；
- 卷级 promise 必须有 payoff policy。

---

## 7.3 WP-3.3 ArcPlan V2

### 迁移

现有 `ArcPlan` 继续可读；新 contract 增加：

```text
parent_volume_version_id
setup
inciting_event
complications
midpoint
crisis
climax
resolution
state_transition
```

### 禁止

不在旧 AssetVersion 上原地追加字段并假装迁移完成；必须有 contract version 和 adapter。

---

## 7.4 WP-3.4 ChapterGroupPlan

### 目标

形成未来 10–20 章的滚动局部计划。

### Validator

- chapter function 分布；
- conflict escalation；
- reward cadence；
- reveal cadence；
- promise debt；
- foreshadow progression；
- antagonist actions；
- relationship movement；
- opening/exit state consistency。

---

## 7.5 WP-3.5 PlanningHorizon

### Operation

```text
planning.horizon.initialize
planning.horizon.evaluate
planning.horizon.refresh
planning.horizon.freeze
```

### 并发

```text
concurrency_key = project:{project_id}:planning-horizon
```

### DoD

- 当前 chapter 只有一个 Frozen Plan；
- planned/speculative 边界可查询；
- refresh 不修改 executed/frozen；
- horizon version optimistic concurrency；
- Book Saga 能判断是否需要 refresh。

---

## 7.6 WP-3.6 Legacy Outline Import

### 工具

```text
outline.import_to_planning_authority
```

### 输出

- BookPlanCandidate；
- VolumePlanCandidate[]；
- ArcPlanCandidate[]；
- migration report；
- unresolved field warnings。

### DoD

迁移不是自动 activate；必须通过 validation/approval。

---

# 8. E4：World 与 Character Generator

## 8.1 WP-4.1 World Candidate Generator

### 复用

- 现有 `build_world_bible`；
- 现有 `validate_world_rules`；
- Content Authority frozen input codec。

### 新增

```text
world.design.generate
world.design.materialize
world.systems.validate
world.ending_compatibility.evaluate
world.repair
world.approve
world.activate
```

### 关键要求

模型输出 Candidate，现有 builder 负责正式 WorldBible 结构化。

---

## 8.2 WP-4.2 World Child Model Extraction

从 WorldBible 生成 typed child assets：

```text
WorldRule
WorldFaction
WorldInstitution
WorldLocation
PowerSystem
EconomySystem
WorldConflictMap
```

不要求第一阶段全部关系表化；先形成版本化 child AssetVersion 和 dependency edges。

---

## 8.3 WP-4.3 Character Cast Generator

### 输入

- ProjectProposal；
- ThemeQuestion；
- EndingIntent；
- Active WorldBible；
- BookPlan constraints（若已有）；
- Genre/Platform/Quality profiles。

### 输出

```text
CharacterCastCandidate
```

候选包含：

- CastFunctionMatrix；
- CharacterProfiles；
- initial relationships；
- CharacterArcs；
- antagonist strategy；
- voice distinctions。

---

## 8.4 WP-4.4 Character Validators

```text
character.cast_function.evaluate
character.profile.validate
character.voice_distinctness.evaluate
character.relationship_network.evaluate
character.arc.validate
character.world_compatibility.evaluate
character.ending_compatibility.evaluate
```

### 关键负例

- 被动主角；
- 主角优势无代价；
- 主要人物功能重复；
- 反派无独立目标；
- 反派不适应；
- 关系只存在标签无状态；
- 全员相同声音；
- 人物弧无法到达 EndingContract。

---

# 9. E5：Creative、Theme 与 Ending Generator

## 9.1 WP-5.1 Real Creative Candidate Provider

替换 scripted-only proof，接入 Shared Generator Runtime。

### 首次真实 proof

- 至少 3 个候选；
- mechanism distinct；
- ProviderReceipt real_model_call=true；
- token/cost；
- candidate evaluation；
- operator approval。

---

## 9.2 WP-5.2 Theme Candidate Generator

### 输出

- ThemeCandidate[]；
- ThemeQuestion candidate；
- initial ThemePositionMap；
- ThemeArc direction。

### Validator

- concrete pressure；
- multiple defensible positions；
- costly choice；
- no predetermined sermon；
- compatible with protagonist/antagonist。

---

## 9.3 WP-5.3 EndingIntent Generator

### 输出多个方向

至少比较：

- closed resolution；
- bittersweet；
- partial/open but designed；
- tragic（题材允许时）。

### 评估

- promise payoff capacity；
- character arc completion；
- world state causality；
- antagonist terminal causality；
- theme re-answer；
- serialization fit。

---

## 9.4 WP-5.4 Theme/Ending Compatibility Gate

阻断：

- Ending 回答与 ThemeQuestion 无关；
- 主角最终选择不承担代价；
- 反派终态无法体现价值冲突；
- 开放结局没有明确保留项；
- Ending 依赖未设计能力。

---

# 10. E6：Book Design Root Saga

## 10.1 WP-6.1 Operation Graph

新增模块建议：

```text
src/novel_forge/modules/book_design_authority/
  application.py
  definitions.py
  registry.py
  handlers.py
  scheduler.py
  projections.py
```

### Root Operation

```text
book.design.run
```

### 子 Operation

按主设计文档第 16 节。

---

## 10.2 WP-6.2 Approval Gates

审批点：

- ProjectProposal；
- Theme + Ending；
- World core rules；
- CharacterCast；
- BookPlan；
- first Volume/Arc/ChapterGroup。

### 测试

- gate waiting；
- reject；
- approve；
- pause/resume；
- duplicate admission replay；
- child failure；
- root completion contract。

---

## 10.3 WP-6.3 Book Design Projection

Query 返回：

```text
current stage
completed stages
active candidates
waiting approvals
blocking validation
cost summary
real provider evidence
active asset versions
planning readiness
```

---

# 11. E7：Asset Dependency 与 Impact

## 11.1 WP-7.1 Dependency Writer

每次 Asset materialize/activate 时写 dependency edges。

### 第一批支持

```text
ProjectProposal -> ThemeQuestion
ProjectProposal -> WorldBible
ThemeQuestion -> CharacterCast
EndingIntent -> BookPlan
WorldBible -> CharacterCast
CharacterCast -> BookPlan
BookPlan -> VolumePlan
VolumePlan -> ArcPlan
ArcPlan -> ChapterGroupPlan
ChapterGroupPlan -> ChapterPlan
ChapterPlan -> Accepted Chapter
```

---

## 11.2 WP-7.2 Semantic Diff

### 第一阶段

按字段路径比较：

```text
changed_fields
added_fields
removed_fields
changed_collections
```

### 第二阶段

增加领域语义分类：

```text
CORE_RULE
CHARACTER_IDENTITY
CHARACTER_GOAL
ENDING_DIRECTION
PLOT_STRUCTURE
STYLE_ONLY
DESCRIPTIVE_ONLY
```

---

## 11.3 WP-7.3 Impact Policy Registry

示例：

```text
WorldRule.cost -> HARD regenerate CharacterCapability
CharacterProfile.appearance -> REFERENCE refresh Context
EndingIntent -> HARD revalidate BookPlan
ArcPlan.reward_schedule -> HARD regenerate planned ChapterPlans
```

---

## 11.4 WP-7.4 General Asset Change Saga

```text
asset.change.analyze
asset.impact.report
asset.invalidation.propose
asset.regeneration.plan
asset.regeneration.approve
asset.regeneration.execute
asset.version.activate
asset.regeneration.rollback
```

### 复用

尽可能复用 Source Diff Repair 中的：

- impact report 结构；
- approval pattern；
- stale marking；
- rollback plan/result；
- no silent mutation policy。

---

# 12. E8：真实 Book-to-Chapter Delegation

## 12.1 WP-8.1 Replace Fixture Chapter Dispatch

`book.chapter.dispatch` 不再生成：

```text
ACCEPTED_FIXTURE_PROTOCOL
```

而是创建真实 `chapter.slice.run` child Saga。

### 兼容

保留 explicit fixture mode 供架构测试，但必须：

- 单独 policy；
- 显示 fixture_protocol_only=true；
- 不计入 longform proof；
- 不与 production entrypoint 混用。

---

## 12.2 WP-8.2 Child Completion Binding

Book child completion 必须引用：

- chapter root operation id；
- accepted draft/revision version；
- ChapterPlan version/hash；
- Quality Aggregate；
- Canon update result；
- release decision；
- provider cost settlement。

---

## 12.3 WP-8.3 Budget and Cancellation Propagation

验证：

- book budget；
- chapter budget；
- provider budget；
- cancel root -> cancel active child；
- pause root -> 不创建新 child；
- active child 的取消遵循 Chapter policy；
- budget exhaustion -> WAITING_GATE。

---

## 12.4 WP-8.4 3-Chapter Real Delegation Proof

这是进入 10 章前的强制门禁。

必须证明：

```text
Book Root Saga
-> 3 real Chapter Sagas
-> 3 accepted ChapterOutcomes
-> Recap
-> exact cost settlement
-> pause/resume
```

---

# 13. E9：ChapterOutcome 与 Story Reducers

## 13.1 WP-9.1 ChapterOutcome Contract

从 accepted chapter、plan、review、canon 和 quality evidence 构建。

### 不允许

- 只保存自由文本 summary；
- 把 Provider 原始结果直接当 Snapshot；
- 未 accepted chapter 写状态。

---

## 13.2 WP-9.2 Planned vs Actual Diff

新增：

```text
chapter.plan_actual.evaluate
```

输出：

```text
ChapterPlanActualDiff
```

---

## 13.3 WP-9.3 Reducer Orchestration

新增：

```text
chapter.outcome.reduce
```

内部协调：

- Canon；
- Timeline；
- Character；
- Relationship；
- Foreshadow；
- Promise；
- Reward；
- Power；
- Mystery。

### 原则

每个 reducer 可单独 replay 和测试，但由一个 Authority Operation 统一提交 Snapshot manifest。

---

## 13.4 WP-9.4 Snapshot Manifest

输出：

```text
StoryStateCommitManifest
```

包含：

- previous snapshot versions；
- new snapshot versions；
- applied events；
- skipped events；
- approvals；
- content hashes；
- reducer versions。

---

# 14. E10：Longform Adaptation

## 14.1 WP-10.1 NarrativeDebt Registry

统一 promise、foreshadow、mystery、relationship、arc、world explanation、reward、theme 等债务。

---

## 14.2 WP-10.2 Enhanced Formal Recap

当前 semantic reports 继续复用，增加：

- PlanActualDiff aggregation；
- PlanningHorizon health；
- EndingFeasibility；
- NarrativeDebt；
- chapter economy trend；
- character pressure trend；
- mobile/readability trend。

---

## 14.3 WP-10.3 Planning Adjustment Proposal V2

必须明确：

```text
trigger
problem evidence
target planning nodes
proposed changes
preserve constraints
impact risk
freeze conflict
estimated cost
approval policy
```

---

## 14.4 WP-10.4 Future Planning Regeneration

仅允许作用于：

- planned；
- speculative；
- 经审批的 frozen。

执行顺序：

```text
ChapterGroup
-> ChapterPlan candidates
-> validate
-> activate/freeze
-> update PlanningHorizon
```

---

# 15. E11：Completion Authority

## 15.1 WP-11.1 EndingContract Activation

在 BookPlan 激活前必须建立 EndingContract；允许后续新版本，但必须 impact analysis。

---

## 15.2 WP-11.2 ClosureMatrix

从以下 Authority 状态构建：

- CharacterArc；
- RelationshipState；
- MysteryState；
- ForeshadowState；
- PromiseState；
- WorldState；
- ThemeMovement；
- AntagonistThreat；
- RewardState。

---

## 15.3 WP-11.3 CompletionReadiness

### Blocker rules

按主设计文档执行。

### UI

必须支持从 blocker 跳转：

- source asset；
- relevant chapters；
- evidence；
- proposed fix；
- required approval。

---

## 15.4 WP-11.4 Final Completion Saga

只有 Final Approval 才能把 Book lifecycle 改成 `COMPLETED`。

---

# 16. E12：Reader Feedback Authority

## 16.1 WP-12.1 PostgreSQL Feedback Operations

迁移：

```text
feedback.import
feedback.normalize
feedback.cluster
feedback.attribute
feedback.confidence.evaluate
feedback.plan_adjustment.propose
feedback.adjustment.approve
feedback.adjustment.apply
```

---

## 16.2 WP-12.2 Platform Metrics Contract

第一批：

```text
impressions
opens
chapter_reads
completion_rate
next_chapter_rate
favorite_rate
comment_rate
payment_conversion
chapter_dropoff
character_mentions
```

每个指标必须记录：

- platform；
- measurement window；
- sample size；
- denominator；
- source receipt；
- confidence；
- anomaly flags。

---

## 16.3 WP-12.3 Attribution and Confidence Gate

不能仅靠关键词聚类决定主线修改。至少提供：

- deterministic baseline；
- optional provider-assisted attribution；
- human calibration sample；
- confidence threshold；
- no-change outcome。

---

## 16.4 WP-12.4 Post-adjustment Evaluation

调整后比较：

- 目标指标；
- 非目标副作用；
- 内容质量；
- 长篇一致性；
- cost；
- 是否 rollback。

---

# 17. E13：产品控制台

## 17.1 页面优先级

### P0

1. ChapterPlan Generator Console；
2. Hierarchical Planning Tree；
3. Book Saga Timeline；
4. Approval Queue；
5. Generator Receipt/Repair Inspector。

### P1

1. Creative Incubation；
2. Theme/Ending；
3. World Design；
4. Character Cast；
5. Longform Health；
6. Dependency Impact。

### P2

1. Feedback Adaptation；
2. Completion Console；
3. Advanced cost analytics；
4. multi-book views。

## 17.2 UI 共同要求

每个 Asset 页面显示：

```text
asset id
version id
content hash
lifecycle
eligibility
governance
active/superseded
input versions
provider receipt
validation
repair attempts
approval
cost
maturity evidence
```

---

# 18. E14：验收与证明

## 18.1 Architecture Proof

必须证明：

- 所有定义注册；
- handler binding；
- input frozen；
- idempotency；
- completion contract；
- audit/outbox；
- pause/resume/cancel；
- migration rollback。

这只允许标记 `integration_proven`。

## 18.2 Real Provider Proof

每类核心 Generator 至少一次：

- Creative；
- World；
- CharacterCast；
- BookPlan；
- ChapterPlan。

才允许标记对应 `real_provider_proven`。

## 18.3 Longform Proof Ladder

### 3 章

验证真实 Book delegation。

### 10 章

验证：

- ChapterOutcome；
- reducers；
- light/formal recap；
- future plan adjustment；
- cost growth。

### 30 章

验证一个完整 ChapterGroup：

- 规划滚动；
- NarrativeDebt；
- payoff；
- state consistency；
- no manual database mutation。

### 100 章

验证一个完整卷。

### 300 章

验证多卷和 EndingFeasibility 的长期变化。

---

# 19. 建议代码目录

```text
src/novel_forge/modules/
  generator_runtime/
  model_effect_runtime/
  planning_authority/
  book_design_authority/
  asset_dependency_authority/
  chapter_outcome/
  story_state_reducers/
  completion_authority/
  feedback_authority/
```

注意：

- 目录名是建议，不要求一次迁移现有包；
- 优先增加 facade/protocol；
- 现有 domain 逻辑保留原位置也可以；
- 不为了目录美观做无收益移动。

---

# 20. 数据迁移顺序

## Migration 1：Generator Runtime Tables

- generation request/receipt；
- repair plan/attempt；
- indexes；
- foreign keys to operation/external effect/asset version。

## Migration 2：Planning Authority

- planning horizons；
- optional planning node projection；
- activation/freeze constraints。

## Migration 3：Asset Dependency

- dependency edges；
- semantic diff；
- impact report linkage；
- regeneration plan linkage。

## Migration 4：ChapterOutcome

- chapter outcome；
- story state commit manifest projection。

## Migration 5：Feedback/Completion

按实际查询需要增量添加，不提前创建空表。

### 迁移要求

- forward migration；
- rollback/rehearsal；
- fixture data；
- PostgreSQL integration test；
- catalog binding test；
- no SQLite/local silent fallback。

---

# 21. 推荐提交策略

每个 WP 使用独立小提交，示例：

```text
feat(generator): add shared generation contracts
refactor(model): extract shared provider receipt runtime
feat(planning): add chapter plan authority generator
feat(planning): add book and volume contracts
feat(world): add world candidate generation
feat(character): add cast generation authority
feat(book): add book design root saga
feat(asset): add dependency impact authority
feat(book): delegate real chapter sagas
feat(state): add chapter outcome reducers
feat(longform): add governed planning adaptation
feat(ending): add completion authority
```

禁止一个提交同时：

- 大规模移动目录；
- 修改生产行为；
- 更换 Schema；
- 重写 UI；
- 更新数十份历史报告。

---

# 22. 测试命令建议

根据当前项目工具链，阶段性执行：

```bash
python3 -m compileall -q src tests
python3 -m unittest tests.unit.test_generator_runtime_contracts
python3 -m unittest tests.unit.test_chapter_plan_v3_contract
python3 -m unittest tests.unit.test_planning_contracts
python3 -m unittest tests.integration.test_content_model_external_effect_postgres
python3 -m unittest tests.integration.test_book_design_authority_postgres
python3 -m unittest tests.integration.test_book_real_chapter_delegation
python3 -m unittest tests.acceptance.test_book_design_to_three_chapters
make lint
```

最终仍需运行仓库当前定义的 architecture、unit、PostgreSQL、migration、catalog 和 Web Admin jobs。

---

# 23. 每阶段文档更新

完成 WP 后更新：

```text
docs/project-current-state.md
docs/reports/operation-definition-maturity-matrix.md
docs/reports/blueprint-gap-audit.md
docs/reports/module-maturity-matrix.md
docs/reports/data-model-gap-matrix.md
docs/README.md
```

新增证据报告命名建议：

```text
docs/reports/chapter-plan-authority-generator-proof.md
docs/reports/hierarchical-planning-authority-report.md
docs/reports/world-character-generator-provider-proof.md
docs/reports/book-design-authority-report.md
docs/reports/asset-impact-authority-report.md
docs/reports/book-real-chapter-delegation-proof.md
docs/reports/chapter-outcome-reducer-proof.md
docs/reports/completion-authority-report.md
```

报告必须区分：

```text
deterministic fixture
scripted provider
real provider
longform
production
```

---

# 24. 阶段门禁

## Gate A：允许实施 Book Design Saga

必须完成：

- Shared Generator Runtime；
- ChapterPlan Authority Generator；
- Book/Volume/Arc/ChapterGroup contract；
- World/Character Candidate Generator；
- Approval policy。

## Gate B：允许真实 Book Delegation

必须完成：

- PlanningHorizon；
- Frozen ChapterPlan；
- ChapterPlan exact version/hash；
- child Saga binding；
- budget/cancel propagation；
- ChapterOutcome contract。

## Gate C：允许 10 章 proof

必须完成：

- 3 章 real delegation；
- Reducers；
- recap；
- planning refresh；
- write amplification measurement；
- cost budget。

## Gate D：允许 30 章 proof

必须完成：

- Asset Dependency；
- future regeneration；
- NarrativeDebt；
- formal recap；
- no silent mutation；
- rollback rehearsal。

## Gate E：允许 production claim

必须完成：

- real provider qualification；
- 真实长篇；
- calibrated quality；
- external publishing proof；
- operational runbook；
- backup/restore；
- incident/reconciliation drill。

---

# 25. 不应提前实施的内容

在 30 章真实闭环前推迟：

- 完整多租户 SaaS；
- 大规模多模型自动竞价；
- 十本并行自动调度；
- 自动平台发布；
- 自由规划通用 Agent；
- 独立微服务拆分；
- 全量知识图谱数据库迁移；
- 复杂跨书共享世界；
- 自动根据评论改结局。

这些功能应建立在单书生产权威已经闭合的基础上。

---

# 26. 最终执行顺序

建议严格按以下顺序推进：

```text
1. E0 Contract Rebaseline
2. E1 Shared Generator Runtime
3. E2 ChapterPlan Authority Generator
4. E3 Hierarchical Planning Authority
5. E4 World and Character Generators
6. E5 Creative, Theme and Ending Generators
7. E6 Book Design Root Saga
8. E9 ChapterOutcome Contract
9. E8 Real Book-to-Chapter Delegation
10. 3-chapter real proof
11. E7 Asset Dependency and Impact
12. E10 Longform Adaptation
13. 10-chapter proof
14. 30-chapter proof
15. E11 Completion Authority
16. E12 Reader Feedback Authority
17. 100/300-chapter proof
18. Multi-book and production hardening
```

其中 E9 的 Contract 应在 E8 前完成，因为真实 Book delegation 必须知道章节完成后如何形成长期状态提交。

---

# 27. 成功标准

本计划完成后，系统应能在不直接修改数据库、不复制粘贴模型输出、不覆盖历史资产的前提下完成：

```text
创意候选
-> 项目审批
-> Theme / Ending
-> World / Character Cast
-> 分层全书规划
-> 滚动 ChapterPlan
-> 真实章节生产
-> 状态回写
-> Recap
-> 未来规划调整
-> 结局和 Payoff 验收
```

最终工程判断标准不是模块数量，而是：

- 是否只有一个生产权威；
- 是否具有真实模型证据；
- 是否能恢复失败；
- 是否能控制成本；
- 是否能保持长篇状态；
- 是否能安全调整未来；
- 是否能证明作品真正完成。
