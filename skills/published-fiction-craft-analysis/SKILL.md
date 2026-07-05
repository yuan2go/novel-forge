---
name: published-fiction-craft-analysis
description: Analyze published fiction references into abstract scene craft, narrative distance, character arc, subtext, and transferable technique reports.
---

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

用于拆解出版小说的技法层：场景经营、叙事距离、角色弧光、转场、潜台词和语言纹理。只保留技法参数，不模仿具体作者。

## 输入要求

- schema-backed source asset path.
- project workspace path when available.
- source rights and copyright boundary.
- desired craft focus if available.

## 操作流程

1. Read the referenced source asset by path.
2. Separate scene objective, obstacle, turn, after-effect, character belief pressure, and narrative distance.
3. Remove source-specific characters, scenes, prose texture, and sequence.
4. Produce `published_fiction_analysis_report`.
5. Record validation status and copyright boundary.

## 输出格式

Write one JSON asset with type `published_fiction_analysis_report` under `data/analysis`.

## 质量标准

- Report passes schema validation.
- Output stays at craft-parameter level.
- `metadata.use_in_generation_rag` is `false`.
- No specific author imitation request appears.

## 禁止事项

- Do not copy protected text.
- Do not imitate a specific author.
- Do not write draft prose.
- Do not preserve source-specific scene order.

## 与其他模块的关系

Output can be converted into `craft_template`, `writing_template`, or `review_rule_pack` before use in production.
