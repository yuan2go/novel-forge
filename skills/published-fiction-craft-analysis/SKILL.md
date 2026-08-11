---
name: published-fiction-craft-analysis
description: Analyze published fiction references into abstract scene craft, narrative distance, character arc, subtext, and transferable technique without copying protected expression.
---

# Published Fiction Craft Analysis

## Novel OS Runtime Contract

- 生产链输出必须进入 schema-backed Authority asset，不得只停留在 Markdown 或对话文本。
- 禁止 raw source text、参考作品表达、可识别场景顺序或作者风格模仿进入 prose、publish、recap 和 feedback backflow。
- Source Authority / EvidenceSpan / Observation / MKAOS / KnowledgePack 是正式生产边界；文件路径和 Markdown 报告仅用于非生产 operator handoff。

## Source Intelligence Observation Contract

当冻结 stage 为 `source.deconstruction.observe`，或输入包含 `AnalyzerContract` / `EvidenceSpan` 时，本节优先于任何 standalone 输出说明：

1. 只分析本次 AnalyzerContract 指定的 `dimension`、`scope` 和已冻结输入；不得自行扩大到整本作品。
2. Source bytes 只作为本次 Provider 内存中的瞬时证据使用；不得请求文件系统、Web、MCP 或额外来源。
3. 每条 finding 必须只描述抽象技法或叙事功能，并引用 supplied `evidence_span_ids`；聚合执行时改为引用 supplied lower Observation AssetVersion。
4. 输出必须严格匹配 Source Authority 的 Observation schema：`findings`、`confidence`、`knowledge_status=NOT_ABSTRACTED`。不得输出 `published_fiction_analysis_report`、KnowledgeCard、正文、文件写入指令或 Markdown 包装。
5. 不保留人物名、地点、独特事件序列、标志性场景、原句、语言纹理或可重建作品的组合。
6. `originality_copyright_risk` 维度只判断可迁移机制与受保护表达/独特组合之间的边界，不执行 Knowledge 抽象；Knowledge 抽象由后续 MKAOS 完成。

## 分析重点

根据 dimension 只选择相关观察：

- `structure`: 场景目标、阻碍、转折、后效应、段落/章节功能。
- `conflict`: 目标冲突、价值压力、选择成本和升级机制。
- `character_mechanism`: 欲望、信念压力、决策变化和角色弧驱动力。
- `relationship_mechanism`: 权力、信任、依赖、距离和关系状态变化。
- `emotion_curve`: 压力、缓释、反转、余韵与情绪节奏。
- `information_progression`: POV、叙事距离、信息遮蔽、揭示和潜台词。
- `foreshadowing`: 建立、强化、延迟、兑现或转义的功能关系。
- `originality_copyright_risk`: 不可迁移的表达、独特场景组合和作者识别性风险。

## Standalone / Operator Handoff

不在 Canonical Source Import Runtime 中运行时，可以生成 `published_fiction_analysis_report` 供人工阅读，但它不是生产 Authority，也不得直接进入生成 RAG。正式使用前必须转成 Observation，再经过 MKAOS 治理。

## 质量标准

- 结论停留在 craft/function 层，不模仿具体作者。
- Observation lineage 完整，confidence 与证据相符。
- 单个 finding 离开原作品语境仍能被理解，但不能据此复原原作品。
- Source-specific scene order、表达和专有组合不得进入可复用知识。

## 禁止事项

- Do not copy protected text or imitate a living or deceased author's distinctive style.
- Do not write draft prose from the reference.
- Do not preserve recognizable set pieces or source-specific scene sequence.
- Do not bypass Observation → MKAOS → Approval boundaries.
