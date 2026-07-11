# Novel OS 16 项优先问题执行进度

> 更新日期：2026-07-11  
> 当前阶段：Phase 0 — 可信工程基线

| Work Package | 状态 | 已完成 | 测试证据 | 剩余问题 | 下一步 |
|---|---|---|---|---|---|
| WP-00A 基线分类 | completed | 已取得首次全量基线、16项重核验和五层测试证据口径 | Python 779 tests / 7F / 35E / 2S；聚焦Source/Publish/Scheduler 79 tests / 1F / 21E；Web 11 pass / 1 skip；validate 3 unscoped | 无；失败已归入Source Gate、项目隔离、旧运行期望和质量门禁四组 | 执行Task 0.2 |
| WP-00B Source Gate迁移 | completed | 修复workspace readiness Schema；建立可复用的自有来源、Policy、Risk、eligibility和clean sweep fixture | Source/Review 37 pass；Publish/Editor/Analysis 29 pass；Platform/Registry 21 pass | 无；Scheduler仍有1个独立旧状态期望，归入WP-00D | Task 0.4 |
| WP-00C 项目隔离 | completed | Pipeline在创作前创建项目并逐步绑定资产；Registry/Workflow/Lease使用显式system scope；历史3资产经审计修复 | 8个scope/pipeline聚焦测试通过；`make validate`通过 | 无 | Task 0.5 |
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

## WP-00A 完成记录

1. 解决内容：建立当前分支而非历史报告的测试事实基线，并分开确定性、沙箱、浏览器、真实Provider和真实平台证据。
2. 核心模块：仅文档；未修改业务行为。
3. 旧路径：没有删除或兼容业务路径。
4. 协议/模型：没有新增运行协议。
5. 测试：Python全量、Source/Publish/Scheduler聚焦、Web Node、Web TypeScript、compile、Skill drift、workspace validate、diff check。
6. 结果：确定性基线未通过；聚焦套件确认21个error共享Source Gate前置证据缺失，另有1个Scheduler旧状态期望失败。
7. 风险：其他聚焦套件仍需在对应工作包复跑；浏览器E2E未执行。
8. 阶段标准：WP-00A通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.2进入条件。

## WP-00B 完成记录

1. 解决内容：workspace级readiness不再违反Schema；合法production fixture不再因缺stale/retention/eligibility证据被Source Runtime Gate误阻断。
2. 核心模块：`source_intake/guarded_apply_readiness.py`；测试侧新增`source_governance_fixtures.py`。
3. 旧路径：没有增加bypass；未治理知识卡仍被生产Gate拒绝。
4. 协议/模型：workspace聚合报告使用`system:workspace`和`scope_kind=workspace`；项目报告保持真实project scope。
5. 测试：Source/Review、Publish、Agent Editor、Analysis、Publishing Adapter、Registry/Scheduler Integration聚焦套件。
6. 结果：87个聚焦测试通过；Agent Scheduler另有1个非Source Gate状态期望失败，留给WP-00D。
7. 风险：完整Python套件需在后续工作包后重跑；fixture helper只用于测试，不是生产信任捷径。
8. 阶段标准：WP-00B通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.4进入条件。

## WP-00C 完成记录

1. 解决内容：sample pipeline不再事后批量猜测项目归属；系统Registry、Workflow Definition和Scheduler Lease不再保持无归属。
2. 核心模块：`workflows/pipeline.py`、`agent_registry/service.py`、`workflow_nodes/service.py`、`runtime_ledger/service.py`、`api/services/product.py`。
3. 旧路径：保留旧Pipeline兼容入口，但其sample流程现在先立项目再生产；历史system runtime资产由`project_scope_audit(repair=True)`显式修复。
4. 协议/模型：system runtime metadata统一为`project_id=local-system`、`workspace_path=local-system`、`scope_kind=system`。
5. 测试：Agent Registry、legacy system repair、Workflow Definition、Scheduler Lease和sample pipeline双运行。
6. 结果：8个聚焦测试通过；当前`.local/workspace`验证通过，0 unscoped/cross-project issue。
7. 风险：完整套件仍可能暴露其他创建器的scope问题；将在Task 0.6验证。
8. 阶段标准：WP-00C通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.5进入条件。
