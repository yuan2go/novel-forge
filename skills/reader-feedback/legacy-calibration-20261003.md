---
name: reader-feedback
description: Use when importing, classifying, interpreting, or applying reader feedback so comments improve future chapters without breaking project boundaries, character arcs, world rules, or the main conflict.
---

# Reader Feedback

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 导入评论、评分、读者反馈或测试读者意见后。
- 需要判断反馈应观察、采纳、延后还是拒绝。
- 需要把反馈反哺到后续章节、RevisionPlan 或 FeedbackInsight。

## 输入要求

- ReaderFeedback 或评论来源、时间、章节范围和样本数量。
- 当前 TopicSeed、Outline、ChapterPlan、DraftChapter 或 ReviewReport。
- 项目边界、世界规则、人物成长线和不可修改项。

## 操作流程

1. 按来源、章节、评分、情绪和主题归类反馈。
2. 区分 S/A/B/C 级反馈：主线风险、追读问题、局部体验、噪声。
3. 提取重复出现的读者信号，不被单条评论牵引。
4. 判断反馈影响范围：下一章、未来 3-10 章、卷纲、长期规则或不采纳。
5. 检查是否突破角色弧、世界规则、原创边界或主线承诺。
6. 输出 FeedbackInsight 和可执行后续约束。
7. 将重大调整交给 `quality-review` 或 Chief Editor Agent 决策。

## 输出格式

```markdown
# Reader Feedback Insight

## 来源与范围
## 样本概况
## 高频信号
## 反馈分级
## 可采纳项
## 暂缓观察项
## 不采纳项
## 影响范围
## 后续章节约束
## 是否需要主编决策
```

## 质量标准

- 必须区分高频信号和单条噪声。
- 必须说明采纳反馈的影响范围。
- 必须保护项目核心承诺、人物成长线和世界规则。
- 必须输出可执行调整，不只复述评论。

## 禁止事项

- 禁止让评论直接修改项目核心规则。
- 禁止让高人气配角抢走主角成长线。
- 禁止为短期爽感破坏长期代价机制。
- 禁止把读者原话直接当正文素材。

## 与其他模块的关系

- 上游：`import-feedback`、`analyze-feedback`、ReaderFeedback。
- 下游：FeedbackInsight、RevisionPlan、`quality-review`。
- Agent：Feedback Agent、Chief Editor Agent、Quality Agent。
