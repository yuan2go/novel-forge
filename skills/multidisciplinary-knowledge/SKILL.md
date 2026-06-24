---
name: multidisciplinary-knowledge
description: Use when transforming professional or multidisciplinary knowledge into story-safe credibility rules, conflict generators, review checks, and project constraints without turning fiction into exposition or unsafe advice.
---

# Multidisciplinary Knowledge

## 适用场景

- 解析专业书籍、学科资料、行业材料或多学科知识。
- 需要把知识转成小说可信度、冲突机制、人物动机或世界规则。
- 审稿时需要检查心理、逻辑、经济、政治、社会、法律、军事、历史或技术可信度。

## 输入要求

- 来源、学科、可信度等级、适用范围和禁用范围。
- 当前题材、世界观、人物、大纲或章节目标。
- 安全边界：不得输出现实高风险操作建议，不得让知识直接进入正文说教。

## 操作流程

1. 标记知识来源、学科、可信度等级和适用题材。
2. 提取核心概念、约束条件、因果规则和常见误用。
3. 转译为故事功能：可信度规则、冲突生成器、人物行为约束或审稿检查。
4. 删除不相关细节、现实操作步骤和高风险建议。
5. 标记哪些内容只能做审稿检查，不能进入正文。
6. 输出 KnowledgeCard 候选或项目约束。
7. 交给 `quality-review` 检查是否压过读者吸引力。

## 输出格式

```markdown
# Multidisciplinary Knowledge Card

## 来源与学科
## 核心概念
## 可信度等级
## 故事功能
## 可生成的冲突
## 人物/世界约束
## 审稿检查项
## 禁止进入正文的内容
## 安全与合规边界
```

## 质量标准

- 知识必须转成故事功能，而不是资料摘录。
- 每条知识必须说明服务哪个剧情问题。
- 高风险现实操作必须删除或抽象。
- 多学科知识只能增强可信度，不能替代爽点和冲突。

## 禁止事项

- 禁止把小说写成论文。
- 禁止输出可执行的现实伤害、违法或高风险操作。
- 禁止未经转译直接塞入正文。
- 禁止让专业合理性破坏追读和情绪奖励。

## 与其他模块的关系

- 上游：SourceDocument、CleanedText、外部专业资料摘要。
- 下游：KnowledgeCard、WorldBible、CharacterCard、ReviewReport。
- Agent：Knowledge Agent、Review Agent、Chief Editor Agent。
