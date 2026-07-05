---
name: long-outline
description: Use when creating or reviewing full-book outlines, volume plans, long-serial arcs, enemy escalation, resource progression, relationship changes, payoff distribution, and foreshadowing/recovery plans.
---

# Long Outline

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 生成全书大纲、卷纲、前 30 章规划或长期连载节奏。
- 审查大纲是否能支撑主线目标和持续追读。
- 将题材、世界观和人物转化为可执行剧情路线。
- 长线结构需要检查 reader grounding、beat 解锁顺序、伏笔/payoff 路径和信息递进时，配合 `narrative-beat-design`。

## 输入要求

- TopicSeed、WorldBible、CharacterCard、MaterialCard。
- 目标读者、核心爽点、主线冲突和连载长度预期。
- 已有伏笔、禁用项、原创风险边界。

## 操作流程

1. 明确全书主线目标和不可回避的核心冲突。
2. 划分阶段目标或卷目标，并定义每阶段的敌人升级和资源升级。
3. 规划人物关系变化、信念变化和关键代价。
4. 定义每阶段 reader prerequisites、已 grounded 规则、人物状态和读者承诺。
5. 规划阶段 beat path：每个阶段必须说明它 requires 什么、grounds 什么、解锁哪些后续冲突或 payoff。
6. 安排爽点分布、情绪曲线、阶段高潮和追读钩子。
7. 建立伏笔设置、延迟兑现和回收计划，确保 payoff 前有足够 grounding。
8. 检查每卷是否有明确奖励、代价、升级和更大压力。
9. 输出全书大纲、卷纲和风险清单。

## 输出格式

```markdown
# 全书大纲

## 一句话主线
## 全书目标
## 核心冲突
## 阶段目标 / 卷纲
## 敌人升级
## 资源升级
## 人物关系变化
## Reader Grounding
## Beat Path
## 爽点分布
## 情绪曲线
## 伏笔与回收
## 前 3 章目标
## 前 10 章目标
## 风险与返工项
```

## 质量标准

- 每一卷必须有清晰目标、阻力、奖励、代价和结尾升级。
- 主角成长必须对应更强冲突，而不是单纯堆能力。
- 每个阶段关键 beat 必须说明它为后续章节 grounded 了哪些规则、关系、悬念或承诺。
- 伏笔必须有设置位置、回收窗口和剧情功能。
- 长线规划必须服务追读，不得变成设定年表。

## 禁止事项

- 禁止只有世界设定，没有人物行动。
- 禁止让敌人升级无理由或主角升级无代价。
- 禁止照搬已有作品卷结构。
- 禁止让伏笔只存在于作者笔记，无法进入章节执行。

## 与其他模块的关系

- 上游：`character-design`、`worldbuilding`、`TopicSeed`。
- 下游：`chapter-outline`、`prose-generation`、`quality-review`。
- 关联 Skill：`narrative-beat-design`。
- Agent：Chief Editor Agent、Draft Agent、Review Agent。
