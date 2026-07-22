# Novel Forge 统一生产执行平面

Updated: 2026-07-22  
Status: Target architecture and implementation plan; not an implementation-complete claim  
Target branch: `feat/v7-content-intelligence-and-longform-proof`

## 0. 文档定位

本文定义 Novel Forge 的统一生产执行平面（Production Execution Plane）。

它不是一次普通的模型适配器重构，也不是把 `codex exec` 封装到一个新类中，而是建立一套能够长期支撑以下目标的生产运行架构：

- Claude Code 作为上层总控编排 Agent；
- Codex CLI 作为当前第一生产执行后端；
- 不同创作环节使用不同 Model Profile；
- 当前重点支持 `gpt-5.6-sol high` 与 `gpt-5.6-sol xhigh` 两类逻辑执行档位；
- PostgreSQL Command Kernel、Operation、Saga、Attempt 和 Receipt 继续作为生产权威；
- 单章、章节组、剧情弧、卷级和全书生产任务统一治理；
- 后续自然扩展到远程 Provider、多主机、多账号、多书并发、Shadow、Judge、Ensemble 和 Eval 驱动路由。

本文中的模型名称和推理档位是逻辑配置目标。实际运行时必须通过 Capability Probe 验证本机 Codex CLI、账号和模型是否支持对应配置，不允许因为配置不可用而静默降级。

---

# 1. 核心结论

统一生产执行平面采用以下责任模型：

```text
Claude Code
    = Supervising Orchestrator
    = 诊断、规划、提交决策、读取结果、决定后续动作

Novel Forge PostgreSQL Authority
    = Production Authority
    = 接受命令、冻结路由、创建 Operation/Saga/Attempt、控制预算、提交正式结果

Production Execution Plane
    = Controlled Execution Runtime
    = 准入、路由、运行主机、账号、工作区、执行、取消、恢复、验证、回执

Codex CLI
    = Local Execution Backend
    = 启动受控本地进程并调用底层模型服务

gpt-5.6-sol high / xhigh
    = Model Profile targets
    = 按环节、重要性、风险和质量历史分配推理资源
```

最终必须满足：

```text
业务模块不依赖 Codex CLI
业务模块不依赖 Claude Code 进程
业务模块不依赖 OpenAI SDK
业务模块不直接选择账号
业务模块不直接选择运行主机
业务模块只提交 Authority Command 或 Work Order
```

统一入口应收敛为：

```text
Business Engine
→ PostgreSQL Authority Operation
→ ProductionExecutionGateway
→ Qualified ExecutionBackend
```

---

# 2. 当前实现基线与保留策略

## 2.1 当前可复用能力

当前分支已经具备大量可以直接复用的生产基础：

- PostgreSQL Command Kernel；
- Operation、Saga、Attempt、Lease、Fence、Budget、Receipt；
- Chapter Root Saga 和 Book Root Saga 骨架；
- Provider Adapter v2 注册、资格校验、Query、Cancel、Callback 和 Usage/Cost Receipt；
- `LocalCodexCliWorkerMixin` 的 Codex 非交互执行、JSON Schema、输出解析和 Runtime Guard；
- Model Router、Context Builder、Quality、Canon、Review、Revision、Long-form Recap；
- Worker supervision 和生产运行报告；
- Evaluation Center 和部分 Golden Set 基础。

关键现有路径包括：

```text
src/novel_forge/model_adapters/providers.py
src/novel_forge/model_adapters/runtime.py
src/novel_forge/modules/model_router/
src/novel_forge/provider_control/
src/novel_forge/modules/production_kernel/
src/novel_forge/modules/command_kernel/
src/novel_forge/modules/workspace/
src/novel_forge/modules/context_builder/
src/novel_forge/modules/evaluation_center/
```

## 2.2 当前主要结构问题

当前最大的架构风险不是缺少模型调用能力，而是存在多条相似但不统一的执行路径：

```text
Legacy ModelAdapter path
LocalCodexCliWorkerMixin path
ModelRouter path
Provider Adapter v2 path
Chapter Authority external-effect path
Agent/Workflow direct call path
```

如果在这些路径之外再增加一个新的 Codex 调用器，会从双轨变成多轨，进一步削弱 Authority、幂等、预算和恢复能力。

## 2.3 保留与迁移原则

必须保留：

- Provider Adapter v2；
- Provider capability contract；
- Query、Cancel、Callback、Receipt；
- 当前 Codex 命令构造、输出约束和结果解析能力；
- Runtime Guard；
- Model Router 中可复用的策略和配置资产；
- Command Kernel 和 PostgreSQL Authority；
- Fixture 和 Mock 后端。

需要上移或重新命名：

| 当前概念 | 目标概念 |
|---|---|
| Provider Gateway | Production Execution Gateway |
| Provider Adapter Registry | Execution Backend Registry 的远程 Provider 子注册表 |
| Local Codex Provider | Codex CLI Execution Backend |
| ClaudeCodeAdapter（实际调用 Codex 时） | CodexCliExecutionBackend 或 legacy compatibility adapter |
| Provider Route | Execution Route |
| Provider Capability | Backend Capability + Provider Capability |
| Model Router direct invocation | Route Resolver only |

禁止通过复制旧代码到 `archive/` 目录进行长期双份维护。迁移前使用 Git Tag 保存完整版本，主分支只保留有明确删除条件的 Compatibility Layer。

---

# 3. 目标架构总览

```text
┌────────────────────────────────────────────────────────────┐
│ Claude Code Supervising Orchestrator                       │
│                                                            │
│ Inspect → Diagnose → Plan → Submit → Observe → Decide     │
└────────────────────────────┬───────────────────────────────┘
                             │ OrchestratorDecision
                             ▼
┌────────────────────────────────────────────────────────────┐
│ Novel Forge Authority Plane                                │
│                                                            │
│ Command Kernel                                             │
│ Operation / Saga / Attempt                                 │
│ Idempotency / Lease / Fence / Budget / Approval / Audit    │
└────────────────────────────┬───────────────────────────────┘
                             │ Authorized Work Order
                             ▼
┌────────────────────────────────────────────────────────────┐
│ Novel Forge Production Execution Plane                     │
│                                                            │
│ Admission Controller                                       │
│ Route Resolver and Route Snapshot                          │
│ Model Profile Registry                                     │
│ Capability Negotiator                                      │
│ Runtime Host Scheduler                                     │
│ Auth and Quota Controller                                  │
│ Workspace Transaction Manager                              │
│ ProductionExecutionGateway                                 │
│ Result Validator                                           │
│ Reconciliation Controller                                  │
│ Execution Event Ledger                                     │
└───────────────┬───────────────────┬────────────────────────┘
                │                   │
                ▼                   ▼
┌────────────────────────┐  ┌───────────────────────────────┐
│ Local Runtime          │  │ Remote Runtime                │
│                        │  │                               │
│ CodexCliBackend        │  │ RemoteProviderBackend         │
│ ClaudeCodeAgentBackend │  │  └─ ProviderAdapterV2         │
│ FixtureBackend         │  │                               │
└────────────┬───────────┘  └───────────────┬───────────────┘
             │                              │
             └──────────────┬───────────────┘
                            ▼
┌────────────────────────────────────────────────────────────┐
│ Workspace / Staging / Manifest / Receipt Layer             │
│                                                            │
│ InputManifest                                              │
│ ExecutionManifest                                          │
│ ProcessReceipt / ProviderReceipt                           │
│ OutputManifest                                             │
│ ValidationManifest                                         │
│ CommitManifest                                             │
└────────────────────────────┬───────────────────────────────┘
                             │ Validated Commit Proposal
                             ▼
┌────────────────────────────────────────────────────────────┐
│ PostgreSQL Authority and Projection                        │
│                                                            │
│ Chapter / Canon / Arc / Foreshadow / Character / Quality   │
│ Runtime Ledger / Eval Observation / Route Recommendation   │
└────────────────────────────────────────────────────────────┘
```

---

# 4. 五个平面

统一生产执行平面在逻辑上分为五个协作平面。

## 4.1 Authority Plane

负责：

- Command 接收；
- Operation、Saga、Attempt 生命周期；
- Stable Key；
- Lease 和 Fencing Token；
- Budget Reservation；
- Approval Gate；
- 正式资产提交；
- 取消和补偿；
- Audit 和 Receipt 权威。

Authority Plane 是唯一可以宣告生产结果正式生效的平面。

## 4.2 Orchestration Plane

由 Claude Code 和 Novel Forge Orchestrator Service 共同组成。

Claude Code负责：

- 分析当前书籍状态；
- 判断下一项任务；
- 提交结构化决策；
- 根据失败类型决定重试、升级、重建上下文、暂停或申请人工处理；
- 提出 Plan Adjustment Proposal。

Novel Forge Orchestrator Service负责：

- 验证 Claude Code 决策；
- 将决策转化为 Authority Command；
- 限制 Agent Hop；
- 阻止递归调用；
- 记录 Orchestration Run 和 Decision Evidence。

## 4.3 Execution Plane

负责：

- 准入；
- 路由冻结；
- Backend 资格校验；
- 运行主机和账号选择；
- Workspace Snapshot 和 Staging；
- 进程或 Provider 请求；
- 超时、取消和恢复；
- 结果收集和标准化；
- 执行级审计。

## 4.4 Evaluation Plane

负责：

- 模型和 Prompt 性能观测；
- high/xhigh 性价比比较；
- Shadow Execution；
- Golden Set；
- Drift Detection；
- Route Recommendation；
- Candidate/Judge/Ensemble 评测。

Evaluation Plane 初期只能提出建议，不允许在线自动修改生产 RoutePolicy。

## 4.5 Security and Workspace Plane

负责：

- Book Workspace Registry；
- Workspace Snapshot；
- Staging-only 写入；
- 环境变量白名单；
- 账号凭据隔离；
- 路径逃逸保护；
- 跨书隔离；
- Process Group；
- Source Isolation；
- Agent Workspace Transaction。

---

# 5. 角色与信任边界

## 5.1 Claude Code

允许：

- 调用 Novel Forge CLI/API；
- 读取被授权的状态和报告；
- 提交结构化决策；
- 提出任务、重试、升级和计划调整建议；
- 为复杂任务生成变更 Proposal。

禁止：

- 直接写 PostgreSQL 业务表；
- 直接修改正式 Story Bible；
- 直接写正式章节目录；
- 直接创建成功 Receipt；
- 绕过 Route Resolver 调用 Codex；
- 绕过预算和审批；
- 直接切换 Auth Profile；
- 把本地进程终止声称为上游请求取消；
- 让 Codex 再反向启动 Claude Code。

## 5.2 Codex CLI Backend

允许：

- 读取 ExecutionRequest 中声明的输入；
- 读取只读 Workspace Snapshot；
- 写入 Execution Staging；
- 返回结构化结果和建议；
- 报告 Usage、进程状态和错误。

禁止：

- 创建 Authority Operation；
- 写正式 Canon；
- 写正式章节；
- 修改路由；
- 自行切换账号；
- 访问其他书籍；
- 访问未声明的环境凭据；
- 递归调用 Claude Code；
- 自行批准输出。

## 5.3 PostgreSQL Authority

负责：

- 保存唯一正式状态；
- 接受或拒绝请求；
- 验证 Fencing Token；
- 保证旧 Attempt 无法覆盖新 Attempt；
- 控制结果提交；
- 决定 Saga 是否完成。

---

# 6. 核心领域模型

## 6.1 ExecutionBackend

顶层接口不应只描述远程 Provider，也不应只描述单次文本生成。

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

目标实现：

```text
ModelInvocationBackend
├── CodexCliExecutionBackend
├── RemoteProviderExecutionBackend
└── ScriptedFixtureExecutionBackend

AgentRuntimeBackend
├── ClaudeCodeAgentExecutionBackend
└── FutureCodexAgentExecutionBackend
```

当前第一生产实现是 `CodexCliExecutionBackend`。真正的 `ClaudeCodeAgentExecutionBackend` 放在后续复杂多文件任务阶段，不应与当前实际调用 Codex 的旧 `ClaudeCodeAdapter` 混淆。

## 6.2 ModelProfile

`ModelProfile` 表示可复用模型执行配置。

```json
{
  "profile_id": "codex.sol.xhigh",
  "profile_version": 1,
  "backend_id": "codex_cli",
  "runtime_class": "LOCAL_CLI_REMOTE_INFERENCE",
  "model_provider": "openai",
  "model_id": "gpt-5.6-sol",
  "reasoning_effort": "xhigh",
  "auth_profile_ref": "chatgpt-pro-primary",
  "quota_class": "EXPENSIVE_REASONING",
  "timeout_policy_ref": "codex-xhigh-v1",
  "workspace_policy_ref": "book-staging-readonly-v1",
  "output_policy_ref": "structured-output-required-v1",
  "fallback_policy": "FAIL_CLOSED",
  "status": "ACTIVE"
}
```

注意：

- `profile_id` 是稳定逻辑别名；
- `model_id` 是当前实际配置；
- 模型或 CLI 变化时升级 `profile_version`；
- 业务节点不得硬编码 `gpt-5.6-sol`；
- RouteSnapshot 必须保存实际解析后的模型和推理档位。

## 6.3 RoutePolicy

`RoutePolicy` 表示何时选择某个 ModelProfile。

```yaml
route_policies:
  chapter_draft_routine:
    when:
      task_kind: CHAPTER_DRAFT
      importance_class: ROUTINE
      retry_count: 0
    use_profile: codex.sol.high

  chapter_draft_climax:
    when:
      task_kind: CHAPTER_DRAFT
      importance_class: CLIMAX
    use_profile: codex.sol.xhigh
```

## 6.4 RouteSnapshot

RouteSnapshot 是某次 Operation 的执行事实，必须冻结：

```json
{
  "route_snapshot_id": "route-snapshot-001",
  "operation_id": "operation-001",
  "policy_version": 7,
  "backend_id": "codex_cli",
  "backend_version": "codex-cli-backend-v1",
  "runtime_host_id": "mac-mini-01",
  "auth_profile_ref": "chatgpt-pro-primary",
  "model_profile_id": "codex.sol.xhigh",
  "model_profile_version": 1,
  "model_provider": "openai",
  "model_id": "gpt-5.6-sol",
  "reasoning_effort": "xhigh",
  "prompt_bundle_ref": "prompt-bundle-92",
  "skill_bundle_ref": "skill-bundle-18",
  "context_bundle_ref": "context-bundle-881",
  "output_schema_ref": "chapter-draft-v4",
  "release_sha": "<novel-forge-release-sha>"
}
```

默认重试继续使用原 RouteSnapshot。任何模型、Reasoning Effort、Prompt、Skill、Context、账号或运行主机改变，都必须创建新的 RouteDecision 和 RouteSnapshot。

## 6.5 RuntimeHost

```json
{
  "runtime_host_id": "mac-mini-01",
  "host_class": "LOCAL_WORKER",
  "operating_system": "darwin",
  "status": "HEALTHY",
  "max_concurrency": 2,
  "capabilities": [
    "codex_cli",
    "structured_output",
    "process_group_control"
  ],
  "allowed_book_scopes": ["*"],
  "last_heartbeat_at": "2026-07-22T20:00:00+08:00"
}
```

## 6.6 AuthProfile

```json
{
  "auth_profile_id": "chatgpt-pro-primary",
  "backend_id": "codex_cli",
  "credential_mode": "LOCAL_CODEX_LOGIN",
  "codex_home_ref": "secret://codex-home-primary",
  "max_concurrency": 2,
  "xhigh_max_concurrency": 1,
  "quota_policy_ref": "chatgpt-pro-primary-v1",
  "status": "ACTIVE"
}
```

AuthProfile 只保存引用和治理元数据，不能把真实令牌写入普通数据库字段或 Manifest。

## 6.7 BookWorkspace

当前项目中的 Workspace 状态资产不能等价替代物理生产 Workspace Registry。

目标 BookWorkspace 至少包含：

```text
book_id
workspace_id
workspace_root
staging_root
snapshot_root
allowed_read_scopes
allowed_write_scopes
materialization_policy
current_authority_version
current_projection_version
status
```

PostgreSQL 和 AssetStore 是 Authority；物理文件目录是 Projection 和执行介质。

---

# 7. Claude Code 编排协议

## 7.1 运行模式

Claude Code 采用短周期、可恢复、状态外置的编排循环：

```text
读取 Authority 状态
→ 读取可执行 Work Order 和阻塞项
→ 分析下一步动作
→ 提交 OrchestratorDecision
→ Authority 接受或拒绝
→ Execution Plane 执行
→ Claude Code 读取结果和质量报告
→ 提交下一轮决策
```

禁止依赖单个超长 Claude Code 会话保存整本小说状态。

## 7.2 OrchestratorDecision

```json
{
  "orchestration_run_id": "orch-20260722-001",
  "decision_id": "decision-001",
  "book_id": "book-001",
  "decision_type": "SUBMIT_WORK_ORDER",
  "task_kind": "CHAPTER_DRAFT",
  "target": {
    "chapter_number": 21
  },
  "importance_class": "CLIMAX",
  "requested_profile": "codex.sol.xhigh",
  "reason": "卷级第一次核心冲突正面爆发",
  "evidence_refs": [
    "chapter-plan-21-v3",
    "arc-plan-03-v2",
    "longform-recap-20-v1"
  ],
  "expected_outputs": [
    "chapter_draft",
    "draft_metadata"
  ]
}
```

## 7.3 决策类型

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

## 7.4 防止 Claude Code—Codex 无限递归

每次执行记录：

```text
origin_chain
parent_execution_id
agent_hop_count
max_agent_hops
allowed_child_backends
```

初期约束：

```text
max_agent_hops = 2
Claude Code → Novel Forge → Codex
Codex 不允许反向启动 Claude Code
Codex 不允许创建新 Authority Operation
```

任何建议性后续任务必须先返回 Novel Forge，由 Authority 重新接受。

## 7.5 Claude Code 调用接口

建议提供稳定 CLI：

```bash
novel-forge orchestrator inspect --book book-001
novel-forge orchestrator next-actions --book book-001
novel-forge orchestrator submit-decision decision.json
novel-forge execution status --operation operation-001
novel-forge execution cancel --operation operation-001
novel-forge execution reconcile --operation operation-001
novel-forge book pause --book book-001
novel-forge book resume --book book-001
```

Claude Code 不直接调用内部 Python Service，不直接连接 PostgreSQL。

---

# 8. ExecutionRequest、Handle 和 Result

## 8.1 ExecutionRequest

```json
{
  "execution_id": "execution-001",
  "operation_id": "operation-001",
  "saga_id": "chapter-saga-21",
  "attempt_id": "attempt-003",
  "fencing_token": 19,
  "parent_execution_id": null,
  "origin_chain": [
    "human",
    "claude_code_orchestrator",
    "novel_forge_authority"
  ],
  "task_kind": "CHAPTER_DRAFT",
  "stage": "DRAFT",
  "book_id": "book-001",
  "chapter_id": "chapter-021",
  "importance_class": "CLIMAX",
  "risk_class": "HIGH",
  "route_snapshot_id": "route-snapshot-001",
  "workspace_snapshot_id": "workspace-snapshot-201",
  "input_manifest_ref": "input-manifest-001",
  "resource_claims": {
    "read_set": [
      "book:001:canon",
      "book:001:chapters:1-20",
      "book:001:arc:03"
    ],
    "write_set": [
      "book:001:chapter:21:draft"
    ]
  },
  "timeout_policy": {
    "soft_timeout_seconds": 1800,
    "hard_timeout_seconds": 2400,
    "termination_grace_seconds": 20
  },
  "budget_policy": {
    "quota_class": "EXPENSIVE_REASONING"
  },
  "permission_policy": {
    "workspace_mode": "STAGING_ONLY",
    "network_mode": "BACKEND_MANAGED",
    "environment_policy": "ALLOWLIST"
  }
}
```

## 8.2 ExecutionHandle

```json
{
  "execution_id": "execution-001",
  "backend_execution_id": "codex-local-001",
  "backend_id": "codex_cli",
  "local_process_id": 12345,
  "local_process_group_id": 12345,
  "local_process_start_time": "2026-07-22T20:10:00+08:00",
  "provider_request_id": null,
  "completion_mode": "POLL_LOCAL_PROCESS",
  "query_capability": "LOCAL_PROCESS_ONLY",
  "cancel_capability": "LOCAL_PROCESS_ONLY",
  "callback_capability": "UNSUPPORTED"
}
```

## 8.3 ExecutionResult

```json
{
  "execution_id": "execution-001",
  "outcome": "RESULT_AVAILABLE",
  "process_receipt_ref": "process-receipt-001",
  "provider_receipt_ref": null,
  "raw_output_ref": "artifact://execution-001/raw-output",
  "normalized_output_ref": "artifact://execution-001/normalized-output",
  "output_manifest_ref": "output-manifest-001",
  "usage_receipt_ref": "usage-receipt-001",
  "cost_receipt_ref": null,
  "validation_report_ref": null,
  "started_at": "2026-07-22T20:10:00+08:00",
  "completed_at": "2026-07-22T20:26:00+08:00"
}
```

字段可以为空，但必须有明确语义。例如本地 Codex 无法提供真正的 Provider Request ID 时，必须为 `null`，不能伪造为远程 Provider ID。

---

# 9. Model Profile 与环节路由

## 9.1 第一阶段 Profile

```yaml
model_profiles:
  codex.sol.high:
    backend_id: codex_cli
    model_provider: openai
    model_id: gpt-5.6-sol
    reasoning_effort: high
    quota_class: STANDARD_REASONING
    fallback_policy: FAIL_CLOSED

  codex.sol.xhigh:
    backend_id: codex_cli
    model_provider: openai
    model_id: gpt-5.6-sol
    reasoning_effort: xhigh
    quota_class: EXPENSIVE_REASONING
    fallback_policy: FAIL_CLOSED
```

这些 Profile 只有 Capability Probe 通过后才能进入 `ACTIVE`。

## 9.2 基础路由矩阵

| 生产环节 | 默认 Profile | 升级条件 |
|---|---|---|
| 题材候选生成 | `codex.sol.high` | 多题材融合、重大差异化设计时升级 |
| 商业定位 | `codex.sol.xhigh` | 默认深推理 |
| 核心创意 | `codex.sol.xhigh` | 默认深推理 |
| 世界观核心机制 | `codex.sol.xhigh` | 默认深推理 |
| 普通世界观补充 | `codex.sol.high` | 影响核心规则时升级 |
| 主角/核心反派 | `codex.sol.xhigh` | 默认深推理 |
| 普通配角 | `codex.sol.high` | 涉及核心伏笔时升级 |
| 全书大纲 | `codex.sol.xhigh` | 默认深推理 |
| 卷级大纲 | `codex.sol.xhigh` | 默认深推理 |
| 剧情弧设计 | `codex.sol.xhigh` | 默认深推理 |
| 普通章节组规划 | `codex.sol.high` | 跨弧、高潮前后升级 |
| 普通章节细纲 | `codex.sol.high` | 连续失败或高风险升级 |
| 高潮章细纲 | `codex.sol.xhigh` | 固定深推理 |
| 普通章节正文 | `codex.sol.high` | 重要章、失败重写升级 |
| 高潮章正文 | `codex.sol.xhigh` | 固定深推理 |
| 普通章节审稿 | `codex.sol.high` | 严重逻辑/Canon 冲突升级 |
| 卷末审稿 | `codex.sol.xhigh` | 固定深推理 |
| 普通修订 | `codex.sol.high` | 第二次修订或严重问题升级 |
| 深度重写 | `codex.sol.xhigh` | 固定深推理 |
| Canon 抽取 | `codex.sol.high` | 低置信度或冲突升级 |
| Canon 冲突裁决 | `codex.sol.xhigh` | 固定深推理 |
| 每 10 章复盘 | `codex.sol.xhigh` | 固定深推理 |
| 卷级复盘 | `codex.sol.xhigh` | 固定深推理 |
| 长篇一致性审计 | `codex.sol.xhigh` | 固定深推理 |
| Reader Outcome Judge | `codex.sol.high` | 多群体分歧或重大节点升级 |
| 发布前总审 | `codex.sol.xhigh` | 固定深推理 |

## 9.3 路由决策输入

最终路由函数不能只看环节：

```text
RouteDecision =
    Stage
  + ImportanceClass
  + RiskClass
  + ContextSizeClass
  + QualityHistory
  + RetryCount
  + CanonConflictLevel
  + QuotaStatus
  + RuntimeHealth
  + ModelDriftStatus
```

## 9.4 Reasoning Escalation Policy

推荐升级链：

```text
HIGH
→ HIGH RETRY
→ XHIGH
→ XHIGH WITH REBUILT CONTEXT
→ EDITOR REVIEW REQUIRED
```

可触发升级：

- 高潮章、卷首、卷末、结局；
- 核心伏笔揭示；
- 角色死亡、背叛或立场逆转；
- Review 发现严重逻辑冲突；
- Canon 置信度过低；
- 修订后仍未通过门禁；
- Context Builder 报告高等级冲突；
- 长篇复盘要求重新规划；
- Reader Outcome Judge 与 Quality Aggregate 明显分歧。

禁止无限升级。每个 Operation 必须配置：

```text
max_attempts
max_high_attempts
max_xhigh_attempts
max_context_rebuilds
max_budget
```

---

# 10. Capability Probe 和资格校验

Worker 启动和定期心跳时执行：

```text
Codex CLI executable probe
Codex CLI version probe
Authentication probe
Model availability probe
Reasoning effort probe
Structured output probe
Sandbox option probe
Ephemeral mode probe
Process group capability probe
Workspace access probe
```

Capability Probe 结果进入 RuntimeHostCapability：

```json
{
  "runtime_host_id": "mac-mini-01",
  "backend_id": "codex_cli",
  "cli_version": "detected-at-runtime",
  "available_models": ["gpt-5.6-sol"],
  "model_capabilities": {
    "gpt-5.6-sol": {
      "reasoning_efforts": ["high", "xhigh"],
      "structured_output": true
    }
  },
  "checked_at": "2026-07-22T20:00:00+08:00"
}
```

规则：

- `xhigh` 不可用时，`codex.sol.xhigh` 资格校验失败；
- 不允许静默降级到 `high`；
- CLI 版本变化后必须重新 Probe；
- Probe 失败的 Host 不得接收新任务；
- 已运行任务进入 Reconcile，而不是立即重派。

---

# 11. CodexCliExecutionBackend

## 11.1 组件拆分

```text
CodexCliExecutionBackend
├── CodexCapabilityProbe
├── CodexCommandBuilder
├── CodexEnvironmentBuilder
├── CodexProcessSupervisor
├── CodexOutputParser
├── CodexUsageParser
├── CodexResultNormalizer
├── CodexResultValidator
└── CodexProcessReconciler
```

## 11.2 从现有代码迁移

从 `LocalCodexCliWorkerMixin` 抽取：

```text
命令构造
模型参数
Profile 参数
Sandbox 参数
JSON Schema 文件
Output Last Message 文件
Prompt 输入限制
stdout/stderr 收集
Usage 解析
结构化输出验证
Runtime Guard
External execution evidence
```

旧 Adapter 在过渡期改为：

```text
Legacy Adapter
→ LegacyRequestMapper
→ ProductionExecutionGateway
→ CodexCliExecutionBackend
→ LegacyResultMapper
```

旧 Adapter 不再直接拥有进程执行实现。

## 11.3 命令构造原则

业务层不拼接 Codex 参数。CommandBuilder 根据 RouteSnapshot 构造命令：

```text
codex exec
+ explicit model
+ explicit reasoning effort/profile
+ explicit sandbox
+ explicit output schema
+ explicit output path
+ explicit working directory
+ automation isolation
+ ephemeral mode when supported
```

命令、CLI 版本和配置摘要进入 ExecutionManifest，但不得写入敏感凭据。

---

# 12. 本地进程监督

## 12.1 启动协议

```text
PREPARING
→ 创建持久化执行目录
→ 写 InputManifest 和 ExecutionManifest
→ 创建独立进程组
→ 记录 PID、PGID、start_time
→ 持久化 ProcessReceipt
→ RUNNING
```

## 12.2 取消协议

```text
CANCEL_REQUESTED
→ SIGTERM process group
→ 等待 termination_grace_seconds
→ SIGKILL process group
→ 验证子进程不存在
→ LOCAL_PROCESS_TERMINATED
```

必须区分：

```text
local_process_terminated
upstream_request_cancelled
```

上游状态枚举：

```text
CONFIRMED
UNSUPPORTED
UNKNOWN
NOT_APPLICABLE
```

本地进程终止后，如果无法确认上游请求状态，Attempt 应进入 `UPSTREAM_STATE_UNKNOWN` 或 `RECONCILING`，不能直接声称完整取消成功。

## 12.3 Worker 崩溃恢复

Worker 重启后扫描：

```text
RUNNING / CANCEL_REQUESTED / RECONCILING attempts
+ ProcessReceipt
+ PID/PGID/start_time
+ execution directory
```

处理：

| 状况 | 处理 |
|---|---|
| 进程仍在 | 重新接管监控 |
| 进程结束且结果完整 | 继续结果验证 |
| 进程不存在且无结果 | 标记 ORPHANED |
| PID 被复用 | 标记 ORPHANED |
| 结果文件部分写入 | 标记 CORRUPT_RESULT，禁止提交 |
| 状态无法确定 | 进入 RECONCILING |

## 12.4 进程回执

```json
{
  "process_receipt_id": "process-receipt-001",
  "execution_id": "execution-001",
  "host_id": "mac-mini-01",
  "pid": 12345,
  "pgid": 12345,
  "process_start_time": "2026-07-22T20:10:00+08:00",
  "exit_code": 0,
  "termination_signal": null,
  "stdout_ref": "artifact://execution-001/stdout",
  "stderr_ref": "artifact://execution-001/stderr",
  "started_at": "2026-07-22T20:10:00+08:00",
  "ended_at": "2026-07-22T20:26:00+08:00"
}
```

---

# 13. Workspace Transaction

## 13.1 Authority 与 Projection

```text
PostgreSQL / AssetStore = Authority
Book Workspace Files = Projection
Execution Staging = Untrusted candidate output
```

Codex 不得直接修改正式 Projection。

## 13.2 执行目录

推荐：

```text
<workspace-root>/
├── books/<book-id>/projection/
├── snapshots/<workspace-snapshot-id>/
└── executions/<execution-id>/
    ├── input/
    ├── staging/
    ├── output/
    ├── logs/
    └── manifests/
```

Execution 目录必须持久化到结果完成、审计完成和保留期结束，不能继续只使用自动删除的临时目录作为唯一证据。

## 13.3 五类 Manifest

### InputManifest

记录：

- Authority 输入版本；
- Context Bundle；
- Prompt Bundle；
- Skill Bundle；
- Book/Chapter/Arc/Canon 版本；
- 输入文件 Hash；
- Source Eligibility；
- Read Set。

### ExecutionManifest

记录：

- Operation、Attempt、Fence；
- RouteSnapshot；
- Backend、Host、Auth Profile 引用；
- CLI 版本；
- 命令摘要；
- 环境变量名称白名单；
- 超时策略；
- Release SHA。

### OutputManifest

记录：

- Raw Output；
- Normalized Output；
- stdout/stderr；
- 输出 Hash；
- 输出 Schema 版本；
- 文件清单。

### ValidationManifest

记录：

- Schema Validation；
- Semantic Validation；
- Canon Validation；
- Workspace Scope Validation；
- Source Isolation Validation；
- Copyright/Originality Validation；
- Quality Preflight；
- Fencing Validation。

### CommitManifest

记录：

- 被提交的 AssetVersion；
- Authority Commit ID；
- Projection Materialization；
- 被拒绝输出；
- 回滚引用；
- 提交时间。

## 13.4 提交流程

```text
Codex 输出到 staging
→ Output Normalizer
→ Schema Validation
→ Semantic Validation
→ Canon Validation
→ Workspace Scope Validation
→ Source Isolation Validation
→ Quality Preflight
→ Fencing Token Validation
→ Authority Commit
→ Projection Materialization
```

任何一步失败，候选输出只能留在 Staging，不得出现在正式章节和 Canon 中。

## 13.5 Fail-closed Workspace

生产模式必须：

```text
工作目录不存在 → 失败
工作目录未注册 → 失败
路径逃逸 → 失败
跨书访问 → 失败
Snapshot 版本不匹配 → 失败
Write Set 之外写入 → 失败
```

禁止回退到当前仓库目录或 `Path(".")`。

---

# 14. 三层幂等与重复执行治理

## 14.1 Authority Idempotency

```text
Stable Key = business intent identity
```

确保相同业务命令不会创建多个正式 Operation。

## 14.2 Execution Deduplication

```text
Execution Fingerprint =
Operation ID
+ Attempt generation
+ InputManifest hash
+ RouteSnapshot hash
+ WorkspaceSnapshot hash
```

确保重复派发可识别。

## 14.3 Provider Idempotency

远程 Provider 在支持时使用 Provider-side Idempotency Key。

Codex CLI 通常只能证明 Authority 和 Execution 两层，不能声明 Provider-side Idempotency。

Capability 应分别记录：

```text
authority_idempotency
execution_deduplication
provider_idempotency
```

## 14.4 重试规则

- 同一 Attempt 不得被并发执行两次；
- Worker 失联先 Reconcile，不立即重派；
- 只有确认旧执行终止或被 Fence 后，才能创建新 Attempt；
- 新 Attempt 的结果不能被旧 Fencing Token 覆盖；
- 从 high 升级 xhigh 必须创建新 RouteSnapshot；
- Prompt、Context 或 Skill 改变必须创建新 RouteSnapshot。

---

# 15. 执行状态机

正常路径：

```text
CREATED
→ ADMITTED
→ ROUTE_FROZEN
→ LEASED
→ PREPARING
→ STAGED
→ SUBMITTED
→ RUNNING
→ RESULT_AVAILABLE
→ VALIDATING
→ COMMITTING
→ SUCCEEDED
```

异常和恢复状态：

```text
RETRYABLE_FAILURE
FINAL_FAILURE
TIMEOUT_REQUESTED
CANCEL_REQUESTED
LOCAL_TERMINATION_SENT
LOCAL_PROCESS_TERMINATED
UPSTREAM_CANCEL_CONFIRMED
UPSTREAM_CANCEL_UNSUPPORTED
UPSTREAM_STATE_UNKNOWN
ORPHANED
CORRUPT_RESULT
RECONCILING
STALE_ATTEMPT
FENCING_REJECTED
VALIDATION_REJECTED
UNAUTHORIZED_MUTATION
DEAD_LETTER
EDITOR_REVIEW_REQUIRED
```

关键规则：

- `LOCAL_PROCESS_TERMINATED` 不自动等于 `CANCELLED`；
- `UPSTREAM_STATE_UNKNOWN` 不能立即释放全部预算并重试；
- `VALIDATION_REJECTED` 不能提交结果；
- `STALE_ATTEMPT` 的结果永久禁止写 Authority；
- `DEAD_LETTER` 必须提供可操作错误分类和恢复建议。

---

# 16. Auth、配额和成本治理

## 16.1 Billing Mode

支持：

```text
API_METERED
SUBSCRIPTION
ACCOUNT_QUOTA
LOCAL_MODEL
UNKNOWN
```

Codex CLI 使用订阅或账号额度时，不能把单次成本伪造为 `0 USD`。

## 16.2 Usage 和 Cost Precision

```text
usage_precision:
  REPORTED
  ESTIMATED
  UNAVAILABLE

cost_precision:
  EXACT
  ESTIMATED
  ALLOCATED
  UNAVAILABLE
```

## 16.3 配额池

```text
STANDARD_REASONING_POOL
EXPENSIVE_REASONING_POOL
SHADOW_EVAL_POOL
RECOVERY_POOL
```

`xhigh` 应有独立并发和额度限制。

## 16.4 Quota Window

记录：

```text
Auth Profile
Window Start/End
Request Count
Estimated Tokens
Rate-limit Events
Cooldown Until
Concurrent Executions
Xhigh Concurrent Executions
Last Successful Invocation
```

## 16.5 准入检查

Admission Controller 必须检查：

- ModelProfile 是否 ACTIVE；
- Host 是否 HEALTHY；
- AuthProfile 是否 ACTIVE；
- 当前并发是否超限；
- xhigh 配额是否足够；
- Book Budget 是否足够；
- Operation Budget 是否足够；
- Shadow 是否使用独立预算；
- Retry Budget 是否耗尽。

---

# 17. 环境变量与安全

当前本地进程执行不能继续默认继承完整 `os.environ`。

## 17.1 Environment Allowlist

默认允许：

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

按 Backend 显式增加，其余环境变量默认拒绝。

## 17.2 凭据注入

所有凭据通过：

```text
AuthProfileResolver
→ Secret Reference
→ Runtime-specific Injection
```

禁止：

- 把数据库密码传给 Codex；
- 把 MinIO Secret 传给 Codex；
- 把其他 Provider Key 全量传给子进程；
- 在 Manifest 中记录真实 Token；
- 在 stdout/stderr 中泄漏凭据。

## 17.3 沙箱模式

初期建议：

```text
Codex chapter/content task:
  filesystem = read-only snapshot + staging write
  network = backend managed
  subprocess = denied unless explicitly required
  git write = denied
```

复杂 Claude Code Agent Transaction 后续使用独立 Git Worktree 和审批式 Diff Commit。

---

# 18. 资源声明、锁和多书并发

每个 Work Order 必须声明：

```text
read_set
write_set
workspace_scope
canon_scope
chapter_range
```

示例：

```json
{
  "read_set": [
    "book:001:canon",
    "book:001:arc:03",
    "book:001:chapters:1-20"
  ],
  "write_set": [
    "book:001:chapter:21:draft",
    "book:001:canon-proposal"
  ]
}
```

可并行：

- 不同书籍生产；
- 同一本书互不冲突的只读评测；
- 素材清洗与章节审稿；
- Primary 和只读 Shadow Eval。

禁止并行：

- 同一章节两个正式 Draft；
- Canon 更新和依赖旧 Canon 的正式 Draft；
- 同一全书大纲两个 Authority Commit；
- 同一 Worktree 两个写任务；
- 同一 xhigh AuthProfile 超过并发限制。

后续可以从粗粒度 `BOOK_WRITE_LOCK` 演进到 Resource Claim Conflict Matrix。

---

# 19. 高级扩展

## 19.1 Eval 驱动路由

每次执行生成 `ModelPerformanceObservation`：

```text
Task Kind
Genre
Stage
Importance Class
Model Profile
Reasoning Effort
Prompt Version
Skill Version
Context Size
Latency
Usage
Validation Result
Quality Scores
Canon Conflict
Revision Count
Reader Outcome
Final Acceptance
```

Eval Center 输出 Route Recommendation：

```text
普通正文 high 一次通过率
高潮正文 high/xhigh 差异
Canon 抽取 high 是否足够
卷级复盘 xhigh 的收益
不同题材的最优 Profile
```

第一阶段只允许人工审批后更新 RoutePolicy。

## 19.2 Shadow Execution

```text
Primary: codex.sol.high
Shadow:  codex.sol.xhigh
```

Shadow 规则：

- 不写正式章节；
- 不写 Canon；
- 不改变 Saga；
- 不触发自动修订；
- 使用独立预算；
- 结果只进入 Eval Center。

推荐比例：

```text
普通章 1%–3%
重要章 5%–10%
新 Profile 上线时使用固定 Golden Set
```

## 19.3 Candidate / Judge / Ensemble

适用：

- 核心题材；
- 主角能力机制；
- 全书主线；
- 大反派；
- 卷级高潮；
- 结局；
- 大规模重构。

流程：

```text
Candidate A
Candidate B
Candidate C
→ Independent Judge
→ SelectionProposal / MergeProposal
→ Approval
→ Authority Commit
```

Judge 不能直接提交正式资产。

## 19.4 模型漂移检测

Golden Set 定期检测：

- 结构化输出成功率；
- Canon 抽取准确率；
- 逻辑冲突召回率；
- 人物一致性；
- 爽点和章节钩子；
- 重复表达；
- 文风稳定性；
- 延迟和失败率。

ModelProfile 状态：

```text
ACTIVE
DEGRADED
QUARANTINED
RETIRED
```

漂移严重时停止新任务，已运行任务继续 Reconcile。

## 19.5 多主机调度

支持：

```text
Mac mini
Ubuntu workstation
Cloud worker
```

调度输入：

```text
Required Capability
Host Health
Host Load
Auth Quota
Book Scope
Workspace Locality
Expected Duration
```

## 19.6 多账号治理

多 AuthProfile 不能随机轮换，必须记录：

- 账号并发；
- xhigh 并发；
- 限流；
- 冷却；
- 连续失败；
- 最近成功；
- 允许书籍；
- 允许任务类型。

账号选择进入 RouteSnapshot。

## 19.7 Agent Workspace Transaction

复杂任务：

- 整卷重构；
- 批量修订 10 章；
- 全书人物弧修复；
- 伏笔链调整；
- 后半部重新规划。

采用：

```text
Authority Snapshot
→ Git Worktree / Copy-on-write Workspace
→ Claude Code Agent 修改
→ Diff Report
→ Test and Validation
→ Approval
→ Authority Commit
→ Projection Materialization
```

## 19.8 事件流

统一事件：

```text
orchestration.decision_created
operation.accepted
route.frozen
execution.admitted
execution.started
process.spawned
provider.requested
usage.updated
artifact.created
validation.started
validation.failed
authority.committed
execution.completed
execution.cancel_requested
execution.orphaned
execution.reconciled
```

通过 PostgreSQL Outbox 分发到 Runtime Ledger、UI Timeline、Metrics 和 Eval Center。

## 19.9 熔断、退化与回退

Backend 状态：

```text
HEALTHY
DEGRADED
OPEN
HALF_OPEN
QUARANTINED
```

触发条件：

- 连续启动失败；
- 连续认证失败；
- 连续结构化输出失败；
- 连续超时；
- 限额耗尽；
- Host 失联；
- Capability Probe 失败；
- Golden Set 严重漂移。

回退原则：

- 关键创作任务默认 fail-closed；
- `xhigh` 不可用不得静默降级；
- 低风险分类和格式抽取可配置受控降级；
- 正文、全书大纲、卷级规划、高潮章、Canon 裁决、结局不得自动跨 Profile 降级；
- Fallback 必须生成 RouteDecision Evidence。

## 19.10 可进一步扩展的能力

后续还可以增加：

- Speculative Candidate Generation；
- Hierarchical Orchestration；
- Book-level Admission Scheduling；
- Cost-aware Batch Windows；
- Prompt/Skill A/B Testing；
- Context Bundle Compression Experiments；
- Cross-model disagreement analysis；
- Reader Cohort-specific Judge；
- Quality-risk-based priority queue；
- Publication deadline-aware scheduling。

这些能力必须继续建立在 Authority、RouteSnapshot、Manifest、Receipt 和 Eval Observation 上，不能成为新的旁路。

---

# 20. 数据模型建议

第一阶段核心表：

```text
execution_backends
backend_capabilities
model_profiles
route_policies
route_snapshots
runtime_hosts
runtime_host_capabilities
auth_profiles
quota_windows
execution_requests
execution_attempts
execution_handles
process_receipts
execution_manifests
execution_artifacts
execution_events
resource_claims
workspace_registry
workspace_snapshots
validation_reports
orchestration_runs
orchestrator_decisions
```

高级扩展表：

```text
model_performance_observations
route_recommendations
shadow_executions
model_drift_reports
golden_set_runs
ensemble_runs
judge_decisions
circuit_breaker_states
agent_workspace_transactions
```

## 20.1 数据归属

| 数据 | Authority |
|---|---|
| Operation/Saga/Attempt | PostgreSQL |
| RouteSnapshot | PostgreSQL |
| ProcessReceipt | PostgreSQL + Artifact reference |
| Raw stdout/stderr | ArtifactStore |
| Model raw output | ArtifactStore |
| Normalized output | ArtifactStore + AssetVersion |
| Canon/Chapter/Outline | PostgreSQL/Asset Authority |
| Workspace files | Projection |
| Auth secret | Secret store/local secure config |
| Eval Observation | PostgreSQL/analytics projection |

---

# 21. API、CLI 与 UI

## 21.1 API

建议：

```text
POST /product/orchestrator/decisions
GET  /product/orchestrator/runs/{run_id}
GET  /product/executions/{execution_id}
POST /product/executions/{execution_id}/cancel
POST /product/executions/{execution_id}/reconcile
GET  /product/model-profiles
GET  /product/route-snapshots/{id}
GET  /product/runtime-hosts
GET  /product/auth-profiles/status
GET  /product/quota-windows
GET  /product/execution-events
GET  /product/model-observations
```

写接口必须经过 Authority Operation，不允许路由直接写业务资产。

## 21.2 CLI

```text
orchestrator inspect
orchestrator next-actions
orchestrator submit-decision
execution status
execution cancel
execution reconcile
execution events
model-profile list
model-profile qualify
runtime-host probe
runtime-host health
quota status
workspace inspect
```

## 21.3 Web Admin

至少提供：

- Execution Timeline；
- Operation/Saga/Attempt 关系；
- RouteSnapshot；
- ModelProfile；
- Runtime Host Health；
- Auth/Quota Status；
- Process Receipt；
- Manifest Inspector；
- Validation Report；
- Cancel/Reconcile 操作；
- Shadow 对比；
- Drift Report；
- Route Recommendation 审批。

UI 只能调用受控 API，不能直接修改数据库状态。

---

# 22. 代码结构建议

```text
src/novel_forge/execution_plane/
├── contracts.py
├── gateway.py
├── admission.py
├── state_machine.py
├── registry.py
├── capabilities.py
├── manifests.py
├── receipts.py
├── reconciliation.py
├── events.py
├── routing/
│   ├── model_profiles.py
│   ├── route_policy.py
│   ├── route_resolver.py
│   ├── route_snapshot.py
│   └── escalation_policy.py
├── backends/
│   ├── base.py
│   ├── codex_cli/
│   │   ├── backend.py
│   │   ├── capability_probe.py
│   │   ├── command_builder.py
│   │   ├── environment.py
│   │   ├── parser.py
│   │   └── reconciler.py
│   ├── remote_provider/
│   │   └── backend.py
│   └── fixture/
│       └── backend.py
├── runtime_hosts/
│   ├── registry.py
│   ├── scheduler.py
│   └── health.py
├── process_supervision/
│   ├── supervisor.py
│   ├── process_receipt.py
│   └── orphan_recovery.py
├── auth/
│   ├── profiles.py
│   ├── resolver.py
│   └── quota_controller.py
├── workspaces/
│   ├── registry.py
│   ├── snapshot.py
│   ├── staging.py
│   └── transaction.py
└── eval_routing/
    ├── observations.py
    ├── shadow.py
    ├── drift.py
    └── recommendations.py
```

编排层：

```text
src/novel_forge/orchestration/
├── contracts.py
├── decision_service.py
├── work_order_service.py
├── policy.py
├── cli.py
└── claude_code_adapter.py
```

---

# 23. 当前文件级迁移方案

## 23.1 `model_adapters/providers.py`

处理：

- 抽出 Codex 命令构造；
- 抽出环境构造；
- 抽出进程监督；
- 抽出输出解析和 Usage 解析；
- Legacy Adapter 改为 Gateway 兼容包装器；
- 禁止生产路径继续直接使用 `LocalCodexCliWorkerMixin`。

## 23.2 `provider_control/`

保留：

- Provider Adapter v2；
- Provider Capability；
- Query、Cancel、Callback；
- Provider Receipt；
- OpenAI-compatible transport seam。

迁移到：

```text
RemoteProviderExecutionBackend
```

Provider v2 不删除，不强迫本地 Codex 伪装成远程 Provider。

## 23.3 `modules/model_router/`

收敛职责：

```text
Route Resolver
ModelProfile Registry
RoutePolicy
Route Recommendation read model
```

生产路径不再由 Model Router 直接调用旧 Adapter。

## 23.4 Chapter Authority

从 Provider-specific Gateway 迁移到：

```text
ProductionExecutionGateway
```

Chapter Authority 只提交 ExecutionRequest 和处理标准 ExecutionResult。

## 23.5 Book Authority

在真实单章证明之后，将脚本化章节派发替换为真实 Chapter Root Saga 委托，并聚合：

- Chapter Operation；
- Cost/Quota；
- Recap；
- Plan Adjustment Proposal；
- Pause/Resume；
- Failure Policy；
- Book-level Resource Claim。

## 23.6 Workspace

保留当前 ProjectWorkspaceState 作为部分业务状态，但新增物理 Workspace Registry、Snapshot 和 Transaction，不能把默认自动创建的 JSON 状态当作生产 Workspace 隔离证明。

## 23.7 `ClaudeCodeAdapter`

如果当前实现实际调用 Codex CLI：

```text
重命名/迁移为 CodexCliExecutionBackend
```

真正的 Claude Code Agent Backend 后续单独实现，用于复杂多文件 Agent Transaction。

---

# 24. 兼容层和归档

## 24.1 迁移前保存

```bash
git tag archive/model-execution-v1-before-convergence <sha>
```

只有旧版本仍需长期维护时才创建归档分支。

## 24.2 Compatibility Layer

建议：

```text
src/novel_forge/model_adapters/legacy_compat.py
```

需要记录：

```text
replacement
introduced_at
removal_gate
runtime_call_count
import_count
```

## 24.3 删除条件

只有满足以下条件后才能删除旧执行实现：

- 所有生产调用进入 ProductionExecutionGateway；
- 单章真实 Codex 证明通过；
- CLI 和 API 通过新 Gateway；
- Legacy Runtime Call Count 为零；
- 静态扫描无生产旧路径；
- 回归测试通过；
- 迁移文档记录恢复 Tag。

---

# 25. 测试矩阵

## 25.1 Contract Tests

- ExecutionRequest Schema；
- ExecutionHandle Schema；
- ExecutionResult Schema；
- Capability Profile；
- ModelProfile；
- RouteSnapshot；
- Manifest；
- Receipt；
- OrchestratorDecision。

## 25.2 Unit Tests

- Route Resolver；
- high/xhigh 选择；
- Escalation Policy；
- Capability Negotiation；
- Environment Allowlist；
- CommandBuilder；
- Usage Parser；
- Result Normalizer；
- Resource Conflict Matrix；
- Quota Controller；
- State Machine。

## 25.3 Process Tests

- 正常退出；
- 非零退出；
- stdout/stderr；
- JSON 缺失；
- JSON 破损；
- 超时；
- SIGTERM；
- SIGKILL；
- 子进程残留；
- PID 复用；
- Worker 重启；
- Orphan Recovery；
- Staging 保留。

## 25.4 Authority Tests

- Stable Key Replay；
- Stable Key Conflict；
- Lease Expiry；
- Fence Rejection；
- Duplicate Dispatch；
- Old Attempt Late Result；
- Budget Reservation；
- Cancel/Retry Race；
- Reconcile/Retry Race；
- Commit Manifest Binding。

## 25.5 Security Tests

- 环境变量泄漏；
- 路径逃逸；
- 跨书读取；
- Write Set 越权；
- 未注册 Workspace；
- Secret Log Redaction；
- Codex 反向启动 Claude Code；
- Agent Hop 超限。

## 25.6 Real Runtime Proof

顺序：

```text
Capability Probe
→ one controlled model invocation
→ one Chapter Draft
→ full single Chapter Saga
→ three chapters
→ ten chapters with recap
→ thirty chapters
→ multi-book concurrency
```

## 25.7 Advanced Evaluation Tests

- high/xhigh Shadow；
- Golden Set；
- Drift Detection；
- Route Recommendation；
- Candidate/Judge；
- Circuit Breaker；
- Multi-host Scheduling；
- Multi-account Quota。

---

# 26. 分阶段实施路线

## Phase 0：设计冻结和基线保护

交付：

- 本文档；
- ADR；
- 迁移前 Git Tag；
- Legacy Call Inventory；
- 当前执行路径图。

禁止：

- 立即删除 Provider v2；
- 立即删除旧 Adapter；
- 在业务模块新增直接 Codex 调用。

## Phase 1：统一协议

实现：

- ExecutionRequest；
- ExecutionHandle；
- ExecutionResult；
- ExecutionCapabilityProfile；
- ModelProfile；
- RoutePolicy；
- RouteSnapshot；
- Manifest；
- Receipt；
- 状态机。

不改变当前生产行为。

## Phase 2：持久化本地进程监督

实现：

- Process Group；
- ProcessReceipt；
- Persistent Execution Directory；
- Timeout/Cancel；
- Orphan Recovery；
- Environment Allowlist。

## Phase 3：Codex CLI Backend 抽取

实现：

- 从 `LocalCodexCliWorkerMixin` 抽取组件；
- 新 Backend；
- Legacy Compatibility Adapter；
- Capability Probe；
- high/xhigh Profile Qualification。

## Phase 4：Workspace Registry 和 Transaction

实现：

- Book Workspace Registry；
- Workspace Snapshot；
- Staging；
- 五类 Manifest；
- Fail-closed Path Policy；
- Authority Commit/Materialization。

## Phase 5：Claude Code 编排接口

实现：

- OrchestratorDecision；
- Inspect/Next Actions/Submit Decision；
- Agent Hop Policy；
- Plan Adjustment Proposal；
- Pause/Resume。

## Phase 6：真实单章证明

完整链：

```text
ChapterPlan
→ Context
→ Draft high/xhigh
→ Review
→ Revision
→ Re-review
→ Canon Extraction
→ Canon Approval
→ Quality Groups
→ Quality Aggregate
→ Publish Gate
→ Export
→ Final Release Gate
```

必须验证：

- 真实 Codex 执行；
- RouteSnapshot；
- high/xhigh；
- Usage；
- Timeout；
- Cancel；
- Reconcile；
- Duplicate Request；
- Worker Restart；
- Authority Commit。

## Phase 7：三章和十章证明

三章：

- Canon 传播；
- 人物一致性；
- Context Builder；
- Chapter dependency。

十章：

- Long-form Recap；
- xhigh Recap；
- Plan Adjustment Proposal；
- Artifact Growth；
- Quota Consumption；
- Performance。

## Phase 8：Book→Chapter 真实委托

实现：

- Book Root Saga 委托真实 Chapter Root Saga；
- Book-level Budget；
- Chapter Cost Rollup；
- Pause/Resume；
- Book Failure Policy；
- Recap Cadence。

## Phase 9：高级评测扩展

实现：

- ModelPerformanceObservation；
- Route Recommendation；
- Shadow Execution；
- Golden Set；
- Drift Detection；
- Circuit Breaker。

不允许自动在线更新 RoutePolicy。

## Phase 10：多主机、多账号和多书

实现：

- RuntimeHost Scheduler；
- AuthProfile；
- Quota Controller；
- Resource Claim Conflict Matrix；
- Multi-book Admission；
- Host Failover Reconciliation。

## Phase 11：Ensemble 和 Agent Transaction

实现：

- Candidate/Judge；
- Merge Proposal；
- Claude Code Agent Backend；
- Git Worktree Transaction；
- Diff Validation；
- Approval Commit。

---

# 27. Work Package 建议

```text
PEP-00 Architecture Decisions and Baseline
PEP-01 Execution Contracts
PEP-02 Model Profiles and Route Snapshots
PEP-03 Persistent Process Supervisor
PEP-04 Codex CLI Backend
PEP-05 Workspace Registry and Manifests
PEP-06 Production Execution Gateway
PEP-07 Claude Code Orchestrator Interface
PEP-08 Single Chapter Real Runtime Proof
PEP-09 Three/Ten Chapter Proof
PEP-10 Book-to-Chapter Delegation
PEP-11 Eval Observations and Shadow
PEP-12 Drift and Circuit Breaker
PEP-13 Multi-host and Multi-account
PEP-14 Multi-book Resource Scheduling
PEP-15 Ensemble and Agent Transactions
PEP-16 Legacy Path Retirement
```

每个 Work Package 必须包含：

- Scope；
- Non-goals；
- Schema migration；
- Code changes；
- Tests；
- Failure injection；
- Acceptance flags；
- Docs update；
- Rollback plan。

---

# 28. 验收标志

```text
execution_plane_contract_proven
production_execution_gateway_proven
claude_code_orchestration_proven
codex_cli_backend_proven
codex_capability_probe_proven
model_profile_resolution_proven
high_reasoning_route_proven
xhigh_reasoning_route_proven
route_snapshot_proven
persistent_execution_manifest_proven
local_process_tree_cancel_proven
orphan_recovery_proven
environment_allowlist_proven
workspace_registry_proven
workspace_isolation_proven
single_chapter_authority_proven
three_chapter_continuity_proven
ten_chapter_recap_proven
book_to_chapter_delegation_proven
quota_governance_proven
shadow_execution_proven
model_drift_detection_proven
multi_host_scheduling_proven
multi_account_governance_proven
multi_book_concurrency_proven
agent_workspace_transaction_proven
production_verified
```

任何 Flag 只能由对应自动化测试、运行回执和审计证据置为 true，不能由文档声明完成。

---

# 29. 非目标和禁止事项

第一阶段不做：

- 同时接入大量模型；
- 在线自动学习并修改生产路由；
- 无审批的大规模整卷重写；
- 把 Workspace 文件改成 Authority；
- 把 Claude Code 长会话当作长期记忆；
- 让 Codex 自主创建新 Operation；
- 静默从 xhigh 降级 high；
- 伪造 Provider Request ID；
- 把未知成本记录成 0；
- 因为本地启动 CLI 就声称推理完全本地；
- 因为本地进程结束就声称远程请求已取消；
- 将旧执行实现复制到主分支 archive 目录长期维护。

---

# 30. 最终生产闭环

```text
创作目标
→ Claude Code 读取当前 Authority 状态
→ Claude Code 提交 OrchestratorDecision
→ Command Kernel 接受并创建 Operation/Saga
→ Route Resolver 选择 high 或 xhigh
→ RouteSnapshot 冻结
→ Admission Controller 检查 Host/Auth/Quota/Budget/Resource Claim
→ Workspace Snapshot 和 InputManifest
→ CodexCliExecutionBackend 启动受控进程
→ ProcessReceipt 和 OutputManifest
→ Schema/Semantic/Canon/Security/Quality Validation
→ PostgreSQL Authority Commit
→ Workspace Projection Materialization
→ Runtime Ledger 和 ModelPerformanceObservation
→ Claude Code 读取结果并决定下一项任务
→ Eval Center 生成 Route Recommendation
→ 人工审批后更新后续 RoutePolicy
```

该闭环同时覆盖：

- 业务闭环；
- 模型执行闭环；
- 数据权威闭环；
- 异常恢复闭环；
- 质量反馈闭环；
- 配额和成本闭环；
- 长篇稳定闭环；
- 多模型演进闭环；
- 多书生产闭环。

---

# 31. 最终决策

Novel Forge 近期应固定以下生产组合：

```text
Claude Code
+ Novel Forge PostgreSQL Authority
+ Production Execution Plane
+ Codex CLI
+ codex.sol.high
+ codex.sol.xhigh
```

其中：

- Claude Code 决定“下一步应该做什么”；
- Novel Forge Authority 决定“是否允许、如何记录、何时正式生效”；
- Route Resolver 决定“使用 high 还是 xhigh”；
- CodexCliExecutionBackend 决定“如何安全、可恢复地执行”；
- Validation 和 Quality Gate 决定“结果是否具备提交资格”；
- Eval Center 决定“未来路由应如何优化”，但初期只输出建议。

统一生产执行平面必须作为现有 Provider v2、Model Router、本地 Codex 执行、Agent OS、Ops/Trace/Cost OS 和 Security/Sandbox OS 之间的上位收敛层，而不是新建一条旁路。
