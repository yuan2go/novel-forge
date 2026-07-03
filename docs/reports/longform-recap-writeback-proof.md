# Longform Recap Writeback Proof

生成时间：2026-07-03

## Proof Summary

测试：`tests/unit/test_longform_recap_agent.py`

| 验收点 | 证明 |
| -- | -- |
| 12 章样例触发至少 1 次 recap | `evaluate_recap_trigger(... chapter_count=12)` 返回 `ten_chapter_interval`。 |
| Recap 输出结构化报告 | 写入 `longform_recap_report`，包含 stage、continuity、character、foreshadowing、pacing、commercial rhythm。 |
| Recap 能读取 ReviewIssue | 测试先写 `foreshadowing_drop` ReviewIssue，Recap summary 统计 active issues。 |
| Recap 能产生 ReviewIssue | `writeback.review_issue_paths` 非空，且 source_system=`longform_recap.agent`。 |
| Recap 能产生 RevisionTask | `writeback.revision_task_path` 非空。 |
| Recap 能回写 Canon | `writeback.canon_patch_path` 非空，且 human gate 为 waiting。 |
| Recap 能回写 Character | `writeback.character_state_ledger_path` 非空。 |
| Recap 能回写 Arc | `writeback.arc_plan_path` 非空，已有 arc 会追加 recap_history。 |
| Recap 能回写 Foreshadowing | `writeback.foreshadowing_graph_path` 非空。 |
| Recap 能回写 MKAOS usage/feedback | `mkaos_usage_event_count > 0` 且 `mkaos_feedback_paths` 非空。 |
| 下一章可读取 recap 状态 | Chapter 13 ContextBundle 显式选入 `longform_recap_report`。 |
| 不泄露 raw source | report 和 next context bundle 均断言不含 `raw_text`。 |

## Writeback Files

Longform Recap Agent 会写：

- `data/continuity/*.json`:
  - `longform_recap_report`
  - `canon_patch`
  - `character_state_ledger`
  - `foreshadowing_graph`
  - `arc_plan` update 或新建
- `data/reviews/*.json`:
  - `review_issue`
  - `revision_task`
- `data/runs/*.json`:
  - `knowledge_usage_event`
- `data/knowledge/*.json`:
  - `knowledge_quality_score`

## Safety Notes

- Canon 只写 proposed patch，不自动 apply。
- Recap report 不保存章节正文，只保存章节号、标题、风险和治理包。
- MKAOS feedback 使用 `flow=review`，`used_as=longform_recap_context`，保持当前 MKAOS P0 flow enum 不破坏。
