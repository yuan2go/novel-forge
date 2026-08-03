# AC-12 Provider 与外部执行

状态：`PLANNED`  
阶段：Phase 3 / Intelligence and Decision Closure  
前置依赖：AC-05、AC-09

2026-08-03 有限修订：在 Track B Minimal Authority-only Runtime 与 Track C 之间增加 D0 Real Provider Qualification Probe；D0 只证明控制面行为，不构成章节或小说质量证明，缺凭据时 Gate 保持 false。

## 1. ADR

### 背景

系统需要调用 LLM Provider、Codex/Claude Code 本地进程、外部发布平台、Source connector、反馈接口和通知服务。这些调用具有超时、重复、未知结果、成本、凭据和取消语义。业务模块直接依赖 SDK、HTTP 或 subprocess 会复制执行逻辑，并使真实 Provider 证明无法统一。

### 决策

所有不确定外部执行通过统一 Production Execution Plane，但按能力类型区分：

- Model Capability；
- Local Agent/CLI Capability；
- External Action Capability。

业务只请求 Capability 和质量/预算策略，不指定凭据和具体 SDK。Execution Plane 负责 Backend Registry、Qualification、RouteSnapshot、ExternalEffect、Receipt、Normalization、Validation、Cost、Cancel、Query、Callback 和 Reconciliation。

## 2. 核心模型

### Backend Registry

每个 Backend 声明：capabilities、model profiles、version、qualification、timeout/cancel/query/callback support、cost source、auth profile requirements、environment eligibility。

### RouteSnapshot

每次执行冻结：

```text
backend_id
provider/model/version
capability
reasoning profile
quality tier
timeout/deadline
retry/reconciliation policy
budget reservation
auth_profile_ref
credential_scope
qualification evidence
```

执行后不得静默换模型；fallback 必须形成新 Attempt 和新 RouteSnapshot。

### Cost

统一记录：estimated、reserved、provider-reported、calculated、final cost，以及 currency、token/usage、pricing profile version。`0 USD / not_provided` 不能满足生产成本 Gate。

### Credential

正式 manifest 只保存 auth profile/secret version reference，不保存 secret 内容。Provider adapter 通过 Secret Resolver 获取最小范围凭据。

## 3. 实施范围

- 统一 Remote Provider v2、OpenAI Responses seam、Codex process supervisor 和 external action ports；
- 建立 capability probe 和 qualification lifecycle；
- 建立 request identity、stable key、timeout、cancel、query、callback、receipt；
- 建立 synchronous、polling 和 callback 三种完成模式；
- 建立 UNKNOWN reconciliation 和 late result；
- 建立成本 reservation、limit 和 finalization；
- 建立 output normalization、schema validation 和 object store evidence；
- 移除 controlled environment 中的 direct provider/model adapter fallback。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/production_execution/`
- `src/novel_forge/modules/provider_control/`
- `src/novel_forge/modules/provider_control/openai_v2.py`
- Provider registry/gateway/backends
- Persistent Codex process supervisor
- Publishing/source/notification external action adapters
- `src/novel_forge/api/provider_adapters.py`
- runtime policy、cost ledger、callback/reconciliation modules

### 目标收敛

- `production_execution/contracts.py`
- `production_execution/gateway.py`
- `production_execution/registry.py`
- `production_execution/routing.py`
- `production_execution/effects.py`
- `production_execution/receipts.py`
- `production_execution/reconciliation.py`
- `production_execution/cost.py`
- `production_execution/secrets.py`
- `production_execution/backends/`
- `tests/contract/test_backend_conformance.py`

### 禁止位置

Domain/Application 之外的 adapter 层以外禁止 import Provider SDK、`httpx/requests` 外部调用和 `subprocess` 模型执行。禁止 Provider adapter 决定领域 acceptance 或直接写 AssetVersion。

## 5. 迁移脚本设计

数据库需支持 Backend/ModelProfile/RoutePolicy/Qualification snapshots、Effects、Receipts、Callbacks、Usage、Cost reservation/finalization、Reconciliation 和 cancellation evidence。

脚本：

```text
scripts/migrations/inventory_direct_external_calls.py
scripts/migrations/import_backend_registry.py
scripts/migrations/backfill_route_snapshots.py
scripts/migrations/backfill_effect_request_identity.py
scripts/migrations/reconcile_cost_ledgers.py
scripts/migrations/quarantine_unverifiable_external_results.py
```

历史结果缺少 request id、route 或 receipt 时标记 `external_execution_verifiable=false`，不得升级为真实 Provider proof。

## 6. 实施计划

1. 枚举所有 SDK/HTTP/subprocess 调用。
2. 固定 Capability、Backend、Route、Effect、Receipt 和 Cost contracts。
3. 建立 Backend conformance suite。
4. 将 Chapter、Agent、Judge、Source、Publishing 调用迁入 Gateway。
5. 实现 qualification、secret resolver 和 environment policy。
6. 实现 timeout/cancel/query/callback/UNKNOWN reconciliation。
7. 实现真实 usage/cost 对账。
8. 完成一个真实 Provider 单章和一个 sandbox external action 纵切证明。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Registry | 未注册/未资格 Backend | admission 拒绝 |
| Route freeze | 执行中配置变化 | 当前 Attempt route 不变 |
| Timeout | 上游结果未知 | UNKNOWN，不盲重试 |
| Cancel | 上游支持/不支持 cancel | 证据准确，不伪称成功取消 |
| Callback duplicate | 同一 receipt 重放 | 幂等 |
| Callback conflict | 同 identity 不同 payload | 阻塞并审计 |
| Secret leakage | manifest/output 出现 secret | 拒绝/脱敏 |
| Cost limit | 预计或累计超预算 | admission/continuation 阻塞 |
| Local process | timeout/kill/PID reuse | process receipt 可验证 |
| Real provider | 真实请求 | request id、usage、cost、output evidence 完整 |
| Direct call scan | 新增 SDK 调用 | CI 失败 |

## 8. Acceptance Gate

```text
backend_registry_authoritative=true
all_production_external_calls_gateway_bound=true
route_snapshots_immutable=true
provider_unknown_reconciliation_verified=true
callback_receipt_idempotency_verified=true
secret_reference_only_verified=true
real_cost_accounting_verified=true
single_real_provider_vertical_slice_proven=true
```

## 9. 风险

- 统一平面掩盖能力差异：Backend contract 显式声明 cancel/query/callback 等能力，禁止假装支持。
- 多 Provider 路由过早复杂：先固定契约并接一个真实 Provider，再增加策略。
- 成本数据不可靠：保留 provider reported 与 local calculated 两套来源及差异。
- Local CLI 与 Remote Provider 混淆：Local receipt 与 Provider request id 分离。
