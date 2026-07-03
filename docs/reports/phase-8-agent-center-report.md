# Phase 8 Agent Center Report

日期：2026-07-03

## 完成内容

1. 新增 `agent_task` schema，并注册到 `SCHEMA_CLASSES`、资产目录和 required fields。
2. `agent_task` 加入 generation RAG blocklist，避免运行资产污染生成检索。
3. 扩展 Agent Scheduler：
   - `create_agent_task`
   - `dispatch_revision_task_from_issue`
   - Agent Center snapshot 聚合 AgentTask、LoopRun、ContextBundle、ReviewIssue、RevisionTask、Handoff。
4. 从 ReviewIssue 派发时落地真实 `revision_task`，再创建 AgentTask、AgentRun、DispatchQueue。
5. Agent Center project view 使用 AgentTask / LoopRun 链接补取 run、queue、context，避免改写跨项目运行资产。
6. 新增 API：
   - `POST /product/agents/tasks`
   - `POST /product/agents/tasks/from-issue`
7. 扩展 `/agent-dispatch` UI：
   - AgentTask 列表；
   - Runtime links；
   - Loop / Context 面板；
   - ReviewIssue / RevisionTask 面板；
   - ReviewIssue dispatch 按钮。

## 证据文件

| 类型 | 文件 |
| -- | -- |
| Schema | `src/novel_forge/schemas/assets.py`, `src/novel_forge/schemas/base.py`, `src/novel_forge/schemas/__init__.py` |
| 服务 | `src/novel_forge/modules/agent_scheduler/service.py` |
| API | `src/novel_forge/api/models.py`, `src/novel_forge/api/routers/agents.py` |
| RAG 隔离 | `src/novel_forge/storage/rag_context.py` |
| UI | `web/admin/app/features/os/AgentDispatchCenterPage.tsx`, `web/admin/app/features/os/api.ts` |
| 测试 | `tests/unit/test_agent_scheduler.py`, `tests/unit/test_schemas.py` |

## 关键取舍

1. 没有新增独立 Agent Center scheduler，复用现有 Agent Scheduler，避免双执行路径。
2. 默认 from-issue 派发使用现有 `review` runtime profile，而不是新增未定义 `editor` profile。
3. 不强制把 AgentRun 改成项目资产；AgentRun 可引用 local-system AgentContract。Agent Center 使用 AgentTask 链接把项目相关 run/queue 纳入视图。
4. Phase 8 的 RevisionTask 是从 ReviewIssue 派发的最小任务，不执行真实编辑；执行闭环继续由 Phase 10/11 的 publish/feedback/pressure test 加固。

## 风险

| 风险 | 级别 | 说明 | 后续处理 |
| -- | -- | -- | -- |
| AgentRun project scope 与 AgentContract local-system 归属不同 | P2 | 通过 AgentTask 链接补取解决 UI 可见性，但底层 run 仍可能按 local-system 列表出现。 | Phase 11 做压力测试时检查 project filter 使用体验。 |
| RevisionTask 从 issue 生成后尚未自动执行 editor patch | P2 | Phase 8 只要求可派发和可观察，不承担修订执行。 | Phase 10/11 通过 publish/feedback 和 longform pressure 验证。 |
| UI 仍是最小控制台 | P2 | 已能看到核心 runtime 关系，但还不是完整可编辑 Agent Center。 | Phase 9 扩展 Novel OS editable console。 |

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/agent_scheduler src/novel_forge/api src/novel_forge/schemas` | OK |
| `python3 -m unittest tests/unit/test_agent_scheduler.py tests/unit/test_schemas.py tests/unit/test_product_api_routes.py tests/unit/test_loop_kernel.py tests/unit/test_review_issue.py` | 33 tests OK |
| `npm --prefix web/admin test` | 7 pass, 1 Playwright smoke skipped by existing optional dependency policy |
| `npm --prefix web/admin run build` | OK |

## 当前状态

Phase 8 验收项已完成：AgentRun 状态、输入输出、ContextBundle、ReviewIssue、RevisionTask、成本/provider 字段和失败/队列状态都能从 Agent Center snapshot 或 UI 面板观察；ReviewIssue 可以派发为 RevisionTask + AgentTask + AgentRun + DispatchQueue。
