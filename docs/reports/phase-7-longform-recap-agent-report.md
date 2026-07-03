# Phase 7 Longform Recap Agent Report

生成时间：2026-07-03

## 完成内容

Phase 7 已实现 Longform Recap Agent 第一片：

- 新增 `src/novel_forge/modules/longform_recap/service.py`。
- 新增资产 `longform_recap_report`。
- 新增 API：
  - `GET /product/longform-recap/reports`
  - `POST /product/longform-recap/trigger`
  - `POST /product/longform-recap/run`
- `longform_recap_report` 可被 Context Builder 作为 `previous_summaries` 读取。
- Recap Agent 接入 Loop Kernel、Context Builder、ReviewIssue、MKAOS usage/feedback。

## 已实现能力

| 能力 | 状态 | 证据 |
| -- | -- | -- |
| 每 10 章触发 | 已实现 | `evaluate_recap_trigger`；`test_twelve_chapter_recap_writes_governance_assets_without_raw_source` |
| ContextBundle 输入 | 已实现 | `run_longform_recap` 调用 `build_flow_context_bundle(flow="recap")` |
| Loop Kernel 接入 | 已实现 | `run_longform_recap` 调用 `run_loop(loop_type="longform_recap")` |
| ReviewIssue 读取/写入 | 已实现 | active issue 进入 recap summary；recap risk 写入 ReviewIssue |
| RevisionTask 输出 | 已实现 | recap suggestions 写 `revision_task` |
| Canon 写回 | 已实现为 human-gated `canon_patch` | `writeback.canon_patch_path` |
| Character 写回 | 已实现 | `writeback.character_state_ledger_path` |
| Arc 写回 | 已实现 | `arc_plan.content.recap_history` 或新建 arc |
| Foreshadowing 写回 | 已实现 | `writeback.foreshadowing_graph_path` |
| MKAOS usage/feedback | 已实现 | `writeback.mkaos_usage_event_count`、`mkaos_feedback_paths` |
| source isolation | 已实现 | 测试断言 report/context 不含 `raw_text` |

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/longform_recap src/novel_forge/modules/context_builder src/novel_forge/modules/longform_stability src/novel_forge/schemas src/novel_forge/api/routers/longform_recap.py src/novel_forge/api/routers/__init__.py` | OK |
| `python3 -m unittest tests/unit/test_longform_recap_agent.py` | 2 tests OK，用时约 14.8s |
| `python3 -m unittest tests/unit/test_schemas.py` | 17 tests OK |
| `python3 -m unittest tests/unit/test_product_api_routes.py` | 1 test OK |
| `python3 -m unittest tests/unit/test_longform_stability.py tests/unit/test_loop_kernel.py` | 12 tests OK |
| `python3 -m unittest tests/unit/test_context_builder_mkaos_flow.py tests/unit/test_mkaos_isolation.py` | 6 tests OK |
| `python3 -m unittest tests.integration.test_longform_quality_gate_e2e` | 1 test OK |

## 取舍

- MKAOS 仍只允许 `outline/chapter_outline/prose/review` flow，因此 Recap Agent 的 MKAOS usage/feedback 使用 `flow=review` 和 `used_as=longform_recap_context`，避免破坏 MKAOS P0 枚举兼容。
- Canon 写回使用 `canon_patch` human gate，不直接覆盖 Canon Database，符合长篇设定变更需要人工确认的边界。
- 当前 recap 文本生成是 deterministic governance report，不调用模型；Phase 11 再补 provider hard-stop proof。

## 遗留风险

| 风险 | 级别 | 后续 |
| -- | -- | -- |
| Recap Agent UI 尚未展示 | P1 | Phase 9 Longform Recap Report Page。 |
| Recap 与 AgentRun/Agent Center 的可视关联还不完整 | P1 | Phase 8 Agent Center。 |
| Recap 的写回仍偏规则化，缺模型辅助分析 | P2 | Phase 11 provider hard-stop proof 后可加入 guarded model route。 |
