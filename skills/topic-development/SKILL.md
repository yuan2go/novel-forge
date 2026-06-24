---
name: topic-development
description: Use when developing or reviewing a novel topic from abstract patterns, market position, genre fusion, premise generation, and trope variation so the topic has reader appeal, differentiation, and originality boundaries.
---

# Topic Development

## 适用场景

- 从 KnowledgeCard、MaterialCard 或抽象拆解结果生成 TopicSeed。
- 判断题材卖点、目标读者、平台适配和差异化。
- 将常见套路转化为原创变体，而不是复刻流行作品。

## 输入要求

- 已通过 `anti-copy-abstraction` 的抽象机制或 MaterialCard。
- 目标读者、平台假设、类型方向和禁用内容。
- 已有相似项目、同质化风险或市场定位约束。

## 操作流程

1. 明确类型基础：玄幻、悬疑、都市、科幻、历史或混合类型。
2. 提炼核心吸引力：主角代入、开局异常、压迫、反击承诺、爽点。
3. 做题材融合：只融合能制造冲突和读者期待的类型机制。
4. 生成一句话 premise：主角、异常、目标、阻力、代价。
5. 做套路变体：保留读者熟悉的期待，替换身份、资源、压力源或冲突场。
6. 检查市场定位：目标读者、平台适配、前 3 章钩子、前 10 章回报。
7. 输出 TopicSeed 候选和原创风险边界。

## 输出格式

```markdown
# Topic Development

## 类型组合
## 目标读者
## 一句话核心创意
## 核心卖点
## 开局异常
## 主角代入点
## 初始压迫
## 爽点承诺
## 前 3 章钩子
## 前 10 章回报
## 差异化设计
## 原创风险边界
## 是否进入世界观/人物设计
```

## 质量标准

- 题材必须能支撑主线冲突和长期连载。
- premise 必须清楚说明主角为什么非行动不可。
- 差异化必须具体，不只写“融合”“创新”。
- 每个套路变体必须避开具体作品的人物、设定、桥段组合。

## 禁止事项

- 禁止直接生成“某作品换皮”题材。
- 禁止只堆类型标签，没有读者承诺。
- 禁止为了新奇牺牲可读性和追读动力。
- 禁止让题材创意绕过 `anti-copy-abstraction`。

## 与其他模块的关系

- 上游：`hot-novel-deconstruction`、`anti-copy-abstraction`、MaterialCard。
- 下游：TopicSeed、`worldbuilding`、`character-design`、`long-outline`。
- Agent：Chief Editor Agent、Material Agent、Outline Agent。
