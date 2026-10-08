---
name: hot-novel-deconstruction
description: Use when analyzing popular novels or genre samples to extract abstract structure, pacing, payoff mechanics, character mechanisms, conflict patterns, emotion curves, chapter hooks, and commercial logic without copying protected expression or plot combinations.
---

# Hot Novel Deconstruction

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 拆解热门小说、爆款章节、同赛道样本或类型文片段。
- 为 `decompose`、`extract-knowledge`、`build-materials` 或题材策划提供抽象输入。
- 需要判断一个样本为什么有追读、爽点和商业吸引力。

## 输入要求

- 来源、范围、类型、目标读者和拆解目的。
- 版权边界说明：输入只用于结构分析，不进入正文生成。
- 若样本来自单一作品，必须标记为高原创风险输入。
- 正式运行只接收 Source Authority 提供的 `source_document_id`、`source_transform_id`、不可变 `source_chunk_asset_version_id` 与稳定 `evidence_span_id`；不得从文件名推断来源身份。
- 每次运行必须冻结 analyzer / schema / prompt / Skill / capability / provider-policy / aggregation-policy 版本和 execution evidence。

## 正式 Deconstruction Intelligence 合同

- 输出首先是 `Observation`，不是 `KnowledgeCard`，也不是一篇整书 Markdown 总结。
- 维度按需独立运行：`structure`、`pacing`、`hook`、`reward_payoff`、`reader_promise`、`conflict`、`character_mechanism`、`relationship_mechanism`、`emotion_curve`、`foreshadowing`、`information_progression`、`serialization`、`commercial_logic`、`originality_copyright_risk`。
- 尺度从 `CHAPTER`、`CHAPTER_WINDOW`、`CHAPTER_GROUP` 逐级聚合到 `ARC`、`VOLUME`、`BOOK`、`CROSS_BOOK_PATTERN`；禁止默认整本一次模型调用。
- 下层 Observation 已足够时，上层聚合只读取 Observation，不重新读取原文；确定性聚合不得调用模型。
- 每条 finding 必须引用本次冻结输入中的 `evidence_span_id` 或 lower-scale Observation AssetVersion，并包含 confidence 与 originality risk。
- 相同 scope + analyzer contract + observation 内容必须重放已有结果；合约升级只重算目标维度及 lineage 下游。

## 操作流程

1. 记录来源、样本范围、类型、目标读者和拆解问题。
2. 拆出结构：开局问题、阶段目标、冲突升级、阶段奖励和结尾压力。
3. 拆出节奏：信息增量、压迫、缓释、反转、奖励兑现和章节钩子间隔。
4. 拆出人物机制：欲望、恐惧、能力、缺陷、关系压力和行动代价。
5. 拆出冲突机制：目标冲突、资源冲突、身份冲突、价值冲突和制度压力。
6. 拆出商业逻辑：读者期待、爽点承诺、情绪释放、追读理由和禁用风险。
7. 先提交结构化 Observation，明确 `knowledge_status=NOT_ABSTRACTED`。
8. 交给 `anti-copy-abstraction` 生成独立 Knowledge Candidate；不得把 Observation 直接当生产知识。

## 输出格式

生产输出必须匹配 `source-deconstruction-observation.v1`，至少包含：

```json
{
  "findings": [{
    "finding_code": "hook.chapter_end_pressure",
    "statement": "仅描述抽象观察，不复述来源表达",
    "evidence_span_ids": ["source-evidence-span:..."]
  }],
  "confidence": 0.0,
  "originality_risk": "LOW_AFTER_ABSTRACTION",
  "knowledge_status": "NOT_ABSTRACTED"
}
```

以下 Markdown 只允许作为 operator handoff，不是生产 Authority：

```markdown
# 热门小说拆解报告

## 来源与范围
## 类型与目标读者
## 结构拆解
## 节奏拆解
## 爽点机制
## 人设机制
## 冲突机制
## 情绪曲线
## 章节钩子
## 商业化逻辑
## 可复用抽象原则
## 禁止复用内容
## 原创风险等级
```

## 质量标准

- 输出重点是结构、机制和读者效果，不是剧情复述。
- 每个可复用点必须说明适用边界。
- 每个高风险点必须进入禁止复用内容。
- Observation 必须能通过后续 Abstraction/Governance 转成 Candidate，但自身永远不是可生成知识。

## 禁止事项

- 禁止复制原文表达、台词、人物身份、独特设定和具体桥段。
- 禁止把单一热门小说直接转成新书剧情骨架。
- 禁止输出换名仿写建议。
- 禁止把原文片段保存为可生成素材。

## 与其他模块的关系

- 上游：Source Authority 的精确 Document、Transform、Chunk、EvidenceSpan，以及 `docs/current-system.md` 的来源隔离合同。
- 下游：`anti-copy-abstraction`、Source Deconstruction Authority、MKAOS Candidate/Governance；任何 operator handoff 都不是生产 Authority。
- Agent：Knowledge Agent、Material Agent、Chief Editor Agent。
