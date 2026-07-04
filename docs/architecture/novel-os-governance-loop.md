# Novel OS Governance Loop

日期：2026-07-04

## 功能目标

治理闭环把 Agent Registry、Context Builder / pgvector、AgentRun / Scheduler、Audit Log、Evaluation Center、ReviewIssue / Publish Gate、ClickHouse Analytics 和 Editor-in-Chief Console 串成一条可追踪链路。

目标链路：

```text
Agent Registry
  -> Context Builder / pgvector
  -> AgentRun / Agent Scheduler
  -> Audit Log
  -> Evaluation Center
  -> ReviewIssue / Publish Gate
  -> ClickHouse Analytics
  -> Editor-in-Chief Console
```

## 当前实现

已完成：

- Agent Registry lifecycle 控制 scheduler 调度资格。
- AgentRun 记录 registry version。
- pgvector retrieval report 记录 Context Builder evidence 和 source isolation。
- AgentRun start/status 自动 best-effort 写入 Audit Log。
- EvaluationGate 阻断时可生成 ReviewIssue。
- Analytics 从 LocalStorage 投影治理事件并生成 dashboard snapshot。
- Editor-in-Chief Console 增加 `governance_loop` 摘要。

核心文件：

- `src/novel_forge/modules/agent_registry/service.py`
- `src/novel_forge/modules/audit_log/service.py`
- `src/novel_forge/modules/evaluation_center/service.py`
- `src/novel_forge/modules/pgvector_store/service.py`
- `src/novel_forge/modules/clickhouse_analytics/service.py`
- `src/novel_forge/modules/editor_chief/service.py`
- `tests/integration/test_novel_os_governance_loop.py`

## API 覆盖

- Agent Registry：`/product/agent-registry/*`
- Audit Log：`/product/audit-log/*`
- Evaluation Center：`/product/evaluation/*`
- Retrieval：`/product/os/retrieval/*`
- Analytics：`/product/analytics/*`
- Editor-in-Chief：`GET /product/editor-chief/snapshot`

## UI 覆盖

- `/agent-registry`
- `/audit-log`
- `/evaluation`
- `/retrieval`
- `/analytics`
- `/editor-chief`

## 测试方式

默认本地测试不依赖真实模型、真实 PostgreSQL、真实 pgvector online、真实 ClickHouse。

```bash
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_agent_registry \
  tests.unit.test_agent_registry_scheduler_integration \
  tests.unit.test_audit_log \
  tests.unit.test_pgvector_source_isolation \
  tests.unit.test_clickhouse_analytics \
  tests.unit.test_evaluation_center_general \
  tests.integration.test_novel_os_governance_loop
```

## 当前限制

- 没有实现 Permission Center。
- Audit Log 仍需更多模块原生接入。
- Evaluation scorer 是 deterministic local heuristic。
- ClickHouse online 是 opt-in PoC。
- pgvector online 真实迁移需要额外环境。

## 后续扩展

- Agent active promotion 必须通过 EvaluationGate。
- Publish Gate 读取 EvaluationGate 形成硬门禁。
- ClickHouse dashboard 加趋势图、SLA 和成本维度。
- Audit Trail UI 增加 trace graph。
