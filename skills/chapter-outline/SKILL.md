---
name: chapter-outline
description: Use when creating or reviewing chapter plans so every chapter has a goal, cast, scene list, conflict, information gain, payoff, suspense, reversal, ending hook, and next-chapter handoff.
---

# Chapter Outline

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 将全书大纲或卷纲拆成可写作的章节细纲。
- 正文生成前检查章节是否具备最小商业单元。
- 审稿时发现章节缺冲突、缺爽点、缺钩子，需要退回细纲。
- 章节存在信息跳跃、概念未铺垫、伏笔/payoff 没有 reader grounding 时，配合 `narrative-beat-design` 重排 beat path。

## 输入要求

- Outline、CharacterCard、WorldBible、前文上下文和本章位置。
- 本章必须推进的信息、必须设置或回收的伏笔。
- 禁止事项和原创风险边界。

## 操作流程

1. 明确本章目标和必须完成的剧情功能。
2. 列出出场人物、人物目标、冲突关系和场景。
3. 设计本章冲突、阻力、行动、代价和结果。
4. 定义本章 reader prerequisites 和 grounded set：读者进入本章前已经知道的人物状态、世界规则、伏笔和承诺。
5. 设计 beat path：每个 beat 标注 function、requires、grounds、hook/payoff 和风险。
6. 安排信息增量、爽点、悬念、反转和情绪变化，确保后续 beat 不依赖未 grounded 概念。
7. 设计开头钩子、小钩子、结尾钩子和下一章承接点；标注 hook type、information gap、reader question、promise id、horizon 和证据位置。
8. 检查章节最小商业单元：冲突、推进、奖励、代价、钩子。
9. 输出可交给正文模型执行的细纲。

## 输出格式

```markdown
# 第 N 章细纲

## 本章目标
## 出场人物
## 场景列表
## 本章冲突
## 信息增量
## Reader Grounding
## Beat Path
## 读者爽点
## 悬念与反转
## 代价
## 开头钩子
## 结尾钩子
## Hook Horizon 与 Promise Binding
## 下一章承接点
## 章节最小商业单元检查
```

## 质量标准

- 每章必须有冲突、推进、奖励、代价和钩子。
- 每个场景必须有目标、阻力、行动、信息增量和情绪变化。
- 每个关键 beat 的 requires 必须已经是 prerequisite 或由早先 beat grounded。
- 如果本章需要解释世界规则、专业知识或伏笔，必须先说明它服务哪个行动、冲突或 payoff。
- 结尾钩子必须制造下一章阅读理由。
- Hook horizon 应由 reader promise、arc 和 serial function 决定，不得硬编码统一兑现窗口。
- 细纲必须足够具体，能约束 `prose-generation` 不脱纲。

## 禁止事项

- 禁止用“铺垫一章”替代章节功能。
- 禁止只有设定说明，没有人物行动。
- 禁止为了反转牺牲因果链。
- 禁止创建没有 promise lineage 或后续承接责任的空钩子。
- 禁止绕过细纲直接生成正文。

## 与其他模块的关系

- 上游：`long-outline`、`character-design`、`worldbuilding`。
- 下游：`prose-generation`、`quality-review`、`DraftChapter`。
- 关联 Skill：`narrative-beat-design`。
- Agent：Draft Agent、Review Agent、Quality Agent。
