# Reader Outcome Judge（ROJ）完整设计蓝图

> 文档类型：目标态产品蓝图 + 工程实施规范  
> 所属系统：Autonomous Novel OS / Quality · Review · Eval OS  
> 目标分支：`feat/v7-content-intelligence-and-longform-proof`  
> 建议实现模块：`reader_outcome_authority` + Chapter Authority 集成  
> 文档状态：`TARGET_DESIGN`，不代表当前代码已实现或已通过生产验证

---

## 0. 文档目的与证据边界

本文定义 Reader Outcome Judge（下称 ROJ）的完整目标设计，用于解决以下核心问题：

> Novel OS 如何从“模型认为章节写得不错”，升级为“系统能够在明确读者群、平台和作品阶段下，预测真实读者继续阅读、追更、付费与长期留存，并持续用真实结果校准判断”。

本文同时承担：

1. 产品边界；
2. 领域模型；
3. Authority 架构；
4. Chapter / Book 生产链集成；
5. PostgreSQL 权威数据模型；
6. Command Kernel 操作目录；
7. Saga 与状态机；
8. Judge 模型与结构化输出协议；
9. 人工样本、缺陷注入和读者行为校准；
10. A/B 实验与因果验证；
11. 发布决策策略；
12. 测试、可观测性、恢复与验收标准；
13. 分阶段实施路线图。

### 0.1 当前代码基线

截至本文写入目标分支时，代码已经具备以下可复用基础：

- PostgreSQL Authority、Operation、Saga、Attempt、Lease、Fencing、Audit、Outbox；
- Chapter Authority 的 Draft、Review、Revision、Re-review、Canon、五组 Quality、Quality Aggregate、Publish Gate、Export、Final Release Gate；
- 五组 Quality：`structural`、`commercial`、`source_originality`、`longform`、`platform`；
- Quality Provider 输出中已经存在 `calibration_status`，但真实 Provider 结果仍会被标记为 `PROVIDER_UNCALIBRATED`；
- Quality evidence 当前仍明确标记 `production_verified=false`；
- Golden Sample、Human Decision、Calibration Profile 等概念已有部分基础，但尚未形成“真实读者结果预测 + 行为闭环 + 因果实验”的完整 ROJ。

主要代码参考：

```text
src/novel_forge/modules/chapter_authority/contracts.py
src/novel_forge/modules/chapter_authority/handlers.py
src/novel_forge/modules/chapter_authority/scheduler.py
src/novel_forge/modules/command_kernel/
docs/blueprint/autonomous-novel-os-full-blueprint.md
docs/blueprint/novel-os-project-blueprint.md
```

### 0.2 本文不作出的声明

本文不表示以下状态已经成立：

```text
reader_outcome_judge_implemented=true
human_preference_anchored=true
real_reader_behavior_connected=true
causal_experiment_validated=true
production_autonomy_approved=true
```

只有在对应验收证据完成后，才允许更新成熟度状态。

---

# 1. 系统定位

## 1.1 名称

```text
Reader Outcome Judge
读者结果判定系统
缩写：ROJ
```

## 1.2 所属层级

ROJ 不应被建设成新的顶级 OS。它属于：

```text
Quality / Review / Eval OS
├── Intrinsic Quality Judge
├── Reader Outcome Judge
├── Calibration Center
├── Experiment Center
└── Decision Policy Engine
```

ROJ 与 Reader Simulation Engine 不同：

- Reader Simulation Engine：在缺少真实读者数据时模拟可能反应；
- Reader Outcome Judge：预测并校准真实读者结果；
- Reader Feedback / Analytics：采集真实曝光和行为；
- Eval Center：验证 Judge 的准确性、稳定性和漂移；
- Decision Policy Engine：将质量、预测、风险与预算转换为发布决策。

## 1.3 核心定义

ROJ 是一个受 PostgreSQL Authority 管理的混合判定系统：

```text
文本和长篇状态
+ 结构化叙事特征
+ 目标读者群
+ 平台和曝光条件
+ 历史人工偏好
+ 历史真实行为
+ 校准配置
→ 结果概率向量
→ 不确定性
→ 证据解释
→ 发布 / 修订 / 实验 / 人工复核建议
```

## 1.4 核心价值

ROJ 解决五类错误：

1. **模型自洽错误**：生成模型和审核模型共享同一偏好，互相确认；
2. **规则代理错误**：满足钩子、爽点等形式规则，但真实读者仍弃读；
3. **短期指标透支**：下一章点击提高，但三章、十章或付费后留存下降；
4. **平均读者幻觉**：对所有读者给出一个平均分，掩盖题材和平台差异；
5. **置信度伪装**：没有足够数据仍强制输出确定结论。

---

# 2. 系统目标与非目标

## 2.1 核心目标

ROJ 必须能够回答：

1. 章节是否存在不可发布的硬质量问题；
2. 章节是否适合指定 Reader Segment；
3. 指定读者读完本章的概率；
4. 指定读者继续下一章的概率；
5. 三章、十章和卷级留存概率；
6. 关注、收藏、追更概率；
7. 付费转化概率；
8. 付费后继续阅读概率；
9. 不满意、快速流失和读者信任受损概率；
10. 两个候选版本哪个更可能产生长期正向结果；
11. 当前判断是否足够可信；
12. 当前内容应接受、修订、实验、人工复核、拒绝还是暂停全书。

## 2.2 非目标

ROJ 不负责：

- 直接生成正文；
- 取代 Topic、World、Character、Outline、ChapterPlan Generator；
- 取代 Canon Authority；
- 取代 Originality、Safety、Platform Compliance 硬门禁；
- 仅凭商业预测允许严重逻辑或原创性问题通过；
- 基于单次点击自动重写整本书；
- 为单个读者生成实时个性化正文；
- 使用未经授权的个人敏感数据进行精细画像；
- 将付费率定义为唯一质量目标；
- 在没有校准证据时声称“精品已验证”。

---

# 3. 精品与读者结果定义

## 3.1 四层精品定义

ROJ 不采用单一 `quality_score`，而采用四层目标。

### A. 内在质量

- Canon、时间线和人物状态一致；
- 因果关系成立；
- 人物选择可信；
- 世界规则稳定；
- 语言自然、无明显 AI 套话；
- 不抄袭、不泄漏来源表达；
- 无严重注水、重复和说明书化。

### B. 即时阅读结果

- 章节打开；
- 有效阅读；
- 章节完成率；
- 退出位置；
- 下一章点击；
- 阅读时长与异常跳读。

### C. 长期追读结果

- 三章留存；
- 十章留存；
- 三十章留存；
- 次日、七日回访；
- 收藏、追更、催更；
- 卷完成率；
- 完本倾向。

### D. 商业与信任结果

- 付费墙到达；
- 首次付费；
- 付费后继续阅读；
- 付费后快速流失；
- 退款、投诉和负反馈；
- 假钩子率；
- 承诺兑现率；
- 长期读者信任。

## 3.2 多目标约束

默认优化原则：

```yaml
maximize:
  - ten_chapter_retention
  - post_payment_retention
  - long_term_follow_rate
  - reader_satisfaction
  - promise_fulfillment

secondary:
  - chapter_completion
  - next_chapter_open
  - paywall_conversion

hard_constraints:
  - canon_consistency
  - originality
  - safety
  - platform_compliance
  - causal_coherence
  - reader_trust
```

任何短期指标提升都不得覆盖硬约束。

---

# 4. 领域术语

| 术语 | 定义 |
|---|---|
| Intrinsic Quality | 不依赖读者行为的内部文本与长篇质量 |
| Reader Segment | 具有相似平台、题材和阅读偏好的统计读者群 |
| Outcome Target | 需要预测的读完、追读、付费、留存等结果 |
| Outcome Prediction | 对特定章节版本和 Segment 的概率预测 |
| Calibration Profile | 将原始 Judge 输出映射为可信概率的版本化配置 |
| Exposure | 某读者在明确条件下看到某章节版本的事实 |
| Outcome Event | 曝光后的打开、阅读、完成、付费、回访等事件 |
| Human Anchor | 由目标读者或编辑产生的少量高价值偏好标签 |
| Mutation Case | 对干净样本注入已知缺陷形成的自动测试样本 |
| Pairwise Evaluation | 对两个章节版本进行盲测比较 |
| Experiment | 对合法候选版本进行随机分流的因果验证 |
| Guardrail Metric | 防止短期优化伤害长期质量的保护指标 |
| OOD | 输入超出校准样本分布，Out of Distribution |
| Shadow Mode | Judge 只预测和记录，不影响生产决策 |
| Promote / Revoke | 校准配置或 Judge Profile 的生产启用与撤销 |

---

# 5. 总体架构

```text
Chapter Authority
    │
    ├─ Draft / Revision / Canon / Five Quality Groups
    │
    ▼
Intrinsic Quality Aggregate
    │
    ▼
Reader Outcome Authority
    ├─ Narrative Feature Extractor
    ├─ Segment Resolver
    ├─ Outcome Judge Ensemble
    ├─ Pairwise Judge
    ├─ Uncertainty / OOD Detector
    ├─ Calibration Resolver
    └─ Decision Policy Engine
    │
    ├─ ACCEPT / REVISE / EXPERIMENT / HUMAN_REVIEW / REJECT
    ▼
Chapter Publish Gate
    │
    ├─ Shadow release
    ├─ Controlled experiment
    └─ Standard release
    ▼
Reader Feedback / Analytics Adapter
    │
    ├─ Exposure Event
    ├─ Outcome Event
    └─ Long-window Aggregate
    ▼
Calibration Center
    ├─ Human anchors
    ├─ Mutation evaluation
    ├─ Behavioral calibration
    ├─ Causal experiment analysis
    └─ Drift detection
    ▼
Calibration Profile Promote / Revoke
```

## 5.1 组件边界

### 5.1.1 Narrative Feature Extractor

将正文、细纲和长篇状态转换为版本化特征，不做最终价值判断。

### 5.1.2 Intrinsic Quality Judge

继续使用现有五组质量链，并逐步细化为证据化维度。

### 5.1.3 Outcome Judge Ensemble

基于正文、特征、Reader Segment 和平台上下文输出未校准预测。

### 5.1.4 Calibration Resolver

根据平台、题材、章节类型、Segment、Judge 版本选择最合适的 Calibration Profile。

### 5.1.5 Decision Policy Engine

使用硬门禁、质量证据、校准概率、不确定性、成本和实验价值产生决策建议。

### 5.1.6 Experiment Center

负责变体、随机分配、指标窗口、样本量、停止和 Promote。

### 5.1.7 Drift Monitor

监控模型、规则、平台、题材和读者结果变化，必要时自动降级到 Shadow Mode。

---

## 文档分册

- [Authority 与生产链接入](01-authority-and-production-integration.md)
- [Judge 契约、特征与校准](02-judge-contracts-and-calibration.md)
- [读者反馈、实验与权威契约](03-feedback-experiments-and-authority-contracts.md)
- [模型治理、测试、成熟度与实施路线](04-model-governance-testing-and-roadmap.md)
