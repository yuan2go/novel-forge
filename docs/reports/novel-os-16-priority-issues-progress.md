# Novel OS 16 项优先问题执行进度

> 更新日期：2026-07-11  
> 当前阶段：Phase 0 — 可信工程基线

| Work Package | 状态 | 已完成 | 测试证据 | 剩余问题 | 下一步 |
|---|---|---|---|---|---|
| WP-00A 基线分类 | in-progress | 已取得首次全量基线和16项重核验 | Python 779 tests / 7F / 35E / 2S；Web 11 pass / 1 skip；validate 3 unscoped | 写入测试分层并完成聚焦失败分类 | 执行Task 0.1 |
| WP-00B Source Gate迁移 | not-started | 已确认大量失败共享3条blocking rows | Source/Publish/Scheduler失败堆栈 | readiness空project Schema、合法fixture治理证据 | Task 0.2-0.3 |
| WP-00C 项目隔离 | not-started | 已确认当前workspace和sample pipeline均有隔离失败 | `make validate`；`test_pipeline` | system scope、跨项目lineage、历史资产处理 | Task 0.4 |
| WP-00D 质量门禁语义 | not-started | 已确认agency rule阻断旧12章验收 | 12章、acceptance、loop、sequence失败 | 合格成功fixture和明确阻断期望 | Task 0.5 |
| WP-00E Phase 0关闭 | not-started | 轻量lint/type/skills/diff已通过 | 尚无两次完整绿色 | 全量回归与文档同步 | Task 0.6 |
| WP-01..15 | not-started | 已完成依赖排序和重基线 | `novel-os-priority-issues-rebaseline.md` | 等待Phase 0绿色 | 按依赖逐阶段细化 |

## 当前基线

```text
Python: FAILED — 779 tests, 7 failures, 35 errors, 2 skipped
Workspace validate: FAILED — 3 unscoped runtime assets
Python compile: PASSED
Web TypeScript: PASSED
Web Node tests: PASSED — 11 passed, 1 Playwright skipped
Skill drift: PASSED
git diff --check: PASSED
```

## Phase 0完成报告

尚未完成。只有当两次确定性全量验证结果一致且为绿色时才填写完成结论。

