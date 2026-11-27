---
name: multi-scale-pacing
description: Use when analyzing or reviewing pacing across scene, chapter, rolling chapter windows, chapter groups, arcs, volumes, or books while separating deterministic measures from semantic quality judgments.
---

# Multi-scale Pacing

## Novel OS Runtime Contract

- 本 Skill 定义节奏分析方法；正式结果必须由 `pacing.analyze` / `pacing.aggregate` 生成 schema-backed `PacingObservation`、`PacingWindowAggregate` 或 `PacingDiagnosis`。
- deterministic measurement 只能读取结构化 Accepted state/change；semantic quality judgment 必须通过 Provider Runtime，记录 evidence spans、qualification、model call、cost ledger 和 trace。
- 所有窗口必须以 accepted Chapter boundary 截断，按 `project_id` 隔离，禁止未来章节泄漏。
- Blocking diagnosis 必须进入 ReviewIssue / Gate；Skill 文本不能直接改 ChapterPlan、Draft 或 Canon。

## 适用场景

- 分析 Scene、Chapter、短窗、长窗、Chapter Group、Arc、Volume、Book 尺度的节奏。
- 检查局部高潮与长线推进是否错位、promise / foreshadow debt 是否积累、状态变化是否过弱或过密。
- 在 Review、Revision、Re-review、Longform Recap 或 Replan 中形成可追溯节奏诊断。

## 输入要求

- `project_id`、chapter boundary、window kind、chapter / group / arc / volume / book id。
- accepted chapter observations、structured state changes、promise / foreshadow lifecycle 和 arc progress。
- semantic 指标所需的 qualified provider evidence；缺失时标记 `NOT_OBSERVED`。

## 操作流程

1. 选择尺度并声明窗口成员和 inclusive as-of boundary。
2. 从结构化变化计算可重放指标：open promises、promise debt、foreshadow debt、state-change magnitude 和显式 arc progress。
3. 将 event/conflict/information/setup/payoff/reward density、emotional intensity/variance、dialogue/action/reflection/exposition ratio、hook/cliffhanger strength 路由到 semantic observation，除非上游已有正式结构化测量。
4. 为每项 semantic observation 保留 evidence span、confidence、provider qualification；无证据不填猜测值。
5. 聚合 Chapter、短/长滚动 Chapter、Chapter Group、Arc、Volume、Book 窗口，并检查未来泄漏与跨项目污染。
6. 生成 diagnosis、ReviewIssue 和 revision actions，不直接修改生产资产。

## 输出格式

```markdown
# Multi-scale Pacing Report

## Scope
- project / as-of chapter:
- scale / members:

## Deterministic Measurements
- metric / value / state evidence:

## Semantic Observations
- metric / value / evidence spans / confidence / qualification:

## Window Aggregate
- open promises / promise debt / foreshadow debt:
- state change / arc progress:

## Diagnosis
- issues:
- revision actions:
- gate:
```

## 质量标准

- 每个指标必须声明 `DETERMINISTIC` 或 `SEMANTIC`，不能混用证据等级。
- 聚合必须可列出窗口成员，且不包含 as-of chapter 之后的数据。
- 多尺度 diagnosis 必须指出局部与长线的具体冲突，而不是只给“节奏快/慢”。
- 缺少 qualified semantic evidence 时必须降级结论，不能由 deterministic 数值冒充质量判断。

## 禁止事项

- 禁止通过关键词、英文正则、标点或字数阈值直接判断节奏质量。
- 禁止把单章观察外推为 Arc / Volume / Book 证明。
- 禁止读取未来章节、未接受资产或跨项目 observation。
- 禁止创建第二套 Workflow、Scheduler、Provider Runtime 或状态库。

## 与其他模块的关系

- 上游：Quality Commercial、HookAnalysis、Accepted Canon changes、Chapter Boundary、Longform Recap。
- 下游：ReviewIssue、RevisionPlan、Re-review、Replan、Publish Gate。
- 关联 Skill：`quality-review`、`narrative-beat-design`、`long-outline`、`canon-continuity-graph`。
