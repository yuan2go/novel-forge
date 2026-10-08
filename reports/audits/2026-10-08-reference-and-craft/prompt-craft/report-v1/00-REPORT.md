# WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01

**从可核实的产出与改稿机制看，当前更接近“先为规则与验收生成材料，再期待它成为好故事”。** 这不是说系统不能讲故事：现行方法已经支持人物欲望、可选技法、声音、幽默和留白，短候选也有真正的利益冲突。但当前能看到的完整章把大量叙述用于证明做法和记录正确；新main最完整的真实请求证据仍停在策划，没有本轮传统修仙目标的完整正文与作者修订闭环。讲故事的方法存在，持续讲好这个目标读者要看的故事尚未被作品证据证明。

置信度：上述“可见产出重心”中高；当前main会否继续产生同类问题中低；持续长篇质量不足以判定。历史同章样本不能证明所有新书风格，也不能把工程PASS升级为文学达标。

## 基线、运行与审查边界

|层|开工确认身份/状态|
|---|---|
|远端main/审查源码|`7540c51fe587266b8083ef4168271aa5a4ff9f3e`；开工UTC `2026-10-08T09:20:54.169447+00:00`；git ls-remote与origin/main相符；仓库外git archive快照|
|本地工作分支|`codex/wp02-author-approved-run` / `ceb69fa2ff1c56f07005154bb5797616e933e8c2`；未切分支、未覆盖工作区|
|未提交差异|已有AGENTS.md、ai-instruction-manifest、reality-evidence、docs/development等tracked修改与大量untracked Skill/审批输入；见status/diff，不能当main或已运行版本|
|实际安装|本地.venv distribution novel-forge 6.0.0；未加PYTHONPATH时模块不可解析。包版本不能绑定当前源码SHA|
|实际运行|未发现带novel_forge模块的可见进程；Docker daemon不可用；PostgreSQL只读连接失败。当前服务release、安装Pack及Book cursor未核实，不据此宣称全部停机|
|实际策划请求|历史执行源码939c12ad47db37e3b27fc35897decb525a95cae0；42真实gpt-6.1-sol调用，41成功/1UNKNOWN；42请求/receipt hash一致；人物Skill冻结v2，非当前v3；正文0|
|实际正文|sol40本地同开篇章5份输出（2 Draft/3 Revision）；历史简报轻喜剧/5000–6000汉字/40章与gpt-6-sol medium，仅本次样本背景，非本轮要求；接纳状态/父子版本缺证|
|未批准修仙候选|方向-04《再试一回》是原生生成的短候选/声音测试，不是已选方案或正式章|

本轮仅在独立审查目录导出证据与建议；未改生产代码/Prompt/Skill/配置/数据库/冻结资产，未调用新Provider、部署、合并或恢复队列。完整后端矩阵NOT_RUN；这是一份审查完成报告，不是运行资格报告。

主要导航已按docs/README allowlist读current-system、runtime-operations、development，以及reality-evidence、production/worker/migration manifest。它们用于定位，最终判断回到实现、Schema和具体请求。相关历史10/3、10/4、10/5、10/7与10/8报告均按冻结时点使用。

## 最优先的四项

### P1 — 把本轮阅读目标落实为本书行动与承诺，先取得可读正文

影响高，证据是交付缺口；不是已确认代码丢字段。

来源：[skills/topic-development/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/topic-development/SKILL.md:16)、[src/novel_forge/modules/story_planning_runtime/foundation_generation.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/story_planning_runtime/foundation_generation.py:267)、[src/novel_forge/modules/hierarchical_planning/chapter_contracts.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/hierarchical_planning/chapter_contracts.py:42)。当前任务要求已选修仙成长/连载时落实期待和实际进展；公共层不统一强制升级/奖励/钩子是正确通用性。Chapter Mission对APPLICABLE本书serialization requirement要求具体实现，null不可豁免。Formation有多候选/作者精确选择以及历史兼容策略，不能把模型排名当作者批准。

实际证据：42个测试请求的作品目标是各自生活喜剧、食堂经营与档案悬疑；没有本轮完整作者目标→已选修仙Book→完整章记录。方向-04只有未批准声音测试。主角当前争取什么、阻力是谁的利益、阶段回报怎样继续改变选择，应由Reader Promise/Book/Arc/Chapter owner确定，不能交给Draft凭空补事件。

反证：代码已有上述owner和字段，不能据无当前样本判“没人负责”；离线确认无普遍chapter_hook要求。修改方向：先用现有作者简报/选择/规划链做本书具体落实；不新增公共修仙公式。见[reader.promise.generate.task.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/reader.promise.generate.task.json)及需求表。

### P1 — 历史章的解释与校核过程占据叙事重心，须分清规划问题和文笔问题

影响高；样本现象高置信，当前Prompt因果待验证。

原文：“它没有说这碗适合别的来客，也没有替将来的每一顿作保证”；“拿笔核算的这会儿仍是收工的一部分…给记录本身留了一行。”详见[文本证据](05-TEXT-EVIDENCE-AND-HYPOTHESES.md)。多份输出把到货、同意、温度、当次反馈、工时都再次论证。叙事像人物在完成核验，读者较少面对独立欲望的对撞、未解关系或令人期待的下一行动。

可能入口：既有Plan/Scene及知识边界、历史Draft/repair合同；**这些正文的完整最终请求和Review未取得，不能把该现象直接归因v12、某Skill或高分选稿**。当前3.10.0使用continuous-scene，一Scene一连续单元；旧5类槽拆分不可冒充现行规则。当前[src/novel_forge/modules/chapter_authority/realization_composition.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/realization_composition.py:226)明确dialogue/action/interiority是叙述选择并保留silence；方法允许作者判断。

保留：具体碗、手势、米、火候、身体余力及生活幽默；必要规则和来源边界。修改方向：若Plan本身只有核验流程，回上游改行动与关系；若事件已有戏，只在同Plan内减少动作后的同义解释。不得把“少解释”变成删除必要因果或一刀切禁词。

### P2 — 调度把情绪与实现模式逐字锁定；当前Planning system又未按阶段裁剪

影响中高；指令/接线确定，文学危害尚未证明。

[config/capability_packs/artifacts/story_planning_system_instruction_v11.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/config/capability_packs/artifacts/story_planning_system_instruction_v11.md:101)：“Also copy its reader_experience.target_emotion and reader_experience.reward_mode exactly”; Chapter Plan对primary/secondary、state delta、promise/reward/ending hook/density逐字复制。必要因果与知识链可保留；目标情绪和具体回报模式是否必须在更早层硬锁，是UNRESOLVED_DESIGN_CONSTRAINT，不能从代码存在推导质量益处。

[src/novel_forge/modules/chapter_authority/execution_gateway.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/execution_gateway.py:4536)只对system v8调用stage projection；当前v11不裁剪。42份真实Foundation/Planning请求确实包含Foundation/Book/Arc/Chapter/World/Actor等全部system段。它们多有“For stage”作用域限定，不是所有规则都要求同一输出；存在无关阶段指令同请求并存、可能形成竞争。character-design-qualification-v3也不满足general v2 projection判断，但目前全文只有Shared/Character方法，没有发现额外跨阶段污染，优先级低。

修改方向：先标清必要调度结果与可选呈现；若验证显示情绪过程被过锁，再在所属上游合同最小版本化调整。对system v11支持声明的阶段投影是单独可审阅的小修正，保留Shared与该阶段需要的serialization/selector等新段，不能直接复用v8投影漏掉新增规则。只提出，不实施。

### P2 — 普通审美建议不能直接进入自动改稿；作者选择后的文学改稿要有可用路径

影响中高；普通入口限制确定，系统完全不能改稿的假设不成立。

[src/novel_forge/modules/review/diagnostics.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/review/diagnostics.py:75)只将特定语义/合同/连续性问题视为可执行repair；AESTHETIC限定minor。[config/capability_packs/artifacts/chapter_generation_template_v12.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/config/capability_packs/artifacts/chapter_generation_template_v12.md:10)明确无可执行诊断时edits=[]。[src/novel_forge/modules/revision/domain.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/revision/domain.py:60)在宿主再校验，不能靠改Prompt绕过。较低分或更好听的建议本身不授权改稿，这是合理边界。

反证：[skills/quality-review/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/quality-review/SKILL.md:12)已审声音/潜台词/张力；[src/novel_forge/modules/chapter_quality_authority/creative_validation.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_quality_authority/creative_validation.py:117)有独立Quality LOCAL_REPAIR/EVIDENCE_REASSESSMENT；[src/novel_forge/modules/chapter_authority/author_editor.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/author_editor.py:148)及API支持作者提交精确文本、保存/接受/拒绝，结构改变转Plan Change。[src/novel_forge/modules/chapter_authority/candidate_selection.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/candidate_selection.py:68)有基线、阻断、解决与保留检查，新稿分高不必被采用。

缺口：作者采纳“无聊/解释过多/人物平”等文学反馈之后，如何将其送入**模型**改稿并比较而非手动提交文本，本轮未取得可核实执行链。修改方向：先用现有作者编辑/获授权改稿实现一个实际案例；只在入口确缺时补一条既有owner内的最小授权任务，不把所有审美建议升级为自动硬错误。

## 保留项及不能成立的旧诊断

当前main不普遍要求每章升级、反转、不可逆成本、和解或钩子；Foundation当前工作任务已替换旧“所有主题必须付代价”的提示。策划可设计心理与未来条件，limited POV不是禁止设计。风格已能保留到work view；旧15槽文本不能证明当前continuous-scene仍机械拆分。新稿有preservation和同baseline检查，不能笼统说“分更高就采用”。这些规则宜保留，不能为减少Prompt而删除。

MKAOS已有具体的受控留白/动作因果/潜台词/节奏等抽象方法及副作用检查，值得复用；其原创方法库与参考Source拆解不是同一证据。editorial_learning非DEFER编译REQUIRED的范围/条件需核查，暂列次级对照项，未证实会强迫全书展示。无需新训练、新Agent或新资格体系。

## 文档冲突与后续清理建议（本轮不修改）

|材料|冲突/过期边界|后续处理|
|---|---|---|
|10/3–10/4 Prompt审查|冻结b1d42/f34eee及旧Pack；部分问题在当前main已修复；旧P01–P05不能直接称现行缺陷|保留历史证据并显式链接新基线复核，不改旧原始报告|
|sol40 strict-real-start proposals/reports|旧启动/缺预算/未实现等生命周期与后续真实输出分离；旧40章/篇幅/model不是当前作者要求|注明时点与successor，保留UNKNOWN/失败历史；正文由native ID导航|
|yu-xian-zhi-wai/current/execution-status.json|文件名current，但baseline5cce48；指向../../../config/production/author-guided-twelve，当前输入已在novels/.../inputs/author-guided-twelve|重新投影路径与时点，不能将旧零Card/零Book计数当现在数据库事实|
|参考source-manifest 与CODEX-CONTINUE|初始扫描NOT_RUN和后续授权研究任务属于不同时点；标题扫描不是阅读；任务指令不是运行结果|分开原件/扫描/读取/分析/方法Card/本书应用；不拿计划补分析证据|
|original-100ch候选/反馈|已明确未批准，但旧目录名可能暗示固定100章；助手编辑假设不是作者定论|保留状态与实际输入角色，避免被当前brief选择；不将声音测试当正文|
|canonical docs|现行文档按docs/README导航；其故事质量描述仍须以实际请求和作品校验|没有发现允许拿工程PASS替代文学达标的现行规则；持续保持证据上限|

## 交付导航

1. [需求追踪表](01-REQUIREMENTS-TRACE.md)
2. [有效指令链、189份去重全文及42请求索引](02-INSTRUCTION-CHAIN-INDEX.md)
3. [建议Prompt/Skill片段：公共、本书、章节分层](03-PROPOSED-PROMPTS.md)
4. [最小充分验证与下一实施工作包](04-VALIDATION-AND-NEXT-WP.md)
5. [逐稿文本证据、反证、七项假设](05-TEXT-EVIDENCE-AND-HYPOTHESES.md)

本报告没有给出“改Prompt即可保证精品”的结论。直接下一步是用既有owner把本轮作品目标变成可读、可比较的正文，再由文本决定需要哪项改动。


审查收尾：远端main与开工SHA相同；本地HEAD、git status和tracked diff均与开工记录一致，见[final-boundaries.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/final-boundaries.json)。宿主PATH的`codex --version`失败（全局npm包对应原生binary缺失），因此此入口实际CLI版本未核实；这不证明应用冻结路线使用的其他binary不可用，也不改变历史42份真实回执。
