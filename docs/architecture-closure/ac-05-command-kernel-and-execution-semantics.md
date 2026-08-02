# AC-05 Command Kernel 与统一执行语义

状态：`PLANNED`  
阶段：Phase 1 / Shared Kernel Closure  
前置依赖：AC-03、AC-04

## 1. ADR

### 背景

当前工程已具备 Operation、Saga、Attempt、Lease、Fencing Token、ExternalEffect、Receipt、Recovery 等生产架构，但仍需确认所有正式入口、Worker、Provider、外部平台和后续全书 Supervisor 都复用同一套语义。若每个模块自行实现 retry、timeout、task status 或 cancellation，恢复和幂等将不可证明。

### 决策

所有正式生产意图必须先 Admission 为 Operation；多步骤业务使用 Saga；每次不确定执行使用 Attempt；Worker 必须通过 Lease/Fence；外部副作用必须持久化 ExternalEffect 和 Receipt；超时不等于失败，无法确认结果时进入 UNKNOWN/Reconciliation。

统一状态：

```text
Operation: ADMITTED / RUNNING / SUCCEEDED / FAILED / CANCELLED / BLOCKED
Saga: PENDING / RUNNING / PAUSED / RECOVERING / SUCCEEDED / FAILED / CANCELLED
Attempt: PENDING / LEASED / RUNNING / SUCCEEDED / FAILED_CONFIRMED /
         UNKNOWN / CANCELLED / LATE_SUCCESS / LATE_FAILURE
```

不得建立第二套可推进正式状态的 task/run 状态机。

## 2. 核心契约

### OperationDefinition

必须冻结：`definition_key`、`version`、input/output schema、idempotency、retry、timeout、cancel、capability、authority、maturity、cost policy。

### Operation Admission

必须绑定：

- trusted actor/service account；
- project/workspace/book scope；
- idempotency_key；
- request_digest；
- frozen input AssetVersions；
- deadline/budget；
- definition version；
- concurrency key。

相同 idempotency key + 相同 digest 返回已有 Operation；digest 不同必须冲突。

### Saga

需要支持 root/child、step dependency、pause/resume、cancel propagation、manual intervention、reconciliation 和 compensation intent。Compensation 不等于删除历史，而是产生新的可审计动作。

### Attempt、Lease 和 Fence

- attempt_no 单调增加；
- fencing_token 单调增加；
- 过期/旧 Fence 不得提交结果；
- heartbeat 只续当前 lease；
- Worker 崩溃后由 recovery scanner 接管；
- late result 保留证据但不得覆盖新结果。

### UNKNOWN 与 Reconciliation

Provider/平台/CLI 在 timeout 或连接中断时，如果不能确定副作用是否发生，必须进入 UNKNOWN。Reconciler 通过 provider request id、receipt、query capability 或本地 process identity 确认，禁止盲目重试。

## 3. 代码位置

### 当前重点

- `src/novel_forge/modules/command_kernel/`
- `src/novel_forge/modules/command_kernel/service.py`
- `src/novel_forge/storage/authority_uow.py`
- `src/novel_forge/storage/authority_repositories.py`
- `src/novel_forge/modules/production_execution/`
- `src/novel_forge/modules/chapter_authority/`
- `src/novel_forge/modules/book_authority/`
- Worker/recovery/outbox/callback modules

### 目标收敛

- `src/novel_forge/modules/command_kernel/contracts.py`
- `.../definitions.py`
- `.../admission.py`
- `.../saga.py`
- `.../attempts.py`
- `.../leases.py`
- `.../effects.py`
- `.../reconciliation.py`
- `.../cancellation.py`
- `.../outbox.py`
- `tests/contract/test_command_kernel_semantics.py`

目录可渐进整理，但公共契约必须稳定。

### 禁止位置

- Celery/queue task status 作为正式状态；
- Provider adapter 自行重试且不创建新 Attempt；
- API 同步请求内完成长 Saga；
- Worker 无 Fence 提交；
- timeout 直接标记 confirmed failure；
- 删除失败记录以“重置”任务。

## 4. 迁移脚本设计

数据库迁移需补齐或验证：

- OperationDefinition version/hash 唯一性；
- Operation request digest/idempotency conflict；
- Saga root/child/dependency；
- Attempt/Lease 单调约束；
- Effect stable key 与 Receipt 去重；
- UNKNOWN/reconciliation 状态；
- cancellation request 与 late result evidence；
- audit/event/outbox 同事务约束。

脚本：

```text
scripts/migrations/audit_parallel_task_state_machines.py
scripts/migrations/backfill_operation_definitions.py
scripts/migrations/backfill_effect_stable_keys.py
scripts/migrations/verify_attempt_fence_monotonicity.py
scripts/migrations/quarantine_unbound_execution_records.py
```

具体 migration 版本从实施时唯一 head 分配。

## 5. 实施计划

1. 枚举所有 CLI/API/Worker/Agent/平台正式入口。
2. 建立 OperationDefinition catalog 和覆盖矩阵。
3. 将非 Kernel retry/cancel/timeout 收敛为 policy + Attempt。
4. 统一 Effect stable key、Receipt 和 UNKNOWN reconciliation。
5. 将 Book/Chapter/Follow-up 调度映射到 root/child Saga。
6. 建立 recovery scanner、deadline scanner 和 outbox worker 的统一契约。
7. 清理或降级 Legacy task state 为只读 projection。
8. 加入故障注入和模型检查。

## 6. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Idempotency | 同 key/同 digest | 返回同 Operation |
| Idempotency conflict | 同 key/不同 digest | 明确冲突 |
| Attempt monotonic | 并发创建 Attempt | attempt_no 唯一单调 |
| Fence | 旧 Worker 提交结果 | 拒绝并记录 stale evidence |
| Lease expiry | Worker 崩溃 | 新 Worker 可恢复 |
| UNKNOWN | provider timeout | 不盲重试，进入 reconcile |
| Duplicate receipt | 相同 effect receipt 重放 | 幂等接受 |
| Receipt conflict | stable key 相同、内容不同 | 阻塞并审计 |
| Cancel race | cancel 与 success 并发 | 状态符合冻结策略，late evidence 保留 |
| DB restart | 运行中重启 PostgreSQL/Worker | 可从 Authority 恢复 |
| Outbox | commit 后 publisher 崩溃 | 重放但不重复业务副作用 |
| Definition drift | 同 version 内容变化 | 启动/注册失败 |

## 7. Acceptance Gate

```text
operation_definition_catalog_complete=true
production_entrypoints_operation_bound=true
single_attempt_lease_fence_model=true
external_effect_receipt_model_complete=true
unknown_reconciliation_verified=true
cancel_late_result_semantics_verified=true
outbox_atomicity_verified=true
parallel_production_state_machines_zero=true
```

## 8. 风险与控制

- Kernel 过度通用：只承载执行语义，不承载小说领域决策。
- 状态过多：状态必须对应可恢复业务事实，不增加 UI 展示型状态。
- Compensation 被误解为回滚数据库：使用新 Operation 纠正外部世界。
- Worker吞吐下降：通过批量领取、连接池和短事务优化，不绕过 Fence。