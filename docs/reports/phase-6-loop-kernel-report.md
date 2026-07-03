# Phase 6 Loop Kernel Report

生成时间：2026-07-03

## 完成内容

Phase 6 已新增 Loop Engineering Kernel 第一片实现：

- 新增 `src/novel_forge/modules/loop_kernel/service.py`。
- 新增 Loop 资产：
  - `loop_run`
  - `loop_step`
  - `loop_checkpoint`
  - `loop_report`
- 新增 `data/loops` 目录映射。
- 新增最小 API：
  - `GET /product/loops`
  - `GET /product/loops/{loop_ref}`
  - `POST /product/loops/run`
  - `POST /product/loops/cancel`
- Loop runtime asset 已加入 generation RAG 黑名单。
- 新增 `tests/unit/test_loop_kernel.py`。

## 架构取舍

本阶段没有替换现有 workflow scheduler / Agent scheduler。LoopKernel 是它们上层或旁侧的循环控制资产层：

| 组件 | 保持职责 | Phase 6 新增关系 |
| -- | -- | -- |
| Workflow scheduler | DAG、node、queue、resume | 后续可把 node operation 包进 LoopStep。 |
| Agent runtime | AgentRun、checkpoint、budget、gate | 后续 Agent Center 可把 AgentRun 挂到 LoopRun。 |
| Context Builder | 上下文统一入口 | LoopRun 通过 `build_flow_context_bundle` 获取 context。 |
| ReviewIssue | blocking issue 持久化 | LoopStep 的 `review_issue_gate` 可阻断 loop。 |
| OS Envelope | production runtime contract | `run_loop` 在 production 缺 envelope 时 fail closed。 |

## 当前支持的 Loop

| loop_type | 状态 | 说明 |
| -- | -- | -- |
| `chapter_review` | 已可执行 | 可构建 context、检查 ReviewIssue、写 checkpoint/report。 |
| `outline_revision` | 已可执行 | 可记录 revision loop，并受 budget gate 控制。 |
| `longform_recap` | 可执行骨架 | 可运行 recap loop 步骤；真实 recap 写回进入 Phase 7。 |

## 关键证据

| 能力 | 证据 |
| -- | -- |
| Context Builder 接入 | `run_loop` 调用 `build_flow_context_bundle`；测试 `test_chapter_review_loop_writes_context_checkpoint_and_report`。 |
| ReviewIssue 阻断 | `review_issue_gate` 调用 `blocking_review_issues`；测试 `test_loop_stops_on_blocking_review_issue`。 |
| Budget stop | `_budget_stop_condition`；测试 `test_loop_stops_on_budget_exceeded`。 |
| OS Envelope fail closed | `enforce_os_envelope`；测试 `test_production_loop_requires_os_envelope`。 |
| Runtime RAG isolation | `GENERATION_RAG_BLOCKED_TYPES` 包含 Loop 资产；测试读取 `generation_context_policy`。 |

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/loop_kernel src/novel_forge/schemas src/novel_forge/api/routers/loops.py src/novel_forge/api/routers/__init__.py` | OK |
| `python3 -m unittest tests/unit/test_loop_kernel.py` | 4 tests OK |
| `python3 -m unittest tests/unit/test_schemas.py` | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | 1 test OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | 4 tests OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py tests/unit/test_mkaos.py tests/unit/test_review_issue.py` | 10 tests OK |
| `python3 -m unittest tests/unit/test_workflow_executor.py` | 27 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK，用时 410.099s |

## 未完成项

- LoopStep 尚未直接执行真实 Agent operation；当前是可审计 loop control layer。
- Longform Recap 的 Canon/Character/Arc/Foreshadowing 写回进入 Phase 7。
- LoopRun 与 AgentRun 的运行图关联进入 Phase 8 Agent Center。
- Publish Gate Loop 与 Feedback Backflow Loop 进入 Phase 10。

## 风险

| 风险 | 级别 | 处理 |
| -- | -- | -- |
| Loop 与 Workflow scheduler 的边界可能在后续变复杂 | P2 | Phase 8 统一展示关联，不在 Phase 6 替换 scheduler。 |
| Longform Recap 当前只是 loop shell | P1 | Phase 7 必须实现结构化 recap 输出和写回。 |
| Loop 资产目前是 local asset，不是 SQL 表 | P3 | 现有 local-first asset store 足够；如生产查询压力上升再加 migration。 |
