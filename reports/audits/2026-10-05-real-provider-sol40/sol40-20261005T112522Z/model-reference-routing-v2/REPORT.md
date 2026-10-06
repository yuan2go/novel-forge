# 模型参考路由阶段进度；验证仍被阻断

当前不是完成报告。用户已确认模型共识作为本次资格参考，选择两次隔离盲评与一次独立裁决使用 `gpt-6.1-sol / high`；生成器保持 `gpt-6-sol / medium`。模型共识不得写入 HumanEvaluation 或伪称人类校准，同模型调用之间仍有相关性。

实际推理 0，盲评 0，裁决 0，接纳正文 0/40。当前仍不能执行 40 章连续小说验证。Pack 原生审批/部署缺失是当前外部阻断；模型参考原生合同及其消费是尚未完成的工程项，两者必须分别处理。

## 版本与保护

- 初始远端 main：4948d9b3a1ca22a78daffb4f4ab1cbf46180ac52。
- 本阶段读取的远端 main：9bd1d34f24ebe302533ffc26c72bda97336c4152；以本地 merge 6d3f67ecc977cce0ceaffcda222844badd952996 合入。
- 本阶段代码 SHA：6510ee74099a002f0d84f2c97f36e14ec7a523a0；分支 codex/work-intent-context-e2e-20261005。报告本身的最终 Git SHA 可由 `git log -1 -- <本目录>` 定位。
- 原工作区仍是 codex/wp02-author-approved-run、ceb69fa2ff1c56f07005154bb5797616e933e8c2；10 条未跟踪状态逐项保持，仅忽略 Git 输出末尾换行进行比较。没有 reset/stash/clean、覆盖或丢弃。
- 真实验证 Book 仍冻结在 22b44980f050fc6ffd13b8ca2ea52f2257e99ac7；失败 Attempt、预算 v2、作者输入和旧配置保留。新的配置只有 preflight 副本，没有替换活动配置、Book baseline 或原生预算。

## 当前已实现

`codex-router-models.v1` 显式目录绑定 model/reasoning/role/tasks/capacity，每条配置进入 model revision。PRIMARY 和 REFERENCE 走既有 Router、entitlement accounting、Kernel 额度及 task scope。无目录的历史配置保留 escalation-only 语义。Book Opening 允许精确匹配的 PRIMARY entitlement lane。两个 creation freeze 均纳入目录，不能在恢复时换模型、effort 或 scope。

两种模型共用 provider+authorization_ref 调用额度，增加模型不增加授权额度。PRIMARY没有伪造语义失败或HIGH风险理由；没有严格资格时仍 fail closed。REFERENCE 角色本身不产生模型参考、校准或资格，不能通过高分覆盖证据资格。

真实 PG 回归还重现了当前主线的 Planning 兼容缺口：1.18 原生 grant/source/reference 被历史 1.16 常量拒绝，以及 1.17 handler 未注册。精确兼容集合现为 1.16.0/1.17.0/1.18.0，版本仍逐项冻结。没有接受前缀版本，没有弱化 profile hash。参考 fixture 标签改为按其实际 command 的 work-v3 profile 构造；旧手工 Router fixture补齐已有 constructor scope，未改变生产门。

## 修复前反例与修复后结果

| 反例 | 修复后证据 |
| --- | --- |
| 合法资格下 MEDIUM Draft 的 Codex仅升级角色仍拒绝 | 显式PRIMARY可选，无伪造history；零资格仍拒绝 |
| 当前 composition 限制一个Codex model | 正式assembler可装配6-sol/medium与6.1-sol/high，各自scope、profile和revision |
| 参考模型被派到Draft | Router、materialization、reservation及真实Kernel均拒绝MODEL_TASK_NOT_AUTHORIZED |
| 新增模型可能复制account quota | 不同Operations、两个模型、同授权quota=1并发，只一个RESERVED |
| 当前Planning 1.18经过旧1.16 native来源门 | 合法原生grant/reference走通；1.19/1.180/后缀版本仍拒绝 |
| 1.17历史handler KeyError | 精确恢复1.17，无版本或语义自动升级 |

## 正式调用链与边界

作者输入 v2 → 正式 Book/Formation → Planning Generate → Pack Deployment解析 → Context/Provider Router → admission → Kernel reservation/Effect → 候选/评审/Quality → Acceptance → Canon/State/Projection → successor。

当前真实实例停在 Pack Deployment解析。新的候选目录已通过 composition preflight 与离线路由/Kernel回归；没有进入真实模型派发。4个6510正式Pack通过原生编译为TRUSTED，approval/activation/deployment均0，总16 compilation是历史追加，不是16个模型资格。具体精确manifest/compile/catalog/Prompt/Skill/Schema refs见 packs-source-6510ee74/。

作者方向仍为原创玄幻轻喜剧《这家灵兽食堂有点忙》，禁止武侠/悬疑，40章，每章5000–6000正文汉字，HAN_CHARACTERS_V1。共享1600 calls/80m tokens、DeepSeek USD20上限不增加。参考书只有用户提供标题，SOURCE_IMPORT_PENDING；未阅读/导入原文，不主张分析其具体内容，不把原书人物、场景或情节投入Draft。

## 验证

- 同代码SHA最终unit：429 passed +8 subtests；检验角色资格、scope、legacy、catalog version drift、当前/历史Planning及creation freeze。
- 同代码SHA最终PG：88 passed +13 subtests；既有Router/Kernel原生预算、PRIMARY采样、UNKNOWN/retry/accounting、reference provenance、跨模型并发quota以及越权reservation。
- 文档现实检查：PASS；修正一次新增comment触发ratchet的失败，没有提高ratchet。
- 最小Ruff、diff check：PASS；工程独立复核未发现必修漏洞。
- 早期失败XML及原始摘要均保留，包含版本兼容反例和测试装配合同错误。credentials只做精确脱敏，并保留原始私有SHA与公开SHA。
- 所有PG测试只使用独立 nf_model_catalog_20261005_test，未在小说运行账本执行fixture/truncate。
- 完整backend release matrix NOT_VERIFIED；不主张已完成新生产部署或40章运行。

STATIC/OFFLINE是本轮最高推理证据。此前DeepSeek余额HTTP200只是REAL_CAPTURE行政查询，不是推理；没有REAL_RUN小说、连续稿件或文学质量证据。本轮自制高分样本只在离线Router测试中使用，未写入运行实例资格台账。

## 尚需完成

1. 原生模型参考生成/三次隔离调用、记录与裁决、严格资格反馈合同，使用独立于Human契约的模型共识basis，并绑定精确subject/baseline/producer/Prompt/Skill/Schema/ModelCallLog/Effect/receipt；不得用协作编程代理输出代替。
2. 当前四个编译目标的另一位可信Principal审批、deployment和activation；编译者operator:sol40-20261005T112522Z不能自批，职责分离保持。已请求缺少的可信身份，没有造新身份或关闭检查。
3. 既有REFERENCE allocation为0，需在不增加共享预算下显式版本化分配和原生冻结。无需重新请求已批准的总预算，不得静默改旧budget。
4. 新目录/合同进入Book时要走所属Authority的明确迁移或新版本流程；旧Book禁止静默恢复到不同baseline/Prompt/Skill。
5. 完成严格资格后才能正式Author入口重跑：formation/planning/draft/review/必要revision/rereview/quality/acceptance/next-unit/recovery，再按10/20/30/40章检查实际可读稿。

这些仍属于当前授权工作，不需要用新的Agent/Skill/Authority体系或另建平行生产链。当前阶段尚未完成，不能宣布PRODUCTION_READY。

## 判定

| 项目 | 当前判定 |
| --- | --- |
| QUALITY_SEMANTICS_CLOSED | PASS |
| CONTEXT_COMPRESSION_PRODUCTION_READY | BLOCKED |
| AUTHOR_INTENT_PROPAGATION | NOT_VERIFIED |
| FORMAL_PRODUCTION_E2E | BLOCKED |
| ACCEPTANCE_AND_NEXT_UNIT | NOT_VERIFIED |
| RECOVERY_PATH | NOT_VERIFIED |
| LEGACY_ASSET_SAFETY | PASS |
| REAL_PROVIDER_VALIDATED | NOT_VERIFIED |
| CREATIVE_QUALITY_PROVEN | NOT_VERIFIED |
| PRODUCTION_READY | FAIL |

QUALITY_SEMANTICS_CLOSED的PASS沿用a57b8db工程证据，只覆盖既有STATIC/OFFLINE/MOCK_E2E范围；LEGACY_ASSET_SAFETY的PASS只覆盖本轮精确兼容与legacy escalation回归。其余项不因新目录、编译或fixture通过升级。

## 修改与文档

代码提交的实际文件：

- architecture/reality-evidence.json
- docs/runtime-operations.md
- scripts/creation_comparison.py
- scripts/run_creation_synthesis.py
- src/novel_forge/api/authority_dependencies.py
- src/novel_forge/modules/chapter_quality_authority/reference_subject.py
- src/novel_forge/modules/command_kernel/budget_runtime.py
- src/novel_forge/modules/command_kernel/routing_bootstrap.py
- src/novel_forge/modules/production_execution/codex_model_catalog.py
- src/novel_forge/modules/production_execution/cost_routing.py
- src/novel_forge/modules/production_execution/routing_runtime.py
- src/novel_forge/modules/story_planning_runtime/application.py
- src/novel_forge/modules/story_planning_runtime/world_sampling.py
- tests/integration/test_provider_routing_postgres.py
- tests/integration/test_routing_bootstrap_budget_postgres.py
- tests/unit/test_chapter_authority_dependencies.py
- tests/unit/test_codex_model_catalog.py
- tests/unit/test_creation_comparison.py
- tests/unit/test_routing_bootstrap.py
- tests/unit/test_story_planning_runtime.py

文档先在94135e1d修正模型参考当前/目标/缺口；本阶段更新docs/runtime-operations.md的多模型目录、旧升级语义、精确Planning兼容和尚未实施的模型参考边界；architecture/reality-evidence.json绑定当前实现树。历史strict-real-start-v2和model-panel-selection-v1保留，不能当作当前运行Authority。本目录是已有reports/audits体系中的工程证据，不新增canonical文档体系。
