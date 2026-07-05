---
name: hot-novel-deconstruction
description: Use when analyzing popular novels or genre samples to extract abstract structure, pacing, payoff mechanics, character mechanisms, conflict patterns, emotion curves, chapter hooks, and commercial logic without copying protected expression or plot combinations.
---

# Hot Novel Deconstruction

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 拆解热门小说、爆款章节、同赛道样本或类型文片段。
- 为 `decompose`、`extract-knowledge`、`build-materials` 或题材策划提供抽象输入。
- 需要判断一个样本为什么有追读、爽点和商业吸引力。

## 输入要求

- 来源、范围、类型、目标读者和拆解目的。
- 版权边界说明：输入只用于结构分析，不进入正文生成。
- 若样本来自单一作品，必须标记为高原创风险输入。

## 操作流程

1. 记录来源、样本范围、类型、目标读者和拆解问题。
2. 拆出结构：开局问题、阶段目标、冲突升级、阶段奖励和结尾压力。
3. 拆出节奏：信息增量、压迫、缓释、反转、奖励兑现和章节钩子间隔。
4. 拆出人物机制：欲望、恐惧、能力、缺陷、关系压力和行动代价。
5. 拆出冲突机制：目标冲突、资源冲突、身份冲突、价值冲突和制度压力。
6. 拆出商业逻辑：读者期待、爽点承诺、情绪释放、追读理由和禁用风险。
7. 输出可复用抽象原则和禁止复用内容。
8. 交给 `anti-copy-abstraction` 去具体化和降版权风险。

## 输出格式

```markdown
# 热门小说拆解报告

## 来源与范围
## 类型与目标读者
## 结构拆解
## 节奏拆解
## 爽点机制
## 人设机制
## 冲突机制
## 情绪曲线
## 章节钩子
## 商业化逻辑
## 可复用抽象原则
## 禁止复用内容
## 原创风险等级
```

## 质量标准

- 输出重点是结构、机制和读者效果，不是剧情复述。
- 每个可复用点必须说明适用边界。
- 每个高风险点必须进入禁止复用内容。
- 拆解结果必须能转成 `KnowledgeCard` 或 `MaterialCard`。

## 禁止事项

- 禁止复制原文表达、台词、人物身份、独特设定和具体桥段。
- 禁止把单一热门小说直接转成新书剧情骨架。
- 禁止输出换名仿写建议。
- 禁止把原文片段保存为可生成素材。

## 与其他模块的关系

- 上游：`data/raw/`、`data/cleaned/`、`docs/00-product/copyright-and-compliance.md`。
- 下游：`anti-copy-abstraction`、`data/decompositions/`、`data/knowledge/`、`data/materials/`。
- Agent：Knowledge Agent、Material Agent、Chief Editor Agent。
