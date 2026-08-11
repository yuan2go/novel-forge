---
name: anti-copy-abstraction
description: Convert governed source Observations into reusable abstract Knowledge Candidates that cannot reconstruct or imitate a protected work.
---

# Anti Copy Abstraction

## Novel OS Runtime Contract

- Observation 只描述来源中观察到什么；Knowledge Candidate 才描述经过抽象后可复用什么，两者不得共用资产或状态。
- 正式输入必须是已提交的 Observation AssetVersion，并保留 EvidenceSpan lineage；不得重新读取 raw SourceChunk、文件路径或外部来源。
- Candidate 未经过 MKAOS Governance/Approval 前不得成为 KnowledgeCard，也不得进入生成 Context。

## Source MKAOS Candidate Contract

当 stage 为 `source.mkaos.extract`，本节优先于 standalone 报告格式：

1. 只使用 supplied Observation 及其冻结 lineage metadata，不请求文件系统、Web、MCP 或 raw source。
2. 删除或泛化人物名、地点、专有名词、事件顺序、标志性场景、语言纹理、独特反转和可识别组合。
3. 只保留跨作品成立的因果机制、约束、冲突生成器、可信度规则和审稿检查。
4. 输出必须严格匹配冻结 MKAOS schema，且只包含：
   - `concept_name`
   - `discipline`
   - `abstract_principle`
   - `constraints`
   - `conflict_generators`
   - `review_checks`
   - `copyright_boundaries`
5. 不得输出 Markdown、反抄袭报告、Source quote、EvidenceSpan 原文、KnowledgeCard ID、approval decision 或正文。
6. `copyright_boundaries` 必须说明哪些具体表达、设定、场景组合、案例或来源组织方式不能迁移。
7. 如果 Observation 本身不足以支持可复用机制，Candidate 应保持保守、收窄适用条件，而不是发明机制。

## 抽象方法

1. 区分表达、具体事件、设定、结构功能、因果机制和读者/系统效果。
2. 删除表达、具体事件、独特设定和可识别人物组合。
3. 将具体桥段映射成类型无关的状态变化、约束或决策机制。
4. 为原则补充适用条件、失效条件和安全/版权边界。
5. 把可检验的风险转成 review checks，而不是模糊“注意原创”。
6. 对专业知识，保留概念和因果边界，不保留来源特有案例与表达。
7. 对文学作品，保留 craft/function，不保留作者识别性语言或 set piece。

## Standalone / Operator Handoff

脱离 Canonical Source MKAOS Runtime 时可以生成人工阅读用反抄袭抽象报告，但该报告不是 Knowledge Authority。正式生产必须重新进入 Observation → Candidate → Governance → KnowledgeCard。

## 质量标准

- Candidate 不能让创作者据此复原原作品的具体桥段或表达。
- 每条抽象原则脱离单一来源语境仍成立，并说明适用/禁用范围。
- copyright boundary、review checks 与 constraints 必须具体可执行。
- 不得把“换名字、换地点”视为有效抽象。

## 禁止事项

- 禁止保留可识别人物组合、标志性场景、独特反转或具体案件结构。
- 禁止用“致敬”“参考风格”规避版权边界。
- 禁止把 Observation 直接交给 prose-generation。
- 禁止绕过 MKAOS Approval 把 Candidate 变成生产知识。
