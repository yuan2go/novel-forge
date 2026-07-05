# Novel OS Agent Optimization Plan

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：Agent runtime、operation registry、调度、上下文、门禁、Eval、发布闭环。  

## 目标结构

目标 Agent 分组：

| 目标 Agent | 当前承载 profile/module | 优化方向 |
| --- | --- | --- |
| Editor-in-Chief | `chief_editor` | 统一规划、验收、路线图和 release decision |
| Outline Agent | `outline` | 接入 narrative beat design 和 continuity seed |
| Detailed Outline Agent | `chapter_plan` | 保持 chapter plan schema 和 ReviewIssue gate |
| Chapter Writer Agent | `draft` | 强制 Context Builder、provider policy、OS Envelope |
| Reviewer Agent | `review` | 标准化 ReviewIssue 输出 |
| Revision Agent | `ai_editor` | diff/rollback/version 必填 |
| Canon Guardian Agent | `continuity` | Canon/Character/Foreshadowing/Arc 合并一致性 gate |
| Foreshadowing Agent | `continuity` | 作为 continuity profile 的 operation 子类型 |
| Character Consistency Agent | `continuity` | 作为 continuity profile 的 operation 子类型 |
| Worldbuilding Agent | `worldbuilding` | 世界规则冲突写入 continuity graph |
| Multidisciplinary Knowledge Agent | `knowledge` | MKAOS pack、lineage、quality gate |
| Longform Recap Agent | `longform_recap` | 复盘、writeback、revision task 全部进入 AgentRun |
| Reader Feedback Agent | `feedback` | feedback insight 到 plan/canon 的变更任务化 |
| Platform Compliance Agent | `platform_strategy` | platform gates、adapter、release risk |
| Eval Agent | `model_evaluation` | provider routing、benchmark、release gate hard-stop |
| Release Gate Agent | `publishing` | publish gate、release package、rollback rehearsal |

## P0 计划

| ID | 任务 | 验收 | 状态 |
| --- | --- | --- | --- |
| P0-AGENT-RUNTIME-001 | 修复 Skill 到 Agent runtime drift | 所有 root Skill 都有显式 Agent map；目标 Agent alias 可解析 | 已完成 |
| P0-AGENT-RUNTIME-002 | operation registry 覆盖 longform recap、platform compliance、training | operation coverage test 通过，无默认 fallback | 待做 |
| P0-AGENT-CONTEXT-001 | model-producing operation 强制 OS Envelope + Context Builder | 缺字段时 fail-closed，测试覆盖 draft/review/publish | 待做 |
| P0-AGENT-REVIEW-001 | 所有审稿/发布阻断统一 ReviewIssue | blocking issue 可阻断 release package | 部分已实现，待压测 |
| P0-AGENT-CANON-001 | Canon/Character/Foreshadowing/Arc 统一 continuity gate | 修改 canon 必有 patch、confidence、source、trace | 待做 |

## P1 计划

| ID | 任务 | 验收 |
| --- | --- | --- |
| P1-AGENT-SCHED-001 | 拆分 `agent_scheduler/service.py` 为 registry、lease、runner、recovery | 外部 API 不变，单元测试分层 |
| P1-AGENT-LONGFORM-001 | 将 `longform_recap` 包装为 AgentOperation | AgentRun/cost/trace/checkpoint 可见 |
| P1-AGENT-PUBLISH-001 | 给 publishing module 增加 gate facade，委托 audit implementation | 部分完成：已新增 facade 和单测；待迁移其他调用方 |
| P1-AGENT-EVAL-001 | Eval result 接入 provider runtime policy 和 release gate | 未达标 provider 不能进生产主链 |
| P1-AGENT-UI-001 | Agent Center 页面拆分并增加 operation detail/trace/cost 视图 | UI 可追踪每个 Agent 输出 |

## P2 计划

| ID | 任务 | 验收 |
| --- | --- | --- |
| P2-AGENT-OBS-001 | token/cost/latency dashboard | Web 控制台可按 project/workflow/agent 查看 |
| P2-AGENT-LOAD-001 | 长篇 12 章以上 pressure fixture 纳入 CI 可选任务 | 不阻塞快速单测，保留手动 acceptance |
| P2-AGENT-HUMAN-001 | human review checkpoint UX | 可在 UI 中接受/驳回 Agent 输出 |

## 执行规则

- 不新增平行 Agent framework。
- 所有 Agent operation 先走现有 `AgentRun`、`AgentOperationRegistry`、`OS Envelope`、`Context Builder`。
- 不把 fallback 当主路径。离线/mock 只能在测试或明确 provider policy 中存在。
- 每个新增 Agent 能力至少配一个 schema/contract 单测和一个失败门禁测试。
