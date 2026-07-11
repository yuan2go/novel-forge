# Phase 1：ExecutionEnvelope 与 Production Kernel 收敛设计

## 目标

在不重写现有 Workflow、Agent Scheduler、Loop Kernel 和 Chapter Production Bus 的前提下，建立一个版本化的生产执行契约，并让所有生产执行入口在写入 Run、Task 或 Artifact 前完成同一套验证。

## 当前事实

- `os_envelope` v0.1 已能在 production 模式 fail-closed，并写 TraceSpan，但主要是 metadata dict。
- Loop Kernel 在创建 LoopRun 前调用 `enforce_os_envelope`。
- Topic、Outline、Chapter Plan、Draft 等模型操作通过 production governance 间接检查 Envelope。
- Chapter Production Bus 会先创建 `chapter_production_run`，未在入口直接 enforce Envelope。
- Workflow、Agent Scheduler、Chapter Bus、Loop Kernel 都持有部分生命周期状态；当前不能把任一模块直接宣布为唯一 Kernel。
- Product API middleware 只检查“生产 mutation 是否带 envelope dict”，不验证完整字段或 canonical refs。

## 决策

### 1. Envelope v2 采用 canonical refs + legacy shadow

Canonical 字段包括：

```text
schema_version
envelope_id
project_ref / novel_ref
workflow_ref / run_ref / task_ref / agent_ref
artifact_ref / asset_ref / context_ref / approval_ref
provider_ref
correlation_id / causation_id
idempotency_key
operation / actor_type / actor_id
input_refs / expected_output_types
budget / source_policy / environment
```

兼容期继续输出 `project_id`、`task_type`、`asset_type`、`trace_id`、`version` 等 legacy shadow；旧 payload 会被标记 `legacy_derived=true`。新代码只从统一 normalize/enforce 结果读取执行字段。

### 2. 本阶段不提前引入微服务或强制 PostgreSQL

LocalStorage 继续是本地模式权威。Envelope 先作为不可变、可验证的契约和所有运行资产的反向引用；工业事务 repository 与唯一约束留到 Phase 2 Outbox 工作包，避免在 Kernel 边界未确定时固化错误存储模型。

### 3. Production Kernel 是 facade，不是第五套状态机

新增的 Kernel seam 只负责：

```text
validate command
resolve/enforce envelope
authorize dispatch target
create or delegate authoritative run
record correlation/idempotency
return normalized execution result
```

它不复制 WorkflowRun、NodeRun、AgentRun 或 ChapterProductionRun 状态。第一条 tracer bullet 为“章节生产 command -> Kernel -> Chapter Bus”；随后迁移 Workflow 和 Scheduler 外部入口。

### 4. 生产验证必须发生在副作用前

Production API、CLI、Worker 和内部 handoff 在创建 Run/Task/Artifact 前必须完成：

- v2/legacy-compatible Envelope normalize；
- project scope 一致性；
- operation/asset/task contract；
- correlation/causation/idempotency；
- Context/Source policy presence；
- 目标执行器注册验证。

失败只记录无业务副作用的审计证据；不能先创建“planned”运行再失败。

## 迁移顺序

1. 扩展 `os_envelope` 为 v2 typed-normalized contract，并补 schema/compat/idempotency tests。
2. 建立生产入口 manifest 与 bypass contract test。
3. 在 Chapter Production Bus 入口副作用前 enforce；下游复用同一 envelope。
4. 建立 Production Kernel facade，将 API/Worker/Workflow 的章节生产调用迁入。
5. 核验 Workflow/Agent/Loop 的状态所有权，禁止 facade 新建平行状态。
6. 入口覆盖达到 100% 后，生产新写禁止无 canonical refs 的 native v2 请求；历史 v0.1 仅只读兼容。

## 非目标

- 本工作包不实现 transactional Outbox。
- 不删除现有 Workflow/Agent/Loop 状态资产。
- 不接入真实 Provider。
- 不把所有产品 CRUD 或治理查询错误地纳入 Production Kernel。
- 不进行微服务拆分。

## 验收

- v2 normalize、legacy adapter、字段冲突、幂等稳定性和 causation tests 通过。
- Production Chapter Bus 缺 Envelope 时在任何 Run/Task/Artifact 写入前失败。
- 相同 project + operation + immutable refs 的请求得到稳定 idempotency key。
- API、Worker 和 direct service 的章节生产使用同一 Kernel seam。
- Manifest 能自动发现登记生产入口缺少 enforcement。
- 两轮全量确定性回归保持绿色。

