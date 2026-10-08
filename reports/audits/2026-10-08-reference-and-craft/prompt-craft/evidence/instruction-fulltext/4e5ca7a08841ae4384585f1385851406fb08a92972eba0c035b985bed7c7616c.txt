---
name: prose-generation
description: Use when drafting chapter prose from an approved chapter plan while controlling web-novel pacing, dialogue, action, emotion, narrative density, chapter hooks, and post-draft self-checks.
---

# Prose Generation

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 根据已通过检查的 ChapterPlan 生成正文 v0 或修订稿。
- 将场景目标、冲突、行动和情绪变化转化为可审稿文本。
- DeepSeek 或其他正文模型需要明确写作边界时。

## 输入要求

- 已通过 `chapter-outline` 检查的 ChapterPlan。
- 项目上下文、人物状态、世界规则、风格规则和本章审稿重点。
- 禁止复用内容和原创风险边界。

## 操作流程

1. 读取细纲，不新增未经授权的主线设定。
2. 按场景顺序写作，先行动和冲突，后解释设定。
3. 控制叙述密度：每个场景必须有信息增量或情绪变化。
4. 通过对白、动作、选择和代价体现人物。
5. 确保爽点通过行动兑现，结尾留下追读钩子。
6. 生成后自检章节功能是否完成。
7. 输出正文草稿和自检报告，不直接标记为 final。

## 输出格式

```markdown
# 第 N 章正文 v0

## 正文

## 自检

- 是否完成本章目标：
- 是否有明确冲突：
- 是否有信息增量：
- 是否有读者爽点：
- 是否有代价：
- 是否有结尾钩子：
- 是否存在原创风险：
- 是否存在 AI 腔：
```

## 质量标准

- 正文必须严格服务细纲，不能脱纲扩展新主线。
- 开头必须尽快进入异常、冲突或压力。
- 每章结尾必须给出下一章阅读理由。
- 解释不能压过行动，多学科知识只能服务可信度。
- 生成稿必须进入 `quality-review`，不能直接进入 final。

## 禁止事项

- 禁止无细纲生成正文。
- 禁止覆盖 final 或发布稿。
- 禁止复制热门小说表达、桥段、人物或独特设定。
- 禁止用总结式 AI 腔替代场景推进。

## 与其他模块的关系

- 上游：`chapter-outline`、ChapterPlan、MockModel 或未来 Draft adapter。
- 下游：`quality-review`、ReviewReport、RevisionPlan。
- Agent：Draft Agent、Review Agent、Quality Agent。
