# Architecture Closure Work Package Index

更新时间：2026-08-02  
状态：下一阶段 Epic 执行入口  
主文档：[`autonomous-novel-os-architecture-closure-epic.md`](autonomous-novel-os-architecture-closure-epic.md)

## 使用方式

每个 AC 文档均包含：

- ADR；
- 实施计划；
- 当前与目标代码位置；
- 迁移脚本设计；
- 测试矩阵；
- Acceptance Gate；
- 依赖、风险与交付物。

这些文档是目标架构与实施规范，不是实现证明。完成状态必须以当前 SHA 的代码、迁移、测试和部署证据更新。

## 工作包索引

| ID | 文档 | 阶段 | 前置依赖 |
|---|---|---|---|
| AC-00 | [仓库与 HEAD 完整性](ac-00-repository-head-integrity.md) | Phase 0 | 无 |
| AC-01 | [架构原则与 ADR 治理](ac-01-architecture-principles-and-adrs.md) | Phase 0 | AC-00 |
| AC-02 | [领域边界与依赖规则](ac-02-domain-boundaries-and-dependency-rules.md) | Phase 1 | AC-00, AC-01 |
| AC-03 | [Authority 与存储边界](ac-03-authority-and-storage-boundaries.md) | Phase 1 | AC-01, AC-02 |
| AC-04 | [Project、Workspace、Book 与 Scope](ac-04-project-workspace-book-and-scope.md) | Phase 1 | AC-02, AC-03 |
| AC-05 | [Command Kernel 与统一执行语义](ac-05-command-kernel-and-execution-semantics.md) | Phase 1 | AC-03, AC-04 |
| AC-06 | [统一资产版本模型](ac-06-unified-asset-version-model.md) | Phase 1 | AC-03, AC-05 |
| AC-07 | [分层规划 Authority](ac-07-hierarchical-planning-authority.md) | Phase 2 | AC-04, AC-05, AC-06 |
| AC-08 | [Canon 与 StoryState](ac-08-canon-and-story-state.md) | Phase 2 | AC-05, AC-06, AC-07 |
| AC-09 | [Context Builder](ac-09-context-builder.md) | Phase 2 | AC-06, AC-07, AC-08, AC-10 contract |
| AC-10 | [Source 与 MKAOS Authority](ac-10-source-and-mkaos-authority.md) | Phase 2 | AC-03, AC-04, AC-06 |
| AC-11 | [Agent Collaboration](ac-11-agent-collaboration.md) | Phase 3 | AC-04, AC-05, AC-06, AC-09 |
| AC-12 | [Provider 与外部执行](ac-12-provider-and-external-execution.md) | Phase 3 | AC-05, AC-09 |
| AC-13 | [Quality、Eval 与 Release Gate](ac-13-quality-eval-and-release-gates.md) | Phase 3 | AC-06, AC-08, AC-09, AC-12 |
| AC-14 | [Book Production Supervisor](ac-14-book-production-supervisor.md) | Phase 4 | AC-05–AC-13 |
| AC-15 | [API、事件与契约](ac-15-api-events-and-contracts.md) | Phase 4 | AC-02, AC-05, AC-06, AC-14 |
| AC-16 | [部署、运维与安全](ac-16-deployment-operations-and-security.md) | Phase 4 | AC-00, AC-03, AC-05, AC-12, AC-15 |
| AC-17 | [Legacy 迁移与退役](ac-17-legacy-migration-and-retirement.md) | Phase 5 | AC-03–AC-16 |
| AC-18 | [Architecture Fitness Tests](ac-18-architecture-fitness-tests.md) | Phase 0–5 | 全部工作包持续接入 |
| AC-19 | [文档与变更治理](ac-19-documentation-and-change-governance.md) | Phase 0–5 | 全部工作包持续接入 |

## 推荐执行节奏

```text
Milestone A — Trusted Baseline
AC-00 + AC-01 + AC-18 foundation

Milestone B — Shared Kernel Closure
AC-02 + AC-03 + AC-04 + AC-05 + AC-06

Milestone C — Novel Domain Closure
AC-07 + AC-08 + AC-09 + AC-10

Milestone D — Intelligence and Decision Closure
AC-11 + AC-12 + AC-13

Milestone E — Autonomous Book Runtime Closure
AC-14 + AC-15 + AC-16

Milestone F — Migration and Proof
AC-17 + AC-18 full + AC-19 full + L3/L10/L30
```

## 状态字段

实施时建议在每个工作包顶部维护：

```text
architecture_defined=true|false
implementation_present=true|false
migration_applied=true|false
unit_verified=true|false
postgres_integration_verified=true|false
deployment_verified=true|false
external_execution_proven=true|false
acceptance_gate_passed=true|false
```

不得通过修改文档直接将状态设为 true；必须引用当前 SHA、测试命令、CI run 或生产证明报告。

## 跨工作包变更纪律

- 修改 Authority 所有权：必须同时更新 AC-02、AC-03、AC-19。
- 修改 Operation/Saga/Attempt：必须同时更新 AC-05、AC-15、AC-18。
- 修改 AssetVersion：必须同时更新 AC-06 及受影响领域工作包。
- 修改 Plan hierarchy：必须同时更新 AC-07、AC-08、AC-14。
- 修改 ContextManifest：必须同时更新 AC-09、AC-11、AC-12、AC-13。
- 修改 Provider route/receipt/cost：必须同时更新 AC-12、AC-13、AC-16。
- 修改生产部署或权限：必须同时更新 AC-04、AC-16、AC-18。
- 新增 Legacy 依赖：必须在 AC-17 登记退役期限，不允许无期限兼容。