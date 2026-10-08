---
name: hot-novel-business-deconstruction
description: Analyze web fiction references into abstract commercial structure, reader promise, hooks, pacing, and reusable review constraints without copying protected expression.
---

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

用于把网文或连载参考作品拆解成商业结构、爽点循环、章节钩子、人设压力和平台节奏。只输出抽象机制，不输出可直接复用的正文、角色名、设定名或情节顺序。

## 输入要求

- schema-backed source asset path.
- project workspace path when available.
- source rights and copyright boundary.
- target platform, genre, and reader promise if available.

## 操作流程

1. Read the referenced source asset by path.
2. Identify reader promise, hook system, payoff loop, pacing model, and retention risks.
3. Remove source-specific names, protected scenes, unique settings, and prose.
4. Produce `web_fiction_business_analysis_report`.
5. Record source asset id, expected output path, validation command, and risk boundary.

## 输出格式

Write one JSON asset with type `web_fiction_business_analysis_report` under `data/analysis`.

## 质量标准

- Report passes schema validation.
- Analysis is abstract and mechanism-level.
- `metadata.use_in_generation_rag` is `false`.
- High-risk findings are marked for conversion review.

## 禁止事项

- Do not copy protected text.
- Do not reuse source-specific names, settings, or plot sequence.
- Do not write draft prose.
- Do not insert analysis reports directly into generation RAG.

## 与其他模块的关系

Output can be converted by the asset converter into `material_card`, `writing_template`, `craft_template`, or `review_rule_pack`.
