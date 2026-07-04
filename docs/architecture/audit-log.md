# Audit Log / Audit Trail

日期：2026-07-04

## 功能目标

Audit Log 是治理级审计层，用于回答谁、何时、对什么资产、经过哪些 Agent/Model/Tool/Gate、是否失败、是否阻断、是否可回滚。它不替代 TraceSpan、GateResult、ModelCallLog、CostLedger 或 AgentEvent，而是引用这些证据。

## 当前实现

核心模块：

- `src/novel_forge/modules/audit_log/service.py`
- `src/novel_forge/api/routers/audit_log.py`
- `src/novel_forge/modules/agent_runs/service.py`
- `web/admin/app/features/governance/GovernancePages.tsx`

已接入：

- AgentRun start/status/succeed/fail 以 best-effort 方式记录 audit event。
- 手动 API 可记录 MKAOS、Evaluation、Publish Gate、Rollback、pgvector、ClickHouse 等治理事件。
- 支持 `project_id`、`trace_id`、`event_type` 查询。
- 支持 trail report 和 source-isolated export package。

## 数据资产

- `audit_log`
- `audit_trail_report`
- `audit_export_package`

导出包会移除 `raw_text` 并替换 `source_chunk.raw_text` 字符串引用。

## API

- `GET /product/audit-log/events`
- `POST /product/audit-log/record`
- `GET /product/audit-log/trail`
- `POST /product/audit-log/trail-report`
- `POST /product/audit-log/export-package`

## UI

- `/audit-log`

页面展示最近 event、trace、状态、actor 和 evidence trail，可生成 source-isolated export package。

## 测试

- `tests/unit/test_audit_log.py`
- `tests/integration/test_novel_os_governance_loop.py`

## 当前限制

- AgentRun 已自动接入，其他模块可继续逐步显式记录 audit event。
- Audit Log 不做用户身份认证和组织权限。
- Export package 当前是本地 JSON asset，不做外部归档上传。

## 后续扩展

- Context Builder、Model Gateway、Publish Gate、Rollback 模块内增加更细粒度 audit event。
- Audit Trail UI 增加 trace graph 和证据抽屉。
