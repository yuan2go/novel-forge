# 最小改写建议（PROPOSAL / NOT_RUNTIME_AUTHORITY）

基线：b1d42e6107d871442baa71823f7c21bfeec841b1。以下均是建议文件，未覆盖原始资产、源码或数据库。只使用已有 Brief constraints、author_design、批准Foundation、ChapterPlan/style_policy、QualityContext、profile版本机制。

## 1 · Foundation task 与 Schema 同步（P01）

改写前（完整相关 task 段）：

````text
Develop a distinctive, sustainable conflict from the brief. Explain reader value, choices and costs; create original operational style examples, never imitate reference prose.
Turn the approved premise into opposing thematic answers tested by costly character decisions; avoid a moral slogan.
Design an earned ending direction with irreversible costs, required closures and forbidden shortcuts; this is future intent, not a predetermined accepted event.
Specify what readers may expect, observable preparation, escalation and payoff; distinguish promise from fact and leave timing to Planning.
Compile only world depth needed by the approved conflict. Consider laws, geography/time, resources, power, history/culture, existence and information; explain deferred dimensions and extension triggers. Rules need costs, exceptions and story consequences.
Build a cast with distinct narrative functions, then deepen each through desire, fear, contradiction, beliefs and choices. Derive voice anchors from biography and motives. Ground relationships and capabilities in the approved world, never invent accepted history.
````

改写后（相同六类阶段，不是六段同时注入；每阶段仍只选择自己的task）：

````text
Develop a distinctive creative direction from the frozen author brief and approved design parents. Explain its intended reader experience and the choices, tensions or observations that sustain it. Derive conflict and narrative engine only where they serve this work. Create original operational style examples for this work; never imitate reference prose.
Turn the approved premise into a clear thematic question and relevant competing answers, uncertainties or tensions. Describe how this work tests them through character experience. Specify costs only where these choices incur them; do not add sacrifice, trauma or a resolved moral conclusion merely to fill the schema.
Design the intended ending or ending openness from the author's goals and approved parents. Explain what changes, remains unresolved, or deliberately stays the same, and what earlier preparation is needed. Include irreversible costs only when this work selects or entails them. Preserve explicit prohibitions and avoid unearned shortcuts. This is future intent, not a predetermined accepted event.
Specify the experience this work promises its intended readers and the observable preparation needed to earn it. Use progression, escalation and payoff where appropriate to this promise; a deliberately quiet, open or non-serial form is not a missing commercial reward. Distinguish promise from fact and leave authorized timing to Planning.
Compile only world depth needed by this work's approved direction. Consider relevant laws, geography/time, resources, power, history/culture, existence and information; explain deferred dimensions and extension triggers. State each applicable rule's limits, exceptions and consequences. Do not invent a price or power system for a rule that does not call for one.
Build the cast appropriate to the frozen scope and work's goals, with distinct relevant narrative functions. Explain behavior through motives, beliefs, relationships, resources and context. Include wounds, false beliefs and transformation only when appropriate to this character; a maintained conviction or unresolved contradiction is valid. Derive voice anchors from biography and motives. Ground relationships and capabilities in the approved world, never invent accepted history.
````

保留：当前输入优先、原创、读者价值、因果/世界限制、当前scope、未来/事实分离、schema-only和独立接纳。下沉：不可逆成本、创伤、反转、商业升级、闭合方式由本书目标确定。

必须同步代码：ending.protagonist_cost、theme.choice_tests.cost、world.rules.cost、character.wound/false_belief等不能仍要求每个非空文学要素；用最小兼容新版本的nullable/适用性表示，调整validator。明确不适用不同于缺证据。当前被明确授权的代价不得丢掉。作者方向界面的“核心冲突与代价”等标签应同步说明可按本书适用性填写，不能用界面措辞暗示所有书必须牺牲。cast有界预算保留，但不将单批max12解释成全书人数上限。

验证：两份合法Brief只改变不可逆/开放结局策略；task与schema都不产生相反硬要求。作者选择代价的对照仍要求合理准备和实现。先offline，无Provider。

## 2 · 资格与章节必填范围（P02/P03）

改写前（完整相关模型评估指令段）：

````text
Independently evaluate the immutable candidate against every frozen qualification profile and criterion. The frozen Provider Context is the complete evidence boundary. For EXACT_CANDIDATE_ONLY, use only the first selected input. For EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES, keep the first selected input as the sole candidate under evaluation and consume each remaining exact qualified dependency's semantic_payload as evidence for that candidate's cross-layer claims. A reference-only BookDesign field is not missing evidence when its exact referenced dependency supplies the semantics. Do not consume prior qualification verdicts, demand downstream plans that cannot legally exist at the candidate's stage, or infer anything outside the frozen candidate-and-dependency envelope. Copy layer, profile_id, profile_version, profile_hash, capability_id, skill_ref, criterion, and candidate evidence identities exactly. Return one verdict per criterion. A non-PASS verdict must include a concrete repair_directive; PASS must leave repair_directive empty. Do not activate, revise, or replace the candidate, and do not infer evidence outside the frozen candidate.
````

改写后（仅随代码/Schema支持后可采用）：

````text
Independently evaluate the immutable candidate against every frozen qualification profile and criterion within the supplied current-work goals and criterion applicability. The frozen Provider Context is the complete evidence boundary. For EXACT_CANDIDATE_ONLY, use only the first selected input. For EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES, keep the first selected input as the sole candidate under evaluation and consume each remaining exact qualified dependency's semantic_payload as evidence for that candidate's cross-layer claims. A reference-only BookDesign field is not missing evidence when its exact referenced dependency supplies the semantics. Do not consume prior qualification verdicts, demand downstream plans that cannot legally exist at this stage, or infer evidence outside this envelope. Copy every frozen profile, criterion and candidate identity exactly. Return one verdict per criterion under the declared output contract. Evaluate applicable criteria against this work's selected purpose, never a universal commercial form. Use NOT_APPLICABLE only when the supplied scope or goals justify it, and cite that basis; it cannot excuse a binding author constraint or due obligation. FAIL and INSUFFICIENT require concrete repair directives; PASS and justified NOT_APPLICABLE do not invent repairs. Do not activate, revise, replace or accept the candidate.
````

代码先决：当前verdict enum只有PASS/FAIL/INSUFFICIENT；不能直接只改提示词新增NOT_APPLICABLE。最小可选方案是在已有profile里按冻结当前目标选择适用criteria；如果保留逐项report则版本化新增正式NOT_APPLICABLE及host审核依据。两者择一个一致实施，不能让自由文本“无”冒充PASS。

Volume irreversible_change/midpoint/climax/next_volume_bridge，应改为可表达当前卷结构与终卷状态的合同；保持scope、parentrefs、planned future与有效因果。ChapterPlan interface保留title/objective/scene units/identity，hook/charm/antagonist/suspense等按当前章功能选用。第1章不能仅因序号覆盖作者明确的观察式开篇。当前到期披露/情节义务仍必须检查。

验证：quiet首章、无反派普通章、开放终章、非连载卷；各不适用技法不进入强制任务或repair。适用技法失败、缺真正证据与未授权变更仍阻断。不能只造qualifier PASS。

## 3 · 作者风格绑定（P04）

这里不需要把公共Prompt再写强一点。改写前完整相关投影段见PROMPTS_AND_SKILLS_FULL.md B层 build_draft_plan_view/build_draft_style_view；原始源码全文在evidence/source。

最小代码建议：已有Writer plan whitelist加入style_constraints，并保留point_of_view/target_word_count/prohibited_outcomes；production_preparation.service._context_candidate先将已验证style_policy.constraints投影到style facts或有源字段（它目前仅取safe_summary/structured_facts）；已有draft style policy投影消费这些有源constraints及确切identity/scope。只在确认这些字段已经投影到task后才从context去重。普通审读与修订使用同一有效约束基准，author_private仍隔离。

建议的完整相关公共冲突处理段（新增于既有Shared rules适用位置，不是另建模板）：

````text
Use the current work's approved style and the in-scope author constraints supplied with this task. Preserve their source identity and scope when interpreting them. A method suggestion does not override an explicit author requirement. If approved inputs conflict or a requested form cannot be represented by the declared contract, report the conflict through the task's supported diagnostic path; do not silently replace it with a default style or manufacture approval. Choose sentence rhythm, narrative distance and detail for this work and this scene while preserving accepted facts, actor knowledge, source boundaries and the declared output format.
````

目前某些生成阶段schema不支持diagnostic path，不能仅塞一句“report conflict”却迫模型返回未知字段；最小缺口是对应已存在validation/reviewIssue渠道的显式输入冲突处理，先让合法不矛盾输入完整传播。

验证：style只在plan、只在policy.constraints、只在safe_summary/facts、author_design scopedfragment四路分别验证；不是要求所有原Brief永久全文重复注入。

## 4 · 质量审读与回改基准（P05/P06）

改写前（Quality dimension方法完整段）：

````text
Evaluate only the requested dimension and its frozen criteria. Support each finding with this candidate's evidence; state insufficient evidence when needed. Distinguish a structural/schema failure, a source boundary failure and a literary judgment. Do not replace the requested dimension with a universal checklist or infer audience approval from a score.
````

改写后（完整相关方法段）：

````text
Judge only the requested dimensions using the exact candidate and the supplied current-work goals, approved style baseline and applicable quality/platform policy. For style drift, compare the candidate against that baseline and identify a supported deviation; if no baseline is supplied, report insufficient evidence. For anti_ai, identify a concrete defect in meaning, voice, coherence or reading experience under this work's goals. Long sentences, deliberate repetition, low-conflict pacing or open endings are not defects by themselves. Distinguish an evidenced failure, uncertainty and a discretionary taste suggestion. Cite literal candidate passages and the relevant goal or policy. Never replace the requested dimension with a universal checklist or infer audience approval from a score. Return only the declared judgment contract.
````

保留：exact candidate、请求维度、定位证据、原文隔离、policy支持、人类批准不伪造。代码先决：SourceOriginalityQualityContextView加入精简有源author/style基准；不加入外部参考作品表达。style_drift当前非阻断，不能报成已强制回改；anti_ai阻断判断要与当前目标相容。修订应消费同一基准和仅有证据任务。

Fallback先消费CompiledQualityPolicy而非硬70/270；句长36等公式的文学适用性另列产品策略，不自动判成所有体裁质量真理。已校准exactdimension evidence的优先顺序保留。测试不同阈值与合法风格会产生可解释变化，客观空正文/身份/源泄漏门不变。

## 5 · 专业方法中的商业绝对句（P07）

改写前（完整相关质量/禁止条目）：

````text
- 多学科知识只能增强可信度，不能替代爽点和冲突。
- 禁止让专业合理性破坏追读和情绪奖励。
````

改写后：

````text
- 多学科知识应服务本次作品或分析任务的明确目标。专业可信度、情绪体验、冲突、观察和解释深度按当前作品需要权衡；不默认要求爽点或商业追读。
- 当当前作品明确选择追读和情绪奖励时，判断资料细节是否妨碍这些目标并说明取舍。作品以严肃表达或专业可信度为核心时，不得以默认商业偏好降低其明确要求。
````

操作流程第8项建议完整替换为：

````text
8. 交给适用的 quality-review 方法，检查这些知识是否服务当前作者目标、可信度和阅读体验；只在本次明确选择商业追读时审查对相应奖励与节奏的影响。
````

保留：安全、版权、来源、事实转译、不把无关资料直接塞正文。此方法只在指定源分析任务生效，不给所有Writer加载一个新Skill。

## 6 · 仅设计后续文学效果验证

先修装配/Schema一致性，再在额外授权下固定输入、模型、采样、上下文、篇幅和版本，单次只改变一项，做少量重复配对。匿名评价以本书作者目标为rubric，同时看连贯、可信、原创与可读。分别报告装配符合性、模型遵循性、文学结果和成本；一次样本/测试PASS不等于通用小说工厂已验证。
