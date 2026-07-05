---
name: canon-continuity-graph
description: Use when designing, reviewing, or debugging Canon Graph, continuity facts, character/world state, foreshadowing, invalidation, conflict resolution, rollback evidence, or continuity gates across outline, chapter, draft, revision, recap, publish, and feedback flows.
---

# Canon Continuity Graph

## 适用场景

- 建立或审计 Canon Graph、continuity fact、world rule、character state、arc state、foreshadowing 和 payoff。
- 检查 outline、chapter plan、draft、revision、recap、publish 或 feedback 是否破坏正典。
- 设计 invalidation、impact report、rollback evidence 和 conflict resolution。

## 输入要求

- `project_id`、target asset、flow、canon graph snapshot、continuity facts 和 revision intent。
- CharacterCard、WorldBible、Outline、ChapterPlan、DraftChapter、ReviewIssue、Recap、PublishGateReport。
- evidence refs、trace_id、prior accepted version、candidate version 和 rollback target。

## Novel OS Runtime Contract

- 被接受的正典事实必须有 asset id、version、source flow、trace_id 和 gate status。
- 任何修改 accepted canon 的动作必须产生 impact report、invalidation scope 和 rollback evidence。
- high / critical canon conflict 必须转成 blocking ReviewIssue 或 human_review gate。
- 不能通过 recap、feedback、revision 或 publish flow 静默改写人物状态、世界规则或伏笔承诺。

## 操作流程

1. 读取目标资产和当前 canon graph snapshot。
2. 抽取候选事实：人物状态、关系、资源、世界规则、时间线、伏笔、承诺和禁用项。
3. 对比 accepted canon，标记 MATCH、NEW、UPDATE、CONFLICT、DEPRECATE、NEEDS_DECISION。
4. 为 UPDATE / CONFLICT 生成 impact report、affected assets、review issue 和 rollback instruction。
5. 计算 continuity gate：continue、revise、block、human_review。
6. 输出 canon continuity report，不直接覆盖 accepted canon。

## 输出格式

```markdown
# Canon Continuity Report

## Scope
- target:
- canon snapshot:
- candidate version:

## Fact Changes
- new:
- updated:
- conflicts:
- deprecated:

## Impact
- affected chapters:
- affected arcs:
- invalidation:
- rollback:

## Gate
- result:
- review issues:
- human decisions:
```

## 质量标准

- 每条事实变化必须可追溯到输入资产和版本。
- 冲突必须说明破坏了哪个已接受事实、影响哪些下游资产。
- rollback instruction 必须足够让后续 Agent 恢复旧状态或创建新版本。

## 禁止事项

- 禁止静默修改 accepted canon。
- 禁止用“作者想改”跳过 impact report。
- 禁止让反馈或发布文案反向覆盖正文正典。
- 禁止把参考作品设定作为 canon fact。

## 与其他模块的关系

- 上游：WorldBible、CharacterCard、Outline、ChapterPlan、DraftChapter、Recap、FeedbackInsight。
- 下游：Context Builder、ReviewIssue Gate、RevisionTask、Publish Gate、Loop Kernel。
- 关联 Skill：`context-builder-source-isolation`、`review-issue-gate`、`agent-loop-governance`。
