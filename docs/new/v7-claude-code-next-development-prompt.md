# Claude Code Prompt - V7 Content Intelligence And Longform Proof

Updated: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`

Use this prompt in Claude Code from the repository root.

---

## Prompt

```text
你是 novel-forge 项目的资深后端架构师、产品工程师和 Novel Operating System 工业化实现负责人。

当前分支：feat/v7-content-intelligence-and-longform-proof

目标：
基于当前代码和文档，继续完成 V7 Content Intelligence And Longform Proof，不要重写项目，不要创建平行小说生成链路，而是在现有 Novel OS Runtime 上补齐内容智能层，使系统更接近“能稳定输出各种题材、各种风格、精品长篇小说”的 Novel Operating System。

必须先阅读：
1. CLAUDE.md
2. AGENTS.md
3. docs/README.md
4. docs/project-current-state.md
5. docs/roadmap/current-roadmap.md
6. docs/architecture/novel-operating-system-new-capabilities.md
7. docs/new/v7-content-intelligence-current-analysis.md
8. docs/new/v7-content-intelligence-product-spec.md
9. docs/new/v7-content-intelligence-architecture.md

执行原则：
1. 代码和测试是事实来源；历史 docs 只能作为参考。
2. 不允许绕过 Context Builder、MKAOS、Canon/KG、ReviewIssue、Provider Runtime Guard、Evaluation Gate、Publish Gate、Agent Scheduler、Loop Kernel、Trace/Cost Ledger。
3. 新能力必须以 schema-backed asset、service、API、Agent operation、Workflow processor、tests、docs 的形式接入现有系统。
4. production / operating_system 环境下必须 fail closed；local/mock 环境保持可测试。
5. 不要把 UI 页面存在当成产品 workflow 完成，必须有 service/API/test 证据。
6. 不要复制参考作品内容，只抽象结构、节奏、爽点、人设机制、冲突设计、情绪曲线、章节钩子和商业逻辑。
7. 每轮修改后运行相关测试；测试失败先修复。
8. 不要频繁询问下一步；按文档规划自主推进，直到完成可验证闭环。
9. 可以从项目 skills 仓库中选择合适 skill；如果当前 skills 不足，可以从 https://www.skills.sh/ 或 https://github.com/anthropics/skills 查找并安装任务所需 skill，但必须记录到 docs 或执行报告，且不得把外部 skill 当成项目源码事实。

第一阶段任务：Content Intelligence Foundation

A. Genre OS
新增或完善：
- src/novel_forge/modules/genre_os/
- genre_profile
- subgenre_mechanic
- genre_strategy_pack
- genre_risk_gate
- platform_genre_fit
- genre_template_binding

要求：
1. 支持玄幻、都市、悬疑、科幻、历史、言情、奇幻、恐怖、现实、轻小说等大类。
2. 支持子类型，例如凡人流、无敌流、诡异修仙、刑侦、密室、赛博朋克、权谋、关系向等。
3. 每个 strategy pack 必须包含核心爽点、读者承诺、必要系统、世界观要求、人物要求、开篇信号、章节 beat、长篇风险、平台适配、review rules。
4. Genre Strategy Pack 必须能进入 Context Builder。
5. Genre Risk Gate 必须能生成 ReviewIssue。
6. 增加 product API 和基础 UI 页面，至少能 inspect 和 run。
7. 增加 tests/unit/test_genre_os.py 和集成测试。

B. Style OS
新增或完善：
- src/novel_forge/modules/style_os/
- style_sample
- style_fingerprint
- style_profile
- style_generation_policy
- style_review_rule
- style_drift_report
- style_rewrite_task

要求：
1. 支持项目自有或授权样本文本导入。
2. 保留 rights 和 source isolation；样本 raw text 不得进入生成上下文。
3. 抽取平均句长、句长分布、对话比例、描写比例、心理描写比例、修辞密度、情绪词分布、叙述视角、叙述距离、节奏、AI 味风险。
4. style_profile 必须能转为 generation_policy 和 review_rule。
5. style_drift_report 必须能对 draft_chapter 输出漂移等级和 rewrite task candidate。
6. Style Drift Gate 必须能生成 ReviewIssue。
7. 增加 tests/unit/test_style_os.py 和集成测试。

C. Canon Graph 2.0
在现有 src/novel_forge/modules/canon_graph/service.py 基础上扩展，不要另起平行 Canon 系统。

新增或完善 plugin：
- fantasy_power_scale_engine
- mystery_evidence_chain_engine
- romance_relationship_state_engine
- historical_faction_network_engine
- sci_fi_rule_consistency_engine
- horror_rule_contamination_engine

要求：
1. 每个 plugin 输出 schema-backed report。
2. 所有 critical conflict 必须转 ReviewIssue。
3. 支持 chapter/draft/outline/release package 的 gate 调用。
4. Canon Graph diff 和 rollback 后重建必须保持一致。
5. 增加 tests/unit/test_canon_graph_plugins.py。

D. Quality Eval 2.0
扩展 evaluation_center，不要废弃现有模块。

新增或完善：
- quality_rubric_pack
- opening_3_report
- golden_10_report
- volume_30_report
- longform_100_report
- quality_regression_report
- model_judge_result
- human_annotation

要求：
1. Local heuristic 作为 fallback，不得冒充精品评测。
2. 支持 genre/platform/style rubric。
3. 支持 Opening 3、Golden 10、Volume 30、Longform 100 四类套件。
4. 低分自动生成 ReviewIssue / RevisionTask。
5. Release Package 必须能引用质量评测证据。
6. 增加 tests/unit/test_quality_eval_v2.py。

第二阶段任务：Long-chain Proof Center

新增：
- src/novel_forge/modules/long_chain_proof/
- long_chain_run
- long_chain_checkpoint
- long_chain_acceptance_report
- long_chain_failure_report
- chapter_quality_trend
- canon_conflict_trend
- style_drift_trend
- reader_fatigue_trend
- cost_quality_trend

要求：
1. 支持 deterministic 50 chapter pressure run。
2. 支持 mock 100 chapter run。
3. 支持 state-only 300 chapter simulation。
4. 支持可选 provider 30 chapter slow test，默认不在普通 make test 中运行。
5. 每 10 章触发 Longform Recap。
6. 每 30 章触发 volume review。
7. 每 50/100 章生成 acceptance report。
8. 记录 Context Bundle、Chapter State、Evaluation Result、Cost Ledger、ReviewIssue、Canon Conflict、Style Drift 的覆盖率和趋势。
9. 支持 resume/rollback 证据。
10. 增加 tests/integration/test_long_chain_50_chapter_content_intelligence.py，slow tests 可 opt-in。

第三阶段任务：Publishing / Feedback Adapter 2.0

新增或完善：
- src/novel_forge/modules/publishing_feedback_adapters/
- platform_upload_package
- platform_publish_receipt
- platform_review_status
- platform_metric_snapshot
- platform_comment_batch
- comment_cluster_report
- chapter_dropoff_report
- feedback_plan_mutation_proposal

要求：
1. 先实现 manual upload package，不强行接真实平台 API。
2. 平台上传包包含标题、简介、章节标题、正文、封面/敏感/格式 checklist、手动上传步骤。
3. 支持发布回执录入和状态跟踪。
4. 支持导入平台指标和评论。
5. 评论聚类输出毒点、爽点、角色热度、弃读原因。
6. 反馈不得直接静默修改大纲，必须生成 human-gated mutation proposal。
7. mutation proposal 可指向 topic/genre/style/outline/chapter_plan/character/MKAOS weight governance。
8. 增加 tests/unit/test_publishing_feedback_adapters.py。

第四阶段任务：Agent / Workflow / UI 全覆盖

要求：
1. AgentOperationRegistry 注册所有新增 operation：
   - build-genre-strategy-pack
   - run-genre-risk-gate
   - ingest-style-sample
   - extract-style-fingerprint
   - build-style-profile
   - run-style-drift-gate
   - run-canon-graph-plugin
   - run-quality-suite
   - run-quality-gate
   - run-long-chain-proof
   - build-platform-upload-package
   - record-platform-receipt
   - import-platform-metrics
   - cluster-platform-comments
   - create-feedback-mutation-proposal
2. Workflow ProcessorRegistry 注册对应 processor。
3. Product API 新增：
   - /product/genre/*
   - /product/style/*
   - /product/quality/*
   - /product/long-chain-proof/*
   - /product/publishing-adapters/*
   - /product/feedback-adapters/*
4. Web Admin 新增或完善：
   - Genre Console
   - Style Console
   - Canon Graph Workbench 2.0
   - Quality Eval Console 2.0
   - Long-chain Proof Console
   - Publishing Feedback Console 2.0
   - Agent Operation Coverage Console
5. UI 页面不能只展示静态数据，至少要能触发核心 run/build/inspect 操作。

验收命令：
优先运行 focused tests：

python3 -m unittest tests.unit.test_genre_os tests.unit.test_style_os tests.unit.test_canon_graph_plugins tests.unit.test_quality_eval_v2 tests.unit.test_long_chain_proof tests.unit.test_publishing_feedback_adapters
python3 -m unittest tests.integration.test_content_intelligence_context_builder tests.integration.test_genre_style_quality_to_draft_chain tests.integration.test_feedback_to_mutation_proposal tests.integration.test_long_chain_50_chapter_content_intelligence
python3 -m unittest tests.unit.test_product_api_routes tests.unit.test_schemas tests.integration.test_novel_os_acceptance
npm --prefix web/admin run lint
npm --prefix web/admin test
python3 -m compileall -q src/novel_forge tests

最后运行：
make test

如果某些测试因环境缺依赖而无法运行：
1. 不要忽略。
2. 写清楚缺失依赖、跳过原因、替代验证。
3. 保证普通本地模式仍可运行。

完成标准：
1. 新增 schema 已接入 SCHEMA_CLASSES、ASSET_DIR_BY_TYPE、validate_common_fields。
2. 新增 service 均写 schema-backed assets。
3. 新增 API 有 route tests。
4. 新增 Agent/Workflow operation 有 coverage。
5. Context Builder 能注入 genre/style/quality/canon evidence。
6. Production/operating_system 模式下 fail closed。
7. 50 章 deterministic long-chain content intelligence 测试通过。
8. 质量评测失败能生成 ReviewIssue。
9. 反馈回流生成 human-gated mutation proposal，不静默修改计划。
10. 文档更新：docs/README.md、docs/project-current-state.md、docs/roadmap/current-roadmap.md、docs/architecture/module-map.md、docs/product/capability-map.md、docs/quality/regression-tests.md。

输出要求：
1. 每完成一个阶段，提交清晰的阶段报告到 docs/reports/。
2. 报告必须列出新增文件、修改文件、测试命令、测试结果、剩余风险。
3. 不要声称已完成未测试能力。
4. 不要删除历史文档；必要时标记为 historical。
5. 若发现文档与代码冲突，以代码为准并更新当前文档。

开始执行。
```
