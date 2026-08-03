# Architecture Closure 最小稳定契约

更新时间：2026-08-03

状态：`ARCHITECTURE_DEFINED`

适用顺序：`Track B → D0 Provider Probe → Track C`
实现证明：除文中明确列出的 Track B 代码落点外，本文件定义目标契约，不构成 Track C～F 实现或生产证明。

## 1. 契约共同规则

所有下列契约都必须有 `schema_version`、稳定身份、Project/Book Scope、创建它的 Operation、`trace_id`、决策或激活记录，以及版本化 Query Contract。候选、证据和提案不能直接改写正式 Authority 状态。

跨领域读取只能通过 Query Port、Versioned Projection 或 Snapshot Contract。允许同一 PostgreSQL 中的单体事务，但禁止 Planning 直接依赖 StoryState Repository 实现、Context 直接读 Planning 表、Quality 直接更新 Chapter 表。

## 2. BookCompletionContract

最小字段：

```text
schema_version
book_id
active_book_design_version_id
active_plan_version_id
ending_achieved
main_conflict_closed
character_arcs_completed
reader_promises_fulfilled
required_foreshadowing_closed
blocking_issue_count
unresolved_canon_conflict_count
final_volume_gate_result_id
release_package_id
evidence_asset_version_ids
decision
decided_by_operation_id
```

只有以上条件全部通过，Completion Authority 才能接受。`Book Production Coordinator` 只等待该决策，不自行计算结局、人物弧或质量结论。

目标代码落点：`modules/book_completion/` 领域合同、Quality/Canon/Release 的只读快照端口，以及 Book Root Saga 的等待节点。当前未实现。

## 3. HumanInterventionContract

统一对象：

```text
InterventionRequest
BlockedReason
RequiredEvidence
AllowedAction
AssignedRole
Decision
ResumeToken
AuditTrail
```

最小规则：

- `BlockedReason` 是版本化枚举和结构化详情，不是自由文本状态机；
- `AllowedAction` 由发起领域声明，操作员不能提交未授权变更；
- `Decision` 追加写入，不能覆盖原请求；
- `ResumeToken` 绑定被阻塞 Operation 的版本、Fence 和输入快照；
- Resume 创建新的 Attempt/Run 版本，不静默续写旧结果；
- 所有模块复用共同审批元数据，但领域验证仍归领域模块。

目标代码落点：Command Kernel 中的共同 Intervention 元数据、Task Query Projection，以及各领域的 AllowedAction validator。当前未实现统一合同。

## 4. JudgePromotionLifecycle

统一生命周期：

```text
DRAFT → BENCHMARKED → CALIBRATED → APPROVED → ACTIVE → SUSPENDED → RETIRED
```

`Evaluation And Calibration Lab` 产生 Benchmark、Human Annotation、Pairwise、Mutation、OOD 和校准证据；它只能提出晋升候选。Production Quality Gate 只接受 `APPROVED` 后被显式激活的 `JudgeProfile`，并冻结 `judge_profile_version`、rubric、model/route、阈值和校准证据。`SUSPENDED` 或 `RETIRED` Profile 不能用于新的生产 Gate。

目标代码落点：Eval Lab 资产、JudgeProfile typed payload、JudgePromotionDecision、Production Gate route validator。当前未实现晋升链。

## 5. ContextDependencyAndInvalidation

最小编译链：

```text
Domain Context Requirement
→ Selection
→ Assembly
→ Compression
→ Validation
→ ContextManifest
```

最小身份和依赖字段：

```text
context_input_hash
compilation_version
requirement_schema_version
ContextDependency(source_asset_version_id, dependency_kind, effective_range)
ContextInvalidation(cause_version_id, affected_manifest_id, reason, recorded_at)
```

Context Cache 的键至少包含 `context_input_hash + compilation_version + token_policy_version`。依赖的 AssetVersion、Canon Snapshot、StoryState Snapshot、PlanVersion、KnowledgePack 或 Source eligibility 变化时，必须生成 Invalidation；已发送上下文作为历史证据保留，不能原地重编。Compiler 只编译领域声明的 Requirement，不理解 Planning、Canon、Quality 的全部业务规则。

目标代码落点：`context_compiler` 的 Requirement/Manifest/Dependency/Invalidation ports。当前只定义，未实现 Track C 编译器。

## 6. StoryStateCorrectionTemporalSemantics

最小更正字段：

```text
effective_from_chapter
effective_to_chapter
recorded_at
superseded_by
correction_reason
source_operation_id
previous_story_state_version_id
corrected_story_state_version_id
```

语义区分：`effective_*` 表示故事内适用区间，`recorded_at` 表示系统何时知道该更正。更正创建新版本和 Impact/Invalidation，不改写已发布 ChapterOutcome 或旧 StoryState Snapshot。当前阶段不要求完整双时态数据库。

目标代码落点：StoryState Correction Operation、Reducer input、版本化 Projection。当前未实现。

## 7. ReadModelAndProjectionContract

每个跨领域 Read Model 至少声明：

```text
query_contract_version
owner_domain
scope
source_authority_versions
projection_version
as_of
freshness
rebuild_cursor
content_hash
```

同事务强读可使用领域 Query Port；最终一致读取使用 Projection；Saga/Provider 输入使用冻结 Snapshot。Projection 可删可重建，不能成为 Command 或 Task Authority。当前 Book/BookDesign 落点为 `BookDesignAuthorityQuery`，它不暴露 Repository 实现。

## 8. ObjectStoreLifecyclePolicy

最小 Blob 元数据：

```text
content_hash
object_ref / provider + object_key
content_type
size
retention_class
retention_until
encryption_metadata
legal_hold
orphan_detected_at
gc_eligible_at
gc_operation_id
```

Orphan scanner 只产生带 Operation/Trace 的候选；重新出现引用时撤销候选。GC 必须再次验证引用闭包、Retention 和 Legal Hold，并通过 `object_store.delete` External Effect、Receipt 和 UNKNOWN reconciliation 执行，禁止数据库扫描直接物理删除。

当前代码落点：迁移 `0051`、`AssetBlobRepository.detect_orphans/gc_candidates`、`command_kernel.object_lifecycle` 和既有 `release_blob` External Effect。物理 GC 调度和生产保留策略尚未部署验证。

## 9. WorkerDeliveryAndOutboxContract

权威关系固定为：

```text
PostgreSQL = Operation、Attempt、Lease、Fence、Task 和业务状态 Authority
Outbox = 与 Authority Commit 同事务写入的可靠通知源
Queue / Celery / Redis = 可丢弃和重建的投递机制
Worker = 按 Lease/Fence 执行的消费者
Receipt / Inbox = 外部结果去重和终局证据
```

Queue 消息只携带 Authority identity/version；Worker 必须回读 PostgreSQL、获得 Lease/Fence 后执行。Queue ack、Celery result 或 Redis key 不能宣告任务成功。Outbox publisher 可重放；重复投递由 Command/Receipt 幂等约束吸收；UNKNOWN 由 Reconciliation worker 查询 Provider 或请求人工决策。

当前代码落点：既有 Operation/Attempt/Lease/Fence/Outbox/Receipt、`runtime_groups.py` 进程分组和 `compose.authority-only.yml`。生产 Queue publisher、SLO 和备份恢复属于 Track E 硬化，不由 Track B 文档宣告完成。

## 10. 每个 Slice 的 Legacy Cutover Contract

每条纵向 Slice 必须随 Gate 记录：

```text
legacy_source
authority_target
import
validation
writer_cutover
reader_compatibility
retirement_deadline
```

统一序列为 `Discover → Classify → Import → Validate → Authority Commit → Cut Over → Disable Legacy Writer → Observe → Retire`。Track F 只清理已经不在关键生产路径上的剩余 Legacy，不能推迟前序 Slice 的正式 Writer 切换。

Book/BookDesign 当前代码落点：`authority_slice_legacy_cutover`；Authority-only composition 不加载 Legacy Writer。真实旧数据导入仅在发现非空 Legacy Source 时执行，不能以空 Fixture 冒充迁移证明。

## 11. 防止 God Service 的硬边界

- Context Compiler 只编译领域声明的 Context Requirement；
- Policy Registry 只管理共同版本、激活、失效和审计生命周期，不解释全部领域规则；
- Book Coordinator 只维护 Root Saga、Cursor、阻塞状态和子 Operation 引用；
- Asset Registry 只管理共同元数据、版本、依赖、决策和证据，不取代领域 Payload Schema；
- Agent Center 只提供角色、权限、Run/Checkpoint/Gate 视图，不重新实现 Workflow、Scheduler、Provider 或 Commit；
- Production Quality Gate 消费已批准 JudgeProfile；Eval Lab 负责实验和晋升证据，两者不共享一套可被实验结果直接改写的生产状态；
- Shared Kernel 只接受至少被当前纵向 Slice 使用的抽象，不预建万能工作流或万能 JSON 平台。
