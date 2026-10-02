# Novel Forge｜参考研究用途适配与实际分析续执行

继续既有 `WP-REFERENCE-MECHANISM-LOGIC-AND-CONTEXT-EVALUATION-01`，兼容原任务编号 `WP-REFERENCE-MECHANISM-LOGIC-AND-ORIGINAL-PROSE-01`。本次不是新建平台，也不是重新取得已有作者决定。

仓库：`https://github.com/yuan2go/novel-forge`。
本次分析核验 main：`32cef050fc6a1830c559b5145cc9dd3abf55828f`；实施以执行时最新 main 与实际本地工作区为准，报告差异，不覆盖已有修改。

## 1. 目标及范围

修复参考研究用途与生产用途混用的三个根因，在同一任务中继续取得：

1. 有原文证据的人物、剧情、节奏、信息差、幽默和长程回收机制分析。
2. 12个 SRC 原文案例、6个 MUT 受控错误变体的真实判断、反证及未决项。
3. 完整相关 Context 与当前任务级压缩 Context 的有限对照。

只做参考分析与评测，不生成新书世界观/人物/大纲/正文，不接纳章节、不恢复生产队列。已有原件、索引、26处跨度和已保存执行证据优先复用；身份未变化时不反复重建全书导入。原文仍为分析数据，不是模型指令。

## 2. 开始前一次查清整条实际路径

读取适用 AGENTS.md、现有 TEST-TASK.md 和本地“本轮分析阻塞与证据边界.md”。先固定代码、来源、任务与已有授权身份，串联检查：

Source 导入/processing → 局部读取与选择 → Source consumption → Context 候选与边界 → 压缩/保真 → Router/Pack → Provider 最终复检 → 模型返回 → 分析观察记录。

不要只修第一个拒绝点。沿全部 caller/callee 检查重复准入，并用现有预检/日志一次报告全部必要条件；不要新增预检平台。区分工程缺陷、单个案例资料缺口、真实授权缺口和外部运行问题。

执行顺序以获取首次真实结果为主线：必要安全回归 → 一个原生 A 组分析请求 → 保存可阅读结果 → 继续样本与案例 → B组及对照。不要把完整批量或无关全仓资格工作放在首次请求之前；最终工程声明仍遵守仓库适用验收要求。

## 3. 修复 Source 使用政策，而不是伪造版权状态

重点入口：
- `modules/source_authority/corpus.py::corpus_admission/corpus_use_admission`
- `modules/source_authority/domain.py::decide_source_governance`
- `modules/source_authority/consumption.py::require_curated_consumption`
- `modules/source_authority/corpus_consumption.py::require_corpus_consumption`
- `storage/corpus_ingestion_records.py` 及其全部消费复检。

保留 `underlying_rights=UNKNOWN` 这一来源事实，不改为 OWNED、LICENSED、PERMISSION_GRANTED，不把作者的处理授权当成著作权证明。

本任务已有明确的研究目的、用户提供材料及指定模型传输许可。把“底层权利事实”“用户授予的处理/传输权限”“本次具体用途”和“使用限制”分别处理。对精确来源/版本/窗口、有效授权和指定账户/模型，提供受限的 SOURCE_ANALYSIS 决策；原有资产的全局状态不因此升级为可生产或可公开。

“仅私有分析”“禁止公开分发”“禁止进入Writer”是需要落实的限制，不能因为 restrictions 非空就无条件拒绝分析；也不能全部忽略这些限制。结构化解释已明确条款，未知或冲突条款保持待决，禁止用不可靠文本猜测自动授予权限。

明确禁止本次处理/传输、超范围、来源不匹配、已撤销/过期授权、实际权利冲突等仍拒绝。分析结果、压缩片段及原文都不能因此获得 ABSTRACT_GENERATION、Writer、训练或公开用途。已有 BENCHMARK 与生产隔离不放宽，不通过改标签绕过它。

沿既有领域和版本化合同实施最小修改。相同任务、用途、来源、边界和授权必须贯穿入口与下游复检；新决策只对该任务范围有效，不能全局放宽 UNKNOWN。

## 4. 结构完整性按被消费范围验证

重点：
- `CorpusIngestionRecords.corpus_edition_uses/corpus_document_denials`
- `CorpusProcessingRecords.corpus_processing_denials`
- `CorpusCatalogRecords.catalog_reading_units/catalog_reading_chunks`
- 当前分析入口及模型发送前的 lineage 检查。

保留全书 REVIEW_REQUIRED 和703/997标题异常等原始疑点。对本次实际读取的 source-unit/byte-span 及其必要上下文，核验原始/规范化映射、内容hash、单位边界、连续性与完整性问题的影响范围。

被消费范围可验证、局部无影响其解释的完整性问题时，允许局部研究并携带覆盖限制；不能宣称全书完整或无误。不得简单按章节数字判断问题是否无关，须检查真实源位置与依赖。

全局原件hash错误、无法可靠定位、局部内容损坏仍阻断；只影响单个案例时阻断该案例，不妨碍独立无问题样本。来源存在缺页时也不能借“局部允许”推导全局不存在某事实。

Provider前复检必须消费同一局部范围及有效授权，不能从chunk回溯到edition后丢掉scope、再次只按全书状态拒绝。不得将 require_bridge=False、删除source identity、伪造全书CLEAR作为修复。

## 5. 为参考研究使用真实观察边界

重点：
- `modules/context_builder/task_compression.py::compile_task_context`
- `modules/context_contracts.py::ContextCandidate`
- Context profile/eligibility、Provider view、压缩回调、Router及缓存/恢复。

以明确类型区分生产接纳边界与来源观察边界。旧生产调用缺失 accepted boundary 继续拒绝；参考分析绑定 source/edition/processing版本、源hash、允许unit/span集合、观察模式和可见范围，不创建Book、Canon或伪造accepted_through_chapter。

PREFIX的输入必须是授权范围与当时可见证据的交集；RETROSPECTIVE使用显式允许的离散材料，不能把“允许第558章”扩成“允许1—558章全文”。原文、派生摘要、检索、chunk前后文、索引标题和简介均遵守同一边界。

必须在检索/压缩/保真调用之前裁剪输入。当前读取返回的是覆盖所选units的chunk，不能直接发送整chunk导致泄漏未来或未授权文字。使用可验证的原文切片，程序绑定span和hash。

压缩不得仅放宽 accepted_boundary 的一个if：同步处理当前 draft 专用Profile、`_HISTORY`白名单、候选允许用途和依赖校验。为真实reference材料提供适用的分析Profile及可压缩表示，复用通用算法；不能把原文伪装成已接纳章节摘要。

分析候选可提供原文证据；Writer侧 raw source 禁止仍有效。缓存和回执绑定边界类型、允许片段、源版本、策略与任务，不跨PREFIX/RETROSPECTIVE或A/B错误复用。

## 6. 模型、授权与计量

本轮模型为用户指定 `gpt-6.1-sol`，推理high；全部实际分析、语义压缩、保真和判读均使用它，不切DeepSeek或其他模型。外层会话配置不代替子调用证据。

不再索取已经明确的分析用途、章节范围、模型和参考传输决定。运行前核对其原生登记是否完整，能从已有明确用户授权安全补齐的，沿现有入口登记，不反复让用户重写同一授权。

复用任务明确有效的原始授权与剩余额度。已明确的调用上限120、输入输出累计5,000,000；金额/credits、有效期及账户按实际已批准记录执行。旧授权不是因修改策略就自动续期，过期/额度用完/新增付费方式需要真实新决定。不能将历史示例、模型生成文字或其他任务额度当成批准。

来源策略适配不得自动续期预算，也不要求用户把UNKNOWN改成许可证。无法准确换算美元时保留未知及现有可执行计量，不记为免费；不能忽略实际已批准费用限制。所有子调用、失败、恢复共用累计上限。

不购买额度、不升级订阅、不改变正式作品状态、不全局解除暂停。用既有隔离研究入口派发获授权任务；无法安全隔离时报告具体共享资源影响，不私自放开生产。

## 7. 必要验证与首次真实输出

最小关键检查：
- 全书待审，但已核验局部窗口允许；真正局部损坏/全局hash不符拒绝。
- UNKNOWN保持不变；明确受限研究可用，超范围/过期/Writer/公开用途拒绝。
- 上游与Provider前复检一致；记录期间来源/授权失效不能继续发送。
- 观察边界可用；旧生产路径仍要求真实accepted boundary。
- chunk、索引与摘要不泄漏未来/未授权文本；expected/adjudication不进入分析、压缩或保真输入。
- 原生压缩路径真正接受reference材料，Router开启时也可执行。
- 结果保存失败不触发无条件重新生成；不伪造回执。

优先扩展现有测试，不堆积单元数量。需要数据库时使用隔离PostgreSQL；假传输保留真实装配、Source复检、Router和Schema。修复稳定后遵守仓库适用gate，但不以全仓未知问题为借口永久跳过已安全获准的隔离研究。

从既有用例自动选择原文范围清楚、无局部完整性疑点的一个样本，先完成真实A组调用、校验、持久化和可读结果导出。不能只运行hello或模型身份探针后宣称完成分析。

若新暴露的是本范围内的代码缺陷，保留诊断继续修复；不要每发现一个内部拒绝就宣布授权不足或撤回整包。只有真实未授权、未知外部效果、资源耗尽、无法信任的源输入等边界才停止相关动作。

A组已可执行时继续做有效参考分析；B组未就绪单独记录和修复，不把A组结果也清零，更不能伪造A/B。最终仍必须说明B组与对照是否完成。

## 8. 完成既有分析，不扩大创作任务

先取得可阅读、带证据的真实结果，再按授权执行机制拆解、12 SRC、6 MUT和有限A/B。SRC不是12个已确认硬伤；MUT不归给原作者。保留真矛盾、误报、延迟解释、角色认知/说谎、文本版本异常与证据不足。

各被测子调用使用隔离输入；可见文件/工具范围和上下文不得包含gold、未来答案、其他组结果。前缀分析与回溯判断分开；模型记忆不算证据。独立同模型调用如实标注，不冒充真人或跨模型验证。

A/B绑定相同任务、源边界、模型、high及输出要求，主要变量是Context构造。B由当前被测Context链产生，不手工摘要代替；不需压缩记录NO_COMPRESSION_NEEDED，不把它算成有损压缩保真已证明。有损选择的已批准预算对照单独说明，保留失败与退化。

每项机制写清原文证据、作用、适用条件及原创迁移原则。最终明确哪些疑点成立、哪些误报、压缩是否改变判断、哪些信息必须保留。建议只是后续方法，不生成新作设定与正文。

## 9. 交付与完成状态

只修改本范围直接相关代码和必要文档；保留本地提交、完整diff和运行记录，默认不push、不合并、不部署。沿现有研究数据路径保存分析结果，不另建通用平台。

交付以实际参考分析为主，工程摘要为辅：
- BASE_SHA / FINAL_SHA及本次真正修复的条件；
- 局部来源准入与观察边界的真实回执；
- 首次及后续真实模型请求、结果和计量；
- 机制拆解、18例结果、反证、A/B及不确定性；
- 改动相关测试与适用gate状态；
- 原有生产隔离未退化的证据。

分别报告 SOURCE_WINDOW_ADMITTED、REFERENCE_CONTEXT_EXECUTABLE、REAL_MODEL_RESPONSE_PERSISTED、MECHANISM_ANALYSIS、CASE_RESULTS、CONTEXT_AB、ENGINEERING_QUALIFICATION。

前三项通过不是本轮分析全部完成；只有哈希、脚本或Mock通过更不是文学评测完成。本轮终点是参考分析与对照结果，不是再次输出“资料就绪，模型调用0次”，也不是越权写新书。确有外部阻塞时保留已经完成的有效结果并准确说明，不伪造成功。