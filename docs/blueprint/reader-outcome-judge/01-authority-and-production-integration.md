# Reader Outcome Judge：Authority 与生产链接入

> 返回：[Reader Outcome Judge 总览](README.md)  
> 更新日期：2026-07-22  
> 文档状态：`ACTIVE TARGET DESIGN`

## 1. PostgreSQL Authority 原则

ROJ 必须复用当前生产权威：

- Command 先 Admission；
- 输入 AssetVersion 冻结；
- Operation、Saga 和 Attempt 持久化；
- 模型调用通过 ProductionExecutionGateway；
- Provider / Process 运行通过 ExternalEffect 和 Receipt 记录；
- Lease、Fencing、Retry、Cancel 和 Reconcile 可恢复；
- 输出 Append-only；
- Prediction、Calibration、Decision 和 Human Override 可审计；
- Outbox 发布事件；
- LocalStorage 不得成为生产权威。

ROJ 不建立第二套 Task、Attempt、Provider Receipt、Approval 或 Budget 系统。

## 2. 数据分类

### 2.1 AssetVersion

适合保存：

- `reader_segment_profile`；
- `narrative_feature_snapshot`；
- `reader_outcome_prediction_bundle`；
- `pairwise_judge_report`；
- `quality_decision_report`；
- `calibration_profile`；
- `judge_drift_report`；
- `human_preference_batch_report`；
- `experiment_analysis_report`。

### 2.2 Typed Append-only Table

适合保存高频事件：

- `reader_exposure`；
- `reader_outcome_event`；
- `experiment_assignment`；
- `human_preference_vote`。

### 2.3 可重建聚合

- `reader_outcome_aggregate`；
- `experiment_metric_snapshot`；
- `calibration_dataset_snapshot`。

## 3. 不可变性

- 已产生 Prediction 不允许修改；
- 新模型或 Prompt 生成新的 Prediction；
- Calibration Promote 不改变历史 Raw Score；
- Human Override 不删除原自动 Decision；
- Experiment Assignment 不原地改写；
- 行为修正使用 Correction Event；
- 已发布 ChapterVersion 与 Exposure 永久绑定。

## 4. Chapter Authority 集成

### 4.1 第一阶段：Shadow Sidecar

第一阶段不得修改十八节点 Chapter Completion Contract。

目标链：

```text
Chapter Quality / Final Version Available
→ reader_outcome.root
→ Feature Extraction
→ Segment Resolution
→ Raw Outcome Score / Pairwise
→ OOD / Disagreement
→ Advisory Decision
→ Eval and Projection
```

约束：

- 不阻断 Publish Gate；
- 不改变 Chapter Saga 成功状态；
- 不自动触发 Revision；
- 不写 Canon；
- 不修改 Book Production Cursor；
- 使用独立 Shadow Budget；
- 输出明确 `production_decision_allowed=false`。

### 4.2 后续接入阶梯

```text
M1 Shadow Only
→ M2 Advisory + Human Review
→ M3 Low-risk Policy Input
→ M4 Controlled Experiment
→ M5 Bounded Production Decision
```

只有 M3 以上且 Calibration Profile 有效时，ROJ 才能成为 Publish Gate 的非硬门禁输入。

Originality、Safety、Canon、Causal Coherence 和 Platform Compliance 永远保留独立硬门禁。

## 5. Shadow Input Contract

必须冻结：

```text
chapter_version_id
chapter_plan_version_id
quality_aggregate_version_id
quality_group_report_version_ids
canon_snapshot_version_id
story_state_version_id
context_manifest_id
book_plan_version_id
volume_plan_version_id
chapter_group_plan_version_id
arc_state_refs
reader_segment_version_ids
platform_profile_version_id
judge_profile_version_id
calibration_profile_version_id | null
route_snapshot_id
```

Judge 请求禁止包含：

- 当前版本真实 Outcome；
- 当前实验赢家；
- 生成模型身份；
- 人工最终答案；
- 测试标签；
- 高风险参考原文。

## 6. Shadow Output Contract

主输出：

```text
asset_type = reader_outcome_prediction_bundle
output_key = chapter.reader_outcome.shadow
```

辅助输出：

- NarrativeFeatureSnapshot；
- Segment-specific Raw Score / Prediction；
- Pairwise Report，若有变体；
- Judge Disagreement Report；
- OOD Report；
- Prediction Cost Report；
- Advisory Decision Report。

未校准时：

```yaml
raw_scores:
  completion_score: 0.82
  next_chapter_score: 0.74
ordinal_band: HIGH
calibrated_probabilities: null
calibration_status: UNCALIBRATED
production_decision_allowed: false
```

已行为校准时：

```yaml
raw_scores:
  completion_score: 0.82
calibrated_probabilities:
  completion_probability: 0.79
calibration_status: BEHAVIOR_CALIBRATED
production_decision_allowed: true
```

## 7. Decision Policy

第一阶段输出 Advisory：

```yaml
quality_decision_report:
  mode: SHADOW
  decision: ACCEPT_ADVISORY | REVISE_ADVISORY | HUMAN_REVIEW | INSUFFICIENT_EVIDENCE
  blocking_reasons: []
  warnings: []
  reader_segment_ids: []
  prediction_ids: []
  calibration_profile_ids: []
  disagreement_summary: {}
  ood_summary: {}
  required_next_operation: null
  policy_version: roj-shadow-policy-v1
  production_decision_allowed: false
```

后续决策枚举：

```text
ACCEPT
REVISE
EXPERIMENT
HUMAN_REVIEW
REJECT
PAUSE_BOOK_PROPOSAL
INSUFFICIENT_EVIDENCE
```

阈值必须版本化，不得硬编码在 Handler。

## 8. Chapter Type Policy

至少区分：

- opening；
- normal；
- transition；
- reveal；
- payoff；
- climax；
- aftermath；
- paywall；
- volume_ending；
- book_ending。

开篇、付费点、高潮、卷末和结局提高 Human Review 或 Experiment 门槛。

## 9. Book Authority 集成

Book Authority 不重新审核全文，只消费：

- 最近 3 / 5 章 Raw Score 趋势；
- 最近 10 章已校准结果，若存在；
- 质量问题复发率；
- Reader Promise / Payoff；
- Segment 差异；
- OOD 比例；
- Judge Drift；
- Human Override 频率；
- 真实 Exposure / Outcome 聚合。

书级节点：

```text
book.reader_outcome.recap.light
book.reader_outcome.recap.formal
book.reader_outcome.recap.volume
book.reader_outcome.plan_adjustment.propose
```

第一阶段这些节点只生成 Evidence 和 Proposal，不直接 Pause Book。

后续自动暂停条件必须生成 `book_pause_proposal`，由 Book Policy 决定是否自动批准。

## 10. Operation Catalog

M0/M1：

```text
judge.feature.extract
judge.segment.resolve
judge.outcome.score
judge.pairwise.compare
judge.adversarial.review
judge.arbitration.resolve
judge.decision.evaluate.shadow
```

M2：

```text
human.preference.batch.create
human.preference.assignment.create
human.preference.vote.record
human.preference.batch.close
judge.human_anchor.evaluate
```

M3：

```text
reader.exposure.record
reader.outcome.record
reader.outcome.aggregate
reader.outcome.window.close
judge.calibration.dataset.freeze
judge.calibration.run
judge.calibration.evaluate
judge.calibration.promote
judge.calibration.revoke
```

M4：

```text
experiment.create
experiment.approve
experiment.start
experiment.assign
experiment.observe
experiment.stop
experiment.analyze
experiment.promote_variant
```

## 11. 单章 Outcome Saga

```text
reader_outcome.root
├─ feature.extract
├─ segment.resolve
├─ judge.outcome.score [fan-out]
├─ judge.pairwise.compare [conditional]
├─ judge.adversarial.review [conditional]
├─ judge.arbitration.resolve [conditional]
├─ result.aggregate
└─ decision.evaluate.shadow
```

该 Saga 使用 Authority Attempt 和 ProductionExecutionGateway，不建立独立执行运行时。

## 12. 数据模型最小集

M0/M1 首期：

```text
reader_segment
reader_segment_version
judge_profile
judge_run
judge_evidence
narrative_feature_snapshot
outcome_prediction
pairwise_evaluation
quality_decision
```

M2 增加：

```text
human_preference_batch
human_preference_assignment
human_preference_vote
human_decision_override
```

M3/M4 有真实数据后增加：

```text
reader_exposure
reader_outcome_event
reader_outcome_aggregate
calibration_dataset_snapshot
outcome_calibration_profile
experiment
experiment_variant
experiment_assignment
experiment_metric_snapshot
```

第一阶段不得一次创建全部高级表。

## 13. API

Shadow Prediction：

```http
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/outcome-predictions
```

```json
{
  "chapter_version_id": "CHV-0012-R2",
  "reader_segment_version_ids": ["SEG-V1"],
  "prediction_scope": ["completion_score", "next_chapter_score"],
  "mode": "shadow",
  "idempotency_key": "..."
}
```

响应只返回 Operation Receipt：

```json
{
  "operation_id": "OP-...",
  "status": "ADMITTED",
  "trace_id": "TRACE-..."
}
```

## 14. 验收

M1 Shadow 集成必须证明：

- 使用真实 ExecutionBackend 或明确 Fixture；
- 输入版本完整冻结；
- Output AssetVersion Append-only；
- Usage / Cost / Trace 可追溯；
- Duplicate Request 幂等；
- Provider UNKNOWN 可 Reconcile；
- OOD 和 Disagreement 可查询；
- 不改变 Chapter Publish / Completion；
- 不把 Raw Score 标成 Probability；
- 不把 Fixture 标成 Production Evidence。