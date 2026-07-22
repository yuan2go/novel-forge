# Reader Outcome Judge：Judge 契约、特征与校准

> 返回：[Reader Outcome Judge 总览](README.md)  
> 更新日期：2026-07-22  
> 文档状态：`ACTIVE TARGET DESIGN`

## 1. Judge 角色体系

### 1.1 Continuity Judge

负责：

- Canon；
- 时间线；
- 人物、地点、物品和伤势状态；
- 战力、资源和世界规则。

优先使用确定性规则和结构化 Story State，LLM 只补充语义冲突。

### 1.2 Narrative Structure Judge

负责：

- 场景目标；
- 冲突、转折和因果；
- 信息释放；
- 情绪曲线；
- 章节功能；
- 场景状态变化。

### 1.3 Character Judge

负责：

- 主角能动性；
- 动机和人设连续；
- 选择与代价；
- 关系推进；
- Voice 区分；
- Character Arc Contribution。

### 1.4 Commercial Fiction Judge

负责：

- 开篇压力；
- 阅读阻力；
- Reader Promise；
- 爽点和兑现；
- Hook 和追读动力；
- 付费点；
- 移动端节奏；
- 毒点和信任风险。

### 1.5 Prose Judge

负责：

- AI 套话；
- 同义反复；
- 过度总结；
- 说明性对白；
- 抽象情绪；
- 句式同质；
- 段落节奏；
- 文风漂移。

### 1.6 Longform Judge

负责：

- 章节间重复；
- 人物和关系漂移；
- Promise / Foreshadow / Reward Debt；
- 爽点疲劳；
- 设定膨胀；
- 中段塌陷；
- Arc Progress；
- 主线和 Ending Feasibility。

### 1.7 Outcome Judge

针对特定 Reader Segment 输出 Raw Score 或已校准 Prediction，不覆盖硬质量门禁。

### 1.8 Adversarial Judge

挑战结论：

- 规则是否适用；
- 是否存在反证；
- 是否忽略章节功能；
- 是否把风格差异误判为缺陷；
- 是否过度修改；
- 是否存在长度、位置或模型偏好偏差。

### 1.9 Arbitration Judge

仅在以下情况启动：

- Judge 严重分歧；
- A/B 换位后结论改变；
- 接近决策门槛；
- 高价值章节；
- 质量赢家与商业赢家冲突；
- 多轮修订仍不稳定。

## 2. Narrative Feature Schema

Narrative Feature 是文本、结构化状态与统计校准之间的桥梁。

必须：

- 版本化；
- 可重算；
- 可追溯到 Text Span 或 Story State；
- 不复制高风险参考表达；
- 不把 Judge 主观结论伪装成客观事实。

### 2.1 文本基础

```text
word_count
paragraph_count
sentence_length_distribution
dialogue_ratio
narration_ratio
unique_character_count
scene_count
```

### 2.2 冲突与行动

```text
conflict_entry_position
active_conflict_count
state_change_count
protagonist_effective_choice_count
irreversible_choice_count
cost_bearing_action_count
opponent_pressure_event_count
```

### 2.3 信息与认知

```text
new_information_count
repeated_information_ratio
exposition_density
mystery_question_created
mystery_question_resolved
information_asymmetry_count
```

### 2.4 情绪与兑现

```text
emotional_turn_count
positive_payoff_count
negative_cost_count
promise_created_count
promise_partially_fulfilled
promise_fulfilled_count
false_hook_risk
```

### 2.5 长篇连续性

```text
canon_conflict_count
character_state_delta_count
relationship_state_delta_count
arc_contribution_count
foreshadow_open_count
foreshadow_resolved_count
unresolved_debt_age
recent_trope_similarity
recent_scene_similarity
```

### 2.6 移动阅读

```text
long_paragraph_ratio
screen_break_density
opening_pressure_300_chars
first_major_state_change_position
ending_hook_type
ending_unresolved_state_count
```

### 2.7 Evidence

每个关键特征必须允许：

```yaml
evidence:
  protagonist_effective_choice_count:
    - start: 1420
      end: 1633
      explanation: 主角拒绝既定任务并提出替代路径
```

## 3. Reader Segment

### 3.1 冷启动

第一阶段只使用人工定义的宽泛群体：

```yaml
reader_segment:
  segment_id: SEG-TOMATO-XUANHUAN-FAST-V1
  platform: tomato
  primary_genre: eastern_fantasy
  secondary_genres: [system, growth]
  reading_experience: experienced
  preferred_pacing: fast
  exposition_tolerance: low
  preferred_reward_frequency: high
  status: ACTIVE
```

允许维度：

- Platform；
- 主、子题材；
- 阅读经验；
- 节奏和说明容忍度；
- 情绪浓度；
- 主角类型；
- 爽点频率；
- 付费敏感度；
- 连载长度偏好。

默认不使用敏感个人属性。

### 3.2 生命周期

```text
DRAFT
→ VALIDATED
→ ACTIVE
→ MERGED | DEPRECATED
```

每个 Segment 必须记录：

- 定义来源；
- 样本规模；
- 最后校准时间；
- 支持的 Outcome Target；
- 置信边界；
- 合并或废弃原因。

### 3.3 样本不足

不得输出伪精确概率，必须：

- 回退到上级 Genre Segment；
- 回退到 Platform Segment；
- 输出 `INSUFFICIENT_EVIDENCE` 或 OOD；
- 建议 Shadow 或 Human Review。

## 4. Raw Score Contract

M0/M1 输出：

```yaml
reader_outcome_score:
  prediction_id: PRED-...
  chapter_version_id: CHV-...
  reader_segment_version_id: SEG-...
  judge_profile_version_id: JP-...
  calibration_profile_version_id: null
  prediction_scope:
    - completion_score
    - next_chapter_score
    - dissatisfaction_score
    - reader_trust_risk_score

  raw_scores:
    completion_score: 0.88
    next_chapter_score: 0.76
    dissatisfaction_score: 0.21
    reader_trust_risk_score: 0.17

  ordinal_bands:
    completion: HIGH
    next_chapter: MEDIUM_HIGH

  calibrated_probabilities: null
  calibration_status: UNCALIBRATED
  production_decision_allowed: false
```

Raw Score 只能解释为模型排序或相对强度，不得解释为真实事件频率。

## 5. Calibrated Prediction Contract

只有 M3 有有效 Calibration Profile 时：

```yaml
reader_outcome_prediction:
  prediction_id: PRED-...
  chapter_version_id: CHV-...
  reader_segment_version_id: SEG-...
  judge_profile_version_id: JP-...
  calibration_profile_version_id: CAL-...

  raw_scores:
    completion_score: 0.88
    next_chapter_score: 0.76

  calibrated_probabilities:
    chapter_completion_probability: 0.84
    next_chapter_open_probability: 0.71

  calibration_status: BEHAVIOR_CALIBRATED
  production_decision_allowed: true
```

长程 Outcome 不由单章 Judge 单独输出。

## 6. Prediction Scope 分层

### 6.1 Chapter-local

```text
chapter_completion
next_chapter_open
immediate_dissatisfaction
fast_drop
hook_trust_risk
```

### 6.2 Sequence-level

```text
three_chapter_retention
ten_chapter_retention
thirty_chapter_retention
```

Sequence Forecaster 必须消费：

- 多章 Score / Prediction Trend；
- Story State；
- Chapter Types；
- Book / Volume / Group Progress；
- 真实行为，若有；
- Exposure Context。

### 6.3 Book-level

```text
volume_completion
post_payment_retention
long_term_follow
book_abandonment
completion_tendency
```

Book-level Prediction 不能只基于一个章节。

## 7. 不确定性与 OOD

第一阶段不允许单个 LLM直接输出精确的：

```text
epistemic_uncertainty = 0.15
aleatoric_uncertainty = 0.22
```

使用可验证代理：

```text
judge_disagreement
pairwise_position_sensitivity
segment_sample_coverage
calibration_sample_count
calibration_error
mutation_stability
human_disagreement
ood_distance
prediction_residual
```

OOD 信号：

- 未覆盖题材或平台；
- 极端章节长度；
- 新型叙事结构；
- Segment 样本不足；
- Feature 分布偏离；
- Judge 分歧异常；
- 与历史样本距离过大。

OOD 时：

```text
禁止自动 ACCEPT
允许 Shadow Score
允许 Human Review
允许合法 Experiment
```

## 8. Pairwise Judge

使用场景：

- Draft 与 Revision；
- 两个开篇或 Hook；
- 冲突提前与延后；
- 不同说明量；
- 付费点变体；
- 高风险章节候选。

协议：

```text
Round 1: A / B
Round 2: B / A
Round 3: blinded canonical order
```

输出：

- Overall Winner；
- Dimension Winner；
- Evidence / Counter Evidence；
- Position Stability；
- Raw Outcome Difference；
- Human Test Recommendation；
- Experiment Value。

聚合：

```text
HIGH_STABILITY
MEDIUM_STABILITY
POSITION_SENSITIVE
TIE
ARBITRATION_REQUIRED
```

## 9. Quality Rule Registry

规则必须版本化：

```yaml
quality_rule_version:
  rule_id: protagonist_agency
  version: 3
  dimension: character
  applicability:
    chapter_types: [opening, normal, climax, payoff]
    excluded_types: [antagonist_pov]
  severity_policy:
    blocker: 连续两章无有效选择且主角为核心视角
    warning: 单章偏弱
  required_outputs:
    - evidence_spans
    - counter_evidence
    - applicability
    - confidence_band
  calibration_state: MACHINE_VALIDATED
```

状态：

```text
DRAFT
→ MODEL_AUDITED
→ MUTATION_VALIDATED
→ HUMAN_ANCHORED
→ BEHAVIOR_VALIDATED
→ ACTIVE
→ DEPRECATED
```

规则注册表必须支持优先级、适用题材、章节类型、例外、互斥和覆盖，避免重复计分。

## 10. Calibration Center

### 10.1 层级

```text
Global
→ Platform
→ Genre
→ Chapter Type
→ Reader Segment
→ Book-specific adjustment
```

选择最具体且样本充分的 Profile；不足则逐级回退。

### 10.2 Calibration Profile

```yaml
calibration_profile:
  profile_id: CAL-...
  outcome_target: next_chapter_open_probability
  platform: tomato
  genre: eastern_fantasy
  chapter_type: normal
  reader_segment_version_id: SEG-...
  judge_profile_version_id: JP-...
  feature_schema_version: narrative-feature-v1
  dataset_snapshot_id: CDS-...
  sample_count: 12840
  calibration_method: isotonic
  expected_calibration_error: 0.031
  brier_score: 0.142
  status: ACTIVE
```

### 10.3 冷启动阶段

M1：

```text
LLM Raw Score
+ Mutation Test
+ Pairwise Stability
→ MACHINE_VALIDATED
```

M2：

```text
Human Pairwise Anchor
→ HUMAN_ANCHORED
```

注意：Human Anchor 可以改善排序和 Band，但不等于真实行为概率校准。

M3：

```text
Exposure + Outcome
→ Platt / Isotonic / Beta Calibration
→ BEHAVIOR_CALIBRATED
```

M4：

```text
Randomized Experiment
→ CAUSAL_VALIDATED
```

### 10.4 指标

- Brier Score；
- Log Loss；
- Expected Calibration Error；
- AUROC / PR-AUC；
- Pairwise Accuracy；
- Kendall / Spearman；
- Top-K Lift；
- Segment Worst-group Error；
- OOD Error；
- Temporal Drift Error。

### 10.5 Promote

必须满足：

- Dataset Snapshot 冻结；
- 无测试集泄漏；
- 优于 Active Baseline；
- 关键 Segment 不退化；
- 回归通过；
- 可回滚；
- Approval Policy 满足。

## 11. Human Anchor

人工主要提供少量高价值真值：

- A/B 哪个更愿意继续读；
- 是否愿意付费；
- Revision 是否真正更好；
- Judge 是否误用规则；
- 不继续阅读的主要原因。

优先样本：

- Judge 分歧最大；
- 门槛附近；
- OOD；
- 新题材和平台；
- 开篇、付费点、高潮和结局；
- 真实结果与预测相反；
- 多轮修订仍不稳定。

起步 `60—100` 组只能作为 Pilot，不得声称覆盖所有平台和题材。

标注质量控制：

- 隐藏模型和版本来源；
- 随机交换 A/B；
- 重复样本和注意力检测；
- 评审一致性；
- 限制单评审权重；
- 记录 Segment；
- 异常评审降权而非静默删除。

## 12. Mutation 与 Metamorphic Test

Mutation 验证 Judge 是否发现已知问题，而不是是否会写专业报告。

目录：

- 连续性：时间、地点、物品、伤势、战力、世界规则；
- 人物：动机突变、主角被动、Voice 漂移、关系错误；
- 结构：目标、转折、因果和状态变化缺失；
- 商业：兑现删除、假 Hook、奖励延迟、说明膨胀；
- 文风：套话、反复、过度总结、句式同质。

变形测试要求：

```text
只注入时间线错误
→ Continuity 显著下降
→ Prose / Originality 不应同步大幅下降
```

指标：

```text
Mutation Recall
Mutation Precision
Evidence Localization Accuracy
Severity Accuracy
False Positive Rate
Repair Confirmation Rate
Cross-Dimension Leakage
```

## 13. Prompt 和结构化输出

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

每条问题必须包含：

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
- 使用未提供的真实读者数据；
- 把模拟反应写成事实；
- 把 Raw Score 写成 Calibrated Probability；
- 缺少 Segment 的全局断言。

Schema 必须支持完整 JSON Schema：enum、items、oneOf / anyOf、bounds、pattern、nested required 和 `additionalProperties=false`。

## 14. 验收

M1 至少达到：

- Blocker Mutation Recall 目标；
- Evidence Span 可定位；
- Pairwise A/B 与 B/A 稳定；
- OOD 样本自动决策率为 0；
- Raw Score 与 Probability 语义严格分离；
- Segment Fallback 可验证；
- Provider / Process Receipt 可追溯；
- Fixture 与真实执行明确区分。