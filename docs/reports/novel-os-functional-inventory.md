# Novel OS Functional Inventory

审计日期：2026-07-05  
基线 commit：`8733acf`
范围：Novel OS 业务域能力、代码证据、实现成熟度。  

## 功能清单

| 业务域 | 当前状态 | 关键证据 | 主要缺口 |
| --- | --- | --- | --- |
| 素材 | 已实现 | `modules/materials/`、`modules/creative_assets/`、`data/materials/`、`skills/material-curation/` | 素材到 MKAOS 权重和生产使用证据需更统一 |
| 拆解 | 已实现 | `modules/deconstruction/`、`modules/analysis/`、`modules/mkaos_ingestion/` | 拆解报告到知识资产的自动闭环仍偏服务集中 |
| 题材 | 部分实现 | `modules/topics/`、`skills/topic-development/` | 题材评估、市场反馈和 platform strategy 的联动需加强 |
| 世界观 | 已实现 | `modules/worldbuilding/`、`skills/worldbuilding/` | 世界规则冲突检测应进一步接入 continuity graph |
| 人物 | 已实现 | `modules/characters/`、`modules/character_state/`、`skills/character-design/` | 人物状态 ledger 与章节写作 gate 仍需更强制 |
| 大纲 | 已实现 | `modules/outline/`、`modules/long_planning/`、`skills/long-outline/` | 大纲和 narrative beat design 的 runtime 使用需持续验证 |
| 细纲 | 已实现 | `modules/chapter_plan/`、`skills/chapter-outline/` | 细纲到正文前的 ReviewIssue gate 应强制化 |
| 正文 | 已实现 | `modules/drafting/`、`modules/editor/`、`skills/prose-generation/` | model provider 边界已建；本轮补 provider hard-stop + success evidence fixture，仍需真实外部 provider 压测 |
| 审稿 | 已实现 | `modules/review/`、`modules/review_issue/`、`skills/quality-review/` | ReviewIssue 标准已存在，需进一步减少自由文本 review 旁路 |
| 反馈 | 已实现 | `modules/feedback/`、`modules/feedback_backflow/`、`skills/reader-feedback/` | 读者反馈到 outline/canon 调整需更多 end-to-end 测试 |
| 训练题 | 已实现第一片 | `modules/training/`、`skills/training-exercise/`、`agent_scheduler` | Training Agent 已有 scheduler operation；后续需接入更多知识/评估输入 |
| 可复用模板 | 已实现 | `data/templates/`、`modules/mkaos/`、`schemas/assets.py` | 模板版本和适用范围可更结构化 |
| 多学科知识资产 | 已实现 | `modules/mkaos/`、`modules/mkaos_quality/`、`skills/mkaos-knowledge-asset-os/` | 服务过大，需拆分 ingestion、selection、quality、lineage |
| RAG / 记忆库 | 已实现 | `storage/rag_context.py`、`pgvector_store.py`、`qdrant_index.py`、`modules/long_memory/` | fallback 和异常处理需显式 fail-open/fail-closed 策略 |
| Context Builder | 已实现 | `modules/context_builder/service.py`、`skills/context-builder-source-isolation/` | 性能和去重策略需持续量化 |
| OS Envelope | 已实现 | `modules/os_envelope/service.py` | 应扩大所有 model-producing operation 的强制覆盖 |
| Agent Center | 已实现第一生产片 | `agents/runtime.py`、`modules/agent_runs/`、`modules/agent_scheduler/` | Longform/Platform/Training 已补 operation coverage；UI 深度仍未达到完整自治中心 |
| Eval Center | 部分实现 | `modules/evaluation_center/` | Eval/provider 可阻断发布；后续需更多 benchmark/routing 正向 fixture |
| 长篇复盘 Agent | 已实现第一片 | `modules/longform_recap/`、`modules/longform_stability/`、`agent_scheduler` | 已有 operation coverage；后续补更深 trace/cost/UI |
| 发布 / 平台适配 / 回滚 | 部分实现 | `modules/audit/service.py`、`modules/publishing/`、`modules/platform_strategy/`、`skills/publish-release-gate-os/` | Release package 已自检 gate evidence；rollback rehearsal 需自动化 |
| UI 控制台 | 已实现 | `web/admin/app/features/*` | 页面可操作性已覆盖多中心，但大页面和状态可视化需优化 |
| 数据统计和观测 | 部分实现 | `modules/runtime_ledger/`、`modules/audit_log/`、`modules/clickhouse_analytics/` | token/cost/latency 可记录，但跨链路 dashboard 仍需加强 |

## 当前功能判断

Novel OS 已经具备 P0 垂直切片的主要构件：项目资产、上下文、模型 provider 边界、AgentRun、调度、ReviewIssue、Canon/continuity、MKAOS、发布 gate 和 UI 观察面。当前最大不足是这些构件在所有入口上还没有完全同一化，一些兼容路径仍可以绕过更严格的 runtime contract。

## 优先补齐项

1. 将所有项目源 Skill 映射到明确 Agent runtime profile，避免默认 Quality Agent fallback。本轮已修复并加单测。
2. 将 Publish Gate 从 audit service 的实现细节继续迁出到 publishing domain。
3. 给 Context Builder、RAG、ReviewIssue、Canon 更新链路补更多集成测试和 pressure fixture。
4. 对 MKAOS、workflow_nodes、agent_scheduler、product API facade 做渐进拆分。
5. 将 release package 正向 production-ready fixture 纳入 acceptance。
