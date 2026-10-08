---
name: canon-continuity-graph
description: Use when designing, reviewing, or debugging Canon Graph, as-of continuity, character/world state, deterministic narrative rules, foreshadowing, invalidation, rollback evidence, or continuity gates across long-form production flows.
---

# Canon Continuity Graph

## 适用场景

- 建立或审计 Canon Graph、continuity fact、world rule、character state、arc state、foreshadowing 和 payoff。
- 检查 outline、chapter plan、draft、revision、recap、publish 或 feedback 是否破坏正典。
- 设计 invalidation、impact report、rollback evidence 和 conflict resolution。
- 区分可由已接受结构化状态确定性判断的矛盾，与需要理解动机、OOC 或情绪合理性的 semantic judgment。

## 输入要求

- `project_id`、target asset、flow、canon graph snapshot、continuity facts 和 revision intent。
- CharacterCard、WorldBible、Outline、ChapterPlan、DraftChapter、ReviewIssue、Recap、PublishGateReport。
- evidence refs、trace_id、prior accepted version、candidate version 和 rollback target。
- 需要跨章节判断时，输入必须包含 `TemporalQueryService` 的 as-of 结果和 chapter boundary；不得让 Skill 自行查询数据库。

## Novel OS Runtime Contract

- 被接受的正典事实必须有 asset id、version、source flow、trace_id 和 gate status。
- 任何修改 accepted canon 的动作必须产生 impact report、invalidation scope 和 rollback evidence。
- high / critical canon conflict 必须转成 blocking ReviewIssue 或 human_review gate。
- 不能通过 recap、feedback、revision 或 publish flow 静默改写人物状态、世界规则或伏笔承诺。
- 时态读取必须来自 PostgreSQL Accepted Canon projection；Legacy LocalStorage Canon Query 不能作为生产证据。
- 确定性发现必须进入 `canon.validate` / `continuity.validate` 的结构化报告；高严重度发现进入 ReviewIssue / Gate，不由 Skill 文本直接激活或回滚 Canon。

## Deterministic / Semantic Boundary

以下规则仅在 Authority 已有明确字段和 lineage 时交给 deterministic validator：

- timeline ordering、future-state leakage、invalid state transition；
- character identity、dead-character usage、knowledge boundary、relationship transition；
- promise / foreshadow lifecycle ordering；
- resource balance、world-rule、power-state transition、graph integrity。

人物动机、OOC、情绪可信度、关系变化是否“自然”等需要语义理解的问题交给 provider judge，并保留 evidence spans、qualification、model call 与 cost ledger。Authority 数据不足时输出 `INSUFFICIENT_STATE` 或未实现规则，不得使用关键词、正则或常识 heuristic 假装确定性验证。

## 操作流程

1. 读取目标资产、chapter boundary、accepted canon snapshot 和必要的 as-of temporal query 结果。
2. 抽取候选结构化事实：人物状态、身份、关系、资源、知识、力量、世界规则、时间线、plot thread、伏笔和承诺。
3. 先运行 deterministic rules；每条 finding 记录 rule、当前/前序 evidence、chapter、severity 和 missing-state 状态。
4. 只把动机、OOC、情绪合理性等剩余问题路由到 semantic judge。
5. 对比 accepted canon，标记 MATCH、NEW、UPDATE、CONFLICT、DEPRECATE、NEEDS_DECISION。
6. 为 UPDATE / CONFLICT 生成 impact report、affected assets、ReviewIssue 和 rollback instruction。
7. 计算 continuity gate：continue、revise、block、human_review。
8. 输出 canon continuity report，不直接覆盖 accepted canon。

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

## Deterministic Findings
- rule:
- as-of chapter:
- evidence refs:
- missing state:

## Semantic Findings
- judge qualification:
- evidence spans:

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
- deterministic finding 必须可由结构化 accepted state 重放；不得依赖 LLM 或字面模式。
- as-of 查询不得返回目标章节之后的事实，supersession、rollback、missing state 和 project isolation 必须显式。
- 冲突必须说明破坏了哪个已接受事实、影响哪些下游资产。
- rollback instruction 必须足够让后续 Agent 恢复旧状态或创建新版本。

## 禁止事项

- 禁止静默修改 accepted canon。
- 禁止用“作者想改”跳过 impact report。
- 禁止让反馈或发布文案反向覆盖正文正典。
- 禁止把参考作品设定作为 canon fact。
- 禁止把 `SKILL.md` 当作状态查询器、validator implementation 或 Canon Authority。
- 禁止用 semantic judge 重判可确定性计算的 lifecycle、balance、identity 或 ordering 规则。

## 与其他模块的关系

- 上游：WorldBible、CharacterCard、Outline、ChapterPlan、DraftChapter、Recap、FeedbackInsight、`temporal.query`。
- 下游：Context Builder、ReviewIssue Gate、RevisionTask、Publish Gate、Command Kernel。
- 关联 Skill：`longform-temporal-query`、`context-builder-source-isolation`、`review-issue-gate`、`agent-loop-governance`。
