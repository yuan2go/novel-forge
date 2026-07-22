# Reader Outcome Judge：Authority 与生产链接入

> 返回：[Reader Outcome Judge 总览](README.md)

# 6. Authority 与权威边界

## 6.1 PostgreSQL 权威原则

ROJ 必须遵循当前 Command Kernel 的权威原则：

- Command 先被 admission；
- 输入 AssetVersion 冻结；
- Operation 和 Saga 在数据库持久化；
- Provider 调用通过 ExternalEffect；
- Attempt、Lease、Fencing 和 Retry 可恢复；
- 输出不可原地覆盖；
- 预测、校准、决策和人工覆盖全部可审计；
- Outbox 负责发布事件；
- 不允许 LocalStorage 成为生产权威。

## 6.2 权威数据分类

### 资产型数据

以 Asset / AssetVersion 管理：

- `reader_segment_profile`；
- `narrative_feature_snapshot`；
- `reader_outcome_prediction`；
- `pairwise_judge_report`；
- `quality_decision_report`；
- `calibration_profile`；
- `judge_drift_report`；
- `human_preference_batch_report`；
- `experiment_analysis_report`。

### 高频事件型数据

以 append-only PostgreSQL 表管理：

- `reader_exposure`；
- `reader_outcome_event`；
- `experiment_assignment`；
- `human_preference_vote`。

### 聚合型数据

可重建、带版本：

- `reader_outcome_aggregate`；
- `experiment_metric_snapshot`；
- `calibration_dataset_snapshot`。

## 6.3 不可变性

- 已产生的预测不得修改；
- 新模型必须生成新的 prediction；
- Calibration Profile Promote 不能改变历史预测；
- 人工覆盖不能删除原自动决策；
- 实验分组一经分配不可重写；
- 行为修正通过补偿事件实现，不直接覆盖原事件。

---

# 7. Chapter Authority 集成设计

## 7.1 目标链路

当前 18 节点链建议扩展为：

```text
PLAN
→ CONTEXT
→ DRAFT
→ REVIEW
→ REVISION
→ REREVIEW
→ CANON_EXTRACTION
→ CANON_PROPOSAL
→ CANON
→ FIVE QUALITY GROUPS
→ QUALITY
→ READER_OUTCOME
→ DECISION_POLICY
→ PUBLISH_GATE
→ EXPORT
→ FINAL_RELEASE_GATE
```

新增两个逻辑节点：

```text
chapter.reader_outcome.predict
chapter.quality.decision.evaluate
```

其中 `DECISION_POLICY` 也可以在第一阶段作为 `PUBLISH_GATE` 的内部步骤实现，但长期应独立，以便：

- 保存独立决策证据；
- 重新计算策略而不重复调用 Judge；
- 支持不同发布策略；
- 支持人工覆盖；
- 支持 Shadow Mode。

## 7.2 READER_OUTCOME 输入

必须冻结：

- `draft_version`；
- `chapter_plan`；
- `quality_score_report`；
- 五组 `chapter_quality_group_report`；
- `canon_patch`；
- `context_bundle`；
- 当前 `book_production_state`；
- Reader Segment AssetVersion；
- Platform Profile AssetVersion；
- Judge Profile AssetVersion；
- Calibration Profile AssetVersion，若可用。

## 7.3 READER_OUTCOME 输出

主输出：

```text
asset_type: reader_outcome_prediction_bundle
output_key: chapter.reader_outcome
```

辅助输出：

- `narrative_feature_snapshot`；
- 每个 Segment 的 `reader_outcome_prediction`；
- `judge_disagreement_report`；
- `out_of_distribution_report`；
- `prediction_cost_report`。

## 7.4 DECISION_POLICY 输入

- `quality_score_report`；
- `reader_outcome_prediction_bundle`；
- `canon_patch`；
- `re_review_report`；
- `chapter_type`；
- `book_policy`；
- `release_policy`；
- `experiment_policy`；
- `budget_state`。

## 7.5 DECISION_POLICY 输出

```yaml
quality_decision_report:
  decision: ACCEPT | REVISE | EXPERIMENT | HUMAN_REVIEW | REJECT | PAUSE_BOOK
  blocking_reasons: []
  warnings: []
  selected_reader_segments: []
  selected_variant_ids: []
  prediction_ids: []
  calibration_profile_ids: []
  uncertainty_summary: {}
  required_next_operation: string
  policy_version: string
```

## 7.6 章节类型策略

必须区分：

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

开篇、付费点、高潮、卷末和结局默认提高人工或实验门槛。

---

# 8. Book Authority 集成设计

## 8.1 书级输入

Book Authority 不直接重新审核全文，而消费 ROJ 的章节结果和真实行为聚合：

- 最近 3 章预测趋势；
- 最近 5 章轻复盘；
- 最近 10 章真实结果；
- 付费前后结果；
- 质量问题复发率；
- Reader Promise 兑现；
- 爽点和冲突节奏；
- Segment 差异；
- Judge 漂移；
- OOD 比例；
- 人工覆盖频率。

## 8.2 书级复盘节点

```text
book.reader_outcome.recap.light       每 5 章
book.reader_outcome.recap.formal      每 10 章
book.reader_outcome.recap.volume      每卷
book.reader_outcome.plan_adjustment   复盘后
```

## 8.3 自动暂停条件

示例：

- 连续 3 章 `next_chapter_probability` 显著下降；
- 真实十章留存低于书级最低门槛；
- 付费后快速流失显著升高；
- 质量判断与真实结果持续反向；
- OOD 比例超过阈值；
- Judge Profile 被 revoke；
- 同一阻断问题连续复发；
- 预算消耗异常；
- 读者信任指标恶化。

自动暂停必须生成 `book_pause_proposal`，不得在没有策略授权时直接终止项目。
