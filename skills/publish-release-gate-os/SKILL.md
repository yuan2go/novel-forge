---
name: publish-release-gate-os
description: Use when preparing, reviewing, or blocking a Novel Forge release package, publish gate report, platform publish plan, title/summary/hook/schedule, chapter finalization, or post-publish invalidation/resume workflow.
---

# Publish Release Gate OS

## 适用场景

- 检查 DraftChapter、revised draft、canonical chapter 或 release package 是否可以发布。
- 生成 publish gate report、platform publish plan、title/summary/hook/schedule 检查和 release readiness。
- 审计发布前的 ReviewIssue、source isolation、canon continuity、provider/cost trace 和 rollback/resume 证据。

## 输入要求

- release target、platform profile、canonical candidate、ReviewIssue 列表、GateResult、ContextBundle、KnowledgePack。
- Canon continuity report、quality review、provider runtime evidence、model_call_log、cost_ledger。
- title、summary、opening hook、chapter hook、schedule、publish adapter 和 rollback plan。

## Novel OS Runtime Contract

- ReleasePackage 必须引用 accepted asset versions、context_bundle_id、knowledge_pack_id、gate results、model_call_log 和 cost_ledger。
- 未解决 blocking ReviewIssue、canon conflict、source leakage、provider hard-stop 或 platform policy risk 必须阻断发布。
- 发布 gate 只能接受 schema-backed artifacts，不能只接受聊天文本或未验证 Markdown。
- 发布后 invalidation、resume 和 feedback backflow 必须创建新版本或事件记录，不得覆盖历史。

## 操作流程

1. 收集候选 release package 和全部上游 gate evidence。
2. 检查 source isolation、canon continuity、quality review、platform fit、provider runtime 和 cost ledger。
3. 检查 title、summary、chapter hook、schedule 和平台发布适配是否匹配 release target。
4. 将风险归类为 block、revise、warn、human_review 或 accept。
5. 生成 PublishGateReport、ReleasePackage decision、rollback/resume instruction。
6. 若发布后反馈需要回流，生成 FeedbackBackflow 和 MKAOS advisory learning 建议。

## 输出格式

```markdown
# Publish Release Gate Report

## Release
- target:
- candidate:
- platform:
- schedule:

## Evidence
- context bundle:
- knowledge pack:
- review issues:
- canon gate:
- provider/cost:

## Publishing Checks
- title:
- summary:
- hook:
- platform fit:

## Decision
- result:
- blockers:
- warnings:
- rollback/resume:
```

## 质量标准

- 任何 accepted release 都必须能从 release package 反查上游资产、gate 和 trace。
- blocking issue 必须阻断 canonical release 和 publish package。
- 发布建议必须区分平台优化、质量修订和合规/原创阻断。

## 禁止事项

- 禁止发布未审稿、未过 source isolation 或存在 blocking issue 的内容。
- 禁止用手写发布摘要替代 release package。
- 禁止发布后直接覆盖历史章节或 gate result。
- 禁止为平台表现牺牲版权边界、正典一致性或 provider hard-stop。

## 与其他模块的关系

- 上游：Draft/Revision、ReviewIssue Gate、Canon Graph、Context Builder、Platform Strategy、Provider Runtime Policy。
- 下游：Publishing log、Feedback Backflow、Authority API/admin projection、MKAOS learning、Resume/Invalidation。
- 关联 Skill：`platform-strategy-os`、`review-issue-gate`、`canon-continuity-graph`、`provider-runtime-policy`。
