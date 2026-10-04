# Prompt / Skill 与全工程生产链只读审计

固定基线：[b1d42e6107d871442baa71823f7c21bfeec841b1](https://github.com/yuan2go/novel-forge/tree/b1d42e6107d871442baa71823f7c21bfeec841b1)。仓库：https://github.com/yuan2go/novel-forge。审计起始：2026-10-04T13:20:14.040055+00:00（北京时间 2026-10-04 21:20:14）。remote refs/heads/main 在开始时以 git ls-remote 核验。全程从 git archive 的仓库外快照取证；本地用户分支 `codex/wp02-author-approved-run`，HEAD `ceb69fa2ff1c56f07005154bb5797616e933e8c2`，未切换/覆盖/清理，未读取其未提交生产记录作为 main 的运行证据。结束核验见 baseline-end.json；main 若变化仅报告。

## 结论

发现公共生产规则存在范围过宽和作者输入绑定缺口：8项机制问题（含本次全链路补充P08），另有2项历史兼容/旧合同风险登记。最强证据是不可逆代价 task/Schema、固定资格 criteria、章节预备必填，以及 Writer/Quality投影缺字段。**可以确认规则存在并进入指定可达装配链（A+B）；不能确认本次 main 对应的线上 release/真实请求使用，更不能确认它造成某本小说质量差（C未验证）。**

未证明这些约束出自“某次AI开发任务”。少量 blame 可定位首次提交，但没有对应局部任务授权证据。不能将已有冲突规则自动包装为作者选择：已生成/批准 Foundation 也必须回溯 Brief 与适用性；本轮尚无同版本批准产物，未替它背书。

当前默认 chapter Pack 2.9.0 的 system v3/template v7、prose v4、quality v3、chapter-outline v3 和 causal-cost v2 已明显改为按本书选择技法。末次核验 remote main 未变化，用户分支、HEAD和git porcelain路径清单一致（未读取未提交文件内容作哈希，不能据此证明其他进程没有改过其内容）。

没有确认默认全古风、每章笑点、固定十二章、固定人物或世界观。Formation 的 target_chapters 为明确必填1..10000，不是静默十二章；genre/audience 是自由有界字符串，没有在该入口发现未知题材静默落回固定题材。Writer尊重风格的正向路径存在；问题发生在上游硬合同与部分投影/审读基准，而不是“所有Prompt都坏了”。

## 判定标准与证据边界

A 公共处理规则；B 当前作品要求；C 条件技法；D 透明产品默认/技术限制；E 历史样例/一次性要求；F 来源/范围不明。按用途而非目录判定。具体作品输入进入 Prompt 合法；JSON/场景slots不等于全小说固定情节；保持Canon不等于所有小说共享Canon。

代码层能力状态使用 CODE_EXISTS / WIRED / EXECUTABLE / QUALIFIED / PRODUCTION_PROVEN。纯构造器和投影在阻断外部IO的沙箱中 EXECUTABLE；生产调用连接可静态判 WIRED；未取得真实资格、部署与请求证据，不能升级 QUALIFIED/PRODUCTION_PROVEN。下文A=原文存在，B=特定路径装配，C=实际文学偏差，与仓库能力状态不是一套名词。

| 限制 | 分类 | 判断 |
|---|---|---|
| 精确身份/hash、候选与接受事实分离、源表达隔离 | CURRENT_PROVEN_INVARIANT（已读代码检查的局部范围） | 保留；不宣称完整系统所有路径已生产验证 |
| 默认 Pack 版本、当前单消息 XML 装配、仅zh-CN规则 | CURRENT_RUNTIME_FACT（代码） | 部署选择另需核验；非古风或短句等题材要求 |
| 512K Context、64K planning、输出预算/timeout/目标章数 | CONFIGURABLE_POLICY / CURRENT_RUNTIME_FACT | 输入/执行容量不是作品文学规模；入口章数明确，超限失败而非偷偷改章数 |
| legacy prose/quality/causal-cost v1 | HISTORICAL_COMPATIBILITY | 当前默认未选；旧冻结Pack是否仍活跃未知 |
| 不可逆代价、无条件商业结构、固定质量fallback | UNRESOLVED_DESIGN_CONSTRAINT | 不是因为代码存在就成为合理通用文学合同 |

访问：冻结 tracked 代码/config/Skills、相关构造器、指定 git history；不连接DB、不读.env/凭证、不读取原小说/私有作者资料、不运行真实CLI/Provider、不安装依赖。本轮所有输出在仓库外。脚本先禁止socket/子进程/psycopg连接与快照写入，再import纯函数；PYTHONDONTWRITEBYTECODE=1。未知真实值留UNAVAILABLE。

## 实际生产链与决定权

下列所有位置绑定同一SHA，链接指向包内冻结源文件；完整符号行号索引 evidence/symbol-index.json。不是用文档宣称实现。

| 阶段 | 实际入口 / owner / 突变边界 | 内容决定字段与装配 |
|---|---|---|
| 作者Brief | [src/novel_forge/api/routers/content_authority.py:98](evidence/source/src/novel_forge/api/routers/content_authority.py#L98) → ContentAuthorityApplication.admit/execute → codecs._creative_brief | creative-brief-v2 idea/genre/audience/constraints/source_boundaries；v3 author_design；v4 editorial_learning。validate_creative_brief 明确拒绝未知/超界字段，不自动补固定题材。v1是旧商业长篇合同。 |
| 作者追加/采纳 | [src/novel_forge/api/routers/book_authority.py:285](evidence/source/src/novel_forge/api/routers/book_authority.py#L285) → author_supervision → PostgresStoryDesignAssetAuthority | 明确design、hash-bound Brief与作者身份；REQUIRED/DIRECTION、scoped fragments/decisions。作者私有原文不直传Writer，公开适用guidance有独立路径。 |
| Formation | [src/novel_forge/api/routers/book_authority.py:1037](evidence/source/src/novel_forge/api/routers/book_authority.py#L1037) → book_design_authority.formation / formation_generation | frozen brief、generation_policy.target_chapters/title/approval_mode、v3作者选定Foundation。6类Foundation按 required parent graph；task和Schema含P01。 |
| Foundation qualification / BookDesign接纳 | [src/novel_forge/modules/story_design_authority/application.py:179](evidence/source/src/novel_forge/modules/story_design_authority/application.py#L179)、[src/novel_forge/modules/story_design_authority/qualification.py:432](evidence/source/src/novel_forge/modules/story_design_authority/qualification.py#L432) | 生成候选→独立语义判断→Story Design Authority gate/激活；profile按操作固定，P02。批准不自动证明是作者想要的，需反查输入。 |
| 创建输入 / style | [src/novel_forge/modules/book_authority/creation_inputs.py:117](evidence/source/src/novel_forge/modules/book_authority/creation_inputs.py#L117) → creative.style_projection | READY active BookDesign、批准creative/character绑定 → style_profile:narrator/pov/genre_conventions/constraints/original_examples；整体creative_style放facts，voices与realization policy保存，非外部参考表达。 |
| Book/Volume/Arc/ChapterGroup/Chapter规划 | [src/novel_forge/modules/story_planning_runtime/execution.py:2291](evidence/source/src/novel_forge/modules/story_planning_runtime/execution.py#L2291)、[src/novel_forge/modules/story_planning_runtime/execution.py:5254](evidence/source/src/novel_forge/modules/story_planning_runtime/execution.py#L5254) | frozen_inputs、author scope projection、narrative intelligence、exact Mission/scene/knowledge/Arc refs；候选由Hierarchical Planning/Plan Change激活；未来计划不作已发生事实。 |
| World/Actor条件路径 | world_preparation / world_sampling / worldbuilding | 世界proposal、独立评价、actor_0..2，冻结world action/candidate/task/policy；NO_OP/DEFER可用；无真实对象，本轮完整constructor源、未造动态slice。 |
| Chapter准备 | [src/novel_forge/modules/production_preparation/service.py:256](evidence/source/src/novel_forge/modules/production_preparation/service.py#L256) → plan normalize | 输入身份/准入→P03按章号/功能的required profile；Writer view P04。 |
| Memo / Retrieval / Context | chapter handlers、creative_memo、provider_views/context pack | accepted history、query proposal、extract unit选择/fidelity；当前memo cost可null，非强制成本套餐；知识按scope/governance选择。 |
| Pack与Skill选择 | [src/novel_forge/modules/capability_pack_authority/application.py:398](evidence/source/src/novel_forge/modules/capability_pack_authority/application.py#L398)、runtime:655、prompt_methods | 合同精确匹配/单一fallback，歧义failclosed；每次只取一个 skill，不是所有注册Skill全文同时注入。reader.promise当前qualification-v2选topic；规划long-outline v2；按Shared+当前method投影。 |
| Writer/Reviewer/Reviser | [src/novel_forge/modules/chapter_authority/execution_gateway.py:4282](evidence/source/src/novel_forge/modules/chapter_authority/execution_gateway.py#L4282)、handlers:1390、review_window | 1system→2单一skill→3required_knowledge→4条件tool_policy→5渲染template/task/context→6stage contract→7output_schema。v7writer accepted-history投影；review exact quote+author targets；targeted revision有独立范围/quote合同，保留无关slots。 |
| Quality / 回改 | [src/novel_forge/modules/chapter_quality_authority/context_views.py:160](evidence/source/src/novel_forge/modules/chapter_quality_authority/context_views.py#L160)、content_quality_loop.domain | 5组QualityContext，fixed dimensions；P05风格基准缺项，P06有条件fallback；只blocking失败推repair，商业reward/hook/charisma单项默认非blocking。 |
| 接纳 / 后续 | [src/novel_forge/modules/book_authority/production.py:1153](evidence/source/src/novel_forge/modules/book_authority/production.py#L1153)、commit_acceptance:1299 | 锁定selected outputs，具体作者审批、grounding、ChapterOutcome/StoryState/Canon/projection一体commit；accepted cursor给后续章使用。不能用Reviewer分数代替Book接纳。Reader outcome为SHADOW，意见不直接改active plan。 |

这些owner使用 AuthorityUnitOfWork/PostgreSQL repositories 作持久化：content application:90/119，StoryDesign application:206，Book accept:1299/1494；repositories在 owning UoW里不是另一个内容决定者。相关表迁移包括 0038 story_design、0051 book_design、0071 capability_pack、0120 foundation_generation、0148 author_supervised_design、0119 grounded_chapter_acceptance；原始manifest和迁移源在evidence/source。未连接实际数据库，不能声明迁移已部署。

## 模型发送边界与额外指令

| 边界 | 代码与进入内容 | 已确认 / 缺口 |
|---|---|---|
| OpenAI | [src/novel_forge/modules/provider_control/openai_v2.py:22](evidence/source/src/novel_forge/modules/provider_control/openai_v2.py#L22) responses.create(model,input=envelope.input_text,reasoning,max_output_tokens...) | 单字符串input；XML system标签并非API system角色；无独立instructions/response_format。output Schema在业务串中，解析仍有host validator。未发送。 |
| DeepSeek | provider_control/deepseek.py:124；[src/novel_forge/modules/production_execution/provider_admission.py:56](evidence/source/src/novel_forge/modules/production_execution/provider_admission.py#L56) | 单user message，JSON object或STRICT_TOOL；submit_structured_result说明及投影schema全文已导出。strict剔除部分native限制，主机验证保留；不把它误作文学风格变化。 |
| Codex CLI | production_execution/backends.py:1830..1887；codex_configuration.py:10 | stdin input_text、--output-schema投影、--cd固定目录、--ignore-user-config/--ignore-rules/--ephemeral、project_doc_max_bytes=0、skip_host_skill_discovery=true、memories/hooks/apps等禁用。静态支持“排除宿主开发指令”，没有真实CLI版本/argv/receipt，不能断言实际已加载/未加载任何宿主AGENTS。 |
| Source intelligence | [src/novel_forge/modules/source_import/execution.py:2045](evidence/source/src/novel_forge/modules/source_import/execution.py#L2045) → [src/novel_forge/modules/chapter_authority/execution_gateway.py:4597](evidence/source/src/novel_forge/modules/chapter_authority/execution_gateway.py#L4597) | separate system+精确method Skill+template+target/source_analysis_input+schema+版权尾指令。源证据只作分析；不是小说Writer默认参考文本。 |
| 通用Agent/Longform wrappers | agent_runtime.coordinator / agent_collaboration.application / production_execution.domain_execution | generic candidate说明CODE_EXISTS；work_order/instruction/transcript可能动态改变内容，真实绑定UNAVAILABLE。不得虚构它们已主导当前章写作。 |

所有实际发现的实体发送端（SDK、HTTP、CLI）均映射到装配或动态payload resolver；embedding专用contract、Source路径及generic wrappers已单列。没有观察真实请求，代码中多个调用不能冒充多个已发生生产请求。

## 输入传播表

“有”表示源码或合成装配确认，不表示模型理解正确；“间接”表示已接纳方案而非原文继续传递。

| 输入 | 入口/保存 | 规划 | Writer | Reviewer/Reviser | 覆盖或缺口 |
|---|---|---|---|---|---|
| 题材 | v2 genre自由字符串；v1 target_genre | frozen Brief→creative/world/plan | 经过creative_style/任务/accepted world，不保证原Brief整份每次注入 | frozen story data与author guidance间接 | 无发现genre未知时静默fallback；泛化规则P01-P03仍并行 |
| 受众 / 主题 | audience/idea/constraints、theme_contract | Foundation/theme/reader promise | 当前章目标、世界人物、reader promise间接 | review目标/quality分组间接 | promise资格仍固定REWARD/SERIALIZATION；目标语义是否正确转译无真实样本 |
| 风格 / 语气 / 句式 | v2 constraints，v3author fragments；creative style_profile；style_policy | frozen inputs与author decisions有 | safe_summary/facts正常可达；ChapterPlan.style_constraints/独立顶层constraints可丢 | 普通review/revision context可保留；source_originality无风格基准 | P04、P05；标准compiled style路径不等同constraints-only反例 |
| POV / 叙述方式 | constraints/style_profile.pov/typed point_of_view | Character/scene knowledge contract | point_of_view与creative_style、voices有 | actor/POV边界与候选quote有 | 未支持所有叙述类型枚举不等于禁止；POV未因独立voice跳过而整体丢失 |
| 时态 | 无独立Brief tense字段；可写constraints/author guidance | 自然语言保留，需模型/计划表达 | 若仅plan.style_constraints承载则P04 | 自然语言路径有；没有专用保证 | 产品字段缺口，不以“未实现字段”自动定污染 |
| 篇幅 / 章数 | explicit target_chapters1..10000；target_word_count/platform_profile | bounded Book/plan依授权 | target_word_count有 | quality structural target count；platform length明确冻结 | 输出token/Context容量是技术限制；未证明固定12；裁切不是可接受静默缩书 |
| 节奏 / 开篇 / 收尾 | constraints/章功能/reader experience | plan具体化 | frozen slots/obligations/creative memo | 普通review新合同可不罚无reward/hook | P02-P03资格/结构硬约束优先限制表达 |
| 人物 / 世界 | idea/author design +批准world/character | typed parents，必要CURRENT细节；不无限填远期 | exact actor/voice/factscope | Canon/knowledge判断 | Foundation character.wound/false_belief等全非空、cast max12是有界候选合同；大群像扩展路径未离线验证，不能把它宣称全书只能12人 |
| 作者禁忌 / 允许与建议 | constraints/prohibited_outcomes；REQUIRED vs DIRECTION | exact scope/hash/decisions | prohibited_outcomes + publicguidance | author_design_review_targets + bounded preservation | strength/语义执行未模型验证；AUTHOR_ONLY原文隔离合理，公开guidance丢失另需实物核验 |
| 参考作品 / 资料 | source_boundaries / governed Source assets | 只approved abstraction / editorial-learning当前scope | Context可用知识，不读raw source | source/originality checks | 真实KnowledgeCard与选择scope未知；P07仅上游特定方法 |
| 可选技法 | Craft scope/adopt/omission、currentmemo null | typed translations/strategy、prerequisite/contraindication | realization slots按选定策略，非全部Craft常驻 | NOT_USED/UNKNOWN/约束适用性 | 当前选不使用可在Prompt说明不罚；资格层仍P02。无真实选择库，不能排除不适用Card被错误采纳。 |

作者缺项时：Brief v2必填idea/genre/audience/constraints，其他合理细节由本书授权Foundation规划；不是要求作者填完所有人物世界。超界/未知字段显式拒绝、未发现题材默默替换；输入内部语义矛盾主要仍交模型和后续gate，尚无通用显式冲突优先诊断证据。不得凭模板“respect author”宣称语义已经解决。

## 问题清单

### P01 · Foundation / 作品方案形成

严重性：高；置信度：高（规则与装配）；历史任务来源未确认。

原文或精确代码事实：

````text
Design an earned ending direction with irreversible costs, required closures and forbidden shortcuts; this is future intent, not a predetermined accepted event.
````

固定SHA定位：[src/novel_forge/modules/story_planning_runtime/foundation_generation.py:160](evidence/source/src/novel_forge/modules/story_planning_runtime/foundation_generation.py#L160)；[src/novel_forge/modules/story_planning_runtime/foundation_generation.py:57](evidence/source/src/novel_forge/modules/story_planning_runtime/foundation_generation.py#L57)。

生效条件：所有 ending.intent.generate；theme.candidates.generate 同时使用 costly character decisions 与必填 choice/cost。既有 Formation 选定此阶段时，不受 genre/audience 条件分流。

为何不合理：新 Skill 已说技法服从本书，但 task 又无条件要求不可逆代价。ending Schema 的 protagonist_cost 为非空字符串；theme choice_tests 每项 cost 非空且至少1项。“最终有后果”可以通用，“一定不可逆牺牲”不是所有作品目的。 应有作用范围：当前书授权的结局/主题策略；不是公共 Foundation 强制审美。 影响作品：无损成长、守成、开放式结尾、观察式现实、轻喜剧等不选择不可逆代价的作品。

作者决定权：作者反向要求仍原文保留，公共 task 也保留，形成冲突；不能证明模型最后选了哪方。

证据强度：A 确认；B WIRED 且 SYNTHETIC 装配确认；真实请求/实际生产激活未观察；C 文学效果 UNAVAILABLE。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：先改 foundation_task；同步 ending/theme Schema 及 Foundation validators，使用现有 author constraints 与已接纳方案判断适用性，允许不适用，不用空字符串伪装代价。

验证：同模型调用零出站地渲染两种合法作者目标；不使用不可逆代价时 task 与 Schema 都允许；有作者明确选择时完整保留。

### P02 · 层级规划 / 独立语义资格门

严重性：高；置信度：高（字段和门禁）；单一 criterion 的文学解释置信度中等。

原文或精确代码事实：

````text
"PRESSURE_ESCALATION", "IRREVERSIBLE_CHANGE", "CLIMAX_PAYOFF_COST", "NEXT_VOLUME_BRIDGE"
````

固定SHA定位：[src/novel_forge/modules/story_design_authority/qualification.py:330](evidence/source/src/novel_forge/modules/story_design_authority/qualification.py#L330)；[src/novel_forge/modules/story_design_authority/qualification.py:432](evidence/source/src/novel_forge/modules/story_design_authority/qualification.py#L432)；[src/novel_forge/modules/story_planning_runtime/execution.py:2291](evidence/source/src/novel_forge/modules/story_planning_runtime/execution.py#L2291)。

生效条件：required_qualification_profiles 按 generator operation 选固定 criteria；narrative_semantic_evaluation 逐条判断；qualifier 不按当前作者技法选择过滤；strict门禁与AUTHOR_ADVISORY不同，见本次补充。Volume schema 必填非空 irreversible_change/midpoint/climax/settlement/next_volume_bridge。

为何不合理：严格独立资格要求全部 frozen criteria PASS，合法 verdict 仅 PASS/FAIL/INSUFFICIENT；不适用不能表达。SERIALIZATION_CAPACITY、REWARD_REACHABILITY 名称本身不是爽文定罪，但与硬结构/不可逆字段和无适用性通道合起来，使非升级、非连载或终卷目标无法自然表示。 应有作用范围：当前书/Volume 所选择的商业、情绪或戏剧目标；确有到期义务仍必须验收。 影响作品：独立短篇/中篇、非连载、静态群像、终卷无后续桥、非线性/开放结构、拒绝不可逆变化的卷。

作者决定权：作者 Brief 可自由输入；后面的 profile 集合与 Schema 不因此改变。Reviewer 不需套用旧 Skill 全文也会收到这些 criteria。

证据强度：A+B 静态 WIRED；volume required 字段 SYNTHETIC 断言；未伪造独立 evaluator verdict/生产 receipt；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：在已有 qualification profile 与 output-schema/validators 层做版本化适用性，不另建平台。以当前目标解释 reader promise，给非连载/终卷/无代价一个正式合法表示；不要把缺证据改成 PASS。

验证：同输入只改变串行升级/不可逆策略与终卷标记，选定 criteria 应反映选择；不适用不会触发 repair；已适用硬约束失败仍阻断。

### P03 · Chapter 输入预备 / 章节结构合同

严重性：高；置信度：高（存在与阻断）；hook 可以宽解释，不证明必须悬崖结尾。

原文或精确代码事实：

````text
BASE_REQUIRED_FIELDS = ("title", "premise", "chapter_objective", "scene_sequence", "chapter_hook")
if chapter == 1 or function in {"opening", "golden_opening"}:
    required = BASE_REQUIRED_FIELDS + ("conflict_chain", "reader_promise_actions", "protagonist_charm_mechanism", "information_reveals", "next_chapter_bridge")
````

固定SHA定位：[src/novel_forge/modules/chapter_authority/chapter_plan_views.py:65](evidence/source/src/novel_forge/modules/chapter_authority/chapter_plan_views.py#L65)；[src/novel_forge/modules/production_preparation/service.py:256](evidence/source/src/novel_forge/modules/production_preparation/service.py#L256)；[src/novel_forge/modules/chapter_authority/chapter_plan_views.py:126](evidence/source/src/novel_forge/modules/chapter_authority/chapter_plan_views.py#L126)。

生效条件：ProductionPreparation READY 后按 chapter/function 选择 strict profile；第1章不论 quiet_observation 仍走 opening；genre/platform 只记入 profile，未改变 required_fields。

为何不合理：身份、场景单元和目标是接口；非空 hook、主角魅力机制、ordinary 的 antagonist_pressure/suspense_curve 等是创作内容。不能以“可以随意填余韵”代替正式不适用。ending 分支还要求 next_chapter_bridge。 应有作用范围：书/章已选择的开篇、悬念、对抗及衔接策略。 影响作品：慢热群像、无中心主角、低冲突观察章、无反派章、无悬念收尾、独立终章。

作者决定权：作者章节功能 quiet_observation 也不能让第1章避开 opening 字段；空 chapter_hook 在纯 normalization 被阻断。

证据强度：A+B 静态生产准备调用；SYNTHETIC quiet-opening-profile 与 empty_hook_rejected；无实际 READY / BLOCKED 运行 receipt；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：先调整已有 profile.required_fields 的内容适用条件和章节结束目的表达，再同步 schema；保留身份、可执行任务和连续性验证，不把缺失的必要计划放行。

验证：首章为观察章/普通章无反派/独立终章分别可正式标不适用；对作者选定悬念仍检查；不允许仅填“无”通过伪约束。

### P04 · Writer 计划与风格投影

严重性：高；置信度：高。

原文或精确代码事实：

````text
build_draft_plan_view 的白名单没有 style_constraints；build_draft_style_view 只输出 asset_version_id、safe_summary、structured_facts。
````

固定SHA定位：[src/novel_forge/modules/chapter_authority/chapter_plan_views.py:224](evidence/source/src/novel_forge/modules/chapter_authority/chapter_plan_views.py#L224)；[src/novel_forge/modules/chapter_authority/chapter_plan_views.py:285](evidence/source/src/novel_forge/modules/chapter_authority/chapter_plan_views.py#L285)；[src/novel_forge/modules/chapter_authority/provider_views.py](evidence/source/src/novel_forge/modules/chapter_authority/provider_views.py)；[src/novel_forge/modules/chapter_authority/handlers.py:1390](evidence/source/src/novel_forge/modules/chapter_authority/handlers.py#L1390)。

生效条件：正常 draft 从 normalized plan 构造 task view；Context 为 draft 跳过 chapter_plan/style_policy，因其预期已在 task 中。独立 operator style_policy 虽接受顶层 constraints，若其 summary/facts 没重复，投影不传。

为何不合理：存储和 normalization 保留要求，正文投影丢失。不是文学偏好争议，而是已有合法字段没有送给 Writer；再强调“服从作者”无法恢复丢失值。 应有作用范围：已有本书/本章作者约束，应原样随适用范围进入阶段输入。 影响作品：只在 ChapterPlan.style_constraints 声明时态、句式、语气的所有作品；只在独立 style_policy.constraints 声明风格的作品。

作者决定权：两个合成 marker 在最终 draft 均消失；Foundation 标准编译路径会将 creative_style 包进 facts，所以不能说所有风格都丢失。author_design_guidance 另一通路存在。

证据强度：A+B WIRED + SYNTHETIC 丢失对照；同 safe_summary/facts 风格在 draft/review/revision/rereview 都保留；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：修复现有 build_draft_plan_view/build_draft_style_view、production_preparation.service._context_candidate 与 Context 去重假设，保留 style_constraints/constraints 及其版本/范围；不用新增题材枚举或 Prompt 套餐。

验证：单变量 marker 对照；从真实已批准 style source 到四阶段查约束与身份；冲突时显式保留并诊断，不静默覆盖。

### P05 · style_drift / anti_ai 质量审读与修订依据

严重性：高（anti_ai）；中（style_drift 非阻断）；置信度：高（上下文缺项）；实际审美误判为待核验。

原文或精确代码事实：

````text
SourceOriginalityQualityContextView 含 revision_text、source_governance、context_manifest、source_isolation_result、copyright_boundary、governed_segment_identities，但没有本书 style_profile/style_policy 内容或 author intent。
````

固定SHA定位：[src/novel_forge/modules/chapter_quality_authority/context_views.py:160](evidence/source/src/novel_forge/modules/chapter_quality_authority/context_views.py#L160)；[src/novel_forge/modules/chapter_quality_authority/domain.py:49](evidence/source/src/novel_forge/modules/chapter_quality_authority/domain.py#L49)；[src/novel_forge/modules/chapter_authority/provider_views.py:805](evidence/source/src/novel_forge/modules/chapter_authority/provider_views.py#L805)；[src/novel_forge/modules/content_quality_loop/domain.py:181](evidence/source/src/novel_forge/modules/content_quality_loop/domain.py#L181)。

生效条件：固定 quality_source_originality 请求 dimensions 包括 originality、anti_ai、style_drift；通用 Context quality_* 分支跳过全部 segments，实际任务 quality_context 成为唯一故事判据。

为何不合理：检测“漂移”需要本书风格基准。共享 Skill 虽要求按 author intent 审读，但该投影没给出内容。可能依靠模型默认审美解释 anti_ai；不能证明它一定禁长句或修回套路。 应有作用范围：与当前书已批准风格、作者意图和当前候选比较；原始参考表达仍隔离。 影响作品：克制长句、刻意重复、诗性、非线性等容易与通用“AI味”印象混淆的作品；所有需要真实风格一致性判断的作品。

作者决定权：合成 style marker 在 structural 出现，在 source_originality/commercial/longform/platform 不出现；其中后3组未必需要完整风格，不据此单独判错。style_drift 非 blocking；anti_ai 是 blocking，只有实际失败及合法 evidence 才能产生修订任务。

证据强度：A+B WIRED+24快照中的质量对照；未执行模型判断、修订任务或接纳；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：将现有已批准风格与适用作者目标的精简有源投影放进相应 QualityContext；缺基准时不足证据，不用通用禁词表代替。跟随修订输入保留同一基准。

验证：同段落改风格目标：对应style_drift/anti_ai 输入跟随变化；合意风格不能只因技法而触发修订。缺基准时给出明确不足证据；匿名文学验证另行授权。

### P06 · 质量 deterministic fallback / 技术阈值

严重性：中（条件性）；置信度：高（离线fallback）；当前部署发生频率未知。

原文或精确代码事实：

````text
score = round(max(0.0, min(100.0, 100.0 - max(0.0, average - 36.0) * 2.0)), 2)
"PASSED" if score >= 70 else "FAILED"
"PASSED" if average <= 270 else "FAILED"
````

固定SHA定位：[src/novel_forge/modules/chapter_quality_authority/context_views.py:102](evidence/source/src/novel_forge/modules/chapter_quality_authority/context_views.py#L102)；[src/novel_forge/modules/chapter_quality_authority/domain.py:568](evidence/source/src/novel_forge/modules/chapter_quality_authority/domain.py#L568)。

生效条件：没有可消费的 exact target/dimension calibrated evidence 才进入 fallback；已校准 Provider evidence 优先。

为何不合理：compile_quality_policy 接受 readability/maximum_average_paragraph 等覆盖，但 fallback 固定70/270；长句评分还固定36基点。结果可能把书选定长句当可读性失败。并非所有当前真实 Provider 请求都走这里。 应有作用范围：显式质量/阅读设备配置；文体相关阈值与建议不宜伪装普适文学真理。 影响作品：合法长句、长段及非移动端优先作品；仅相关 fallback。

作者决定权：合成配置 readability=10，句均60，score52仍FAILED；证明覆盖未消费。readability blocking；mobile/paragraph 本身非blocking。

证据强度：A+B 条件 WIRED+SYNTHETIC _evaluate；真实 calibrated precedence 静态确认；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：让 fallback 消费编译后的配置；固定指标作为可解释诊断/适用作品策略，避免覆盖明确文体目标；保留客观完整性检查。

验证：同指标不同合法阈值改变 verdict；有 exact calibrated evidence 时仍优先；设备模式/文体不得由隐蔽36基点替作者决定。

### P07 · 条件上游专业资料分析 Skill

严重性：中（条件上游）；置信度：高（原文/条件加载）；下游效果待核验。

原文或精确代码事实：

````text
- 多学科知识只能增强可信度，不能替代爽点和冲突。
- 禁止让专业合理性破坏追读和情绪奖励。
````

固定SHA定位：[skills/multidisciplinary-knowledge/SKILL.md:63](evidence/source/skills/multidisciplinary-knowledge/SKILL.md#L63)；[src/novel_forge/modules/source_import/methodologies.py:42](evidence/source/src/novel_forge/modules/source_import/methodologies.py#L42)；[src/novel_forge/modules/source_import/execution.py:2045](evidence/source/src/novel_forge/modules/source_import/execution.py#L2045)。

生效条件：SourceMethodologyRegistry 精确选择 multidisciplinary-knowledge 时全文注入 Source 分析；分析目的本可由当前任务指定。必须 Observation→抽象/审核→Knowledge选择后才可能间接进入写作。

为何不合理：专业可信度也服务严肃/出版/硬科幻目标；这里把商业爽点/追读优先性写成无条件禁令。不是当前 Writer 默认必选 Skill。 应有作用范围：当本次明确面向追读/情绪奖励作品时启用；其他目标应按需求权衡可信度与阅读体验。 影响作品：本次选择该资料方法的严肃现实、可信度优先硬科幻、非商业作品。

作者决定权：上游约束可能压低专业目标，但未取得本书 Observation/Card/选择 lineage，无法证明下游已经覆盖作者输入。

证据强度：A+B 条件静态 WIRED；无 Source真实请求、批准知识/Writer引用；C 未验证。

对应修改层（完整方案见 ENGINEERING_OPTIMAL_CHANGE_PLAN.md）：修改商业绝对句与操作流程第8项，并核验本次任务目标实际进入Source输入、Card适用性及后续选择；保留安全、来源和不把知识变成无关讲义的原则。

验证：专业资料分析目的只改变商业/可信度取舍，方法输入随之改变；源表达仍不得进入Writer；不将专业准确性降级为普遍次要。

### C01 / C02 · 历史兼容和声明合同风险

C01：旧 prose v1/quality v1/chapter-outline v1 无条件商业reward/hook、成本和Markdown自检等完整原文在汇编；旧causal-cost v1为CONSTRAINT且“Every decisive chapter action ... irreversible cost”。当前默认已选v4/v3/v3与knowledge v2，不能称这些是当前默认。resolver仍能精确解析历史版本，若数据库ACTIVE旧冻结Pack仍有条件性生效；实际选择未知。版本处置先核验release/attempt frozen hash，避免改历史字节或误删兼容证据；新的选择应使用已修正版本，旧请求不应偷偷换Prompt。

C02：目录 schema:chapter-plan:v1 required=[chapter_goal,conflicts,scenes,ending_hook] 且conflicts minItems1/hook minLength1。声明在目录可达，但实际rich Provider schema有另层构造；不能据此断言这一旧schema就是每次最终response format。把它作为条件旧接口偏好风险登记，当前生产预备更强证据见P03。

### 合理规则与应保留资产

当前 prose-generation-v4：按本书voice选择叙事距离/句子节奏/细节；不强求每个scene reward/cost/reversal。quality-review-v3：taste、uncertainty与硬冲突区分，literal quote由host定位，不能伪称人类批准。chapter-outline-v3：当前Mission和知识边界，NO_OP/DEFER可用。long-outline-v2：commercial escalation/rewards/cliffhangers明确为作者选择项。topic/world/character/narrative-beat现版服务当前Foundation，不固定朝代/职业/结局；新人物Skill允许保持信念/未解决矛盾，不强求次次代价。

现有causal-cost v2原则、Canon/Book接纳边界、source隔离、schema-only交付、scene slots顺序与精确引用、失败封闭、bounded revision保留无关内容均应保留。Slots是执行接口，不等于小说必须使用固定冲突套路。资料分析/平台/Screenplay等专用Skill按实际源任务/平台或改编范围使用即可，不因有“爽点”“商业”词删除专用能力。reader-feedback现版SHADOW及作品承诺判据应保留，观察不直改故事。

## 少量历史核验

只对现有问题的foundation任务、qualification、chapter profile和draft view做blame。原始line-porcelain及指定提交stat保存在evidence/history，历史证据与当前装配分开。

Foundation任务可追到 bbd59eb3f629a19499c5c79a2044a1b1c6081b96（2026-09-07，formation/Foundation治理生成提交）；Volume/profile早期规则和draft白名单也各有记录。提交主题只说明代码改动，未取得“只针对某本书/十二章”的原始任务授权，故不确认污染的单次开发成因。当前确有不合理范围，不需要推断提交者身份。历史存在修正：当前Skill和knowledge已软化；剩余任务/Schema/门禁没有同步全部软化，是冻结代码可见的层间不一致。

## 离线验证与覆盖

使用既有venv，不安装；外部快照import前设置IO阻断。两个审计输入（严肃现实群像与轻松幻想冒险）是SYNTHETIC，均符合现行v2字段，不替项目新增题材。只改变风格/不可逆策略等对照，用真实固定assembler，不走生产admission，不生成小说，不构造真实qualified receipt。

24份快照：每个输入包含creative/theme/ending 3阶段、draft/review/revision/rereview 4阶段、quality 5阶段。独立阶段方法12种；shared core assembler1种被实际离线执行。静态还追踪hierarchical、world/actor、Memo/Context/Retrieval、design evaluator、agent session、reader outcome、longform review、screenplay、Source与generic wrappers。**静态映射不等于这些路径全部离线执行。**

41个小型断言全部与预期机制匹配（evidence/checks/results.json）。这些包括发现缺陷的反例，PASS表示复现预期，不表示系统通用性通过。记录：style正常summary/facts路径贯穿四阶段；反向作者目标与不可逆task共存；plan/style顶层marker丢失；quiet首章仍强制魅力字段；空hook被拒；volume不可逆必填；cost v2为PRINCIPLE、memo cost nullable；source_originality缺风格，structural保留plan风格；fallback readability覆盖不生效。

脚本初次扩展Quality对照误用quality_context_view而非实际quality_context，出现2项检查不符；核对真实caller后更正审计脚本并重新执行，未改变生产源码/期望来追求PASS。最终全部结果来源于正确参数，脚本可审查。本轮未执行docs/runtime-operations全矩阵：NOT_RUN；只读审计不声称生产完成/QUALIFIED。

REAL_CAPTURE=0；RECONSTRUCTED=0；SYNTHETIC=24；真实模型/付费Provider调用=0。没有同SHA、同冻结作者目标/输入、模型配置、实际请求与接受正文的共同身份，因此文学效果未验证；不使用旧报告、不同分支或样例正文代替。

## 完整性统计与未完成范围

| 项目 | 数量/状态 |
|---|---|
| 默认resolver与7种生成profile联合catalog | 196个精确kind/ref/version/hash身份（不同Pack scoped同ref/version不混同） |
| Prompt/Skill注册身份 / 不同源文件 | 45 / 42；正文均完整读取、全文导出 |
| 条件Source methodology | 7身份，全文导出；与目录重复源只存原件一次 |
| 目录Schema | 81；完整解析/导出；非都直接送Provider |
| 额外纯构造记录 | 103；包含103记录中的1条默认Chapter dynamic-slice缺失原始失败 |
| 独立阶段离线输入 | 12stage methods × 2输入 =24；不是24真实请求 |
| 小型必要断言 | 41/41机制预期匹配 |
| 源证据文件 | 178（最终counts.json核对） |
| 全字段/动态语义审查 | 重点核验改变创作边界字段；巨大动态Canon/Planning变体未逐实例渲染，源构造逻辑完整保留 |

完整全文、身份/调用覆盖和逐资产合理/有问题/条件适用/待核验评价见PROMPTS_AND_SKILLS_FULL.md、inventory.jsonl、ASSET_EVALUATIONS.md。对已证明不自动注入的旧/示例路径单列evidence/unbound-and-demo-assets.json。所有资产全文检查文件哈希与固定snapshot一致；JSON组装schema是纯构造序列化内容，不能称原始生产请求字节。

关键缺口：数据库ACTIVE released Pack/自定义catalog，真实style/quality/platform配置，agent动态instruction/tools/transcript与Skill内容，真实CLI/workdir/config receipt，world/actor/craft冻结决策与Chapter realization slices，retry/repair/resume真实运行receipt，同版本author objective→最终正文。Chapter默认schema constructor需Frozen Narrative Realization，不填未知对象；原失败evidence/generated/CHAPTER.planning.schema.error.json，源代码完整导出。真部署/DB未访问不是不存在。

retry/repair/resume：static frozen_context_retry核验exactproject/book/inputs及range/policy；repair用原候选与验证report hash，bounded revision不应自动回模板；resume仍从frozen attempt与durable evidence取内容。没有找到正式新路径静默落回样例小说的证明；没有离线完整执行状态恢复，也不能宣布所有恢复路径已排除污染。旧frozen Pack与错误已接纳上游内容仍会被保留，这既是证据不改写原则，也需要新授权纠正，不能靠replay洗掉。

## 全工程修改建议与验证设计

按用户追加要求，本报告不再把建议限定为局部或最小改写。完整架构、职责、合同、输入传播、审读回改、持久化、版本迁移、恢复与验证见 [ENGINEERING_OPTIMAL_CHANGE_PLAN.md](ENGINEERING_OPTIMAL_CHANGE_PLAN.md)。相关完整指令建议见 [REWRITE_PROPOSALS.md](REWRITE_PROPOSALS.md)。

推荐顺序：先明确本书有效创作要求与规则适用性（W1），同步修改Foundation/资格、层级/实现合同、投影/Context、质量/修订（W2/W3/W4/W6），再统一Prompt/Skill/Pack版本（W5），核对接纳与后续（W7），最后处理真实release、旧书兼容、恢复与受控文学验证（W8）。这不是只修七个局部字符串，也不是重写一套新Authority。

现有公共能力继续有效：权限、版权、精确身份、事实连续性、候选与接受分离、必要接口、限定修订、UNKNOWN调和及原子接纳。作品差异由当前输入与批准方案决定。完整方案的实现和验收全部NOT_RUN；本轮机制检查不代表修改已完成。

审计文件不是新运行Authority；没有写回生产Prompt/代码、连接DB、调用Provider、修改作品状态或commit/push/PR/merge。

## 补充：字段丢失首点与开发约束

P04的独立style_policy.constraints路径，生产预备 service._context_candidate:650/775 首先只投影safe_summary/structured_facts，尚未进build_draft_style_view就已经丢顶层constraints。因此修复必须包含该既有候选投影点；只在下游补一个不存在字段不足以完成修复。Foundation标准编译会把全部profile放creative_style facts，正常路径仍可用。

相关tests/unit/test_chapter_plan_fidelity.py:292要求opening缺reader_promise_actions必须抛错，维护层确实锁定P03某些商业语义；这不是测试文本进入模型。fixture含cost/public promise/irreversible示例：chapter handlers.DeterministicFixtureChapterProvider:94明确external_effect_backed=False；planning_fixture_response在scripted路径由authority_dependencies:1098选择。这些是模拟输出，不是正式paid模型fallback或默认某本小说。测试/fixture登记见evidence/development-and-fixture-boundaries.json；本轮未执行它们。测试对新Skill可选技法有正面校准线索，但本轮结论用当前源码与自己的小型装配，不借用历史PASS。

最终核对：196目录资产、45注册文本身份（42不同源）+7条件源方法（合计48不同文本源）、103纯构造记录（102成功+1显式失败）、16内联说明/门禁/作者入口、27装配/发送/对照身份调用位置、5访问缺口，inventory共354记录。全文原字节复制 178个源文件；24 SYNTHETIC请求、原41机制断言及本次7个纯构造检查（合计48）。调用清单包括无模型input的CLI版本probe与只重建producer identity的sampling点，已经单列，不能按27计真实模型调用。

## 作者界面入口补充

已完整阅读并导出 web/admin/app/features/production/CreativeInputPanel.tsx。genre/audience/idea为空待作者填写，constraints/source_boundaries逐行trim后原义提交；目标章数有可见1..10000输入，UI初值1、候选数2，是透明可改默认，不是所有书只能1章或12章。formation提交直接用saved.target。作者本地草稿key含project+book；恢复上次提交保留本次body/幂等键，不认定为旧小说默认注入。作者已确定方向designFields虽然以“核心冲突与代价”标签引导且包含持续叙事空间，但目前未确认这些UI标签本身成为额外模型指令；底层硬成本见P01/P02。editorial-learning最大12是讨论取舍数量，不是章节数；正文知识须按批准的本书scope选择。未运行浏览器或读取用户实际localStorage，不宣称UI交互已验证。

## 本次扩展：P08与跨层修正范围

P08定位与完整分析见 [全工程方案第10节](ENGINEERING_OPTIMAL_CHANGE_PLAN.md#10-p08narrative-realization-不能成为隐蔽的每章戏剧模板)。新ChapterGroup校验正式调用NarrativeRealizationEvent：每章需要事件覆盖，每事件irreversible_change非空、state_deltas/disclosures/obligation_actions/arc_contributions非空。planning rich Schema与host合同一致。这是新的A+B机制证据，不是fixture故事内容进入生产的证明。

严重性高；机制置信度高；来源未确认。7个追加SYNTHETIC检查复现空不可逆字段/披露/状态变化被拒、整组章覆盖及rich Schema非空要求。没有运行任何真实资格/接纳/Provider，不证明文学效果。推荐修改Chapter执行覆盖、事件适用副作用、proof、frozen slice和Book消费的整个合同链，而不是仅更改一个字段。

P02范围补正：validate_narrative_qualification只有require_pass=True才对非PASS抛失败；评估输出保存可用require_pass=False。strict独立资格仍需适用标准满足；AUTHOR_ADVISORY配合原生作者监督可有证据处置分歧，不授独立资格。固定标准的适用性问题仍在，但不能说所有模式每项模型FAIL都必然阻断。

P06补充：_report对有分数证据固定threshold=70.0，需与实际policy、测量、verdict和required_actions一起修复；不推断所有已校准分数在当前部署都使用了错误阈值。

新增代码证据完整复制到evidence/source，全文汇编E层登记；原静态Prompt原文、原24份模型装配及原41检查未改。追加检查见 evidence/checks/engineering-chain-results.json。整个方案未实施；全适用矩阵和文学验证仍NOT_RUN。

## 追加分析结束时main变化

remote main已更新为 `68c1c6c3b611810310fd61dbca79f3626f93fdfe`。所有原文、追加合同证据与全工程建议仍绑定 `b1d42e6107d871442baa71823f7c21bfeec841b1`；没有混入新版本内容，也未核验新SHA是否已修复。第一阶段结束时main未变的记录仍保留；追加阶段核验见baseline-followup-end.json。用户分支和HEAD未变。
