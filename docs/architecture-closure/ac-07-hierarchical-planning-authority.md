# AC-07 分层规划 Authority

状态：`PLANNED`  
阶段：Phase 2 / Novel Domain Closure  
前置依赖：AC-04、AC-05、AC-06

## 1. ADR

### 决策

全书规划统一采用：

```text
BookPlan
→ VolumePlan
→ ArcPlan
→ ChapterGroupPlan
→ ChapterPlan
```

每层 Plan 都是不可变 AssetVersion，具有 Scope、Goals、Constraints、Reader Outcomes、Entry State、Expected Exit State、Dependencies、Acceptance Criteria、Effective Range 和 Status。上层通过 Authority Operation 委托下层；下层通过 Outcome 和 Progress Projection 反向汇总。

已 Final Release 的章节形成 `committed_cursor`，普通重规划只能影响未来区间。历史修改必须使用单独的 Retcon/Correction Operation。

### 重规划决策

任何重规划必须产生：

```text
ReplanRequest
PlanDiff
ImpactAnalysis
AffectedAssetVersions
EffectiveRange
AuthorityDecision
NewPlanVersion
```

禁止原地覆盖 active plan。

## 2. 层级职责

| 层级 | 决策范围 |
|---|---|
| Book | 主题、结局、总冲突、卷结构、主角总弧、读者承诺 |
| Volume | 阶段目标、卷内主冲突、状态迁移、卷末高潮 |
| Arc | 冲突升级、信息揭示、人物选择、弧终结果 |
| ChapterGroup | 若干章节奏、爽点分布、小高潮、上下文窗口 |
| Chapter | 场景、目标、冲突、情绪曲线、信息增量、钩子、预期状态变化 |

## 3. 实施范围

- 建立统一 Plan contract 和 type registry；
- 建立 parent/child、effective range 和 progress projection；
- 建立 Planning Authority Operations；
- 建立 rolling planning：只详细规划可控窗口，远期保持低分辨率；
- 建立 plan reservation，避免两个 worker 生成同一下一章；
- 建立 impact traversal，覆盖 Ending、World、Character、Foreshadowing 和 Future ChapterPlan；
- Book Authority 只能读取/委托 Planning Authority，不直接写计划。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/book_authority/`
- `src/novel_forge/modules/chapter_plan/`
- `src/novel_forge/modules/outline/`
- Book Design、Volume/Arc/ChapterGroup 相关 schemas/services
- `docs/design/hierarchical-story-planning-and-production-authority.md`
- `docs/design/book-design-authority-and-longform-closed-loop.md`

### 目标位置

- `src/novel_forge/modules/planning_authority/contracts.py`
- `.../application.py`
- `.../operations.py`
- `.../repositories.py`
- `.../impact.py`
- `.../rolling_window.py`
- `.../progress.py`
- `tests/integration/test_hierarchical_planning_postgres.py`

若当前已有 Planning Authority 实现，必须收敛到唯一模块，不新建平行 Writer。

## 5. 迁移脚本设计

数据库应支持：Plan roots/versions、parent relation、effective ranges、plan dependencies、progress projections、replan requests、diffs、impact results、reservations 和 decisions。

脚本：

```text
scripts/migrations/inventory_plan_assets.py
scripts/migrations/import_hierarchical_plans.py
scripts/migrations/link_plan_parentage.py
scripts/migrations/backfill_effective_ranges.py
scripts/migrations/detect_overlapping_active_plans.py
scripts/migrations/quarantine_orphan_chapter_plans.py
```

重叠 active range、缺失 parent、chapter 已提交但计划仍可变时必须阻塞迁移。

## 6. 实施计划

1. 固定五层 Plan contract。
2. 将现有 Outline/ChapterPlan 映射到统一 AssetVersion。
3. 建立 Planning OperationDefinitions 和 Authority application。
4. 建立 parent/child、reservation、progress 和 effective range。
5. 实现 PlanDiff/ImpactAnalysis/ReplanDecision。
6. 接入 StoryState entry/exit contract。
7. 将 Book Authority 的外部输入改为主动调用 Planning Authority。
8. 完成 3 章和 10 章滚动规划证明。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Contract | 五层 Plan 缺失必填字段 | 拒绝 |
| Parent scope | ChapterPlan 不在 parent range | 拒绝 |
| Reservation | 并发领取下一章 | 仅一个成功 |
| History freeze | 修改 committed chapter plan | 普通 replan 拒绝 |
| Future replan | 第 10 章后生效 | 1–9 章引用不变 |
| Impact | Ending 变化 | 受影响卷/弧/伏笔/未来章可追踪 |
| Rolling window | 只生成未来 N 章细纲 | 远期计划不被伪装成详细章纲 |
| Recovery | replan 中 Worker 崩溃 | Operation/Saga 可恢复 |
| Progress | ChapterOutcome 提交 | group/arc/volume/book projection 更新 |

## 8. Acceptance Gate

```text
hierarchical_plan_contract_stable=true
planning_authority_single_writer=true
committed_history_frozen=true
replan_diff_impact_effective_range_required=true
rolling_planning_verified=true
next_chapter_reservation_verified=true
book_to_planning_delegation_verified=true
l10_plan_progression_verified=true
```

## 9. 风险

- 过度一次性规划：使用滚动窗口和逐层分辨率。
- Plan 与 StoryState 重复：Plan 描述预期，StoryState 描述已发生事实。
- 重规划传播过大：影响分析先分类 blocking/stale/warning，不自动重生成全部资产。