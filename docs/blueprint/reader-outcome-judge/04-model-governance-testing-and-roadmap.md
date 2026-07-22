# Reader Outcome Judge：模型治理、测试与实施路线

> 返回：[Reader Outcome Judge 总览](README.md)

# 26. Provider 与模型策略

## 26.1 第一阶段

不训练专用模型，采用：

```text
强 LLM Judge
+ 严格结构化输出
+ 多角色职责隔离
+ Pairwise 换位
+ Mutation Test
+ 简单统计校准
```

## 26.2 第二阶段

```text
LLM raw prediction
+ Narrative Features
+ Segment / Platform Features
+ Logistic / GBDT / Calibration Model
→ calibrated outcome probability
```

## 26.3 第三阶段

可评估：

- 文本 embedding；
- 多任务结果模型；
- 生存分析处理长期留存与 censoring；
- 分层模型处理平台、题材和书级差异；
- uplift model 预测“某修订是否真正改善结果”。

## 26.4 职责隔离

- 正文生成模型不得单独担任最终 Judge；
- 同一 Provider 可以用于不同角色，但 Profile、Prompt、上下文必须隔离；
- Judge 不得看到真实结果标签；
- 测试集不得进入 Prompt 示例；
- Provider 真实调用、usage、cost、latency 必须通过 ExternalEffect 保存。

## 26.5 降级策略

```text
Primary Judge unavailable
→ Secondary Judge
→ deterministic quality-only mode
→ insufficient evidence
→ human review / pause
```

不得使用 fixture 冒充真实 Judge。

---

# 27. Prompt 与结构化输出规范

## 27.1 输入分区

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

## 27.2 证据要求

每条问题必须包含：

- claim；
- applicability；
- evidence span；
- counter evidence；
- severity；
- confidence；
- uncertainty；
- recommended action。

## 27.3 禁止输出

- 无证据总分；
- 只写“节奏较好”；
- 使用未提供的真实读者数据；
- 把模拟读者反应写成真实事实；
- 把 raw probability 写成 calibrated probability；
- 缺少 Segment 的全局断言。

## 27.4 Schema 验证

生产实现必须使用完整 JSON Schema 验证能力，不能只依赖当前 Kernel 的基础类型检查。需支持：

- enum；
- arrays/items；
- oneOf / anyOf；
- number bounds；
- string pattern；
- required nested fields；
- additionalProperties=false；
- schema version。

---

# 28. 不确定性与 OOD

## 28.1 不确定性分类

- Epistemic：模型或数据不足；
- Aleatoric：读者天然差异；
- Judge disagreement：多个 Judge 不一致；
- Calibration uncertainty：Profile 样本不足；
- OOD：题材、平台、章节类型或文本分布超出训练范围。

## 28.2 OOD 信号

- 未知题材；
- 未覆盖平台；
- 极端章节长度；
- 新型叙事结构；
- Segment 样本不足；
- Narrative Feature 分布偏离；
- Judge 置信度异常集中；
- 与相似历史样本距离过大。

## 28.3 权限策略

OOD 时：

```text
禁止全自动 ACCEPT
允许 Shadow Prediction
允许 EXPERIMENT
优先 HUMAN_REVIEW
```

---

# 29. Anti-Goodhart 与读者信任

## 29.1 风险

只优化下一章点击会诱导：

- 假钩子；
- 强行断章；
- 拖延答案；
- 过度反转；
- 重复刺激；
- 付费前故意压缩兑现；
- 付费后快速崩塌。

## 29.2 Trust Metrics

```text
false_hook_rate
promise_default_rate
post_payment_fast_drop_rate
excessive_cliffhanger_rate
repeated_stimulation_rate
title_content_mismatch_rate
reader_complaint_rate
```

## 29.3 策略约束

- 下一章点击提高但十章留存下降：不得 Promote；
- 付费提高但付费后留存下降：默认失败；
- 强刺激变体造成投诉显著上升：Guardrail fail；
- 修订提升商业指标但破坏人物或 Canon：硬失败。

---

# 30. Drift 管理

## 30.1 漂移来源

- Judge 模型升级；
- Prompt 更新；
- Quality Rule 更新；
- 平台推荐变化；
- 读者偏好变化；
- 新题材；
- 价格和付费策略变化；
- 书籍生命周期变化。

## 30.2 监控

- 预测分布；
- 校准误差；
- Segment worst-group；
- Judge disagreement；
- OOD 比例；
- 人工覆盖率；
- 预测与真实结果残差；
- 特征分布。

## 30.3 自动降级

```text
Drift detected
→ Mark profile DEGRADED
→ Disable automatic ACCEPT
→ Enter Shadow Mode
→ Freeze new calibration dataset
→ Recalibrate
→ Regression test
→ Promote or Revoke
```

---

# 31. 可观测性

## 31.1 Trace

每次 Judge Run 必须记录：

- operation_id；
- saga_id；
- attempt_id；
- provider_request_id；
- judge type；
- model；
- prompt version；
- input hash；
- output hash；
- usage；
- cost；
- latency；
- calibration profile；
- decision policy；
- result status。

## 31.2 Dashboard

最小 Authority Cockpit：

1. Chapter Outcome Timeline；
2. Segment Prediction Matrix；
3. Raw vs Calibrated Probability；
4. Quality Blocker；
5. Judge Disagreement；
6. Experiment Status；
7. Human Review Queue；
8. Calibration Health；
9. Drift Alerts；
10. Cost and Latency。

## 31.3 告警

- Provider invalid output；
- Calibration missing；
- OOD spike；
- Judge disagreement spike；
- Event ingestion lag；
- Experiment SRM；
- 预测和真实结果背离；
- 付费后留存异常下降；
- 成本超预算。

---

# 32. 失败、重试与恢复

## 32.1 Judge Provider 失败

- 使用 ExternalEffect request identity；
- query/cancel/reconcile；
- 网络未知状态不得直接重发；
- 输出非法可按策略重试；
- 超过次数进入 manual intervention。

## 32.2 事件延迟

- Outcome Window 支持延迟到达；
- Aggregate 可重算；
- 迟到事件触发新 aggregate version；
- 已 Promote 的实验如受重大修正影响，生成审计告警，不静默改写。

## 32.3 Calibration 失败

- Active Profile 保持不变；
- Candidate 标记 FAILED；
- 不允许半完成 Promote；
- 失败报告进入 Eval Center。

## 32.4 Experiment Worker 崩溃

- Assignment 由数据库权威保存；
- 重启后按 assignment 恢复；
- 不重复分组；
- Metric 可从事件重建。

---

# 33. 安全、隐私与合规

## 33.1 最小数据原则

- Reader ID 匿名化或假名化；
- 只记录实现结果分析所需数据；
- 不收集无关敏感属性；
- Segment 使用统计群体；
- 支持删除、撤回和数据保留策略；
- 平台 Adapter 必须遵守平台协议。

## 33.2 内容隔离

- 参考原文不得进入 Outcome Judge；
- Judge 只读取抽象规则和必要上下文；
- 防止 Prompt Injection；
- 外部反馈文本视为不可信输入；
- 评论内容需要清洗后再进入分析。

## 33.3 审计

每个发布决策必须可回答：

- 哪个章节版本；
- 哪个 Segment；
- 哪个 Judge；
- 哪个 Prompt；
- 哪套规则；
- 哪个 Calibration Profile；
- 哪些证据；
- 为什么做出该决策；
- 是否被人工覆盖。

---

# 34. 管理界面

## 34.1 Reader Segment Console

- Segment 定义；
- 样本量；
- 校准状态；
- 合并 / 废弃；
- Outcome coverage。

## 34.2 Judge Workbench

- 章节文本与 evidence span；
- 多 Judge 结果；
- 反证；
- Pairwise 换位；
- 人工覆盖。

## 34.3 Calibration Center

- Dataset Snapshot；
- Profile 对比；
- Reliability Diagram；
- Segment worst-group；
- Promote / Revoke；
- Drift。

## 34.4 Experiment Console

- 假设；
- 变体；
- 分流；
- Primary / Guardrail；
- SRM；
- 观察窗口；
- Promote。

## 34.5 Book Outcome Review

- 3 / 5 / 10 / 30 章趋势；
- 预测与真实结果；
- 付费前后；
- 承诺与兑现；
- Plan Adjustment 建议。

---

# 35. Eval 与测试体系

## 35.1 单元测试

- schema；
- policy；
- Segment fallback；
- calibration resolution；
- event dedup；
- outcome window；
- experiment assignment；
- version binding。

## 35.2 集成测试

- PostgreSQL Authority admission；
- Saga forward recovery；
- Provider invalid output；
- callback；
- cancel；
- retry / fencing；
- outbox；
- human approval resume；
- experiment recovery。

## 35.3 Judge 回归集

```text
Golden Human Preference
Mutation Cases
Pairwise Cases
OOD Cases
Adversarial Cases
Longform Cases
Platform Cases
```

## 35.4 端到端验收

### E2E-1 Shadow Single Chapter

```text
真实 ChapterVersion
→ 五组 Quality
→ Outcome Prediction
→ Decision Report
→ 不影响发布
```

### E2E-2 Human Anchored Pairwise

```text
两个版本
→ Judge 比较
→ 人工盲测
→ 一致性报告
```

### E2E-3 Behavior Calibration

```text
Prediction
→ Exposure
→ Outcome Event
→ Aggregate
→ Calibration
```

### E2E-4 Controlled Experiment

```text
Variant A/B
→ Random Assignment
→ Outcome Window
→ Analysis
→ Guardrail
→ Promote / Inconclusive
```

### E2E-5 10/30 Chapter Trend

在新 PostgreSQL Authority 下验证：

- 每章预测；
- 书级趋势；
- 复盘；
- Plan Adjustment；
- 性能；
- 恢复；
- 漂移与成本。

---

# 36. 成熟度模型

```text
ROJ-M0 RULE_DEFINED
ROJ-M1 MACHINE_VALIDATED
ROJ-M2 HUMAN_ANCHORED
ROJ-M3 BEHAVIOR_CALIBRATED
ROJ-M4 CAUSAL_VALIDATED
ROJ-M5 BOUNDED_PRODUCTION_AUTONOMY
```

## M0

有规则和输出 schema，但未验证。

## M1

完成：

- 多 Judge；
- Mutation Test；
- Pairwise 换位；
- 回归集。

## M2

完成目标读者和编辑的 Human Anchor。

## M3

预测概率经过真实曝光与行为校准。

## M4

随机实验能够证明修订或变体带来因果提升。

## M5

在明确平台、题材、Segment、章节类型和风险边界内，允许自动 ACCEPT / EXPERIMENT，并具备自动降级和人工覆盖。

Novel OS 在声称“真实读者结果已验证”前至少达到 M3；在允许自动内容优化前至少达到 M4。

---

# 37. 验收指标与建议门槛

以下是第一版工程目标，不是跨题材永久标准。

## 37.1 Intrinsic Judge

- Blocker Mutation Recall ≥ 0.90；
- Warning Mutation Recall ≥ 0.75；
- Evidence Localization Accuracy ≥ 0.80；
- False Positive Rate ≤ 0.15；
- 修订后盲测改善率显著高于 0.5；
- A/B 换位稳定率 ≥ 0.85。

## 37.2 Human Anchor

- Pairwise Human Agreement ≥ 0.70；
- 高置信度样本 Agreement ≥ 0.80；
- `CANNOT_JUDGE` 和低质量标注单独监控；
- Segment worst-group 不得严重退化。

## 37.3 Behavior Calibration

- 相对 baseline 改善 Brier / Log Loss；
- ECE 达到预设门槛；
- 十章留存预测优于简单题材均值 baseline；
- 付费后留存预测不能仅依赖付费转化；
- OOD 样本自动决策率为 0。

## 37.4 生产

- 预测记录可追溯率 100%；
- Exposure 到 ChapterVersion 绑定率 100%；
- 重复事件不重复计数；
- 自动决策均有 policy version；
- 人工覆盖均有审计；
- Calibration Promote 可回滚；
- Provider usage / cost / latency 有真实回执。

---

# 38. 实施目录建议

```text
src/novel_forge/modules/reader_outcome_authority/
├── __init__.py
├── application.py
├── contracts.py
├── models.py
├── repository.py
├── service.py
├── scheduler.py
├── handlers.py
├── codecs.py
├── policies.py
├── calibration.py
├── experiments.py
├── drift.py
└── ports.py

src/novel_forge/modules/reader_feedback/
├── adapters/
├── ingestion.py
├── aggregation.py
└── contracts.py

tests/unit/reader_outcome_authority/
tests/integration/test_reader_outcome_authority_postgres.py
tests/integration/test_reader_outcome_chapter_slice.py
tests/integration/test_reader_outcome_calibration.py
tests/integration/test_reader_outcome_experiment.py
tests/acceptance/test_reader_outcome_shadow_real_provider.py
```

第一阶段可将 Chapter 节点适配器留在 `chapter_authority`，但领域和校准逻辑不得写死在 Handler 中。

---

# 39. 分阶段实施路线

## Phase 0：契约和数据底座

交付：

- 领域模型；
- JSON Schema；
- PostgreSQL migrations；
- Command Definitions；
- Repository；
- Asset types；
- 权威状态和审计。

验收：所有预测、版本、Segment 和决策可追溯。

## Phase 1：Machine-Validated Judge

交付：

- Feature Extractor；
- Outcome Judge；
- Pairwise；
- Adversarial；
- Arbitration；
- Mutation Dataset；
- 回归测试；
- Shadow Mode。

达到：`ROJ-M1`。

## Phase 2：Human Anchor

交付：

- 标注任务和界面；
- 60–100 组起步 Pairwise；
- Reader Segment v1；
- 人工一致性；
- Human Calibration Profile。

达到：`ROJ-M2`。

## Phase 3：真实行为接入

交付：

- Platform / private reader test adapter；
- Exposure；
- Outcome Event；
- 窗口聚合；
- Shadow Prediction 对比；
- 概率校准。

达到：`ROJ-M3`。

## Phase 4：因果实验

交付：

- Chapter Variant；
- Random Assignment；
- SRM；
- Primary / Guardrail；
- Experiment Analysis；
- Promote / Revoke。

达到：`ROJ-M4`。

## Phase 5：有限生产自治

交付：

- Decision Policy 自动化；
- Book Authority 趋势暂停；
- Drift 自动降级；
- 人工覆盖；
- 10/30 章验收。

达到：`ROJ-M5`。

---

# 40. Work Package 拆分

## WP-ROJ-0：Evidence Boundary

- 冻结本文状态定义；
- 清理“模型评分等于真实读者验证”的文档表述；
- 建立 maturity flags。

## WP-ROJ-1：Domain and Schema

- ReaderSegment；
- OutcomePrediction；
- CalibrationProfile；
- Exposure / OutcomeEvent；
- Decision；
- Experiment。

## WP-ROJ-2：Authority Core

- Command catalog；
- PostgreSQL repository；
- Saga；
- Attempt / lease / retry；
- outbox。

## WP-ROJ-3：Chapter Integration

- READER_OUTCOME node；
- DECISION_POLICY node；
- Publish Gate 输入扩展；
- Shadow Mode。

## WP-ROJ-4：Machine Validation

- Feature extractor；
- Pairwise；
- Mutation；
- Adversarial；
- 回归集。

## WP-ROJ-5：Human Anchor

- Annotation workbench；
- sample selection；
- vote quality；
- calibration。

## WP-ROJ-6：Behavior Pipeline

- exposure；
- event ingestion；
- aggregation；
- outcome windows；
- late events。

## WP-ROJ-7：Experiment Center

- variants；
- assignment；
- metrics；
- guardrails；
- promote。

## WP-ROJ-8：Book Integration

- 5/10/卷复盘；
- trend；
- pause proposal；
- plan adjustment。

## WP-ROJ-9：Production Proof

- real Provider；
- Human Anchor；
- behavior calibration；
- controlled experiment；
- 10/30 chapter proof。

---

# 41. 当前实现与目标差距

| 能力 | 当前基线 | 目标 |
|---|---|---|
| 五组 Quality | 已有 | 证据化、校准、分群 |
| Provider Quality | `PROVIDER_UNCALIBRATED` | Calibration Profile |
| Quality Aggregate | 已有 | 消费 Outcome Prediction |
| Reader Segment | 未形成权威闭环 | 版本化 Segment |
| Outcome Prediction | 未实现完整闭环 | 概率向量 + uncertainty |
| Human Anchor | 部分概念 | 可执行标注与校准 |
| Reader Exposure | 未形成权威模型 | append-only exposure |
| Outcome Event | 未形成完整生产链 | 幂等事件与窗口聚合 |
| A/B Experiment | 未形成 Authority | 随机分配和因果验证 |
| Decision Policy | Publish Gate 基础 | 多目标版本化策略 |
| Drift | 未闭环 | 自动降级、recalibrate |
| 真实生产证据 | 未完成 | M3/M4/M5 分级证明 |

---

# 42. 明确后置项

第一阶段暂不实现：

- 实时单读者个性化正文；
- 强化学习直接控制生成模型；
- 多平台统一用户 ID；
- 复杂深度学习推荐系统；
- 多模型成本最优路由；
- 全自动发布；
- 多书流量自动分配；
- 无人工边界的 A5 自治。

---

# 43. 关键架构决策

## ADR-ROJ-001

ROJ 属于 Quality / Review / Eval OS，不新建顶级 OS。

## ADR-ROJ-002

Quality Audit、Outcome Prediction、Decision Policy 三者分离。

## ADR-ROJ-003

真实行为是最终校准信号，大模型输出不是最终真值。

## ADR-ROJ-004

所有概率必须绑定 Reader Segment、ChapterVersion、JudgeProfile 和 CalibrationProfile。

## ADR-ROJ-005

所有生产状态使用 PostgreSQL Authority；LocalStorage 仅限兼容、导入导出或测试。

## ADR-ROJ-006

第一阶段默认 Shadow Mode，不直接自动发布。

## ADR-ROJ-007

短期点击、付费不得覆盖长期留存、读者信任和硬质量门禁。

## ADR-ROJ-008

OOD 或 Calibration 不足时必须拒绝伪确定结论。

---

# 44. 最终验收声明

只有满足以下证据时，才允许设置：

```text
reader_outcome_judge_proven=true
```

最低要求：

1. 真实 Provider 完成结构化 Judge 调用；
2. Judge Run、usage、cost、trace 可追溯；
3. Mutation 和 Pairwise 回归通过；
4. 具有目标读者 Human Anchor；
5. Prediction 与 Exposure、Outcome 可以闭环；
6. 概率完成真实行为校准；
7. OOD、漂移和人工覆盖有效；
8. 至少一次受控随机实验完成；
9. 新 PostgreSQL Authority 下完成 10/30 章趋势验收；
10. 不存在以 fixture、mock 或 scripted result 代替真实证据的情况。

最终目标不是：

```text
模型认为这章很好
```

而是：

```text
在明确的平台、题材、章节类型和读者群体下，
系统能够给出经过真实行为校准的继续阅读、追更、付费和长期留存概率，
同时满足原创性、连续性、叙事质量和读者信任约束，
并能在不确定、漂移或高风险时自动降级、实验或请求人工决策。
```
