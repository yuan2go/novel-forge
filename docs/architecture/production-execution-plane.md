# Novel Forge 统一生产执行平面

> 更新日期：2026-07-22  
> 适用分支：`feat/v7-content-intelligence-and-longform-proof`  
> 文档状态：`ACTIVE TARGET ARCHITECTURE`，不代表已经实现或通过生产验证

## 0. 文档定位

本文定义 Novel Forge 的统一生产执行平面（Production Execution Plane，PEP）。

它负责把当前分散的模型、Codex CLI、Provider 和 Agent 执行路径收敛为一个可恢复、可审计、可预算、可验证的生产入口。

本文只定义执行基础设施，不负责：

- Creative、World、Character、Planning 等领域语义；
- Book / Volume / ChapterGroup 的故事规划；
- Canon 和 Story State 的业务提交规则；
- Reader Outcome 的校准逻辑；
- Book Production 的下一步业务决策。

业务领域通过 Authority Operation 提交 Work Order，PEP 只回答：

```text
是否允许执行
→ 使用哪个执行后端和冻结配置
→ 如何安全启动、查询、取消和恢复
→ 如何验证结果
→ 如何生成可审计 Receipt
```

## 1. 核心责任模型

```text
Novel Forge Policy Scheduler / Book Scheduler
= 默认确定性生产协调者

Claude Code
= 可选高级监督、诊断和重规划客户端
= 不应成为常规生产的必需运行时

PostgreSQL Authority
= 唯一生产权威
= Command、Operation、Saga、Attempt、Lease、Fence、Budget、Approval、Commit

Production Execution Plane
= 受控执行运行时
= Admission、Route Snapshot、Backend、Process、Workspace、Cancel、Reconcile、Receipt

Codex CLI / Remote Provider / Fixture
= Execution Backend
```

统一入口：

```text
Business Engine
→ PostgreSQL Authority Operation
→ ProductionExecutionGateway
→ Qualified ExecutionBackend
→ ExecutionResult
→ Authority Validation and Commit
```

业务模块必须满足：

```text
不依赖 Codex CLI
不依赖 Claude Code 进程
不依赖 OpenAI SDK
不直接选择账号
不直接选择运行主机
不直接拼接模型参数
不直接创建成功 Receipt
```

## 2. 当前实现基线

当前可复用能力：

- Command Kernel；
- Operation、Saga、Attempt、Lease、Fencing、Budget、Receipt；
- Provider Adapter v2；
- Provider Capability、Query、Cancel、Callback 和 Usage / Cost Receipt；
- `LocalCodexCliWorkerMixin` 的命令构造、结构化输出和 Runtime Guard；
- Model Router；
- Chapter Authority ExternalEffect；
- Context Builder、Quality、Canon、Review、Revision；
- Worker supervision 和 Evaluation Center 基础。

当前主要风险是多条执行路径并存：

```text
Legacy ModelAdapter
LocalCodexCliWorkerMixin
ModelRouter direct invocation
Provider Adapter v2
Chapter Authority external-effect path
Agent / Workflow direct call path
```

禁止在这些路径之外再新增新的 Codex 调用器。

## 3. 收敛原则

### 3.1 现有 Authority Attempt 是唯一 Attempt 权威

不得新增第二套 `execution_attempts` 业务状态机。

```text
Authority Attempt
= 唯一执行尝试权威

ExecutionRequest / ExecutionHandle / ExecutionResult
= Attempt 的执行合同和投影

ExternalEffect / ProcessReceipt / ExecutionEvent
= Attempt 的外部运行证据
```

PEP 可以维护细粒度执行状态，但不能与 Authority Attempt 竞争最终状态权威。

### 3.2 Provider v2 保留

Provider v2 继续负责远程 Provider 的：

- Query；
- Cancel；
- Callback；
- Provider Receipt；
- Provider-side Capability；
- OpenAI-compatible transport seam。

它通过 `RemoteProviderExecutionBackend` 接入 PEP，不删除、不复制、不强迫本地 Codex 伪装成远程 Provider。

### 3.3 Model Router 收敛为 Route Resolver

Model Router 只负责：

```text
ModelProfile Registry
RoutePolicy
Route Resolver
Route Recommendation Read Model
```

生产路径不得由 Model Router 直接调用旧 Adapter。

### 3.4 Claude Code 是可选客户端

常规 Chapter、Group 和 Book Saga 应由 Novel Forge Scheduler 按批准策略运行。

Claude Code 可用于：

- 复杂诊断；
- 高风险重规划；
- 提交结构化 OrchestratorDecision；
- 读取 Evidence 和建议下一步；
- 复杂 Agent Workspace Transaction。

Claude Code 离线时，已经批准的 Saga 仍应继续执行。

## 4. 第一阶段 PEP Core

第一阶段只实现：

```text
ExecutionRequest
ExecutionHandle
ExecutionResult
ExecutionBackend
ProductionExecutionGateway
ExecutionBackendRegistry
ExecutionCapabilityProfile
ModelProfile
RoutePolicy
RouteSnapshot
CapabilityProbe
PersistentExecutionDirectory
ProcessReceipt
Input / Execution / Output / Validation / Commit Manifest
EnvironmentAllowlist
Timeout / Cancel / Reconcile
Minimal Workspace Staging
```

第一阶段明确后置：

- 多主机调度；
- 多账号自动轮换；
- ClaudeCodeAgentExecutionBackend；
- Git Worktree Agent Transaction；
- Ensemble；
- 自动在线 RoutePolicy 更新；
- 多书资源调度；
- 复杂 Quota 优化。

## 5. 核心合同

### 5.1 ExecutionBackend

```python
class ExecutionBackend(Protocol):
    backend_id: str
    capability_profile: ExecutionCapabilityProfile

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        ...

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        ...

    def cancel(
        self,
        handle: ExecutionHandle,
        reason: str,
    ) -> ExecutionCancellationResult:
        ...
```

第一阶段后端：

```text
CodexCliExecutionBackend
RemoteProviderExecutionBackend
ScriptedFixtureExecutionBackend
```

### 5.2 ExecutionRequest

必须绑定现有 Authority Attempt：

```text
execution_id
operation_id
saga_id
attempt_id
fencing_token
project_id
book_id
chapter_id / target_scope
task_kind
stage
importance_class
risk_class
route_snapshot_id
workspace_snapshot_id
input_manifest_ref
resource_claims
timeout_policy
budget_policy
permission_policy
origin_chain
agent_hop_count
```

### 5.3 ExecutionHandle

```text
execution_id
backend_execution_id
backend_id
local_process_id
local_process_group_id
local_process_start_time
provider_request_id
completion_mode
query_capability
cancel_capability
callback_capability
```

### 5.4 ExecutionResult

```text
execution_id
outcome
process_receipt_ref
provider_receipt_ref
raw_output_ref
normalized_output_ref
output_manifest_ref
usage_receipt_ref
cost_receipt_ref
validation_report_ref
started_at
completed_at
```

字段允许为 `null`，但不允许伪造。

## 6. ModelProfile 与 RouteSnapshot

### 6.1 ModelProfile

业务节点使用稳定逻辑别名，不硬编码实际模型：

```yaml
profile_id: codex.sol.xhigh
profile_version: 1
backend_id: codex_cli
runtime_class: LOCAL_CLI_REMOTE_INFERENCE
model_provider: openai
model_id: gpt-5.6-sol
reasoning_effort: xhigh
timeout_policy_ref: codex-xhigh-v1
workspace_policy_ref: book-staging-readonly-v1
output_policy_ref: structured-output-required-v1
fallback_policy: FAIL_CLOSED
status: ACTIVE
```

只有 Capability Probe 通过后才能 `ACTIVE`。

### 6.2 RoutePolicy

Route 决策输入：

```text
Stage
ImportanceClass
RiskClass
ContextSizeClass
QualityHistory
RetryCount
CanonConflictLevel
QuotaStatus
RuntimeHealth
ModelDriftStatus
```

### 6.3 RouteSnapshot

每次 Operation 冻结：

```text
route_snapshot_id
operation_id
policy_version
backend_id / backend_version
runtime_host_id
auth_profile_ref
model_profile_id / version
model_provider / model_id
reasoning_effort
prompt_bundle_ref
skill_bundle_ref
context_bundle_ref
output_schema_ref
release_sha
```

默认重试继续使用原 RouteSnapshot。

以下变化必须创建新 RouteDecision 和 RouteSnapshot：

- 模型；
- Reasoning Effort；
- Prompt；
- Skill；
- Context；
- Auth Profile；
- Runtime Host。

不允许从 `xhigh` 静默降级到 `high`。

## 7. Capability Probe

Worker 启动和定期心跳检查：

```text
Codex CLI executable / version
Authentication
Model availability
Reasoning effort
Structured output
Sandbox option
Ephemeral mode
Process group control
Workspace access
```

规则：

- Profile 不满足能力时 Qualification 失败；
- CLI 版本变化后重新 Probe；
- Probe 失败的 Host 不接收新任务；
- 已运行任务进入 Reconcile；
- 不允许静默修改 Route。

## 8. Codex CLI Backend

### 8.1 组件

```text
CodexCliExecutionBackend
├─ CodexCapabilityProbe
├─ CodexCommandBuilder
├─ CodexEnvironmentBuilder
├─ CodexProcessSupervisor
├─ CodexOutputParser
├─ CodexUsageParser
├─ CodexResultNormalizer
├─ CodexResultValidator
└─ CodexProcessReconciler
```

### 8.2 从现有代码抽取

从 `LocalCodexCliWorkerMixin` 抽取：

- 命令构造；
- Model/Profile/Sandbox 参数；
- JSON Schema 和 Output Last Message；
- Prompt 输入限制；
- stdout / stderr；
- Usage 解析；
- Runtime Guard；
- 结构化输出验证。

旧 Adapter 过渡期改为：

```text
Legacy Adapter
→ LegacyRequestMapper
→ ProductionExecutionGateway
→ CodexCliExecutionBackend
→ LegacyResultMapper
```

旧 Adapter 不再拥有独立进程执行实现。

### 8.3 本地回执语义

本地 Codex CLI 是本地进程启动远程推理，不等于本地模型，也不等于可查询的远程 Provider API。

必须记录：

```text
transport = LOCAL_CLI_REMOTE_INFERENCE
local_execution_receipt_id = <real local receipt>
provider_request_id = null  # 无真实值时
provider_query_capability = UNSUPPORTED / UNKNOWN
provider_cancel_capability = UNSUPPORTED / UNKNOWN
```

禁止使用哈希构造伪造的远程 Provider Request ID。

## 9. 持久化进程监督

当前临时目录不足以支持 Worker Crash Recovery。

目标启动协议：

```text
PREPARING
→ 创建持久化 Execution Directory
→ 写 InputManifest 和 ExecutionManifest
→ 创建独立进程组
→ 记录 PID / PGID / start_time
→ 持久化 ProcessReceipt
→ RUNNING
```

### 9.1 Cancel

```text
CANCEL_REQUESTED
→ SIGTERM process group
→ grace period
→ SIGKILL process group
→ 验证本地子进程不存在
→ LOCAL_PROCESS_TERMINATED
```

必须区分：

```text
local_process_terminated
upstream_request_cancelled
```

上游取消状态：

```text
CONFIRMED
UNSUPPORTED
UNKNOWN
NOT_APPLICABLE
```

本地进程终止不能自动宣称完整 Provider Cancel 成功。

### 9.2 Worker Restart

扫描：

```text
RUNNING / CANCEL_REQUESTED / RECONCILING Attempt
+ ProcessReceipt
+ PID / PGID / start_time
+ Execution Directory
```

处理：

| 状况 | 处理 |
|---|---|
| 进程仍在 | 重新接管监控 |
| 已结束且结果完整 | 继续验证 |
| 进程不存在且无结果 | ORPHANED |
| PID 被复用 | ORPHANED |
| 部分结果 | CORRUPT_RESULT |
| 无法判断 | RECONCILING |

## 10. Workspace 与 Manifest

### 10.1 权威边界

```text
PostgreSQL / AssetStore = Authority
Workspace Files = Projection / execution medium
Execution Staging = untrusted candidate output
```

### 10.2 Manifest

InputManifest：

- Context / Prompt / Skill Bundle；
- Book、Chapter、Arc、Canon 版本；
- 输入 Hash；
- Source Eligibility；
- Read Set。

ExecutionManifest：

- Operation、Attempt、Fence；
- RouteSnapshot；
- Backend、Host、Auth Ref；
- CLI 版本；
- 命令摘要；
- Environment Allowlist 名称；
- Timeout；
- Release SHA。

OutputManifest：

- Raw / Normalized Output；
- stdout / stderr；
- Hash；
- Schema Version；
- 文件清单。

ValidationManifest：

- Schema；
- Semantic；
- Canon；
- Workspace Scope；
- Source Isolation；
- Originality；
- Quality Preflight；
- Fencing。

CommitManifest：

- Committed AssetVersion；
- Authority Commit；
- Projection Materialization；
- Rejected Output；
- Rollback Ref。

### 10.3 Commit 流程

```text
Backend output to staging
→ Normalize
→ Schema Validation
→ Semantic / Canon / Source / Security Validation
→ Fencing Validation
→ Authority Commit
→ Projection Materialization
```

验证失败的输出只能留在 Staging。

## 11. Environment 和 Security

当前本地进程不得继续继承完整 `os.environ`。

默认 Allowlist：

```text
PATH
HOME
CODEX_HOME
LANG
LC_ALL
TMPDIR
SSL_CERT_FILE
HTTP_PROXY
HTTPS_PROXY
NO_PROXY
```

其余变量默认拒绝，按 Backend 显式增加。

所有可序列化执行合同、恢复记录和 External Receipt 在写入前递归执行
Secret Guard。明文 `api_key`、`authorization`、access/refresh token、client
secret、private key、password，以及高置信度 Secret 值均 fail closed。持久化
合同只能保存：

```text
auth_profile_ref
credential_scope
secret_version_ref
```

`RouteSnapshot` 和 `ExecutionManifest` 冻结这三个引用；Backend 在执行时由
受控凭据解析器取得真实值，真实值不得回写到 Request、Manifest、Receipt、
日志或测试快照。

本地 Process Policy 同时冻结工作目录、命令前缀和最大结果字节数。
Agent Workspace Policy 冻结 Snapshot、Read/Write Set、工具/命令、网络、
Git Base、输出目录、最大文件数、单文件大小、成本及审批策略。Runner
返回的每一个修改路径、文件大小和输出路径都必须落在冻结边界内。

禁止：

- 向 Codex 注入数据库密码；
- 注入 MinIO Secret；
- 注入其他 Provider Key；
- 在 Manifest 写真实 Token；
- stdout / stderr 泄漏凭据；
- 未注册 Workspace；
- 路径逃逸和跨书读取；
- Write Set 外写入。

## 12. 幂等与重试

### 12.1 Authority Idempotency

```text
Stable Key = business intent identity
```

### 12.2 Execution Deduplication

```text
Execution Fingerprint =
Operation ID
+ Attempt generation
+ InputManifest hash
+ RouteSnapshot hash
+ WorkspaceSnapshot hash
```

### 12.3 Provider Idempotency

只在 Provider 真正支持时记录 Provider-side Idempotency。

Capability 分开记录：

```text
authority_idempotency
execution_deduplication
provider_idempotency
```

### 12.4 Retry

- 同一 Attempt 不并发执行两次；
- Worker 失联先 Reconcile；
- 旧执行终止或被 Fence 后才能新建 Attempt；
- 旧 Fence 结果永久不能提交；
- Route 变化必须新 Snapshot；
- Provider UNKNOWN 不得立即重复发送。

## 13. Usage、Quota 与 Cost

Billing Mode：

```text
API_METERED
SUBSCRIPTION
ACCOUNT_QUOTA
LOCAL_MODEL
UNKNOWN
```

Codex CLI 使用订阅或账户额度时，不得把成本伪造为 `0 USD`。

```text
usage_precision: REPORTED | ESTIMATED | UNAVAILABLE
cost_precision: EXACT | ESTIMATED | ALLOCATED | UNAVAILABLE
```

Admission 至少检查：

- ModelProfile Active；
- Backend / Host Qualified；
- Budget Reservation；
- Operation Retry Budget；
- Resource Claim Conflict；
- Workspace Registered；
- 必要 Approval。

复杂 AuthProfile、Quota Window 和多账号调度后置，不阻塞第一阶段单机单账号闭环。

## 14. Orchestration 接口

默认生产由 Novel Forge Scheduler 驱动。

Claude Code 可提交结构化决策：

```text
SUBMIT_WORK_ORDER
RETRY_OPERATION
ESCALATE_REASONING
REBUILD_CONTEXT
REQUEST_REVIEW
PROPOSE_PLAN_ADJUSTMENT
PAUSE_BOOK
RESUME_BOOK
MARK_BLOCKED
REQUEST_HUMAN_DECISION
ABANDON_PROPOSAL
```

Claude Code 禁止：

- 直接写业务表；
- 修改正式 Story Bible / Canon；
- 绕过 Gateway 调用 Codex；
- 绕过预算和审批；
- 直接创建成功 Receipt；
- 让 Codex 反向启动 Claude Code。

初期 Agent Hop：

```text
Claude Code
→ Novel Forge Authority
→ Codex / Provider
```

所有建议性后续任务必须返回 Authority 重新 admission。

## 15. 数据模型策略

优先复用：

```text
operations
attempts
sagas
external_effects
provider receipts
budget reservations / settlements
audit / outbox
```

PEP Core 首期新增或扩展：

```text
execution_backends
backend_capabilities
model_profiles
route_policies
route_snapshots
execution_requests
execution_handles
process_receipts
execution_manifests
execution_artifacts
execution_events
workspace_registry
workspace_snapshots
validation_reports
resource_claims
```

注意：

- 不新增平行 `execution_attempts` 权威；
- `execution_requests` 必须唯一绑定 Authority Attempt；
- Raw stdout/stderr 和大模型原始输出进入 ArtifactStore；
- RouteSnapshot、Handle、Receipt 和状态索引进入 PostgreSQL。

## 16. 实施顺序

### Gate 0：迁移前真实单章基线

在已有 Provider v2 路径具备合法凭据、预算和权限时，先执行一次受控真实 Chapter Saga，保存基线证据。

若条件不足，记录明确 Blocker，不虚假运行、不阻塞本地架构工作。

### Phase 1：协议与 Route Snapshot

- ExecutionRequest / Handle / Result；
- Backend Protocol；
- Capability Profile；
- ModelProfile / RoutePolicy / RouteSnapshot；
- Contract Tests。

不改变当前生产行为。

### Phase 2：持久化 Process Supervisor

- Persistent Directory；
- Process Group；
- ProcessReceipt；
- Timeout / Cancel；
- Orphan Recovery；
- Environment Allowlist。

### Phase 3：Codex CLI Backend 抽取

- 从 Mixin 抽取组件；
- Capability Probe；
- Legacy Compatibility Adapter；
- 本地回执语义修正。

### Phase 4：ProductionExecutionGateway

- Backend Registry；
- Admission；
- Route Resolution；
- Manifest / Staging；
- Validation / Commit 接口；
- Remote Provider v2 Adapter。

### Phase 5：迁移 Chapter Authority

覆盖 Draft、Review、Revision、Re-review、Canon Extraction 和 Provider Quality。

### Phase 6：迁移后真实单章证明

对比迁移前基线，验证：

- RouteSnapshot；
- high / xhigh；
- Usage / Cost；
- Timeout / Cancel / Reconcile；
- Duplicate Request；
- Worker Restart；
- Authority Commit。

### Phase 7：Book → Chapter 委托

PEP 单章稳定后再接入 Book Root Saga。

### Phase 8：Eval / Shadow

后置实现：

- ModelPerformanceObservation；
- Shadow Execution；
- Golden Set；
- Drift；
- Route Recommendation。

Route Recommendation 初期只能建议，不能在线自动修改生产路由。

## 17. 测试矩阵

### Contract

- ExecutionRequest / Handle / Result；
- Capability；
- ModelProfile；
- RouteSnapshot；
- Manifest；
- Receipt；
- OrchestratorDecision。

### Process

- 正常和非零退出；
- JSON 缺失和破损；
- Timeout；
- SIGTERM / SIGKILL；
- 子进程残留；
- PID 复用；
- Worker Restart；
- Orphan / Corrupt Result；
- Staging 保留。

### Authority

- Stable Key Replay / Conflict；
- Lease Expiry；
- Fence Rejection；
- Duplicate Dispatch；
- Old Attempt Late Result；
- Budget Reservation；
- Cancel / Retry Race；
- Reconcile / Retry Race；
- CommitManifest Binding。

### Security

- Environment Leakage；
- Path Escape；
- Cross-book Read；
- Write Set Violation；
- Unregistered Workspace；
- Secret Redaction；
- Agent Hop Limit。

## 18. 验收标志

```text
execution_plane_contract_proven
production_execution_gateway_proven
codex_cli_backend_proven
remote_provider_backend_proven
capability_probe_proven
model_profile_resolution_proven
route_snapshot_proven
persistent_execution_manifest_proven
local_process_tree_cancel_proven
orphan_recovery_proven
environment_allowlist_proven
workspace_isolation_proven
single_chapter_authority_proven
book_to_chapter_delegation_proven
production_verified
```

任何 Flag 只能由测试、Receipt、运行报告和审计证据置为 true。

## 19. 非目标和禁止事项

第一阶段禁止：

- 同时接入大量模型；
- 在线自动学习和修改 RoutePolicy；
- 把 Workspace 文件当 Authority；
- 把 Claude Code 长会话当长期记忆；
- 让 Codex 创建 Authority Operation；
- 静默降级模型档位；
- 伪造 Provider Request ID；
- 把未知成本记录为 0；
- 因本地进程结束声称远程请求已取消；
- 新建第二套 Attempt / Saga / Approval；
- 为未来多主机需求阻塞当前单书单机闭环。

## 20. 最终闭环

```text
Authority Operation
→ RouteSnapshot
→ Capability and Budget Admission
→ Workspace Snapshot / InputManifest
→ Qualified Backend
→ Persistent Process / Provider Effect
→ Process / Provider Receipt
→ Output / Validation Manifest
→ Fencing Validation
→ Authority Commit
→ Projection and Eval Observation
```

PEP 的价值不是增加一层抽象，而是消除所有模型执行旁路，为单章、章节组、全书和 Reader Outcome Judge 提供同一套生产运行证据。
