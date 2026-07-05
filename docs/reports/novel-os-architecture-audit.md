# Novel OS Architecture Audit

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：分层、核心链路、旁路、fallback、长期演进风险。  

## 当前实际分层

```text
web/admin
  -> src/novel_forge/api/routers
  -> src/novel_forge/api/services/product.py
  -> src/novel_forge/modules/*
  -> src/novel_forge/schemas + src/novel_forge/storage
  -> local files / Postgres / vector / object / graph backends
```

Agent 运行面：

```text
agents/runtime.py
  -> modules/agent_scheduler/service.py
  -> modules/agent_runs/service.py
  -> operation registry
  -> modules/context_builder + os_envelope + review_issue + mkaos + audit/evaluation
```

## 分层审计

| 层 | 当前状态 | 证据 | 问题 |
| --- | --- | --- | --- |
| API 层 | 已实现 | `api/app.py`、`api/routers/*` | Product service facade 过大 |
| Application Service 层 | 已实现但边界混合 | `modules/*/service.py` | 多个 service 同时承担 orchestration 和 domain logic |
| Domain 层 | 部分实现 | `schemas/assets.py`、`schemas/base.py`、各 module asset 类型 | 领域对象多为资产 schema，行为模型偏弱 |
| Infrastructure 层 | 已实现 | `storage/*`、provider adapters | fallback 策略需显式化 |
| Persistence 层 | 已实现 | local store、Postgres、object store、vector store | 文件优先可用，迁移/索引策略需继续加强 |
| Agent Orchestration 层 | 已实现第一片 | `agent_runs`、`agent_scheduler`、`loop_kernel` | coverage 和 UI 深度不足 |
| Knowledge Asset 层 | 已实现 | `mkaos`、`mkaos_quality`、`knowledge` | MKAOS service 过大 |
| Workflow / Task 层 | 已实现 | `workflow_nodes`、`task_status`、`pipeline` | 兼容 facade 容易旁路严格 runtime |
| Evaluation 层 | 部分实现 | `evaluation_center`、`runtime_policy` | Eval 未完全成为 release/provider hard-stop |
| UI / Admin Console 层 | 已实现 | `web/admin/app/features/*` | 页面偏大，局部状态复杂 |

## 核心链路统一性

| 链路 | 统一程度 | 证据 | 风险 |
| --- | --- | --- | --- |
| 小说项目创建 | 中 | API/product facade、local workspace | 项目元数据和 workspace path 校验需更硬 |
| 题材选择 | 中 | `modules/topics` | Platform fit 与 Eval 不够强 |
| 世界观生成 | 中 | `worldbuilding` | continuity gate 接入需加强 |
| 人物生成 | 中 | `characters`、`character_state` | ledger 与章节写作前置 gate 不够硬 |
| 大纲生成 | 中 | `outline`、`long_planning` | beat design 已进入 Skill，需 runtime proof |
| 细纲生成 | 中 | `chapter_plan` | ReviewIssue gate 可继续强制 |
| 章节生成 | 中高 | `drafting`、provider runtime、context builder | 仍需检查所有入口无旁路 |
| 章节审稿 | 高 | `review`、`review_issue` | 自由文本 review 入口需收敛 |
| 章节修订 | 中 | `editor`、`revision` | diff/rollback/version 强制性需提高 |
| 长篇复盘 | 中 | `longform_recap`、`longform_stability` | AgentRun 统一不足 |
| Canon 更新 | 中高 | `canon_graph`、`continuity_graph` | patch/confidence/source 强制化需继续 |
| 伏笔追踪 | 中 | `foreshadowing_graph` schema/service | 与 release gate 的阻断关系需强化 |
| 读者反馈 | 中 | `feedback`、`feedback_backflow` | backflow 到 plan/canon 的任务化不足 |
| 发布门禁 | 中高 | `audit.create_publish_gate_report`、`release_package` | publishing module 边界不清 |
| 回滚 | 中 | Agent checkpoint/rollback docs and scheduler code | business rollback rehearsal 不足 |
| Eval | 中 | `evaluation_center` | 未完全接入主链 hard-stop |

## 主要架构风险

1. 过渡 facade 过大：`api/services/product.py` 和 `workflows/pipeline.py` 容易延续多入口。
2. 大 service 过多：MKAOS、workflow_nodes、agent_scheduler 需要以测试保护渐进拆分。
3. Publish/Eval/Longform Recap 的目标 Agent 结构已有，但运行闭环还不够硬。
4. Context Builder、OS Envelope、ReviewIssue 已实现，但仍需对所有 model-producing operation 做 coverage 审计。
5. 文件资产 schema 覆盖广，但领域行为和状态机还可以从 JSON asset 中提炼。

## 本轮已修复

Agent runtime 与 Skill 源目录 drift：所有 root project Skill 已显式映射到 Agent profile，目标 Agent 名称新增 alias，避免默认 Quality Agent fallback。

