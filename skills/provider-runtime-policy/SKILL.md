---
name: provider-runtime-policy
description: Use when designing, reviewing, or debugging model provider routing, runtime profiles, model hard-stop behavior, fallback approval, timeout, token/cost budgets, model_call_log, cost_ledger, or provider-neutral execution in Novel Forge.
---

# Provider Runtime Policy

## 适用场景

- 设计或审计模型 provider、runtime profile、model routing、fallback 和 hard-stop。
- 检查 `model_call_log`、`cost_ledger`、token budget、timeout、SLA 和 retry 记录。
- 判断 Claude、OpenAI、local/mock provider 或兼容 provider 是否能进入生产链路。

## 输入要求

- task、flow、runtime environment、provider、model、runtime profile 和 provider policy。
- token budget、cost budget、timeout、retry、fallback approval、trace_id 和 workspace/project id。
- `model_call_log`、`cost_ledger`、AgentRun、GateResult、ReviewIssue 或测试证据。

## Novel OS Runtime Contract

- 新调用保留 Provider/模型能力、实际上下文容量、账号及真实付费授权检查；已保存结果的读取不得重新要求新调用资格。
- 用量、耗时、失败、取消与 UNKNOWN 如实留证。纯生成不因自设累计 Token/调用/期限/恢复次数锁死；暂时故障退避，认证、配置和重复无进展明确报错。
- fallback 不能 silent；必须记录原 provider、失败原因、批准主体、替代 provider、成本影响和质量 gate。
- mock / deterministic provider 只能标记为 fixture、compat 或 test，不得伪装为 production model coverage。

## 操作流程

1. 识别目标 flow 的 provider 需求、预算边界、上下文大小和质量门槛。
2. 检查 runtime profile 是否声明 provider、model、timeout、retry、fallback 和 cost policy。
3. 检查 model call 是否写入 trace、model_call_log、cost_ledger、input/output token 和 stop reason。
4. 判断失败是否应 retry、fallback、human_review、block 或 dead_letter。
5. 将 provider 风险转成 GateResult、ReviewIssue 或 AgentRun recovery instruction。
6. 输出 provider runtime policy report 和测试/证据缺口。

## 输出格式

```markdown
# Provider Runtime Policy Report

## Contract
- flow:
- provider:
- model:
- runtime profile:
- budget:

## Calls
- model_call_log:
- cost_ledger:
- stop/hard-stop:

## Fallback
- allowed:
- approval:
- audit refs:

## Gate
- result:
- blocking issues:
- tests:
```

## 质量标准

- 每个生产 model call 都能反查 provider、model、prompt/context source、token、cost 和 trace。
- 原始结果和来源可核验的正文候选先留存；执行终态、核算、结构、选稿及正式事实提交分别判断。候选保存不产生隐式发布或接纳权限。
- fallback 结果必须重新进入 schema validation、quality gate 和 source isolation gate。

## 禁止事项

- 禁止 silent fallback。
- 禁止把 mock provider 结果标记为真实生产输出。
- 禁止因 provider 成功返回就跳过 schema、ReviewIssue、ContextBundle 或 Publish Gate。
- 禁止在报告、日志或配置中写入 API key、token、cookie 或 secret。

## 与其他模块的关系

- 上游：Runtime Profile、AgentRun、ContextBundle、provider adapter、model_call_log、cost_ledger。
- 下游：Quality Qualification、ReviewIssue Gate、Agent Runtime、Publish Gate、Authority API/admin projection。
- 关联 Skill：`agent-loop-governance`、`review-issue-gate`、`novel-os-engineering-audit`。
