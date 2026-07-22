# Reader Outcome Judge：模型治理、测试与实施路线

> 返回：[Reader Outcome Judge 总览](README.md)  
> 更新日期：2026-07-22  
> 文档状态：`ACTIVE TARGET DESIGN`

## 1. Provider 与模型策略

### 1.1 M1 Machine Validation

第一阶段不训练专用 Outcome Model，采用：

```text
Strong LLM Judge
+ Strict Structured Output
+ Role Separation
+ Pairwise Position Swap
+ Mutation / Metamorphic Test
+ OOD Detection
+ Shadow Mode
```

输出是 Raw Score、Ordinal Band、Evidence 和 Disagreement，不是可信行为概率。

### 1.2 M2 Human Anchor

```text
LLM Raw Score
+ Target Reader / Editor Pairwise Vote
+ Ranking / Band Calibration
→ HUMAN_ANCHORED
```

Human Anchor 用于验证排序和偏好一致性，不等同于行为概率校准。

### 1.3 M3 Behavior Calibration

```text
Raw Score
+ Narrative Features
+ Segment / Platform / Chapter Type
+ Exposure / Outcome
+ Logistic / GBDT / Calibration Model
→ Calibrated Outcome Probability
```

可使用 Platt、Isotonic、Beta Calibration 或透明统计模型。

### 1.4 M4 Causal Validation

可评估：

- 随机实验；
- 生存分析处理长期留存和 Censoring；
- 分层模型处理平台、题材和书级差异；
- Uplift Model 预测修订是否真正改善结果。

只有合法随机化和 Guardrail 通过后才允许 `CAUSAL_VALIDATED`。

### 1.5 职责隔离

- 正文生成模型不能单独担任最终 Judge；
- 同一 Provider 可承担不同角色，但 Profile、Prompt、Context 和 RouteSnapshot 必须隔离；
- Judge 不得看到当前样本真实标签；
- 测试集不得进入 Prompt Example；
- 所有调用通过 ProductionExecutionGateway；
- Usage、Cost、Latency、Prompt、Skill 和 Model Version 可追溯。

### 1.6 降级

```text
Primary Judge unavailable
→ Secondary Qualified Judge
→ Deterministic Quality-only Mode
→ INSUFFICIENT_EVIDENCE
→ Human Review / Shadow
```

不得使用 Fixture 冒充真实 Judge，也不得把未校准 Score 当 Probability。

## 2. Prompt 与输出规范

输入分区：

```text
SYSTEM ROLE
TASK CONTRACT
QUALITY RULES
READER SEGMENT
PLATFORM PROFILE
CHAPTER INTENT
LONGFORM STATE
CHAPTER TEXT
OUTPUT SCHEMA
```

每条判断必须包含：

- Claim；
- Applicability；
- Evidence Span；
- Counter Evidence；
- Severity；
- Confidence Band；
- Limitation；
- Recommended Action。

禁止：

- 无证据总分；
- 只写“节奏较好”；
- 使用未提供的真实读者数据；
- 把模拟反应写成真实事实；
- 把 Raw Score 写成 Calibrated Probability；
- 缺少 Segment 的全局断言；
- 输出虚构的样本量和 Calibration Error。

生产 Schema 必须使用完整 JSON Schema：

- enum；
- arrays / items；
- oneOf / anyOf；
- number bounds；
- string pattern；
- nested required；
- `additionalProperties=false`；
- schema version。

## 3. OOD 与不确定性治理

### 3.1 OOD 来源

- 未覆盖平台和题材；
- 极端章节长度；
- 新型叙事结构；
- Segment 样本不足；
- Feature 分布偏离；
- Book 生命周期发生变化；
- Judge Model / Prompt 漂移；
- 与历史样本距离过大。

### 3.2 可观测不确定性

```text
judge_disagreement
pairwise_position_sensitivity
segment_sample_coverage
mutation_stability
human_disagreement
calibration_sample_count
calibration_error
ood_distance
prediction_residual
```

第一阶段不得让单个 LLM 直接声明精确的 Aleatoric / Epistemic Uncertainty 数字。

### 3.3 Policy

OOD 或证据不足时：

```text
Disable Automatic ACCEPT
Allow Shadow Score
Allow Human Review
Allow Legal Experiment
Return INSUFFICIENT_EVIDENCE
```

## 4. Anti-Goodhart 与 Reader Trust

监控：

```text
false_hook_rate
promise_default_rate
post_payment_fast_drop_rate
excessive_cliffhanger_rate
repeated_stimulation_rate
title_content_mismatch_rate
reader_complaint_rate
```

约束：

- Next Chapter 提升但 10-Chapter Retention 下降：不得 Promote；
- Payment 提升但 Post-payment Retention 下降：默认失败；
- Complaint 显著上升：Guardrail Fail；
- Canon、Character、Originality、Safety 失败：Hard Fail。

## 5. Drift 管理

Drift 来源：

- Judge Model Upgrade；
- Prompt / Rule Update；
- Platform Recommendation Change；
- Reader Preference Change；
- New Genre；
- Pricing Change；
- Book Lifecycle Change。

监控：

- Raw Score Distribution；
- Calibration Error；
- Segment Worst-group；
- Judge Disagreement；
- OOD Ratio；
- Human Override Rate；
- Prediction Residual；
- Feature Drift。

自动降级：

```text
Drift Detected
→ Mark Profile DEGRADED
→ Disable Automatic ACCEPT
→ Enter Shadow Mode
→ Freeze New Calibration Dataset
→ Recalibrate
→ Regression Test
→ Promote or Revoke
```

## 6. Observability

每次 Judge Run 必须记录：

```text
operation_id
saga_id
attempt_id
route_snapshot_id
provider_request_id | null
local_execution_receipt_id | null
judge_type
model_profile_version
prompt_version
skill_version
input_hash
output_hash
usage
cost
latency
calibration_profile_version_id | null
decision_policy_version
result_status
```

最小 Cockpit：

1. Chapter Outcome Timeline；
2. Segment Score / Prediction Matrix；
3. Raw Score vs Calibrated Probability；
4. Quality Blocker；
5. Judge Disagreement；
6. Human Review Queue；
7. Calibration Health；
8. Experiment Status；
9. Drift Alerts；
10. Cost / Latency。

告警：

- Invalid Output；
- Calibration Missing；
- OOD Spike；
- Disagreement Spike；
- Event Ingestion Lag；
- Experiment SRM；
- Prediction Residual Drift；
- Post-payment Retention Drop；
- Cost Overrun。

## 7. 失败、重试与恢复

### Judge Execution Failure

- 通过 ProductionExecutionGateway；
- 使用 Authority Attempt 和 ExternalEffect Identity；
- Query / Cancel / Reconcile；
- UNKNOWN 不得直接重发；
- Schema Invalid 可按策略有限重试；
- 超过上限进入 Human Review。

### Event Delay

- Outcome Window 支持迟到事件；
- Aggregate 可重算并产生新版本；
- 已 Promote 实验若受重大修正影响，生成 Audit Alert，不静默改写。

### Calibration Failure

- Active Profile 保持不变；
- Candidate 标记 Failed；
- 不允许半完成 Promote；
- Failure Report 进入 Eval Center。

### Experiment Worker Failure

- Assignment 由 PostgreSQL Authority 保存；
- 重启后按原 Assignment 恢复；
- 不重复分组；
- Metric 可由 Event 重建。

## 8. Security、Privacy 与 Source Isolation

- Reader ID 匿名化或假名化；
- 只记录分析所需数据；
- 不收集无关敏感属性；
- Segment 使用统计群体；
- 支持删除、撤回和保留策略；
- Platform Adapter 遵守平台协议；
- Judge 不读取高风险参考原文；
- 外部评论视为不可信输入并清洗；
- 防止 Prompt Injection；
- 每个发布建议可回答模型、Prompt、Rule、Segment、Evidence 和 Override。

## 9. 测试体系

### 9.1 Unit

- Schema；
- Policy；
- Segment Fallback；
- Calibration Resolution；
- Event Dedup；
- Outcome Window；
- Experiment Assignment；
- Version Binding。

### 9.2 PostgreSQL Integration

- Authority Admission；
- Saga Recovery；
- Invalid Provider Output；
- Callback；
- Cancel / Retry / Fencing；
- Outbox；
- Human Approval Resume；
- Experiment Recovery。

### 9.3 Judge Regression Set

```text
Golden Human Preference
Mutation Cases
Pairwise Cases
OOD Cases
Adversarial Cases
Longform Cases
Platform Cases
```

### 9.4 Metamorphic

只改变一个维度时，相关指标应变化，无关维度不应同步大幅漂移。

### 9.5 End-to-End

E2E-1 Shadow Single Chapter：

```text
ChapterVersion
→ Five Quality Groups
→ Raw Outcome Score
→ Advisory Decision
→ Publish Unchanged
```

E2E-2 Human Anchored Pairwise：

```text
Two Versions
→ Judge Pairwise
→ Human Blind Vote
→ Agreement Report
```

E2E-3 Behavior Calibration：

```text
Raw Score
→ Exposure
→ Outcome Event
→ Aggregate
→ Calibration
→ Calibrated Probability
```

E2E-4 Controlled Experiment：

```text
Platform Capability
→ Variant Assignment
→ Exposure / Outcome Window
→ SRM / Analysis / Guardrail
→ Promote or Inconclusive
```

E2E-5 10 / 30 Chapter Trend：

- 每章 Score / Prediction；
- 书级趋势；
- Recap；
- PlanAdjustmentProposal；
- Recovery；
- Drift；
- Cost。

## 10. 建议工程门槛

以下是第一版目标，不是跨题材永久标准。

### M1 Intrinsic / Machine Validation

- Blocker Mutation Recall ≥ 0.90；
- Warning Mutation Recall ≥ 0.75；
- Evidence Localization Accuracy ≥ 0.80；
- False Positive Rate ≤ 0.15；
- Pairwise Position Stability ≥ 0.85；
- OOD 自动生产决策率 = 0。

### M2 Human Anchor

- Pairwise Human Agreement ≥ 0.70；
- 高置信样本 Agreement ≥ 0.80；
- `CANNOT_JUDGE` 单独监控；
- Segment Worst-group 不严重退化。

### M3 Behavior Calibration

- Brier / Log Loss 优于简单 Baseline；
- ECE 达到预设门槛；
- 10-Chapter Retention 优于 Genre Mean Baseline；
- Post-payment Retention 不只依赖 Payment Conversion；
- Exposure 绑定率 100%；
- Event 不重复计数；
- Promote 可回滚。

### M4 Experiment

- Randomization Capability 有证据；
- SRM 通过；
- Primary / Guardrail 预注册；
- Minimum Practical Effect 达到；
- Historical Version 不覆盖；
- Observational Result 不冒充 Causal Result。

## 11. 实施目录

```text
src/novel_forge/modules/reader_outcome_authority/
├─ contracts.py
├─ models.py
├─ repository.py
├─ application.py
├─ handlers.py
├─ scheduler.py
├─ policies.py
├─ features.py
├─ pairwise.py
├─ calibration.py
├─ drift.py
└─ ports.py

src/novel_forge/modules/reader_feedback/
├─ adapters/
├─ ingestion.py
├─ aggregation.py
└─ contracts.py
```

第一阶段 Chapter Adapter 可以留在 `chapter_authority`，但领域和 Calibration 逻辑不得写死在 Handler。

## 12. 分阶段路线

### WP-ROJ-0 Evidence Boundary

- 修正文档语义；
- Raw Score / Probability 分离；
- Maturity Flag；
- Shadow Policy。

### WP-ROJ-1 Domain and Schema

首期仅实现：

- ReaderSegment；
- JudgeProfile；
- NarrativeFeatureSnapshot；
- RawOutcomeScore；
- PairwiseReport；
- OODReport；
- AdvisoryDecision。

### WP-ROJ-2 Authority Core

- Operation Catalog；
- PostgreSQL Repository；
- Saga；
- Attempt / Lease / Fencing；
- Outbox；
- ProductionExecutionGateway。

### WP-ROJ-3 Shadow Chapter Integration

- Sidecar Trigger；
- 不进入 Completion Contract；
- 不影响 Publish Gate；
- Independent Budget；
- Query Projection。

达到 M1。

### WP-ROJ-4 Machine Validation

- Feature Extractor；
- Pairwise；
- Mutation；
- Adversarial；
- Arbitration；
- Regression Set。

### WP-ROJ-5 Human Anchor

- Annotation Workbench；
- 60—100 组 Pilot；
- Reviewer Quality；
- Human Anchored Rank / Band。

达到 M2。

### WP-ROJ-6 Behavior Pipeline

只有真实数据来源明确后实现：

- Exposure；
- Outcome Event；
- Aggregate；
- Outcome Window；
- Late Event；
- Calibration。

达到 M3。

### WP-ROJ-7 Experiment Center

只有 Platform Capability 满足后实现：

- Variant；
- Assignment；
- SRM；
- Metric；
- Guardrail；
- Promote。

达到 M4。

### WP-ROJ-8 Book Integration

- 5 / 10 / Volume Trend；
- Drift；
- Pause Proposal；
- Plan Adjustment Evidence。

### WP-ROJ-9 Bounded Autonomy

- 低风险 Policy 输入；
- Automatic Downgrade；
- Human Override；
- 10 / 30 Chapter Proof。

达到 M5。

## 13. 明确后置项

第一阶段不实现：

- 实时单读者个性化正文；
- 强化学习直接控制 Generator；
- 多平台统一用户 ID；
- 复杂深度推荐系统；
- 全自动发布；
- 多书流量分配；
- 无人工边界自治；
- 未校准概率驱动生产。

## 14. 最终验收声明

只有同时满足以下证据，才允许：

```text
reader_outcome_judge_proven = true
```

1. 真实 ExecutionBackend Judge 调用；
2. Trace、Usage、Cost 和 Version 可追溯；
3. Mutation / Pairwise 回归通过；
4. Target Reader Human Anchor；
5. Prediction 与 Exposure / Outcome 闭环；
6. 真实行为 Calibration；
7. OOD、Drift 和 Human Override 有效；
8. 至少一次合法 Controlled Experiment；
9. 10 / 30 Chapter Trend Proof；
10. Fixture / Mock 不冒充真实证据。