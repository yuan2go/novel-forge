# Reader Outcome Judge（ROJ）完整设计蓝图

> 文档类型：目标态产品蓝图与工程实施规范  
> 所属系统：Quality / Review / Eval OS  
> 目标分支：`feat/v7-content-intelligence-and-longform-proof`  
> 建议模块：`reader_outcome_authority`  
> 更新日期：2026-07-22  
> 文档状态：`ACTIVE TARGET DESIGN`，不代表已经实现或通过生产验证

## 0. 文档目的

Reader Outcome Judge（ROJ）用于把 Novel Forge 从“模型认为章节写得不错”升级为：

```text
在明确平台、题材、章节类型和 Reader Segment 下
→ 对读者结果产生可验证预测或排序
→ 明确不确定性和适用范围
→ 使用人工偏好和真实行为逐级校准
→ 为发布、修订、实验和暂停提供证据
```

ROJ 不等于普通 Quality Score，也不把 LLM 自报概率当作真实读者概率。

## 1. 当前事实边界

当前可复用基础：

- PostgreSQL Authority、Operation、Saga、Attempt、Lease、Fencing、Audit、Outbox；
- Chapter Authority 的 Draft、Review、Revision、Canon、五组 Quality、Publish Gate、Export 和 Final Release Gate；
- Quality Provider 的 `calibration_status` 基础；
- Golden Sample、Human Decision、Evaluation Center 和 Reader Feedback 的部分概念。

当前不得声称：

```text
reader_outcome_judge_implemented = false
human_preference_anchored = false
real_reader_behavior_connected = false
behavior_calibrated = false
causal_experiment_validated = false
production_autonomy_approved = false
```

## 2. 系统定位

ROJ 属于：

```text
Quality / Review / Eval OS
├─ Intrinsic Quality Judge
├─ Reader Outcome Judge
├─ Calibration Center
├─ Experiment Center
└─ Decision Policy Engine
```

边界：

- Reader Simulation：缺少真实数据时模拟可能反应；
- Reader Outcome Judge：输出可校准的读者结果 Score / Prediction；
- Reader Feedback / Analytics：采集真实 Exposure 和 Outcome；
- Calibration Center：把 Raw Score 映射为可信概率；
- Experiment Center：验证修订或变体是否造成因果提升；
- Decision Policy：综合硬门禁、质量、读者结果、风险和预算形成建议。

ROJ 不新建顶级 OS，不取代 Canon、Originality、Safety 和 Platform Compliance。

## 3. 核心目标

ROJ 分阶段回答：

### M0/M1 可回答

- 章节对指定 Segment 的相对吸引力；
- 本章完成和下一章点击的 Raw Score；
- 主要正负驱动和 Evidence Span；
- 两个版本的 Pairwise Preference；
- Judge 分歧、位置敏感和 OOD；
- 是否应进入人工审阅或 Shadow 实验。

### M2 可回答

- 与目标读者和编辑盲测的一致性；
- Human Anchored Rank / Band；
- 哪些问题是模型偏好而非目标读者偏好。

### M3 才允许回答

- 经过真实行为校准的章节完成、下一章打开和留存概率；
- 分平台、题材、章节类型和 Segment 的可靠性；
- 预测残差和 Drift。

### M4 才允许回答

- 某个修订或变体是否造成因果提升；
- 是否值得 Promote；
- Guardrail 是否被破坏。

## 4. 非目标

ROJ 不负责：

- 直接生成正文；
- 取代 Topic、World、Character、Planning Generator；
- 修改 Canon；
- 以商业预测覆盖硬质量门禁；
- 根据单次点击或评论自动重写整本书；
- 使用未经授权的敏感个人数据；
- 把付费率定义为唯一目标；
- 在没有校准证据时声称“精品已验证”。

## 5. 四层结果目标

### A. Intrinsic Quality

- Canon、时间线、人物和世界规则一致；
- 因果和人物选择可信；
- 不抄袭、不泄漏来源表达；
- 无严重注水、重复和 AI 套话。

### B. Immediate Outcome

- 章节打开；
- 有效阅读；
- 章节完成；
- 退出位置；
- 下一章打开；
- 快速跳读和即时不满。

### C. Long-term Outcome

- 3 / 10 / 30 章留存；
- 次日 / 七日回访；
- 收藏、追更和卷完成；
- 完本倾向。

### D. Commercial and Trust

- 付费墙到达；
- 首次付费；
- 付费后继续阅读；
- 退款、投诉和负反馈；
- 假钩子、承诺违约和读者信任。

短期指标不得覆盖长期留存、读者信任和硬质量约束。

## 6. 总体架构

```text
Chapter Authority / Book Authority
→ Intrinsic Quality Evidence
→ ROJ Shadow Sidecar
   ├─ Narrative Feature Extractor
   ├─ Segment Resolver
   ├─ Outcome Judge / Pairwise Judge
   ├─ Disagreement / OOD
   ├─ Calibration Resolver
   └─ Advisory Decision Policy
→ Reader Feedback / Exposure / Outcome
→ Calibration Center
→ Experiment Center
→ Promote / Revoke / Drift Downgrade
```

第一阶段 ROJ 不进入 Chapter Completion Contract，不阻断 Publish Gate。

## 7. 分阶段生产权限

```text
ROJ-M0 RULE_DEFINED
ROJ-M1 MACHINE_VALIDATED
ROJ-M2 HUMAN_ANCHORED
ROJ-M3 BEHAVIOR_CALIBRATED
ROJ-M4 CAUSAL_VALIDATED
ROJ-M5 BOUNDED_PRODUCTION_AUTONOMY
```

权限：

| 成熟度 | 输出 | 生产权限 |
|---|---|---|
| M0 | Schema / Rule | 无 |
| M1 | Raw Score / Pairwise / OOD | Shadow Only |
| M2 | Human Anchored Advisory | Advisory / Human Review |
| M3 | Calibrated Probability | 低风险 Policy 输入 |
| M4 | Causal Experiment Result | Controlled Promote |
| M5 | Bounded Decision | 有限自动 ACCEPT / EXPERIMENT |

Novel Forge 声称真实读者结果已验证前至少达到 M3；允许自动内容优化前至少达到 M4。

## 8. 关键语义约束

### 8.1 Raw Score 不等于 Probability

未校准输出：

```yaml
raw_scores:
  completion_score: 0.82
  next_chapter_score: 0.74
ordinal_band: HIGH
calibrated_probabilities: null
calibration_status: UNCALIBRATED
```

只有存在行为校准 Profile 时才允许：

```yaml
calibrated_probabilities:
  completion_probability: 0.79
  next_chapter_open_probability: 0.68
calibration_status: BEHAVIOR_CALIBRATED
```

### 8.2 可观测不确定性

第一阶段只使用：

- Judge Disagreement；
- Pairwise Position Sensitivity；
- Segment Sample Coverage；
- OOD Distance；
- Mutation Stability；
- Human Disagreement；
- Calibration Sample Size；
- Prediction Residual。

不得由单个 LLM 凭空声称精确的 Aleatoric / Epistemic Uncertainty。

### 8.3 Chapter-local 与 Long-window 分离

Chapter-local Judge：

- Completion Score / Probability；
- Next Chapter Score / Probability；
- Immediate Dissatisfaction；
- Hook / Trust Risk。

Sequence / Book Forecaster：

- 3 / 10 / 30 章留存；
- 卷完成；
- 付费后留存；
- 长期追读。

长程预测必须消费历史趋势、真实行为和 Book State，不能只根据一个章节输出。

## 9. 组件边界

### Narrative Feature Extractor

将正文、ChapterPlan 和 Longform State 转换为版本化特征，不做最终价值判断。

### Outcome Judge

针对 Reader Segment 输出 Raw Score 或已校准 Prediction，不覆盖硬质量门禁。

### Pairwise Judge

盲测两个版本，并通过 A/B、B/A 和固定顺序检测位置偏差。

### Calibration Resolver

按 Platform、Genre、Chapter Type、Segment 和 Judge Profile 选择最具体且样本充分的 Calibration Profile。

### Decision Policy Engine

综合：

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

### Experiment Center

只在平台或私有测试环境具备合法随机分流能力时声称因果实验。

### Drift Monitor

发现模型、规则、平台或读者变化时，自动禁用生产 ACCEPT 并降级到 Shadow。

## 10. 文档分册

- [Authority 与生产链接入](01-authority-and-production-integration.md)
- [Judge 契约、特征与校准](02-judge-contracts-and-calibration.md)
- [读者反馈、实验与权威契约](03-feedback-experiments-and-authority-contracts.md)
- [模型治理、测试、成熟度与实施路线](04-model-governance-testing-and-roadmap.md)

## 11. 最终证据边界

只有同时满足以下条件，才允许设置：

```text
reader_outcome_judge_proven = true
```

最低要求：

1. 真实 ExecutionBackend 完成结构化 Judge 调用；
2. Judge Run、Usage、Cost 和 Trace 可追溯；
3. Mutation 和 Pairwise 回归通过；
4. 具有目标读者 Human Anchor；
5. Prediction 与 Exposure / Outcome 闭环；
6. 概率经过真实行为校准；
7. OOD、Drift 和人工覆盖有效；
8. 至少一次合法受控随机实验；
9. 新 PostgreSQL Authority 下完成 10 / 30 章趋势验收；
10. 不使用 Fixture、Mock 或 Scripted Result 冒充真实证据。