# Novel OS Distance To Operating System

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：Novel Forge 距离真正 Novel Operating System 的工程级差距。  

## 评分

| 维度 | 当前评分 | 目标评分 | 差距 | 关键证据 | 优先级 |
| --- | ---: | ---: | ---: | --- | --- |
| 架构完整度 | 7 | 9 | 2 | OS Envelope/Context/AgentRun 已有，大 service/facade 仍重 | P1 |
| 创作链路完整度 | 7 | 9 | 2 | topic/world/character/outline/chapter/review/publish 均有模块 | P1 |
| 长篇稳定性 | 6 | 9 | 3 | longform_recap/stability 已有，AgentRun 统一不足 | P1 |
| 多学科知识资产使用深度 | 7 | 9 | 2 | MKAOS 强，但 service 过大、生产权重需更多证据 | P1 |
| Agent 自治能力 | 6 | 9 | 3 | scheduler/AgentRun 存在，operation coverage/UI 深度不足 | P0/P1 |
| Context Builder 成熟度 | 8 | 9 | 1 | source isolation/budget 已有，需性能和全覆盖 | P1 |
| Canon / 伏笔 / 人物一致性 | 7 | 9 | 2 | canon_graph/continuity_graph/character_state 已有 | P1 |
| 审稿质量 | 7 | 9 | 2 | ReviewIssue gate 已有，需消除自由文本旁路 | P1 |
| Eval 能力 | 5 | 9 | 4 | evaluation_center 存在但 hard-stop 闭环不足 | P1 |
| UI 可操作性 | 6 | 9 | 3 | 管理台多中心存在，交互深度和分页可优化 | P2 |
| 数据模型成熟度 | 6 | 9 | 3 | schema 广但集中，领域状态机不均 | P1 |
| 性能可靠性 | 6 | 9 | 3 | scheduler/retry 有基础，文件扫描/上下文膨胀需量化 | P1 |
| 可测试性 | 6 | 9 | 3 | tests 丰富但大 service 和核心闭环压力不足 | P1 |
| 可观测性 | 6 | 9 | 3 | ledger/trace 存在，dashboard 和跨链路查询不足 | P2 |
| 可维护性 | 5 | 9 | 4 | 多个 3000-7000 行 service | P1 |
| 可扩展性 | 6 | 9 | 3 | 多后端 adapter 存在，contract 需统一 | P1 |
| 平台发布能力 | 6 | 9 | 3 | publish gate/release package 有，rollback rehearsal 不足 | P1 |
| 读者反馈闭环 | 6 | 9 | 3 | feedback/backflow 有，任务化和 gate 化不足 | P1 |
| 工程生产级程度 | 6 | 9 | 3 | 第一生产片成熟，但完整 autonomic OS 尚未完成 | P0/P1 |

## 当前完成度

估算完成度：64%。

理由：核心构件已经存在且可运行，但完整 Novel Operating System 需要更强的统一入口、Agent operation 覆盖、Eval hard-stop、longform production pressure、UI 操作深度和可维护拆分。

## 最关键 10 个阻塞点

1. Agent operation coverage 不完整。
2. Eval 未成为 provider/release 的强阻断。
3. Longform Recap Agent 与 AgentRun/trace/cost 统一不足。
4. Publish Gate 和 Publishing 模块边界分散。
5. Product API facade 过大。
6. MKAOS service 过大。
7. Workflow node service 过大。
8. Context/RAG 在长篇规模下性能证据不足。
9. 数据模型状态机不均。
10. UI 控制台对 trace/cost/retry/rollback 的操作深度不足。

## 最值得优先实现的 20 个优化项

1. 完成 root Skill -> Agent profile 显式映射。本轮已完成。
2. Longform Recap 注册为 Agent operation。
3. Platform Compliance 注册为 Agent operation。
4. Training 注册为 Agent operation。
5. Publishing module 暴露 gate facade。
6. Eval result 接入 runtime policy。
7. Release package 查询 unresolved ReviewIssue。
8. Context Builder 增加 cache/selection digest。
9. Postgres/local fallback 改为环境策略。
10. MKAOS service characterization tests。
11. Product service 拆 use case facade。
12. Workflow node 拆 state transition。
13. Agent scheduler 拆 registry/lease/runner。
14. Canon/character/foreshadowing patch contract 加单测。
15. Feedback backflow 改 revision task first。
16. UI Agent Dispatch detail 增 trace/cost。
17. Eval Center 增 release readiness view。
18. Longform 12-chapter pressure fixture 固化。
19. schema required fields 按域拆分。
20. docs 报告索引归并，减少阶段文档漂移。

## 路线图

P0：Agent runtime/operation 覆盖、OS Envelope/Context/ReviewIssue hard-stop。  
P1：大 service 拆分、数据模型状态机、Eval/Publish/Longform 闭环。  
P2：性能缓存、UI 深化、观测 dashboard、平台 adapter 和 rollback rehearsal。

