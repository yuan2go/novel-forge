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

## 代码证据

- `src/novel_forge/schemas/assets.py`：`ProductionOperation`
- `src/novel_forge/schemas/base.py`：required fields 和状态/envelope/child 校验
- `src/novel_forge/core/constants.py`：`production_operation -> runs`
- `src/novel_forge/modules/production_kernel/entrypoints.py`：注册入口和 `parent_state_owner`
- `src/novel_forge/modules/production_kernel/service.py`：父记录创建、回放、冲突、失败更新和 child projection

## 测试证据

- `tests/unit/test_production_entrypoint_contract.py`：9 tests，包括 schema、入口父级、重复请求、幂等冲突、child 异常恢复和 write budget。
- `tests/unit/test_os_envelope_v2.py`、`tests/unit/test_chapter_production_envelope_contract.py`：共 15 tests 通过。
- Phase 0 基线：Python 812 pass / 0 fail / 0 error / 2 skipped；`make validate`、`make lint`、`make check-skills`、Web lint/test、`git diff --check` 均通过；Playwright 仍未安装，Web browser smoke 未执行。

## 真实 Provider / Fixture 边界

本阶段没有调用真实 Provider、真实平台或外部凭据。Kernel 测试使用 patched child runner，仅证明父级持久化、边界、幂等和错误恢复；不能证明真实章节正文、Provider 成本或 10/30 章长链质量。

## 没有解决什么

- 仍未证明 CLI、所有 API/Worker、Revision、Recap、Publish 等历史直接调用全部经过 Kernel；当前只覆盖注册表中的五类 dispatch operation。
- `start/resume/retry/cancel/timeout/compensate` 尚未形成统一 parent command API；子 Run 的状态机仍分散。
- Envelope 尚未由 PostgreSQL 工业事务库权威保存，当前持久化是 LocalStorage JSON；没有 Asset + StateEvent + Outbox 原子 UoW 或双写故障注入证据。
- Kernel 尚未强制每个 child 写入完整 ContextManifest/ContextBundle、Provider Runtime Gate、model call log 和 cost ledger；这些仍由下游路径分别治理。

## 回滚方式

按提交边界回滚 `d0c9972` 和 `c29cee6` 即可移除本阶段新增父资产与 Kernel parent 逻辑；不删除已有 child Run、Envelope、Trace 或历史运行资产。执行回滚前需先停止使用新 `production_operation` 查询的调用方。

## 下一阶段条件

继续 Phase 1：建立 direct-entrypoint bypass scan、parent lifecycle command contract、状态对账报告，并将剩余生产入口逐一迁移到 Kernel；完成后再进入 Context Builder 全入口收敛。当前阶段不得标记为 complete，也不得作为 10/30 章生产验收证据。
