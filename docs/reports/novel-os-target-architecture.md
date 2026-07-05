# Novel OS Target Architecture

审计日期：2026-07-05  
基线 commit：`534d195`  
用途：定义 Novel OS 长期目标分层和 P0 acceptance 闭环。  

## 目标原则

Novel Forge 目标不是“生成一章文字”，而是一个可追踪、可回滚、可评估、可长期运行的 Novel Operating System。所有生产输出必须通过 schema、context、provider、canon、review、release、ledger 和 trace 约束。

## 目标分层

```text
Admin Console / CLI / API
  -> Application Services
  -> Agent Operation Layer
  -> OS Envelope + Runtime Policy
  -> Context Builder + MKAOS + RAG + Canon
  -> Domain Services
  -> Asset Schema + ReviewIssue + Gate Result
  -> Storage Adapters
  -> Local / Postgres / Vector / Object / Graph
```

## 目标链路

```text
Project Goal
  -> Topic Fit
  -> World Bible
  -> Character Cards
  -> Long Outline
  -> Chapter Plan
  -> Context Bundle
  -> Draft Candidate
  -> ReviewIssue Gate
  -> Revision
  -> Canon/Foreshadowing/Arc Update
  -> Longform Recap
  -> Eval
  -> Publish Gate
  -> Release Package
  -> Feedback Backflow
```

每一步必须记录：

- input asset ids；
- output asset ids；
- schema type；
- project/workspace id；
- AgentRun/workflow/task id；
- provider/model/runtime policy；
- prompt/Skill version；
- context bundle id；
- ReviewIssue/gate result；
- trace/cost/latency；
- rollback or revision task when applicable。

## 目标模块边界

| 边界 | 目标 |
| --- | --- |
| API | 只做请求认证、DTO、调用 application service，不持有业务分支 |
| Application Service | 编排一个明确 use case，禁止散落 prompt |
| Agent Operation | 每个 operation 有 contract、input schema、output schema、policy、gate |
| Context Builder | 唯一上下文入口，负责 source isolation、budget、compression、lineage |
| MKAOS | 知识资产 ingestion、selection、quality、lineage 分模块 |
| Canon/Continuity | 统一处理 canon、character state、foreshadowing、arc |
| ReviewIssue | 唯一阻断问题表达，不再用自由文本风险绕过 gate |
| Publish | 对外提供 publish gate/release package/rollback rehearsal facade |
| Eval | 连接 provider routing、quality regression、release hard-stop |
| Storage | 本地文件和数据库后端共享同一 repository/asset contract |

## P0 Acceptance 闭环

一个项目/章节 fixture 必须能证明：

1. workflow run 创建；
2. Agent dispatch 入队、lease、执行、checkpoint；
3. Context Builder 产出 context bundle；
4. provider runtime policy 和 OS Envelope 校验；
5. draft/review/revision 产出 schema-backed assets；
6. ReviewIssue 阻断或放行；
7. Canon/character/foreshadowing/arc 更新；
8. Longform Recap 写回记忆；
9. Eval 记录 provider/quality 结果；
10. Publish Gate 生成 gate report 和 release package；
11. invalidation/resume/rollback 记录可追踪；
12. 所有步骤有 trace/cost/ledger。

## 拆分路线

1. 先修覆盖缺口，不大拆运行链路。
2. 再用 characterization tests 包住大 service。
3. 将大 service 内部按 coordinator、validator、repository、policy、report writer 拆分。
4. 外部 API 稳定后再移动模块路径。
5. 所有迁移必须保留 asset version 和 compatibility reader。

