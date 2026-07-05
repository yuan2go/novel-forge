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

## 操作流程

1. 将输入分成表达、剧情、设定、结构、机制和读者效果。
2. 删除或标记表达、具体剧情、独特设定和可识别人物组合。
3. 保留结构、机制和读者效果。
4. 将具体桥段改写为类型无关的因果机制。
5. 为每条原则补适用范围、禁用范围和审稿检查项。
6. 输出可进入 `KnowledgeCard`、`MaterialCard` 或审稿规则的抽象原则。

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

## 质量标准

- 输出不能让创作者复原原作品的具体桥段。
- 每条抽象原则必须脱离单一作品语境也能成立。
- 必须明确哪些内容不能进入 prompt、正文、素材库和生成输出。
- 必须能被 `quality-review` 用作原创风险检查依据。

## 禁止事项

- 禁止保留可识别人物组合。
- 禁止保留独特反转和具体案件结构。
- 禁止用“致敬”“参考风格”规避版权边界。
- 禁止将拆解结果直接交给 `prose-generation`。

## 与其他模块的关系

- 上游：`hot-novel-deconstruction`、`data/decompositions/`。
- 下游：`data/knowledge/`、`data/materials/`、`quality-review`。
- Agent：Knowledge Agent、Review Agent、Quality Agent。
