# Novel OS Agent Audit Report

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：`agents/runtime.py`、`modules/agent_runs/`、`modules/agent_scheduler/`、Agent 相关 Skills、workflow/loop/publish/eval 入口。  

## Agent 总表

| Agent | 代码路径 | 职责 | 输入/上下文 | 输出 | 状态/记忆 | 测试/门禁 | 成熟度 |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| Chief Editor Agent | `agents/runtime.py`、`modules/agent_runs/` | 规划、优先级、验收 | docs、roadmap、workflow state | plans、acceptance、constraints | AgentRun、checkpoint | 单测和调度覆盖部分 | 7 |
| Workflow Agent | `modules/agent_scheduler/`、`modules/workflow_nodes/` | operation registry、queue、retry、dead-letter | workflow run、dispatch queue | run status、recovery instruction | queue lease、checkpoint | scheduler tests、MKAOS coverage tests | 7 |
| Engineering Agent | `agents/runtime.py` | schema/code/docs 维护 | code/docs/tests | code、tests、docs | 无业务记忆 | 本轮新增 Skill map 单测 | 6 |
| Analysis Agent | `modules/analysis/`、`modules/deconstruction/` | 抽象拆解 | cleaned source、profile、rights metadata | analysis report | lineage assets | originality boundary 依赖 MKAOS gate | 6 |
| Knowledge Agent | `modules/mkaos/`、`modules/knowledge/` | 知识资产、规则候选 | analysis、decomposition | knowledge assets | MKAOS pack、lineage | MKAOS quality tests | 7 |
| Material Agent | `modules/materials/`、`modules/creative_assets/` | reusable material | material source | material cards/templates | asset storage | 基础测试 | 6 |
| Context Agent | `modules/context_builder/` | token 预算、source isolation、bundle | project goal、asset pool | context bundle/build plan | context assets | Context Builder proof docs/tests | 8 |
| Topic Agent | `modules/topics/` | topic seed and fit | platform、genre、materials | topic assets | asset storage | 覆盖不足 | 5 |
| Worldbuilding Agent | `modules/worldbuilding/` | world bible、rules | topic、knowledge | world bible | Canon/continuity 可接入 | 覆盖部分 | 6 |
| Character Agent | `modules/characters/` | character cards、relations | topic/world | character assets | character state ledger | 覆盖部分 | 6 |
| Outline Agent | `modules/outline/`、`modules/long_planning/` | long outline、volume outline | topic/world/characters | outline | continuity seeds | 覆盖部分 | 6 |
| Chapter Plan Agent | `modules/chapter_plan/` | scene goals、conflicts、hooks | outline、continuity | chapter plan | task/workflow assets | 覆盖部分 | 6 |
| Draft Agent | `modules/drafting/` | draft candidate | chapter plan、context bundle | draft chapter | model call log/cost ledger | provider hard-stop proof | 6 |
| AI Editor / Revision Agent | `modules/editor/`、`modules/revision/` | controlled revisions | draft、issues | patch、revised draft | versioned assets | 覆盖部分 | 6 |
| Review Agent | `modules/review/`、`modules/review_issue/` | review report、blocking issues | draft、rubric、canon | ReviewIssue、report | ReviewIssue records | ReviewIssue proof docs/tests | 7 |
| Quality Agent | `modules/audit/` | validation/gates | artifacts/schemas | validation/risk/gate | audit log | validation tests | 7 |
| Feedback Agent | `modules/feedback/` | reader signal clustering | reader feedback、metrics | insights/backflow | feedback assets | simulation proof | 6 |
| Publishing Agent | `modules/audit/`、`modules/publishing/` | publish gate、release package | final chapter、package | gate report、plan/log | release assets | publish feedback report | 6 |
| Model Evaluation Agent | `modules/evaluation_center/`、`modules/runtime_policy/` | provider and model evaluation | runs、benchmarks、profiles | eval result/routing recommendation | ledger/eval assets | provider runtime policy tests partial | 6 |
| Continuity Agent | `modules/canon_graph/`、`modules/continuity_graph/` | canon、character、foreshadowing consistency | recap/context/canon | canon patch、graph updates | continuity graph | canon graph proof | 7 |
| Longform Recap Agent | `modules/longform_recap/` | recap and writeback | chapters、review、canon | recap, canon patch, ledger | long memory/continuity | proof docs; runtime profile added this round | 5 |
| Platform Compliance Agent | `modules/platform_strategy/` | platform fit, rhythm, publish adapter | platform profile/content | platform gates/adapters | platform assets | runtime profile added this round | 5 |
| Training Agent | `modules/training/` | exercise generation | knowledge/material | training exercise | asset storage | runtime profile added this round | 4 |

## 深度问题

| 问题 | 证据 | 影响 | 优先级 | 状态 |
| --- | --- | --- | --- | --- |
| 项目 Skill 到 Agent runtime 映射不完整 | `agents/runtime.py` 原 `SKILL_AGENT_MAP` 缺少多个 root Skill，未知 Skill 会退到 Quality Agent | Agent 选择和权限边界不稳定 | P0 | 本轮已修复 |
| 目标 Agent 名称和代码 profile 名称不一致 | 用户目标结构包含 `Editor-in-Chief`、`Chapter Writer`、`Canon Guardian` 等，代码使用 `chief_editor`、`draft`、`continuity` | 文档/操作入口容易漂移 | P0 | 本轮新增 alias |
| Agent 运行构件成熟但覆盖不均 | `agent_runs`、`agent_scheduler` 已存在，部分业务 module 未强制走 AgentExecutionContext | 仍可能产生旁路链路 | P1 | 待继续 |
| Longform Recap 有 writeback 但顶层 Agent 化不足 | `modules/longform_recap/service.py` 直接协调 context/loop/writeback | 复盘 Agent 的状态、成本、重试记录不够统一 | P1 | 待继续 |
| Publishing domain 边界分散 | release package/gate 在 `modules/audit/service.py`，plan/log 在 `modules/publishing/service.py` | 发布 Agent 职责难以从路径直观看出 | P1 | 待继续 |
| Eval 与 release/provider routing 闭环不够硬 | `modules/evaluation_center/` 和 `modules/runtime_policy/` 独立存在 | Eval 结果不一定阻断发布或 provider routing | P1 | 待继续 |

## 本轮代码修复

- 在 `src/novel_forge/agents/runtime.py` 新增 `platform_strategy`、`longform_recap`、`training` runtime profile。
- 新增 `AGENT_PROFILE_ALIASES`，使目标 Agent 名称可解析到实际 runtime profile。
- 扩展 `SKILL_AGENT_MAP` 到所有 root `skills/*/SKILL.md`。
- 添加 `tests/unit/test_agent_runtime_profiles.py`，防止 Skill 新增后再次默认落入 Quality Agent。

## 判断

Agent Center 已有真实第一片基础设施，不应被描述为“完全没有 Agent”。但它距离完整自治中心仍缺 UI 深度、operation coverage、业务 rollback、Eval hard-stop、跨链路 observability 和端到端 acceptance 压测。

