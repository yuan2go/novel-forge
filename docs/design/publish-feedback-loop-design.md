# Publish / Feedback Loop Design

日期：2026-07-03

## 范围

Phase 10 将发布门禁、release package 和读者反馈回流接入 Novel OS 工业化主线。目标不是替代既有 Publishing Center，而是让生产发布路径具备可阻断、可追溯、可回写和 source isolation 证明。

## 发布门禁

入口：

- `src/novel_forge/modules/audit/service.py:create_publish_gate_report`
- `POST /product/publishing/gate`

强制项：

- production 环境必须提供 OS Envelope。
- Context Builder 构造 `publish` context bundle。
- source policy 默认禁止 `source_chunk.raw_text`。
- MKAOS high/critical risk 写入 gate。
- active blocking ReviewIssue 写入 gate。
- gate content 写入 `context_bundle_id`、`context_bundle_path`、`mkaos_risk`、`source_isolation`、`os_envelope_id`。

兼容策略：

- dev/sample/test 路径可通过 `environment` 和 `bypass_reason` 显式 bypass。
- 旧 API 请求不带 envelope 时保持非 production 兼容。

## Release Package

入口：

- `src/novel_forge/modules/audit/service.py:create_release_package`
- `POST /product/publishing/release-package`

阻断规则：

- ReviewIssue blocking 继续阻断 release。
- Publish gate blocked 继续阻断 release。
- MKAOS high/critical risk 进入 gate 后阻断 release。

Package 内容：

- chapters / canonical draft reference；
- review report；
- blocking status；
- known risks；
- platform checklist；
- rollback snapshot；
- context bundle reference；
- MKAOS risk summary；
- source isolation proof；
- OS Envelope reference。

Release package 只保存引用、摘要和治理证据，不保存 `source_chunk.raw_text`。

## Feedback Loop

入口：

- `src/novel_forge/modules/feedback/service.py:process_publish_feedback_loop`
- `POST /product/feedback/publish-loop`
- `web/admin/app/features/feedback/ReaderFeedbackPage.tsx`

处理步骤：

1. 读取 project-scoped reader feedback。
2. 生成 ReaderSentimentReport。
3. 生成 FeedbackBackflowPlan。
4. 根据负向反馈/追读风险计算 MKAOS weight delta。
5. 对最近 project-scoped MKAOS usage event 中的 knowledge card 执行权重更新。
6. 写入 FeedbackInsight，保留 feedback paths、release package path、backflow plan、MKAOS weight update 和 revision task proposal。

## 数据边界

- 反馈闭环只消费 `reader_feedback` 资产和 release package 引用。
- MKAOS 权重更新基于 `knowledge_usage_event`，不直接读取 source chunk raw text。
- 发布链路通过 Context Builder 的 source policy 统一禁止 raw source text。
- UI 只展示结果计数和路径，不展示原始 source chunk。

## 后续边界

- Platform feedback ingestion 仍是最小结构化入口，后续可扩展平台指标 schema。
- Feedback clustering 当前为确定性聚类，P1 可接入模型辅助，但必须保持 OS Envelope 和成本记录。
- RevisionTask proposal 已进入反馈回流计划，后续可由 Agent Center 派发执行。
