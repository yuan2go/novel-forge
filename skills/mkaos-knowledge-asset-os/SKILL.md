---
name: mkaos-knowledge-asset-os
description: Use when importing, extracting, selecting, gating, tracing, or learning from multidisciplinary knowledge assets through MKAOS while preserving evidence lineage, source isolation, quality scores, and feedback-based evolution.
---

# MKAOS Knowledge Asset OS

## 适用场景

- 将专业书、网文拆解、名著分析、平台规则、读者反馈或 Agent 报告转为 MKAOS 知识资产。
- 设计或审计 KnowledgeCard、RuleCard、TemplateCard、KnowledgeRelation、KnowledgePack、SelectorDecision、QualityScore、LineageReport。
- 需要把知识从“资料说明”抽象成可迁移创作机制、审稿规则、模板或生产约束。

## 输入要求

- `project_id`、任务目标、目标 flow、平台、题材、运行环境和 OS Envelope 或显式 compat 理由。
- source document / chunk / evidence span / extraction report / feedback / review issue 的引用，而不是原文长段。
- 当前 source policy、copyright boundary、source isolation 要求和质量门禁阈值。

## Novel OS Runtime Contract

- 生产链路输出必须落到 schema-backed asset，不能只停留在对话文本。
- 每个知识资产必须保留来源引用、evidence refs、`project_id`、`trace_id`、质量状态和 mutation audit 线索。
- KnowledgePack 必须通过 Selector、Quality Gate、Source Isolation Gate，并记录 selected/rejected 原因。
- 禁止 raw source text、`source_chunk.raw_text`、parallel pair `source_text/target_text` 进入 KnowledgePack、ContextBundle、prose、publish、recap。
- 高风险、隔离、过低抽象或 source leakage 风险必须转为 ReviewIssue 或 GateResult。

## 操作流程

1. 识别来源类型、权利边界、证据层范围和可下游使用的抽象边界。
2. 将来源转成 evidence refs、知识候选、规则候选或模板候选。
3. 检查 creative principle、narrative function、conflict function、applicable flows 和 originality boundary 是否完整。
4. 运行质量评分、反百科化、source leakage、冲突检测和 flow binding 检查。
5. 构建 KnowledgeRelation / lineage / selector decision，解释选中和拒绝原因。
6. 将合格知识进入 KnowledgePack；不合格项进入 ReviewIssue、RegressionCase 或 human review queue。
7. 使用 usage event、review result、reader feedback 和 publish gate 结果生成 learning recommendation。

## 输出格式

```markdown
# MKAOS Knowledge Asset Report

## Assets
- source/evidence refs:
- knowledge cards:
- rule cards:
- template cards:
- relations:
- packs:

## Gates
- quality:
- source isolation:
- conflict:
- review issues:

## Selector Decision
- selected:
- rejected:
- budget:
- risk:

## Learning
- feedback signals:
- weight recommendations:
- audit refs:
```

## 质量标准

- 知识必须是抽象机制、生产约束或可迁移模板，不能是来源内容摘要。
- 每条生产可用知识必须有 evidence refs、适用 flow、原创边界和质量分。
- Selector 必须能解释选中、拒绝、降权、隔离和预算裁剪。
- Feedback Learning 默认 advisory；自动调权必须有显式 apply policy 和 audit。

## 禁止事项

- 禁止把来源原文、译文、摘录、受保护表达或平行语料文本写入生成上下文。
- 禁止无 evidence refs 的生产知识进入 strict / production / operating_system 路径。
- 禁止用百科说明替代创作机制。
- 禁止跳过 Context Builder、ReviewIssue、GateResult 或 mutation audit。

## 与其他模块的关系

- 上游：MKAOS Ingestion、Model Extraction、Audit Log、Feedback Backflow、Evaluation Center。
- 下游：Context Builder、AgentRun、Loop Kernel、ReviewIssue、Publish Gate、Editor-in-Chief Console。
- 关联 Skill：`context-builder-source-isolation`、`review-issue-gate`、`platform-strategy-os`、`quality-review`。
