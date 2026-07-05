---
name: narrative-beat-design
description: Use when designing or reviewing long-outline, chapter-outline, scene sequence, information progression, reader grounding, beat order, hook setup, payoff path, or any narrative plan that must introduce concepts before later beats rely on them.
---

# Narrative Beat Design

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed outline、chapter plan、scene plan、foreshadowing plan 或 review issue，而不是只停留在对话文本。
- 每个 beat 必须保留输入依据、目标资产、`project_id`、可追踪引用、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 beat、prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 设计全书、卷、章节或场景的 beat 顺序。
- 审查 reader grounding：读者是否已经知道后续 beat 依赖的概念、规则、人物动机、承诺或伏笔。
- 修复大纲/细纲中的信息跳跃、解释过载、伏笔未铺、 payoff 没有前置基础的问题。
- 将商业钩子、冲突、反转、代价和信息增量组织成可执行路径。

## 输入要求

- TopicSeed、WorldBible、CharacterCard、Outline、ChapterPlan、ContextBundle 或目标章节位置。
- 目标读者默认已知的 prerequisite concepts。
- 本段必须 introduced 的概念、规则、人物状态、悬念、伏笔、承诺和 payoff。
- 禁用项、原创风险边界、platform rhythm 和 source isolation policy。

## 操作流程

1. 定义 reader prerequisites：读者进入本段前已经知道什么。
2. 建立 grounded set：已知概念、已立规则、已展示关系、已承诺 payoff。
3. 拆出候选 beats：每个 beat 只做一个动作，如设置压力、展示规则、制造选择、兑现奖励、翻转认知。
4. 为每个 beat 标注 `requires` 和 `grounds`：它依赖什么、它让读者新理解什么。
5. 删除或前移不可达 beat：任何依赖未 grounded 概念的 beat 必须先补 grounding beat。
6. 排列 beat path：优先行动和冲突，解释只在读者需要时出现。
7. 将 beat path 映射回 Outline / ChapterPlan / ScenePlan，并生成 missing groundwork 和 review issues。

## 输出格式

```markdown
# Narrative Beat Design Report

## Scope
- target:
- reader prerequisites:
- grounded at start:

## Beat Path
- beat:
  - function:
  - requires:
  - grounds:
  - hook/payoff:
  - risk:

## Grounding Gaps
- missing concept:
- required before:
- proposed grounding beat:

## Gate
- result:
- review issues:
- downstream asset:
```

## 质量标准

- 每个 beat 必须只有一个主要叙事功能。
- 每个后续 beat 依赖的概念必须已是 prerequisite 或被早先 beat grounding。
- beat path 必须产生行动、冲突、信息增量、情绪变化或 reader payoff。
- 章节级 beat 必须能约束 `prose-generation`，不是抽象口号。

## 禁止事项

- 禁止为了漂亮结构跳过因果和 reader grounding。
- 禁止把解释性百科 beat 当作剧情推进。
- 禁止用参考作品 beat 顺序作为新项目骨架。
- 禁止输出正文草稿或 final chapter。

## 与其他模块的关系

- 上游：Topic、WorldBible、CharacterCard、MKAOS Pack、Platform Strategy、Canon Graph。
- 下游：`long-outline`、`chapter-outline`、`quality-review`、`canon-continuity-graph`、DraftChapter。
- Agent：Outline Agent、Chapter Plan Agent、Review Agent、Quality Agent。
