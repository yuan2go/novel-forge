# Reader Outcome Judge：读者反馈、实验与权威契约

> 返回：[Reader Outcome Judge 总览](README.md)

# 18. 真实读者行为模型

## 18.1 Exposure 是因果分析起点

任何 Outcome 必须绑定 Exposure：

```yaml
reader_exposure:
  exposure_id: EXPOSURE-...
  anonymous_reader_id: R-...
  book_id: B-...
  chapter_id: C-...
  chapter_version_id: CHV-...
  reader_segment_id: SEG-...
  experiment_id: EXP-... | null
  traffic_source: recommendation
  placement: feed_slot_3
  price_context: free
  assigned_at: timestamp
```

## 18.2 Outcome Event

```text
chapter_impression
chapter_open
reading_progress
chapter_complete
next_chapter_open
follow
favorite
comment
paywall_view
payment
post_payment_continue
return_next_day
return_next_week
book_abandon
refund
complaint
```

## 18.3 幂等与去重

每个事件必须包含：

- stable event id；
- source；
- occurred_at；
- received_at；
- deduplication key；
- schema version；
- correction reference，若为修正事件。

## 18.4 行为窗口

```text
W0: 当前章
W1: 下一章
W3: 后续 3 章
W10: 后续 10 章
W30: 后续 30 章
WP: 付费后窗口
WV: 卷级窗口
```

未到观察窗口结束前，Outcome 状态应为 `CENSORED` 或 `PENDING`，不能当作失败。

## 18.5 混杂因素

必须记录：

- 流量来源；
- 推荐位置；
- 是否广告；
- 免费活动；
- 标题、封面、简介版本；
- 阅读设备；
- 阅读时间；
- 章节价格；
- 新老读者；
- 平台推荐策略版本。

否则无法区分内容效果与曝光效果。

---

# 19. Experiment Center

## 19.1 实验类型

- 开篇 A/B/n；
- 钩子；
- 冲突进入位置；
- 人物选择；
- 说明量；
- 章节长度；
- 付费点；
- 修订版本；
- 标题与正文联合实验。

## 19.2 默认实验方法

第一版推荐：

- Reader-level 随机分配；
- Intent-to-Treat 分析；
- 二元指标使用 Beta-Binomial 后验；
- 连续指标使用 bootstrap 区间；
- 同时监控 Sample Ratio Mismatch；
- 设最小实际效果，而非只看统计显著；
- 预先声明 primary、secondary、guardrail metrics。

## 19.3 实验定义

```yaml
experiment:
  experiment_id: EXP-...
  hypothesis: 冲突提前能提高十章留存且不伤害付费后留存
  target_segment_ids: [SEG-...]
  variants: [CHV-A, CHV-B]
  allocation: [0.5, 0.5]
  primary_metric: ten_chapter_retention
  secondary_metrics:
    - chapter_completion
    - next_chapter_open
    - paywall_conversion
  guardrail_metrics:
    - post_payment_retention
    - complaint_rate
    - reader_trust_damage
  minimum_effect: 0.02
  observation_window: W10
  status: DRAFT
```

## 19.4 状态机

```text
DRAFT
→ APPROVED
→ RUNNING
→ STOPPING
→ ANALYZING
→ WON | INCONCLUSIVE | FAILED | CANCELLED
→ PROMOTED | ARCHIVED
```

## 19.5 污染防护

- 同一读者不能在同一实验中看到多个正文版本；
- 版本不得中途修改；
- 推荐位置差异必须记录；
- 实验前不得读取结果修改 primary metric；
- 实验赢家不得直接覆盖历史版本；
- Promote 必须创建新的 Active Version 指针。

---

# 20. Decision Policy Engine

## 20.1 决策枚举

```text
ACCEPT
REVISE
EXPERIMENT
HUMAN_REVIEW
REJECT
PAUSE_BOOK
INSUFFICIENT_EVIDENCE
```

## 20.2 决策优先级

```text
Hard Gate
→ Quality Blocker
→ Calibration Validity
→ OOD / Uncertainty
→ Long-term Outcome
→ Short-term Outcome
→ Experiment Value
→ Cost / Deadline
```

## 20.3 示例策略

```yaml
decision_policy:
  hard_fail:
    - canon_consistency == FAIL
    - originality_risk == HIGH
    - safety_verdict == FAIL

  accept:
    - blocker_count == 0
    - calibration_state in [HUMAN_ANCHORED, BEHAVIOR_CALIBRATED, CAUSAL_VALIDATED]
    - next_chapter_open_probability >= 0.68
    - ten_chapter_retention_probability >= 0.34
    - confidence >= 0.80
    - out_of_distribution == false

  experiment:
    - blocker_count == 0
    - confidence >= 0.55
    - confidence < 0.80
    - expected_value_of_information >= threshold

  human_review:
    - chapter_type in [opening, paywall, climax, volume_ending, book_ending]
    - judge_disagreement == HIGH
```

所有阈值必须版本化，不能硬编码在 Handler。

## 20.4 Expected Value of Information

是否实验应考虑：

```text
预期决策改善价值
- 实验成本
- 延迟成本
- 流量机会成本
- 内容风险
```

低流量、低风险章节不一定值得实验；高价值开篇或付费点更值得实验。

---

# 21. Command Kernel 操作目录

## 21.1 Judge 操作

```text
judge.feature.extract
judge.quality.evaluate
judge.outcome.predict
judge.pairwise.compare
judge.adversarial.review
judge.arbitration.resolve
judge.decision.evaluate
```

## 21.2 校准操作

```text
judge.calibration.dataset.freeze
judge.calibration.run
judge.calibration.evaluate
judge.calibration.promote
judge.calibration.revoke
judge.drift.detect
judge.drift.report
```

## 21.3 Reader 数据操作

```text
reader.segment.create
reader.segment.update
reader.segment.deprecate
reader.exposure.record
reader.outcome.record
reader.outcome.aggregate
reader.outcome.window.close
```

## 21.4 实验操作

```text
experiment.create
experiment.approve
experiment.start
experiment.assign
experiment.observe
experiment.stop
experiment.analyze
experiment.promote_variant
experiment.archive
```

## 21.5 人工操作

```text
human.preference.batch.create
human.preference.assignment.create
human.preference.vote.record
human.preference.batch.close
human.decision.override
```

## 21.6 Chapter / Book 集成操作

```text
chapter.reader_outcome.predict
chapter.quality.decision.evaluate
book.reader_outcome.recap.light
book.reader_outcome.recap.formal
book.reader_outcome.recap.volume
book.reader_outcome.plan_adjustment
```

---

# 22. Operation Definition 与 Completion Contract

## 22.1 `chapter.reader_outcome.predict`

```yaml
input_schema:
  required:
    - project_id
    - chapter_version_id
    - reader_segment_version_ids
    - judge_profile_version_id

frozen_inputs:
  - draft_version
  - chapter_plan
  - quality_score_report
  - canon_patch
  - reader_segment_profile
  - platform_profile
  - judge_profile
  - calibration_profile

completion_contract:
  required_outputs:
    - reader_outcome_prediction_bundle
  auxiliary_outputs:
    - narrative_feature_snapshot
    - judge_disagreement_report
    - out_of_distribution_report
  invariants:
    - every prediction references exact chapter_version_id
    - every segment has explicit calibration status
    - provider evidence is persisted
```

## 22.2 `judge.calibration.promote`

必须要求：

- frozen dataset snapshot；
- candidate profile；
- baseline profile；
- evaluation report；
- approval decision，若策略要求；
- rollback target；
- no test leakage assertion。

## 22.3 `experiment.promote_variant`

必须要求：

- experiment status 为 `WON`；
- guardrail 未失败；
- analysis report 冻结；
- promoted version 不可变；
- Book / Chapter Authority 接受新 Active Version 指针。

---

# 23. Saga 设计

## 23.1 单章 Outcome Saga

```text
reader_outcome.root
├─ feature.extract
├─ segment.resolve
├─ judge.outcome.predict [fan-out per segment]
├─ judge.adversarial.review [conditional]
├─ judge.arbitration.resolve [conditional]
├─ prediction.aggregate
└─ decision.evaluate
```

## 23.2 Calibration Saga

```text
calibration.root
├─ dataset.freeze
├─ leakage.check
├─ candidate.train_or_fit
├─ offline.evaluate
├─ segment.worst_group.evaluate
├─ regression.evaluate
├─ approval.gate
└─ profile.promote
```

失败时不得覆盖 Active Profile。

## 23.3 Experiment Saga

```text
experiment.root
├─ design.validate
├─ approval.gate
├─ assignment.activate
├─ exposure.collect
├─ outcome.window.await
├─ metrics.aggregate
├─ contamination.check
├─ analysis.run
├─ guardrail.gate
└─ variant.promote | archive
```

## 23.4 人工覆盖 Saga

```text
automatic_decision
→ human_override_request
→ approval / rejection
→ override_receipt
→ downstream resume
```

原自动决策必须保留。

---

# 24. PostgreSQL 数据模型

## 24.1 核心表

```text
quality_rule
quality_rule_version
judge_profile
judge_run
judge_evidence
judge_disagreement
reader_segment
reader_segment_version
outcome_prediction
outcome_calibration_profile
calibration_dataset_snapshot
chapter_variant
pairwise_evaluation
human_preference_batch
human_preference_assignment
human_preference_vote
reader_exposure
reader_outcome_event
reader_outcome_aggregate
experiment
experiment_variant
experiment_assignment
experiment_metric_snapshot
quality_decision
human_decision_override
judge_drift_report
```

## 24.2 关键约束

### outcome_prediction

- 唯一键：`prediction_id`；
- 外键：chapter version、segment version、judge profile、calibration profile；
- 不允许 UPDATE 预测 payload；
- 支持 `supersedes_prediction_id`，但历史保留。

### reader_exposure

- 唯一 `exposure_id`；
- `(experiment_id, anonymous_reader_id)` 在实验策略内保持一致分组；
- 必须引用具体 `chapter_version_id`。

### reader_outcome_event

- `(source, deduplication_key)` 唯一；
- event payload 带 schema version；
- correction event 引用原 event。

### experiment_assignment

- 分配后不可修改；
- 变体权重变更生成新的 allocation version；
- 保存随机化单元和 hash bucket。

### quality_decision

- 引用具体 prediction、quality report、policy version；
- 人工覆盖通过额外表记录；
- 不覆盖自动决策。

## 24.3 索引建议

```text
outcome_prediction(chapter_version_id, reader_segment_version_id)
reader_exposure(chapter_version_id, assigned_at)
reader_outcome_event(exposure_id, occurred_at)
reader_outcome_aggregate(reader_segment_id, outcome_window, calculated_at)
experiment_assignment(experiment_id, anonymous_reader_id)
judge_run(judge_profile_id, created_at)
```

## 24.4 分区建议

高频事件表可按月或项目分区：

- reader_exposure；
- reader_outcome_event；
- judge_run；
- experiment_metric_snapshot。

第一阶段数据量不足时不提前复杂化，但 schema 应避免阻塞未来分区。

---

# 25. API Contract

## 25.1 预测 API

```http
POST /api/v1/projects/{project_id}/chapters/{chapter_id}/outcome-predictions
```

请求：

```json
{
  "chapter_version_id": "CHV-0012-R2",
  "reader_segment_version_ids": ["SEG-V1"],
  "prediction_scope": ["completion", "next_chapter", "ten_chapter_retention"],
  "mode": "shadow",
  "idempotency_key": "..."
}
```

响应只返回 operation receipt，不同步执行长任务：

```json
{
  "operation_id": "OP-...",
  "status": "ACCEPTED",
  "trace_id": "TRACE-..."
}
```

## 25.2 结果查询

```http
GET /api/v1/operations/{operation_id}
GET /api/v1/chapters/{chapter_id}/outcome-predictions
GET /api/v1/predictions/{prediction_id}
```

## 25.3 曝光与事件接入

```http
POST /api/v1/reader-exposures
POST /api/v1/reader-outcome-events:batch
```

必须支持：

- 幂等；
- 批量；
- 部分失败回执；
- schema version；
- source adapter；
- 延迟事件。

## 25.4 人工偏好

```http
POST /api/v1/human-preference-batches
GET  /api/v1/human-preference-assignments/next
POST /api/v1/human-preference-assignments/{id}/votes
```

## 25.5 实验 API

```http
POST /api/v1/experiments
POST /api/v1/experiments/{id}:approve
POST /api/v1/experiments/{id}:start
POST /api/v1/experiments/{id}:stop
POST /api/v1/experiments/{id}:analyze
POST /api/v1/experiments/{id}:promote
```
