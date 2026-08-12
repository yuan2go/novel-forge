---
name: worldbuilding
description: Use when designing or reviewing world rules, power systems, resource systems, class structures, organizations, geography, history, taboos, and costs so each setting produces conflict, limits, or story hooks.
---

# Worldbuilding

## Novel OS Runtime Contract

- 需要进入生产链路的输出必须落到 schema-backed asset，而不是只停留在对话文本。
- 产物必须保留 `project_id`、输入引用、来源边界、质量状态；涉及 Agent/Workflow 时必须保留 `trace_id` 或 handoff 依据。
- 生成、审稿、修订、发布、复盘相关上下文必须通过 Context Builder / Knowledge Pack / ReviewIssue / GateResult 的现有边界。
- 禁止 raw source text、参考作品表达、`source_chunk.raw_text` 或未抽象材料进入 prose、publish、recap 和 feedback backflow。
- Markdown 输出格式只作为 operator handoff；写入工程时必须映射到对应资产 schema、测试或报告路径。

## 适用场景

- 创建 WorldBible、世界模板或项目世界分支。
- 审查世界观是否能支撑长期冲突。
- 大纲或正文中出现规则失效、资源无代价或设定堆砌问题。
- 定义“规则是什么”；长期系统性后果、制度适应和故事机会交给 `world-consequence-modeling`，不在本 Skill 重复推演。

## 输入要求

- TopicSeed、目标读者、核心爽点和主线冲突。
- 已有知识卡、素材卡和原创风险边界。
- 主角切入口、长期连载目标和类型约束。

## 操作流程

1. 定义世界第一规则和不可修改边界。
2. 设计力量体系、资源体系、代价体系和限制条件。
3. 设计阶层结构、组织势力、法律规则和权力来源。
4. 设计地理空间、历史背景、禁忌、灾难或系统缺陷。
5. 为每个设定标注剧情功能：冲突、限制、钩子、代价或反转条件。
6. 检查是否存在设定过重、资源无主、权力无成本或规则只为剧情服务。
7. 输出世界观卡和风险检查项。

## 输出格式

```markdown
# 世界观设计

## 世界第一规则
## 力量体系
## 资源体系
## 代价机制
## 阶层结构
## 组织势力
## 法律与禁忌
## 地理空间
## 历史背景
## 可产生的冲突
## 可产生的章节钩子
## 不可修改规则
## 风险检查
```

## 质量标准

- 每个核心设定必须产生冲突、限制、代价或钩子。
- 稀缺资源必须有来源、控制者、分配方式和争夺成本。
- 权力结构必须有合法性、维护成本和反抗成本。
- 世界规则必须约束主角，不能只服务主角开挂。

## 禁止事项

- 禁止为炫设定而堆百科。
- 禁止让强资源凭空无限供应。
- 禁止复制具体作品的独特世界观组合。
- 禁止让世界规则在主角需要时失效。
- 禁止把 provider 推演出的 consequence candidate 直接写成 Accepted Canon。

## 与其他模块的关系

- 上游：`TopicSeed`、`KnowledgeCard`、`MaterialCard`。
- 下游：`CharacterCard`、`Outline`、`ChapterPlan`、`quality-review`、`world-consequence-modeling`。
- Agent：Chief Editor Agent、Draft Agent、Review Agent。
