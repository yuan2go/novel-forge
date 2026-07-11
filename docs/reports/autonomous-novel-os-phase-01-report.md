# Autonomous Novel OS Phase 01 Report

> 日期：2026-07-11  
> 状态：partial  
> 范围：Production Kernel parent operation、Execution Envelope 持久化和幂等回放

## 解决了什么

- 新增 schema-backed `production_operation` 资产，写入 `data/runs/`，保存父级 operation、`state_owner`、请求摘要、Execution Envelope、输入引用、预期输出、child projection、结果和恢复错误。
- `dispatch_production_operation` 在路由 Workflow、Agent、Loop、Chapter Production 前持久化父记录；child 仍分别由 `WorkflowRun`、`AgentRun`、`LoopRun`、`ChapterProductionRun` 保持状态权威。
- 服务端按 `idempotency_key` 和 request digest 做回放/冲突判断：同一请求返回既有父记录，不再重复调用 child；同 key 不同请求拒绝并保留原运行。
- child 抛出异常时，父记录进入 `failed`，包含错误类型、错误消息和 recovery instruction。
- production 环境仍由现有 `enforce_os_envelope` fail-closed；compat/local 请求明确归入 `system` scope，不伪装成小说项目。
- `ProductionOperationReconciliationReport` 对账父 projection 与 child Run，标记 `aligned`、`asynchronous_child`、`diverged` 或 `missing_child`；报告不修改历史状态。
- 章节同步 resume/pause/cancel/recover API 现在先按 child path 查找 parent，并经 Kernel control 更新 parent；没有 parent 的历史 child 返回显式 `kernel_compatibility=legacy_child_without_production_operation`。

## 代码证据

- `src/novel_forge/schemas/assets.py`：`ProductionOperation`
- `src/novel_forge/schemas/base.py`：required fields 和状态/envelope/child 校验
- `src/novel_forge/core/constants.py`：`production_operation -> runs`
- `src/novel_forge/modules/production_kernel/entrypoints.py`：注册入口和 `parent_state_owner`
- `src/novel_forge/modules/production_kernel/service.py`：父记录创建、回放、冲突、失败更新、child projection 和 bounded lifecycle control
- `src/novel_forge/api/routers/runtime.py`：生产入口审计、父运行查询和 control API
- `src/novel_forge/schemas/assets.py`：`ProductionOperationReconciliationReport`

## 测试证据

- `tests/unit/test_production_entrypoint_contract.py`：13 tests，包括 schema、入口父级、重复请求、幂等冲突、child 异常恢复、write budget、bypass scan、父级查询、cancel control 和状态对账。
- `tests/unit/test_os_envelope_v2.py`、`tests/unit/test_chapter_production_envelope_contract.py`：共 15 tests 通过。
- Phase 0/Phase 01 回归：新增 schema 后首次全量回归发现并修复 schema registry count 期望；修复后连续两轮 Python 全量均为 820 pass / 0 fail / 0 error / 2 skipped（589.582 秒、599.251 秒）。`make validate`、`make lint`、`make check-skills`、Web lint/test、`git diff --check` 均通过；Web 为 11 pass / 1 skipped，Playwright 仍未安装。

## 真实 Provider / Fixture 边界

本阶段没有调用真实 Provider、真实平台或外部凭据。Kernel 测试使用 patched child runner，仅证明父级持久化、边界、幂等和错误恢复；不能证明真实章节正文、Provider 成本或 10/30 章长链质量。

## 没有解决什么

- 仍未证明 CLI、所有 API/Worker、Revision、Recap、Publish 等历史 control 调用全部经过 Kernel；章节同步 control 已迁移，异步 Celery control 与其他旧 control API 仍有 direct-child compatibility path。
- parent boundary 当前支持有限的 pause/resume/cancel/recover，并能生成只读状态对账；统一 retry/timeout/compensate/fail/complete command API 尚未完成，子 Run 的领域状态机仍分散。
- Envelope 尚未由 PostgreSQL 工业事务库权威保存，当前持久化是 LocalStorage JSON；没有 Asset + StateEvent + Outbox 原子 UoW 或双写故障注入证据。
- Kernel 尚未强制每个 child 写入完整 ContextManifest/ContextBundle、Provider Runtime Gate、model call log 和 cost ledger；这些仍由下游路径分别治理。

## 回滚方式

按提交边界回滚 `d0c9972` 和 `c29cee6` 即可移除本阶段新增父资产与 Kernel parent 逻辑；不删除已有 child Run、Envelope、Trace 或历史运行资产。执行回滚前需先停止使用新 `production_operation` 查询的调用方。

## 下一阶段条件

继续 Phase 1：把旧 chapter/workflow/loop/agent control API 迁移到 parent control boundary，补状态对账和 timeout/compensation contract；完成后再进入 Context Builder 全入口收敛。当前阶段不得标记为 complete，也不得作为 10/30 章生产验收证据。
