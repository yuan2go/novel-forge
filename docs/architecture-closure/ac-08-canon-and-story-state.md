# AC-08 Canon 与 StoryState

状态：`PLANNED`  
阶段：Phase 2 / Novel Domain Closure  
前置依赖：AC-05、AC-06、AC-07

## 1. ADR

### 背景

长篇系统不能只保存章节正文和一个不断增长的 Canon JSON。稳定事实、动态状态、章节结果、计划预期和读者感受具有不同语义。混在同一对象中会导致冲突难以定位、状态无法重放、人工修正覆盖历史。

### 决策

明确分离：

- Canon：已确认且相对稳定的世界事实、身份、规则、历史和重要事件；
- StoryState：当前随章节变化的人物、关系、位置、能力、物品、冲突、谜题、伏笔、读者承诺、弧进度和信息披露状态；
- ChapterOutcome：已接受章节产生的结构化事实增量；
- Plan：未来预期，不属于已发生事实。

状态推进必须使用版本化、确定性 Reducer：

```text
Previous StoryState Snapshot
+ Accepted ChapterOutcome
+ Approved Canon Changes
+ Reducer Version
= New StoryState Snapshot
```

Agent、Reviewer 和模型只能提出 Proposal；Longform Authority 才能提交 Canon 与 StoryState。

## 2. 核心模型

### Canon Change

至少包含 subject、predicate、object/value、validity range、evidence span、source chapter、confidence type、conflict policy 和 approval status。

### ChapterOutcome

至少包括：

- events；
- character decisions；
- state changes；
- relationship changes；
- conflict/arc progress；
- canon proposals；
- foreshadowing changes；
- promise progress；
- knowledge disclosure；
- unresolved issues；
- expected reader effect。

### StoryState Components

```text
CharacterState
RelationshipState
World/LocationState
InventoryState
PowerState
ConflictState
MysteryState
ForeshadowingState
ReaderPromiseState
ArcState
KnowledgeDisclosureState
EmotionalState
```

组件可分表或分投影，但必须属于同一 Snapshot boundary。

### Correction

人工修正必须创建 `ManualStateCorrection` Operation，经过 impact analysis 和 Authority Decision，再通过 correction event 重放。禁止直接编辑 Snapshot。

## 3. 实施范围

- 统一 Canon fact/change/snapshot 模型；
- 统一 ChapterOutcome schema；
- 建立 StoryState reducer registry 和 reducer version；
- 建立增量 event + 周期性完整 Snapshot；
- 建立 replay checksum、rebuild 和 divergence report；
- 建立冲突、人工修正和 retcon 流程；
- Context Builder 只读取已提交 Snapshot；
- Book Cursor 引用当前 Canon/StoryState Snapshot。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/canon_graph/`
- `src/novel_forge/modules/longform_stability/`
- `src/novel_forge/modules/book_followup_authority/`
- `src/novel_forge/modules/book_authority/`
- Chapter Authority Canon extraction/proposal/approval handlers
- Foreshadowing、Reader Promise、Character Pressure、Chapter Economy modules

### 目标位置

- `src/novel_forge/modules/longform_authority/contracts.py`
- `.../chapter_outcome.py`
- `.../canon.py`
- `.../story_state.py`
- `.../reducers/`
- `.../replay.py`
- `.../corrections.py`
- `.../projections.py`
- `tests/integration/test_story_state_replay_postgres.py`

不得创建第二套 Canon writer；现有 Canon Graph 2.0 应作为检查/投影或被收敛为 Authority 内部能力。

## 5. 迁移脚本设计

数据库需支持：Canon facts/changes/snapshots、ChapterOutcome versions、StoryState events/snapshots、reducer versions、replay checkpoints、conflicts、manual corrections。

脚本：

```text
scripts/migrations/inventory_canon_and_state_assets.py
scripts/migrations/convert_legacy_canon_snapshots.py
scripts/migrations/extract_story_state_events.py
scripts/migrations/rebuild_story_state_snapshots.py
scripts/migrations/verify_story_state_checksums.py
scripts/migrations/quarantine_state_divergence.py
```

无法从历史数据可靠还原 event sequence 时，允许导入为 `BASELINE_SNAPSHOT`，但必须记录来源和不可重放区间。

## 6. 实施计划

1. 固定 ChapterOutcome 与 StoryState component contract。
2. 将现有 Canon extraction/approval 输出映射到统一 Canon Change。
3. 建立 reducer registry、version 和 deterministic pure functions。
4. 实现 snapshot commit、replay、checksum 和 divergence report。
5. 接入 Chapter Final Release → Outcome → Canon → State Reduce 链。
6. 接入 Context Builder 与 Book Cursor。
7. 实现 Manual Correction/Retcon。
8. 完成 L3/L10 状态重放和故障恢复证明。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Reducer determinism | 相同输入重复执行 | checksum 一致 |
| Replay | 从 baseline + outcomes 重建 | 与当前 Snapshot 一致 |
| Conflict | 相互矛盾 Canon changes | fail closed，生成 conflict |
| Unapproved canon | Proposal 未批准 | 不进入正式 Snapshot |
| Outcome idempotency | 同 ChapterOutcome 重放 | 不重复应用 |
| Ordering | 跳过前一章 Outcome | 拒绝或等待缺口 |
| Correction | 人工修改状态 | 创建新 event/version，历史保留 |
| Context | 下一章构建 | 只读取 committed Snapshot |
| DB restart | reduce 中断 | 可恢复且不重复状态变化 |
| Long chain | 10/30 章 replay | 无 divergence，增长受控 |

## 8. Acceptance Gate

```text
canon_story_state_separated=true
chapter_outcome_contract_stable=true
story_state_reducer_versioned=true
story_state_replay_verified=true
canon_conflicts_fail_closed=true
manual_correction_governed=true
context_reads_committed_state_only=true
l10_state_continuity_verified=true
```

## 9. 风险

- Reducer 变更导致历史结果变化：保留 reducer version，迁移通过显式 rebuild Operation。
- Snapshot 体积增长：事件增量 + 周期快照 + component projection。
- 模型抽取错误污染 Canon：Proposal、evidence span、approval 和 conflict gate 必须分离。
- 动态状态过度细化：只保留会影响计划、上下文、质量或连续性的状态。