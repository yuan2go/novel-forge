# V7 Content Intelligence Product Specification

Updated: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`

---

## 1. Product Positioning

V7 的目标不是继续扩展“章节生成器”，而是把 Novel Forge 从早期 Novel OS Runtime 推进为：

```text
可按题材、平台、风格、长篇状态、精品标准和读者反馈进行稳定调度的长篇小说内容操作系统。
```

本阶段新增的产品层命名为：

```text
Content Intelligence Layer
```

它负责将已有的 OS Runtime 能力转化为真正的内容生产能力。

---

## 2. Product Goals

### 2.1 Primary Goals

1. 支持不同题材的长篇生产策略，而不是只支持单一悬疑样例。
2. 支持不同文风的生成、审稿、漂移检测和修订。
3. 支持百万字级长篇状态管理，包括 Canon、人物、伏笔、世界规则、时间线、战力/资源体系。
4. 支持精品小说质量评估，而不是只做工程验收评分。
5. 支持 50/100/300 章长链压力证明。
6. 支持平台发布包、发布回执、评论/指标反馈回流。
7. 支持 Agent Center 对所有内容智能操作的调度、门禁、回滚和证据展示。

### 2.2 Non-goals

1. 不重写现有生成链路。
2. 不绕过 Context Builder、MKAOS、Canon/KG、ReviewIssue、Provider Runtime Guard、Evaluation Gate、Publish Gate。
3. 不直接接入高风险未知平台接口；先实现本地手动上传包和回执 schema。
4. 不把历史设计文档当作真实实现；代码和测试是事实依据。
5. 不把 UI 页面存在视为产品 workflow 已成熟。

---

## 3. Personas

| Persona | Need | Product Capability |
|---|---|---|
| 作者 / 总编 | 想稳定产出长篇，不想每章手动维护设定 | Canon Graph、Long Memory、Long-chain Proof |
| 题材策划 | 想知道不同平台适合什么题材和爽点 | Genre OS、Platform x Genre Matrix |
| 风格编辑 | 想保持文风稳定，避免 AI 腔和跑偏 | Style OS、Style Drift Gate |
| 审稿人 | 想判断是否达到精品、可追读、可发布 | Quality Eval 2.0、ReviewIssue |
| 发布运营 | 想生成平台专用发布包并跟踪反馈 | Publishing Adapter、Feedback Adapter |
| 工程维护者 | 想保证所有操作可追踪、可恢复、可回滚 | Agent/Loop/Trace/Cost/Gate Coverage |

---

## 4. Product Modules

## 4.1 Genre OS

### Purpose

把“题材”从普通文本标签升级为可执行策略包。

### Core Objects

```text
genre_profile
subgenre_mechanic
genre_strategy_pack
genre_risk_gate
platform_genre_fit
genre_template_binding
genre_feedback_learning_report
```

### Functional Requirements

1. 创建题材大类：玄幻、都市、悬疑、科幻、历史、言情、奇幻、恐怖、现实、轻小说等。
2. 创建子类型：凡人流、无敌流、诡异修仙、刑侦、密室、赛博朋克、权谋、关系向等。
3. 每个子类型必须包含：
   - 核心爽点；
   - 读者承诺；
   - 必要世界观机制；
   - 必要人物机制；
   - 必要章节 beat；
   - 常见长篇风险；
   - 平台适配程度；
   - 推荐开篇信号；
   - 反套路创新方向。
4. Genre Strategy Pack 必须能进入 Context Builder。
5. Genre Risk Gate 必须能在 outline / chapter_plan / draft / review 阶段触发 ReviewIssue。

### Acceptance

输入：

```text
平台：番茄
题材：都市异能
风格：轻松爽快
目标：150 万字
```

系统必须输出：

1. genre_strategy_pack；
2. platform_genre_fit；
3. opening requirements；
4. first 30 chapter rhythm plan；
5. longform risks；
6. review rules；
7. Context Builder evidence。

---

## 4.2 Style OS

### Purpose

让系统支持“各种风格”，而不是只靠 prompt 中的一句风格描述。

### Core Objects

```text
style_sample
style_fingerprint
style_profile
style_generation_policy
style_review_rule
style_drift_report
style_rewrite_task
style_consistency_gate
```

### Functional Requirements

1. 支持导入项目自有文本或授权样本作为 style_sample。
2. style_sample 必须保留 rights / copyright boundary。
3. style_fingerprint 抽取：
   - 平均句长；
   - 句长分布；
   - 对话比例；
   - 描写比例；
   - 心理描写比例；
   - 修辞密度；
   - 情绪词分布；
   - 叙述视角；
   - 叙述距离；
   - 节奏；
   - AI 味风险。
4. style_profile 转换为生成策略。
5. style_review_rule 转换为审稿规则。
6. style_drift_report 对比当前章节与项目目标风格。
7. style_rewrite_task 将 drift report 转成修订任务。

### Acceptance

同一章细纲必须能生成：

1. 番茄快爽版；
2. 起点长线升级版；
3. 冷峻悬疑版；
4. 出版文学版。

每个版本必须有 style_fingerprint 和 style_drift_report。

---

## 4.3 Canon Graph 2.0

### Purpose

把现有 Canon Graph 从通用图谱升级为面向长篇小说的语义推理系统。

### Core Objects

```text
canon_graph_snapshot
canon_graph_reasoning_report
canon_conflict_report
canon_merge_adjudication
power_scale_rule
timeline_event
evidence_chain
relationship_state
world_rule_constraint
```

### Functional Requirements

1. 保留现有 Canon Graph build/query/path/diff/conflict 能力。
2. 增加 genre-specific reasoning plugin：
   - fantasy_power_scale_engine；
   - mystery_evidence_chain_engine；
   - romance_relationship_state_engine；
   - historical_faction_network_engine；
   - sci_fi_rule_consistency_engine；
   - horror_rule_contamination_engine。
3. 所有 conflict 必须能转 ReviewIssue。
4. Canon patch 必须 human-gated。
5. Canon Graph diff 必须支持长篇回滚后重建。

### Acceptance

50 章压力测试中必须能发现：

- 人物状态冲突；
- 伏笔未绑定真相；
- 战力越级；
- 时间线不可能；
- 世界规则矛盾；
- 关系状态跳变；
- 反派行动与目标不一致。

---

## 4.4 Quality Eval 2.0

### Purpose

把 Evaluation Center 从工程验收评分升级为精品小说评测中心。

### Core Objects

```text
quality_rubric_pack
evaluation_suite
evaluation_case
evaluation_result
evaluation_gate
model_judge_result
human_annotation
quality_regression_report
opening_3_report
golden_10_report
volume_30_report
longform_100_report
```

### Functional Requirements

1. 增加 genre/platform/style 维度的 rubric pack。
2. 增加四类核心评测套件：
   - Opening 3 chapters；
   - Golden 10 chapters；
   - Volume 30 chapters；
   - Longform 100 chapters。
3. Local heuristic 只能作为 fallback。
4. 支持 model judge 和 human annotation。
5. 支持 rubric calibration：评测分数与真实反馈指标对齐。
6. Evaluation Gate 可阻断 publish/release。
7. 失败自动生成 ReviewIssue 和 RevisionTask。

### Acceptance

一个 release package 必须包含：

- 单章质量评分；
- 开篇评分；
- 追读风险；
- 风格一致性；
- Canon consistency；
- 平台适配；
- 原创性风险；
- publish compliance；
- blocking issue count。

---

## 4.5 Long-chain Proof Center

### Purpose

证明系统不是 12 章 demo，而是可以承受长篇生产压力。

### Core Objects

```text
long_chain_run
long_chain_checkpoint
long_chain_acceptance_report
long_chain_failure_report
chapter_quality_trend
canon_conflict_trend
style_drift_trend
reader_fatigue_trend
cost_quality_trend
```

### Functional Requirements

1. 支持 50 章 deterministic pressure。
2. 支持 100 章 mock generation proof。
3. 支持 300 章 state simulation。
4. 支持可选 30 章 real provider slow test。
5. 每 10 章必须触发 Longform Recap。
6. 每 30 章必须触发 volume review。
7. 每 50/100 章必须生成 acceptance report。
8. 中途失败必须支持 resume/rollback。

### Acceptance Metrics

| Metric | Required |
|---|---|
| chapter_state coverage | >= 95% |
| context_bundle coverage | >= 95% |
| evaluation_result coverage | >= 90% |
| unresolved blocking ReviewIssue | 0 for publishable state |
| canon conflict trend | no critical unresolved conflicts |
| style drift trend | bounded by threshold |
| cost ledger coverage | >= 95% |
| resume success | demonstrated in test |
| rollback consistency | demonstrated in test |

---

## 4.6 Publishing / Feedback Adapter 2.0

### Purpose

把本地 release package 推进为平台发布和真实反馈回流闭环。

### Core Objects

```text
platform_upload_package
platform_publish_receipt
platform_review_status
platform_metric_snapshot
platform_comment_batch
comment_cluster_report
chapter_dropoff_report
feedback_plan_mutation_proposal
```

### Functional Requirements

1. 生成平台专用上传包。
2. 支持手动上传步骤说明。
3. 支持平台回执录入。
4. 支持平台审核状态跟踪。
5. 支持评论/追读/收藏/完读/弃读等指标导入。
6. 评论聚类输出毒点、爽点、角色热度。
7. 反馈不能直接静默修改大纲，必须生成 human-gated mutation proposal。

### Acceptance

真实或手动平台反馈输入后，系统生成：

- operational_metric_snapshot；
- comment_cluster_report；
- chapter_dropoff_report；
- platform_feedback_backflow；
- review_rule_pack update proposal；
- topic/genre/style/character/rhythm adjustment proposal；
- MKAOS weight governance dry-run or human-gated apply。

---

## 5. Unified Product Workflow

```text
Project Init
  -> Platform Strategy
  -> Genre Strategy Pack
  -> Style Profile
  -> MKAOS Knowledge Pack
  -> Canon Graph Seed
  -> World / Character / Outline
  -> Chapter Plan
  -> Context Builder: Genre + Style + MKAOS + Memory + Canon/KG
  -> Draft
  -> Style Drift Gate
  -> Canon Graph Gate
  -> Quality Eval Gate
  -> ReviewIssue / RevisionTask
  -> Re-review
  -> Publish Gate
  -> Platform Upload Package
  -> Platform Receipt
  -> Feedback Import
  -> Feedback Backflow
  -> Plan / Genre / Style / Canon / MKAOS human-gated update
  -> Next Chapter Loop
```

---

## 6. Required UI Workflows

| Console | User Actions |
|---|---|
| Genre Console | create genre profile, build strategy pack, run genre gate, inspect platform fit |
| Style Console | import sample, extract fingerprint, build profile, run drift gate, create rewrite task |
| Canon Graph Console 2.0 | build graph, inspect conflicts, approve/reject merges, run genre-specific reasoning |
| Quality Eval Console 2.0 | create suite, run opening/golden/volume/longform evaluation, inspect failed gates |
| Long-chain Proof Console | start 50/100/300 run, inspect checkpoints, trends, failures, resume/rollback |
| Publishing Console 2.0 | build upload package, record receipt, track status, import metrics/comments |
| Feedback Console 2.0 | cluster comments, detect dropoff, propose plan/style/genre mutation |
| Agent Operation Coverage Console | show content-intelligence operation coverage and missing gates |

---

## 7. Release Criteria

The v7 content-intelligence work can be considered complete when:

1. `make test` passes.
2. Focused tests pass for genre/style/canon/eval/long-chain/publishing/feedback.
3. A deterministic fixture can run 50 chapters with long-form artifacts and acceptance report.
4. A mock 100-chapter run can produce quality/canon/style/cost trends.
5. A manual platform feedback fixture can update plan proposals without silent mutation.
6. UI feature architecture tests include all new consoles.
7. Docs index links this specification and the architecture document.

---

## 8. Implementation Priority

### Cycle 1 - Product schemas and service skeletons

- Genre OS schemas/services/API/tests.
- Style OS schemas/services/API/tests.
- Quality rubric pack schemas/services/tests.

### Cycle 2 - Canon Graph and Eval deepening

- Canon Graph genre plugins.
- Quality Eval 2.0 suites.
- ReviewIssue integration.

### Cycle 3 - Long-chain proof

- 50 chapter deterministic suite.
- 100 chapter mock suite.
- Long-chain report and trend assets.

### Cycle 4 - Publishing/feedback

- upload package;
- receipt schema;
- comment cluster;
- dropoff detector;
- mutation proposal.

### Cycle 5 - UI and operation coverage

- UI consoles;
- AgentOperationRegistry entries;
- Workflow ProcessorRegistry entries;
- LoopRun policies;
- docs and regression commands.
