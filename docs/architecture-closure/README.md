# Architecture Closure Execution Index

更新时间：2026-08-03

状态：`TRACK_B_5_VERIFIED_D0_BLOCKED_C1_NOT_STARTED`

主文档：[`autonomous-novel-os-architecture-closure-epic.md`](autonomous-novel-os-architecture-closure-epic.md)

当前实现证据 SHA：`8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`

当前 Gate：Track A 与 Track B 最小纵向切片已通过；Track B.5 已证明 Transaction Command 原子性、精确故障回滚和 Scope 约束；D0 Authority Harness 已持久化，但真实 Provider Probe 因缺少凭据阻塞；BookDesign/Planning 收敛 ADR 已接受，C1 未开始。证据见 [`../reports/track-b-execution-semantics-hardening.md`](../reports/track-b-execution-semantics-hardening.md)、[`../reports/d0-authority-provider-qualification.md`](../reports/d0-authority-provider-qualification.md) 和 [`../reports/track-c-convergence-review.md`](../reports/track-c-convergence-review.md)。

## 1. 执行方式

Architecture Closure 已从 AC-00 至 AC-19 横向工作包模式调整为六条架构轨道、逐条纵向闭环模式。

```text
Track A — Trusted Baseline And Governance
Track B — Shared Authority Kernel And Storage
Track C — Novel Domain And Context
Track D — Intelligence, Execution And Quality
Track E — Autonomous Book Runtime And Operations
Track F — Migration, Long-form And Scale Proof
```

AC-00 至 AC-19 文档继续保留，但其定位变更为：

- ADR 和架构约束参考；
- 当前/目标代码位置清单；
- 数据迁移和退役检查表；
- 测试矩阵与 Reviewer Checklist；
- 跨轨道影响分析索引。

AC 文档不再独立排期，不维护独立完成百分比，也不得单独用于宣布 Architecture Closure 进度。

## 2. 纵向切片规则

每个 Slice 必须从真实入口走到正式 Authority 结果：

```text
API / CLI / Parent Saga
→ identity and scope
→ command and idempotency
→ transaction/job/saga/effect
→ domain validation
→ Candidate and Decision
→ PostgreSQL Authority Commit
→ Object Store evidence when needed
→ query projection
→ recovery and operator visibility
→ current-SHA tests and report
```

以下不构成 Slice 完成：

- 仅 Schema；
- 仅数据库表；
- 仅接口定义；
- 仅 Web 页面；
- 仅 Scripted Provider；
- 仅历史测试报告；
- 仅 LocalStorage 路径；
- 仅文档状态更新。

## 3. 六轨道索引

| Track | 目标 | 必须完成的主要 Slice | 主要 AC 参考 |
|---|---|---|---|
| A | 可信仓库基线和自动治理 | Repository Integrity；Current-SHA Validation；ADR/Fitness Baseline | AC-00、01、02、18、19 |
| B | 共享 Authority、资产和执行内核 | Project/Book Scope；Typed Asset Registry；Execution Classification；Minimal Authority-only Runtime；Slice 内 Legacy Cutover | AC-02、03、04、05、06、15、16、17、18 |
| D0 | 前置真实 Provider 资格探针 | 单 Provider/模型/结构化能力；Auth/Request ID/Usage/Cost/Query/Cancel/UNKNOWN/Late Result | AC-05、12、15、16、18 |
| C | 小说领域和上下文模型 | BookDesign→Plan；ChapterOutcome→StoryState；Context Compiler；Replan/Historical Freeze | AC-06、07、08、09、10、13、18 |
| D | Agent、真实执行和质量 | Qualified Real Provider；Real Chapter；Agent Candidate/Commit；Quality/Eval Separation | AC-09、11、12、13、18 |
| E | 全书自治和生产运维硬化 | L3 Book Chain；L10 Recap/Replan；Readiness/PITR/SLO/Security/Capacity；Operator Intervention | AC-04、05、07、08、09、13、14、15、16、18 |
| F | 剩余 Legacy、长篇和规模证明 | Residual Legacy Retirement；L30 Arc Proof；Post-closure Readiness | AC-03、07、08、10、13、15、16、17、18、19 |

## 4. 推荐执行顺序

```text
Track A
→ Track B
→ D0 Real Provider Qualification Probe
→ Track C
→ Track D
→ Track E
→ Track F
```

允许有限重叠：

- Track A 的 Fitness Tests 和文档治理贯穿全部轨道；
- Track B 后半段可以与 Track C 领域建模并行，但不能同时修改同一 Shared Schema；
- D0 必须在 Track B Minimal Authority-only Runtime 可用后执行；D0 不构成小说质量证明；
- Track D 必须等待 ContextManifest、StoryState 和 Asset Commit 契约稳定；
- Track F 可提前建立 Legacy Inventory，但正式 Writer 切换必须等待对应纵向 Slice 通过。

## 5. WIP 和合并纪律

- 同一时间最多一个主要纵向 Slice 处于实现中；
- 允许额外保留一个缺陷修复或稳定性通道；
- 禁止同时启动多个跨 Shared Kernel 的重构；
- 每个 Slice 合并前必须提交 Gate Report；
- 不允许以“以后统一补测试”进入下一个 Slice；
- 迁移文件必须从当前唯一 migration head 分配，不在文档中预占编号；
- 影响 Shared Kernel 的变更必须先更新 ADR 和 Fitness Test；
- 真实 Provider、L3、L10、L30 必须绑定完整 commit SHA、环境和成本证据。

## 6. 轨道 Gate

### Track A

```text
head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
```

### Track B

```text
project_book_scope_authority_proven=true
typed_asset_lifecycle_proven=true
execution_classification_enforced=true
authority_only_minimal_slice_proven=true
production_legacy_write_blocked=true
duplicate_replay_proven=true
query_projection_proven=true
```

### D0

```text
real_provider_auth_proven=true
provider_request_receipt_proven=true
provider_usage_proven=true
provider_cost_proven=true
provider_timeout_query_cancel_behavior_recorded=true
unknown_reconciliation_proven=true
provider_restart_recovery_proven=true
```

### Track B.5 / C1 admission

```text
transaction_command_atomicity_proven=true
inflight_command_recovery_semantics_proven=true
execution_classification_consistent=true
architecture_fitness_scope_hardened=true
asset_scope_database_constraints_proven=true
book_design_planning_convergence_adr_accepted=true
```

这些字段与 D0 全部真实 Gate 必须同时为 true 才能进入 C1。Fixture
query/reconcile 或应用重建不得被记作真实 Provider restart proof。

### Track C

```text
book_design_to_plan_proven=true
story_state_replay_proven=true
context_reproducibility_proven=true
source_material_knowledge_boundary_proven=true
historical_freeze_and_replan_proven=true
```

### Track D

```text
single_capability_real_provider_proven=true
single_chapter_real_provider_proven=true
real_usage_proven=true
real_cost_proven=true
agent_candidate_commit_boundary_proven=true
production_quality_eval_separation_proven=true
```

### Track E

```text
book_coordinator_l3_proven=true
book_coordinator_l10_proven=true
recap_replan_loop_proven=true
production_runtime_hardening_verified=true
persistent_state_restart_proven=true
inflight_durable_job_recovery_proven=true
provider_external_effect_restart_recovery_proven=true
operator_intervention_flow_proven=true
```

### Track F

```text
critical_legacy_writers_retired=true
l30_arc_proven=true
cross_book_contamination_baseline_passed=true
architecture_closure_gate_passed=true
```

## 7. AC 参考文档

### Baseline And Governance

- [AC-00 仓库与 HEAD 完整性](ac-00-repository-head-integrity.md)
- [AC-01 架构原则与 ADR 治理](ac-01-architecture-principles-and-adrs.md)
- [AC-02 领域边界与依赖规则](ac-02-domain-boundaries-and-dependency-rules.md)
- [AC-18 Architecture Fitness Tests](ac-18-architecture-fitness-tests.md)
- [AC-19 文档与变更治理](ac-19-documentation-and-change-governance.md)

### Shared Kernel And Storage

- [AC-03 Authority 与存储边界](ac-03-authority-and-storage-boundaries.md)
- [AC-04 Project、Workspace、Book 与 Scope](ac-04-project-workspace-book-and-scope.md)
- [AC-05 Command Kernel 与执行语义](ac-05-command-kernel-and-execution-semantics.md)
- [AC-06 统一资产版本模型](ac-06-unified-asset-version-model.md)
- [AC-15 API、事件与契约](ac-15-api-events-and-contracts.md)
- [AC-16 部署、运维与安全](ac-16-deployment-operations-and-security.md)
- [AC-17 Legacy 迁移与退役](ac-17-legacy-migration-and-retirement.md)

### Novel Domain And Context

- [AC-07 分层规划](ac-07-hierarchical-planning-authority.md)
- [AC-08 Canon 与 StoryState](ac-08-canon-and-story-state.md)
- [AC-09 Context Builder](ac-09-context-builder.md)
- [AC-10 Source 与 MKAOS](ac-10-source-and-mkaos-authority.md)

### Intelligence And Runtime

- [AC-11 Agent Collaboration](ac-11-agent-collaboration.md)
- [AC-12 Provider 与外部执行](ac-12-provider-and-external-execution.md)
- [AC-13 Quality、Eval 与 Release Gate](ac-13-quality-eval-and-release-gates.md)
- [AC-14 Book Production Supervisor](ac-14-book-production-supervisor.md)
- [最小稳定契约与 God Service 防线](minimal-stable-contracts.md)

这些标题保留历史命名。实施时应遵循主 Epic 中的新术语：

- `Context Builder` 以 `Context Compiler` 职责实现；
- `Book Production Supervisor` 以 `Book Production Coordinator` 职责实现；
- `Quality Authority` 拆分为 Production Quality Gate 和 Evaluation And Calibration Lab；
- Source、Material、Knowledge 必须分层；
- 不得因为文档标题包含 Authority 就为每个领域建立独立执行内核。

## 8. Slice Gate Report 模板

每个纵向 Slice 至少记录：

```text
slice_id=
track=
baseline_commit_sha=
result_commit_sha=
environment=
entrypoint=
authority_commit=
query_projection=
legacy_write_path=
legacy_source=
authority_target=
import_validation=
writer_cutover=
reader_compatibility=
retirement_deadline=
provider_or_external_effect=
usage_and_cost_evidence=
recovery_scenarios=
test_commands=
test_counts=
failures=
errors=
skips=
known_limits=
gate_passed=true|false
```

不得通过修改文档直接将 Gate 设为 `true`。必须引用当前 SHA、CI run、测试输出、数据库证据和必要的真实外部执行报告。

## 9. Architecture Closure 最终退出条件

```text
一个完整当前 SHA 可构建和部署
一套 Authority-only Runtime 可启动
一个真实 Provider 章节可恢复并记录成本
一条 Book→Chapter→Outcome→StoryState 链完成 L10
一个真实 L30 Arc 可重规划、恢复和审计
全书关键 Legacy Writer 已退役
Architecture Fitness Tests 阻止架构回退
```

通过后进入：

```text
L100 → L300 → L1M
3 → 5 → 10 Books
Official Publishing Adapter
Feedback And Controlled Learning
Multi-user Productization
```
