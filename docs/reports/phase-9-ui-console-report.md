# Phase 9 UI Console Report

日期：2026-07-03

## 完成内容

1. 新增通用可编辑控制台组件：`web/admin/app/features/os/EditableAssetConsolePage.tsx`。
2. 新增 Novel OS 可编辑控制台 routes：
   - `/canon-console`
   - `/character-console`
   - `/arc-console`
   - `/foreshadowing-console`
   - `/review-issues`
   - `/longform-recap`
   - `/loop-runs`
   - `/agent-center`
   - `/publish-gate`
   - `/feedback-console`
3. 更新导航：
   - Agent Center；
   - Canon / Character / Arc / Foreshadowing；
   - Review Issues；
   - Longform Recap；
   - Loop Runs；
   - Publish Gate；
   - Feedback Console。
4. 增加 admin 架构测试，固定新增 route 和控制台组件。
5. `/mkaos` 页面未修改。

## 覆盖矩阵

| 要求 | 当前实现 | 证据 |
| -- | -- | -- |
| Canon 控制台 | 已有 `/canon-console` | `web/admin/app/canon-console/page.tsx` |
| Character 控制台 | 已有 `/character-console` | `web/admin/app/character-console/page.tsx` |
| Arc 控制台 | 已有 `/arc-console` | `web/admin/app/arc-console/page.tsx` |
| Foreshadowing 控制台 | 已有 `/foreshadowing-console` | `web/admin/app/foreshadowing-console/page.tsx` |
| ReviewIssue 控制台 | 已有 `/review-issues` | `web/admin/app/review-issues/page.tsx` |
| Longform Recap 报告页 | 已有 `/longform-recap` | `web/admin/app/longform-recap/page.tsx` |
| LoopRun 监控页 | 已有 `/loop-runs` | `web/admin/app/loop-runs/page.tsx` |
| Agent Center 页 | 已有 `/agent-center` | `web/admin/app/agent-center/page.tsx` |
| Publish Gate 页 | 已有 `/publish-gate` | `web/admin/app/publish-gate/page.tsx` |
| Feedback 页 | 保留 `/feedback`，新增 `/feedback-console` | `web/admin/app/feedback/page.tsx`, `web/admin/app/feedback-console/page.tsx` |
| MKAOS 不回归 | 未改动 MKAOS 页面 | `web/admin/app/features/mkaos/MkaosConsolePage.tsx` |

## 取舍

1. 没有新增后端业务 API；使用现有资产详情/保存接口，避免为 UI 直接绕过 schema。
2. 没有给所有资产类型新增创建功能；只有 Creative Library 已支持的类型可以创建。
3. 没有隐藏原有 `/agent-dispatch`、`/feedback`、`/quality?tab=publishing` 等入口；新增 route 作为 Novel OS 控制台别名和专用视图。

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `npm --prefix web/admin test` | 8 pass, 1 Playwright smoke skipped |
| `npm --prefix web/admin run build` | OK；build 输出包含 44 个 route，其中包括所有新增控制台 |

## 风险

| 风险 | 级别 | 说明 | 后续处理 |
| -- | -- | -- | -- |
| JSON content 编辑门槛较高 | P2 | 这是 Phase 9 最小可编辑控制台，不是最终领域表单。 | P1/P2 可增加专用字段编辑器和校验提示。 |
| Canon/Arc 等非 Creative 类型不能直接创建 | P2 | 避免新增不完整创建 API。 | 后续通过领域服务补 create/update API。 |
| 浏览器 smoke 仍因 Playwright 未安装而跳过 | INFO | 项目已有可选跳过策略。 | 最终阶段可按需安装 Playwright 后运行 smoke。 |
