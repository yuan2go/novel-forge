---
name: evidence-fact-verification
description: Use when extracting a factual claim, binding source evidence, checking cross-source agreement and temporal freshness, and producing a fail-closed verification decision for story research or review.
---

# Evidence / Fact Verification

## Novel OS Runtime Contract

- 本 Skill 不建立第二套 Source、Evidence、Knowledge 或 Vector Store；必须复用 Source Governance、MKAOS、KnowledgePack、Context Builder、AssetVersion 和 Trace。
- 正式链路为 Claim extraction → evidence retrieval → evidence binding → cross-source verification → decision → Fact Gate。
- `fact.verify` 只能使用同项目、带 lineage 和 temporal metadata 的 evidence；无充分 evidence 返回 `INSUFFICIENT_EVIDENCE`，不得让 LLM 用常识补齐。
- Claim、verification report、ReviewIssue / GateResult 必须 schema-backed，保留 trace；Provider 调用还需 model call、cost ledger 和 qualification。

## 适用场景

- 审核现实世界事实、专业细节、时间敏感断言或不同来源互相冲突的 claim。
- 为 WorldBible、Outline、ChapterPlan、Draft Review 或 Publish Gate 提供 evidence-backed fact decision。
- 判断 VERIFIED、DISPUTED、UNSUPPORTED、OUTDATED 或 INSUFFICIENT_EVIDENCE。

## 输入要求

- `claim_id`、`project_id`、statement、domain、source id、trace id。
- evidence refs、source published/retrieved time、temporal valid range、source quality、stance 和 confidence。
- verification as-of time、freshness policy、fictionalization policy 和 downstream target。

## 操作流程

1. 抽取最小可验证 Claim，不把观点集合伪装为单一事实。
2. 通过 MKAOS / KnowledgePack 检索 eligible evidence，保留 source 与 chunk lineage。
3. 绑定支持、反对和中性 evidence；过滤跨项目、未授权、无 lineage 或时间上无效的记录。
4. 检查来源质量、独立性、published/retrieved time、temporal validity 和 freshness。
5. 产生 VERIFIED / DISPUTED / UNSUPPORTED / OUTDATED / INSUFFICIENT_EVIDENCE 决策及理由。
6. 将 blocking decision 写入 ReviewIssue / Fact Gate；`fictionalization_allowed` 只表达策略，不把假事实标记为 VERIFIED。

## 输出格式

```markdown
# Fact Verification Report

## Claim
- id / project / statement / domain:
- temporal validity:
- fictionalization allowed:

## Evidence Binding
- supporting:
- contradicting:
- excluded and reason:

## Decision
- status:
- source quality / confidence:
- freshness:
- trace:
- gate / revision action:
```

## 质量标准

- VERIFIED 必须有适用时间内、lineage 完整且达到质量门槛的支持证据。
- DISPUTED 必须保留冲突双方，不以单一 provider 偏好抹去反证。
- OUTDATED 必须说明失效时间或 freshness policy；UNSUPPORTED 与 INSUFFICIENT_EVIDENCE 不混淆。
- 所有 evidence 与 Claim 必须同项目，跨来源结论必须能列出绑定关系。

## 禁止事项

- 禁止“让 LLM 根据常识检查是否正确”。
- 禁止无 evidence 返回 VERIFIED，或把模型 confidence 当作 source quality。
- 禁止重复建设 MKAOS、Source Governance、Knowledge DB、Vector Store 或 Provider Runtime。
- 禁止把原始受保护来源文本直接放进 Draft / Publish 上下文。

## 与其他模块的关系

- 上游：Source、Evidence、MKAOS、KnowledgePack、Context Builder、Trace。
- 下游：ReviewIssue、Fact Gate、RevisionPlan、WorldBible / Draft review、Publish Gate。
- 关联 Skill：`mkaos-knowledge-asset-os`、`context-builder-source-isolation`、`multidisciplinary-knowledge`、`quality-review`。
