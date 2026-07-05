---
name: quality-review
description: Use when reviewing topics, worlds, characters, outlines, chapter plans, drafts, revisions, or feedback decisions for logic gaps, consistency, pacing, payoff density, hooks, foreshadowing, commercial weakness, and originality risk.
---

# Quality Review

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 审查题材、世界观、人物、大纲、细纲、正文或反馈采纳方案。
- 正文草稿进入修订或 final 前。
- 判断是否通过、小修、重修、退回细纲或暂停。

## 输入要求

- 审稿对象文件路径、schema 类型和版本。
- 上游依据：TopicSeed、WorldBible、CharacterCard、Outline、ChapterPlan 或 DraftChapter。
- 原创风险边界、读者吸引力目标和当前验收标准。

## 操作流程

1. 标记审稿对象、版本、输入依据和输出位置。
2. 先查 P0：原创风险、设定崩坏、严重逻辑断裂。
3. 再查 P1：读者吸引力、冲突、爽点、结尾追读。
4. 检查人物动机链、因果链、世界规则、伏笔设置与回收。
5. 检查节奏、叙述密度、AI 腔、对白差异和商业化弱点。
6. 给出评分、优先级、是否退回和可执行修改建议。
7. 明确哪些内容不建议改，避免破坏已有优势。

## 输出格式

```markdown
# Quality Review

## 审稿对象
## 版本
## 总分
## 结论
通过 / 小修 / 重修 / 退回细纲 / 暂停
## P0 问题
## P1 问题
## P2 问题
## P3 问题
## P4 问题
## 可执行修改建议
## 不建议修改内容
## 是否需要主编决策
```

## 质量标准

- 审稿必须区分问题优先级。
- 修改建议必须能直接转成任务或 RevisionPlan。
- 不能只给泛泛评价，必须指出具体问题类型。
- 商业追读和原创边界优先于炫技式设定补完。

## 禁止事项

- 禁止直接覆盖正文终稿。
- 禁止降低原创风险标准。
- 禁止用多学科合理性压制章节爽点。
- 禁止建议突破世界规则或核心人物逻辑。

## 与其他模块的关系

- 上游：全部生成资产、`anti-copy-abstraction`、evaluation rubric。
- 下游：ReviewReport、RevisionPlan、FeedbackInsight。
- Agent：Review Agent、Quality Agent、Chief Editor Agent。
