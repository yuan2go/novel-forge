# Novel OS Capability Pack 产品设计文档

> 文档类型：产品设计 / Product Requirement and Governance Design  
> 更新日期：2026-08-05  
> 目标分支：`feat/v7-content-intelligence-and-longform-proof`  
> 本轮静态审计 HEAD：`f8bb9f252ef701ede19a9a1838d4deaf513ff6fc`  
> 仓库既有实现证据基线：`8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`  
> 测试状态：`NOT_EXECUTED`；本轮未在本地执行测试，GitHub HEAD 无 Actions 状态和 workflow run 记录  
> 文档状态：`PROPOSED PRODUCT STANDARD`  

## 1. 执行摘要

Novel Forge 已经不是一个仅依赖 Prompt 调用模型的章节生成器。当前代码已经形成以下可复用基础：

- PostgreSQL Command Kernel；
- Operation、Saga、Attempt、Lease、Fencing、ExternalEffect；
- Authority Asset / AssetVersion；
- Production Execution Plane；
- CapabilityDefinition / CapabilityRegistry；
- PromptBundle / SkillBundle；
- ContextPolicy / SourcePolicy / ValidationPolicy / CommitPolicy；
- 18 节点 Chapter Authority；
- Book、BookDesign、Story Design、Hierarchical Planning、Reader Calibration、MKAOS Authority 等领域切片。

这些基础证明 Novel OS 已具备承载“可版本化业务能力包”的技术条件，但当前能力仍分散在代码常量、环境变量、Skill 文件、Prompt hash、Operation Definition、数据库表、领域 Handler 和架构文档中。系统能够执行若干受治理的能力，却不能用一个统一产品对象回答以下问题：

1. 某项业务能力由谁负责；
2. 它绑定哪些 Skill、Prompt、模型能力、工具和知识资产；
3. 它允许读取什么上下文，禁止读取什么上下文；
4. 它通过什么 Workflow 执行；
5. 它必须经过哪些 Judge、Quality Gate 和 Authority 决策；
6. 当前生产使用哪个版本；
7. 某次运行为什么被允许、失败、回滚或替换；
8. 该能力能否跨项目、跨书、跨环境迁移。

因此，本设计建议在 Novel OS 中引入 **Capability Pack**：

> Capability Pack 是面向业务结果的、可版本化、可治理、可执行、可评估、可审计的能力交付单元。它不是 Prompt 文件，不是 Skill 改名，也不是新的执行状态机。

Capability Pack 应作为 Agent OS 层的业务能力标准，向下编译并复用现有 Production Execution Plane、Command Kernel、Context Compiler、MKAOS、Quality / Review 和 PostgreSQL Authority。

首个落地对象应为：

```text
chapter_generation_pack
```

它对应当前最完整、证据最充分的 Chapter Authority 纵向链路，可以在不重构运行时的前提下完成最小协议、静态校验、版本治理和运行证据绑定。

---

## 2. 产品背景

### 2.1 当前产品形态

Novel Forge 的产品目标是 Autonomous Novel OS，即面向长篇网络小说生产的低人工干预、可恢复、可审计、可持续运行的内容生产操作系统。

当前生产结构已经从“Prompt → 模型 → 文本”演进为：

```text
Project / Book / Planning Authority
→ frozen AssetVersions
→ Command / Operation / Saga / Attempt
→ Context and Source Governance
→ Production Execution Gateway
→ Model / Agent / External Action
→ Validation and Quality Gates
→ Authority Commit
→ Canon / Story State / Reader Outcome / Longform Follow-up
→ Audit / Cost / Recovery / Operator Query
```

但产品能力的交付方式仍以多个分散对象存在：

- Skill 文件描述方法；
- PromptBundle 描述模型调用输入；
- CapabilityDefinition 描述执行能力；
- Workflow / ChapterNode 描述流程；
- ContextPolicy 描述上下文限制；
- MKAOS KnowledgePack 描述知识选择；
- Operation Definition 描述命令、权限、幂等和完成条件；
- Authority 表描述候选、决策、激活和版本状态；
- 文档描述角色、业务边界和未来目标。

Capability Pack 的产品价值，就是把这些对象组织成一个可交付、可选择、可发布、可替换、可解释的业务能力单元。

### 2.2 当前痛点

#### 痛点一：能力定义分散

同一个章节生成能力的配置分散在：

- `src/novel_forge/modules/chapter_authority/contracts.py`；
- `src/novel_forge/modules/chapter_authority/orchestrator.py`；
- `src/novel_forge/modules/chapter_authority/handlers.py`；
- `src/novel_forge/modules/chapter_authority/execution_gateway.py`；
- `src/novel_forge/api/authority_dependencies.py`；
- `src/novel_forge/modules/production_execution/*`；
- 环境变量中的 provider、model、prompt version、skill version 和 hash。

任何人都很难通过一个对象确认“章节生成能力的完整合同”。

#### 痛点二：Skill 不能独立成为生产能力

现有 Skills System 已明确 Skill 是可复用方法，不应替代 Schema、Workflow、工具或 Review Gate。Skill 本身缺少：

- 完整业务角色；
- Workflow；
- Context 和 Source 边界；
- Tool Permission；
- Evaluation；
- Runtime Contract；
- 发布、灰度、迁移和审计策略。

因此不能把 Skill 直接重命名为 Capability Pack。

#### 痛点三：运行时有治理合同，但缺少上游产品标准

Production Execution Plane 已具备：

- CapabilityDefinition；
- PromptBundle；
- SkillBundle；
- ContextPolicy；
- SourcePolicy；
- ValidationPolicy；
- CommitPolicy；
- InputManifest；
- RouteSnapshot；
- ExecutionRequest；
- CommitManifest。

这些合同当前主要由 Python 代码和环境变量拼装。它们已经能够记录“本次执行如何发生”，但还不能回答“这个业务能力为什么这样定义、属于哪个版本、由谁拥有、如何发布和迁移”。

#### 痛点四：跨项目复用和迁移缺少产品边界

世界观设计、人物设计、章节生成、长篇复盘、Book Design Authority 和 Reader Outcome Judge 都具有跨书复用价值。但如果缺少 Capability Pack：

- 复用会退化为复制 Prompt 或 Skill；
- 项目之间难以比较版本；
- 生产问题无法归因到 Pack、Skill、Prompt、Provider 或 Context；
- 多书并行时难以保证不同项目使用正确能力版本；
- 企业 Agent 平台难以复用 Novel OS 已形成的能力治理经验。

---

## 3. 产品目标与非目标

### 3.1 产品目标

Capability Pack 需要覆盖以下完整能力：

1. **能力复用**：同一业务能力可以被多个项目、书籍和生产流程引用；
2. **版本治理**：能力包具有稳定身份、SemVer、状态和生命周期；
3. **角色治理**：明确 Agent、Worker、Reviewer、Judge、Authority 或 Coordinator 的职责边界；
4. **上下文绑定**：规定允许读取的 AssetVersion 类型、优先级、预算、时效和隔离规则；
5. **工具权限**：规定模型、数据库、文件、检索和外部工具的权限与审批要求；
6. **Workflow 编排**：描述标准节点、依赖、重试、审批、补偿和完成条件；
7. **评估标准**：绑定 Quality Gate、Judge、阈值、失败类型和生产晋升条件；
8. **审计追踪**：每次运行可追溯到 Pack、版本、manifest hash、Skill、Prompt、Route 和 Input；
9. **生产验证**：区分静态有效、Fixture 验证、真实 Provider 验证、长篇验证和生产验证；
10. **跨项目迁移**：在满足兼容性和权限要求时迁移到其他书籍、项目或业务域；
11. **未来扩展**：支持多模型、多工具、多租户、多项目和多书并行。

### 3.2 非目标

Capability Pack 第一阶段不负责：

- 新建第二套 Operation / Saga / Attempt 状态机；
- 替代 PostgreSQL Authority；
- 替代 MKAOS KnowledgePack；
- 把所有 Workflow 改造成动态低代码编排；
- 自动生成任意工具权限；
- 自动决定业务 Authority 决策；
- 自动修改 Pack 版本或在线学习生产策略；
- 在没有真实 Provider、长篇和生产证据时宣称生产完成；
- 统一所有历史 Legacy 路径。

---

## 4. 核心定义与边界

### 4.1 Capability Pack 定义

Capability Pack 是以下对象的组合合同：

```text
Pack Identity
+ Role Definition
+ Skill Binding
+ Prompt Binding
+ Workflow Template
+ Context Sources
+ Tool Permissions
+ Knowledge / Rule / Template Assets
+ Evaluation Rules
+ Runtime Contract
+ Governance / Audit
```

### 4.2 与现有概念的关系

| 概念 | 核心职责 | 与 Capability Pack 的关系 |
|---|---|---|
| Skill | 可复用的方法和步骤 | Pack 的组成件，不能单独代表完整业务能力 |
| Prompt | 模型调用指令和模板 | Pack 的模型执行参数之一 |
| Agent | 执行角色和权限主体 | Agent 可以执行一个或多个 Pack；Pack 不等于进程或人格 |
| Workflow | 节点、依赖和完成顺序 | Pack 的执行模板 |
| CapabilityDefinition | PEP 可执行能力及策略引用 | Pack 编译到运行时的底层能力定义 |
| MKAOS KnowledgePack | 针对目标资产冻结的知识选择 | Pack 的知识依赖，不是业务能力包 |
| Rule / Template | 约束和结构资产 | Pack 的资产依赖 |
| Context Compiler | 选择、压缩、验证和记录上下文 | 执行 Pack 的上下文合同 |
| Review / Judge | 评估输出并给出证据 | Pack 的 Evaluation Gate |
| Authority | 对候选、版本和状态作权威决策 | Pack 可扮演 Authority 角色，但不能绕过领域 Authority |
| Command / Saga / Attempt | 生产执行状态和恢复机制 | Pack 的运行载体，不由 Pack 重建 |

### 4.3 Pack 与 MKAOS KnowledgePack 的区别

```text
MKAOS KnowledgePack
= 为某个目标资产选择哪些知识卡、权重和用途

Capability Pack
= 为某个业务能力定义角色、技能、流程、上下文、工具、评估、运行和治理
```

一个 Capability Pack 可以依赖一个或多个 MKAOS KnowledgePack，但二者不能合并。

---

## 5. 目标用户与产品角色

### 5.1 核心用户

| 用户 | 主要诉求 |
|---|---|
| Novel OS 产品架构师 | 定义能力边界、版本和组合方式 |
| Agent 平台架构师 | 将角色、技能、权限、上下文和工具形成标准能力单元 |
| 小说主编 / Book Authority Operator | 选择书籍生产使用的 Pack 版本并查看质量结果 |
| Prompt / Skill 设计者 | 发布可复用 Skill 和 Prompt，但不越过 Workflow 和 Authority 边界 |
| 平台工程师 | 实现 Registry、Loader、Validator、Resolver 和 Runtime Binding |
| 质量工程师 | 定义评估门、校准策略和晋升条件 |
| 安全与审计人员 | 查询 Pack 权限、工具调用、来源、成本和版本变更 |
| 企业 Agent 平台团队 | 在其他业务域复用 Capability Pack 协议 |

### 5.2 运行时角色类型

Pack 角色应至少支持：

- `AGENT`：有目标、有输入输出、可能使用工具；
- `WORKER`：执行确定工作单元；
- `REVIEWER`：识别问题并输出 ReviewIssue；
- `JUDGE`：基于证据和量表作评估，不直接修改业务资产；
- `AUTHORITY`：对候选、决策、激活、替换作领域权威提交；
- `COORDINATOR`：协调多个 Operation / Saga，不拥有领域创作状态。

---

## 6. 产品原则

### 6.1 业务能力优先，不以 Prompt 为中心

Prompt 是 Pack 的一项依赖。产品设计必须先定义业务职责、输入输出、工作流、权限和评估，再绑定 Prompt。

### 6.2 Authority 复用，不创建平行运行时

Pack 运行必须落到现有：

```text
Operation Definition
→ Command Admission
→ Transaction Command / Durable Job / Saga / External Effect
→ Attempt / Lease / Fence where applicable
→ Validation / Commit
→ Authority AssetVersion / Event / Audit / Outbox
```

### 6.3 默认拒绝和显式授权

- Tool 默认 `DENY`；
- Context 类型必须显式允许；
- 生产环境禁止静默 Provider fallback；
- 生产上下文禁止原始参考文本直接进入生成；
- 高风险和关键工具必须审计，必要时审批。

### 6.4 版本冻结与可复现

每次生产运行必须冻结：

- pack_id / pack_version；
- pack manifest hash；
- Skill version / content hash；
- Prompt version / hash；
- Context and Input AssetVersions；
- RouteSnapshot；
- Evaluation policy；
- release SHA。

### 6.5 证据等级不可混淆

Pack 的验证状态必须区分：

```text
STATIC_VALIDATED
FIXTURE_PROVEN
POSTGRES_INTEGRATION_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTI_BOOK_PROVEN
PRODUCTION_VERIFIED
```

Fixture、表结构、接口、UI 或文档都不能自动提升到真实生产验证。

### 6.6 最小闭环优先

第一阶段只完成一个 Pack 的静态标准和校验，不一次性实现 Registry、UI、数据库、动态 Workflow、多 Pack 编排和企业平台。

---

## 7. Capability Pack 产品模型

### 7.1 顶层产品对象

| 模块 | 产品含义 |
|---|---|
| Identity | Pack 的稳定身份、版本、域、所有者和状态 |
| Compatibility | Novel Forge、协议、Schema、Capability、环境和其他 Pack 的兼容要求 |
| Role | 职责、边界、禁止行为和上下游关系 |
| Skill Binding | Skill 输入输出、依赖、调用次数、动态选择和漂移策略 |
| Prompt Binding | Prompt 版本、hash、编译器和 Schema |
| Workflow Template | 节点、输入输出、依赖、重试、超时、审批、补偿和完成条件 |
| Context Sources | 允许资产、禁止资产、优先级、Token 预算、时效和隔离 |
| Tool Permissions | 工具、数据库、文件、模型和检索权限 |
| Assets | MKAOS、Rule、Template 和 Source Policy 依赖 |
| Evaluation | Judge、Gate、指标、阈值和失败策略 |
| Runtime Contract | 输入、输出、错误、状态、事件、审计、回滚和提交协议 |
| Governance | 发布、灰度、迁移、替换、停用、成本和质量追踪 |
| Audit | 本次执行必须记录的证据 |
| Extensions | UI、企业、多租户、实验和供应商扩展 |

### 7.2 Pack 类型

| Pack 类型 | 说明 | 小说生产示例 |
|---|---|---|
| Generator Pack | 生成候选资产 | worldbuilding、character、chapter draft |
| Review Pack | 识别问题并输出修订要求 | chapter review、longform consistency review |
| Judge Pack | 对候选输出量化或规则判断 | Reader Outcome Judge、originality judge |
| Authority Pack | 管理候选、决策、激活和替换 | Book Design Authority Pack |
| Coordinator Pack | 调度多项业务能力 | Book Production Coordinator Pack |
| Integration Pack | 外部平台或工具接入 | publishing adapter、feedback ingestion |
| Composite Pack | 组合多个受治理 Pack | chapter_generation_pack |

---

## 8. 核心业务场景

### 8.1 章节生产

```text
chapter_generation_pack@1.0.0
→ frozen ChapterPlan
→ governed Context
→ Draft
→ Review
→ Revision
→ Re-review
→ Canon Extraction / Proposal / Update
→ five Quality groups
→ Quality Aggregate
→ Publish Gate
→ Export
→ Final Release Gate
```

产品价值：

- 一个版本即可描述章节生产的完整能力；
- 能追溯每个阶段使用的 Skill、Prompt、Provider、Context 和 Gate；
- 能比较不同 Pack 版本的质量、成本和失败率；
- 能按项目或书籍灰度升级。

### 8.2 世界观设计

`worldbuilding_pack` 应定义：

- World Designer 角色；
- 世界规则、资源、势力、地点、冲突结构等输出合同；
- 允许读取的题材、Book Design、MKAOS 知识和 Source eligibility；
- 禁止复制具体原作表达；
- 与 Character / Planning Pack 的依赖；
- 世界规则一致性和可叙事性 Gate。

### 8.3 Book Design Authority

`book_design_authority_pack` 应围绕现有 `book.create`、`book_design.propose`、`book_design.decide`、`book_design.activate`：

- 将 Generator 与 Authority 明确分离；
- 候选生成不自动激活；
- 决策和激活必须有版本与证据；
- 支持 supersession 和回滚；
- 不拥有 Chapter Runtime。

### 8.4 长篇一致性复盘

`longform_consistency_review_pack` 应读取：

- Book / Volume / Arc / ChapterGroup / Chapter Plan；
- Canon Snapshot；
- Story State；
- Character State；
- Foreshadow / Promise / Reward Ledger；
- Quality Trend；
- Reader Outcome。

输出：

- deviation report；
- continuity issue；
- arc closure assessment；
- plan change proposal；
- operator decision request。

它不能直接修改已激活计划或 Canon，必须提交候选和影响分析。

### 8.5 Reader Outcome Judge

`reader_outcome_judge_pack` 应区分：

- 模型预测；
- 人类偏好；
- 真实读者行为；
- 校准状态；
- Shadow / Advisory / Bounded Production 模式。

在没有有效 calibration profile 时，只允许 Shadow 或 Advisory，不得成为阻塞生产 Gate。

---

## 9. Pack 生命周期

### 9.1 生命周期状态

```text
DRAFT
→ CANDIDATE
→ ACTIVE
→ DEPRECATED
→ RETIRED

任何阶段可进入 DISABLED
```

含义：

| 状态 | 含义 |
|---|---|
| DRAFT | 可编辑，不可进入生产 |
| CANDIDATE | 已静态校验，可进入 Fixture / Validation |
| ACTIVE | 已批准，可按 release channel 使用 |
| DEPRECATED | 允许已有绑定继续使用，不允许新增默认绑定 |
| RETIRED | 禁止新运行，只保留历史审计 |
| DISABLED | 因安全、质量或兼容问题立即停用 |

### 9.2 发布通道

```text
DEV
→ VALIDATION
→ CANARY
→ PRODUCTION
```

每个通道必须定义证据要求。示例：

| 通道 | 最低要求 |
|---|---|
| DEV | Schema 和静态校验通过 |
| VALIDATION | Fixture / PostgreSQL integration 通过 |
| CANARY | 真实 Provider、成本、错误和恢复证据通过 |
| PRODUCTION | 长篇、操作、SLO、安全、回滚和质量验证通过 |

### 9.3 版本策略

采用 SemVer：

- Patch：不改变输入输出和权限，仅修正文档、描述或兼容性问题；
- Minor：新增可选资产、非阻塞 Gate 或兼容节点；
- Major：改变必填输入、Workflow、输出 Schema、权限、阻塞 Gate 或 Commit Policy。

Major 版本必须提供迁移和回滚策略。

---

## 10. 产品功能需求

### 10.1 Pack Registry

产品能力：

- 查看 Pack 列表、所有者、域、类型、状态和版本；
- 查询默认版本和项目/书籍绑定；
- 查看 manifest hash、兼容性和验证级别；
- 查看替代 Pack 和 retirement deadline。

### 10.2 Pack Validator

需要输出：

```json
{
  "ok": true,
  "pack_id": "chapter_generation_pack",
  "version": "1.0.0",
  "manifest_hash": "sha256:...",
  "errors": [],
  "warnings": [],
  "resolved_capabilities": []
}
```

校验范围：

- Identity 和 SemVer；
- Capability Registry 引用；
- Skill / Prompt hash；
- Workflow DAG；
- Tool default deny；
- Context / Source isolation；
- Evaluation Judge；
- Runtime Authority 绑定；
- production / fixture 兼容性。

### 10.3 Pack Version Resolver

优先级建议：

```text
explicit workflow version
> book binding
> project binding
> environment default
> global active default
```

Resolver 结果必须冻结到本次 Operation，运行中不得漂移。

### 10.4 Pack Audit View

应能回答：

1. 这次运行使用哪个 Pack 版本；
2. manifest hash 是什么；
3. 使用哪些 Skill、Prompt 和 Provider；
4. 读取哪些 AssetVersion；
5. 调用了哪些工具；
6. 哪些 Gate 通过或失败；
7. 消耗多少 Token 和成本；
8. 是否重试、取消、恢复或回滚；
9. 哪个 Authority 提交最终资产。

### 10.5 Pack Compare

未来产品能力：

- 比较两个 Pack 版本的 Workflow、权限、Context、Skill、Prompt 和 Evaluation 差异；
- 标记 breaking change；
- 生成 rollout 和 migration 风险报告。

---

## 11. 权限、安全与合规要求

### 11.1 默认拒绝

所有 Pack 必须：

- 工具默认 `DENY`；
- 显式声明可读取和可写入的资源；
- 显式声明外部模型和检索权限；
- 禁止 inline secret；
- 高风险工具要求完整审计。

### 11.2 小说版权和来源隔离

生成类 Pack 必须默认：

- 禁止原始参考文本直接进入生成上下文；
- 只允许 `PRODUCTION_ELIGIBLE` 或 `NOT_SOURCE_DERIVED` 资产；
- 要求 lineage；
- 使用抽象化 Knowledge / Rule / Template；
- 原创性和 source leakage Gate 不得被 Pack 关闭。

### 11.3 跨项目隔离

- Pack 可以跨项目复用定义；
- 运行时 Input AssetVersion 必须属于当前 Project / Book scope；
- Pack 不得将一个项目的 Context 或 Reader Data 带入另一个项目；
- 多租户扩展必须引入 tenant scope，但 P0 不实现。

---

## 12. 产品指标

### 12.1 采用指标

- Active Pack 数量；
- 使用 Pack 的生产 Operation 占比；
- 未绑定 Pack 的生产路径数量；
- Pack 版本复用项目数；
- Pack 升级和回滚成功率。

### 12.2 质量指标

- Pack Validator 失败率；
- 每个 Pack 的 Gate 通过率；
- Review → Revision → Re-review 改善率；
- Pack 版本间质量差异；
- Reader Outcome 校准误差；
- 长篇一致性问题率。

### 12.3 运行指标

- Operation 成功率；
- Attempt 重试率；
- ExternalEffect UNKNOWN 率；
- 平均 Token / 成本；
- 取消和恢复成功率；
- Pack 版本解析失败率；
- 运行证据完整率。

### 12.4 治理指标

- 未审计高风险工具调用数，目标为 0；
- 非法 raw source context 次数，目标为 0；
- cross-project context rejection 数；
- Deprecated Pack 新绑定数，目标为 0；
- 无迁移计划的 breaking release 数，目标为 0。

---

## 13. 分阶段产品路线图

### P0：协议与静态校验

目标：证明 Capability Pack 可以成为稳定产品对象。

范围：

- `novelos.capability_pack.v1`；
- 强类型 Schema；
- JSON Loader；
- Validator；
- `chapter_generation_pack` 示例；
- Unit Tests。

不做：

- 数据库；
- CLI / API；
- Runtime Binding；
- UI；
- 多 Pack 编排。

### P1：Registry 与版本治理

目标：Pack Manifest 成为 Authority AssetVersion，并能注册、查询和激活。

范围：

- Pack / PackVersion 最小表；
- register / validate / activate Operation；
- active version 查询；
- manifest hash 冲突和幂等。

### P2：章节生产绑定

目标：Chapter Authority 每次运行冻结 Pack identity。

范围：

- Pack Version Resolver；
- `pack_id / pack_version / manifest_hash` 进入 Operation、InputManifest、RouteSnapshot 或专用 binding evidence；
- 不改变 18 节点业务 DAG。

### P3：评估、审计和回滚

目标：形成 Pack 级质量、成本、审计和替换视图。

范围：

- Pack evaluation aggregation；
- Pack audit query；
- activation / supersession；
- canary / rollback。

### P4：多 Pack 和企业扩展

目标：支持 Book Design、Chapter、Longform、Reader Outcome 等多 Pack 组合。

范围：

- Pack dependencies；
- Composite Pack；
- 多项目、多书和多模型；
- tenant extension；
- 企业 Agent 平台复用。

---

## 14. 风险与控制

| 风险 | 说明 | 控制策略 |
|---|---|---|
| 协议过度设计 | 在真实使用前设计过多字段 | P0 只实现核心字段和一个真实示例 |
| 与 PEP 重复 | Pack 又实现一套执行合同 | Pack 只做声明和编译，PEP 继续执行 |
| 与 Command Kernel 竞争 | 新建 Pack Run 状态机 | Pack Run 只做聚合索引，Operation 是状态权威 |
| 与 MKAOS 混淆 | 把知识包当业务包 | 文档、Schema 和命名明确分离 |
| 动态 Workflow 失控 | 任意 Pack 修改生产 DAG | 早期只允许绑定已注册 Operation Definition |
| 权限扩大 | Pack 通过工具配置绕过安全 | default deny、静态校验、Authority permission 和 audit |
| 文档先于实现 | 协议被标记为完成 | 每阶段使用明确验证等级和 current-SHA 证据 |
| 版本碎片化 | 每本书自定义大量 Pack | 默认 Pack + project/book override，限制非必要 fork |
| 质量不可归因 | Skill、Prompt、Context、Provider 混在一起 | 所有依赖 hash 和版本冻结，建立 Pack audit view |

---

## 15. P0 产品验收标准

P0 完成必须同时满足：

1. 有 `novelos.capability_pack.v1` 强类型对象；
2. 有 JSON Loader；
3. 有结构化 Validator Report；
4. `chapter_generation_pack` 能通过校验；
5. 未知 Capability、非法 hash、重复 Skill、Workflow 环、非 default deny、高风险工具无审计、生产 raw source context、缺少 Authority binding 均会失败；
6. 不修改现有 Chapter Authority 行为；
7. 不新增数据库迁移；
8. 不引入第三方依赖；
9. Unit Tests 和 compileall 通过；
10. 完成报告明确列出未做事项。

---

## 16. 产品结论

Novel Forge 有必要引入 Capability Pack，原因不是缺少更多 Prompt 或 Skill，而是系统已经进入需要进行**业务能力产品化和治理标准化**的阶段。

当前工程已经具备足够底座：

```text
Capability Registry
+ Prompt / Skill Bundle
+ Context / Source / Validation / Commit Policy
+ Production Execution Plane
+ Command Kernel
+ AssetVersion
+ Chapter / Book / MKAOS Authority
```

Capability Pack 应当成为这些底座的上游业务标准，而不是平行平台。

首个最小闭环应为：

```text
chapter_generation_pack
→ static protocol
→ loader
→ validator
→ unit tests
```

只有在该闭环稳定后，才进入 Registry、Runtime Binding、Audit、Canary 和多 Pack 编排。