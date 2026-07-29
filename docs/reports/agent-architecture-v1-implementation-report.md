# Agent Architecture V1 Implementation Report

> 日期：2026-07-29
> 分支：`feat/v7-content-intelligence-and-longform-proof`
> 初始 HEAD：`8613f743ca039f4ed13513e7eee51478df10487a`
> 工作包：Scoped Conversational Agent Architecture V1

## 1. 总体判断

原实现已经有 Agent Role Profile、Agent Run/Checkpoint/Budget/Gate、Agent
Workspace Backend、ProductionExecutionGateway，以及 PostgreSQL
Operation/Saga/Attempt/Lease/Fence/AssetVersion Authority，但缺少生产级的
“有界多 Agent 协作”领域。

主要问题是：

- `agents/runtime.py` 的角色常量不是版本化 AgentDefinition Registry；
- 本地 `agent_messages` 是文件型自由消息总线，不是 Authority Conversation；
- PEP `TargetScope` 是执行定位，不是小说协作所需六维 Scope；
- 没有冻结 Participant/Input AssetVersion 的 Collaboration Session；
- 没有结构化 Challenge/Objection、CandidateVersionGraph、Conflict 或
  ScopeExpansion；
- Agent Workspace 已是 candidate-only，但没有把每轮候选接回领域仲裁和
  Authority Commit；
- 长期协作若建立在 Runtime Chat history 上，将无法由 PostgreSQL 恢复。

本次修复采用“独立 Collaboration 领域 + 现有 Authority/PEP”方案：

```text
Authority creates bounded Collaboration Saga
→ each Turn uses existing Operation/Attempt/Fence and PEP
→ Collaboration validates Message/Scope/Candidate/Conflict
→ Domain Authority decides
→ existing AssetVersion Authority commits
```

没有建立第二套 Attempt、执行状态机或 Provider 调用器。

详细代码事实审计见
`docs/reports/agent-architecture-v1-code-fact-audit.md`。

## 2. 实现清单

### 2.1 新增

| 文件 | 内容 |
|---|---|
| `src/novel_forge/modules/agent_collaboration/domain.py` | Definition、Capability、六维 Scope、Message、Session、Candidate、Conflict、Decision、Termination |
| `src/novel_forge/modules/agent_collaboration/repository.py` | Repository Port、test-only in-memory seam、Commit record |
| `src/novel_forge/modules/agent_collaboration/application.py` | Collaboration 应用服务、PEP Turn、状态推进、仲裁与恢复 |
| `src/novel_forge/modules/agent_collaboration/__init__.py` | 公共领域 API |
| `src/novel_forge/storage/agent_collaboration_repositories.py` | PostgreSQL Repository 与 Authority Asset Commit Adapter |
| `src/novel_forge/storage/migrations/versions/v20260728_0033_agent_collaboration_v1.py` | 0033 Authority Schema |
| `tests/architecture/test_agent_collaboration_boundaries.py` | Runtime/Provider/第二 Attempt 边界守卫 |
| `tests/unit/test_agent_collaboration_scope.py` | 六维 Scope 与越权 |
| `tests/unit/test_agent_collaboration_domain.py` | Definition、Message、状态机、Decision、Termination |
| `tests/unit/test_agent_collaboration_application.py` | 应用服务、幂等、恢复、扩域、仲裁、PEP Evidence |
| `tests/unit/test_agent_collaboration_candidate_graph.py` | 多父版本、谱系、不可覆盖 |
| `tests/unit/test_agent_collaboration_migration.py` | Schema/约束/索引/无第二 Attempt |
| `tests/unit/test_agent_collaboration_pep.py` | 真实 Gateway Fixture 与 Domain Reject |
| `tests/integration/test_agent_collaboration_postgres.py` | PostgreSQL 纵向切片、Fence、崩溃恢复与 Commit |
| `docs/architecture/scoped-conversational-agent-architecture.md` | V1 架构 |
| `docs/reports/agent-architecture-v1-code-fact-audit.md` | 修改前代码事实审计 |
| `docs/reports/agent-architecture-v1-implementation-report.md` | 本报告 |
| `docs/superpowers/plans/2026-07-28-scoped-conversational-agent-architecture-v1.md` | 实施计划 |

### 2.2 修改

| 文件 | 修改 |
|---|---|
| `src/novel_forge/storage/authority_repositories.py` | 在现有 UoW 暴露 Collaboration Repository |
| `src/novel_forge/storage/migrations/versions/__init__.py` | 注册 0033 为 latest |
| `scripts/run_authority_postgres_tests.py` | 将 Collaboration PostgreSQL 测试纳入不可跳过门禁 |
| `docs/README.md` | 将 V1 架构加入当前文档入口与阅读顺序 |
| `docs/architecture/production-execution-plane.md` | 增加 Agent Turn PEP 语义 |
| `docs/project-current-state.md` | 增加 V1 当前状态和保守 proof flags |
| `tests/integration/authority_postgres_support.py` | 修正隔离 PostgreSQL 默认连接，不污染全局 Settings |
| `tests/unit/test_chapter_authority_definitions.py` | 对齐现有独立 `model.rereview` Capability |
| `tests/unit/test_os_new_capabilities.py` | MCP HTTP 假响应补齐隔离层要求的 status evidence |

### 2.3 删除与迁移

没有删除旧业务资产或手改 `.claude/skills`。

旧 `agent_messages` 保留为 local/development 能力，但不能作为生产
Collaboration Authority。新生产路径使用 0033 PostgreSQL Schema。后续调用方应
迁移到 `AgentCollaborationApplication`，不得把本地 Message Bus 适配成正式状态。

## 3. 核心模型

### AgentDefinition 与 AgentCapability

Definition 冻结角色、合同、策略、工具和上下文权限；Capability 冻结结构化输入输出、
Message/Scope 支持、风险和资格。WorkOrder 使用 Definition version 与 domain
Capability version 的复合外键。

PEP `execution_capability` 单独冻结，避免把 Role、业务能力和 Runtime 混成一个名称。

### ScopeContract

正式实现 Narrative、Asset Read、Proposal、Authority、Temporal、Knowledge
Visibility 六维合同。ScopeSnapshot 内容不可变，Session 只能引用冻结 Snapshot。

### CollaborationSession

Session 保存 Authority、Goal、Issue、Scope/Participant Snapshot、当前 Candidate、
轮次/执行/预算计数、Termination policy、创建 Operation、Saga 与 Decision ref。
状态由确定性 StateMachine 推进，PostgreSQL version 提供并发 CAS。

### ConversationMessage

Message 覆盖 Proposal、Challenge、CounterProposal、Revision、Evidence、Impact、
Support、Objection、Evaluation、ScopeExpansion、Escalation、Recommendation 和
AuthorityDecision。目标型消息必须引用 Candidate，所有消息引用 Turn、Scope 和
Evidence。

### CandidateVersionGraph

候选是不可变节点，支持多父 Revision/Merge、结构化 Diff、reason refs、
preserved constraints 和 conflict refs。相同 ID 不同内容失败关闭。正式资产保存
完整 candidate lineage。

### ConflictRecord

Conflict 保存业务 Claim、证据、Scope/Asset 影响、Reader Outcome、Continuity 和
Ending Reachability。Blocking Conflict 阻止 Decision/Commit；非阻断异议可随
Decision 保留并链接 Authority Decision。

### CollaborationDecision

只有冻结 Scope 对应的 Authority 可提交 Accepted、Rejected、Repair、Deferred、
Replan、Human Decision 或 Scope Expansion 决策。Scope Expansion Decision 不绑定
被 Scope 拒绝的 Candidate；批准必须生成新 Snapshot，原 Session Scope 不变。

## 4. PEP 集成

每个生产 Turn：

```text
Authority Session/Saga
→ persisted AgentWorkOrder
→ existing Operation / RUNNING Attempt / HELD Fence
→ DomainExecutionPort
→ ProductionExecutionGateway
→ qualified Backend
→ DomainExecutionCandidate / Evidence
→ AgentOutputEnvelope repair/schema validation
→ Scope Validation
→ Domain Acceptance
→ Message / Candidate / Conflict
→ Session Continue
```

WorkOrder 和 Evidence 双向绑定：

- project / workspace / book；
- Operation / Attempt / Fence；
- domain Capability 与 PEP execution capability；
- RouteSnapshot / InputManifest；
- Scope / Participant Snapshot；
- input AssetVersions / current Candidate；
- budget / timeout / approval / failure / continuation policy。

生产 Repository 在没有 PEP Evidence 时拒绝 Output。Backend exit success 不会直接
完成 Turn。`TurnProcessingResult` 显式记录 Backend、Output、Schema、Scope、
Domain、Message、Candidate、Decision、Commit 与 Attempt-completion gate。

PEP 仍不理解小说语义；所有 Scope、Conflict 和 Candidate 决策位于 Collaboration
领域。

## 5. 测试证据

新增 46 个测试：

- 40 个 unit / architecture 测试；
- 6 个 PostgreSQL Collaboration 集成测试。

重点证据：

- 六维 Scope、包含关系、隐藏结局、Canon、已发布章节越权；
- 正常/非法状态转换、重复 Turn、取消、恢复、预算/轮次/执行数/人工门禁；
- 多父 Candidate、不可覆盖、幂等与谱系；
- PEP Route/Input/Attempt/Fence Evidence 绑定；
- malformed Output 为 `REPAIR_REQUIRED`；
- Backend Success + Domain Scope Reject；
- PostgreSQL 重启恢复，不依赖 Runtime history；
- stale Fence 拒绝；
- duplicate Output/Candidate/Commit；
- Commit 前崩溃整笔回滚，重启后只提交一个 AssetVersion；
- Scope Expansion Authority Decision 生成新 Snapshot，不修改旧 Snapshot；
- 非阻断 Conflict 随接受保留并绑定 Decision。

已确认：

```text
focused_agent_tests=40/40
postgres_authority_tests=111/111
postgres_collaboration_tests=6/6
postgres_migration_clean_and_0007_upgrade=2/2
skipped_in_postgres_authority_gate=0
mypy_new_collaboration_sources=5/5
```

首次完整回归在显式全局数据库环境下运行 1286 tests，暴露 5 个失败：

- 3 个 Settings 测试被全局 `NOVEL_FORGE_DATABASE_URL` 污染；
- 1 个旧 Chapter Definition 测试仍期望 `model.review`，代码事实是
  `model.rereview`；
- 1 个 MCP fake response 缺少新隔离 HTTP 层读取的 status。

三类问题均已修复，五个失败测试定向复跑为 5/5。最终完整回归结果：

```text
python_full_regression=1286/1286
python_skipped=9
web_tests_passed=11
web_tests_skipped=1
full_regression_failures=0
compileall=passed
workspace_validation=passed
git_diff_check=passed
```

Python 跳过项是普通 `make test` 下未启用的独立 PostgreSQL/online/长链等 opt-in
测试；本工作包要求的 PostgreSQL Authority 门禁另行运行并为 111/111、跳过 0。
Web 唯一跳过项是未安装 Playwright 时保留的可选浏览器 smoke。没有删除测试、放宽
断言或把失败项隐藏到 proof flags。

## 6. 纵向切片证据

```text
Turn 1 Character Agent
PROPOSAL
→ candidate:v1

Turn 2 Plot Agent
CHALLENGE: missing escalating cost
→ ConflictRecord(PLOT_SCALABILITY, MAJOR)

Turn 3 Character Agent
REVISION: add irreversible escalating cost
→ candidate:v2(parent=v1)
→ resolve PLOT_SCALABILITY

Turn 4 Reader Outcome Judge
EVALUATION: accept with non-blocking calibration objection

Book Design Authority Stub
ACCEPTED
→ non-blocking objection retained
→ PostgreSQL Authority AssetVersion
```

谱系：

```text
candidate:v1
└── candidate:v2
    ├── originating Challenge reason ref
    ├── resolved Conflict ref
    └── accepted Authority Decision
```

每个 Turn 都经过 `ProductionExecutionGateway` Scripted Fixture，并在独立
PostgreSQL UoW 后恢复。正式测试资产包含 Session、Candidate、完整 lineage、
originating Message/Turn、ScopeSnapshot、Diff、constraints、conflicts、Decision
和 proof flags。

异常链：

```text
Character Agent proposes ending.replace
→ Gateway Backend Success
→ Envelope Schema Passed
→ Proposal Scope Failed
→ REPLAN_REQUIRED / SCOPE_VIOLATION
→ Message not accepted
→ Candidate not created
→ no Authority Commit
```

## 7. 剩余差距

### Agent Architecture V1

合同、PostgreSQL Authority、PEP 接口、Authority-led fixture slice 和恢复语义已
完成。它不是完整 autonomous Agent Center。

### PEP 语义闭合

Collaboration 到 PEP 的 WorkOrder/Evidence/Domain Acceptance 接口已闭合。
现有 PEP PostgreSQL recovery tests 可持久恢复 Execution Record/Evidence。

### PEP Runtime 尚缺

- 本工作包没有运行真实 Provider、Codex CLI 或 Claude Code Workspace；
- 没有完成 Collaboration 专用 Scheduler composition root；
- 没有证明真实模型 usage/cost hard stop；
- 没有扩大整个 ProductionExecutionCoordinator 的 operation coverage；
- Fixture 不构成真实性能、质量、超时或供应商恢复证明。

### Book Design Authority

当前是最小 Authority Commit Adapter，只提交
`book_design_core_advantage` 测试资产。尚未实现正式 BookDesign aggregate、
Book Cursor、完整影响分析和 Book→Volume→Arc 规划。

### Proof 边界

```text
real_provider_proven=false
codex_cli_backend_proven=false
book_design_authority_proven=false
longform_proven=false
production_verified=false
```

## 8. 完成门禁

```text
agent_definition_contract_proven=true
agent_scope_contract_proven=true
agent_conversation_message_proven=true
agent_collaboration_session_proven=true
candidate_version_graph_proven=true
conflict_record_proven=true
scope_expansion_proven=true
authority_led_deliberation_proven=true
agent_turn_pep_integration_proven=true
collaboration_recovery_proven=true
book_design_collaboration_fixture_proven=true
```

这些 `true` 只表示合同/Fixture/PostgreSQL 集成证据，不提升真实 Runtime 或生产
成熟度。

## 9. 下一工作包建议

下一工作包应为：

```text
Book Design Authority Collaborative Vertical Slice
```

理由：PEP 的 Collaboration 语义接口已经闭合，当前阻塞点是将最小 Authority
Stub 替换为正式 BookDesign aggregate、Command 和影响分析，而不是再设计一套
执行协议。

该工作包必须同时使用现有持久 PEP Execution Record Store、真实 BookDesign
Schema 和 Book Root Saga；若接入时发现 Scheduler 尚不能生成完整冻结
ExecutionRequest，应把该缺口作为 Book slice 内的前置
`Production Execution Semantic Closure` 子任务处理，而不是建立旁路。
