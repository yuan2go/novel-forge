---
name: agent-loop-governance
description: Use when converting production workflows into auditable AgentRun and LoopRun execution with context contracts, budget limits, checkpoints, stop conditions, review-revision loops, rollback rehearsal, and dead-letter recovery.
---

# Agent Loop Governance

## 适用场景

- 将 analysis、outline、chapter plan、draft、review、revision、recap、publish、feedback 等操作纳入 Agent Center 或 Loop Kernel。
- 设计 review -> revision -> re-review -> publish gate 的标准 LoopRun。
- 审计 Agent operation coverage、hard-stop、checkpoint、dead letter、rollback rehearsal。

## 输入要求

- operation、Agent profile、ContextBundle contract、runtime policy、budget、stop conditions、gate policy。
- 相关 ReviewIssue、RevisionTask、EvaluationResult、PublishGateReport、AuditLog 和 rollback evidence。
- 本次运行的 `trace_id`、project/workspace id 和环境。

## Novel OS Runtime Contract

- 生产 AgentRun 必须记录 `context_bundle_id`、`knowledge_pack_id`、model/provider、cost/token budget、gate result 和 registry metadata。
- LoopRun 必须有 max_steps、max_tokens、max_cost、max_duration 和明确 stop condition。
- provider timeout、cancel、budget exceeded、blocking issue、human required 都必须 hard-stop 并记录。
- compat operation 必须显式标记，不能伪装成 production coverage。

## 操作流程

1. 识别目标 workflow 的 Agent operation、输入资产、输出资产和关键 gates。
2. 生成 LoopRun / AgentRun 计划，包括 budget、checkpoint、rollback 和 stop condition。
3. 为每步绑定 ContextBundle、ReviewIssue、EvaluationGate、MKAOS Gate 和 AuditLog。
4. 执行或设计状态迁移：planned、running、checkpointed、succeeded、failed、waiting_human、dead_letter。
5. 处理阻断：创建 recovery instruction、dead letter repair 或 rollback rehearsal。
6. 输出 coverage report，标记 production、compat、bypass forbidden 和 missing contract。

## 输出格式

```markdown
# Agent Loop Governance Report

## Coverage
- operation:
- agent:
- context contract:
- gate:
- status:

## Loop
- steps:
- budget:
- stop condition:
- checkpoints:

## Recovery
- dead letters:
- rollback rehearsal:
- human approval:
```

## 质量标准

- 每个主链 step 都能从 trace_id 查到 AgentRun、ContextBundle、GateResult 和 AuditLog。
- blocking issue、budget exceeded、provider hard-stop 都有可测试证明。
- Loop 不修改历史 run；rerun 必须创建新 run/version。

## 禁止事项

- 禁止 Agent 绕过 Context Builder 或 MKAOS contract。
- 禁止 provider failure silent fallback。
- 禁止通过 chat memory 代替 schema-backed checkpoint 或 handoff。

## 与其他模块的关系

- 上游：Agent Registry、Context Builder、Runtime Policy、ReviewIssue、Evaluation Center。
- 下游：Agent Center UI、Loop Kernel、Publish Gate、Longform Recap、Audit Log。
- 关联 Skill：`context-builder-source-isolation`、`review-issue-gate`、`novel-os-engineering-audit`。
