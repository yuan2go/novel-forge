---
name: analysis-to-asset-conversion
description: Convert abstract analysis reports into schema-backed reusable creative assets with explicit copyright boundary, reuse scope, and rejected high-risk items.
---

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

用于把分析报告转换成可生产使用的抽象资产，如素材卡、知识卡、写作模板、技法模板和审稿规则包。

## 输入要求

- schema-backed analysis report path.
- requested conversion targets.
- project workspace path when available.
- source risk and allowed pipeline.

## 操作流程

1. Read the analysis report by path.
2. Reject any item that depends on protected expression, names, settings, or event sequence.
3. Convert safe mechanisms into schema-backed creative assets.
4. Write `analysis_conversion_report` under `data/analysis`.
5. Record created assets, rejected items, reuse scope, copyright risk, and validation status.

## 输出格式

Write one JSON asset with type `analysis_conversion_report` under `data/analysis`, plus any created creative assets in their mapped data directories.

## 质量标准

- All outputs pass schema validation.
- Created assets declare abstract copyright boundary.
- High copyright risk material is rejected or marked for human gate.
- Source report itself is not inserted into generation RAG.

## 禁止事项

- Do not copy protected text.
- Do not create draft prose.
- Do not hide rejected high-risk items.
- Do not bypass schema validation.

## 与其他模块的关系

Converted assets can feed topic, material, knowledge, template, context, and review workflows after project review.
