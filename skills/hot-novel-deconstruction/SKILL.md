---
name: hot-novel-deconstruction
description: Analyze web novels and genre samples into evidence-backed abstract structure, pacing, reward, character, conflict, emotion, hook, serialization, and commercial Observations without copying protected expression or plot combinations.
---

# Hot Novel Deconstruction

## Novel OS Runtime Contract

- Source Authority / EvidenceSpan / Observation / MKAOS / KnowledgePack 是正式生产边界。
- raw source、原句、人物名、独特设定和具体桥段不得进入 prose、publish、recap 或 feedback backflow。
- Observation 只描述来源中观察到什么；只有经后续 MKAOS 抽象和 Governance 批准的 KnowledgeCard 才可进入生产知识。

## Source Intelligence Observation Contract

当 stage 为 `source.deconstruction.observe`，或输入包含冻结 AnalyzerContract / EvidenceSpan 时：

1. 只分析 AnalyzerContract 指定的 `dimension` 和 `scope`，不得默认整本一次分析，也不得自行扩大样本范围。
2. 只使用 supplied Source evidence 或 lower-scale Observations；不得访问文件系统、Web、MCP 或其它未冻结来源。
3. 每条 finding 必须引用 supplied `evidence_span_ids`；聚合模式只引用 supplied lower Observation AssetVersion。
4. 输出必须**严格**匹配冻结 Source Observation schema，只允许：
   - `findings`
   - `confidence`
   - `knowledge_status`，且必须为 `NOT_ABSTRACTED`
5. 不得额外输出 `originality_risk`、Markdown 报告、KnowledgeCard、正文、文件写入指令或解释性包装；原创风险必须作为 `originality_copyright_risk` dimension 下的 finding 表达。
6. finding statement 只能描述抽象机制、节奏/状态变化和读者效果，不复述来源剧情，不保留可识别事件序列。
7. Higher-scale 聚合如果输入已经是 lower-scale Observations，不得重新读取 Source text。

## Dimension Focus

- `structure`: 开局问题、阶段目标、转折、升级、阶段结果和结构压力。
- `pacing`: 信息增量、压迫、缓释、反转、奖励间隔和节奏密度。
- `hook`: 未决问题、信息缺口、威胁、机会和章节末前进压力。
- `reward_payoff`: 承诺、延迟、兑现、升级与奖励密度。
- `reader_promise`: 题材/角色/冲突对读者形成的可验证期待与兑现状态。
- `conflict`: 目标、资源、身份、价值、关系和制度压力的升级机制。
- `character_mechanism`: 欲望、恐惧、能力、缺陷、决策成本和行动驱动。
- `relationship_mechanism`: 信任、权力、依赖、敌友和亲疏状态变化。
- `emotion_curve`: 压力、期待、释放、反转、余韵和疲劳。
- `foreshadowing`: 建立、强化、延迟、兑现、转义或失效的功能关系。
- `information_progression`: 信息隐藏、揭示、误判、认知差和读者知识变化。
- `serialization`: 连载推进、阶段闭环、持续未决问题和下一章驱动力。
- `commercial_logic`: 追读理由、核心承诺、奖励周期和读者留存机制；不得把未经证据支持的平台传闻写成规则。
- `originality_copyright_risk`: 哪些仅能迁移抽象功能，哪些表达、设定、场景和独特组合必须隔离。

## MKAOS Handoff

Observation 完成后交给 `anti-copy-abstraction`：

```text
Evidence
→ Observation (NOT_ABSTRACTED)
→ MKAOS Candidate
→ Governance
→ KnowledgeCard
```

不得把热门作品直接变成“换名剧情模板”。

## Standalone / Operator Handoff

脱离 Canonical Source Import Runtime 时可以生成人工阅读用热门小说拆解报告，但它不是生产 Authority。正式使用必须重新进入 Evidence-backed Observation，再经过 MKAOS。

## 质量标准

- 输出重点是结构机制和读者状态，而不是剧情复述。
- 每条 finding 必须有本次冻结输入的 lineage。
- 可迁移原则必须脱离单一作品仍成立，并有适用/禁用边界。
- Originality 风险通过专门 dimension 记录，不在 schema 外增加字段。

## 禁止事项

- 禁止复制原文、台词、人物身份、独特设定、标志性场景和具体桥段。
- 禁止把单一热门小说直接转成新书剧情骨架或换名仿写方案。
- 禁止把 SourceChunk 或 Observation 直接送入正文生成。
- 禁止绕过 MKAOS Governance。
