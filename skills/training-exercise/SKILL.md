---
name: training-exercise
description: Use when designing or reviewing writing, reading-comprehension, translation, or correction-rubric exercises so training tasks produce clear goals, structure, model answers, evaluation criteria, and reusable learning points.
---

# Training Exercise

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 设计作文训练、阅读理解训练、翻译练习或批改标准。
- 将小说工厂中的结构、节奏、人物、逻辑和表达能力转化为训练题。
- 审查训练题是否有明确目标、答案标准和能力点。

## 输入要求

- 训练目标、对象水平、题型、篇幅或时间限制。
- 可用知识点、示例材料或技能目标。
- 禁止内容和版权边界。

## 操作流程

1. 明确训练目标：立意、结构、论证、阅读理解、翻译或修辞表达。
2. 拆分能力点：题目理解、信息提取、逻辑组织、语言表达、审稿修订。
3. 设计题干和输入材料，避免使用未授权长文本。
4. 输出作答要求、评分维度、常见错误和优秀答案特征。
5. 如需示例答案，只给短样例或结构说明，不复制版权材料。
6. 设计批改 rubric 和下一步练习建议。
7. 将训练结果和小说生产能力关联，例如钩子、冲突、情绪推进或逻辑链。

## 输出格式

```markdown
# Training Exercise

## 训练目标
## 适用对象
## 题干
## 输入材料
## 作答要求
## 能力点
## 评分标准
## 常见错误
## 优秀答案特征
## 批改建议
## 下一步训练
```

## 质量标准

- 训练题必须有清晰能力目标。
- 评分标准必须可执行，不只写“语言优美”。
- 阅读或翻译材料必须遵守版权和篇幅边界。
- 训练结果应能反哺写作、审稿或表达能力。

## 禁止事项

- 禁止复制长篇版权文本作为训练材料。
- 禁止只有题目没有评分标准。
- 禁止把训练题做成泛泛鸡汤或空泛模板。
- 禁止输出现实高风险、违法或不安全操作训练。

## 与其他模块的关系

- 上游：KnowledgeCard、MaterialCard、ReviewReport、用户训练目标。
- 下游：TrainingExercise、质量评估、写作能力改进。
- Agent：Chief Editor Agent、Quality Agent、Review Agent。
