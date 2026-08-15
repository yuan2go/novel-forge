# Claude Code Prompt — Canonical Design to Production Code

下面这份提示工程用于持续把 Novel Forge 当前真实代码收敛到最新 Canonical Design。它是实施入口，不是新的架构 Source of Truth；若与 `docs/architecture/canonical-overall-design.md` 冲突，以重新审查后的 Canonical Design 和真实代码证据为准，并在同一变更中消除冲突。

---

# Novel Forge / Autonomous Novel OS Canonical Implementation & Qualification

请在以下仓库最新 `main` 上持续实施 Novel Forge：

```text
https://github.com/yuan2go/novel-forge
```

项目目标是建设：

> **Human-AI Collaborative Long-form Narrative Operating System with a Governed Autonomous Production Runtime**

不是简单小说生成器，也不是自由聊天的 Multi-Agent Demo。

## 1. 开发前必须先做真实性审查

不要直接按照文档机械编码。开始任何修改前必须：

```text
拉取最新 main
→ 记录 HEAD / worktree / Python / migration head /主要入口
→ 完整阅读 docs/architecture/canonical-overall-design.md
→ 阅读 docs/README.md 与相关 current-runtime 文档
→ 阅读当前真实代码、migrations、architecture manifests、tests、composition roots
→ 对照 Canonical Design 检查 docs 与代码是否一致
→ 识别 OUTDATED / SUPERSEDED / DEAD / LEGACY / FIXTURE_ONLY / UNWIRED / AUTHORITY_BYPASS / AI 残留
→ 只清理有真实证据的失效内容
→ 找到当前最重要的真实工程断点
→ 再开始开发
```

不要因为 Canonical Design 写了某项 Gap 就假设代码一定没有实现；近期 `main` 可能已经前进。反过来，也不要因为存在 DTO、Domain Type、Service、测试或文件名就认为能力已经完成。

若文档与代码冲突：

1. 判断哪一方代表正确的目标架构；
2. 保留可证明的现有正确实现；
3. 消除真正的旁路或过期设计；
4. 必要时同步更新 Canonical 文档；
5. 不建设平行替代 Runtime。

## 2. 必须保持的架构约束

### Authority

- PostgreSQL 是生产业务 Source of Truth。
- Agent / Provider / Conversation / Draft / Proposal 都不是 Canonical Story Authority。
- Agent 提议，Owning Domain Authority 接受/拒绝并提交。
- 禁止 Agent → direct SQL → Canon/Plan/Book State。
- Accepted history 不原地修改；未来变化走 version/supersession/replan，已接受或已发布内容的修正必须保留治理与 lineage。

### Long-form model

Canonical temporal hierarchy：

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

`Arc` 是跨时间的 orthogonal graph dimension，不是 `Volume → Chapter` 的树状父层。

不要重新引入被淘汰的：

```text
Book → Volume → Arc → Chapter
```

作为唯一层级模型。

### Agent / Capability

采用：

```text
少量稳定 Conversational Role / Agent Persona
+
大量 versioned Capability / Skill / Capability Pack
+
NarrativeScope / Context Contract
```

不要创建大量：

```text
BookCharacterAgent
VolumeCharacterAgent
ArcCharacterAgent
...
```

目标一等可对话角色包括：

```text
Chief Editor
Story Architect
Character Director
World Architect
Theme & Philosophy Advisor
Reader & Commercial Strategist
Plot Doctor
Research & Material Curator
Chapter Director
Chapter Editor
Long-form Retrospective
Reader Outcome Analyst
```

这些优先表达为现有 `AgentDefinition + capabilities + scope/context/policy`，不是每个角色一个 Authority/微服务/独立 Runtime。

### Conversational Creative Studio

作者既可以和 Chief Editor 对话，也可以直接进入专业 Agent。

Conversation 不是 Authority。目标语义：

```text
Conversation / Collaboration Session
→ candidate decisions
→ Accepted / Rejected / Open / Deferred
→ Proposal + rationale + scope
→ Semantic Diff（如修改既有设计）
→ Impact / Risk
→ Human / Policy Decision
→ Owning Authority Command
→ Versioned Commit / Activation / Supersession
```

优先扩展当前 `agent_collaboration`；不要在没有独立生命周期证据时新建第二个 Chat/Conversation Authority。

### Narrative Change

不要新建一个与现有系统重叠的通用 `NarrativeChangeAuthority`。

优先复用：

```text
agent_collaboration
plan_change_authority
revision / corrective_action
story / book design authority
planning / book_replan
Canon / Narrative State acceptance boundary
```

统一变更级别：

```text
L0 Text
L1 Scene
L2 Chapter Structural
L3 Arc / Volume Future
L4 Book / Canon Critical
```

局部编辑不能偷偷升级成结构性剧情修改。

### Chapter Editor

章节生成后的主要人工编辑入口应是 `Chapter Editor`：

```text
Draft
↔ Chapter Editor
→ Revision
→ Review / Re-review
→ Correctness
→ Canon / State candidate
→ Quality
→ Acceptance
```

如果作者改措辞、对话或局部场景，保持局部 Revision；如果影响 Chapter/Arc/Volume/Book，则自动升级到对应 Planning/PlanChange/Governance，而不是要求用户手工切换内部执行链。

### Author Intent

先评估当前 `NarrativeLayer.FUTURE_INTENT`、Story/Book Design、Planning contracts 是否足以承载 Author Intent / rationale。

除非发现明确独立生命周期、并发或 Authority 需求，不要创建 `AuthorIntentAuthority`。

Author Intent 需要能够进入 task-specific Context 和 Quality/Retrospective 判断，但仍不是 Accepted Story Truth。

### Context / Memory / Knowledge

明确区分：

```text
Authority Memory     = PostgreSQL accepted/design truth
Working Memory       = frozen/reproducible task Context
Interaction Evidence = conversation / rejected alternatives / rationale
Retrieval Memory     = rebuildable search/vector projection
MKAOS                = reusable methods / professional knowledge
```

Context 必须是 Minimum Sufficient Context，并能够区分：

```text
accepted truth
future intent
pending proposal
reader knowledge
character knowledge / belief
MKAOS / source evidence
```

防止 stale/future/hidden knowledge leakage。

### Execution Plane

保留当前唯一生产执行语义：

```text
Command
→ Operation
→ Attempt
→ Lease / Fence
→ ExternalEffect
→ Provider / Tool
→ Receipt
→ Domain Commit
```

`RuntimeJob` 按当前架构继续承担 durable worker execution/scheduling 角色。

不要增加第二个：

```text
WorkOrder Engine
Agent Workflow Engine
Conversation Runtime Kernel
Narrative Change Engine
```

除非真实代码证据表明现有执行模型无法满足需求，并在修改前证明原因。

## 3. 实施质量要求

禁止：

```text
Minimal Implementation
Stub
Placeholder
Fixture-only Implementation
Mock-only Proof
Temporary Architecture
Parallel Runtime
为了测试通过的特殊生产路径
```

对于确认需要建设的能力，按与项目定位匹配的生产级最佳实践实现。

但同时禁止 AI 式过度设计：

```text
无实际需求的 Interface/Adapter
重复 Authority
重复 Repository/Service 层
平行 Workflow Engine
无业务价值的配置系统
未来假设驱动的兼容层
人格化所有内部组件
大量 session/build-plan 文档
```

原则：

> **Production-grade ≠ Maximum Complexity。优先复用和收敛现有正确边界。**

## 4. 新能力必须进入 Canonical Runtime

新增能力不能只停留在：

```text
DTO
Enum
Domain Type
Service
Helper
Fixture
Unit Test
Standalone Module
```

根据能力性质，必须验证它真正进入必要的生产路径，例如：

```text
API / CLI / Operator Entry
→ Application
→ Domain Contract
→ Owning Authority
→ Command Kernel / RuntimeJob / Worker
→ ProductionExecutionComposition
→ Provider / Tool
→ Persistence
→ Quality / Governance
→ Consumer / downstream state
→ Trace / Metrics / Cost
```

并通过 manifest、composition root、worker registration、migration、contract test 或真实运行证据证明，而不是根据 import 推测。

## 5. Reliability / Failure semantics

根据本轮功能真实需求主动处理必要的：

```text
Idempotency
Technical Retry
Semantic Revision
Recovery / Resume
Replay
Lease / Fence
CAS / Optimistic Version
Concurrency
Transaction
ExternalEffect
Audit / Lineage
Trace / Metrics / Cost
Migration / Versioning
```

不要机械把所有机制复制到每个模块。

特别检查：

- technical retry 和 semantic revision 是否混淆；
- Provider 成功是否被错误等同于业务成功；
- Agent/Conversation candidate 是否能绕过 Authority；
- stale worker 是否能在 lease transfer 后提交；
- accepted content 是否存在 in-place mutation；
- recovery 是否依赖内存对象而不是 PostgreSQL state；
- replay 是否有 exact logical input/provenance。

## 6. 当前优先 Work Package

在重新审查最新 `main` 后，优先判断是否应该实施：

> **WP-CREATIVE-COLLAB-01 — Conversational Creative Collaboration + Chapter Editor + Narrative Change Integration**

它的目标不是增加聊天 UI，而是把作者可持续介入创作的语义接到现有工业级 Runtime：

```text
Human Conversation / Selected Text
→ existing Agent Collaboration scope
→ AgentDefinition / Capability / Context
→ Provider reasoning
→ Proposal / Decision Capture
→ L0–L4 Change Classification
→ Revision OR PlanChange OR Owning Design Authority
→ Impact / Approval / Requalification when required
→ Canonical Runtime
→ Trace / Recovery / Audit
```

重点核对和复用至少：

```text
agent_collaboration
agent_runtime
story_design_authority
book_design_authority
hierarchical_planning
plan_change_authority
book_replan
chapter_authority / chapter_group_authority
revision
corrective_action
chapter_quality_authority
narrative_state
context_builder / context_contracts
production_execution
command_kernel
runtime_job
provider_control / provider_qualification
```

但如果最新代码已经完整实现并证明该 Work Package，或者出现更高优先级的真实正确性断点，则根据证据调整 Work Package，不要为了执行提示词重复造功能。

## 7. 文档与 Legacy 清理

只保留小而清晰的文档体系：

```text
docs/architecture/canonical-overall-design.md = 唯一 Target Architecture
docs/architecture/* companion               = 当前 Runtime/Boundary 说明
docs/product/*                                = 派生产品视图
docs/operations/*                             = 运维
docs/development/*                            = 开发/验证
docs/adr/*                                    = 仍有效的 durable decisions
```

不要新增：

```text
session-summary.md
phase-N-plan.md
TODO-analysis.md
一次性 exact-SHA 报告
重复蓝图
大量 AI 生成设计说明
```

Legacy 只有在 migration/read-boundary 等被明确允许的路径中才可保留；不能成为新生产功能依赖。

## 8. 验证要求

至少执行并记录适用于当前代码的：

```text
Unit Test
Contract / Architecture Test
Integration Test
PostgreSQL Integration
Fresh Migration
Upgrade Migration
Lint
Type Check
Build / package validation
Capability Pack / Skill validation（如受影响）
```

条件具备时还必须执行：

```text
Real Provider
Real Canonical Runtime
Recovery / Retry / Replay Proof
End-to-End / Design-only proof
```

如果真实 Provider、PostgreSQL、外部服务或市场环境不可用，要明确：

```text
NOT_RUN / BLOCKED
```

以及具体原因，不能用 Mock/Fixture 替代后再升级结论。

## 9. 证据等级

最终对每项能力分别报告：

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
PRODUCTION_QUALIFIED
```

同时沿用项目 proof ladder：

```text
MISSING
SKELETON
IMPLEMENTED
WIRED
FIXTURE_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_PROVEN
```

必须绑定：

```text
Commit SHA
DB migration head
配置/Provider 模式
执行过的命令
测试结果
Evidence artifact / receipt / trace（如有）
```

不得把：

```text
代码阅读
Mock
Fixture
单元测试
单章成功
```

升级成 Real Provider、Long-form、Multi-book 或 Production 结论。

## 10. 持续推进规则

不要实现一个很小 TODO 就停止。

按以下循环持续推进同一个阶段：

```text
识别最重要真实断点
→ 完成完整 Work Package
→ 运行验证
→ 根据失败修复真实问题
→ 重新审查 Canonical Runtime
→ 补齐同一目标链必要断点
→ 再验证
```

直到该阶段形成：

```text
业务闭环
+
Authority closure
+
Runtime wiring
+
Failure semantics
+
Verification evidence
```

才结束。

遇到真正外部阻塞时才停止，并明确区分：

```text
CODE_FAILURE
ENVIRONMENT_BLOCKED
REAL_PROVIDER_BLOCKED
CI_ACCOUNT_BLOCKED
EXTERNAL_SERVICE_BLOCKED
```

## 11. Git / PR

- 从最新 `origin/main` 创建独立 feature branch；
- 不覆盖用户现有未提交修改；
- commit 要按真实逻辑边界组织；
- push 后创建 Draft PR；
- PR 描述列出设计目标、真实实现、验证命令、未运行项和证据等级；
- 保持最终 worktree clean；
- 不在同一 PR 混入无关重构。

## 12. 最终输出

最终报告只需要：

1. 起始 HEAD / 最终 HEAD；
2. 开发前发现的 Canonical Design 与真实代码偏差；
3. 清理的过期设计、Legacy 和 AI 残留；
4. 实际完成的能力；
5. 关键架构决策；
6. Canonical Runtime 如何变化；
7. 测试与真实运行验证结果；
8. 当前能力证据等级；
9. 尚未解决的真实 Gap；
10. 下一阶段最值得推进的 Work Package。

最后必须额外输出：

```text
# 下一阶段 Claude Code Prompt
```

生成下一轮可以直接执行的完整提示工程，使开发过程持续按照：

```text
Canonical Design
→ Real Code
→ Verification
→ Gap Review
→ Next Work Package
```

收敛。

---

## 最终判断原则

本任务不是为了增加更多 Agent、更多模块或更多文档。

判断一个改动是否应该进入核心系统，只问：

> 它是否真实提升了 Human-AI 创作协作、Narrative Correctness、Authority closure、Canonical Runtime、可靠性、可验证性或合理演进能力？

如果答案是否定的，默认不增加该复杂度。
