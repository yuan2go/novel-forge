# 全链路指令与合同改写建议（PROPOSAL / NOT_RUNTIME_AUTHORITY）

基线：b1d42e6107d871442baa71823f7c21bfeec841b1。以下均是建议文件，未覆盖原始资产、源码或数据库。这是全工程方案的指令与合同配套文件，须与 [ENGINEERING_OPTIMAL_CHANGE_PLAN.md](ENGINEERING_OPTIMAL_CHANGE_PLAN.md) 的W1–W8一起实施。复用现有Brief、author_design、Foundation、ChapterPlan/style_policy、QualityContext和profile；必要适用性能力需扩展相应版本化合同，不能仅替换文字。

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

必须同步代码：ending.protagonist_cost、theme.choice_tests.cost、world.rules.cost、character.wound/false_belief等不能仍要求每个非空文学要素；采用明确的新版本适用性及nullable/合法空集合表示，联动validator、profile与下游消费者。明确不适用不同于缺证据。当前被明确授权的代价不得丢掉。作者方向界面的“核心冲突与代价”等标签应同步说明可按本书适用性填写，不能用界面措辞暗示所有书必须牺牲。cast有界预算保留，但不将单批max12解释成全书人数上限。

验证：两份合法Brief只改变不可逆/开放结局策略；task与schema都不产生相反硬要求。作者选择代价的对照仍要求合理准备和实现。先offline，无Provider。

## 2 · 资格与章节必填范围（P02/P03）

改写前（完整相关模型评估指令段）：

````text
Independently evaluate the immutable candidate against every frozen qualification profile and criterion. The frozen Provider Context is the complete evidence boundary. For EXACT_CANDIDATE_ONLY, use only the first selected input. For EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES, keep the first selected input as the sole candidate under evaluation and consume each remaining exact qualified dependency's semantic_payload as evidence for that candidate's cross-layer claims. A reference-only BookDesign field is not missing evidence when its exact referenced dependency supplies the semantics. Do not consume prior qualification verdicts, demand downstream plans that cannot legally exist at the candidate's stage, or infer anything outside the frozen candidate-and-dependency envelope. Copy layer, profile_id, profile_version, profile_hash, capability_id, skill_ref, criterion, and candidate evidence identities exactly. Return one verdict per criterion. A non-PASS verdict must include a concrete repair_directive; PASS must leave repair_directive empty. Do not activate, revise, or replace the candidate, and do not infer evidence outside the frozen candidate.
````

改写后（仅随代码/Schema支持后可采用）：

````text
Evaluate the immutable candidate against the exact applicable qualification profiles and criteria already selected and frozen by the owning Authority for this work and stage. The frozen Provider Context is the complete evidence boundary. Use the supplied current-work goals and the selected strategy basis when interpreting a creative criterion; do not substitute a universal commercial form. Do not add, omit or waive a frozen criterion yourself.
For EXACT_CANDIDATE_ONLY, use only the first selected input. For EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES, keep the first selected input as the sole candidate under evaluation and consume each remaining exact dependency's semantic_payload as evidence for cross-layer claims. A reference-only BookDesign field is not missing evidence when its exact referenced dependency supplies the semantics. Do not consume prior qualification verdicts, demand downstream plans that cannot legally exist at this stage, or infer evidence outside this envelope.
Copy every frozen profile, criterion and candidate identity exactly. Return one verdict per applicable criterion under the declared output contract. Missing evidence for an applicable requirement is INSUFFICIENT, never PASS. FAIL and INSUFFICIENT identify the supported problem and the evidence or bounded correction needed; do not invent a new literary requirement. PASS leaves repair_directive empty. Do not activate, revise, replace or accept the candidate. If this evaluation is AUTHOR_ADVISORY, preserve that purpose and the model findings; the author's evidenced disposition remains a separate Authority decision and does not confer independent qualification.
````

代码先决：推荐由宿主依据本书冻结决策选择精确适用criteria，再构造对应profile/hash/output Schema，模型不自行返回NOT_APPLICABLE来豁免。未适用标准在选择/manifest中留痕，不请求其模型verdict；适用但缺证据保留INSUFFICIENT。当前verdict enum与固定criteria仍需版本化调整构造逻辑，不能只改上段提示。strict与AUTHOR_ADVISORY分别保持资格与作者决定证据。

Volume irreversible_change/midpoint/climax/next_volume_bridge，应改为可表达当前卷结构与终卷状态的合同；保持scope、parentrefs、planned future与有效因果。ChapterPlan interface保留title/objective/scene units/identity，hook/charm/antagonist/suspense等按当前章功能选用。第1章不能仅因序号覆盖作者明确的观察式开篇。当前到期披露/情节义务仍必须检查。

验证：quiet首章、无反派普通章、开放终章、非连载卷；各不适用技法不进入强制任务或repair。适用技法失败、缺真正证据与未授权变更仍阻断。不能只造qualifier PASS。

## 3 · 作者风格绑定（P04）

这里不需要把公共Prompt再写强一点。改写前完整相关投影段见PROMPTS_AND_SKILLS_FULL.md B层 build_draft_plan_view/build_draft_style_view；原始源码全文在evidence/source。

完整投影修改建议：已有Writer plan whitelist加入style_constraints，并保留point_of_view/target_word_count/prohibited_outcomes；production_preparation.service._context_candidate先将已验证style_policy.constraints投影到style facts或有源字段（它目前仅取safe_summary/structured_facts）；已有draft style policy投影消费这些有源constraints及确切identity/scope。只在确认这些字段已经投影到task后才从context去重。普通审读与修订使用同一有效约束基准，author_private仍隔离。

建议的完整相关公共冲突处理段（新增于既有Shared rules适用位置，不是另建模板）：

````text
Use the current work's approved style and the in-scope author constraints supplied with this task. Preserve their source identity and scope when interpreting them. A method suggestion does not override an explicit author requirement. If approved inputs conflict or a requested form cannot be represented by the declared contract, report the conflict through the task's supported diagnostic path; do not silently replace it with a default style or manufacture approval. Choose sentence rhythm, narrative distance and detail for this work and this scene while preserving accepted facts, actor knowledge, source boundaries and the declared output format.
````

目前某些生成阶段schema不支持diagnostic path，不能仅塞一句“report conflict”却迫模型返回未知字段；必须补齐的是对应已存在validation/reviewIssue渠道的显式输入冲突处理，先让合法不矛盾输入完整传播。

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

Fallback、report实际threshold、blocking与required_actions共同消费同一CompiledQualityPolicy，而非硬70/270；句长36等公式的文学适用性另列产品策略，不自动判成所有体裁质量真理。已校准exactdimension evidence的优先顺序保留。测试不同阈值与合法风格会产生可解释变化，客观空正文/身份/源泄漏门不变。

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

## 6 · 改写的工程与文学验证

先修装配/Schema一致性，再在额外授权下固定输入、模型、采样、上下文、篇幅和版本，单次只改变一项，做少量重复配对。匿名评价以本书作者目标为rubric，同时看连贯、可信、原创与可读。分别报告装配符合性、模型遵循性、文学结果和成本；一次样本/测试PASS不等于通用小说工厂已验证。


## 7 · 公共职责、作品要求与冲突处理的统一指令段

本段是新增/整合建议；没有声称仓库原来存在下面的同名段落。现有system全文见全文汇编A层，固定原件不改。本段应纳入现有Shared规则及各阶段真正的task/Context；不能只放在一个Writer模板上却让上游不消费。

改写后的完整相关段：

```text
Complete only the declared stage for the current work and frozen scope. Treat the supplied source boundaries, permissions, accepted facts and output contract as binding. Current-work author requirements and explicitly approved planning decisions determine creative direction; reusable method suggestions do not select a genre, voice, audience, plot pattern or ending for the work.
Use the supplied effective work requirements within their exact scope and strength. Preserve the distinction between required, preferred, permitted and deliberately excluded choices. A scene-level requirement does not become a book-wide rule. A candidate proposal or inferred preference is not an accepted author decision.
When the author delegates planning, supply appropriate creative details that serve this work. Do not inherit an unselected example, prior book, development task or compatibility rule as its purpose. Use a specialized strategy only when its applicable choice is present in the frozen task. Absence of a choice is not permission to force all available techniques into the chapter.
Do not invent accepted history, external approval or gate evidence. Follow the declared structured output and produce only the current-stage candidate. Input conflicts or unsupported creative requirements must use the owning workflow's declared diagnostic route; never silently substitute a default genre or style.
```

工程前提：公开有效要求与适用性先装配；host在模型调用前处理无输出字段可承载的输入冲突。不能向JSON-only阶段凭空加diagnostics字段。公共权限、事实、版权和格式不因“作者输入优先”而取消。

## 8 · 层级规划与实现事件的相关指令

改写前的完整相关字段合同与Schema原文分别见全文汇编B/E层：planning_provider_output_schema、validate_planning_contract、NarrativeRealizationEvent、NarrativeRealizationContract与_realization_proof_decisions。原代码不能用一段文字替代，P08全文证据已导出。

建议加入现有规划/实现方法的完整段（同时版本化Schema与host）：

```text
Decompose this work's approved goals into the current planning scope while preserving exact parent, chapter, scene, event, fact and actor identities. Cover the work assigned to this scope; do not assume that every unit needs escalation, an antagonist, a reward, a revelation or irreversible change.
Represent each chapter's intended experience and executable scene coverage. Describe causal events and state changes when they are actually planned. An observation, transition, sustained condition or deliberate uncertainty may have no new state delta, disclosure or obligation action. Use the contract's explicit empty or inapplicable representation rather than manufacturing a change or writing a placeholder claim.
For every applicable planned action, identify its real motivations, prerequisites, relevant knowledge boundaries and consequences. Preserve selected cause/next-event relationships and the exact accepted boundary. An irreversible change is required only when selected or entailed by the approved event; it is not a universal chapter obligation.
Verify only the transitions, disclosures, obligations and Arc contributions actually assigned to this scope. Missing an assigned requirement is a failure; having no assigned requirement is not evidence of failure. Do not claim proof, accepted progress or authority activation from a planning proposal. Use the declared Schema and leave factual acceptance to the owning Authority.
```

需要一体修改：Volume字段、ChapterGroup事件覆盖、event side effects、proof标准、frozen realization slice、ChapterMission / SceneTask和接纳消费。执行覆盖不能取消；文学事件副作用可以按真实任务为空。不能用“所有字段optional”或事件`required=false`绕过不合理非空合同。

建议的相关Schema表示原则（不是可直接部署的完整Schema）：

| 字段 | 新合同推荐语义 | 宿主必须验证 |
|---|---|---|
| irreversible_change | 本次适用时非空，否则显式null/未适用记录 | 已批准策略或事件所选变化与来源 |
| state_deltas | 真实计划变化列表，可空 | 非空时精确实体、前后状态与既有边界；不能编造变化 |
| disclosures | 本次新披露列表，可空 | 每项许可与reader知识边界；已计划必披露未执行仍失败 |
| obligation_actions | 真实生命周期动作，可空 | 引用已存在/授权计划义务；到期项仍检查 |
| decision / resistance | 与任务适用的行动/决定/阻力，不适用可正式表示 | 不需要决策冲突的观察单元仍有执行目标 |
| chapter coverage | 当前scope所有章有明确任务/场景覆盖 | 不能以没有状态变更而跳过整个章任务 |
| next_volume / chapter bridge | 有后续计划且已选桥接目的时适用 | 终章/终卷合法为空；确有桥接任务仍要兑现 |

## 9 · Writer与场景实现的相关指令

当前prose v4原文已多数合理，应保留其阶段方法、事实/角色知识边界、slots合同与原创约束；不整体替换成一句“写高质量小说”。以下是与新增有效要求配套的相关段，不是整份Skill替代。

```text
Write the prose for the exact frozen chapter and scene tasks using this work's approved voice, narrative distance, point of view and in-scope author requirements. Choose sentence rhythm, description, dialogue, observation and action to serve the current scene's intended experience.
Realize the assigned scene work and selected craft obligations. Do not add a joke, reversal, battle, revelation, irreversible cost, reward or cliffhanger merely because it appears in a reusable method or unselected example. Quiet, reflective, open or non-linear execution is valid when consistent with the current plan and author goals.
Maintain accepted facts, actor knowledge, source isolation, planned identities and the declared output structure. A planned future is not accepted history. Use only approved original operational examples; do not copy reference expression. Produce prose and structured evidence only as the current output contract requests.
```

工程前提：修复plan.style_constraints、operator style_policy.constraints的首点与Writer view；Budget不能删除必要要求。当前Foundation compiled-style正常路径保留。同一场景的声音/POV/人物知识约束一致，不能靠更多风格文本覆盖未知事实。

## 10 · 审读、修订、rereview的相关指令

普通review/revision/rereview完整原文在全文汇编A/G；当前质量维度方法的改写前后见第4节。以下三段是全链路目标绑定配套，分别用于对应阶段，不同时混入同一次请求。

Reviewer：

```text
Review the exact frozen candidate against its current-work goals, approved style, applicable plan obligations and objective continuity/source constraints. For each finding, identify the relevant requirement or policy, its scope, the candidate evidence and whether the issue is a binding failure, insufficient evidence or optional improvement.
Do not treat an unselected commercial technique or your general literary preference as a requirement. A long sentence, deliberate repetition, quiet opening or open ending is not a defect by itself. If a needed baseline is absent, identify that evidence gap rather than inventing a default style. Produce only findings supported by the declared review contract; do not rewrite or accept the candidate.
```

Reviser：

```text
Apply only the authorized corrections supported by the selected issues and their exact current-work requirement or policy basis. Preserve approved voice, permitted deliberate techniques, accepted facts, actor knowledge and all material outside the permitted change scope.
Use the frozen candidate quotes and locations required by the targeted edit contract. Do not introduce a new global rule, change a chapter's purpose, or add an unselected reward, reversal or cost to improve a generic score. A missing baseline requires evidence, not speculative rewriting. Changes to active plans belong to the owning Plan Change workflow. Return only the declared bounded revision output.
```

Rereviewer：

```text
Evaluate the exact revised candidate using the same applicable requirements and evidence basis that authorized the correction. Verify the addressed issues, preservation of unaffected material and any newly introduced binding problem. Do not replace the frozen baseline with a new default rubric or equate a higher aesthetic score with proof of improvement. Record unresolved uncertainty and return only the declared rereview contract.
```

工程前提：QualityContext补基准，quality维度与blocking按适用性冻结；anti_ai宽泛审美不独立驱动强制改文。Issue、evidence、required_action、edit和rereview target有共同版本身份。适用真实问题仍按原门禁失败封闭。

## 11 · repair与resume：纠正输出，不扩展创作范围

改写前原段与装配源见 story_planning_runtime.execution._repair_context、_validate_frozen_context_retry及真实Materializer全文。当前有正确的frozen retry和scoped修复，应保留；此建议不把现有机制称为已证污染。

```text
Repair only the specific invalid result of this frozen task using the supplied validation evidence. Preserve the current work requirements, applicable strategy choices, source boundary, exact scene and candidate identities, and previously correct content. Do not turn this local repair into a rule for other chapters or works.
A technical retry or resume does not authorize a new creative direction, different examples, replacement Pack or changed quality baseline. Follow the host's frozen request identity and declared recovery contract. If a creative or contract change is required, report it through the owning workflow instead of silently replacing this request. Earlier results and evidence remain immutable.
```

工程前提：由host而非模型保证同Attempt/Effect冻结；新合同纠偏创建新版本与相应授权；UNKNOWN先调和，不复用身份偷换Prompt。

## 12 · 指令改写不能代替的工程工作

| 工作 | 仅改文案是否足够 | 完整配套 |
|---|---|---|
| 风格字段丢失 | 否 | 首点candidate、stage view、Context去重与最终发送 |
| 固定代价/开篇/事件副作用 | 否 | Schema、host validator、qualification、proof、下游消费 |
| 质量基准缺失/阈值不生效 | 否 | Context、policy算法/report、blocking、aggregate与修订 |
| 源方法商业绝对句 | 相关正文需要改 | 任务目标进入Source，知识适用与拒用结果正确传播 |
| 未选Skill/旧Pack残留 | 否 | 选择条件、版本/hash、真实release、兼容与恢复 |
| 专用技法被作者选中 | 不应删除 | 保留精确策略与任务范围，验证已选义务 |
| 文学效果 | 文案或工程PASS均不足 | 固定条件、随机性、匿名按本书目标比较与成本 |

以上全部建议尚未实施。完整原件在独立证据层，建议不冒充运行输入，也不覆盖历史身份。
