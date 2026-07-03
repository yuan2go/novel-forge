# Phase 10 Publish / Feedback Report

日期：2026-07-03

## 完成内容

1. 发布门禁接入 OS Envelope、Context Builder、ReviewIssue、MKAOS risk 和 source isolation。
2. Release package 增加 known risks、review report、rollback snapshot、MKAOS risk、ContextBundle 和 OS Envelope 引用。
3. Production 发布路径缺 OS Envelope 时 fail closed；dev/sample/test 仍可显式兼容。
4. MKAOS high/critical risk 能阻断 release package。
5. 新增 publish feedback loop service/API，将 reader feedback 转成 sentiment report、feedback backflow plan、FeedbackInsight，并回写 MKAOS selection weight。
6. 反馈中心 UI 新增“发布反馈闭环”操作入口。
7. 增加专项回归测试：发布门禁 envelope/context/source isolation、production fail-closed、MKAOS risk 阻断 release、feedback -> MKAOS weight 回写。

## 证据

| 要求 | 当前实现 | 证据 |
| -- | -- | -- |
| Publish Gate 接入 OS Envelope | production 缺 envelope 抛错；非 production 写入 envelope metadata | `src/novel_forge/modules/audit/service.py:create_publish_gate_report` |
| Publish Gate 接入 Context Builder | 构造 `flow="publish"` ContextBundle 并写入 gate content/reference | `src/novel_forge/modules/audit/service.py:create_publish_gate_report` |
| Publish Gate 接入 MKAOS risk | `list_risk_knowledge` 汇总 high/critical risk，写入 `mkaos_risk_clear` gate | `src/novel_forge/modules/audit/service.py:_mkaos_risk_summary` |
| Release package 可被 MKAOS risk 阻断 | gate blocked 且含 MKAOS blocker 时 raise `ValueError` | `src/novel_forge/modules/audit/service.py:create_release_package` |
| Release package 不泄露 raw source | 写入 source isolation proof 和引用，不写 `source_chunk.raw_text` | `tests/unit/test_publish_feedback_loop.py:test_release_package_blocks_mkaos_risk_and_excludes_raw_text` |
| Feedback 闭环回写 MKAOS | sentiment/backflow 后调用 `apply_weight_update` | `src/novel_forge/modules/feedback/service.py:process_publish_feedback_loop` |
| API 暴露闭环入口 | `POST /product/feedback/publish-loop` | `src/novel_forge/api/routers/feedback.py` |
| UI 可操作闭环 | 反馈中心增加 release package path 和闭环回写按钮 | `web/admin/app/features/feedback/ReaderFeedbackPage.tsx` |

## 取舍

1. 没有新增发布专用数据表；沿用现有 asset storage 和 ReviewIssue/MKAOS/ContextBundle 引用，避免 Phase 10 引入大迁移。
2. Platform feedback 仍按 reader feedback 兼容入口处理；完整平台指标 schema 放入 P1。
3. Feedback -> MKAOS weight delta 使用确定性规则，优先提供可测试闭环；后续可在 OS Envelope 下引入模型辅助分析。
4. Release package 阻断选择 fail closed，而不是记录 warning 后继续打包。

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/modules/audit src/novel_forge/modules/feedback src/novel_forge/api tests/unit/test_publish_feedback_loop.py` | OK |
| `python3 -m unittest tests/unit/test_publish_feedback_loop.py` | 4 tests OK，用时约 7.7s |
| `python3 -m unittest tests/unit/test_publishing_center.py tests/unit/test_review_issue.py tests/unit/test_mkaos.py tests/unit/test_product_api_routes.py` | 10 tests OK |
| `python3 -m unittest tests/unit/test_longform_stability.py tests/unit/test_loop_kernel.py` | 12 tests OK |
| `npm --prefix web/admin test` | 8 pass, 1 Playwright smoke skipped |
| `npm --prefix web/admin run build` | OK，44 routes generated |

## 风险

| 风险 | 级别 | 说明 | 后续处理 |
| -- | -- | -- | -- |
| 平台反馈 schema 仍较薄 | P2 | 当前可处理 reader/editor/platform 类反馈，但平台指标尚未形成强 schema。 | P1/P2 建立 platform feedback metric schema。 |
| Feedback 聚类为确定性启发式 | P2 | 适合本地可测闭环，不等同于最终运营智能。 | 在 Provider hard-stop 下增加可选模型分析。 |
| Release package 仍以 JSON asset 为主 | P2 | 已具备阻断和 rollback snapshot，但不是完整发布编排系统。 | 后续接 Publishing Agent 与平台 adapter。 |
