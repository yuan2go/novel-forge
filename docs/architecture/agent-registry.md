# Agent Registry

日期：2026-07-04

## 功能目标

Agent Registry 将 Novel OS 中分散的 `AGENT_RUNTIME_PROFILES`、Agent operation contract、AgentRun 和 Evaluation 绑定收敛成统一 Agent 元数据层。它不是 Permission Center，不新增 RBAC、用户权限、组织权限或 SaaS 权限体系。

## 当前实现

核心模块：

- `src/novel_forge/modules/agent_registry/service.py`
- `src/novel_forge/api/routers/agent_registry.py`
- `src/novel_forge/modules/agent_scheduler/service.py`
- `src/novel_forge/modules/agent_runs/service.py`
- `web/admin/app/features/governance/GovernancePages.tsx`

能力：

- 从 `AGENT_RUNTIME_PROFILES` 同步默认 Agent Registry。
- 支持 lifecycle：`draft -> experimental -> active -> deprecated -> archived`。
- `active` 才允许 scheduler 生产调度。
- AgentRun metadata 记录 `agent_registry_entry_id`、`agent_registry_entry_path`、`agent_registry_version`、`agent_lifecycle_state`。
- Agent Scheduler 执行本地 service operation 前读取 registry；非 active agent fail closed。
- Evaluation Center 可通过 `agent_evaluation_binding` 绑定 Agent。

## 数据资产

- `agent_registry_entry`
- `agent_version`
- `agent_capability`
- `agent_lifecycle_event`
- `agent_evaluation_binding`
- `agent_registry_snapshot`

所有资产默认写入 `data/runs/`，符合 LocalStorage 边界。

## API

- `GET /product/agent-registry/entries`
- `POST /product/agent-registry/sync-runtime-profiles`
- `POST /product/agent-registry/entry`
- `PATCH /product/agent-registry/entry/{agent_id}`
- `POST /product/agent-registry/version`
- `POST /product/agent-registry/lifecycle`
- `POST /product/agent-registry/capability`
- `POST /product/agent-registry/evaluation-binding`
- `GET /product/agent-registry/snapshot`
- `POST /product/agent-registry/resolve`
- `GET /product/agent-registry/coverage`

## UI

- `/agent-registry`

页面展示 entry、生命周期、调度资格、operation coverage 和 evaluation binding 数量，并支持同步 runtime profiles。

## 测试

- `tests/unit/test_agent_registry.py`
- `tests/unit/test_agent_registry_scheduler_integration.py`
- `tests/integration/test_novel_os_governance_loop.py`

## AgentRun Event Policy

AgentRun 默认使用 `agent_event_policy.mode=full`，保持历史行为：创建 run、checkpoint、状态变化都会写入 `agent_event` 和对应 trace span。这个模式适用于生产治理、失败恢复、dead-letter、gate、budget、人工审批、provider hard-stop、发布、回滚和任何需要完整事件审计的路径。

批量章节生产或开发期 runtime-growth 回归可以显式使用 `success_summary`：

```json
{
  "runtime_policy": {
    "agent_event_policy": {
      "mode": "success_summary"
    }
  }
}
```

`success_summary` 只压缩自动成功路径事件：

- `agent_run.started`
- `agent_run.checkpoint`
- `agent_run.succeeded`

被压缩的事件不会创建 `agent_event` 资产和 event trace span，但会写回 AgentRun 的 `agent_event_summary`，并在 Agent Center 的 summary、evidence drawer 和 Agent Event Summary 表格中可见。

不能压缩的证据：

- `failed` / `dead_letter` / `cancelled` 状态事件；
- scheduler dispatch / retry / repair 直接事件；
- checkpoint 资产本身；
- gate / budget / audit / cost / model-call 证据；
- production governance hard-stop 证据。

使用规则：

- 默认写 full，只有明确需要降低成功路径写放大时才使用 `success_summary`。
- workflow 作者应通过 `runtime_policy.agent_event_policy` 传入，不要绕过 AgentRun service。
- 若某条路径会触发 provider、发布、外部 adapter、人工审批或 dead-letter repair，保持 full，除非已有单独证据证明压缩不会影响恢复。
- 修改该策略后运行 `make runtime-growth-regression`；不要用它替代最终章节验收。

## 当前限制

- Registry 只治理 Agent 元数据与调度资格，不做 Permission Center。
- Agent version 目前是本地资产版本，不是远程发布版本。
- Agent Center UI 仍可继续深化 operation coverage 与 rollback 可视化。

## 后续扩展

- Agent 上线前强制 evaluation gate。
- Agent prompt/model binding 的可视化 diff。
- Agent operation coverage 与 ClickHouse SLA 指标合并。
