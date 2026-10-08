---
name: anti-copy-abstraction
description: Use when converting concrete reference-work analysis into reusable abstract mechanisms, writing principles, and review checks that cannot be used to reconstruct or imitate a protected work.
---

# Anti Copy Abstraction

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 热门小说拆解后，进入题材、世界观、人物、大纲或正文前。
- 拆解报告包含具体桥段、人物关系、独特反转或世界设定风险。
- 审稿时怀疑产物过度接近已有作品。

## 输入要求

- 拆解报告、来源标识、可复用点和禁止复用点。
- 任何具体剧情、台词、人物组合和独特设定都必须标记为高风险。
- 不接受无来源的“爆款套路”直接进入生成链路。
- 正式输入必须是已提交的 Observation AssetVersion，并保留其 EvidenceSpan lineage；不得将 raw SourceChunk 内容重新复制进抽象 Prompt。

## Observation 到 Candidate 合同

- `Observation` 只说明来源中观察到什么，`Knowledge Candidate` 才说明经过抽象后可复用什么；两者不得共用一个资产或状态。
- 一个 Observation 可以在不同 abstraction policy / schema / prompt / model 版本下产生多个 Candidate；旧 Candidate 必须保留并可被 rejected、superseded 或 deprecated。
- Candidate 只允许保存跨作品成立的因果机制、约束、冲突生成器和审稿检查，不得保存可复原单一作品的角色组合、事件序列、专有名词或表达。
- Candidate 必须引用 Observation AssetVersion；正式 API 不接受只有 SourceChunk 的 Candidate。

## 操作流程

1. 将输入分成表达、剧情、设定、结构、机制和读者效果。
2. 删除或标记表达、具体剧情、独特设定和可识别人物组合。
3. 保留结构、机制和读者效果。
4. 将具体桥段改写为类型无关的因果机制。
5. 为每条原则补适用范围、禁用范围和审稿检查项。
6. 机制必须说明叙事问题、预期效果、抽象方法、适用与禁用条件、代价、变化方式、证据覆盖和审稿观察点；映射现行 Candidate 的机制/适用性字段，不新增平行资产。
7. 输出 schema-backed Knowledge Candidate，进入 Validation、Source Isolation、Originality Gate 与人工 Approval；未批准前不得成为 KnowledgeCard。

## 输出格式

```markdown
# 反抄袭抽象报告

## 输入来源
## 高风险具体内容
## 删除或禁用内容
## 抽象机制
## 可复用创作原则
## 适用题材
## 审稿检查项
## 原创风险等级
## 是否允许进入下游
```

## 证据及应用边界

- 因果机制是可测试解释，预期读者效果是应用假设；热度不能证明文学质量或效果，不虚构读者反馈。
- 共性和差异可关联；单书证据不能伪装成跨作品验证，相似机制不合并其独立证据。
- Formation / Planning 将机制转译为当前书的原创场景；Draft 只接收作者意图、计划和必要抽象指导。
- 具体 Card 版本、Book 范围、阶段、KEEP/ADAPT/AVOID/DEFER 与理由由现行 CreativeBrief 绑定保存。新参考不改写历史请求。

## 质量标准

- 输出不能让创作者复原原作品的具体桥段。
- 每条抽象原则必须脱离单一作品语境也能成立。
- 必须明确哪些内容不能进入 prompt、正文、素材库和生成输出。
- 必须能被 `quality-review` 用作原创风险检查依据。
- 必须声明 abstraction policy version、input Observation versions、confidence、copyright boundary 和所有 rejected mechanisms。

## 禁止事项

- 禁止保留可识别人物组合。
- 禁止保留独特反转和具体案件结构。
- 禁止用“致敬”“参考风格”规避版权边界。
- 禁止将拆解结果直接交给 `prose-generation`。

## 与其他模块的关系

- 上游：`hot-novel-deconstruction`、`hot-novel-business-deconstruction` 与冻结的 Observation AssetVersion。
- 下游：现行 MKAOS Candidate / KnowledgeCard、单书检索和 `quality-review`。
- Agent：Knowledge Agent、Review Agent、Quality Agent。
