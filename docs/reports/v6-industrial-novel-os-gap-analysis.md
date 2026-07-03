# Novel OS v6 Industrial Gap Analysis

日期：2026-07-03

## 最大遗留差距

| 编号 | 差距 | 级别 | 当前状态 | 下一步 |
| -- | -- | -- | -- | -- |
| G-01 | Canon / Character / Arc / Foreshadowing 深度推理仍不完整 | P1 | 有结构化 adapter、资产和 ReviewIssue，但不是完整语义推理 | 建立统一 Canon Graph query/check service |
| G-02 | Agent Center operation coverage 不足 | P1 | 可观察和派发最小闭环已完成 | 把更多 production operations 注册成 AgentTask |
| G-03 | Loop Kernel 尚未成为所有工作流默认执行器 | P1 | chapter_review/outline_revision/longform_recap 可跑 | 将 review-revise-publish 主链迁移到 LoopRun |
| G-04 | UI 仍偏 JSON asset 编辑 | P1 | 路由齐全，最小可编辑 | 增加领域表单、批量操作、血缘/阻断视图 |
| G-05 | Provider hard-stop 已证明，但自动 fallback 未治理化 | P1 | fail-closed/no silent fallback | 增加显式 fallback policy、human gate 和成本预测 |
| G-06 | Publish 外部平台 adapter 仍是受限边界 | P2 | local/manual/webhook 边界存在 | 建立平台 schema、回执和 rollback protocol |
| G-07 | Feedback platform metrics schema 较薄 | P2 | reader feedback/backflow/MKAOS weight 可回写 | 增加 retention、comment、platform review 强 schema |
| G-08 | 12 章压力是确定性 fixture | P2 | 工业链路 proof 完成 | 增加 opt-in 50/100 章和真实 provider 压力 |
| G-09 | SQL/JSON 双写和 migration 覆盖仍需长期收敛 | P2 | JSON asset 是主证明路径，部分 migration 已有 | 建立 migration acceptance matrix |
| G-10 | 生产可观测性仍可增强 | P2 | trace/cost/gate/report 已有 | 增加 dashboards、SLA alerts、failure drill |

## 风险判断

当前没有阻止继续进入 P1/P2 的 P0 blocker。必须避免：

- 绕过 Context Builder 重新让 Agent 拼 prompt；
- 让 provider hard-stop 后 silent retry/fallback；
- 让 raw source text 进入 generation / recap / publish；
- 把 Longform Recap 当摘要器使用而不写回治理资产；
- 把 UI route 齐全误判为完整领域产品体验。

## 工业化评分拆解

| 领域 | 分数 | 说明 |
| -- | -- | -- |
| 可测试性 | 91 | 297 tests 全量通过，新增 12 章压力和 provider proof |
| 可阻断 | 88 | ReviewIssue / publish gate / release package 已 fail closed |
| 可回写 | 84 | Recap、Feedback、MKAOS weight 已回写，平台反馈仍薄 |
| 可复盘 | 86 | Longform Recap 和 reports 已成体系 |
| 可观测 | 82 | Agent Center、trace、cost、gate 可见，operation coverage 仍不足 |
| 可扩展 | 85 | Envelope/Context/Loop 基座已成形，legacy surface 需继续迁移 |

综合：**86/100**。
