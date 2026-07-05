# Novel OS Performance Reliability Audit

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：Context Builder、RAG、Agent 调度、数据库/文件、UI、token、超时、取消、重试、观测。  

## 总体判断

当前系统有可靠性基础：Agent scheduler 支持 queue leasing、retry、dead-letter；AgentRun 有 checkpoint/gate/budget/metric；Context Builder 有 budget/source isolation；runtime ledger 可记录 model/cost。性能风险主要来自文件资产规模增长、大 service 内重复扫描、上下文膨胀、UI 大页面和 fallback 静默。

## 审计表

| 维度 | 当前状态 | 证据 | 风险 | 优先级 |
| --- | --- | --- | --- | --- |
| 上下文构建性能 | 中 | `modules/context_builder/service.py` | 长篇项目中重复选择/压缩可能增加延迟 | P1 |
| RAG 检索性能 | 中 | `storage/rag_context.py`、`pgvector_store.py`、`qdrant_index.py` | 后端差异和 fallback 语义需统一 | P1 |
| 上下文膨胀 | 中 | ContextBundle 有 budget，但长篇资产多 | token 成本上升，关键证据被挤出 | P1 |
| Agent 调度性能 | 中高 | `agent_scheduler` queue leasing/retry/dead-letter | service 过大，复杂错误难隔离 | P1 |
| 数据库查询性能 | 中 | Postgres/vector adapters 存在 | 索引和查询计划需随规模验证 | P2 |
| UI 加载性能 | 中 | Web feature 页面多，部分 TSX 超 500 行 | 页面状态和表格加载可变慢 | P2 |
| 文件读写性能 | 中 | local-first asset store | 大量 JSON 扫描需索引/cache | P1 |
| 大文档处理 | 中 | MKAOS ingestion/decomposition | chunking/lineage 与质量 gate 复杂 | P1 |
| 批量任务 | 中 | scheduler/workers | 幂等性和 recovery 需更多测试 | P1 |
| token 使用效率 | 中 | Context Builder/runtime ledger | 需 dashboard 和 budget regression | P1 |
| 模型超时 | 部分 | runtime policy/provider adapters | 超时/cancel 策略需统一暴露 | P1 |
| 取消任务 | 部分 | task status/scheduler 概念存在 | UI/API cancel 可操作性不足 | P2 |
| 重试策略 | 中高 | scheduler retry/dead-letter | 需按 operation 类型配置 | P1 |
| 幂等性 | 中 | asset ids/checkpoints | 写操作重复执行的覆盖测试不足 | P1 |
| 并发安全 | 中 | queue leasing | local file 并发写仍需锁/atomic write 检查 | P1 |
| 任务恢复 | 中高 | checkpoint、dead-letter、rollback docs | business rollback rehearsal 不足 | P1 |
| 错误隔离 | 中 | broad exceptions 存在 | 静默 fallback 可能掩盖严重问题 | P1 |
| 日志和追踪 | 中高 | trace/model call/cost ledger | dashboard 和跨链路查询不足 | P2 |

## 低风险高收益优化

1. 给 Context Builder selection 增加 deterministic cache key 和 reviewed source digest。
2. 给 local asset list 增量索引，避免大 workspace 全量扫描。
3. 将 Postgres fallback 改为 policy-driven：development 可 fail-open，production fail-closed。
4. 给 Agent operation 增加 idempotency key 测试。
5. 将 longform recap、publish gate、eval 的 expensive checks 拆成可复用 query。
6. UI 大表格使用分页和 server filtering。

## 本轮执行

本轮先修可靠性基础中的 runtime drift：`SKILL_AGENT_MAP` 覆盖所有 root Skills，避免调度或 Skill 选择进入错误 Agent profile。

