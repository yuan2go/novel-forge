# Reader Outcome Judge：读者反馈、实验与权威契约

> 返回：[Reader Outcome Judge 总览](README.md)  
> 更新日期：2026-07-22  
> 文档状态：`ACTIVE TARGET DESIGN`

## 1. 真实读者行为模型

### 1.1 Exposure 是结果分析起点

任何 Outcome 必须绑定明确 Exposure：

```yaml
reader_exposure:
  exposure_id: EXPOSURE-...
  anonymous_reader_id: R-...
  book_id: B-...
  chapter_id: C-...
  chapter_version_id: CHV-...
  reader_segment_version_id: SEG-...
  experiment_id: EXP-... | null
  traffic_source: recommendation
  placement: feed_slot_3
  title_version_id: TITLE-V2
  cover_version_id: COVER-V3
  synopsis_version_id: SYNOPSIS-V1
  price_context: free
  platform_policy_version: PPF-...
  assigned_at: timestamp
```

没有 Exposure，就不能区分正文质量和流量、位置、标题、封面或价格影响。

### 1.2 Outcome Event

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

### 1.3 幂等、延迟和修正

每个事件必须包含：

```text
stable_event_id
source
occurred_at
received_at
deduplication_key
schema_version
correction_reference | null
```

约束：

- `(source, deduplication_key)` 唯一；
- 迟到事件允许进入新 Aggregate Version；
- 修正事件引用原事件；
- 不原地覆盖历史事件。

### 1.4 Outcome Window

```text
W0  当前章
W1  下一章
W3  后续 3 章
W10 后续 10 章
W30 后续 30 章
WP  付费后窗口
WV  卷级窗口
```

观察窗口未结束时使用：

```text
PENDING
CENSORED
```

不能把未观察到结果直接当作失败。

### 1.5 混杂因素

必须记录：

- 流量来源；
- 推荐位置；
- 广告和免费活动；
- 标题、封面、简介版本；
- 阅读设备和时间；
- 章节价格；
- 新老读者；
- 推荐策略版本；
- 书籍生命周期阶段。

## 2. Feedback Authority

Feedback Authority 负责：

```text
Raw Signal
→ Normalize
→ Aggregate
→ Attribution
→ Confidence
→ PlanAdjustmentProposal
```

不负责：

- 直接修改 Canon；
- 覆盖 Frozen ChapterPlan；
- 改变 EndingIntent；
- 删除主要人物；
- 直接发布；
- 根据单次评论修改主线。

### 2.1 信号层级

```text
L0 Raw Signal
L1 Normalized Metric
L2 Attribution
L3 Adjustment Proposal
```

### 2.2 Confidence Gate

高影响提案至少判断：

- Sample Size；
- Signal Stability；
- Cross-channel Consistency；
- Text Evidence Consistency；
- Platform Anomaly；
- Attribution Confidence；
- Affected Scope；
- 与 BookPlan / EndingContract 冲突；
- 是否属于 Exposure Bias。

## 3. Experiment Center 边界

不是所有小说平台都支持正文版本的读者级随机分流。

Platform Adapter 必须声明：

```text
supports_reader_level_assignment
supports_variant_delivery
supports_exposure_receipt
supports_outcome_event
supports_price_context
supports_title_cover_version_binding
```

只有以下全部满足，才允许称为随机因果实验：

- Reader-level 或合法随机化单元；
- 变体稳定且不可中途修改；
- Exposure 可绑定具体版本；
- Outcome Window 可观测；
- Assignment 不可重写；
- SRM 和污染检查可运行；
- Primary / Secondary / Guardrail 预先声明。

平台不支持时，只能称为：

```text
observational analysis
private reader panel
offline controlled reading test
quasi-experiment
```

不得声称 `CAUSAL_VALIDATED`。

## 4. 实验类型

允许：

- 开篇 A/B/n；
- Hook；
- 冲突进入位置；
- 人物选择；
- 说明量；
- 章节长度；
- 付费点；
- Revision Version；
- 标题、封面、简介和正文联合实验。

不允许实验违反：

- Canon；
- Originality；
- Safety；
- Platform Policy；
- Reader Trust Hard Guardrail。

## 5. 默认实验方法

第一版推荐：

- Reader-level 随机分配，若平台支持；
- Intent-to-Treat；
- 二元指标使用 Beta-Binomial 或预先声明的频率方法；
- 连续指标使用 Bootstrap Interval；
- 监控 Sample Ratio Mismatch；
- 使用 Minimum Practical Effect；
- 预先声明 Primary、Secondary 和 Guardrail；
- 不允许看到中期结果后修改 Primary Metric。

实验定义：

```yaml
experiment:
  experiment_id: EXP-...
  hypothesis: 冲突提前能提高十章留存且不伤害付费后留存
  randomization_unit: anonymous_reader_id
  target_segment_version_ids: [SEG-...]
  variants: [CHV-A, CHV-B]
  allocation_version: 1
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
  minimum_practical_effect: 0.02
  observation_window: W10
  status: DRAFT
```

## 6. 实验状态与污染防护

```text
DRAFT
→ APPROVED
→ RUNNING
→ STOPPING
→ ANALYZING
→ WON | INCONCLUSIVE | FAILED | CANCELLED
→ PROMOTED | ARCHIVED
```

污染防护：

- 同一读者在同一实验中保持一致分组；
- Variant 不得中途修改；
- 推荐位置差异必须记录；
- Experiment Winner 不覆盖历史版本；
- Promote 创建新的 Active Version Pointer；
- Assignment 保存随机化单元和 Hash Bucket；
- Allocation 变化创建新版本。

## 7. Decision Policy Engine

决策优先级：

```text
Hard Gate
→ Quality Blocker
→ Calibration Validity
→ OOD / Disagreement
→ Long-term Outcome
→ Short-term Outcome
→ Experiment Value
→ Cost / Deadline
```

决策枚举：

```text
ACCEPT
REVISE
EXPERIMENT
HUMAN_REVIEW
REJECT
PAUSE_BOOK_PROPOSAL
INSUFFICIENT_EVIDENCE
```

第一阶段只输出：

```text
ACCEPT_ADVISORY
REVISE_ADVISORY
HUMAN_REVIEW
INSUFFICIENT_EVIDENCE
```

所有阈值和 Policy 必须版本化。

### 7.1 Expected Value of Information

是否实验应考虑：

```text
Expected Decision Improvement
- Experiment Cost
- Delay Cost
- Traffic Opportunity Cost
- Content and Trust Risk
```

高价值开篇、付费点和关键 Revision 更值得实验；低流量普通章不一定值得。

## 8. Anti-Goodhart 和 Reader Trust

只优化下一章点击会诱导：

- 假 Hook；
- 强行断章；
- 拖延答案；
- 过度反转；
- 重复刺激；
- 付费前压缩兑现；
- 付费后快速崩塌。

Guardrail：

```text
false_hook_rate
promise_default_rate
post_payment_fast_drop_rate
excessive_cliffhanger_rate
repeated_stimulation_rate
title_content_mismatch_rate
reader_complaint_rate
```

规则：

- 下一章点击提升但十章留存下降：不得 Promote；
- 付费提升但付费后留存下降：默认失败；
- 投诉显著上升：Guardrail Fail；
- 破坏人物、Canon 或 Originality：Hard Fail。

## 9. Calibration Authority Contract

### 9.1 Dataset Freeze

Calibration Dataset 必须：

- 绑定具体 Feature Schema、Judge Profile 和 Outcome Target；
- 保存训练、验证和测试分割；
- 防止当前测试标签进入 Prompt；
- 记录 Censoring 和 Missingness；
- 记录 Segment Coverage 和 Exposure Context。

### 9.2 Promote

`judge.calibration.promote` 必须要求：

- Frozen Dataset Snapshot；
- Candidate Profile；
- Active Baseline；
- Evaluation Report；
- No Test Leakage Assertion；
- Worst-group 不退化；
- Approval，若策略要求；
- Rollback Target。

失败不得覆盖 Active Profile。

## 10. Experiment Authority Contract

`experiment.promote_variant` 必须要求：

- Experiment 状态为 `WON`；
- SRM 和污染检查通过；
- Primary Metric 达到 Minimum Practical Effect；
- Guardrail 未失败；
- Analysis Report 冻结；
- Promoted Version 不可变；
- Book / Chapter Authority 接受新的 Active Version Pointer；
- 影响分析和 Frozen Horizon 规则满足。

## 11. Command Catalog

Reader Data：

```text
reader.segment.create
reader.segment.update
reader.segment.deprecate
reader.exposure.record
reader.outcome.record
reader.outcome.aggregate
reader.outcome.window.close
```

Calibration：

```text
judge.calibration.dataset.freeze
judge.calibration.run
judge.calibration.evaluate
judge.calibration.promote
judge.calibration.revoke
judge.drift.detect
judge.drift.report
```

Experiment：

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

Human：

```text
human.preference.batch.create
human.preference.assignment.create
human.preference.vote.record
human.preference.batch.close
human.decision.override
```

## 12. Saga

Calibration：

```text
calibration.root
├─ dataset.freeze
├─ leakage.check
├─ candidate.fit
├─ offline.evaluate
├─ worst_group.evaluate
├─ regression.evaluate
├─ approval.gate
└─ profile.promote
```

Experiment：

```text
experiment.root
├─ capability.validate
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

Human Override：

```text
automatic_decision
→ override_request
→ approval / rejection
→ override_receipt
→ downstream resume
```

原自动决策必须保留。

## 13. 数据模型阶段化

M2 前：

```text
human_preference_batch
human_preference_assignment
human_preference_vote
human_decision_override
```

M3 有真实行为后：

```text
reader_exposure
reader_outcome_event
reader_outcome_aggregate
calibration_dataset_snapshot
outcome_calibration_profile
```

M4 平台能力满足后：

```text
experiment
experiment_variant
experiment_assignment
experiment_metric_snapshot
```

第一阶段数据量不足时不提前分区；Schema 应预留未来分区和延迟事件能力。

## 14. API

Exposure / Outcome：

```http
POST /api/v1/reader-exposures
POST /api/v1/reader-outcome-events:batch
```

要求：幂等、批量、部分失败 Receipt、Schema Version、Source Adapter、Late Event。

Human Preference：

```http
POST /api/v1/human-preference-batches
GET  /api/v1/human-preference-assignments/next
POST /api/v1/human-preference-assignments/{id}/votes
```

Experiment：

```http
POST /api/v1/experiments
POST /api/v1/experiments/{id}:approve
POST /api/v1/experiments/{id}:start
POST /api/v1/experiments/{id}:stop
POST /api/v1/experiments/{id}:analyze
POST /api/v1/experiments/{id}:promote
```

## 15. 验收边界

M3 行为校准必须证明：

- Exposure 绑定 ChapterVersion 100%；
- Event 幂等去重；
- Outcome Window 正确处理 Pending / Censored；
- Calibration 优于简单 Baseline；
- OOD 自动决策率为 0；
- Promote 可回滚；
- 预测和真实结果残差可查询。

M4 因果验证必须证明：

- Platform Adapter 支持随机分流；
- Assignment 稳定；
- SRM 通过；
- Primary 和 Guardrail 预先声明；
- Promote 不覆盖历史；
- 不使用观察性相关冒充因果结果。