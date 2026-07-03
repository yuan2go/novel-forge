# Novel OS UI Console Design

日期：2026-07-03

## 定位

Phase 9 将 Novel OS UI 从分散功能页推进为本地个人小说工厂控制台。目标不是 SaaS 化，也不是登录/会员/协作系统，而是让长篇治理资产可以被本地操作者查看、编辑、追踪和派发。

## 控制台范围

| 页面 | Route | 资产/能力 |
| -- | -- | -- |
| Canon Console | `/canon-console` | `canon_database`, `canon_patch`, `canon_graph_snapshot`, `continuity_bible`, `chapter_state`, `fact_ledger`, `world_bible`, `power_scale_rule` |
| Character Console | `/character-console` | `character_card`, `character_state_ledger` |
| Arc Console | `/arc-console` | `arc_plan`, `long_form_macro_plan`, `chapter_state` |
| Foreshadowing Console | `/foreshadowing-console` | `foreshadowing_thread`, `foreshadowing_graph` |
| ReviewIssue Console | `/review-issues` | `review_issue`, `review_report`, `revision_task`, `revision_plan` |
| Longform Recap Reports | `/longform-recap` | `longform_recap_report`, recap writeback assets |
| LoopRun Monitor | `/loop-runs` | `loop_run`, `loop_step`, `loop_checkpoint`, `loop_report` |
| Agent Center | `/agent-center` | Reuses Agent Center runtime page |
| Publish Gate Console | `/publish-gate` | `publish_gate_report`, `release_package`, `publishing_plan`, `publishing_log` |
| Feedback Console | `/feedback-console` | Reuses reader feedback page |
| MKAOS | `/mkaos` | Existing MKAOS console, unchanged |

## 实现策略

1. 复用 `EditableAssetConsolePage` 作为多页面资产编辑壳。
2. 页面通过现有资产 API 读取项目资产：
   - `GET /product/projects/{project_id}/assets`
   - `GET /assets`
   - `GET /product/assets/detail`
3. 保存走现有 schema-backed content update：
   - `PATCH /product/assets/content`
4. 支持 Creative Library 类型的最小创建：
   - `POST /product/creative-assets`
5. 不新增登录、计费、团队、邀请或远端协作概念。

## 设计取舍

1. Canon/Arc/ReviewIssue/Loop/Publish 等控制台优先提供查看、编辑和跳转，不发明不完整创建 API。
2. Character/Foreshadowing 复用 Creative Library 创建能力，因为已有 schema 和默认内容。
3. Agent Center 使用 `/agent-center` 作为新入口，同时保留 `/agent-dispatch` 兼容旧导航。
4. Feedback 保留 `/feedback`，新增 `/feedback-console` 作为 Novel OS 控制台入口。

## 验收

1. 所有新 route 在 Next.js build 中可见。
2. `npm --prefix web/admin test` 覆盖 route 文件和导航 key。
3. `npm --prefix web/admin run build` 通过 TypeScript 和静态页面生成。
4. `/mkaos` 未修改，不回归。
