# AC-16 部署、运维与安全

状态：`PLANNED`  
阶段：Phase 4 / Autonomous Book Runtime Closure  
前置依赖：AC-00、AC-03、AC-05、AC-12、AC-15

## 1. ADR

### 背景

当前默认 Compose 和 Dockerfile 仍偏向 Legacy/local-first 运行方式，Authority Worker 虽存在代码，但未形成完整部署拓扑；Authority `/health` 不能仅静态返回 ready；生产身份目前也不能依赖默认 local operator 和 wildcard scope。架构闭合必须证明系统能以 Authority-only 方式运行、恢复和审计。

### 决策

建立明确分离的 Development、Validation、Production 配置。Production 必须：

- `storage_authority=postgresql`；
- `legacy_write_enabled=false`；
- `silent_fallback=false`；
- 使用可信身份、Service Account、Project/Book Scope 和 RBAC；
- 所有 Worker 具备 manifest、health projection、lease/recovery 和 deployment unit；
- 所有秘密通过 Secret Reference 解析；
- PostgreSQL 具备池化、超时、备份、PITR 和 migration rehearsal。

## 2. Authority-only 拓扑

建议部署单元：

```text
Authority API
Book Supervisor Worker
Planning Worker
Chapter Authority Worker
Longform Reducer Worker
Quality/Eval Worker
Provider Callback Worker
Reconciliation Worker
Outbox Worker
Source Worker
MKAOS Worker
Publishing Worker
```

基础设施：PostgreSQL、Object Store、Queue、可选 Redis、Vector Store、Observability、Secret Manager。

逻辑 Worker 可先共用进程镜像，但必须拥有独立 capability、queue、health 和扩缩容配置。

## 3. 健康与可观测性

### Health

- Liveness：进程是否存活；
- Readiness：数据库、migration compatibility、必要 object store/queue 可用；
- Dependency：Provider qualification、Secret resolution、callback endpoint；
- Worker heartbeat：last seen、current attempt、lease；
- Operational lag：outbox、queue、projection、reconciliation backlog。

### Observability

统一 trace/correlation：API request → Operation → Saga → Attempt → Effect → Receipt → Asset Commit → Event。日志必须结构化并脱敏。

核心指标：admission rate、attempt latency、retry/unknown rate、stale fence、outbox lag、cost burn、context size、gate block、book progress、worker recovery。

## 4. PostgreSQL 运维

必须定义：

- connection pool 与每 Worker 上限；
- connect/statement/lock/idle transaction timeout；
- transaction isolation policy；
- deadlock/serialization retry；
- migration lock 和 rollout policy；
- backup、restore、PITR、retention；
- index/partition/slow query review；
- schema compatibility 与 zero/low-downtime rollout。

当前每 UoW 直接创建连接的实现需要评估并迁入受控 pool。

## 5. 安全

### 身份

- OIDC/JWT 用于用户；
- Service Account 用于 Worker；
- callback 使用签名/mTLS/allowlist；
- actor 不从任意请求字段信任。

### 授权

RBAC + Scope：execute/query/cancel/recover/approve/publish/admin 分离。默认拒绝，不使用生产 wildcard `*`。

### Secret

manifest、日志、事件和数据库不得保存明文 secret。只保存 `auth_profile_ref`、`credential_scope`、`secret_version_ref`。

## 6. 代码位置

### 当前重点

- `docker-compose.yml`
- `Dockerfile`
- `.env.example`
- `src/novel_forge/settings.py`
- `src/novel_forge/api/authority_dependencies.py`
- `src/novel_forge/api/authority_app.py`
- `src/novel_forge/modules/authority_security/`
- `src/novel_forge/storage/authority_uow.py`
- `src/novel_forge/workers/`
- `.github/workflows/core-os-ci.yml`

### 目标新增

- `deploy/compose/authority-only.yml`
- `deploy/config/development.env.example`
- `deploy/config/validation.env.example`
- `deploy/config/production.env.example`
- `src/novel_forge/observability/`
- `src/novel_forge/security/identity.py`
- `.../rbac.py`、`service_accounts.py`、`secrets.py`
- `src/novel_forge/storage/postgres/pool.py`
- `scripts/ops/backup_restore_rehearsal.py`
- `tests/acceptance/test_authority_only_deployment.py`

## 7. 迁移脚本设计

数据库 migration 可能包括 service accounts、roles/permissions、scope grants、worker health、deployment/build identity、operational checkpoints。凭据本身不得进入 migration。

运维脚本：

```text
scripts/ops/check_production_configuration.py
scripts/ops/check_migration_compatibility.py
scripts/ops/backup_postgres.sh
scripts/ops/restore_postgres.sh
scripts/ops/verify_pitr.py
scripts/ops/check_worker_health.py
scripts/ops/check_outbox_and_reconciliation_lag.py
```

## 8. 实施计划

1. 建立 Authority-only compose 和完整 env schema。
2. 为所有 Worker 建 manifest、entrypoint、queue 和 health。
3. 引入 PostgreSQL connection pool 与 timeout policy。
4. 实现真实 readiness/dependency checks。
5. 引入 trusted identity、service account、RBAC 和 scope grants。
6. 引入 secret resolver 和日志脱敏。
7. 建立 metrics/traces/dashboards/alerts。
8. 完成 backup/restore/PITR 和 rolling migration rehearsal。
9. 运行无 Legacy workspace 的 Authority-only acceptance。

## 9. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Config | production 缺 build SHA/object root/auth | 启动失败 |
| Legacy fallback | PG 不可用 | 不回退 LocalStorage |
| Readiness | DB/迁移不兼容 | not ready |
| Worker heartbeat | worker 停止 | 健康投影和告警 |
| Pool exhaustion | 并发高 | 有界等待/失败，不无限建连接 |
| RBAC | query 用户执行 cancel/approve | 拒绝 |
| Scope | Service Account 跨 Book | 拒绝 |
| Secret | 日志/manifest 扫描 | 无明文 |
| Backup restore | 恢复到新实例 | Authority state/checksum 一致 |
| PITR | 模拟误删除 | 恢复到目标时间 |
| Rolling migration | 新旧版本并存窗口 | 兼容或明确停机策略 |
| Authority-only | 删除 Local workspace | 完整栈启动并运行 L3 |

## 10. Acceptance Gate

```text
authority_only_deployment_boots=true
production_legacy_fallback_disabled=true
all_workers_deployed_and_healthy=true
postgres_pool_timeout_policy_verified=true
real_readiness_checks_active=true
trusted_identity_rbac_scope_verified=true
secret_plaintext_persistence_zero=true
backup_restore_pitr_rehearsed=true
observability_and_alerting_active=true
```

## 11. 风险

- Worker 数量过多：先逻辑隔离、共享镜像，再按负载拆进程。
- 安全建设拖慢本地开发：Development 使用明确的 local profile，但 evidence 标记 non-production。
- Readiness 依赖外部 Provider 导致不可用：区分核心 readiness 与 capability qualification，不要求所有 Provider 同时可用。
- 迁移难以零停机：当前阶段可选择维护窗口，但必须明确、可演练、可回滚。