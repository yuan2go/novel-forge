---
name: review-issue-gate
description: Use when validation, canon conflict, source leakage, MKAOS risk, evaluation failure, platform risk, or review findings must become structured ReviewIssue records and blocking gates.
---

# Review Issue Gate

## 适用场景

- 将 MKAOS validate、canon conflict、source leakage、evaluation gate、publish gate 或 review report 输出转成 ReviewIssue。
- 判断 canonical chapter、release package、publish gate、revision loop 是否应被阻断。
- 生成 RevisionTask candidate 和 re-review criteria。

## 输入要求

- target asset、flow、severity、issue type、blocking policy、related knowledge ids、context bundle id、knowledge pack id。
- 当前 gate policy、runtime environment、resolved issue 列表和 release target。
- 证据引用，不包含受保护原文。

## Novel OS Runtime Contract

- high / critical 的 source_leakage、canon_conflict、knowledge_conflict、platform_policy_risk 必须结构化为 ReviewIssue。
- critical 默认 blocking；high 是否 blocking 由 gate policy 决定。
- blocking ReviewIssue 必须阻断 canonical draft、release package 和 publish gate。
- resolved 后才能重新通过 gate；不能通过报告文字绕过。

## 操作流程

1. 标准化 issue type、severity、blocking、target asset 和 related knowledge。
2. 为每个 issue 绑定 evidence refs、context bundle、knowledge pack、AgentRun 或 gate report。
3. 创建或更新 ReviewIssue，避免重复但保留历史。
4. 计算 GateResult：continue、revise、block 或 human_review。
5. 为可修复 issue 生成 RevisionTask candidate 和 re-review criteria。
6. 将 blocking 状态暴露给 Command Kernel、Publish Gate、Authority API/admin projection。

## 输出格式

```markdown
# Review Issue Gate Report

## Issues
- id:
- type:
- severity:
- blocking:
- target:
- related knowledge:

## Gate
- result:
- blocked flows:
- revision tasks:
- resolution criteria:
```

## 质量标准

- issue 必须可追溯到证据、资产、上下文、知识包和 gate。
- 阻断必须可被测试证明，而不是只存在报告里。
- 每个 RevisionTask 都必须有 forbidden changes 和 re-review criteria。

## 禁止事项

- 禁止把 blocking issue 只写在 markdown 报告里。
- 禁止发布或 canonical 化存在未解决 blocking issue 的资产。
- 禁止用低严重级别掩盖 source leakage、canon conflict 或平台强违规。

## 与其他模块的关系

- 上游：Quality Review、MKAOS Gate、Canon Graph、Quality Qualification、Platform Strategy。
- 下游：Command Kernel、RevisionTask、Publish Gate、Release Package、Authority API/admin projection。
- 关联 Skill：`quality-review`、`agent-loop-governance`、`platform-strategy-os`。
