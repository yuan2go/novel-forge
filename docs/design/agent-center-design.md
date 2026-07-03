# Agent Center Design

日期：2026-07-03

## 定位

Agent Center 不是新的 Agent 执行器，也不是替代既有 Agent Scheduler。它是 Novel OS v6 的可观察、可派发、可审计控制面：把 `agent_task`、`agent_run`、`agent_dispatch_queue`、`loop_run`、`context_bundle`、`review_issue`、`revision_task` 和 handoff 证据聚合到同一项目视图。

## 资产边界

| 资产 | 存储目录 | 用途 | 生成 RAG |
| -- | -- | -- | -- |
| `agent_task` | `data/runs` | Agent Center 的人工/系统派发锚点，连接 issue、revision task、run、queue。 | 禁止 |
| `agent_run` | `data/runs` | 既有 Agent runtime 执行记录。 | 禁止 |
| `agent_dispatch_queue` | `data/runs` | 既有 scheduler queue、lease、retry、dead-letter。 | 禁止 |
| `loop_run` | `data/loops` | Loop Kernel 治理循环状态。 | 禁止 |
| `context_bundle` | `data/contexts` | Context Builder 审计上下文。 | 受 Context Builder source policy 控制 |
| `review_issue` | `data/reviews` | 可阻断质量/连续性/Canon/MKAOS issue。 | 禁止作为生成 RAG 运行资产 |
| `revision_task` | `data/reviews` | 从 issue 派发的结构化修订任务。 | 禁止作为生成 RAG 运行资产 |

## 服务边界

`src/novel_forge/modules/agent_scheduler/service.py` 继续拥有 Agent Scheduler。Agent Center 新增的职责限定为：

1. 创建 `agent_task`。
2. 从 `review_issue` 派发最小 `revision_task`、`agent_task`、`agent_run` 和 `agent_dispatch_queue`。
3. 在 `agent_center_snapshot` 中聚合 runtime 证据。
4. 以项目内 `agent_task` / `loop_run` 为锚点补取链接的 run、queue、context，避免为了 UI 过滤改写跨项目运行资产。

## 失败策略

1. 未找到 `review_issue` 时返回 404/API 层错误。
2. `agent_run` 使用现有 runtime profile；默认派发 profile 为 `review`，避免引用不存在的 `editor` profile。
3. AgentTask 写入必须通过 schema validation。
4. `agent_task` 显式 `use_in_generation_rag=false`，并列入 RAG runtime asset blocklist。

## API

| API | 用途 |
| -- | -- |
| `GET /product/agents/center` | 统一 Agent Center 快照。 |
| `POST /product/agents/tasks` | 创建 AgentTask。 |
| `POST /product/agents/tasks/from-issue` | 从 ReviewIssue 派发 RevisionTask + AgentTask + AgentRun + DispatchQueue。 |

## UI

`/agent-dispatch` 继续作为 Agent Center 最小 UI，新增：

1. AgentTask 列表。
2. Runtime links JSON。
3. LoopRun / ContextBundle 面板。
4. ReviewIssue / RevisionTask 面板。
5. 从 ReviewIssue 派发 AgentTask 的按钮。

## 关键取舍

没有把 `agent_run` 强行改写为项目资产。原因是 AgentRun 可能引用 local-system 的 AgentContract，直接改写 `metadata.project_id` 会触发 cross-project write guard。Agent Center 改用项目内 AgentTask 的链接补取机制，把相关 run/queue 纳入项目视图，同时保留底层资产真实归属。
