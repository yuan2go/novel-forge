---
name: character-design
description: Use when creating or reviewing character cards so each character has goals, desires, fears, obsessions, abilities, flaws, relationships, growth arc, and actions that serve the main conflict.
---

# Character Design

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 创建主角、反派、配角或关键关系人物。
- 审查人物是否能推动主线冲突。
- 大纲、细纲或草稿中出现动机漂移、降智或工具人问题。

## 输入要求

- TopicSeed、WorldBible、项目方向或章节目标。
- 主线冲突、目标读者、核心爽点和世界规则。
- 已有人物关系、阶段剧情需求和禁止事项。

## 操作流程

1. 明确人物在主线中的功能：推动者、阻碍者、诱因、镜像或代价承担者。
2. 定义外部目标、内在欲望、恐惧、执念和底层缺口。
3. 定义能力、资源、限制、缺陷和行动代价。
4. 建立关系网：利益关系、情感关系、秘密关系和冲突关系。
5. 设计成长弧：开局信念、中段崩塌、关键选择和最终变化。
6. 检查关键行动是否服务主线冲突或人物成长。
7. 输出人物卡和崩人设风险清单。

## 输出格式

```markdown
# 人物卡

## 基础身份
## 主线功能
## 外部目标
## 内在欲望
## 恐惧与执念
## 能力与资源
## 缺陷与代价
## 关系网
## 成长弧
## 行为逻辑
## 不可做的事
## 主线冲突贡献
```

## 质量标准

- 人物行动必须有欲望、压力、选择和代价。
- 关键人物必须能制造或解决主线冲突。
- 反派必须有可理解的收益和压力。
- 配角不能只负责解释设定或推动主角升级。

## 禁止事项

- 禁止让人物为剧情需要突然降智。
- 禁止只写标签化人设，不写行为逻辑。
- 禁止让成长弧脱离主线冲突。
- 禁止复用具体作品的人物身份组合和关系组合。

## 与其他模块的关系

- 上游：`generate-topic`、`generate-world`、`WorldBible`。
- 下游：`generate-outline`、`generate-chapter-plan`、`quality-review`。
- Agent：Chief Editor Agent、Draft Agent、Review Agent。
