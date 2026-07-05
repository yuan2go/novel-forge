---
name: platform-strategy-os
description: Use when adapting topic, outline, chapter plan, draft, review, publish, or feedback strategy to platform-specific production logic such as Qidian, Fanqie, Feilu, Jinjiang, Zhihu Yanxuan, or publishing-oriented releases.
---

# Platform Strategy OS

## 适用场景

- 为同一题材生成不同平台的大纲、节奏、开篇、章节钩子、留存风险和发布策略。
- 构建或审计 PlatformProfile、PlatformRhythmRule、OpeningGate、ChapterGate、RetentionRisk、PublishAdapter、FeedbackBackflow。
- 将读者反馈、平台表现和审稿结果回流到 MKAOS 权重、审稿规则和节奏模板。

## 输入要求

- 目标平台、题材、读者预期、章节阶段、商业目标、平台风险和 release target。
- 当前 outline、chapter plan、ContextBundle、MKAOS pack、ReviewIssue、FeedbackInsight 和 platform metrics。
- 不同平台的节奏边界、语言边界、合规边界和 source policy。

## Novel OS Runtime Contract

- 平台策略必须是结构化资产或 gate policy，不能只作为提示词语气要求。
- 平台 gate 输出必须能进入 ReviewIssue、Publish Gate、Evaluation Center 和 Editor-in-Chief Console。
- 平台适配不得覆盖 canon facts、人物状态、source isolation 或 originality boundary。
- 真实平台 API 和外部数据导入必须 opt-in；默认使用本地 fixture 或 deterministic metrics。

## 操作流程

1. 选择平台画像：起点、番茄、飞卢、晋江、知乎盐选、微信读书/出版向或自定义。
2. 将平台要求转成节奏规则、开篇门禁、章节门禁、留存风险和发布适配器。
3. 对 topic、outline、chapter plan、draft 或 release package 运行 platform fit 检查。
4. 将平台风险转为 ReviewIssue、RevisionTask 或 PublishGate blocking/warning。
5. 读取反馈回流，生成 platform-specific knowledge/template/rule weight 建议。
6. 输出 next-10-chapter strategy 或 release recommendation。

## 输出格式

```markdown
# Platform Strategy Report

## Profile
- platform:
- reader promise:
- rhythm:

## Gates
- opening:
- chapter:
- retention risk:
- publish adapter:

## Backflow
- feedback signals:
- MKAOS weight suggestions:
- review rule changes:
```

## 质量标准

- 平台差异必须体现在生产逻辑上：节奏、冲突密度、钩子、人物关系、留存或主题表达。
- Gate 必须可测试，并能阻断 publish/release 的强风险。
- Feedback backflow 必须可追踪到知识、模板、规则或平台策略。

## 禁止事项

- 禁止只把平台适配理解成“改文风”。
- 禁止为平台留存牺牲正典一致性、版权边界或 source isolation。
- 禁止引入登录、会员、计费或 SaaS 权限逻辑。

## 与其他模块的关系

- 上游：Topic、Outline、ChapterPlan、Feedback、Evaluation Center、MKAOS。
- 下游：ReviewIssue、Publish Gate、Editor-in-Chief Console、Platform Feedback Backflow。
- 关联 Skill：`mkaos-knowledge-asset-os`、`review-issue-gate`、`quality-review`。
