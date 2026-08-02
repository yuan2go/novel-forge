# AC-11 Agent Collaboration

状态：`PLANNED`  
阶段：Phase 3 / Intelligence and Decision Closure  
前置依赖：AC-04、AC-05、AC-06、AC-09

## 1. ADR

### 背景

当前工程已经具备 AgentDefinition、Capability、ScopeSnapshot、ParticipantSnapshot、WorkOrder、Turn、Candidate、Conflict、Decision 和 Commit 的第一阶段实现。后续若每个 Agent 自行读取无限上下文、直接调用模型、更新领域资产或推进工作流，Agent Center 会演变为第二套执行系统和越权写入入口。

### 决策

Agent 负责分析、推理、提出候选、挑战和建议；Authority 负责冻结输入、执行 admission、验证 Candidate、处理冲突、批准并 Commit 正式状态。

统一流程：

```text
Authority WorkOrder
→ Frozen Scope / Participants / Inputs
→ Agent Turn through Production Execution Plane
→ Output Envelope Validation
→ Candidate / Challenge / Conflict
→ Authority Decision
→ Domain Commit
```

Agent 不得直接：修改 Plan/Canon/StoryState、激活 AssetVersion、推进 Book Cursor、发布内容、分配预算或调用外部平台。

## 2. 核心契约

### AgentDefinition 与 AgentCapability

Definition 描述角色、职责和版本；Capability 描述可执行的领域行为。领域 Capability 与 Production Execution Capability 必须分离，避免“能调用模型”等同于“有权提交资产”。

### AgentWorkOrder

必须绑定：project/workspace/book、Operation/Attempt/Fence、ScopeSnapshot、ParticipantSnapshot、InputManifest、ContextManifest、RouteSnapshot、目标 Candidate type、acceptance policy、budget/deadline。

### Candidate Graph

Candidate 不被原地覆盖：

```text
Candidate v1
├── Challenge
├── Alternative Candidate
├── Conflict
└── Revision Candidate v2
```

每条边记录 reason、evidence、actor、turn 和 scope。

### Authority Decision

Decision 必须说明 accepted/rejected/deferred、保留异议、选择的 Candidate、验证结果、Commit target 和后续任务。

## 3. 实施范围

- 收敛 Agent registry、runtime profile、collaboration session 和 PEP；
- 建立 Candidate schema registry 和领域 validator；
- 建立 scope expansion、conflict、escalation 和 human review；
- 建立 Agent handoff，但 handoff 仍是 WorkOrder，不传递隐式权限；
- 建立 deterministic coordinator，禁止模型控制 Saga 状态；
- Agent 输出中 route/commit/activation 声明必须标记 proposed_only 或被拒绝；
- 建立 session recovery、turn idempotency 和 candidate lineage。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/agent_collaboration/`
- `src/novel_forge/modules/agent_registry/`
- `src/novel_forge/modules/agent_scheduler/`
- `src/novel_forge/modules/production_execution/`
- `src/novel_forge/modules/authority_security/`
- Agent workspace/runtime profile modules
- `docs/architecture/scoped-conversational-agent-architecture.md`

### 目标收敛

- `agent_collaboration/contracts.py`
- `agent_collaboration/application.py`
- `agent_collaboration/work_orders.py`
- `agent_collaboration/candidates.py`
- `agent_collaboration/conflicts.py`
- `agent_collaboration/decisions.py`
- `agent_collaboration/scope_expansion.py`
- `agent_collaboration/recovery.py`
- `tests/integration/test_agent_collaboration_authority_postgres.py`

### 禁止位置

- Agent tool 直接 Repository write；
- Agent prompt 自行扩大 scope；
- Agent output 声称已 commit/activate；
- Agent scheduler 自建 retry/lease；
- Agent 直接读取未冻结“最新”资产；
- Agent session 内存成为正式状态。

## 5. 迁移脚本设计

数据库需核验：Definitions、Capabilities、Scope/Participant Snapshots、Sessions、Turns、WorkOrders、OutputEnvelopes、Messages、Candidates、Edges、Conflicts、ExpansionRequests、Decisions、Commits。

脚本：

```text
scripts/migrations/inventory_agent_execution_paths.py
scripts/migrations/import_agent_definitions.py
scripts/migrations/backfill_agent_work_order_bindings.py
scripts/migrations/link_candidates_to_asset_versions.py
scripts/migrations/quarantine_unscoped_agent_outputs.py
scripts/migrations/report_direct_agent_commits.py
```

无法绑定 Operation/Scope/InputManifest 的历史 Agent 输出只能作为非权威历史记录。

## 6. 实施计划

1. 固定 AgentDefinition/Capability/WorkOrder/Candidate/Decision contracts。
2. 将所有 Agent 模型调用接入 Context Builder + PEP。
3. 建立 Candidate Graph 和领域 validator。
4. 建立 ScopeExpansion、Conflict 和 human escalation。
5. 将 Agent scheduler 的执行语义收敛到 Command Kernel。
6. 将 Agent Commit 转化为目标 Domain Authority Operation。
7. 实现 restart recovery 和 duplicate turn replay。
8. 用 Book Design、Planning 和 Review 三种协作证明通用性。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Scope | Agent 输出引用 scope 外资产 | 拒绝 |
| Direct commit | 输出声明已激活 Plan | 拒绝进入 Candidate |
| Candidate lineage | revision | parent edge 完整 |
| Conflict | 两个 Candidate 不兼容 | 生成结构化 Conflict |
| Expansion | 需要额外知识 | 新 ScopeSnapshot，经批准后新 WorkOrder |
| Turn idempotency | 回调重复 | 不重复 Candidate |
| Stale fence | 旧 Attempt 输出 | 拒绝 commit |
| Recovery | Worker/session 重启 | 从 PostgreSQL 恢复 |
| Human decision | 保留异议批准 | Decision 可记录 non-blocking objection |
| Cross-domain | Agent 建议 Canon 修改 | 转交 Longform Authority，不直接写 |

## 8. Acceptance Gate

```text
agent_work_orders_authority_bound=true
agent_scope_snapshots_immutable=true
agent_model_calls_pep_bound=true
agent_outputs_candidate_only=true
candidate_graph_and_conflicts_persistent=true
authority_decision_required_for_commit=true
agent_restart_recovery_verified=true
direct_agent_domain_writes_zero=true
```

## 9. 风险

- Agent 协作过于复杂：仅在多视角有价值时使用，简单步骤仍由确定性 Saga 编排。
- Candidate 数量爆炸：设置 branch/depth/budget policy 和 pruning Decision，历史仍保留。
- Agent 权限配置困难：从 Capability + Scope 模板生成，默认最小权限。
- Agent 成为隐式工作流：流程控制留在 Application/Saga，Agent 只产生内容和判断。