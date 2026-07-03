# Longform Recap Agent Design

生成时间：2026-07-03

## 定位

Longform Recap Agent 不是章节总结器，而是长篇稳定性治理 Agent。它在每 10 章、卷结束、blocking issue 超阈值或重大设定变更时运行，读取 Context Builder、ReviewIssue、MKAOS Pack、长篇稳定性资产和最近章节，输出可写回的治理报告。

## 入口

核心服务：

- `src/novel_forge/modules/longform_recap/service.py::evaluate_recap_trigger`
- `src/novel_forge/modules/longform_recap/service.py::run_longform_recap`

最小 API：

- `GET /product/longform-recap/reports`
- `POST /product/longform-recap/trigger`
- `POST /product/longform-recap/run`

## 触发规则

| 触发 | 实现 |
| -- | -- |
| 每 10 章 | `latest_chapter >= 10` 且项目已有至少 10 章时触发。 |
| 每卷结束 | `volume_end=true`。 |
| blocking issue 超阈值 | active blocking ReviewIssue 数量大于等于阈值，默认 3。 |
| 重大设定变更 | `major_setting_change=true`。 |
| 人工触发 | `force=true`。 |

## 输入

Recap Agent 读取：

- 最近章节 draft metadata，不读取原始来源全文；
- chapter_state、fact_ledger、character_state_ledger；
- foreshadowing_graph、motif_budget_report、reader_fatigue_report、reward_ledger；
- active ReviewIssue；
- Context Builder recap bundle；
- MKAOS Pack；
- LoopRun/LoopReport。

## 输出

新增资产：`longform_recap_report`。

核心字段：

- `stage_summary`
- `continuity_risks`
- `character_drift_report`
- `foreshadowing_report`
- `pacing_report`
- `commercial_rhythm_report`
- `revision_suggestions`
- `memory_update_package`
- `writeback`

## 写回策略

| 目标 | 写回方式 |
| -- | -- |
| Canon | 写 `canon_patch`，human gate 默认 waiting，不直接覆盖 canon。 |
| Character | 写 `character_state_ledger` recap ledger。 |
| Arc | 若已有 `arc_plan`，追加 `recap_history`；否则创建 recap inferred arc。 |
| Foreshadowing | 写 recap `foreshadowing_graph`。 |
| ReviewIssue | 将高风险 recap finding 转成结构化 ReviewIssue。 |
| RevisionTask | 写 `revision_task`，供后续修订 Loop 消费。 |
| MKAOS | 使用 recap context 中的 knowledge ids 写 usage event 和小幅 feedback score。 |

## Context Builder

`longform_recap_report` 已加入 Context Builder 的 `previous_summaries` bucket。下一章构建上下文时可以显式或自动选入 recap report。

## Source Isolation

Recap Report 只保存章节号、标题、风险和抽象治理包，不保存 `source_chunk.raw_text`。测试覆盖 report 与下一章 context bundle 中不含 `raw_text`。

## Phase 边界

本阶段完成结构化治理写回和 12 章触发 proof。更深的 Agent Center 展示、UI 页面、Publish/Feedback 完整闭环分别进入 Phase 8、Phase 9、Phase 10。
