# Loop Engineering Kernel Design

生成时间：2026-07-03

## 定位

Phase 6 新增 `loop_kernel`，目标是把生成、审稿、修订、复盘这类生产动作收敛为可停止、可 checkpoint、可报告的 LoopRun。它不是新的 workflow scheduler，也不替换现有 Agent runtime；它是 Context Builder、ReviewIssue、OS Envelope 之上的循环控制层。

## 资产模型

本阶段使用 local-first asset，而不是新增独立 SQL 表。

| 资产 | 类型 | 目录 | 作用 |
| -- | -- | -- | -- |
| LoopRun | `loop_run` | `data/loops` | Loop 顶层运行记录，保存状态、预算、stop condition、trace、context bundle。 |
| LoopStep | `loop_step` | `data/loops` | 单步执行记录，保存 operation、usage、context、ReviewIssue gate 结果。 |
| LoopCheckpoint | `loop_checkpoint` | `data/loops` | 每步后的恢复点，保存 last_step 和 budget usage。 |
| LoopReport | `loop_report` | `data/loops` | Loop 结束报告，保存 stop reason、steps、checkpoints、blocking issue 和建议。 |

LoopBudget 作为 `loop_run.content.budget` 结构保存：

```json
{
  "max_steps": 6,
  "max_tokens": 4000,
  "max_cost": 1.0,
  "max_duration_seconds": 1800
}
```

LoopStopCondition 固定为：

```text
quality_passed
blocking_issue
budget_exceeded
provider_timeout
human_required
```

LoopState 固定为：

```text
planned
running
waiting_human
succeeded
failed
cancelled
```

## 服务边界

核心入口：`src/novel_forge/modules/loop_kernel/service.py::run_loop`

支持的第一批 loop：

| loop_type | Context Builder flow | 当前能力 |
| -- | -- | -- |
| `chapter_review` | `review` | 构建 context，检查 blocking ReviewIssue，质量通过或中止。 |
| `outline_revision` | `revision` | 记录 outline revision loop 步骤，受 budget gate 控制。 |
| `longform_recap` | `recap` | 预留并可执行 recap loop 步骤；真实 recap 写回在 Phase 7。 |

## 集成点

- OS Envelope：`run_loop` 调用 `enforce_os_envelope`。production 缺 envelope fail closed；dev/test 可显式 bypass。
- Context Builder：有 `target_path` 且无现有 `context_bundle_path` 时，调用 `build_flow_context_bundle`。
- ReviewIssue：`review_issue_gate` 步骤调用 `blocking_review_issues`，发现 blocking issue 后以 `blocking_issue` 中止。
- RAG isolation：`loop_run`、`loop_step`、`loop_checkpoint`、`loop_report` 加入 `GENERATION_RAG_BLOCKED_TYPES`，且 metadata 标记 `use_in_generation_rag=false`。
- Trace：Loop 完成后写入 `trace_span`，span_type 为 `loop_run`。

## 失败策略

| 场景 | 行为 |
| -- | -- |
| blocking ReviewIssue | LoopStep 写 failed，LoopRun failed，LoopReport 给出 issue 列表。 |
| budget exceeded | LoopStep 写 failed 或在下一步前停止，LoopRun failed，LoopReport 标记预算原因。 |
| provider timeout | LoopStep 写 failed，stop_condition=`provider_timeout`。 |
| human required | LoopRun 转 `waiting_human`，保留 checkpoint。 |
| production 缺 envelope | 直接抛错，不创建 production LoopRun。 |

## 回滚与恢复

本阶段不自动修改业务资产，因此不需要业务 rollback。恢复能力由 `loop_checkpoint` 提供：每步 checkpoint 保存 `last_step_path`、usage、stop condition。Phase 8 Agent Center 可读取这些 checkpoint，Phase 7/10 可在业务写回前扩展 rollback plan。

## API

新增最小 API：

- `GET /product/loops`
- `GET /product/loops/{loop_ref}`
- `POST /product/loops/run`
- `POST /product/loops/cancel`

## 测试策略

- `tests/unit/test_loop_kernel.py`
  - 正常 chapter review loop 写 context/checkpoint/report；
  - blocking ReviewIssue 中止；
  - budget exceeded 中止；
  - production 缺 envelope fail closed，带 envelope 可执行。
- 相邻回归：
  - schema；
  - product API route；
  - MKAOS isolation；
  - Context Builder + MKAOS；
  - MKAOS P0；
  - ReviewIssue。
