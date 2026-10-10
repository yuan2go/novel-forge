# WP-LONGFORM-OWNERSHIP-CRAFT-EVIDENCE-01 验收证据

这是固定输入下的审计与交付证据，不是新的架构权威、生产批准或作者决定。

基线 main：`e763d5fc959fb2fa3e03faff839de1e0d9c6ee64`。独立分支：`codex/wp-longform-ownership-craft-evidence-01`。最终业务代码与定向检查 SHA：`4cad6c6f097c658f99b164d0ebc09e9242f7cd27`；随后提交的报告不会替换实际执行 SHA。基线正文执行 SHA 为 `67af07a6b66b4a9d3b19a80f5958b704a3427fa1`，三个增强正文执行 SHA 为 `04e199c181ac74bc10ca59daf693df027d9588ec`，选定范围模型评审执行 SHA 为 `4cad6c6f097c658f99b164d0ebc09e9242f7cd27`。

**验收结论：定向工程能力达到 `EXECUTABLE`；四组真实第17章均已保存、回读、导出。文学改善 `NOT_PROVEN`，真人验证与正式推广 `NOT_READY`，增强策略默认关闭。连续第18章正文、逐样本 Writer 语义归属判定和成对模型校准尚未完成。不得将此 PR 表述为长篇生产质量已经解决。**

## 1. 文档清理和现状对账先于代码

先提交 `b042e100` 的 [PREIMPLEMENTATION_RECONCILIATION.md](PREIMPLEMENTATION_RECONCILIATION.md) 和 [preimplementation-inventory.json](preimplementation-inventory.json)，再进行业务修改。唯一权威文档仍由 `docs/README.md` 列出的五份文档组成；本目录是证据，不增加 canonical 设计来源。

| 对象 | 处理及依据 |
| --- | --- |
| PR #153 | 已合并；复用其第1—16章选稿、续写、迁移0196—0197，不重建 Manuscript 或续写恢复。 |
| PR #154 | 已合并，正是冻结 main；复用其意图/治理分离、Planning 2.14、System v12、Template v3、迁移0198。 |
| 已归档的四份旧提案 | #154 已完成归档；原始字节及 archive manifest 保留，没有重复归档或删除。 |
| 旧正文、冻结计划、Skill、迁移、历史审计 | 保留；新增精确 legacy-v4 Skill 副本，旧合同不转向新 Skill。 |
| `docs/current-system.md` | 修正默认尾部投影的覆盖上限、Memo 输入时机；增加已有链路的 opt-in 投影、Writer 去重及选定范围 Review 的真实行为。 |
| `docs/runtime-operations.md` | 增加可关闭策略、精确血缘、遗漏与溢出边界、真人推广门的运维说明。 |
| 原库存清单中猜测的 production-path 文件 | 保留 `PATH_NOT_PRESENT` 原始观察；[final-authority-inventory.json](final-authority-inventory.json) 补记实际 `production-entry-manifest.yaml`、worker/migration/instruction 清单哈希。 |
| 其他工作包 | 只读识别 #133/#135 及独立意图 followup；未在本分支接管、改写或发送消息。 |

既有 #154 全矩阵的 222 FAIL / 11 ERROR 留在历史证据中，不用本次定向 PASS 覆盖。没有删除仍需兼容的资产，也没有新增迁移或 Authority。

## 2. 根因、真实链路和约束分类

实际入口是 Book `production.submit_chapter`，其 `manuscript.freeze_working_context` 在 Book UoW 中绑定当前精确选稿。Planning 通过 `story_planning_runtime.execution` 和 `provider_views` 投影；Chapter `_ExecutionIntentHandler` 构建执行意图，`_MemoHandler` 提交 Memo，随后 `_ContextHandler` 提交 Writer Context。Provider 输入仍经 Capability Pack、冻结合同、Gateway、路由、Command Kernel 的 ExternalEffect/receipt 链执行。Book acceptance 的 UoW 才能提交 Canon、Narrative State 和 accepted cursor。

| 已证明的节点 | 根因或保留的边界 |
| --- | --- |
| 默认 Selected Working Projection | 仅最近四章尾部、总计4200码点；第1—16章共50381码点。保存了版本不代表早先经历进入了模型。 |
| Memo 发生在 Draft Context 之前 | 原 Memo 仅看到 ExecutionIntent；在后续 Draft 才补入经历，无法修复已经生成的 Memo。 |
| 增强 Intent 和 Context 都含同一选稿 | Intent 的 JSON 字符串隐藏了重复对象；原精确值去重不能穿透字符串。24k投影 Context 通过后，Writer 的输入上界仍达366520，真实路由拒绝。 |
| 既有 Narrative State 信息投影 | 保留 scene/actor scope；世界事件不授予所有人物知识，人物陈述不保证世界真相。未接纳工作稿也不是正式事实。 |
| 冻结计划约束正文推进 | 四组第17章仍主要谈判、确认和安排劳动；更完整的输入不能自行改写计划，把下一章事件提前执行。 |
| 当前 Pack 的 Review v4 解析 | 冻结的是 v4 字节，旧解析却转向 v3；恢复精确 v4 副本，不修改历史 Pack 身份。 |
| 当前 Planning Template v3 的 World Schema 身份 | 只放行带精确 `Narrative intent v1:` 注释的当前 schema/stage 身份；缺注释或不匹配仍拒绝，没有放宽 World 合同。 |

`CURRENT_PROVEN_INVARIANT`：精确源/hash、作者选稿、Book 锁/CAS、UoW 接纳边界、未接纳稿不授予 Canon、UNKNOWN 必须留证对账。`CURRENT_RUNTIME_FACT`：原 Book 16章、accepted0、PAUSED，实际运行 release 与 main 不同。`CONFIGURABLE_POLICY`：可选历史窗口、完整最近章数、段落预算、查询、四种指导模式及手动 Review 范围。`HISTORICAL_COMPATIBILITY`：旧尾部投影、旧 Skill、旧 Review v1 题材指令。`UNRESOLVED_DESIGN_CONSTRAINT`：哪些输入能稳定改善人物、语言和阅读兴趣，仍需连续正文和真人证据。

## 3. 实际实现、Prompt/Skill 与兼容

新增 `book_authority/working_prose.py` 是已有 Book 投影的辅助模块，不拥有第二套状态。`working-prose-projection.v2` 通过现有生产 profile 或 LOCAL_OPERATOR 新 Chapter 请求的 `preparation_report.working_prose_policy` 显式选择。四种模式为 CONTINUITY_ONLY、CHARACTER_REACTION、ACTION_CONSEQUENCES、COMBINED。

投影保留完整段落、Unicode位置、精确 AssetVersion/hash、来源章、选稿血缘、未解决依赖和显式遗漏。最近若干章必须完整；溢出则拒绝，不能静默截断。较早段落按预先声明的词项排名分配可选空间；排名只是取材，不是事实抽取或人物知识证明。`structured_facts` 保持为空，人物知识标记未验证，不制造 Canon ID。跨 Book、未来章、选稿缺失、重叠、人物知识/Canon 提升，即使重算 hash 也不能通过验证；UoW 还核对真实源字节。

同一冻结投影进入 Planning continuity v3、ExecutionIntent/Memo、Draft Context。现有 participation/goal 等规划输入形成 `chapter-character-situation.v1`，明确属于未来意图。指导区分既有经历、人物见闻、信念、传闻、读者披露与未来计划，鼓励自然选择、关系余波和已有变化的承接；不规定题材、情绪终点，不强制冲突、奖励、反转或代价，允许平静与稳定。

Writer `provider-context-view-v7` 仅对增强请求生效：核验 Intent 内嵌投影与 Context 的投影完全一致，保留其余意图为结构化 `frozen_intent`，只传一次工作正文。原 Intent/Context 资产不修改。差异投影拒绝，旧请求保持原 view。外层 `working-manuscript-context.v1` 不变，兼容迁移0181的 CHECK；没有新迁移。旧冻结请求按旧策略精确恢复，不因当前 profile 变化升级。

Root `prose-generation` 新版增加经历、选择、条件性后果与自然表达方法，v4 冻结副本可精确解析。**本次四组对照均使用现有 prose-generation-v4，以控制 Skill 变量；新增 v5 只获得解析和工程证据，未在这些对照中获得真实正文资格。增强组实际变化来自冻结投影及 Memo/Writer 指导。**

公共 Prompt 检查复用 #154 的意图/治理分离和作品 creative baseline。当前 longform Review v3 使用各章冻结作品目标及 UNKNOWN_LEGACY_BASELINE；旧 v1 的玄幻/武侠表述只留在兼容分支，不套用于当前路径。本次没有把某一题材方法卡升级为公共创作要求，也没有新增正式评分权重、DivLM 或多样性评分。没有声称把所有历史动态方法卡逐一重新资格验证。

选定范围 Review 复用 Book Follow-up：MANUAL 策略 `EXPLICIT_RANGES_ONLY` 必须提供2—8个精确源范围，保留全来源 manifest，仅派发指定窗口。默认/自动逐窗行为不变。局部覆盖不等于全书阅读，不授予作者决定或接纳权限。

## 4. 80个候选：来源验证与语义错误率分开

[ownership-cases.json](ownership-cases.json) 包含64个真实选稿段落候选、8个真实未来计划值、4个真实未选版本候选和4个合成边界控制。实际未选版本保留为未选，不虚称已废弃。accepted cursor 为0，因此不能以真实已接纳世界事实替代缺失的控制材料。人物知识、信念、传闻、读者知识等解释标签为待人工裁决的候选，不是黄金真值。

[ownership-verification.json](ownership-verification.json) 逐样本核对 Unicode 原文、hash 或 JSON pointer：真实来源定位错误 **0/76（0%）**；4个合成控制不计入真实定位分母。7个重算hash的边界攻击全部拒绝。该0%不是 Writer 语义归属错误率。

| 覆盖测量 | 64个真实选稿候选进入输入 |
| --- | --- |
| 默认四章尾部 | 3/64 |
| 32k只读投影 | 43/64；真实 Context 预算拒绝，不能写成实际 Writer 覆盖。 |
| 最终22k真实正文投影 | 28/64；剩余36明确遗漏，详见 [ownership-coverage-production22k.json](ownership-coverage-production22k.json)。 |

32k、24k的失败留在独立 predecessor manifest 中。最终22k投影21999码点，其中最近13—16章完整11659码点；历史词项、完整章数和模型预算均未为样本答案调优或放宽。预算变小只减少可选较早段落。

**Writer 逐样本语义归属错误率 `NOT_EVALUATED`；80项语义裁决 `NOT_RUN`。** 本次证明来源与升级边界，尚未证明模型读懂每个人物的知识和信念。复现工具为 `scripts/verify_longform_working_cases.py`；取材覆盖、边界验证和语义理解必须分别验收。

## 5. 规划检查、四组真实正文和连续性边界

[plan-inspection-source.json](plan-inspection-source.json) 固定第16—19章原计划。16章手位练习与木片复验尚未完成；17章主要商量后续劳动；18章陆衡因自身练习不参与，沈砚独立劳动；19章课堂木片出现短暂而不稳定的亮纹。这些都不能被写成已稳定引气。劳动进度、修行进度和关系选择的潜在推进分布过散，重复许可/确认对话值得结构调整，但本次对照保持同一第17章计划，避免混淆计划改动与输入增量。

已有 `planning.change_request.author` 保存了未来规划变更请求：Operation `8fe46b0a-980d-4a05-97fc-ebafded10e93`，资产 `authority-output:8fe46b0a-980d-4a05-97fc-ebafded10e93:planning.change_request:v1`，hash `afd4cac4679c3ab48a7596a5ea4d30941d157c7e52137bb37161aad4e6695404`。建议压缩已经成立的反复询问、把可执行行动及其后续影响落入场景。初次请求错误地继承资产，被现有 authored-input 门拒绝，原失败保留；正确请求按已有 owner 保存。**类型化 Plan Change proposal 的资格审查、作者选择及激活 `NOT_RUN`；没有静默覆盖原计划、历史正文或作者决定。**

四组真实 Native Planning/Memo/Context/Draft/Book保存链使用相同选稿1—16和冻结第17章计划 `authority-output:e025d04a-aafb-411b-8fa6-dd0549fb7d2f:story_planning.candidate:v1`。均为 codex-cli / gpt-6-sol、真实 Provider；每组一份随机输出。基线生成后，增强 Writer 修复只作用于增强请求；基线原产物复用而不重发。独立数据库、完整 roots/receipts/hash 见 [comparison-manifest.json](comparison-manifest.json)、`native-arm-*.json` 和 `model-evidence-arm-*.json`。

| 组 | 指导 | 第17章码点 | 原始 Draft Operation | 结果 |
| --- | --- | ---: | --- | --- |
| 0 | 旧输入 | 2289 | `b7de0a2f-06b9-4761-b1eb-d0c7bc70ad3e` | SAVED_READ_BACK_EXPORTED |
| 1 | 人物反应+行动后果 | 2242 | `da54b446-1ec1-4d2f-9609-00994eee3088` | SAVED_READ_BACK_EXPORTED |
| 2 | 人物反应 | 2649 | `7d4f1cfb-3dd8-4d9b-b1d3-bd1504e2162d` | SAVED_READ_BACK_EXPORTED |
| 3 | 行动后果 | 2359 | `ecdf7eaf-7841-4909-91ce-b0d131ae27cd` | SAVED_READ_BACK_EXPORTED |

正文是 [candidate-arm-0.txt](candidate-arm-0.txt)、[candidate-arm-1.txt](candidate-arm-1.txt)、[candidate-arm-2.txt](candidate-arm-2.txt)、[candidate-arm-3.txt](candidate-arm-3.txt)。JSON公开副本仅脱敏 Provider辅助元数据，正文不变；明确区分 native content hash 与公开副本hash。原JSON和数据库冷备保留于权限受限的私有证据区，[prose-export-verification.json](prose-export-verification.json) 验证导出全文一致。

有限观察见 [qualitative-comparison.json](qualitative-comparison.json)：反应组承接此前交药叶经历；后果组把搬桩后的墙边处境与堆枝联系起来。基线的“接收记录”和组合组的“进一步的质量和收益，要等相应核验”仍显示程序化表达。四组都主要在安排劳动，而未真正开展劳动。**这些是助手读稿观察，不是独立真人意见、原生质量门、统计增益或因果证明。**

组合组随后按原链路生成第18章计划和 Memo，冻结了实际选定第17章经历；Writer路由输入上界227839 + 输出32000 =259839，超过258400的现有预算1439，故在 Draft 派发前 `BLOCKED`。原Root `4909a6e3-47cc-438e-9d14-1dcb439cfdc4` 与routing证据保留于 [chapter18-routing-boundary.json](chapter18-routing-boundary.json)。未扩大预算、重置Root或伪造正文。真正连续两章的反应/后果继承效果仍未证明。

## 6. 模型评价、真人材料与启用依据

组合组16—17章真实选定范围评审 Run `05fba6c2-103f-49f1-ae18-fc0300f68d81`、Operation `21b3a6b4-e107-4aae-949a-87e4dd57f7d6` 已保存回读导出，使用 quality-review-v5。审读六维，产生一项 MINOR 篇幅问题和两项 INTENTIONAL 判定；没有给出文学分数。模型确认16章阶段所得与木片待复验、17章陆衡是否同行仍开放。第16和组合第17章都低于明确的2500中文字下限，不能把保存结果视为篇幅合格。原生run导出的 coverage_complete 为false，全书Review `NOT_RUN`；局部报告不升级全书覆盖。

基线评审原Effect `cd748001-0138-42fa-88d4-b6664ed80dbc` 为 **UNKNOWN**，本地receipt TIMED_OUT/MISSING，usage/cost UNAVAILABLE。现有恢复方法自动追加隔离 successor `6b57eca4-4434-42c3-819d-05582bb00e26`，它被 ProviderUnavailable/cooldown 阻止，未产生第二个Effect；没有重建或修改恢复机制。原Effect、请求digest、隔离历史、冻结资产和失败证据保留；本地结束不能证明远端取消。该隔离Review已通过已有control暂停，不继续派发。详见 `native-model-review-arm-0.json` 及 `model-review-baseline-*.json`。

因此模型基线/增强配对不完整，模型与真人校准 `NOT_EVALUATED`。不能用组合组局部审稿或助手读稿替代独立真人证据。

[qinglan-reader-blind-draft.zip](qinglan-reader-blind-draft.zip) 提供原选稿1—16背景和三组匿名A/B：旧链路对组合、组合对后果组、组合对反应组。对应表单复用既有10维字段，重点映射人物可信度、语言/可读性、场景/节奏/连续性、整体偏好及继续阅读意愿，见 [model-human-mapping.json](model-human-mapping.json)。材料不附模型结果、未来规划或组别身份，随机映射单独私有保存。

**真人评阅者0、决定0；原生正式 blind export/import `NOT_RUN`。** 现有正式协议需要实际独立评阅者身份，本包只是可供评阅的材料草案，空表不是有效人类记录。没有虚构评阅者、导入模型互评或向他人发送消息。启用依据仍为 `NOT_READY / DEFAULT_OFF`，不会阻塞普通作者优先交稿。

## 7. 必要测试、失败与运行状态

[test-records.json](test-records.json) 按执行SHA和证据类型记录：最终270个定向单元测试通过；两项原生PostgreSQL中断回归通过，验证脚本传输的8章保存、重放、事务/CAS/选稿/目标扩展/导出等，**不是真实Provider或文学证据**。documentation_reality、instruction_surface、test_reality、architecture_fitness 均PASS；source comment ratchet保持原515。覆盖精确来源、重算hash攻击、旧请求重建、Memo/Writer输入、Skill绑定、局部Review及默认行为。

历史Planning模块4 FAIL / 52 PASS：三项旧catalog身份失败在冻结main独立复现，另一项仍期待旧当前版本2.13而main已2.14。旧Review集成fixture在 `REALIZATION_SOURCE_BINDING_REQUIRED` 提前失败，冻结main同门失败；没有删除失败证据、弱化源绑定或修改历史golden。最后不保留无效的Review测试参数化。真实选定范围Review另有上述独立执行证据。业务代码 diff-check 通过；最终原文证据 staging 检出第1、15章各一处原始尾部空格，保留精确原文而不改写源字节，记录为独立FAIL。全发布矩阵 `NOT_RUN`，不声称 `QUALIFIED` 或 `PRODUCTION_PROVEN`。

原环境最终只读核验时间2026-10-10T14:23:08Z：数据库 `nf_qidian_learning_20261008_test` / OID16384 / cluster `7694308142111706022`；BookRun `book-run:c14fec92-6d9a-4cbf-932f-aa85b7257a71` 仍16章、accepted0、PAUSED、version114。本工作包未修改原Book或启动原Provider恢复，见 [original-runtime-final-readonly.json](original-runtime-final-readonly.json)。

验证环境来自原始冷快照，独立本机PG16 cluster `7695026994287073315`，loopback端口55483。其parent也有OID16384，**不同cluster不能按OID当作原库**。DevSSD空间不足时保留失败并迁移自己拥有的隔离库，不清理用户原库或扩大服务配置。已完成且无未决Effect的组0/2/3和早期失败组保存pg_dump hash后才回收自有arm库；组合组及含UNKNOWN的基线Review库保持在线留证。没有在该cluster启动API、worker、自动化调度；脚本已结束。原始源快照、冷备、receipt、凭据配置均留在权限受限区，不随PR发布。

## 8. 遗留与后续验收顺序

1. 对80候选完成独立语义裁决，再用实际Writer输出逐项判定人物知识泄漏、未来/工作稿升级和版本污染；当前只证明定位和代码边界。
2. 原Effect UNKNOWN只按原receipt/native隔离记录对账，不能换ID盲发。模型基线配对缺口保留，不拿缺失usage作零成本。
3. 通过已有Plan Change生成可审查的类型化结构方案及作者/version选择；原1—16和冻结计划保留。单加质量规则不能解决17章尚未行动的问题。
4. 在现有预算内给下一次合法请求选择足够的可选旧文预算；不修改已冻结18章输入、不放宽门。真正连续正文后才检验后果继承与重复推进。
5. 两名实际独立真人通过既有blind/Reader Feedback机制评阅候选，校准模型意见，并由作者决定是否采用。结果若不改善，应保留来源与兼容修复而舍弃无效指导；默认仍关闭。

工程改动可审查并回退，已发生的真实调用、冻结版本与UNKNOWN历史不能随回退消失。本次交付提供四份真实正文、精确血缘与评阅草案；尚未达到“稳定生成持续吸引力长篇”的最终文学目标。
