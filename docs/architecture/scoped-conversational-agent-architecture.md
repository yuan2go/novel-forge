# Scoped Conversational Agent Architecture V1

> 更新日期：2026-07-29
> 适用分支：`feat/v7-content-intelligence-and-longform-proof`
> 实现基线：初始 HEAD `8613f743ca039f4ed13513e7eee51478df10487a`
> 状态：`architecture_defined + fixture_proven + integration_proven`
> 非声明：`real_runtime_proven=false`，`production_verified=false`

## 1. 定位与权威边界

Scoped Conversational Agent Architecture V1 是由领域 Authority 领导的、
有冻结作用域的业务协作 Saga，不是聊天产品，也不是第二套执行平台。

```text
PostgreSQL Authority
├── Operation / Saga / Attempt / Lease / Fence / Budget / Receipt
├── Collaboration Session / Turn / Message
├── Scope / Participant Snapshot
├── CandidateVersionGraph / Conflict / Decision
└── accepted Candidate -> versioned Authority AssetVersion

Agent Collaboration Domain
├── 决定议题、参与者、轮次、候选、冲突和终止
├── 执行 Scope Validation 与 Domain Acceptance
└── 请求 Authority Decision；自身不能提交正式资产

Production Execution Plane
├── Admission / RouteSnapshot / Dispatch / Backend
├── Timeout / Retry / Cancel / Reconcile
└── Execution Evidence / Usage / Cost

Runtime
└── deterministic service / Provider / Codex CLI / Agent Workspace / Fixture
```

正式状态只能由 PostgreSQL Authority 持有。LLM、Codex、Claude Code、Workspace、
内存 Session 和本地文件都不能成为 Collaboration 或正式资产权威。

## 2. Role、Capability、Runtime 分离

`AgentDefinition` 是版本化角色定义，包含角色、领域、输入输出合同、
Authority/Scope/执行/批准/质量策略引用，以及允许的工具和上下文类型。

`AgentCapability` 是独立版本化能力，包含输入输出 Schema、支持的 Message 和
Scope 类型、风险等级、执行要求与资格状态。Definition 通过显式版本引用
Capability；Agent 名称不等于能力。

`AgentWorkOrder` 同时冻结两种不同能力：

- `capability + capability_version`：业务 AgentCapability，例如
  `book-design.deliberate@1`；
- `execution_capability`：PEP 能力，例如 `agent.workspace.execute`。

因此：

```text
Agent Role != AgentCapability != PEP Capability != Model != Runtime
```

PostgreSQL 使用 Definition-Capability 复合外键阻止未声明能力的 WorkOrder。
PEP Route Policy 决定 Runtime；Agent 输出不能携带或覆盖路由决策。

## 3. 六维 Scope Contract

`AgentScopeContract` 是版本化合同，冻结后生成内容哈希稳定、身份独立的
`ScopeSnapshot`。

### 3.1 Narrative Scope

支持：

```text
BOOK > VOLUME > ARC > CHAPTER_GROUP > CHAPTER > SCENE
```

每一级必须携带完整祖先身份。包含关系要求同一本书、相同祖先路径，较窄 Scope
不能包含较宽 Scope。

### 3.2 Asset Read Scope

冻结可读资产类型、明确的 AssetVersion 白名单和禁止类型。WorkOrder 输入版本及
AgentOutput 的 source AssetVersion 都必须落在冻结白名单中。

### 3.3 Proposal Scope

冻结允许/禁止的资产类型与 change type。Agent 只能建议允许的候选变化，不能通过
自然语言绕过结构化 `ProposedAssetChange`。

### 3.4 Authority Scope

冻结哪个 Authority 可接受哪些 Narrative 层级和 change type。合法 Proposal
仍须由与 Scope 匹配的 Authority 决策；Agent 或 Judge 评分不产生接受权。

### 3.5 Temporal Scope

冻结：

```text
past_locked_through
active_range
forecast_horizon
published_boundary
```

修改锁定历史、越过发布边界或超出预测窗口会失败。

### 3.6 Knowledge Visibility Scope

支持：

```text
AUTHOR_KNOWLEDGE
CHARACTER_KNOWLEDGE
READER_KNOWLEDGE
PUBLIC_CANON
HIDDEN_PLANNING
```

输出必须声明访问的知识层。Reader Agent 读取隐藏结局会触发
`KNOWLEDGE_VISIBILITY_VIOLATION`。

运行中 Session 的 `scope_snapshot_ref` 不可原地改写。相同合同内容可产生不同
Snapshot 身份，以便不同 Session 保持独立冻结和谱系。

## 4. Session 与确定性状态机

正常路径：

```text
CREATED
→ SCOPE_FROZEN
→ PARTICIPANTS_ASSIGNED
→ INITIAL_PROPOSAL_PENDING
→ DELIBERATING
→ REVISION_PENDING
→ EVALUATING
→ CONSENSUS_REACHED
→ AUTHORITY_DECISION_PENDING
→ ACCEPTED
→ COMMITTED
```

异常/停止状态：

```text
SCOPE_VIOLATION
CONFLICT_UNRESOLVED
BUDGET_EXHAUSTED
MAX_ROUNDS_REACHED
HUMAN_DECISION_REQUIRED
ESCALATED
REJECTED
CANCELLED
FAILED
```

模型不能返回 Session 的下一状态。`CollaborationStateMachine`、
`TerminationPolicy` 和应用服务根据结构化消息、冲突、预算、轮次与 Authority
Decision 推进状态。Session 使用乐观版本号防止并发 Worker 同时推进。

`TerminationPolicy` 支持：

- max rounds / turns / executions / budget；
- 必需参与者和评价角色；
- blocking / major issue 阈值；
- unresolved conflict / scope violation 策略；
- V1 固定为 `AUTHORITY_LED` consensus。

## 5. Message 与 Output 协议

支持的 `AgentMessageType`：

```text
PROPOSAL
CHALLENGE
COUNTER_PROPOSAL
REVISION
EVIDENCE
IMPACT_ASSESSMENT
SUPPORT
OBJECTION
EVALUATION
SCOPE_EXPANSION_REQUEST
ESCALATION_REQUEST
DECISION_RECOMMENDATION
AUTHORITY_DECISION
```

`AgentOutputEnvelope` 保存结构化 payload、自然语言说明、来源版本、证据、
假设、置信度、影响资产、结构化 proposed changes、保留约束、风险与
Execution Evidence 引用。

`AgentConversationMessage` 从通过验证的 Envelope 确定性生成，引用 sender、
recipient、target Candidate/Proposal、ScopeSnapshot、Evidence、parent Message
和 Turn。Challenge、Revision、Evaluation 等目标型消息必须引用 Candidate。

自然语言只供解释和审计；领域服务只依据结构化字段推进。

## 6. CandidateVersionGraph

Proposal、CounterProposal 和 Revision 产生不可变 `CandidateVersion`：

```text
candidate_version_id
parent_version_ids
originating_message_id / turn_id
created_by_agent
scope_snapshot_ref
content_ref
structured_diff
change_reason_refs
preserved_constraints
resolved_conflicts / unresolved_conflicts
validation_status
```

创建时验证父节点存在且属于同一 Session。数据库父边包含顺序和唯一约束；
候选、父边、Message、Output、WorkOrder 与 Snapshot 均有不可变触发器。

重复 candidate ID 只有内容完全相同才视为幂等重放。谱系查询按父序深度优先，
Authority Asset 中保存完整 `candidate_lineage`，可以追踪最终正式版本的来源路径。

## 7. Conflict 与 Scope Expansion

`ConflictRecord` 记录类型、严重度、提出者、目标 Candidate、冲突资产版本、
Claim、Evidence、影响 Scope/Asset、读者结果/连续性/结局可达性影响和请求解法。

- 未解决 `BLOCKING` Conflict 阻止 Authority Decision 和 Commit；
- 非阻断异议可以随接受保留为 `ACCEPTED_NON_BLOCKING`；
- Conflict 绑定最终 Decision，不能在接受时静默丢失；
- Revision 可以显式解析 Conflict，并留下 resolution ref。

跨 Scope 根因采用：

```text
Agent 发现跨域问题
→ ScopeExpansionRequest
→ 当前 Session = ESCALATED
→ 对应 Authority 决策
→ APPROVED 时创建新 ScopeSnapshot
→ 原 Session 仍引用旧 Snapshot
→ 后续以新 Session 使用新 Snapshot
```

扩域必须是当前 Narrative Scope 的严格上层且属于同一本书。Agent 不能自行修改
Session Scope；批准决策不绑定未通过 Scope Validation 的 Candidate。

## 8. Authority-led Deliberation

V1 不采用多数投票：

1. Proposal Owner 提交 Proposal；
2. 专业 Agent 提交 Challenge、Objection 或 CounterProposal；
3. Owner 根据质询生成新 CandidateVersion；
4. Judge 提交 Evaluation，但评分不是最终真值；
5. 未解决异议继续保留；
6. Blocking Conflict 未解决时不得请求 Decision 或 Commit；
7. 非阻断异议可由 Authority 带异议接受；
8. 跨 Scope 或重大价值取舍进入升级/人工决策；
9. 轮次、执行数或预算达到上限时确定性停止；
10. 只有对应 Domain Authority 可接受并提交。

`CollaborationDecision` 支持 Accepted、Rejected、Repair、Deferred、Replan、
Human Decision 和 Scope Expansion approve/reject。正式资产提交只能由注入的
`AuthorityAssetCommitPort` 执行。

## 9. 每个 Turn 与 PEP 的闭环

```text
AgentCollaborationApplication.execute_turn
→ freeze/persist AgentWorkOrder
→ existing Authority Operation / Attempt / Fence
→ DomainExecutionPort
→ ProductionExecutionGateway
→ qualified Backend
→ DomainExecutionCandidate + Execution Evidence
→ AgentOutputEnvelope schema validation
→ Scope validation
→ Domain Acceptance
→ Message / Conflict / Candidate persist
→ deterministic Session continuation
```

WorkOrder 冻结 project/workspace/book、domain AgentCapability、PEP capability、
Operation/Attempt/Fence、RouteSnapshot、InputManifest、Scope/Participant Snapshot、
输入 AssetVersions、当前 Candidate、策略与验收条件。

生产 Repository 拒绝没有 PEP Evidence 的 AgentOutput。Evidence 必须与 WorkOrder
的 Operation、Attempt、Fence、execution capability、RouteSnapshot 和
InputManifest 完全一致。

成功层级保持分离：

```text
Backend Success
≠ Schema Validation
≠ Scope Validation
≠ Domain Acceptance
≠ Message Accepted
≠ Candidate Created
≠ Authority Decision
≠ Authority Commit
≠ Attempt Completion
```

例如 Fixture Backend 成功返回修改结局的 JSON，最终仍是
`REPLAN_REQUIRED + SCOPE_VIOLATION`，不会产生 Message 或 Candidate。

PEP 不包含 `core_advantage`、Canon、Arc 或读者结果等小说业务语义。

## 10. PostgreSQL Authority 持久化

迁移 `20260728_0033_agent_collaboration_v1` 新增：

- Agent Capability / Definition / Definition-Capability；
- Scope / Participant Snapshot；
- Collaboration Session / Turn / WorkOrder / Output / Message；
- CandidateVersion / CandidateParent；
- ConflictRecord / ScopeExpansionRequest / CollaborationDecision；
- Collaboration Commit。

它复用现有：

```text
authority_operation
authority_saga
authority_attempt
authority_lease_acquisition
authority_asset_version
```

没有 `agent_attempts` 或 `conversation_execution_attempts`。

关键约束包括 Operation/Attempt/AssetVersion 外键、Definition-Capability
复合外键、Session 乐观版本、Turn 和 Output 幂等唯一键、每 Session 唯一 Commit、
FK 查询索引、状态 CHECK 与不可变触发器。

取消是保留审计记录的终止状态，不做硬删除。已提交资产版本沿用 Authority
AssetVersion 的 supersession/失效语义。

## 11. 幂等、恢复与重放

- 重复 Turn/Output 返回已存 `TurnProcessingResult`，不再次执行 PEP 或推进计数；
- 相同 ID 不同内容失败关闭；
- WorkOrder 持久化前验证 RUNNING Attempt 和当前 HELD Fence；
- stale Fence Worker 不能提交 WorkOrder；
- Session、Message、Candidate、Conflict、Decision 和 Commit 可从 PostgreSQL
  完整恢复，不依赖 Runtime 聊天历史；
- Candidate 和 Message 使用不可变记录，rerun 必须使用新 Turn/Version；
- Authority Asset、Collaboration Commit 与 Session COMMITTED 在同一 UoW；
- Commit 前 Worker 崩溃时整笔事务回滚，重启后可幂等重放；
- 已提交 Session 重放返回同一 AssetVersion，不重复提交。

PEP 的 Usage/Cost/Receipt 仍由现有 Operation/Attempt/ExternalEffect 体系负责，
Collaboration 不建立第二套费用或 Attempt 权威。

## 12. V1 纵向切片证据

Fixture 场景“主角核心优势机制设计”使用：

```text
Character Design Agent
→ Initial Proposal / Candidate v1
Plot Architecture Agent
→ Challenge / PLOT_SCALABILITY Conflict
Character Design Agent
→ Revision / Candidate v2 / resolve Conflict
Reader Outcome Judge
→ Evaluation
Book Design Authority Stub
→ ACCEPTED with non-blocking objection
PostgreSQL Authority
→ versioned book_design_core_advantage AssetVersion
```

四个 Turn 均通过 `ProductionExecutionGateway` 的 Scripted Fixture Backend，
随后进入同一套 Output、Scope、Domain Acceptance、Message、Candidate 和 Commit
路径。测试销毁每轮 UoW 后从 PostgreSQL 恢复。

异常切片同样经过 Gateway：Character Agent 尝试 `ending.replace`，Backend
Success，但 Scope Validation 拒绝，正式 Candidate 主图保持为空。

## 13. Book Design Authority 后续接入

V1 的 Book Design Authority 是最小 Commit Adapter，不是完整 Book Design
Authority。后续接入应：

1. 用真实 BookDesign Schema 替换 fixture candidate content ref；
2. 由 Book Root Operation 创建 Collaboration Saga 和各 Turn Operation；
3. 使用生产 RouteSnapshot、持久 Execution Evidence、Usage/Cost hard stop；
4. 将 Decision 转为 BookDesign Authority Command；
5. 保留本 V1 的 Scope、Message、Candidate、Conflict、Decision 和 Commit 合同；
6. 增加真实 Provider/Codex 资格与端到端生产验证，不修改 proof flag 含义。

## 14. 证据等级

| 等级 | V1 状态 | 含义 |
|---|---:|---|
| `architecture_defined` | true | 合同、边界、状态机与迁移已定义 |
| `fixture_proven` | true | Scripted Fixture 走真实 Gateway/Domain 路径 |
| `integration_proven` | true | PostgreSQL Authority 恢复、Fence、Commit 已验证 |
| `real_runtime_proven` | false | 未执行真实 Codex/Claude/Provider Agent Runtime |
| `production_verified` | false | 未完成生产环境、真实预算和运行验收 |
