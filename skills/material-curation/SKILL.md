---
name: material-curation
description: Use when classifying, tagging, organizing, or quality-checking reusable material assets so raw sources, cleaned text, decompositions, knowledge, and material cards become searchable production assets without mixing source text into generated fiction.
---

# Material Curation

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 将清洗文本、拆解结果、知识卡或素材卡整理成可调用资产。
- 为素材打标签：题材、情绪、冲突、场景、人物类型、钩子、爽点。
- 审查素材是否混入原文、版权内容或不可生成内容。

## 输入要求

- SourceDocument、CleanedText、DecompositionReport、KnowledgeCard 或 MaterialCard。
- 来源、版权边界、抽象程度和目标用途。
- 标签体系或当前项目需要检索的维度。

## 操作流程

1. 确认素材生命周期：raw、cleaned、decomposition、knowledge、material。
2. 检查来源、版权边界、references 和 metadata 是否完整。
3. 区分可生成素材、只可参考素材、只可审稿素材和禁用素材。
4. 打标签：类型、情绪、冲突、场景、角色功能、钩子、爽点、风险。
5. 删除或隔离具体表达、独特桥段、人物组合和不可授权内容。
6. 输出素材卡整理建议和质量问题。
7. 需要创作转化时交给 `topic-development` 或 `multidisciplinary-knowledge`。

## 输出格式

```markdown
# Material Curation Report

## 素材来源
## 当前资产类型
## 版权边界
## 标签
## 可生成内容
## 只可参考内容
## 只可审稿内容
## 禁用内容
## 质量问题
## 推荐下游用途
```

## 质量标准

- 素材必须有来源和可追溯 references。
- 标签必须服务检索、生成、审稿或反馈，不做装饰性分类。
- 可生成内容必须已经抽象化。
- 禁用内容必须明确写出原因和下游限制。

## 禁止事项

- 禁止把原文、台词、具体桥段标为可生成素材。
- 禁止混淆 raw、cleaned、decomposition、knowledge 和 material。
- 禁止无来源素材进入长期资产库。
- 禁止把素材整理当成正文写作。

## 与其他模块的关系

- 上游：`ingest`、`clean`、`decompose`、`extract-knowledge`、`build-materials`。
- 下游：MaterialCard、TopicSeed、ReviewReport。
- Agent：Material Agent、Knowledge Agent、Quality Agent。
