# OS Envelope Design

生成时间：2026-07-03

## 1. 定位

OS Envelope 是 Novel OS production mutation 和模型/上下文路径的运行契约。Phase 2 先把 MKAOS 关键路径纳入 envelope，不替换已有 `runtime_policy`、`trace_span`、`gate_result`、`model_call_log` 和 `cost_ledger`，而是在 local-first 架构中提供一个稳定的 envelope 字段和 enforcement seam。

## 2. 标准字段

| 字段 | 说明 |
| -- | -- |
| `envelope_id` | envelope 唯一 id。 |
| `project_id` | 项目作用域。production 必填。 |
| `task_type` | 任务类型或 flow。production 必填。 |
| `asset_type` | 目标资产类型。production 必填。 |
| `actor_type` | 发起者类型，如 `agent`、`operator`、`mkaos_service`。production 必填。 |
| `actor_id` | 发起者 id。 |
| `source` | 来源模块，MKAOS 路径为 `mkaos`。production 必填。 |
| `version` | envelope schema 版本。 |
| `context_bundle_id` | 后续 Context Builder 统一入口使用。 |
| `trace_id` | trace id。production 必填。 |
| `provider` | 模型 provider，非模型 mutation 可空。 |
| `model` | 模型名，非模型 mutation 可空。 |
| `cost_ledger` | 成本账本引用或摘要。 |
| `token_budget` | token/知识预算。 |
| `source_policy` | source/RAG/copyright policy。production 必填。 |
| `environment` | `production` / `dev` / `test` / `sample` / `compat`。 |
| `bypass_reason` | 非 production 显式绕过说明。 |
| `created_at` | 创建时间。 |

## 3. Enforcement 规则

1. `environment=production` 且缺少 envelope 时 fail closed。
2. `environment=production` 且缺少 `project_id/task_type/asset_type/actor_type/source/trace_id/source_policy/environment` 时 fail closed。
3. `dev/test/sample/compat` 可运行；若提供 `bypass_reason`，资产 metadata 记录 bypass envelope。
4. 传入 envelope 或 production enforcement 时写入 `trace_span`，`span_type=os_envelope`。
5. 资产 metadata 记录 `os_envelope`、`os_envelope_id`、`trace_id`、`source_policy`、`environment`、`bypass_reason`。

## 4. MKAOS 接入范围

已接入：

```text
source import
knowledge create/update
usage binding create/update
rule card create
template card create
knowledge pack build
usage event write
review feedback
weight update
query knowledge
convert assets
convert rules
```

## 5. API 响应

新增 Query / Convert API 使用标准响应：

```json
{
  "success": true,
  "request_id": "os_envelope_xxx",
  "trace_id": "trace-id",
  "envelope": {},
  "data": {},
  "error": {}
}
```

现有 MKAOS CRUD API 保持兼容返回；但当 payload 标记 `environment=production` 时，底层 service 会强制要求 envelope。

## 6. 后续接入

Phase 4 会把 `context_bundle_id` 变为实际 Context Builder 统一入口字段。Phase 5 会让 ReviewIssue blocking gate 使用同一 envelope/trace。Phase 10 会让 release package/publish gate 在 production 模式下强制校验 envelope 与 blocking issue。
