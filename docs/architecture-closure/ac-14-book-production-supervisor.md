# AC-14 Book Production Supervisor

状态：`PLANNED`  
阶段：Phase 4 / Autonomous Book Runtime Closure  
前置依赖：AC-05 至 AC-13

## 1. ADR

### 背景

当前 Book Authority 已具备持久化 Book Root、章节委托、Outcome reconciliation、StoryState/Canon snapshot 引用、cursor advance、pause/resume/cancel 和 follow-up scheduling 等重要基础，但仍主要协调由调用方提供的 Book/Chapter 输入。要形成全书自治，不能继续让 API、脚本或人工逐章提供 ChapterPlan 和 Context，也不能让 Book Authority 直接生成内容或修改其他领域状态。

### 决策

建立 Book Production Supervisor，作为一本书生产生命周期的 Root Saga 协调者。Supervisor 只负责状态机、委托、等待、汇总、策略决策和恢复；具体设计、规划、章节、长篇状态、质量和发布由各自 Authority 完成。

Supervisor 禁止直接：

- 调用模型；
- 写 Draft/Plan/Canon/StoryState；
- 计算 Judge 分数；
- 绕过 Gate 发布；
- 使用 LocalStorage 决定 Cursor。

## 2. 状态机

```text
CREATED
→ DESIGNING
→ DESIGN_REVIEW
→ PLANNING
→ READY
→ PRODUCING
→ RECAP_PENDING
→ REPLANNING
→ PRODUCING
→ VOLUME_CLOSING
→ COMPLETION_REVIEW
→ COMPLETED
```

异常状态：

```text
PAUSED
BLOCKED
RECOVERING
CANCEL_REQUESTED
CANCELLED
FAILED_RECOVERABLE
FAILED_TERMINAL
```

所有状态转换必须由 Operation/Saga step、Authority evidence 和 transition guard 驱动，不允许直接更新状态字段跳转。

## 3. Book Cursor

Cursor 至少引用：

```text
book_id
active_volume_version
active_arc_version
active_chapter_group_version
next_chapter_number
reserved_chapter
committed_chapter
active_plan_versions
canon_snapshot_version
story_state_snapshot_version
last_chapter_outcome
last_recap_version
pending_replan_request
quality_trend_checkpoint
cost_checkpoint
```

Cursor 是 projection/coordination state，不替代各领域 Authority 的正式资产。

## 4. Supervisor 主循环

```text
Check Book Policy and Budget
→ Ensure approved BookDesign
→ Ensure active hierarchical plans
→ Reserve next chapter scope
→ Request/resolve ChapterPlan
→ Admit Chapter Root Operation
→ Reconcile Chapter completion
→ Require Final Release evidence
→ Consume ChapterOutcome
→ Wait for Canon/StoryState commit
→ Advance cursor
→ Trigger Reader Outcome / Recap by policy
→ Evaluate deviation/replan request
→ Continue / Pause / Replan / Close Volume / Complete Book
```

主循环必须是事件/队列驱动的持久化 Saga，不在一个 Worker 调用栈中循环整本书。

## 5. 代码位置

### 当前重点

- `src/novel_forge/modules/book_authority/production.py`
- `src/novel_forge/modules/book_authority/`
- `src/novel_forge/modules/book_followup_authority/`
- `src/novel_forge/modules/chapter_authority/`
- Planning、Longform、Quality Authority modules
- worker scheduler/recovery modules

### 目标收敛

- `src/novel_forge/modules/book_supervisor/contracts.py`
- `.../application.py`
- `.../state_machine.py`
- `.../cursor.py`
- `.../delegation.py`
- `.../reconciliation.py`
- `.../policies.py`
- `.../completion.py`
- `src/novel_forge/workers/book_supervisor.py`
- `tests/integration/test_book_supervisor_postgres.py`

若现有 Book Authority 可自然扩展，应在其内部实现 Supervisor，不建立平行 Book root writer。

## 6. 迁移脚本设计

数据库需支持 Book production roots、state transitions、cursor versions、chapter reservations/delegations、follow-up checkpoints、replan links、budget/cost checkpoints 和 completion evidence。

脚本：

```text
scripts/migrations/inventory_book_production_state.py
scripts/migrations/import_book_root_operations.py
scripts/migrations/backfill_book_cursors.py
scripts/migrations/link_chapter_delegations.py
scripts/migrations/reconcile_committed_chapters.py
scripts/migrations/quarantine_inconsistent_book_progress.py
```

若正文存在但缺少 Final Release/Outcome/State Snapshot，不得直接推进 committed cursor，必须进入 reconciliation 或人工确认。

## 7. 实施计划

1. 固定 Book state machine、Cursor 和 transition guards。
2. 将当前 Book Authority 的委托能力接入 Planning/Chapter/Longform/Quality Authority。
3. 实现 next scope reservation 和 child Operation tracking。
4. 实现事件驱动 reconciliation、deadline、pause/resume/cancel。
5. 接入 Reader Outcome、Recap、Deviation 和 ReplanDecision。
6. 实现 Volume close 与 Book completion Gate。
7. 建立 Book Supervisor Worker 和健康投影。
8. 完成 L3、L10、L30 以及中途重启/失败注入证明。

## 8. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| State guards | 无 approved design 进入 producing | 拒绝 |
| Reservation | 两个 supervisor tick | 仅一个章节 reservation |
| Delegation | Chapter child admitted | root/child refs 完整 |
| Reconciliation | child 成功但 callback 丢失 | query 后推进一次 |
| Cursor | 缺 StoryState commit | 不前进 |
| Pause/resume | 章节间暂停 | 不再 admit 新章，恢复后继续 |
| Cancel | child 正在执行 | 传播 cancel policy，保留 late result |
| Replan | deviation 触发 | future plan 更新，历史不变 |
| Budget | book cost 超限 | BLOCKED/PAUSED |
| Restart | worker/DB 重启 | 从 PostgreSQL 恢复 |
| L10 | 连续十章 | 无人工逐章输入、状态一致 |
| L30 | 完整 Arc | recap/replan/close evidence 完整 |

## 9. Acceptance Gate

```text
book_supervisor_root_saga_authoritative=true
book_state_machine_guarded=true
book_cursor_versioned=true
planning_chapter_longform_delegation_verified=true
next_chapter_reservation_verified=true
pause_resume_cancel_recovery_verified=true
l10_autonomous_book_loop_verified=true
l30_arc_loop_started_or_verified=true
```

## 10. 风险

- Supervisor 变成巨型业务服务：只协调，不吸收领域逻辑。
- 自动循环失控：设置 chapter/window/budget/deadline/human approval policy。
- Replan 频繁震荡：使用 hysteresis、minimum evidence 和 cooldown。
- Cursor 与真实资产不一致：每次推进通过 transition guard 核验具体 version refs。