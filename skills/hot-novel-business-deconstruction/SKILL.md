---
name: hot-novel-business-deconstruction
description: Analyze web fiction references into abstract commercial structure, reader promise, hooks, pacing, and reusable review constraints without copying protected expression.
---

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
