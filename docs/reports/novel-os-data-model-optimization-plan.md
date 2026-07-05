# Novel OS Data Model Optimization Plan

审计日期：2026-07-05  
基线 commit：`534d195`  
范围：领域模型、schema、迁移、索引、状态机、审计字段优化计划。  

## P0 数据模型任务

| ID | 任务 | 验收 |
| --- | --- | --- |
| P0-DATA-AGENT-001 | Agent operation input/output schema coverage | 每个注册 operation 有 input/output schema、runtime policy、gate |
| P0-DATA-CONTEXT-001 | Context Bundle 必填字段统一 | context bundle 必有 source ids、budget、selection reason、isolation status |
| P0-DATA-REVIEW-001 | ReviewIssue 作为唯一 blocking issue contract | 发布、审稿、MKAOS gate 均输出/消费 ReviewIssue |
| P0-DATA-CANON-001 | Canon/Character/Foreshadowing/Arc 更新统一 patch contract | 所有更新有 patch id、source、confidence、trace、rollback hint |
| P0-DATA-RELEASE-001 | ReleasePackage 强绑定 gate report 和 unresolved issue query | unresolved blocking issue 时不能生成 accepted release |

## P1 数据模型任务

| ID | 任务 | 验收 |
| --- | --- | --- |
| P1-DATA-SCHEMA-001 | 拆分 `schemas/base.py` 的 required field registry | 按 agent/workflow/content/runtime/eval/publish 分模块，兼容导出 |
| P1-DATA-MKAOS-001 | MKAOS asset type 分离 | knowledge asset、quality signal、lineage、pack 分开校验 |
| P1-DATA-EVAL-001 | EvalCase/EvalResult 结构化 | metric、threshold、provider、sample、regression status 必填 |
| P1-DATA-FEEDBACK-001 | ReaderFeedback backflow task 化 | feedback insight 不直接改 outline/canon，只生成 revision task |
| P1-DATA-STORAGE-001 | 文件/DB shared repository contract | local/Postgres 返回同一 asset envelope 和 error semantics |

## P2 数据模型任务

| ID | 任务 | 验收 |
| --- | --- | --- |
| P2-DATA-INDEX-001 | 百万字长篇索引策略 | chapter/canon/character/foreshadowing/query 有分页和索引 |
| P2-DATA-COMPRESS-001 | 长上下文摘要和冷热分层 | stale context 可压缩，release-critical evidence 不丢 |
| P2-DATA-AUDIT-001 | 全链路 audit event 标准化 | API、Agent、workflow、publish、rollback 可统一查询 |

## 实施策略

1. 先加 characterization tests，固定现有 schema 行为。
2. 拆 validator registry，不改变资产 JSON 外部形态。
3. 对新 operation 强制新 contract，对旧资产提供 compatibility reader。
4. 数据库迁移必须向后兼容 local-first workspace。
5. 所有状态字段必须有明确状态转移和拒绝非法转移的测试。

