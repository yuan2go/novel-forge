# AC-15 API、事件与契约

状态：`PLANNED`  
阶段：Phase 4 / Autonomous Book Runtime Closure  
前置依赖：AC-02、AC-05、AC-06、AC-14

## 1. ADR

### 背景

系统拥有 FastAPI、CLI、Workers、Web Admin、Provider callback、Outbox 和多个 Authority。若 API 同步执行长任务、模块通过任意 JSON 互调、事件无版本或数据库提交与消息发送分离，后续恢复、兼容和多 Worker 扩展会产生系统级返工。

### 决策

采用明确的 Command/Query 分离和版本化 Contract：

- Command API 接纳业务意图，返回 Operation identity；
- Query API 读取权威记录或 projection，不推进业务状态；
- 长任务异步执行，不在 HTTP request 中跑完整 Saga；
- 跨模块通信使用版本化 Command、Snapshot、Event 或 Query Port；
- PostgreSQL 状态和 Outbox 在同一事务提交；
- Event consumer 必须幂等并记录 checkpoint；
- Public contract 采用 additive compatibility，破坏性变更必须新增 version。

## 2. API 规范

### Command

示例：

```text
POST /v1/commands/books/{book_id}/start-production
POST /v1/commands/chapters/{chapter_id}/produce
POST /v1/commands/plans/{plan_id}/request-replan
```

返回：

```json
{
  "operation_id": "...",
  "status": "ADMITTED",
  "idempotency_key": "...",
  "query_url": "/v1/operations/..."
}
```

### Query

示例：

```text
GET /v1/operations/{id}
GET /v1/books/{id}/production-state
GET /v1/assets/{id}/versions
GET /v1/sagas/{id}/timeline
```

Query 不得触发隐式修复、索引重建或生产调用。

### Error Envelope

统一错误字段：code、message、retryability、operation_id、trace_id、details、安全脱敏信息。领域冲突、权限、幂等冲突和基础设施故障必须区分。

## 3. Event Envelope

```text
event_id
event_type
event_version
occurred_at
aggregate_type
aggregate_id
project_id
workspace_id
book_id
operation_id
saga_id
attempt_id
causation_id
correlation_id
payload
payload_digest
```

事件描述已发生事实，不使用命令式名称。事件不可原地修改；修正通过新事件表达。

## 4. 实施范围

- 建立 API versioning、Command/Query router 和 operation response；
- 将当前同步 run endpoints 分为 development fixture 与正式 async command；
- 建立 schema registry 和 compatibility checker；
- 建立 Outbox publisher、consumer inbox/dedup 和 replay；
- 建立 projection checkpoint、lag 和 rebuild；
- 建立 webhook/callback signature、receipt 和 conflict policy；
- 建立 OpenAPI contract tests 和 Web Admin typed client generation；
- CLI 作为 API/Application client，不直接绕过 Authority。

## 5. 代码位置

### 当前重点

- `src/novel_forge/api/app.py`
- `src/novel_forge/api/authority_app.py`
- `src/novel_forge/api/legacy_app.py`
- Authority routers
- `src/novel_forge/cli/`
- Command Kernel events/audit/outbox
- Provider callback/reconciliation modules
- `web/admin/app/shared/api.ts`

### 目标收敛

- `src/novel_forge/api/v1/commands/`
- `src/novel_forge/api/v1/queries/`
- `src/novel_forge/api/contracts/`
- `src/novel_forge/modules/event_authority/contracts.py`
- `.../outbox.py`
- `.../inbox.py`
- `.../projections.py`
- `scripts/contracts/check_schema_compatibility.py`
- `tests/contract/test_public_api_contracts.py`

### 禁止位置

- Router 直接跨多个 Repository 提交；
- GET 请求产生副作用；
- API 等待整章/整本完成；
- 未版本化 dict 作为跨模块公共契约；
- 发布事件先于数据库 commit；
- consumer 重试导致重复领域副作用。

## 6. 迁移脚本设计

数据库需支持 outbox、consumer inbox/dedup、projection checkpoints、webhook receipts 和 public contract version metadata。

脚本：

```text
scripts/migrations/inventory_api_and_event_contracts.py
scripts/migrations/backfill_event_envelopes.py
scripts/migrations/backfill_outbox_messages.py
scripts/migrations/create_consumer_checkpoints.py
scripts/migrations/quarantine_unversioned_events.py
```

历史事件无法映射时保留为 legacy audit，不进入新 consumer replay。

## 7. 实施计划

1. 枚举所有 API/CLI/Worker entrypoint 和跨模块 payload。
2. 固定 v1 Command、Query、Error 和 Event contracts。
3. 将长任务 endpoint 改为 admission + query。
4. 实现 outbox/inbox、dedup、checkpoint 和 lag projection。
5. 建立 contract schema registry 与 compatibility CI。
6. 生成前端 typed client 并移除散落 fetch shape。
7. 建立 webhook security 和 receipt reconciliation。
8. 完成 API restart、consumer replay 和 version compatibility 证明。

## 8. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Command idempotency | 重复 POST | 返回同 Operation |
| Query purity | GET | 无 write/effect |
| Async behavior | start production | 快速返回 ADMITTED |
| API auth/scope | 越权 book | 403/领域拒绝 |
| Outbox atomicity | commit 后 publisher crash | 可重放 |
| Consumer dedup | 同 event 两次 | 领域动作一次 |
| Ordering | projection 收到乱序 | checkpoint/版本策略正确 |
| Compatibility | 删除 required field | CI 失败 |
| Callback signature | 伪造 callback | 拒绝 |
| Frontend contract | API schema 变化 | typed client build 检测 |

## 9. Acceptance Gate

```text
command_query_api_separated=true
long_running_http_execution_removed=true
public_contracts_versioned=true
event_envelope_standardized=true
outbox_inbox_idempotency_verified=true
projection_checkpoint_rebuild_verified=true
callback_security_and_receipt_verified=true
api_contract_compatibility_ci_active=true
```

## 10. 风险

- CQRS 过度复杂：只分离 command admission 与 read projection，不要求独立数据库。
- Event schema 演化困难：additive 变更优先，consumer 支持声明版本范围。
- Projection 延迟影响 UI：展示 lag/checkpoint，不回退直接读多个业务表。
- CLI 使用不便：提供轮询/等待命令，但底层仍通过 Operation query。