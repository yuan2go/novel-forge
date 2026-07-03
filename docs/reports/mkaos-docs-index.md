# MKAOS 原始设计文档索引

生成时间：2026-07-03

## 1. 检索范围

本次审计在 `docs/` 下按以下关键词完整搜索：`MKAOS`、`多学科知识资产`、`知识资产操作系统`、`Knowledge Asset`、`Knowledge Card`、`Knowledge Pack`、`Rule Card`、`Template Card`、`Source Document`、`Usage Binding`、`Knowledge Usage`、`Feedback`、`Canon Conflict`、`Context Builder`、`RAG`、`Flow Adapter`、`Review`、`Agent`、`长篇稳定性`、`Novel OS`。

直接命中的 MKAOS 主体文档集中在仓库根层 `docs/` 下；`docs/design/`、`docs/prompts/` 和 `docs/new/` 中还有 Post-MKAOS 或 Novel OS 工业化补充文档。

## 2. 文档索引

| 序号 | 路径 | 标题 | 类型判断 | 核心内容摘要 | 关系 |
| -- | -- | -- | -- | -- | -- |
| 1 | `docs/multidisciplinary-knowledge-asset-os.md` | 多学科知识资产操作系统设计文档 | 主设计文档 | 定义 MKAOS 是 Novel Forge / Novel OS 的知识中枢、规则中枢、审稿中枢和反馈学习中枢；明确非目标、Canon 优先级、Source/Knowledge/Asset/Runtime/Evolution 五层架构、Knowledge Router、Knowledge Pack Builder、Flow Adapter、Canon Checker、Usage Tracker、Feedback Learner、UI 和验收标准。 | 全量产品与架构设计基线。 |
| 2 | `docs/mkaos-database-schema.md` | MKAOS 数据库 Schema 设计文档 | 主设计补充：数据模型 | 定义 P0/P1 数据模型：source documents/chunks、knowledge cards/relations、material/conflict/world/character/rule/template cards、usage bindings、knowledge packs/items、usage/feedback/quality scores、regression cases/runs、Qdrant collections、数据一致性规则和 P0 最小表。 | 对主设计的数据结构展开；用于判断字段、枚举、索引、P0/P1 边界。 |
| 3 | `docs/mkaos-agent-api-protocol.md` | MKAOS Agent API 协议设计文档 | 主设计补充：Agent/API 协议 | 定义 Agent 与 MKAOS 的五类接口：Query、Pack、Convert、Validate、Feedback；要求 Agent 消费 Knowledge Pack、不读原始资料、记录 usage event、反馈可回写权重；列出 Query/Pack/Convert/Validate/Feedback API、标准响应、错误码和 Agent 调用约定。 | 对主设计的运行协议展开；用于判断 API 完整性、标准响应、权限与错误码。 |
| 4 | `docs/mkaos-p0-implementation-plan.md` | MKAOS P0 实施任务清单与测试方案 | P0 实施设计 / 验收计划 | 将全量 MKAOS 收缩为 P0 最小闭环：来源导入、知识卡、用途绑定、Knowledge Pack、outline/chapter_outline/prose/review 四个 Flow Adapter、Usage、基础 Feedback、最小 UI、回归测试；明确 P1/P2 暂不做项和土地兼并验收样例。 | 这是当前实现应优先满足的 P0 范围文件，不等同于全量设计。 |
| 5 | `docs/design/novel-os-v6-industrialization-design.md` | Novel OS v6.1 工业化落地设计文档：MKAOS P0 完成后的系统补全方案 | 后续工业化设计 | 明确“不要重做 MKAOS”，把 MKAOS P0 作为已完成底座；列出已完成文件、表、API、Flow Adapter、UI、测试结果；定义 Post-MKAOS 后续：OS Envelope、MKAOS 生产级加固、Context Builder 统一上下文包、Eval/Review Issue、Loop Engineering、长篇复盘 Agent、Agent Center、UI、发布反馈闭环。 | 不是原始 MKAOS 设计；是后续路线和当前实现声明的重要对照。 |
| 6 | `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` | Claude Code 长任务提示工程：Novel OS v6.1 Post-MKAOS 工业化补全 | 后续执行提示 | 以任务提示形式复述 MKAOS P0 已完成范围，要求后续不重复实现，并把 OS Envelope、Context Builder、Eval、Loop、Longform Recap、Agent Center、UI、发布反馈作为后续长任务。 | 不是原始设计；用于识别后续阶段应修内容及是否需要调整提示词。 |
| 7 | `docs/deep-research-report.md` | 深度研究报告 | 上游产品背景 | 描述 Novel Forge 从工具升级为本地小说工厂 OS 的整体方向，包括资产系统、RAG、上下文构建器、审稿、反馈、Agent 工业化等。 | MKAOS 的产品背景材料，不是 MKAOS 专门设计。 |
| 8 | `docs/new/novel-forge-v6-complete-design-with-literary-analysis.md` | Novel Forge v6 complete design with literary analysis | 上游/平行大型设计 | 包含长篇稳定性、RAG 检索策略扩展、分析资产、原创边界、反馈和工业化路线；不以 MKAOS 命名，但覆盖知识/素材/RAG/审稿上下游。 | 可作为补充背景；不应替代 MKAOS 主设计。 |
| 9 | `docs/new/novel-forge-v6-gap-design-for-codex.md` | Novel Forge v6 gap design for Codex | 上游/平行差距设计 | 识别 v6 缺口，包括长篇稳定性、审核中心、反馈中心、RAG/Context Builder 等。 | 补充说明 MKAOS 之外的 Novel OS 缺口。 |
| 10 | `docs/architecture/novel-operating-system-new-capabilities.md` | Novel Operating System New Capabilities | 后续架构补充 | 详细描述 Context Builder、memory、pgvector/hybrid retrieval、KG preflight 等 Novel OS 能力。 | 用于判断 MKAOS 与后续 Context Builder / RAG / KG 的关系。 |

其他命中文档如 `docs/00-product/*`、`docs/01-architecture/*`、`docs/02-workflows/main-pipeline.md`、`docs/03-schemas/schema-index.md`、`docs/04-modules/module-index.md`、`docs/05-testing/testing-strategy.md`、`docs/08-roadmap/*`、`docs/reports/*` 主要是 Novel OS 通用架构、路线或历史报告，未发现独立的原始 MKAOS 设计要求。

## 3. 主设计文档判断

主设计文档为：

1. `docs/multidisciplinary-knowledge-asset-os.md`：产品定位、原则、总体架构、运行模块、UI、验收。
2. `docs/mkaos-database-schema.md`：数据模型、枚举、P0/P1 表边界、数据一致性。
3. `docs/mkaos-agent-api-protocol.md`：Agent/API 协议、接口集合、错误码、调用约定。

`docs/mkaos-p0-implementation-plan.md` 是主设计的 P0 实施切片。当前工程实现应主要按该 P0 切片验收，同时不能破坏主设计中明确的版权边界、source isolation、Canon 优先级和 Agent 统一消费方向。

## 4. 文档关系

```text
docs/multidisciplinary-knowledge-asset-os.md
  ├─ docs/mkaos-database-schema.md
  │    └─ 将全量对象拆为 P0 必做表与 P1 后续表
  ├─ docs/mkaos-agent-api-protocol.md
  │    └─ 将运行层拆为 Query / Pack / Convert / Validate / Feedback
  └─ docs/mkaos-p0-implementation-plan.md
       └─ 只要求最小闭环和四个核心 flow

Post-MKAOS:
docs/design/novel-os-v6-industrialization-design.md
docs/prompts/claude-code-novel-os-v6-long-task-prompts.md
  └─ 假设 MKAOS P0 已完成，要求后续工业化加固，不重做 MKAOS
```

## 5. 版本差异

| 对比项 | 全量主设计 | P0 实施计划 | Post-MKAOS 工业化文档 | 判断 |
| -- | -- | -- | -- | -- |
| Flow 覆盖 | 题材、世界观、人物、大纲、细纲、正文、审稿、反馈等多流程复用 | 仅 `outline` / `chapter_outline` / `prose` / `review` | 要补 `recap` / `revision` / `publish` / `feedback` adapter | P0 收缩明确，不冲突。 |
| 数据对象 | 包含 knowledge graph、material/conflict/world/character assets、feedback events、regression cases | P0 只做 10 张最小表 | 后续不重做，生产级加固 | P1/P2 对象未实现不应判为 P0 错误。 |
| API | Query / Pack / Convert / Validate / Feedback 五类 | P0 重点 Pack / Validate / Feedback，兼顾基础 CRUD | 后续要求接 Context Builder、ReviewIssue、OS Envelope | Query/Convert 属全量设计缺口，P0 可暂缺但需登记。 |
| Canon | Canon Checker 可阻断冲突，外部知识不可覆盖项目 Canon | P0 要 critical 冲突阻断 | 明确当前 Canon 是 stub，需要接真实 Canon/Character/Arc/Foreshadowing | 当前实现若仍为兼容 stub，是 P1 高风险，不是 P0 表结构缺失。 |
| Context Builder | 主设计要求统一 Knowledge Pack，不直接让 Agent 自由检索 | P0 允许四个服务接入 | 后续明确所有 Agent 必须通过统一 Context Bundle，MKAOS Pack 是正式组成部分 | 这是 Post-MKAOS 架构缺口。 |
| RAG | MKAOS 不是普通 RAG，source chunk 不进正文 Agent | P0 要 Prose Source Isolation 100% | 后续要求运行资产、usage、agent runtime 不污染 generation RAG | P0 和后续一致，后续需要专门回归。 |
| Feedback | Feedback Learner 持续权重演化 | P0 只做简单规则和基础回写 | 后续接 reader feedback、Loop、ReviewIssue | 当前基础反馈闭环可算 P0；深度学习闭环属后续。 |

## 6. 版本冲突与过时内容

未发现三份原始主设计之间存在直接冲突；主要差异是“全量愿景”与“P0 切片”的范围差异。

需要注意的过时或需决策内容：

1. `docs/mkaos-database-schema.md` 使用较强 Postgres/UUID/列级 schema 假设；当前仓库是 local-first JSON asset + 可选 Postgres 同步，因此列级完整性应转化为 asset content/schema validation 与 Postgres projection 两层要求。
2. `docs/mkaos-agent-api-protocol.md` 要求通用响应包含 `success/request_id/trace_id`，当前 FastAPI product routers 多数直接返回业务 payload。是否补统一 envelope 属 OS Envelope 阶段决策。
3. `docs/design/novel-os-v6-industrialization-design.md` 声称 MKAOS P0 已完成，但同时列出 Canon stub、warning fallback、Context Builder 统一入口、RAG isolation regression、OS Envelope 等后续风险。本审计不能把该文档的“已完成声明”当作代码事实，必须以代码和测试核验。
4. `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` 是执行提示，不是设计事实；其中关于“已修复/已完成”的句子需要后续报告以实现证据复核。
