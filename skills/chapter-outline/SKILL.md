---
name: chapter-outline
description: Use when creating or reviewing chapter plans so every chapter has a goal, cast, scene list, conflict, information gain, payoff, suspense, reversal, ending hook, and next-chapter handoff.
---

# Chapter Outline

## 适用场景

- 将全书大纲或卷纲拆成可写作的章节细纲。
- 正文生成前检查章节是否具备最小商业单元。
- 审稿时发现章节缺冲突、缺爽点、缺钩子，需要退回细纲。

## 输入要求

- Outline、CharacterCard、WorldBible、前文上下文和本章位置。
- 本章必须推进的信息、必须设置或回收的伏笔。
- 禁止事项和原创风险边界。

## 操作流程

1. 明确本章目标和必须完成的剧情功能。
2. 列出出场人物、人物目标、冲突关系和场景。
3. 设计本章冲突、阻力、行动、代价和结果。
4. 安排信息增量、爽点、悬念、反转和情绪变化。
5. 设计开头钩子、小钩子、结尾钩子和下一章承接点。
6. 检查章节最小商业单元：冲突、推进、奖励、代价、钩子。
7. 输出可交给正文模型执行的细纲。

## 输出格式

```markdown
# 第 N 章细纲

## 本章目标
## 出场人物
## 场景列表
## 本章冲突
## 信息增量
## 读者爽点
## 悬念与反转
## 代价
## 开头钩子
## 结尾钩子
## 下一章承接点
## 章节最小商业单元检查
```

## 质量标准

- 每章必须有冲突、推进、奖励、代价和钩子。
- 每个场景必须有目标、阻力、行动、信息增量和情绪变化。
- 结尾钩子必须制造下一章阅读理由。
- 细纲必须足够具体，能约束 `prose-generation` 不脱纲。

## 禁止事项

- 禁止用“铺垫一章”替代章节功能。
- 禁止只有设定说明，没有人物行动。
- 禁止为了反转牺牲因果链。
- 禁止绕过细纲直接生成正文。

## 与其他模块的关系

- 上游：`long-outline`、`character-design`、`worldbuilding`。
- 下游：`prose-generation`、`quality-review`、`DraftChapter`。
- Agent：Draft Agent、Review Agent、Quality Agent。
