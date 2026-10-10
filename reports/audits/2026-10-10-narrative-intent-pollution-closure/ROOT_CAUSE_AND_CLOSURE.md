# WP-NARRATIVE-INTENT-AND-PROMPT-POLLUTION-CLOSURE-01

本报告是取证及修改证据快照，不是新的架构 Authority。工程修复已实现并在离线真实装配、原生 Scripted 规划路径执行；完整 Book 集成仍有失败，真实正文改善未证明。不得将本报告或测试结果作为新正文输入、作者接纳、部署或文学资格证据。

## 冻结身份与范围

- main：`f067d189a63f644a3a49f78abda557035b5fa59a`。最初取证基线为 `4c0f8e9ea19221a19112070a4a0c57840a3da8b4`，随后接入 PR #153 的 main，再修复。原始共享 checkout 未修改；修改位于隔离分支 `codex/narrative-intent-closure-01`。
- 原生只读快照：2026-10-10 05:13:50 UTC；PostgreSQL 16.15，数据库 `nf_qidian_learning_20261008_test`，OID `16384`，cluster `7694308142111706022`，snapshot `889973:889973:`。完整原始导出保存于工作区外私有 evidence 目录；没有对原书数据库写入。
- project `qid-learning-prose-01`，Book `book:qinglan-wendao-20261008`，原 Run `book-run:2bf458df-d6ab-441a-abc5-419eb00bb5bc`。四章原稿分别是 Draft Operation `df816504-1cdb-4b69-ba6a-c3e46bb6f006`、`bf1d1a39-b237-4a3c-8622-fa155e587290`、`80f1bfab-e161-405b-a356-1119b562e0b5`、`7e5c1c93-4b94-4a04-b0ec-193924f412bc`。
- PR #151 head `3d523515f8e908672f131179ce02cadad636b9e2`，merge `56b167164d99fa87e57f9146df5266f94b1173c8`。原稿 export 的四个 asset/hash/text hash 与本次原生记录全部一致。PR 当时部署 `06f1a77931dd5795cf94653d71bc09abf131579f`；该时间点四章保存、正式 accepted cursor 0。main 后续 PR #153 的交付记录另有版本，不能混为这四章原始生成或本修复结果。
- 本次配置声明部署 `d13e13b2b240d44da7c2864a16a5c7311d971629`，build `qinglan-repair-d13e13b2b240`；API 进程 cwd 指向该 release。API、Gateway、Planning execution、Book opening 四个部署源文件逐字节匹配该 Git SHA。`/health` 为 `UNAVAILABLE`；未证明全部加载模块及活跃 Pack 都等同该 SHA，更未部署本修复。
- 原书设计 240 章及 40 章交付窗口均未改变。Book Plan 中“止于第3章”是初始执行范围泄漏，不能据此将书改成 3 章或改变后来 40 章授权。

精确字段、全部版本及源码导航在 [native-evidence-chain.json](native-evidence-chain.json)。该文件保存 67 个顺序节点、原生 lineage edge、输出绑定和 46 个 Operation/Effect/Dispatch/Prompt 装配身份；没有用聊天记忆补足资产身份。

## 阅读、归档及历史审计的证据边界

已读取现行 canonical 文档、10 月 4 日审计主报告/改写建议/工程计划、逐资产评价与完整目录导出、PR #151 原稿/文学候选和对应运行记录。完整文件读取/hash、目录 JSONL 解析及 ZIP 完整性检查在 [reviewed-source-inventory.json](reviewed-source-inventory.json)。目录全量读取不是对所有动态 Schema 组合逐项文学合格的声明。

先归档了四份过期或与运行事实混用的设计 proposal，并保存字节 hash、旧路径、归档理由和 unresolved 状态：[design-archive-manifest.json](design-archive-manifest.json)。历史审计、Provider 回执、原稿及所有原生版本未删除。canonical docs 中的过期当前版本/路径随后投影更新；没有新建平行架构文档。

10 月 4 日审计的源 SHA 是 `b1d42e6107d871442baa71823f7c21bfeec841b1`。其 P01–P08 对通用商业技法、资格适用性、Schema、Context 和实际选择边界的判断须逐项对账；不能把当时目录默认当成本书调用的 Prompt。实际原始 46 个 effect 中，38 个 Planning 使用 **System v11**，其余 Memo/Draft 使用 Chapter System v3；实际 Planning template 是 v1，Chapter template 是 v13。本书实际选中的 `knowledge:chapter-causal-cost:v2` 已按作品功能条件适用；它不是强制每章代价的 v1。当前作者/作品 applicability、零变化和作者监督路径已存在，本修复复用这些机制。

## 已证实的根因及传播链

| 节点 | 真实字段及证据 | 判定与边界 |
|---|---|---|
| Author Brief | `8bb703c5…`，hash `774b6cc3…`；`/source_boundaries` 明确工程操作/核验要求不得变成小说任务。idea 要求入门、首次引气、结伴采药和正式外门课。 | 作者确实选择修仙、劳作和任务历练；不能把一切询问、资格或程序性行动判为污染。 |
| Creative Foundation | `528eabd8…`，hash `c681ea48…`；`/constraints/7`：“全部新增人物动机、修行机制与发展结果均为候选设计，不构成已接受事件或人物知识。”`/prohibited_outcomes/0` 禁止把候选写成已接受知识/事实。 | 本顺序链中首次可证实的 **治理文本进入故事约束字段**。生成请求本身带 candidate-only/accepted-history 的 host hard constraint；无法证明模型的内部因果思路。 |
| Theme / World / Cast | Theme `01d50954… /constraints/13` 继续保存候选/accepted 限制；World `bd11fa76…`、Cast `c59b05b5…` 保存未知条件、信息来源及回应范围。 | World 劳作、名额和能力门槛有作者题材依据；这些本身不是工程污染。核验倾向在设计中可观察，但每条人物动机是否由某条系统句子导致，`UNAVAILABLE`。 |
| Book Design | `db9855a3…`，hash `3c0b2c4a…`；`/book_invariants/7,17,28,44` 包含 candidate/accepted-frontier/宿主绑定文字。 | `FormationGeneration.prepare_design` 将 Foundation `constraints` 机械拼接为 `book_invariants`，没有职责区分。这是 **可证实的代码传播/放大**；不是推测模型心理。 |
| Book Plan | `d74c587d…`，hash `ba575…`；`/risk_register/9`：“战略规划被误解为扩大执行权限……当前执行止于第3章……相应冻结任务。” | 执行窗口进入作品风险字段。原命令的 opening topology budget 可达最终 Prompt。3 章是执行配置，不是叙事设计不变量。 |
| Volume / Arc / Group | Volume `a185b627…`；许庭 Arc `358953bc…`、程观 Arc `6981b0a9…`；Group `dbdaaf28…`，其第 1 行 scheduling 明确澄清愿望与未知条件。 | 五/十分钟回应范围与问题整理在上游设计中已形成，先于 Draft。不能仅因相似于权限边界就声称它必然复制某个 Runtime 参数；其具体源句归因仍 `UNAVAILABLE`。 |
| Chapter Mission / Scene / Beat | candidate `a64c95a2…` → activation `af16b192…` → typed Plan `71fb1aca…`，hash `45592498…`。`scene_plan[0..2].goal/conflict` 依次是主动询问、辨认回应边界、整理待核实问题；Beat 保留该动作链。 | 第一章结构性问题已经在计划中，不是 Writer 临时发明的一组 AI 味词。真实约束源、Matrix 行、Arc 贡献和 source_extensions 均在机器证据中。 |
| Narrative State / Memo / Context | genesis State `7348ab08…` 和 Canon `6dfd…` 均 chapter 0；Intent `b49e7ddc…`、Memo `938922eb…` 的 exact Plan hash 都为 `45592498…`。后续每章对应 Plan/Intent/Memo、Context 及 working-manuscript 来源分别冻结。 | Accepted state 没有授予额外人物知识；Memo 按冻结 Scene 放大执行方式。保持 working manuscript 与 accepted Canon 分离，不能把原稿观察自动变成 Canon。 |
| 最终 Prompt / Skill / Knowledge | 46 个 materialization 保存 Pack、System、Skill、Schema、Context、Knowledge exact ref/version/hash。v11 未经过 v8 专有的分阶段 System 投影；跨阶段规则和 host 命令共同可达。 | **可证实的装配污染面**：v11 全部阶段规则注入；身份、修复、窗口、评分选择信息缺少故事意义与输出协议的职责边界。MKAOS 选中内容以本次逐调用记录为准；未获得源作品流入此剧情的证据，不归因于起点原文。 |
| Draft / Literary Revision | 四章 Draft asset/hash 与 PR #151 对齐；文学候选 `5a23cdb3…`、`960c2c24…`、`e349fe26…`、`09fbb5c9…` 保存 base version/hash 与原 Scene 构成。 | 后续局部修订保留源 Scene 的任务目标，不是新的结构规划。不能用它证明任务式情节已根治；作者选择仍属于原生候选机制。 |

完整 hash 均在 JSON 中；表内短 hash 仅供阅读导航。前三项属于 `CURRENT_RUNTIME_FACT`；append-only、精确身份、作者选择和 accepted mutation 边界由代码/测试支持，按相应证据列为 `CURRENT_PROVEN_INVARIANT`。篇幅、执行窗口、Arc 负载和比较策略是 `CONFIGURABLE_POLICY`；旧 frozen Pack 是 `HISTORICAL_COMPATIBILITY`；模型具体如何把权限逻辑转化为五/十分钟人物设定是 `UNRESOLVED_DESIGN_CONSTRAINT`，不据词语相似度升级归因。

## 实际 owner、提交与恢复路径

| 链段 | 当前入口 / owning application / mutation boundary | 持久化、门禁与恢复 |
|---|---|---|
| Brief → Foundation | `api/routers/book_authority.py:1037` formation-runs → `StoryFormationApplication` → `FormationGeneration` → `StoryPlanningGenerationApplication.generate`。生成只产生候选，Story Design / Book Design 决定批准与绑定。 | `AuthorityUnitOfWork` 内原生资产与 Foundation binding；执行 I/O 走 transaction 外 `production_execution_gateway`。candidate/evaluation/author supervision 各自留记录，不由 RuntimeJob 作真相。 |
| Book → Volume → Arc → Group → Chapter | `book_authority/opening.py`、`book_authority/supervisor.py` 协调；`story_planning_runtime/application.py` 生成；`PostgresHierarchicalPlanningAuthority` 验证/激活 typed plan。 | 原生 generation/candidate、asset lineage、input snapshot 表；`plan_change_authority/application.py:185,314,401` 对有界变更 propose/decide/activate；`book_authority/production.py:1955` 绑定新输入快照。没有将新投影变成另一审批 Authority。 |
| Mission → Memo → Context → Draft | `book_authority/supervisor.py:1214` 冻结 Plan；`chapter_authority/handlers.py` `_PlanHandler` / `_ExecutionIntentHandler` / `_MemoHandler` / `_ContextHandler` / `_DraftHandler`；`chapter_plan_views.py:146` 精确 typed plan 投影。 | 原生 Chapter Operation/Attempt/Lease/Fence；`execution_gateway.py` 的 binder 验证 frozen Pack/materialization，`provider_views.py` 先做 typed view，再附加新职责投影；只有真实 owner/UoW 可保存输出。 |
| Draft → Literary Revision | `ChapterAuthorEditingApplication`，`chapter_authority/author_editor.py:148` 的原生会话、候选保存及选择；`author_draft.py` 保存 originating draft 血缘。 | base asset/hash/text hash、scene/realization 契约、版本化候选及作者决定均保持。作者候选不是 accepted Chapter；Book acceptance 原子绑定 ChapterOutcome、Canon/Narrative State 与 cursor。 |
| 外部或提交 UNKNOWN | Command Kernel `command_kernel/external_effect_runtime.py`，而非 Book/Group 复制一套 Effect 状态。 | 原 intent/dispatch/receipt 对账后通过既有 result-repair/runtime-continuation/StepSuccessor；不能换 ID 重发、把新 Prompt 回放算成原 receipt，或改写终态。本次没有调用原书恢复/重发。 |

上述源路径均相对于 `src/novel_forge/`，属于当前源码导航；原执行的 definition SHA/hash 另由 `native_operations` 精确保存。原生取回 52 个 Attempt 与 52 个 Lease（含 fencing token），事务命令没有凭空补造 Attempt。Schema 表的初始迁移见 `storage/migrations/versions/v20260712_0007_postgres_command_kernel_authority.py`；Operation 输出证据 0020、Book production 0034、Plan Change 0041、Pack attempt snapshot 0072、Planning generation/input snapshot 0073、Foundation binding 0100。完整迁移 manifest 检查 198 项通过，本修复未修改已发布 migration。

## 修改与前后机制

| 位置 | 修复前 | 修复后 |
|---|---|---|
| Formation / opening / supervisor / creation runtime | 默认搜索强调 costly agency、reversal/world pressure；candidate/Canon 约束混入创作 hard_constraints；Arc 默认要求 causal transformation。 | 默认方向服务作者意图、人物/关系/观察、作品节奏和安静稳定情境；从新创作请求移除已由 host 强制执行的 candidate-only 文句。Arc 允许作者选择的 continuity/change；明确给定的旧作者请求不重写。 |
| `longform_profiles.py` / selector / artifact resolver | 2.13、v11、旧 Skill/default hash。 | 新当前 Planning Pack **2.14.0**：System **v12**、template **v3**、Pack input/output schema **v2**，long-outline-v4，五类 planning qualification Skill-v4；按 exact binding 选择。旧 ref/version/hash 解析旧原文。 |
| `prompt_methods.py` / v12 System / 六个 root Skill | v11 全量跨阶段 System；部分场景/选题方法默认目标—障碍。 | System 按 Foundation、Book、Volume、Arc、Group、Chapter、World 子阶段取对应方法；共同边界区分作者、虚构规则、叙事设计、治理。知识边界不要求核验场景，程序性与安静叙事均允许有作品依据的实现。 |
| `provider_views.py` / production Gateway | host retry/branch/topology/selection audit 和叙事数据混装。 | 验证冻结源之后生成 `narrative_inputs` 与 `output_protocol`；仅移除已确定的 host 字段，omission pointer/hash 及源/投影 hash 保存于现有 prompt evidence。保留 Context 根结构、Matrix 相对引用、accepted knowledge、working continuity 和 repair finding。不是关键词替换器，不改源资产。 |
| Planning execution rich Schema | 字段说明未限制 constraints/risk_register 等职责。 | 新 materialization 在保存/hash 前附加 `:narrative-intent-v1` 语义契约，约束只能来自作品；Scene/Beat 不强制冲突、奖赏、反转或代价。JSON 数据形状和原生 validator/approval gate 保持兼容；没有新增 DB migration 或平行 owner。 |
| Quality Skill exact hash | main 当前 root quality-review 内容与 v4 默认声明 hash 不一致，Pack 编译被拒绝。 | v4 解析冻结旧文本；当前文本绑定 v5。相应 Review/Evaluation/Screenplay Pack 版本分别更新 1.4.0 / 2.27.0 / 1.2.0。评分内容、策略及四章评分没有改动。 |

主要源码：`book_design_authority/formation_generation.py:131,327`；`book_authority/opening.py:1599,5812`；`story_planning_runtime/search_application.py:34`；`capability_packs/longform_profiles.py:90`；`chapter_authority/provider_views.py:2393`；`chapter_authority/execution_gateway.py:4446`；`story_planning_runtime/execution.py:4449`。以实际函数符号和 Git diff 为准。新 exact artifact/hash 见 [new-binding-manifest.json](new-binding-manifest.json)。

没有自动抹掉现有坏 Scene 或其治理文字：当前冻结计划本身就是作者/Authority 选择过的版本，代码不能凭词语相似度重新赋予其含义。结构性修复应使用已存在的 `PostgresPlanChangeAuthority.propose/decide/activate`、`BookProduction.bind_replanned_input_snapshot`、规划候选/activation 和作者候选选择；新 Chapter Intent/Memo/Draft 绑定新 Plan 及原父链。Literary Revision 的相同 Scene 局部编辑不能代替此流程。240/40 的变更不在该结构重写请求内。

## 必要验证与负面证据

详见 [verification-results.json](verification-results.json)。

- 两组定向离线测试：338 passed、210 passed。覆盖实际 Prompt renderer、Pack/Skill 选择、Work Intent/applicability、知识/Context/working continuity、原生 Plan Change/候选绑定。相反题材样本包括安静家庭叙事、作者明确的程序性调查和修仙；未添加题材 enum、固定章数、统一文风或每章成本策略。
- 最后版本变更后，Pack/Screenplay/Prompt 定向 56 passed；template 说明澄清后 Prompt 45 passed。重复限于实际改动涉及的检查。
- 原生 67 个语义资产经 PostgreSQL JSON 文本按原版本只读取回，完整内容 hash **67/67 MATCH**。初次导出的 Decimal 字符串投影保留；数值类型修正另有只读快照与记录。
- 原始 46 个 Prompt 回放 **45 MATCH / 1 UNAVAILABLE**；38 个新绑定离线反事实装配通过。后者沿原冻输入替换新绑定，不是新 Operation、新小说候选或 Provider 结果。
- 新测试 DB 的 Formation→Foundation→Book/Volume/Arc/Group→Chapter 原生装配保存了 23 个 System v12 materialization；全部 rich Schema 带 narrative-intent-v1，且 final Prompt 与当时原生 provider admission hash **23/23 MATCH**。具体 Pack/template hash 同时保存，不能用版本号替代内容身份。最终 template 文字说明变更另由最终 profile/45 个 Prompt 测试及 38 个反事实装配验证。
- PostgreSQL 定向集成：Plan Change 4 项、atomic candidate activation 1 项 **PASS**；完整 Synthesis Formation **FAIL**。修正夹具的当前权限与精确 Cast/Matrix 引用后，它到达 Chapter/Revision，停在 Scripted Canon 输出 JSON codec，`MODEL_RESPONSE_INVALID` 被原生 effect 记为 `EFFECT_EXTERNAL_STATE_UNKNOWN`。没有真实外部调用；该测试 DB 的失败历史保留，不修改 Canon owner 或原书 UNKNOWN。
- 另选的旧 native PEP 测试 **FAIL**：夹具输出不满足当前 exact realization selector，`PLANNING_REALIZATION_SELECTOR_INVALID` → bounded repair exhausted。这是未闭合的集成缺口，没有降低 selector 或将旧夹具通过声明为新主链通过。
- module / migration / worker / architecture fitness、required-test / console manifest、documentation / instruction / test-reality / historical-reality / proposal lifecycle / generated skills 检查通过；focused Ruff 和 diff whitespace 检查通过。完整无关大规模回归及新 qualification flow **NOT_RUN**。
- 新真实 Provider/模型配对、原书新规划及正文生成、部署/重启、四章重新文学评分、作者候选接纳、正式 acceptance **NOT_RUN**。

测试夹具修改只读取它自己的冻结 Book Cast 并对齐 Group/Chapter 的同一人物 locator；权限补充仅在 test Principal。生产身份/Canon/Unknown gates 未放宽。所有失败数据库/日志 hash 在验证记录中保留。

## 尚未解决及下一次正文验证

1. Chapter 2 规划 repair：Operation `a161a426-f093-4f9b-988b-049bcf9fa836`，Effect `473a3a19-0ec0-4de0-a82c-127f89142006`，Dispatch `b957a0f6-4ed1-4176-bd5e-e8a02d807f8d`。保存的 expected Prompt `6b7cf2be…` 与 reconstructed `62ba505f…` 不符，`UNAVAILABLE`。不得用该次重建解释原模型具体看到什么；原始 stdin 未保留，须原账户/原执行目录的可信证据补齐。
2. 部署健康、全部运行模块与活跃数据库 Pack 的一致性未完成证明；本修复仍是工作树代码，不是已部署效果。
3. 上述两项完整集成失败尚未闭合；23 个装配 hash 通过只证明当前原生规划装配可执行，不证明全 Book/Canon 流程。
4. 原四章的各项程序性细节有完整设计传播证据，但逐个细节的模型内部归因没有证据。未经作者重新选择上游设计，不能承诺它们消失。
5. 当前测试证明语义边界被送入 Prompt/Schema、host 数据投影及旧版本兼容；不证明模型遵守或小说可读性提高。

建议下一次在原 Book 中先由作者确认一个有源的结构修订范围：恢复原 Brief 的近期目标与人物利益，必要时重新选 Foundation/Arc/Group/Scene，保留未受影响的 accepted 边界及 240/40。通过现有 Plan Change/新候选链冻结版本、hash、模型、预算与输入，再生成一个小范围完整正文候选。可在另行授权的相同模型/参数配对范围内比较“旧设计原稿”和“新设计完整场景”，重点看真实行动/修炼/关系是否落实，知识限制是否成为无依据的核验任务；允许作者选定程序性剧情或安静叙事。保存 Provider 回执/usage、候选文本和作者选择，始终不自动接纳。旧稿、文学修订和新结构候选并存。

## 状态

| 要求状态 | 本次证据 |
|---|---|
| CODE_EXISTS | 新边界、投影、版本绑定及兼容解析已经实现。 |
| WIRED | 新当前 Planning profile、selector、preparer、Gateway renderer、现有 evidence 存储路径已连接。旧 live Pack 未切换。 |
| EXECUTED | 离线/Scripted 原生装配已执行；23 个 native Prompt hash 对齐；完整 Book 集成未通过。对应仓库证据上限为 EXECUTABLE（限定已执行的路径），不授予 QUALIFIED 或 PRODUCTION_PROVEN。 |
| LITERARY_IMPROVEMENT_PROVEN | NOT_PROVEN；新真实正文/配对验证 NOT_RUN。 |
