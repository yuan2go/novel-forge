---
name: classic-literary-depth-analysis
description: Analyze classic literature references into abstract theme systems, social pressure graphs, symbol functions, fate curves, and reusable craft constraints.
---

## 适用场景

用于经典名著深度拆解，提取主题系统、社会关系、象征功能、命运曲线和道德困境。只转化结构功能，不复用具体文本或标志性场景。

## 输入要求

- schema-backed source asset path.
- project workspace path when available.
- source rights and copyright boundary.
- analysis scope and desired abstraction level.

## 操作流程

1. Read the referenced source asset by path.
2. Identify deep structure, theme system, symbol functions, social relation model, and fate curve.
3. Mark non-transferable protected elements.
4. Produce `classic_literary_analysis_report`.
5. Record validation status and reusable abstractions.

## 输出格式

Write one JSON asset with type `classic_literary_analysis_report` under `data/analysis`.

## 质量标准

- Report passes schema validation.
- Transferable items are abstract functions, not scenes.
- Non-transferable elements are explicit.
- `metadata.use_in_generation_rag` is `false`.

## 禁止事项

- Do not copy protected text.
- Do not reuse recognizable set pieces.
- Do not write draft prose.
- Do not treat public fame as permission to copy.

## 与其他模块的关系

Output can be converted into `knowledge_card`, `craft_template`, or `review_rule_pack`.
