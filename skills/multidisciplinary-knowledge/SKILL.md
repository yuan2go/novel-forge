---
name: multidisciplinary-knowledge
description: Transform professional, writing-theory, and multidisciplinary sources into evidence-backed abstract concepts, causal constraints, credibility rules, conflict generators, and review checks without copying source expression or turning fiction into exposition.
---

# Multidisciplinary Knowledge

## Novel OS Runtime Contract

- SourceDocument、SourceTransform、EvidenceSpan、Observation、MKAOS Candidate、KnowledgeCard 和 KnowledgePack 是正式生产边界。
- 专业资料不能因为“事实性”而绕过来源、许可、可信度、时效性或安全治理。
- raw source text 与未经抽象的专业资料不得直接进入正文生成 Context。

## Source Intelligence Observation Contract

当 stage 为 `source.deconstruction.observe`，或输入包含 AnalyzerContract / EvidenceSpan 时，本节优先：

1. 只分析当前 profile、dimension 与 scope；`writing_theory` 和 `professional_knowledge` 必须按冻结 profile 区分，不得混用网文拆解逻辑。
2. 只使用 supplied Source evidence 或 lower-scale Observation；不得主动访问文件系统、Web、MCP 或额外资料。
3. 每条 finding 必须引用 supplied `evidence_span_ids`，聚合模式改为 lower Observation AssetVersion。
4. 输出严格匹配 Source Observation schema：`findings`、`confidence`、`knowledge_status=NOT_ABSTRACTED`。不得直接输出 KnowledgeCard、Markdown Card、WorldBible 或项目约束。
5. Observation 只回答“来源中可观察到什么”，不提前完成 MKAOS 抽象、批准或生成使用判断。
6. 对高风险现实操作、医疗/法律/金融/安全等内容，仅保留概念关系、可信度边界和审稿风险；不得产出可执行危险步骤。
7. `originality_copyright_risk` 只记录来源表达、独特组织方式和不可迁移内容的风险边界。

## Professional Knowledge 分析重点

- `structure`: 概念体系、定义层次、前提、模型组成和论证结构。
- `conflict`: 因果机制中的资源冲突、约束、trade-off、制度压力和失败条件。
- `information_progression`: 定义 → 假设 → 证据 → 推理 → 结论的知识递进，以及缺失证据。
- `originality_copyright_risk`: 事实/公共知识与受保护表达、独特编排、专有图表/案例之间的边界。

## Writing Theory 分析重点

- `structure`: 方法、原则、步骤之间的依赖关系与适用层级。
- `pacing`: 理论对场景、章节、叙事节奏的可检验约束，而不是照搬示例。
- `conflict`: 可复用的冲突设计原则、适用条件和失败模式。
- `character_mechanism`: 人物设计/动机/弧光方法中的因果机制和限制。
- `information_progression`: 教学论证、例证与原则之间的逻辑关系。
- `originality_copyright_risk`: 方法原则与作者独特示例、措辞、结构模板之间的隔离。

## MKAOS 转译原则

Observation 进入 MKAOS 后，才可以抽象为：

- 核心概念与因果规则；
- 适用/禁用条件；
- 世界或人物可信度约束；
- 冲突生成器；
- Review checks；
- 仅供审稿而不得进入正文的风险规则。

不得把资料摘录、现实操作步骤或来源特有案例直接转成 KnowledgeCard。

## Standalone / Operator Handoff

脱离 Canonical Source Import Runtime 时可以输出人工阅读用 Multidisciplinary Knowledge Card，但它不是生产 Authority。正式进入 Novel OS 必须先形成 Evidence-backed Observation，再经过 MKAOS Governance。

## 质量标准

- 专业结论必须区分事实、模型、假设、解释和适用边界。
- 不确定、争议或时效敏感知识不得伪装成稳定事实。
- 知识服务剧情可信度和审稿，不替代冲突、人物与读者体验。
- 每个可迁移原则必须能说明何时失效。

## 禁止事项

- 禁止把小说写成论文或资料摘录。
- 禁止输出可执行的现实伤害、违法或高风险操作。
- 禁止未经 MKAOS 抽象和批准直接进入正文。
- 禁止把许可不明或受限制来源作为商业正文生成语料。
- 禁止为了获取资料绕过 robots、验证码、访问控制或平台限制。
