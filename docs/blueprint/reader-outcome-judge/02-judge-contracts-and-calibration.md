# Reader Outcome Judge：Judge 契约、特征与校准

> 返回：[Reader Outcome Judge 总览](README.md)

# 9. Judge 角色体系

## 9.1 Continuity Judge

负责：

- Canon；
- 时间线；
- 人物状态；
- 地点；
- 物品；
- 战力；
- 世界规则。

优先使用确定性规则与结构化状态，LLM 负责语义冲突补充。

## 9.2 Narrative Structure Judge

负责：

- 场景目标；
- 冲突；
- 转折；
- 因果；
- 信息释放；
- 情绪曲线；
- 章节功能；
- 场景状态变化。

## 9.3 Character Judge

负责：

- 主角能动性；
- 动机；
- 人设一致；
- 选择代价；
- 关系推进；
- 语言区分；
- 成长弧。

## 9.4 Commercial Fiction Judge

负责：

- 开篇压力；
- 阅读阻力；
- 读者承诺；
- 爽点；
- 钩子；
- 追读动力；
- 付费点；
- 移动端节奏；
- 毒点风险。

## 9.5 Prose Judge

负责：

- AI 套话；
- 同义反复；
- 过度总结；
- 说明性对白；
- 抽象情绪；
- 句式同质；
- 段落节奏；
- 文风漂移。

## 9.6 Longform Judge

负责：

- 章节间重复；
- 人物弧漂移；
- 伏笔债务；
- 承诺债务；
- 爽点疲劳；
- 设定膨胀；
- 中段塌陷；
- 主线模糊。

## 9.7 Outcome Judge

负责输出特定 Reader Segment 的行为概率，不负责覆盖硬质量门禁。

## 9.8 Adversarial Judge

只挑战结论：

- 规则是否适用；
- 是否存在反证；
- 是否忽略章节功能；
- 是否将风格差异误判为质量；
- 是否过度修改；
- 是否存在位置、长度或自偏好偏差。

## 9.9 Arbitration Judge

仅在下列条件启动：

- Judge 严重分歧；
- A/B 换位后结论改变；
- 接近发布门槛；
- 高价值章节；
- 质量赢家与商业赢家冲突；
- 多轮修订仍不稳定。

---

# 10. Narrative Feature Schema

## 10.1 原则

Narrative Feature 是解释与统计模型的桥梁。特征必须：

- 版本化；
- 可重算；
- 可追溯到文本 span 或状态资产；
- 不直接复制高风险参考表达；
- 不把 Judge 主观结论伪装成客观事实。

## 10.2 特征组

### 文本基础

```text
word_count
paragraph_count
sentence_length_distribution
dialogue_ratio
narration_ratio
unique_character_count
scene_count
```

### 冲突与行动

```text
conflict_entry_position
active_conflict_count
state_change_count
protagonist_effective_choice_count
irreversible_choice_count
cost_bearing_action_count
opponent_pressure_event_count
```

### 信息与认知

```text
new_information_count
repeated_information_ratio
exposition_density
mystery_question_created
mystery_question_resolved
information_asymmetry_count
```

### 情绪与兑现

```text
emotional_turn_count
positive_payoff_count
negative_cost_count
promise_created_count
promise_partially_fulfilled
promise_fulfilled_count
false_hook_risk
```

### 长篇连续性

```text
canon_conflict_count
character_state_delta_count
foreshadow_open_count
foreshadow_resolved_count
unresolved_debt_age
recent_trope_similarity
recent_scene_similarity
```

### 移动阅读

```text
long_paragraph_ratio
screen_break_density
opening_pressure_300_chars
first_major_state_change_position
ending_hook_type
ending_unresolved_state_count
```

## 10.3 输出示例

```yaml
narrative_feature_snapshot:
  schema_version: narrative-feature-v1
  chapter_version_id: CHV-0012-R2
  features:
    conflict_entry_position: 0.08
    protagonist_effective_choice_count: 2
    exposition_density: 0.17
    promise_partially_fulfilled: 1
    false_hook_risk: 0.04
  evidence:
    protagonist_effective_choice_count:
      - start: 1420
        end: 1633
        explanation: 主角拒绝既定任务并提出替代路径
```

---

# 11. Reader Segment 设计

## 11.1 冷启动 Segment

第一阶段仅使用人工定义的宽泛群体：

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
  payment_sensitivity: medium
  status: ACTIVE
```

## 11.2 分群维度

允许：

- 平台；
- 主、子题材；
- 阅读经验；
- 节奏偏好；
- 说明容忍度；
- 情绪浓度；
- 主角类型；
- 爽点频率；
- 付费敏感度；
- 连载长度偏好。

默认不使用精细敏感属性。

## 11.3 Segment 生命周期

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
- 置信度；
- 合并或废弃原因。

## 11.4 最小样本策略

样本不足时不得返回伪精确概率，必须：

- 回退到上级 Genre Segment；
- 回退到 Platform Segment；
- 输出 OOD / insufficient evidence；
- 建议 Shadow Mode 或人工测试。

---

# 12. Outcome Prediction Contract

## 12.1 目标向量

```text
chapter_completion_probability
next_chapter_open_probability
three_chapter_retention_probability
ten_chapter_retention_probability
thirty_chapter_retention_probability
follow_probability
favorite_probability
paywall_conversion_probability
post_payment_retention_probability
dissatisfaction_probability
reader_trust_damage_probability
```

不是每次都要求全部目标。目标由 `prediction_scope` 指定。

## 12.2 结构化输出

```yaml
reader_outcome_prediction:
  prediction_id: PRED-...
  chapter_version_id: CHV-...
  reader_segment_id: SEG-...
  judge_profile_id: JP-...
  calibration_profile_id: CAL-... | null
  prediction_scope: [completion, next_chapter, ten_chapter_retention]

  raw_predictions:
    completion_probability: 0.88
    next_chapter_open_probability: 0.76
    ten_chapter_retention_probability: 0.41

  calibrated_predictions:
    completion_probability: 0.84
    next_chapter_open_probability: 0.71
    ten_chapter_retention_probability: 0.36

  uncertainty:
    confidence: 0.78
    epistemic_uncertainty: 0.15
    aleatoric_uncertainty: 0.22
    out_of_distribution: false
    insufficient_evidence: false

  drivers:
    positive:
      - feature: protagonist_effective_choice_count
        effect: medium
        evidence_spans: []
    negative:
      - feature: exposition_density
        effect: low
        evidence_spans: []

  limitations:
    - 当前 Segment 的十章留存样本较少

  recommendation:
    decision: EXPERIMENT
    reason_code: LONG_TERM_UNCERTAINTY
```

## 12.3 预测真值隔离

Judge 请求中禁止提供：

- 当前版本真实 Outcome；
- 当前实验赢家；
- A/B 版本来源；
- 生成模型身份；
- 测试标签；
- 人工最终答案。

---

# 13. Pairwise Judge

## 13.1 使用场景

- Draft 与 Revision；
- 两个开篇版本；
- 两个钩子版本；
- 冲突提前与延后；
- 不同说明量；
- 付费点变体；
- 高风险章节候选。

## 13.2 三轮协议

```text
Round 1: A / B
Round 2: B / A
Round 3: blinded canonical order
```

聚合规则：

- 三轮一致：`HIGH_STABILITY`；
- 两轮一致：`MEDIUM_STABILITY`；
- 换位改变结论：`POSITION_SENSITIVE`；
- 结论和维度严重冲突：转 Arbitration；
- 差异低于最小效果：`TIE`。

## 13.3 输出

必须包含：

- overall winner；
- dimension winners；
- evidence；
- counter evidence；
- position stability；
- confidence；
- predicted outcome difference；
- 是否值得实验。

---

# 14. 质量规则注册表

## 14.1 QualityRuleVersion

```yaml
quality_rule_version:
  rule_id: protagonist_agency
  version: 3
  dimension: character
  description: 主角是否通过选择、行动或拒绝推动章节状态变化
  applicability:
    chapter_types: [opening, normal, climax, payoff]
    excluded_types: [antagonist_pov]
  positive_evidence: []
  negative_evidence: []
  exceptions: []
  severity_policy:
    blocker: 连续两章无有效选择且主角为核心视角
    warning: 单章偏弱
  required_outputs:
    - evidence_spans
    - counter_evidence
    - applicability
    - confidence
  calibration_state: MACHINE_VALIDATED
```

## 14.2 规则状态

```text
DRAFT
→ MODEL_AUDITED
→ MUTATION_VALIDATED
→ HUMAN_ANCHORED
→ BEHAVIOR_VALIDATED
→ ACTIVE
→ DEPRECATED
```

## 14.3 规则冲突

规则注册表必须支持：

- 优先级；
- 适用题材；
- 章节类型；
- 互斥规则；
- 覆盖关系；
- 例外；
- Blocker / Warning / Suggestion；
- 规则组合不重复计分。

---

# 15. Calibration Center

## 15.1 校准层级

```text
Global
→ Platform
→ Genre
→ Chapter Type
→ Reader Segment
→ Book-specific adjustment
```

优先使用最具体且样本充分的 Profile；不足则逐级回退。

## 15.2 Calibration Profile

```yaml
calibration_profile:
  profile_id: CAL-...
  outcome_target: next_chapter_open_probability
  platform: tomato
  genre: eastern_fantasy
  chapter_type: normal
  reader_segment_id: SEG-...
  judge_profile_id: JP-...
  feature_schema_version: narrative-feature-v1
  dataset_snapshot_id: CDS-...
  sample_count: 12840
  calibration_method: isotonic
  expected_calibration_error: 0.031
  brier_score: 0.142
  ranking_metric: 0.72
  status: ACTIVE
```

## 15.3 冷启动方法

第一阶段：

```text
LLM raw probability
+ 人工 Pairwise Anchor
+ Mutation Test
→ MACHINE_VALIDATED / HUMAN_ANCHORED
```

第二阶段：

```text
真实曝光与行为
→ Platt / Isotonic / Beta Calibration
→ BEHAVIOR_CALIBRATED
```

第三阶段：

```text
随机实验结果
→ 因果验证
→ CAUSAL_VALIDATED
```

## 15.4 推荐指标

- Brier Score；
- Log Loss；
- Expected Calibration Error；
- AUROC / PR-AUC；
- Pairwise Accuracy；
- Kendall / Spearman；
- Top-K Lift；
- Segment Worst-Group Error；
- OOD Error；
- Temporal Drift Error。

## 15.5 Promote 条件

Calibration Profile Promote 必须满足：

- 数据集冻结；
- 无测试集泄漏；
- 指标超过当前 Active Profile；
- 关键 Segment 不退化；
- 回归测试通过；
- 可回滚；
- 审批策略满足。

---

# 16. 人工锚点系统

## 16.1 人工不是全量审稿

人工主要提供少量高价值真值：

- A/B 哪个更愿意继续读；
- 是否愿意付费；
- 修订后是否真正更好；
- Judge 是否误用规则；
- 不继续阅读的主要原因。

## 16.2 样本选择

优先：

- Judge 分歧最大；
- 预测门槛附近；
- OOD；
- 新题材和新平台；
- 开篇、付费点、高潮、结局；
- 真实结果与预测相反；
- 模型或规则刚升级；
- 多轮修订仍不稳定。

## 16.3 标注协议

```yaml
human_preference_vote:
  assignment_id: HPA-...
  reviewer_type: target_reader | editor
  reader_segment_id: SEG-...
  version_a_id: CHV-A
  version_b_id: CHV-B
  preference: A | B | TIE | CANNOT_JUDGE
  continue_reading_intent: 1..5
  payment_intent: 1..5
  reason_codes: [pacing, protagonist, hook]
  free_text_reason: optional
  confidence: 0..1
```

## 16.4 人工质量控制

- 隐藏模型和版本来源；
- 随机交换 A/B；
- 插入重复样本；
- 插入注意力检测；
- 检测评审一致性；
- 限制单评审权重；
- 记录评审 Segment；
- 对异常评审降权而非静默删除。

---

# 17. 缺陷注入与变形测试

## 17.1 目的

Mutation Testing 验证 Judge 能否发现已知问题，而不是验证 Judge 是否会写专业报告。

## 17.2 缺陷目录

### 连续性

- 时间错误；
- 地点错误；
- 物品状态错误；
- 人物伤势错误；
- 战力越级；
- 世界规则冲突。

### 人物

- 动机突变；
- 主角被动化；
- 语言漂移；
- 能力遗忘；
- 关系状态错误。

### 结构

- 删除目标；
- 删除转折；
- 冲突延后；
- 因果断裂；
- 场景无状态变化。

### 商业

- 删除兑现；
- 弱化钩子；
- 假钩子；
- 奖励过度延迟；
- 说明量膨胀。

### 文风

- 套话注入；
- 同义反复；
- 过度总结；
- 句式同质；
- 抽象情绪替代动作。

## 17.3 变形测试

只改变一个维度时，相关指标应变化，无关指标不应大幅漂移。

例如：

```text
注入时间线错误
→ continuity 下降
→ prose / originality 不应显著下降
```

## 17.4 指标

```text
Mutation Recall
Mutation Precision
Evidence Localization Accuracy
Severity Accuracy
False Positive Rate
Repair Confirmation Rate
Cross-Dimension Leakage
```

Blocker 类型缺陷应设置更高检出标准。
