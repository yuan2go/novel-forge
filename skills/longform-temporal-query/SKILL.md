---
name: longform-temporal-query
description: Use when specifying or reviewing chapter-as-of queries for accepted character, knowledge, relationship, world, power, plot-thread, foreshadow, promise, or change state without leaking future chapters.
---

# Long-form Temporal Query

## Novel OS Runtime Contract

- 本 Skill 只定义查询语义和审查方法；正式读取必须调用 PostgreSQL `TemporalQueryService` / `temporal.query`，不能在 Skill 中实现状态存储或查询。
- 生产数据只来自 accepted Chapter boundary 下 eligible、clear、`ACTIVE` / `SUPERSEDED` 历史 `AssetVersion` 及其 supersession / rollback lineage；`RETIRED` / `DELETED` 不可见。
- 查询输出必须保留 `project_id`、as-of chapter、boundary semantics、source asset/version、trace 和 missing-state 状态。
- Legacy LocalStorage Canon Query 不得作为 Production 实现或证据。

## 适用场景

- 为 ChapterPlan、Context Builder、Draft、Review、Revision、Canon 或 Replan 获取某章当时可知的状态。
- 审查未来信息泄漏、旧关系被新关系覆盖、知识取得时点、rollback/rebuild 和跨项目隔离。
- 设计 `character_state_at`、`character_knows_at`、`relationship_at`、`world_state_at`、`power_state_at`、`plot_thread_at`、`foreshadow_state_at`、`pending_promises_at`、`changes_between` 的调用契约。

## 输入要求

- `project_id`、query kind、as-of chapter 或 `(chapter_from, chapter_to]`。
- 对象 id：character、fact、relationship target 或 thread id；不适用时不得伪造。
- 调用目的、下游资产、accepted-only 要求和 trace context。

## 操作流程

1. 选择最窄查询，不用整本最新快照替代 chapter-as-of state。
2. 固定边界：`*_at(chapter)` 包含目标章；`changes_between` 为 `(from, to]`。
3. 要求 accepted-only、same-project、active eligible clear versions，并解析 supersession / rollback。
4. 检查返回证据的 chapter 不大于 as-of chapter；任何未来记录都视为阻断缺陷。
5. 用 `NOT_FOUND` 和 `missing_reason` 区分缺失状态与空集合，不把 missing state 推断为 false fact。
6. 将结果以 schema-backed query result 交给 Context Builder、validator 或 ReviewIssue，不直接修改 Canon。

## 输出格式

```markdown
# Temporal Query Contract

## Request
- project:
- query:
- as-of / range:
- entity:

## Semantics
- inclusive boundary:
- accepted only:
- supersession / rollback:
- missing-state behavior:

## Result Evidence
- source asset versions:
- effective chapters:
- trace:
- future leakage check:
```

## 质量标准

- 同一输入和 Authority state 必须得到可重放结果。
- Chapter 30 获取的事实在 Chapter 20 查询中不可见；Chapter 40 的关系变化不能覆盖 Chapter 35 的旧关系。
- 每个 SQL / projection 路径必须显式过滤 `project_id`。
- 任何状态结论必须携带来源版本和 effective chapter。

## 禁止事项

- 禁止查询“当前最新”后让 LLM 猜测历史状态。
- 禁止返回未来章节信息、跨项目资产或未接受候选。
- 禁止用 Legacy LocalStorage、全文关键词或 provider 常识替代 PostgreSQL temporal projection。
- 禁止把查询结果当作 Canon mutation authorization。

## 与其他模块的关系

- 上游：Book / Chapter Authority、Accepted Canon、State Event、Snapshot、Projection、Chapter Boundary。
- 下游：Context Builder、`canon.validate`、`continuity.validate`、ReviewIssue、Replan、Publish Gate。
- 关联 Skill：`canon-continuity-graph`、`context-builder-source-isolation`、`quality-review`。
