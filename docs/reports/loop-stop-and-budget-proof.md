# Loop Stop And Budget Proof

生成时间：2026-07-03

## Proof Summary

Phase 6 的 Loop Kernel 已证明三类硬停止：

| Stop condition | 触发方式 | 证明 |
| -- | -- | -- |
| `quality_passed` | 所有步骤通过，未命中 blocking issue 或 budget overrun。 | `tests/unit/test_loop_kernel.py::test_chapter_review_loop_writes_context_checkpoint_and_report` |
| `blocking_issue` | `review_issue_gate` 发现 active blocking ReviewIssue。 | `tests/unit/test_loop_kernel.py::test_loop_stops_on_blocking_review_issue` |
| `budget_exceeded` | step token/cost/duration 或 max_steps 超预算。 | `tests/unit/test_loop_kernel.py::test_loop_stops_on_budget_exceeded` |
| `provider_timeout` | runtime payload 标记 provider timeout。 | `src/novel_forge/modules/loop_kernel/service.py::run_loop` |
| `human_required` | runtime payload 标记 human required，状态进入 `waiting_human`。 | `src/novel_forge/modules/loop_kernel/service.py::run_loop` |

## Budget Contract

`loop_run.content.budget` 包含：

```json
{
  "max_steps": 6,
  "max_tokens": 4000,
  "max_cost": 1.0,
  "max_duration_seconds": 1800
}
```

`loop_run.content.budget_used` 包含：

```json
{
  "steps": 0,
  "tokens": 0,
  "cost": 0.0,
  "duration_seconds": 0
}
```

每个 `loop_step.content.budget_delta` 记录该步 token/cost 估算，每个 `loop_checkpoint.content.state.usage` 保存累计用量。

## Blocking Proof

测试构造一个 `canon_conflict` critical ReviewIssue，然后运行 `chapter_review` loop。结果：

- `LoopRun.status = failed`
- `LoopRun.stop_condition = blocking_issue`
- `LoopReport.blocking_review_issues[0].issue_type = canon_conflict`
- 后续步骤不继续执行。

## Envelope Proof

`tests/unit/test_loop_kernel.py::test_production_loop_requires_os_envelope` 证明：

- `environment=production` 且缺 `envelope` 时，`run_loop` 抛出 `OS envelope required`；
- 带完整 envelope 时，Loop 可执行，`envelope.status = enforced`。

## RAG Isolation Proof

Loop runtime assets 均加入 `GENERATION_RAG_BLOCKED_TYPES`：

- `loop_run`
- `loop_step`
- `loop_checkpoint`
- `loop_report`

测试对每个 Loop 资产调用 `generation_context_policy`，结果均为 `eligible=false`。
