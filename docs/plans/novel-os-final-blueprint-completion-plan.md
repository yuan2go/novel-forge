# Novel OS 最终蓝图补全与工程实施方案

> 方案日期：2026-07-11
> 输入：`docs/reports/novel-os-final-blueprint-gap-analysis.md`
> 原则：渐进改造现有模块化单体，不做无必要全量重写或微服务化。

## 1. 方案目标

本方案将当前“早期 Novel OS runtime + 广覆盖治理组件”补全为可验证的 Novel Operating System。目标不是增加更多资产类型或页面，而是建立一个不可绕过、可恢复、可评测的生产闭环：

```text
Project Goal / Platform Strategy
  -> Creative Candidate / Approval / Project Blueprint
  -> World / Character / Outline / Chapter Blueprint
  -> Canonical Production Kernel
  -> Context / Provider / Draft / Review / Revision
  -> Long-form State Commit / Quality Gate
  -> Release / Platform Receipt / Feedback
  -> Governed Learning / Replan
```

完成后的系统必须证明：

1. 单章和长篇只经过一个生产状态权威；
2. 每次关键执行都有版本化 Envelope、输入输出、预算、权限、Trace 和 Gate；
3. 原始来源无法直接进入生成上下文；
4. Canon、Character、Timeline、Arc、Foreshadow 能按事件增量更新并 replay；
5. 内容质量由规则、模型、Golden、人工和回归共同判断；
6. Agent 自治受计划、预算、权限、审批、超时、取消、失败恢复和停止条件控制；
7. 发布和反馈通过统一 Adapter、回执、补偿和受控学习闭环；
8. 在 30 章、100 章和三书并行验收前，不做超出证据的成熟度声明。

## 2. 设计原则

1. **模块化单体优先**：保留一个 Python 部署单元和一个 Web Admin；先拆模块内接口与所有权，不拆网络微服务。
2. **单一生产权威**：Workflow 管业务图，Agent Scheduler 执行节点，Chapter Bus 成为标准模板/facade，旧 Pipeline 仅兼容。
3. **领域、Agent、Workflow 分层**：领域服务不认识调度器；Agent operation 只适配领域命令；Workflow 只编排引用和 Gate。
4. **协议先于功能扩张**：ExecutionEnvelope、ArtifactRef、ReviewIssue、StateEvent、GateResult、ApprovalRef 先统一。
5. **所有 Context 经统一 Builder**：禁止任何生产 Provider 调用直接拼接资产或原始来源。
6. **结构化长篇状态优先**：摘要/RAG 是补充，不是 Canon、时间线和人物状态权威。
7. **证据与生产资产隔离**：EvidenceSpan -> Candidate -> Approved Knowledge -> ProductionAsset，禁止跨层捷径。
8. **质量是发布条件，不是展示分数**：完整性、内容质量、治理和运行健康分别计算并 fail-closed。
9. **有界自治**：先做模板化目标分解和受限计划；不引入可任意创建工具/权限的自由规划 Agent。
10. **失败是领域状态**：幂等、checkpoint、补偿、恢复、取消和人工接管是每个关键能力的必备接口。
11. **渐进兼容**：新 typed schema 与旧 JSON 通过 adapter/version 并存，读取兼容、写入前移，逐批迁移。
12. **生产声明由验收证据驱动**：Mock、fixture、页面、Schema 和 deterministic proof 不替代真实内容/Provider/平台证据。

## 3. 目标架构

### 3.1 六个逻辑平面

```text
+------------------------------------------------------------------+
| UI & Human Governance                                            |
| Workbench | Approval | Conflict Resolution | Eval | Ops          |
+------------------------------------------------------------------+
| Control Plane                                                    |
| GoalPlan | Workflow | Task | Agent Harness | Envelope | Gate     |
+------------------------------------------------------------------+
| Creation & Story State Plane                                     |
| Creative | World | Character | Outline | Chapter | State Reducer |
+------------------------------------------------------------------+
| Knowledge & Context Plane                                        |
| Source | Evidence | Analysis | MKAOS | Context Builder            |
+------------------------------------------------------------------+
| Quality & Learning Plane                                         |
| ReviewIssue | Eval | Golden | Human | Feedback | Mutation         |
+------------------------------------------------------------------+
| Integration & Runtime Plane                                      |
| Provider | Platform | Storage | Event/Outbox | Trace/Cost | DR    |
+------------------------------------------------------------------+
```

平面是模块所有权，不是微服务。Python 包内通过 command/query protocol 交互；持久化变更通过同一 Unit of Work 和 outbox 记录。

### 3.2 唯一章节生产图

```text
admit_project_goal
  -> approve_project_blueprint
  -> ensure_story_state_snapshot
  -> create_chapter_blueprint
  -> longform_preflight
  -> build_context_bundle
  -> generate_draft_candidate
  -> review_and_evaluate
  -> plan_and_apply_revision [bounded loop]
  -> accept_chapter
  -> commit_story_state_events
  -> create_release_candidate
  -> publish_or_operator_handoff
  -> schedule_next_chapter
```

- WorkflowRun 是图和业务进度权威。
- NodeRun 只引用一个 AgentRun 或确定性 DomainCommandRun。
- AgentRun 是执行尝试权威；重试必须创建新 attempt，不覆盖旧输出。
- Story State 只在章节 `accepted` 后提交；失败草稿不污染 Canon。
- Release 只消费 `accepted` 章节版本和通过的 Gate。

### 3.3 建议模块边界

| 目标模块 | 所有权 | 不负责 |
|---|---|---|
| `core/contracts` | Envelope、Ref、状态枚举、错误码 | 业务生成逻辑 |
| `production_kernel` | Workflow 模板、节点准入、状态转换 | Provider SDK、正文规则 |
| `story_state` | Event、Snapshot、Projection、Conflict | Prompt 和模型路由 |
| `knowledge_supply` | Source/Evidence/MKAOS lifecycle facade | 正文生成 |
| `context_runtime` | Plan、select、budget、bundle、replay | 修改 Canon/知识资产 |
| `agent_harness` | Contract、Run、Queue、Budget、Recovery | 自由改变业务状态 |
| `quality_center` | ReviewIssue、Eval、Golden、Gate policy | 直接覆写草稿 |
| `release_center` | Release、Adapter、Receipt、Compensation | 未审批自动发布 |
| `feedback_learning` | Import、confidence、attribution、proposal | 未审批应用变更 |
| `portfolio_runtime` | 书级队列、配额、优先级、隔离 | 绕过单书生产内核 |

现有包不必一次改名；先增加 facade/protocol，将旧服务逐步接入。

## 4. 建议保留的现有能力

以下实现应保留并渐进加强：

| 现有能力 | 保留原因 | 收敛动作 |
|---|---|---|
| `LocalStorage` 版本资产 | 本地优先和可检查性强 | 增加 repository/UoW 接口、项目隔离和内容 digest |
| PostgreSQL migrations/projection | 已有工业化入口 | 明确 industrial authority 和 outbox |
| MKAOS/lineage/quality/lifecycle | 功能覆盖深 | 按 supply/selection/governance 拆内部接口 |
| Context Builder | 当前最强共享 OS 能力 | 成为所有 Provider 调用唯一前置服务 |
| ReviewIssue | 已有中央模型和阻断语义 | 迁移所有 producer，消除临时 issue shape |
| Model Router/Guarded Adapter | 预算、日志和硬停基础较强 | 服务端验证 ApprovalRequest，覆盖所有 Provider |
| AgentRun/Scheduler | 有界执行、租约、重试、死信和恢复成熟度较高 | 与 Workflow/Envelope/OperationTransaction 统一 |
| Chapter Production Bus | 已有完整单章步骤知识 | 转成 production workflow template/facade |
| Editor patch/diff/rollback | 支持可追踪修订 | 接统一 Transaction 和 ReReview gate |
| Trace/ModelCall/Cost ledger | 生产可观察性基础 | 增加 exporter、SLO 和强关联 ID |
| Web Admin | 页面/API 覆盖广 | 改造为 typed workbench，不重做前端框架 |

## 5. 建议重构的现有能力

### 5.1 执行平面收敛

**问题**：旧 Pipeline、Workflow Runtime、Chapter Bus、Agent Scheduler 各有状态。
**目标**：WorkflowRun/NodeRun 为唯一业务图，AgentRun 为执行尝试，Chapter Bus 只创建/推进模板。
**做法**：

- 在 `production_kernel` 增加 `ProductionCommandBus`、`WorkflowTemplateRegistry`、`RunStateMachine`；
- 将 Chapter Bus 12 步拆成标准 node definitions，保留原 API 作为 facade；
- Agent operation handler 只返回 `OperationResult`，不得直接接受下游节点；
- 旧 `workflows/pipeline.py` 标记 `compatibility/demo`，生产模式调用直接拒绝或转发到模板；
- 引入 contract test，枚举所有生产入口并断言 envelope/context/gate。

### 5.2 Schema 渐进强类型化

**问题**：大量空 dataclass + `content` + 集中式条件校验。
**目标**：核心对象强类型，长尾资产仍可用通用容器。
**做法**：

- 优先为 ExecutionEnvelope、Workflow、AgentRun、ReviewIssue、StoryState、ContextBundle、Release、FeedbackMutation 建 typed content model；
- 新写入使用 `schema_version=2`；读取层适配 v1 content；
- 每个领域拥有自己的 validator 和 migration，不再扩张单一 `CONTENT_REQUIRED_FIELDS`；
- 保持旧 import/re-export，避免一次性修改 700+ API handler。

### 5.3 固定示例隔离

- 将 Echo Clock City、Lin Qiao 和确定性正文移动到 `tests/fixtures/` 或 `FixtureModelAdapter`；
- production/local-real 模式没有输入或 Provider 时必须返回 `blocked_missing_input/provider`，不得写固定业务资产；
- Topic/World/Character 输出必须通过 schema、source isolation、novelty 和 human/project gate；
- 增加测试断言生产包不含 fixture sentinel。

### 5.4 长篇写入策略

- 章节接受时仅写增量 `StoryStateEvent`；
- 每 5/10 章或状态事件阈值触发 Snapshot/Recap；卷末强制；
- 所有投影通过 `last_event_offset` 增量处理；
- 禁止每章全目录扫描；引用通过 project/chapter/type/status 索引查询；
- 每个章节运行设 `artifact_write_budget`，超限产生 gate 和热点报告。

### 5.5 发布路径合并

以 `PlatformAdapter` protocol 替换两套分裂接口：`prepare`、`validate`、`submit`、`poll_receipt`、`compensate`。所有外部动作必须解析服务端 ApprovalRequest、带幂等键并写 PlatformSubmission/Receipt。

## 6. 建议新增的核心系统

| 新系统 | 最小职责 | 不应包含 | 阶段 |
|---|---|---|---|
| Production Kernel | 唯一生产图、准入、状态机、恢复 | Prompt 内容、SDK | Phase 1 |
| Typed Execution Contract | Envelope/Ref/Error/Gate/Approval | 业务规则 | Phase 1 |
| Creative & Project Admission | 候选、聚类、评分、审批、ProjectBlueprint | 自动立项绕过人工 | Phase 1-2 |
| Story State Reducer | Event/Snapshot/Projection/Conflict/Rebuild | 长文本摘要权威 | Phase 3 |
| Calibrated Eval Center | Golden/Human/Judge/threshold/version | 单一模型分数决定发布 | Phase 3 |
| Bounded Goal Planner | 模板化目标分解、计划版本、重排、停止 | 自由工具/权限扩张 | Phase 4 |
| Unified Release Adapter | Platform submission/receipt/compensation | 未审批自动发布 | Phase 5 |
| Feedback Quarantine | provenance、cohort、confidence、pollution gate | 直接改 Prompt/大纲 | Phase 5 |
| Portfolio Scheduler | 书级队列、配额、公平性、隔离 | 绕过单书门禁 | Phase 5 |
| Production Security/DR | Identity/RBAC/Secrets/backup/restore/SLO | 业务创作逻辑 | Phase 6 |

### 6.1 重大缺口实施规格索引

下表把重大缺口的必要工程要素集中映射；具体协议和阈值见后续对应章节。

| 缺口 | 现状与根因 | 目标/模块边界/核心模型 | 接口、存储、工作流/Agent/UI | 失败、幂等、权限、可观察性 | 测试/验收 | 迁移、依赖、风险、优先级 |
|---|---|---|---|---|---|---|
| 回归与隔离基线 | 新门禁超过旧夹具；3 个 run 无项目 | Phase 0 Baseline Gate；ProjectRef | CI/validate；隔离修复报告和状态看板 | 不允许 skip；记录 fixture/policy version | 全量绿色、0 unscoped run | 无语义回填；无依赖；门禁误杀；P0/Phase 0 |
| 多执行平面 | Pipeline/Workflow/Bus/Scheduler 各自持有状态 | Production Kernel；WorkflowRun/NodeRun/AgentAttempt | command API、run repository；Chapter Bus facade；统一 Run Graph | 幂等 key、checkpoint、OperationTransaction；Trace 全关联 | 单章重放、kill/recover、入口 contract 100% | 双栈 feature flag；依赖基线/Envelope；入口遗漏；P0/Phase 1 |
| OS 协议和审批 | Envelope 为 metadata；客户端可自报 approved | `ExecutionEnvelope v2`、ArtifactRef、ApprovalRef、Error/Gate | `/envelopes/validate`、Approval verifier、Postgres unique key；所有 Agent/Provider/UI 引用 | 服务端 scope/actor/expiry；重复请求返回已接受结果；Audit/Cost | approval spoof 必败，Provider 调用证据覆盖 100% | legacy-derived adapter；依赖基线；协议漂移；P0/Phase 1 |
| 固定创作前置 | Topic 字段、World/Character 固定样例 | Creative Admission、WorldRule、CharacterCore、StoryBlueprint | Creative API/UI；typed assets/projections；生成 Agent 只消费批准 brief | 无 Provider/输入即阻断；candidate nonce；立项审批/Trace | fixture sentinel 0；候选/风险/审批齐全 | 样例转 fixture；依赖 Kernel/Context；模型质量；P0/Phase 3 |
| MKAOS/来源供应链 | 功能广但历史 lineage、校准和迁移不齐 | Knowledge Supply facade；EvidenceSpan/Candidate/Asset/Pack | ingestion/review/catalog/selector API；evidence/knowledge 分库边界；Context 接入 | snapshot digest 幂等；activation approval；lineage/usage metric | 泄漏 0、stale 选择 0、active lineage 100% 或显式例外 | 历史卡分级；依赖 refs/approval；可用资产骤减；P0/Phase 2 |
| Context 单一入口 | 新 Builder 较强，但旧调用可绕过 | Context Runtime；Plan/Bundle/ActualSent/Digest | `build_context(envelope_ref, target...)`；cache/index；所有 Provider/Agent/UI | raw/高风险/超预算硬停；digest 幂等；selection/latency metric | stage 覆盖 100%、Replay 一致、token 偏差 <=5% | 调用方逐项迁移；依赖 MKAOS/Envelope；回归阻断；P0/Phase 2 |
| 长篇状态 | 资产多但抽取启发式、摘要/RAG 过重 | Story State；Event/Snapshot/Projection/Conflict | state command/query API、event/outbox；accepted 后两阶段提交；typed consoles | event_id 幂等、乐观锁、state commit recovery；高影响人工确认 | Canon/Timeline critical recall、replay digest、30 章性能 | 历史摘要只作证据；依赖 Kernel/Context；抽取误判；P0/Phase 3 |
| 质量/Eval | ReviewIssue 强，分数和 Golden 弱；完整性混同质量 | Quality Center；Dataset/Annotation/Policy/Gate | Eval/annotation/policy API/UI；Golden storage；所有 review producer 统一 | policy version/rollback；issue idempotency；Reviewer role；override metric | critical regression 0、人工一致性/维度阈值、30章盲评 | 旧规则版本保留；依赖真实内容；阈值误阻断；P0-P1/Phase 3 |
| Agent 自治 | Scheduler 是 A2 执行器，无 Goal Planner | Bounded Planner；GoalPlan/PlanVersion/Decision/Schedule | plan API/UI；task graph -> Scheduler；无自由 operation | max iteration、budget/cancel/deadline、permission；decision trace | blocking gate 自动停、恢复不重复、预算不超 | profile contract backfill；依赖质量/Kernel；计划振荡；P1/Phase 4 |
| 发布适配 | 两套 adapter，审批/回执/补偿分裂 | Release Center；Submission/Receipt/Compensation | adapter protocol、release API/UI、Postgres/outbox；Publishing Agent | 外部幂等、先 poll 后重试、Publisher approval、receipt metric | sandbox 429/timeout/duplicate/compensation，真实试点 | 旧记录映射；依赖 identity/approval；平台变化；P1/Phase 5 |
| 反馈学习 | 有导入和 proposal，污染/因果/实验弱 | Feedback Quarantine；Insight/Hypothesis/Experiment/Decision | connector/experiment API/UI；raw quarantine + normalized store；Feedback Agent 只提案 | cohort/anomaly gate、proposal 幂等、审批/回滚、效果指标 | 小样本不可应用；已应用均有实验与 rollback | 历史反馈标 provenance；依赖 release/version；污染；P1/Phase 5 |
| 多书/生产硬化 | Portfolio 不 dispatch；安全/DR/CI 不足 | Portfolio Runtime + Production Foundation | book queue/quota API/UI；OIDC/RBAC/Secrets；authority/outbox/backup | ResourceLease 幂等、公平性、角色权限、SLO/alert | 3-book 0 cross-ref；100章；restore/RPO/RTO | 单书合格后启用；依赖 Phase 3-5；复杂性；P2/Phase 5-6 |

## 7. 统一领域模型

### 7.1 核心聚合

| 聚合 | 根对象 | 关键子对象/引用 | 主要不变量 |
|---|---|---|---|
| Project | `NovelProject` | Goal、PlatformProfile、Blueprint | 所有运行/资产必须绑定 project/workspace |
| Creative Admission | `CreativeDecision` | Candidate、Cluster、Score、Approval | 未审批候选不能创建 active project |
| Story Structure | `StoryBlueprint` | Theme、World、Character、Volume、Arc、Ending | 变更必须生成 impact 和版本 |
| Chapter Production | `ChapterRun` | Blueprint、DraftVersion、ReviewIssue、Gate | accepted 版本唯一且不可静默覆写 |
| Story State | `StoryStateStream` | Event、Snapshot、Projection、Conflict | 只消费 accepted chapter；可确定性 replay |
| Agent Execution | `AgentRun` | Contract、Attempt、Checkpoint、Budget、Gate | 输入封闭、权限最小、重试新 attempt |
| Knowledge | `KnowledgeAsset` | EvidenceSpan、Candidate、Version、Usage | Evidence 不得直接成为生产上下文 |
| Release | `Release` | Package、Submission、Receipt、Compensation | 无通过 gate 和 approval 不可 submit |
| Feedback Learning | `MutationProposal` | Evidence、Confidence、Experiment、Decision | 未审批/未验证不得改变生产策略 |

### 7.2 建议状态机

```text
ChapterRun:
planned -> admitted -> running -> needs_review -> needs_revision
        -> accepted -> state_committed -> release_ready -> published
                      |                  |
                      v                  v
                    failed          publish_failed
                      |                  |
                      +----> recovering <+

AgentRun:
planned -> ready -> leased -> running -> checkpointed -> needs_review
                                      |                  |
                                      v                  v
                                   failed           accepted
                                      |
                         retry_scheduled/dead_letter/recovered

KnowledgeAsset:
candidate -> reviewed -> active -> deprecated
                    |       |
                    v       v
                 rejected quarantined -> restored/deprecated
```

所有状态转换用 command 执行并写 AuditEvent；禁止直接修改 status 字符串。

### 7.3 一等引用类型

```json
{
  "asset_id": "...",
  "asset_type": "context_bundle",
  "version": 3,
  "project_id": "...",
  "content_digest": "sha256:...",
  "storage_uri": "local://...",
  "created_by_run_id": "..."
}
```

所有 input/output/gate/context/model/prompt/skill/approval 引用使用同一 `ArtifactRef` 基础协议；避免路径字符串、ID 和内嵌 dict 混用。

## 8. 统一 OS Envelope 与协议体系

### 8.1 ExecutionEnvelope v2

```json
{
  "schema_version": 2,
  "envelope_id": "env_...",
  "project_id": "project_...",
  "workspace_id": "workspace_...",
  "goal_plan_ref": null,
  "workflow_run_ref": "...",
  "node_run_ref": "...",
  "agent_run_ref": "...",
  "operation": "generate_draft_candidate",
  "idempotency_key": "...",
  "input_refs": [],
  "expected_output_types": [],
  "context_policy_ref": "...",
  "permission_policy_ref": "...",
  "approval_refs": [],
  "budget": {"max_tokens": 0, "max_cost": 0, "deadline_at": "..."},
  "provider_policy_ref": "...",
  "acceptance_contract_ref": "...",
  "trace_id": "...",
  "parent_span_id": "..."
}
```

### 8.2 强制规则

1. 生产 API 只接受业务 command + `envelope_ref`，不信任客户端传入的 approved 状态。
2. 服务端解析 ApprovalRequest，检查 actor、scope、operation、project、expiry 和一次性/多次使用限制。
3. Provider 调用必须引用 ContextBundle、ActualSentContext、PromptVersion、SkillVersion、ModelRoute 和 CostLedger。
4. 输出必须与 `expected_output_types` 匹配并通过 schema/gate；否则 AgentRun 失败。
5. 幂等键覆盖 project + operation + immutable input digests + attempt policy；相同已接受请求返回原结果。
6. ErrorEnvelope 使用稳定 `code`、`retryable`、`operator_action`、`failed_ref` 和 `recovery_plan_ref`。

### 8.3 建议接口和存储

- 新增 `ExecutionEnvelopeRepository.get/put/verify()`；
- 新增 `POST /product/envelopes/validate`、`GET /product/envelopes/{id}`，生产执行 API 不提供任意 envelope mutation；
- PostgreSQL 增加 `execution_envelopes` 或规范化 asset projection，唯一约束 `(project_id, idempotency_key)`；
- Local mode 继续写不可变 JSON version；Industrial mode 由 Postgres 事务提交 envelope/run/outbox，JSON 作为 artifact projection；
- Trace、ModelCall、Gate 和 output 都必须反向引用 `envelope_id`。

### 8.4 迁移

先以 compatibility adapter 从旧 metadata 生成 v2 envelope，标记 `legacy_derived=true`；完成入口覆盖率 100% 后禁止生产写 v1。旧资产只读兼容，不做一次性全量重写。

## 9. MKAOS 最佳实践方案

### 9.1 目标供应链

```text
SourceSnapshot
  -> SourceChunk + EvidenceSpan
  -> KnowledgeCandidate
  -> Quality/Dedup/Risk/Human Review
  -> Active KnowledgeAsset
  -> Versioned KnowledgePack
  -> Context Selection + UsageReceipt
  -> Outcome Attribution
  -> Governed Weight/Lifecycle Proposal
```

### 9.2 模块内拆分

保留现有 `mkaos*` 包，增加稳定 facade：

- `MKAOSIngestionService`：source snapshot -> chunks/evidence/candidates；
- `MKAOSReviewService`：quality、dedup、risk、approval；
- `MKAOSCatalog`：active version、query、lineage；
- `MKAOSPackBuilder`：按用途/平台/项目生成不可变 Pack；
- `MKAOSSelector`：只返回候选引用和选择解释，不直接构建 Prompt；
- `MKAOSLearningService`：UsageReceipt -> proposal，不直接改权重。

### 9.3 核心协议

`EvidenceSpan` 必须包含 snapshot digest、start/end、quote digest、rights policy；`KnowledgeCandidate` 包含抽象文本、claims、evidence refs、extractor/prompt/model version、confidence；`KnowledgeAsset` 包含 approved refs、scope、license constraints、risk class 和 supersedes。

原文只保存在 evidence storage；生产资产只含抽象 claims/techniques。Context Builder 必须拒绝任何带 raw quote、R4/quarantined/stale 或未批准 lineage 的候选。

### 9.4 错误、幂等、审批和可观察性

- 导入幂等键：source URI + snapshot digest + extractor profile version；
- 抽取重试创建新 candidate attempt，不覆盖失败输出；
- rights 缺失、span 越界、来源过期和 quote leakage 均 fail-closed；
- candidate activation、quarantine restore、权重变更必须用服务端 ApprovalRef；
- 指标：candidate acceptance rate、duplicate rate、leakage false-positive/negative、pack selection hit、unused rate、downstream quality delta；
- Trace 关联 Source -> Evidence -> Candidate -> Pack -> Context -> Chapter -> Feedback。

### 9.5 测试与验收

- 100% active KnowledgeAsset 可回溯到至少一个有效 EvidenceSpan 或标记为 operator-origin；
- 高风险/原始 sentinel 在所有生成 stage 的 ActualSentContext 中命中数为 0；
- Golden corpus 上 quote leakage recall >= 0.98，precision 初始 >= 0.90，阈值由人工校准后版本化；
- stale/quarantined asset 的选择率为 0；
- 同一 snapshot 重放不产生重复 active asset；
- feedback 只能产生 proposal，未审批不得改变生产 selector。

阶段：Phase 2；依赖 Phase 1 Envelope/Ref/Approval；主要风险是历史资产 lineage 不完整，采用 quarantine + grandfathered/manual provenance 分批迁移。

## 10. Context Builder 最佳实践方案

### 10.1 单一入口

提供唯一接口：

```python
build_context(
    envelope_ref,
    target: ContextTarget,
    state_snapshot_ref,
    candidate_refs,
) -> ContextBuildResult
```

`ContextBuildResult` 返回 plan、bundle、actual_sent_context、selection reasons、rejected refs、token accounting、source gate、digest 和 replay key。任何 Provider adapter 不再接受任意 `context: str`。

### 10.2 分层选择

| 层 | 内容 | 预算策略 | 权威 |
|---|---|---|---|
| Hard Constraints | Canon、禁止变更、目标、平台安全 | 不可丢弃，超限阻断 | Story State/Policy |
| Active State | 当前人物、位置、物品、Arc、伏笔 | 结构化压缩 | Snapshot projections |
| Chapter Intent | 章节蓝图、场景、钩子、回报 | 高优先级 | accepted blueprint |
| Style/Knowledge | Style rules、MKAOS Pack | 排名和去重 | approved pack |
| Recent Memory | 最近章节/卷摘要 | 分层压缩 | accepted summaries |
| Retrieved Support | RAG/KG 相关项 | 可丢弃，有召回证据 | approved index |

### 10.3 缓存与失效

- `context_digest = hash(profile_version + input ref digests + policy version + tokenizer version)`；
- 相同 digest 复用不可变 bundle；
- StoryState/MKAOS/Policy 更新通过 outbox 发布 `ContextDependencyChanged`，只标记受影响 digest stale；
- Replay 必须使用原始 ref version，不隐式读取 latest；
- 缓存命中仍写轻量 UsageReceipt，不复制所有证据资产。

### 10.4 治理和错误处理

- Production：缺 Canon snapshot、source gate、approval 或 budget 时硬停；
- Local development：只允许显式 `compatibility_mode`，输出 Gate warning，不能生成 release-ready；
- Token 超限先按层压缩，再阻断，不静默截断 Hard Constraints；
- ActualSentContext 做敏感字段遮蔽，但保存 digest 和可审计原文引用；
- 取消时中断检索/压缩并写 checkpoint；重试使用相同 immutable input refs。

### 10.5 验收

- 生产 Provider call 的 ContextBundle/ActualSentContext/SourceGate 覆盖率 100%；
- raw/decomposition/analysis/high-risk sentinel 泄漏为 0；
- 同输入 Replay digest 100% 一致；
- state change 后只失效受影响 bundle；
- token accounting 与 Provider usage 偏差 <= 5%（按 tokenizer 校准）；
- P95 context build 延迟和检索召回在 30/100 章数据规模下满足阶段 SLO。

阶段：Phase 2；保留现有实现，重点迁移调用方和增加 digest/invalidation。

## 11. Agent Center 与 Harness 最佳实践方案

### 11.1 保留执行器，新增受限控制器

现有 Scheduler 负责“怎样可靠执行一个已批准 operation”。新增 Goal Planner 只负责“从批准目标选择模板并生成有界任务图”，二者不得混为一个自由循环。

```text
Approved Goal
 -> GoalPlanTemplate selection
 -> bounded TaskGraph proposal
 -> admission/approval/budget
 -> Scheduler dispatch
 -> checkpoint/gate/outcome
 -> deterministic replan policy or human escalation
```

### 11.2 新模型

- `GoalPlan`：目标、模板版本、success metrics、budget、deadline、stop conditions；
- `PlanVersion`：immutable task graph、reason、supersedes；
- `PlanDecision`：continue/retry/revise/pause/escalate/stop，引用 Gate 和 metrics；
- `RecurringSchedule`：event/cron trigger、max concurrent、cooldown、expiry；
- `ResourceLease`：project/book/provider/cost slot；
- `OperatorIntervention`：pause/cancel/override 请求和理由。

### 11.3 Operation contract

每个 operation 声明：input/output schema、allowed tools、permission scope、side-effect class、idempotency policy、timeout、budget profile、checkpoint strategy、compensation handler、acceptance gates。删除生产通配 `*`；未知 operation fail-closed。

### 11.4 生命周期和失败恢复

- queue lease 到期只能由 recovery policy 重新租赁；
- Provider 任务取消：立即标记 cancel requested，调用 adapter interrupt；5 秒内停止排队任务，活动调用再给 10 秒 grace；
- retry 仅适用于明确 retryable error，指数退避 + jitter + max attempts；
- 非幂等外部动作必须先查 receipt，不能盲重试；
- dead letter 需要 RecoveryPlan 或人工 disposition；
- business rollback 必须调用 OperationTransaction/Platform compensation，不只改 metadata。

### 11.5 Agent Center UI

- Registry：contract/profile/version/eval/SLO/permission；
- Runs：统一图展示 Plan -> Workflow -> Node -> Agent -> ModelCall -> Artifact/Gate；
- Dispatch：队列、lease、retry/dead letter；
- Recovery：checkpoint、compensation preview、approval、resume；
- Budget：项目/作品/Agent/Provider 预算和硬停；
- Planner：计划版本、理由、停止条件和人工接管。

### 11.6 验收

- 未注册/通配 operation 在生产拒绝率 100%；
- budget/timeout/cancel/permission/approval 负例均 fail-closed；
- kill/restart 后从 checkpoint 恢复，不重复已接受 side effect；
- dead-letter repair 不修改原失败证据；
- 计划重排创建新 PlanVersion，旧版本可回放；
- 自动循环在预算、deadline、blocking gate 或 stop condition 下 100% 停止；
- Agent success/quality/cost 按 contract version 可比较。

阶段：Phase 4；前置是 Phase 1-3 的协议、真实质量门禁和业务补偿。

## 12. 创作生产工作流方案

### 12.1 创意与立项

新增 `CreativeBrief`、`ConceptCandidate`、`ConceptCluster`、`ConceptScorecard`、`CreativeDecision`、`ProjectBlueprint`。

输入：平台、受众、题材、篇幅、商业目标、禁区、可用知识范围。
过程：多样化候选 -> embedding/规则聚类 -> 去重/新颖性/版权风险 -> 市场/可持续性/主题潜力评分 -> 人工审批。
输出：获批 ProjectBlueprint，包含 reader promise、theme hypothesis、world constraints、character functions、longform capacity、platform rhythm 和 risk register。

不得只用模型自评分。新颖性由内部资产/历史作品/许可语料相似度、人工审查和来源风险共同判断。

### 12.2 World/Character/Outline

- World Engine 输出 typed WorldRule/Entity/Institution/Resource/PowerConstraint 和 impact graph；
- Character Engine 输出 CharacterCore、RelationshipEdge、ArcPlan、StateConstraint、PlotFunction；
- Meaning Engine 输出 ThemeClaim、ValueConflict、MeaningArc、chapter/volume evidence expectation；
- Outline Engine 消费上述已批准版本，输出 Volume/Arc/Beat/Foreshadow/Ending plan；
- 所有变更写 BlueprintVersion + ChangeImpactReport，已投产章节受影响时需审批。

### 12.3 章节闭环

- ChapterBlueprint 必须有场景目标、POV、冲突、状态前置、变化、信息释放、payoff、hook、禁止变更和预计字数；
- Draft Agent 只能消费 ContextBundle，生成 Candidate，不直接成为 final；
- Review 产出标准 ReviewIssue，不修改正文；
- Revision Planner 按 issue/范围/风险生成 patch plan；Editor 生成新版本和 diff；
- bounded loop 默认最多 2 次模型修订，超限转人工；
- 接受后才提交 StateEvent；发布候选引用接受版本和 gate snapshot。

### 12.4 API/UI/存储

- API：`/creative/briefs|candidates|decisions`、`/projects/{id}/blueprints`、`/chapters/{id}/runs`；
- UI：Creative Center 候选对比/聚类/审批；Story Blueprint 的 World/Character/Arc/Ending typed editors；Chapter Run graph；
- DB：candidate/decision 可作为 typed asset + query projection；story blueprint/version 和 chapter run 有唯一 project/chapter/version 约束；
- 错误：上游版本 stale、blocking impact、missing approval、context gate、quality gate 使用稳定错误码；
- 幂等：每个生成 command 按 input digest + prompt/model policy 产生 attempt，人工“生成新候选”显式 nonce。

### 12.5 验收

- production 模式不存在 fixture sentinel；
- 立项必须有 >=3 个有效候选、聚类/风险证据和 ApprovalRef；
- World/Character/Outline 关键对象 100% 绑定 ProjectBlueprint version；
- Chapter 1-10 的正文 body digest 100% 唯一，归一化成对相似度初始阈值 <0.35（由 Golden 校准后替换）；
- 每章至少一个经人工/规则确认的状态变化或明确“无变化”理由；
- 任何 accepted chapter 都可从 Envelope 重放输入和 Gate。

## 13. 长篇稳定性系统方案

### 13.1 Event + Snapshot，而非摘要权威

新增/强类型化：

```text
StoryStateEvent
  event_id, chapter_version_ref, event_type, subject_ref, predicate,
  before, after, effective_time, location_ref, evidence_span,
  extractor_version, confidence, review_status

StoryStateSnapshot
  project_id, chapter_number, last_event_offset, projection_versions,
  canon_digest, unresolved_conflict_refs
```

投影包括 CanonFact、TimelineEntry、CharacterState、RelationshipState、Inventory/Resource、PowerState、ArcState、ForeshadowState、ReaderPromiseState、ThemeEvidence。

### 13.2 两阶段提交

1. 草稿/修订阶段提取 `ProposedStateEvent`，用于 review；
2. Chapter accepted 后，人工或门禁确认高影响事件；
3. 事务写 accepted events + outbox；
4. reducer 增量更新 projection；
5. conflict detector 失败则章节停在 `state_commit_failed`，不创建 release candidate。

### 13.3 检查策略

- 硬规则：死亡后行动、位置不可能、物品负库存、时间倒流、明确 Canon 冲突；
- 软模型：人物语气/动机漂移、节奏、重复冲突、战力膨胀、主题偏移；
- 所有 issue 指向事实/事件/文本 evidence，并记录规则/模型版本和 confidence；
- 自动修复只生成 RevisionTask，不直接改 state 或正文；
- recap 默认每 5 章、深度 recap 每 10 章、卷末强制；事件量/冲突可提前触发。

### 13.4 性能

- reducer 只读当前 offset 后事件；
- project/type/chapter/subject 建索引；
- snapshot 每 N 章生成，replay 可从最近 snapshot 开始；
- 每章关联运行引用默认预算 <=120 个，超过即触发 runtime growth gate；
- P95 单章耗时不得持续随章节号单调增长；30 章时 P95 <= 前 3 章中位数 2 倍，阈值经基线调整。

### 13.5 验收阶梯

1. 10 章：真实差异化正文，state replay digest 一致，无 critical conflict。
2. 30 章：角色/时间线/伏笔 Golden 标注 precision/recall 达发布阈值；性能无超线性增长。
3. 100 章：至少一卷完整，伏笔 open/payoff/abandoned 全生命周期有证据，人工盲评无系统性漂移。
4. 百万字：在 100 章稳定后单独开展，不用 state-only proof 替代。

## 14. 审稿、质量门禁与 Eval Center 方案

### 14.1 四类分离门禁

| Gate | 关注点 | 失败后动作 |
|---|---|---|
| Artifact Completeness | 必需资产/引用/版本齐全 | 修复工作流，不评价内容 |
| Governance | 来源、权限、预算、审批、安全 | 硬停/人工处理 |
| Content Quality | 逻辑、人物、节奏、文风、钩子、原创 | RevisionTask/人工 review |
| Release Readiness | 以上全部 + 平台规则/包/回滚 | 阻止发布 |

禁止再以 Artifact Completeness 代表 Content Quality。

### 14.2 统一 ReviewIssue

所有 producer 调用 `ReviewIssueService.raise_issue()`，字段包含 category、severity、scope ref、evidence、rule/model version、confidence、blocking policy、suggested action。Gate 只消费 issue refs 和 policy version，不解析 producer 私有 dict。

### 14.3 Golden 与人工校准

- 建立版本化数据集：source leakage、Canon、character drift、timeline、foreshadow、repetition/AI flavor、chapter quality、platform review；
- 每条样本含 input refs、期望 issue/label、允许差异和版权/来源政策；
- 双人标注关键集，报告 Cohen's kappa 或等价一致性；不足阈值先修 rubric；
- Model judge 必须记录 Provider/model/prompt/version/cost；与人工按维度校准，不用单总分；
- 阈值发布为 `QualityPolicyVersion`，变更需回归和审批，可回滚。

### 14.4 建议初始门槛

- Source leakage critical recall >=0.98；
- Canon/Timeline hard conflict recall =1.00（Golden critical 集）；
- Character drift F1 >=0.80 后才允许成为自动 blocking gate，否则只提示；
- 内容总分不单独发布，所有 mandatory dimension >= policy threshold；
- 人工与模型维度相关/一致性不足 0.70 时，模型 judge 不得独立放行；
- Prompt/Skill/Model 新版本不得使 critical regression 增加，成本/延迟需在预算内。

阈值是启动值，必须由 Golden/人工数据校准后版本化，不能写死为永久标准。

### 14.5 Eval UI 和运行

新增 Dataset、Annotation Queue、Agreement、Calibration、Policy Release、Regression Comparison 六个视图；支持样本脱敏、盲标、争议仲裁、阈值 preview 和回滚。离线 eval 在 PR/nightly 运行，在线只记录真实结果和抽样人工复核，不自动训练/改权重。

## 15. 反馈闭环与持续优化方案

### 15.1 Feedback Quarantine

所有外部反馈先进入 quarantine，记录 connector、platform、book/chapter/version、timestamp、cohort、anonymized reader key、sampling、bot/anomaly flags 和 source confidence。解析失败、无版本映射或异常流量不能进入归因。

### 15.2 受控学习链

```text
Raw Feedback
 -> normalized observation
 -> cohort/quality gate
 -> FeedbackInsight
 -> AttributionHypothesis
 -> MutationProposal
 -> approval
 -> offline regression / bounded experiment
 -> MutationDecision keep|rollback
```

Proposal 可以指向 Prompt、Skill、MKAOS weight、QualityPolicy、Outline/ChapterBlueprint，但不同目标由不同 application handler 处理。不得直接改正文或 accepted blueprint。

### 15.3 最小污染防护

- 最小样本/时间窗/cohort 多样性；
- 重复读者/异常速率去重；
- 平台运营变化、投放和发布时间作为混杂变量；
- 高风险变更需要人工批准和 holdout；
- 跨作品迁移只允许抽象规则，禁止正文/角色/设定组合；
- 所有变更可回滚到 policy/prompt/pack 旧版本。

### 15.4 验收

- 100% insight 有原始观测、版本和 confidence；
- 未过 quarantine/cohort gate 的反馈不能产生 dispatch-ready mutation；
- 每个已应用 proposal 有审批、回归、实验、决策和 rollback ref；
- 反馈变更不能绕过项目/知识/版权隔离；
- 失败实验在一个控制周期内自动暂停并转人工。

## 16. 平台适配和发布系统方案

### 16.1 单一 Adapter Contract

```python
class PlatformAdapter(Protocol):
    def validate(package_ref, profile_ref) -> ValidationResult: ...
    def prepare(package_ref, idempotency_key) -> SubmissionDraft: ...
    def submit(draft_ref, approval_ref) -> PlatformReceipt: ...
    def poll(receipt_ref) -> PlatformReceipt: ...
    def compensate(receipt_ref, approval_ref) -> CompensationResult: ...
```

`Fanqie`/`Qidian` 在无官方 API 时只能实现 `ManualHandoffAdapter`，状态必须标记 `manual_handoff`，不得显示为自动发布。

### 16.2 数据与错误

- `PlatformProfileVersion`：规则来源、有效期、验证方式；
- `PlatformSubmission`：package digest、remote target、idempotency key、attempt；
- `PlatformReceipt`：remote ID/version/status/raw response digest；
- `PlatformError`：auth/rate_limit/validation/transient/permanent/unknown；
- `CompensationPlan/Result`：撤回、回滚版本或人工步骤。

外部 submit 之前在服务端解析用户身份和 ApprovalRequest。Transient error 可重试；未知或非幂等响应先 poll receipt；永久错误生成 ReviewIssue/OperatorTask。

### 16.3 平台策略

平台节奏、标题、简介、封面、章节长度和安全规则以版本化 profile 管理；规则必须标记 official/manual/empirical 来源和日期。候选优化以实验和反馈结果评价，不把人工规则伪装为官方 SDK。

### 16.4 验收

- adapter contract 使用 sandbox/fake server 覆盖成功、429、超时、重复 submit、未知响应和补偿；
- 相同 idempotency key 不产生两个 remote publication；
- 无有效 ApprovalRef 的外部调用为 0；
- ReleasePackage digest 与 receipt 绑定且可审计；
- Manual adapter 清晰输出 operator steps，不宣称自动发布；
- 一个真实平台试点完成后才将对应 adapter 标记 production-ready。

## 17. UI 与人工治理控制台方案

### 17.1 信息架构

| 工作台 | 核心操作 | 不是只展示 |
|---|---|---|
| Project/Creative | brief、候选对比、聚类、审批、Blueprint 版本 | 可阻断立项 |
| Source Center | intake、rights、risk、diff、stale、repair、rollback | 可审批/执行受限修复 |
| Story Studio | World/Character/Arc/Timeline/Foreshadow/Ending typed edit | 可看 impact 和冲突 |
| Production | Run graph、pause/cancel/resume、chapter diff | 可执行恢复/人工接管 |
| Review Center | issue triage、revision plan、re-review、gate | 可批量归属/阻断 |
| Eval Center | dataset、annotation、agreement、calibration、policy release | 可发布/回滚阈值 |
| Agent Center | registry、runs、planner、budget、recovery | 与 Dispatch Queue 分离 |
| Release Center | package diff、approval、submission、receipt、compensation | 可回滚/人工 handoff |
| Portfolio | 书级队列、配额、风险、相似度、隔离 | 可暂停/重排 |
| Ops | Trace、Cost、SLO、backup/restore、incident | 可触发演练与导出证据 |

### 17.2 前端契约

- 生成 OpenAPI typed client 或统一 DTO，减少手写字段漂移；
- 所有 mutation 带 `expected_version` 和 idempotency key，冲突返回 409 + diff；
- 长任务显示真实 run state，不用本地 optimistic “completed”；
- destructive/paid/external 操作使用服务端 ApprovalRequest；
- 页面保存过滤器和项目上下文，但不在客户端存 approval status；
- 通用 JSON 编辑器只保留给诊断/未知长尾资产，核心领域改 typed forms/graphs/timelines。

### 17.3 E2E 验收

Playwright 覆盖：创建项目候选并审批、Source 风险阻断、章节运行 pause/resume、ReviewIssue 修订再审、Canon 冲突解决/replay、Provider budget hard-stop、发布审批与补偿、三书隔离切换。桌面和移动视口均检查无重叠、状态不跳动、错误可恢复。

## 18. 数据库、事件和存储方案

### 18.1 每种运行模式一个权威

| 模式 | 控制状态权威 | Artifact | 搜索/分析投影 |
|---|---|---|---|
| Local | 版本化 JSON repository | 本地文件/JSON | 可重建的本地索引 |
| Industrial | PostgreSQL transaction | MinIO immutable object + digest | Qdrant/Neo4j/ClickHouse 可重建投影 |

Industrial mode 不再使用“JSON 成功但 Postgres best-effort 失败”作为成功条件。Postgres 在同一事务提交 Run/State/Ref/Outbox；artifact 内容先写临时对象，以 digest finalize，失败可清理。Qdrant/Neo4j/ClickHouse 永远不是业务权威。

### 18.2 Repository/UoW

定义稳定接口：`AssetRepository`、`RunRepository`、`StoryStateRepository`、`ApprovalRepository`、`OutboxRepository`、`UnitOfWork`。领域服务依赖接口，不直接扫描目录或拼 SQL。Local/Postgres 实现必须通过同一 contract suite。

### 18.3 Outbox 事件

首批事件：

- `ArtifactAccepted`、`ArtifactSuperseded`；
- `StoryStateEventsCommitted`、`ProjectionUpdated`、`StoryConflictRaised`；
- `ContextDependencyChanged`；
- `ReviewIssueStateChanged`、`QualityPolicyReleased`；
- `AgentRunStateChanged`、`BudgetThresholdReached`；
- `ReleaseSubmitted`、`PlatformReceiptChanged`；
- `FeedbackMutationDecided`。

事件包含 event_id、aggregate/version、project、occurred_at、trace/envelope、payload schema version。Consumer 以 event_id 幂等；poison event 进入 dead letter，投影可从权威事件/资产重建。

### 18.4 索引与约束

- 所有核心表/资产强制 `project_id`、`workspace_id`；
- `(project_id, idempotency_key)` 唯一；
- `(aggregate_id, version)` 唯一且乐观锁；
- StoryEvent `(project_id, offset)` 单调；
- ArtifactRef digest 与对象内容一致；
- active story blueprint/chapter accepted version 使用 partial unique constraint；
- source/MKAOS/context/feedback 按 rights/retention 删除时产生 tombstone 和 impact。

### 18.5 迁移和恢复

- 先增加新表/字段和双读，不删旧列；
- backfill 只生成引用/digest/项目归属，不重写内容语义；
- 双写阶段比较 digest 并报告 drift；
- 切换 authority 前进行 snapshot、restore rehearsal 和 read parity；
- 回滚切换只改变读写 router，不删除新数据；
- Qdrant/Neo4j/ClickHouse 从 outbox replay 重建。

## 19. 可观察性、成本和运行治理方案

### 19.1 统一关联

每条日志、Span、Metric、ModelCall、CostLedger、Gate、Artifact、PlatformReceipt 必须至少带 `project_id`、`trace_id`、`envelope_id`、`workflow_run_id`，适用时带 `node_run_id`、`agent_run_id`、`chapter_id/version`。

### 19.2 指标与 SLO

| 类别 | 指标 | 初始 SLO/门槛 |
|---|---|---|
| Run | success/retry/dead-letter/recovery、queue wait | 生产 dead-letter 有 owner；无静默失败 |
| Provider | latency、token、cost、timeout、cancel | 100% 有 ModelCallLog/CostLedger；超预算硬停 |
| Context | build latency、tokens、rejection、leakage | 100% 调用覆盖；critical leakage 0 |
| Story State | event count、conflict、replay lag | accepted 章节 state commit 100%；replay digest 一致 |
| Quality | issue rate、gate pass、human override、drift | policy version 可分组；critical regression 0 |
| Runtime growth | assets/refs/bytes/time per chapter | <=120 linked refs/run；P95 30 章不超过基线 2 倍 |
| Platform | submit、duplicate、receipt lag、compensation | duplicate remote submission 0 |
| Portfolio | concurrent books、quota、starvation | 无跨项目 refs；资源饥饿有告警 |

阈值在 Phase 0 基线测量后调整，调整必须版本化和说明依据。

### 19.3 Exporter 和告警

- 在现有内部 Trace/Metric 资产之外，增加 OpenTelemetry trace/metric exporter 或 Prometheus endpoint；
- 日志为 JSON，错误码稳定，敏感内容遮蔽；
- 告警：budget 80/100%、dead letter、source leakage、critical Canon conflict、projection lag、storage drift、backup stale、platform unknown response；
- SLO dashboard 链接到具体 Run/Artifact/Gate，而不是只有聚合数字。

### 19.4 成本治理

预算按 organization/user（未来）、project、book、workflow、Agent、Provider 分层；子预算只能缩小父预算。成本预留在 dispatch 时发生，Provider 完成后结算；失败释放余额但保留实际费用。无定价版本不得运行 paid route。

## 20. 安全、版权和来源隔离方案

### 20.1 用户和服务安全

- API 增加身份认证（本地单用户可用本机 session；工业模式 OIDC/API key）；
- RBAC 首批角色：Owner、Editor、Reviewer、Operator、Source Curator、Publisher、Auditor；
- 权限检查基于 actor + project + operation + resource，不等同于 Agent permission；
- ApprovalRequest 服务端创建和签发，含 scope、expiry、risk、required role、used_at；
- Provider/platform secret 由环境 Secret backend 解析，不存资产或浏览器；
- 外部 API 强制 TLS、CORS allowlist、CSRF/session 防护和速率限制。

### 20.2 来源存储边界

```text
restricted evidence store:
  raw source / source snapshot / source chunk / exact quote

governed knowledge store:
  EvidenceSpan refs / abstract claims / techniques / risk / rights

production store:
  project blueprint / context bundle / draft / review / release
```

Production Context 只能引用 governed knowledge 和 story state。Evidence store 的权限、retention、export 和删除策略独立；ActualSentContext 定期进行 source sentinel 和 near-match 扫描。

### 20.3 原创性和防照抄

- 生成前：MKAOS Pack 风险、来源多样性、命名/组合相似度；
- 生成中：禁止 named imitation、raw quote、单一作品结构组合；
- 生成后：exact/near quote、实体/设定组合、跨作品内部相似度和人工抽检；
- 命中高风险产生 blocking ReviewIssue，不自动改写后直接放行；
- 所有判断保留 corpus/version/threshold，避免无法复现的“原创分”。

### 20.4 审计与保留

外部调用、审批、来源查看/导出、发布、回滚、Policy 变更写 append-only AuditEvent。Industrial mode 对审计摘要做链式 hash/签名或外部 WORM 投影。权利撤回触发 lineage impact、context invalidation、release risk 和可验证删除/隔离计划。

## 21. 测试与验证体系

### 21.1 测试层级、输入、阈值和门禁

| 测试层级 | 当前事实 | 目标输入 | 预期/阈值 | 失败阻断 |
|---|---|---|---|---|
| Unit Test | 数量多，局部覆盖强 | 纯领域规则、状态转换、预算、错误分类 | 分支/边界/负例；无 IO | PR |
| Schema Test | BaseAsset 条件校验已有 | 每个 v1/v2 typed payload、非法引用/状态 | schema round-trip；非法 100% 拒绝 | PR/迁移 |
| Contract Test | Local/API/adapter 局部存在 | Repository、Provider、Platform、Operation contract | 所有实现相同行为 | PR |
| Integration Test | 较多，但当前有失败 | Postgres/MinIO/Qdrant/Redis + UoW/outbox | 无双写漂移；可 replay | PR/nightly |
| Workflow Test | Chapter/Scheduler 有覆盖 | 标准单章图、修订 loop、state commit | 状态转换和 Gate 不可绕过 | PR/release |
| Agent Evaluation | 资产/operation metrics 存在 | 每个 Agent task family Golden | quality/cost/latency 达 policy | Agent version release |
| Prompt/Skill Regression | Prompt/Eval 资产存在 | 版本化 benchmark suite | critical 不退化；预算内 | Prompt/Skill sync/release |
| RAG Source Leakage Test | 多 stage 负例存在 | raw/analysis/R4/stale sentinel +真实样本 | critical recall >=0.98；sent context 0 泄漏 | Release |
| Canon Consistency Test | 规则/graph 测试存在 | hard conflict Golden + accepted chapters | critical recall 1.0；无未解决 blocker | Chapter/Release |
| Character Drift Test | 压力/longform 规则存在 | 标注动机/语气/状态变化 | F1 >=0.80 才可硬阻断 | Quality policy |
| Timeline Consistency Test | 局部存在 | 时间、旅行、并发事件 Golden | critical recall 1.0 | Chapter/Release |
| Foreshadow Lifecycle Test | 资产/规则存在 | seed/open/payoff/abandoned 30/100章 fixture | 状态 replay 一致；逾期 blocker 有证据 | Volume/Release |
| Long-form Regression | state proof 有，真实内容缺 | 10/30/100 章真实正文 + 人工标注 | 唯一性、推进、状态、质量、性能阈值 | Phase/Release |
| Failure Recovery Test | Scheduler/rollback 局部较强 | kill、lease expiry、projection fail、unknown platform response | 无重复 side effect；可恢复/接管 | Release |
| Timeout/Cancel/Budget Test | Provider guard 聚焦通过 | queued/running/provider/paid operations | queued <=5s；active +10s grace；预算不超 | PR/Release |
| UI End-to-End Test | 本次 Playwright 跳过 | 八个核心操作旅程 | 后端状态真实、错误可恢复、无越权 | Web release |
| Release Gate Test | 已有本地门禁 | incomplete、governance fail、quality fail、valid package | 三类 fail 均阻断；valid 唯一放行 | Release |
| Multi-novel Isolation Test | 单元规划，真实并行缺 | 3 projects/3 books concurrent + injected failures | 0 cross refs/cost/context；公平恢复 | Phase 5/Release |
| Performance Test | 10 章显示明显退化 | 30/100 chapter indexed dataset | P95 <= 基线 2x；无超线性增长 | Phase 3/6 |
| Production Rehearsal | 尚缺 | backup/restore/provider/platform/incident | RPO/RTO、receipt、compensation 达标 | Production launch |

### 21.2 必须新增的负向测试

1. 客户端伪造 `approval_status=approved` 必须失败；
2. Provider 调用无 Envelope/Context/ActualSentContext/CostLedger 必须失败；
3. accepted chapter 引用 fixture sentinel 或重复前章正文必须失败；
4. Story state 在章节未 accepted 前不得提交；
5. stale/quarantined/raw source 进入任意生成 stage 必须失败；
6. Agent 重试不得重复发布或重复提交 state event；
7. 项目 A 的资产、Context、Cost、Trace 不得出现在项目 B；
8. 投影后端关闭时业务权威仍一致，恢复后可 replay；
9. backup 恢复后 artifact digest、state offset、approval usage 和 receipt 一致；
10. feedback 小样本/异常 cohort 不得产生可应用 mutation。

### 21.3 CI 分层

- PR fast：lint、schema、unit、contract、skills drift、Web type/static；
- PR integration：Postgres/Redis/MinIO/Qdrant compose + workflow critical path；
- Nightly：Provider sandbox、30 章小模型/预算运行、Playwright、failure injection；
- Release：Golden regression、source leakage、restore rehearsal、platform sandbox、SBOM/secret/security scan；
- 手动 production rehearsal：真实 Provider 限额运行、真实平台试点、100 章/三书阶段验收。

所有报告保存 commit、config、fixture/model/prompt/policy version、开始/结束时间和 artifact refs。

## 22. 迁移与兼容策略

### 22.1 Strangler 顺序

1. 为旧入口增加 telemetry，枚举真实调用覆盖；
2. 引入 v2 contract/facade，旧服务通过 adapter 调用；
3. 新写入只走 v2，读取双栈；
4. 逐个 workflow/Agent/API/UI 迁移并用 contract test 固定；
5. production mode 禁止旧入口，local demo 保留明确警告；
6. 达到数据/调用覆盖阈值后删除写路径，最后删除兼容读取。

### 22.2 数据迁移规则

- 不推断无法证明的 lineage、approval、project 或 state；标记 `migration_status=needs_review`；
- 缺 project 的运行资产移入 quarantine 或绑定明确 system workspace，不能默认绑定任意项目；
- 固定样例资产标记 fixture 并禁止生产选择；
- 旧 OS Envelope 生成 derived v2 ref，保留原 metadata digest；
- 临时 ReviewIssue dict 迁移为标准 issue 时保留 producer raw payload；
- 长篇历史摘要不反推为 accepted fact，只作为 low-confidence evidence。

### 22.3 兼容和回滚

- 所有 schema/API 变更先 additive；
- Web 以 capability/version 协商，不假设后端同步部署；
- feature flag 按 project 开启 Production Kernel v2、State Reducer、Eval policy；
- 切换失败时回到旧 read path，但已写 v2 数据不删除；
- 外部 side effect 通过 adapter compensation，不能靠数据库回滚假装撤回；
- 每阶段发布前保存迁移前快照和实际 restore 证据。

### 22.4 完成兼容迁移的判定

- 生产入口 Envelope v2 覆盖 100%；
- 旧 Pipeline 生产调用 0；
- 临时 ReviewIssue producer 0；
- 无项目/无 workspace 的业务运行资产 0；
- 双读 digest drift 0，持续两个 release window；
- compatibility warning 在生产日志 0 后才能移除旧写路径。

## 23. 分阶段实施路线图

### Phase 0：事实基线与架构止血

**目标**：恢复可重复的绿色基线，禁止虚假验收继续积累。
**前置**：当前分支和工作区快照；不依赖新架构。
**模块**：tests、storage validation、source runtime gate、quality policy、CI、docs。

**交付物**：

- 修复来源门禁后旧 Context/Scheduler/章节夹具；
- 修复 `project_metric_snapshot` 缺 `project_id` 和 V1 序列失败；
- 对 protagonist agency 规则做阈值/fixture/期望的明确决策，不绕过门禁；
- 清理或隔离 3 个无项目运行资产；
- 资产完整性与内容质量报告分离；
- 固定样例/Mock/deterministic proof 在报告和 UI 中显式标记；
- Python/Web/Schema/Skill 基础 CI；
- 性能基线：每章资产、引用、字节、耗时和目录扫描热点。

**数据迁移**：只处理项目归属、fixture 标记和无效测试数据；不改变业务语义。
**测试**：全量现有测试、当前 workspace validate、clean workspace validate、skills、Web、10 章 fixture 性能采样。
**验收**：全量套件绿色；0 个未归属业务 run；Playwright 可安装执行；报告不再把 artifact coverage 写成 content acceptance。
**风险/回滚**：规则迁移可能暴露更多失败；保留旧 policy version，仅在明确数据后发布新版本。
**完成定义**：连续两次干净环境 CI 相同结果，失败无“忽略/暂时通过”例外。

### Phase 1：协议、领域模型和主流程统一

**目标**：建立 Envelope v2、ArtifactRef、ApprovalRef、Error、Gate、Production Kernel。
**前置**：Phase 0 绿色基线。
**模块**：schemas/contracts、os_envelope、workflow_nodes、chapter bus、agent runs/scheduler、operation transactions、storage/UoW。

**交付物**：

- typed v2 contracts 和兼容 adapter；
- 服务端 ApprovalRequest verifier；
- 单一章节 workflow template 和状态图；
- Chapter Bus facade 转发 Production Kernel；
- 旧 Pipeline production 禁用策略；
- Workflow/Node/Agent/Model/Gate/Artifact 的统一引用图；
- Local/Postgres repository contract 和 outbox 第一版。

**数据迁移**：旧 envelope derived ref、核心资产 project/workspace backfill、ReviewIssue producer 迁移。
**测试**：schema/contract、入口枚举、幂等、乐观锁、kill/restart、approval spoof negative。
**验收**：一个章节 fixture 从 workflow 到 state-before-commit 全链经过 v2 Envelope；100% Provider call 有 Context/Trace/Cost；相同幂等键无重复输出。
**风险/回滚**：入口遗漏和双栈漂移；feature flag 按项目启用，比较旧/新只读结果。
**完成定义**：所有生产 API/CLI/Agent operation contract test 通过，生产日志无 v1 write。

### Phase 2：知识资产与上下文统一

**目标**：完成 Source -> Evidence -> MKAOS -> Context 的不可绕过供应链。
**前置**：Phase 1 refs/envelope/approval/outbox。
**模块**：source_intake、mkaos*、analysis、context_builder、retrieval/KG。

**交付物**：

- MKAOS facade 和 lifecycle 强制；
- EvidenceSpan/Candidate/Knowledge/Pack v2；
- Context digest/cache/invalidation/replay；
- 所有创作 stage Context 迁移；
- Source Center 第一版；
- 真实许可语料的 leakage/dedup Golden 子集。

**数据迁移**：历史知识卡按 lineage 完整度分 active/grandfathered/quarantine；不伪造 evidence。
**测试**：source leakage、stale/quarantine、rights expiry、RAG/KG recall、token accounting、replay digest。
**验收**：所有 production model call Context 覆盖 100%；raw/high-risk 泄漏 0；stale 选择 0；同输入 replay 一致。
**风险/回滚**：严格门禁导致可用知识骤减；通过 grandfathered manual review queue 缓释，不降低 production gate。
**完成定义**：Context runtime coverage report 在每个 stage 通过，旧 direct context builder 0 调用。

### Phase 3：长篇稳定性和质量闭环

**目标**：证明真实内容推进、结构化状态和校准质量。
**前置**：Phase 2 可信 Context；真实 Provider 预算和人工评审资源。
**模块**：creative/world/character/outline、story_state、longform、review/eval、chapter production。

**交付物**：

- 移除 production 固定 Topic/World/Character；
- Creative Admission、Theme/Meaning、Ending 最小闭环；
- StoryStateEvent/Snapshot/Projection reducer；
- recap 5/10/volume 策略；
- Golden/Human Annotation/Calibration/QualityPolicy；
- 10 章和 30 章真实 Provider 验收；
- runtime growth index/write budget 修复。

**数据迁移**：历史摘要作为 low-confidence evidence，不作为 accepted facts；固定样例转 fixture。
**测试**：Canon/Character/Timeline/Foreshadow、content uniqueness/progression、quality regression、performance、state replay。
**验收**：30 章正文差异化且有连续故事推进；critical Canon/Timeline 未解决数 0；replay 一致；质量达到校准 policy；P95 不超基线 2 倍。
**风险/回滚**：模型质量/成本不达标；按 Provider/Prompt/Policy version 回滚，允许人工接管，不回退来源/审计门禁。
**完成定义**：发布候选通过内容、治理、状态和运行四类独立 Gate，并有人工签署验收。

### Phase 4：Agent Harness 和自治运行

**目标**：从 A2 有界执行器升级为 A3 受治理项目自治。
**前置**：Phase 3 的业务状态和质量门禁可作为真实反馈。
**模块**：goal planner、agent registry/runs/scheduler、workflow、budget、recovery、Agent Center。

**交付物**：

- GoalPlan/PlanVersion/Decision/RecurringSchedule；
- 模板化任务分解和 admission；
- 删除 production wildcard operation；
- 统一 business transaction/compensation；
- budget/cancel/timeout/stop/escalation SLO；
- Agent Center planner/run graph/recovery UI。

**数据迁移**：现有 Agent profiles/contracts 增 side-effect/idempotency/compensation metadata；不自动启用 recurring。
**测试**：目标分解 Golden、预算/取消/死信/恢复、重排版本、无限循环防护、权限越界。
**验收**：系统可在批准计划下连续完成 10 章，遇 blocking gate 自动停下/转人工，恢复不重复 side effect，预算不超。
**风险/回滚**：计划振荡或错误自动化；默认 max iterations/cooldown/人工 gate，feature flag 可停 planner 而保留手动 scheduler。
**完成定义**：没有自由 tool escalation；每个自动决策可解释、可回放、可停止。

### Phase 5：反馈、平台与多小说并行

**目标**：真实外部闭环和三书受控并行。
**前置**：Phase 4 单书自治稳定；身份/审批基础可用。
**模块**：release adapter、feedback quarantine/learning、portfolio scheduler、UI。

**交付物**：

- Unified PlatformAdapter、receipt、compensation；
- 至少一个 sandbox 和一个真实平台手工/官方试点；
- Feedback Quarantine、cohort、proposal experiment；
- Portfolio queue、quota、fairness、cross-book similarity；
- 三书并行控制台和验收。

**数据迁移**：两套 publishing adapter 映射到新 submission/receipt；旧 feedback 标记 provenance quality。
**测试**：adapter errors/idempotency/compensation、feedback pollution、mutation rollback、3-book isolation/fairness/failure injection。
**验收**：外部重复发布 0；所有提交有 Approval/Receipt；三书 0 cross-project refs；一本失败不阻塞/污染另两本；反馈变更可回滚。
**风险/回滚**：平台规则变化和反馈噪声；profile version/kill switch/manual handoff/quarantine。
**完成定义**：Portfolio 能真实 dispatch，但只能调用同一单书 Production Kernel 和 Gate。

### Phase 6：生产硬化和规模化验证

**目标**：达到可运营、可恢复和可审计的生产标准。
**前置**：Phase 5 外部/并行闭环。
**模块**：identity/RBAC、Secrets、rate limit、Postgres authority、observability、CI/CD、backup/DR、performance。

**交付物**：

- OIDC/local identity、RBAC、审批签发和 Secret backend；
- Industrial UoW/outbox/投影重建；
- OpenTelemetry/Prometheus/SLO/alert；
- PostgreSQL/MinIO/Qdrant/Neo4j backup/restore；
- 100 章真实验收和后续百万字 rehearsal；
- SBOM、依赖/Secret 扫描、发布/回滚 runbook。

**数据迁移**：工业 authority 切换、投影重建和审计保留策略。
**测试**：load/soak/chaos、restore、security、100 章、provider/platform incident、RPO/RTO。
**验收**：RPO/RTO 达产品目标；100 章质量/状态/成本/性能 policy 通过；安全高危 0；多书恢复演练成功。
**风险/回滚**：基础设施复杂性；保持 Local mode，按 project/tenant 灰度 Industrial authority。
**完成定义**：生产 readiness review 由 Engineering、Editorial、Security、Operations 共同签署。

## 24. 模块依赖图

```text
Phase 0 green baseline
  |
  v
Typed Contracts + Project Isolation + Approval Verification
  |
  +--> Repository/UoW/Outbox
  |
  v
Production Kernel + Unified Workflow/Agent State
  |
  +--> Source/Evidence/MKAOS lifecycle
  |        |
  |        v
  +----> Context Builder single entry
           |
           v
Creative/World/Character/Outline production inputs
           |
           v
Story State Reducer <--> Calibrated Review/Eval
           |
           v
30-chapter accepted production loop
           |
           v
Bounded Goal Planner / Recurring Harness
           |
       +---+-------------------+
       v                       v
Unified Release Adapter   Feedback Quarantine
       |                       |
       +-----------+-----------+
                   v
          Portfolio Scheduler / 3-book isolation
                   |
                   v
        Security / DR / 100-chapter scale
```

禁止的捷径：在 Production Kernel/State/Eval 未完成前直接做自由自治；在单书真实长篇未通过前做多书自动 dispatch；在 Approval/Identity 未完成前接真实自动发布。

## 25. P0 / P1 / P2 优先级

### P0：没有这些就没有可信主流程

| ID | 工作包 | 依赖 | 主要输出 |
|---|---|---|---|
| P0-01 | 绿色基线和项目隔离修复 | 无 | 全量测试/validate/CI |
| P0-02 | ExecutionEnvelope/ArtifactRef/Error/Gate v2 | P0-01 | typed contract + adapter |
| P0-03 | 服务端 ApprovalRef 验证 | P0-02 | provider/external mutation hard-stop |
| P0-04 | Production Kernel 和四执行平面收敛 | P0-02 | 唯一章节 workflow/state |
| P0-05 | 固定 Topic/World/Character fixture 隔离 | P0-04 | 真实目标驱动前置资产 |
| P0-06 | Source/MKAOS/Context 全入口迁移 | P0-02/04 | 100% Context/source gate |
| P0-07 | StoryState Event/Snapshot reducer | P0-04/06 | 可 replay 长篇状态 |
| P0-08 | 资产完整性/内容质量分离和 Golden 基线 | P0-01/07 | 校准质量 Gate |
| P0-09 | 写放大、索引和 recap 策略 | P0-04/07 | 30 章性能可控 |
| P0-10 | 10/30 章真实内容验收 | P0-05..09 | 单书最小精品长篇证据 |

### P1：从可控生产进入受治理自治和外部闭环

- Creative Center/立项、Meaning/Ending；
- Bounded Goal Planner、Recurring Schedule、统一业务补偿；
- Golden/Human/Eval 深化和 Agent/Prompt/Skill benchmark；
- Source/Story/Eval/Agent 深度控制台与 Playwright；
- Unified PlatformAdapter sandbox/试点；
- Feedback Quarantine/Experiment；
- Industrial storage authority/outbox 基础。

### P2：规模、商业化和生产硬化

- Portfolio Scheduler 和三书并行；
- 100 章/百万字分级验收；
- Identity/RBAC/Secrets/rate limit；
- 完整 Metrics/Trace/SLO/alert；
- 全存储备份、DR、chaos、RPO/RTO；
- 多平台生产 Adapter 和商业目标归因。

## 26. 每阶段交付物

| 阶段 | 产品交付 | 工程交付 | 证据交付 |
|---|---|---|---|
| 0 | 可信状态看板 | 绿色 CI、隔离、基线脚本 | test/validate/performance baseline |
| 1 | 单一生产运行图 | v2 contracts、Kernel、Approval、UoW | 单章端到端 contract/recovery report |
| 2 | Source/MKAOS/Context 工作流 | lifecycle facade、digest/invalidation | leakage/replay/lineage acceptance |
| 3 | 可验证 30 章单书闭环 | StoryState、Eval、内容引擎、性能修复 | Golden、人工、10/30章报告 |
| 4 | 受限自治生产 | GoalPlan、planner、recurring、compensation | budget/cancel/recovery/autonomy report |
| 5 | 平台/反馈/三书控制 | adapters、quarantine、portfolio scheduler | receipt/experiment/3-book report |
| 6 | 生产运行能力 | Security、SLO、DR、industrial authority | 100章、restore、security readiness |

每项交付必须包含：schema、service/API contract、migration、negative tests、observability、runbook、UI（适用时）和可重放验收资产。

## 27. 每阶段验收标准

| 阶段 | 必须通过 | 明确不算通过 |
|---|---|---|
| 0 | 全量测试绿色；0 未归属 run；Playwright 实跑；历史报告口径标注 | 仅 lint、跳过失败或删除 fixture |
| 1 | 所有生产入口 v2 Envelope；单一状态图；approval spoof 被拒；幂等恢复 | 只新增 Schema/API 而旧入口继续绕过 |
| 2 | 100% Context 覆盖；raw/high-risk 泄漏 0；replay 一致；lineage 完整/显式例外 | 只通过 synthetic safe sample |
| 3 | 30 章真实差异化/推进；state replay；Golden/人工 policy；性能达标 | artifact coverage、Mock/state-only proof |
| 4 | 批准计划下自动 10 章；预算/取消/门禁停止/恢复全部有效 | 单个 Planner Prompt 或无限 scheduler loop |
| 5 | 平台 receipt/补偿；反馈实验/回滚；三书 0 交叉引用且公平恢复 | fake client 单测或 Portfolio 计划表 |
| 6 | 100 章；RBAC；SLO；全存储 restore；RPO/RTO；高危安全问题 0 | 只有 Compose health 或本地 ZIP |

### 27.1 最终“稳定精品长篇”判定

必须同时满足：

- 真实目标驱动的 World/Character/Outline，无 fixture sentinel；
- 至少 30 章真实 Provider 输出，章节 body digest 全唯一且语义推进通过人工抽检；
- Canon/Timeline critical blocker 为 0，Character/Arc/Foreshadow 达校准指标；
- 每章可 replay Envelope/Context/Prompt/Model/State/Gate；
- 质量 policy 有 Golden、人工一致性和真实 Provider 校准；
- 成本、延迟、写入增长和失败恢复在 SLO 内；
- Release package 通过独立内容、治理、状态和运行 Gate。

### 27.2 最终“Autonomous Novel OS”判定

在上述基础上，还必须满足：受限 GoalPlan 可连续运行、停机和恢复；外部发布/反馈闭环有回执和回滚；三书并行无隔离/资源污染；100 章和 DR rehearsal 通过。仅存在 Agent prompt、queue 或 dashboard 不构成自治验收。

## 28. 风险、回滚和降级方案

| 风险 | 触发指标 | 降级 | 回滚 |
|---|---|---|---|
| v2 入口遗漏 | legacy write/无 envelope >0 | 阻断 production，local warning | router 回旧 read，不回旧不治理 write |
| 严格来源门禁导致停产 | eligible pack 数不足 | 转人工/许可资产补充 | 回滚 selector policy version，不允许 raw source |
| State extractor 误判 | Golden F1/人工 override 恶化 | 降为 non-blocking 建议 | 回滚 extractor/policy；重建 projection |
| Quality policy 误阻断 | gate fail/人工 overturn 激增 | 人工 review queue | 回滚 policy version，不删除 issue |
| Provider 成本/质量异常 | 预算、延迟、regression 告警 | fallback/local manual | route/prompt/model version 回滚 |
| Planner 振荡/失控 | 重排次数、无进展循环 | pause planner，保留手动 scheduler | PlanVersion 回滚/终止，不覆盖 run |
| 外部发布未知结果 | timeout/unknown response | 停止重试，poll/manual | adapter compensation/人工撤回 |
| Feedback 污染 | anomaly/cohort/confidence 失败 | quarantine | policy/prompt/pack 版本回滚 |
| 双写/投影漂移 | digest mismatch/projection lag | 权威库读、停投影 consumer | replay outbox/重建投影 |
| 性能退化 | P95/asset budget 超线 | 降低并发、人工批次 | write policy/index/recap flag 回滚 |
| 多书资源饥饿 | queue age/quota breach | 暂停低优先书、公平队列 | portfolio plan version 回滚 |
| DR 失败 | restore digest/RTO 不达标 | 禁止生产发布 | 恢复上个已验证备份/保留 local mode |

任何降级都不得关闭来源隔离、审批、成本硬停、审计或 critical release gate。降级后的输出必须标记 `not_release_ready`。

## 29. 建议的后续开发批次

以下批次可直接转成工程 Issue；每批保持可独立验收，不跨越依赖。

1. **Batch 0A - Regression Repair**：修复当前来源 gate、metric snapshot、12 章 quality rule 和 V1 sequence 失败；建立完整 CI 命令清单。
2. **Batch 0B - Evidence Semantics**：拆分 artifact/content acceptance，fixture/mock/proof 标记，增加正文重复负例。
3. **Batch 0C - Isolation/Performance Baseline**：隔离无项目运行资产，测量扫描/写入热点和每章预算。
4. **Batch 1A - Core Contracts v2**：ExecutionEnvelope、ArtifactRef、ApprovalRef、ErrorEnvelope、GateRef typed schema 和兼容读取。
5. **Batch 1B - Verified Approval**：Provider/API/UI 移除客户端 approved 信任，服务端 scope/expiry/actor 验证。
6. **Batch 1C - Production Kernel**：将 Chapter Bus 转标准 Workflow template，统一 Run/Node/Agent attempt 和幂等。
7. **Batch 1D - Transaction/Outbox**：Local/Postgres repository contract、OperationTransaction 和首批 outbox event。
8. **Batch 2A - MKAOS Supply Contract**：Evidence/Candidate/Knowledge/Pack v2 与历史 lineage 分类迁移。
9. **Batch 2B - Context Single Entry**：所有 stage/provider 调用迁移，digest/cache/invalidation 和 coverage gate。
10. **Batch 2C - Source Center**：rights/risk/diff/stale/repair/rollback typed UI + E2E。
11. **Batch 3A - Real Creative Inputs**：fixture adapter 隔离，CreativeBrief、Topic/World/Character production 实现。
12. **Batch 3B - Story State Core**：Event/Snapshot/Projection/replay、两阶段 state commit 和 hard conflicts。
13. **Batch 3C - Eval Calibration**：Golden repository、annotation、agreement、policy version、ReviewIssue producer 统一。
14. **Batch 3D - Long-form Acceptance**：10 章后 30 章真实 Provider 运行、人工抽检、性能和成本报告。
15. **Batch 4A - Goal Planner**：模板化 GoalPlan/PlanVersion/Decision，无自由 operation 创建。
16. **Batch 4B - Harness Hardening**：cancel/timeout/budget/retry/dead-letter/business compensation 和 run graph UI。
17. **Batch 5A - Release Adapter**：统一 submission/receipt/compensation，sandbox 后真实平台试点。
18. **Batch 5B - Feedback Learning**：quarantine/cohort/attribution/experiment/rollback。
19. **Batch 5C - Portfolio Scheduler**：配额、公平队列、cross-book check、三书并行验收。
20. **Batch 6A - Production Foundation**：Identity/RBAC/Secrets/rate limit、observability/SLO、industrial authority。
21. **Batch 6B - DR and Scale**：全存储 backup/restore、failure injection、100 章、后续百万字 rehearsal。

建议首先实施 **Phase 0 / Batch 0A-0C**。当前回归和隔离基线未恢复前，任何自治、多书或真实自动发布开发都会放大已有状态和治理分裂。

本方案是产品与工程实施基线，不代表其中缺失能力已经实现。本轮未修改业务代码、数据库迁移、API 或生产配置。
