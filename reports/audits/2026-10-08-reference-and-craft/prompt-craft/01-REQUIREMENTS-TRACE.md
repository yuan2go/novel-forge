# 需求追踪：以本轮作者要求为准

本轮目标是同赛道、相近阶段的阅读质量。没有统一精品分数、商业成功、每场代价/成长/升级/反转/和解要求。真人作者感指叙述判断与人物独立性，不指AI检测。传统修仙是这一本验证作品的范围，未批准任何历史人物或固定40/100章方案。本轮不登记新作品、不运行生成。

|作者目标|负责阶段/owner|实际指令与证据|缺口/当前结论|
|---|---|---|---|
|清楚的修仙成长主线、阅读期待、阶段回报、续读理由|Creative Foundation→Reader Promise→Book/Arc/Group→Chapter Mission|[skills/topic-development/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/topic-development/SKILL.md:16)要求具体期待；[src/novel_forge/modules/hierarchical_planning/chapter_contracts.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/hierarchical_planning/chapter_contracts.py:42)对已选APPLICABLE连载要求不能用null豁免|通用方法可选是正确的；本轮完整作者简报→已选传统修仙Book→章节兑现未核实。不能拿旧轻喜剧目标替代|
|人物主动、有独立利益判断与声音|Character Design→Cast→Scene→Draft|[skills/character-design/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/character-design/SKILL.md:1)动机、声音、冲突；策划能设计心理，limited narrator仅限制表现。历史修鞋短样例有具体冲突与回避|现有42请求喜剧人物温和合作由测试输入明确指定；不能证明公共层强制。缺连续修仙人物独立行动的完整章节|
|变化自然、叙事有轻重|Outline→chapter plan→Memo/Draft|[skills/chapter-outline/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/chapter-outline/SKILL.md:1)目标、阻力、改变或未解张力；[skills/prose-generation/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/prose-generation/SKILL.md:1)节奏与细节由场景需要决定|历史食堂章流程逐项解释明显；当前continuous-scene能增加实现自由，但文学收益未验证|
|本书/人物辨识度，适量说明、潜台词、幽默、留白|本书Style→Draft/Review→文学修订|[src/novel_forge/modules/chapter_authority/chapter_plan_views.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/chapter_plan_views.py:253)传递style_constraints；[skills/prose-generation/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/prose-generation/SKILL.md:1)动作、声音、留白；原生Craft有具体方法与禁用条件|风格接线不等于读者认可。样例有生活幽默但叙述反复代读者解释判断|
|事实、规则与后果长期成立|Story Design/Hierarchical Planning→Book acceptance→Canon/Narrative State|[src/novel_forge/modules/book_authority/production.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/book_authority/production.py:1170)原子绑定ChapterOutcome+Canon+State；[skills/quality-review/SKILL.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/skills/quality-review/SKILL.md:24)只审实际窗口|保护是必要的；本轮没有足够连续正文，不评价长篇兑现或恢复后文学一致性|
|修订改善体验并保留优势|Review/Quality→Revision→ReReview→selection；作者编辑/Plan Change|[src/novel_forge/modules/review/diagnostics.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/review/diagnostics.py:75)过滤普通审美建议；[src/novel_forge/modules/chapter_authority/candidate_selection.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/candidate_selection.py:68)保留旧稿、同baseline、改进及preservation；[src/novel_forge/modules/chapter_authority/author_editor.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/author_editor.py:148)提供作者编辑|非“没有硬错误就完全不能改稿”；Quality有独立LOCAL_REPAIR，作者可提交新文本。缺审美建议经作者选择→模型改写→逐稿对读的运行证据|
|学习成熟起点作品，抽象并应用|Source reading/analysis→MKAOS→editorial_learning→本书选择→Draft|[src/novel_forge/modules/mkaos_authority/craft.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft.py:1)要求机制/适用/副作用/保留/谱系；[src/novel_forge/modules/creative/editorial_learning.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/creative/editorial_learning.py:1)KEEP/ADAPT/AVOID/DEFER精确绑定|有原件/索引/受控用例，不等于通读拆解；旧方向明确Observation未作为已批准Card。当前新书未取得已选方法→正文的完整证据|
|每本书独立，公共知识按现有MKAOS使用|输入绑定→所有owner|project/workspace/Book+exact version；[src/novel_forge/modules/creative/input_selection.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/creative/input_selection.py:16)历史样例不可充当当前作者意图|保留。无新共享世界线、Agent、模型训练或资格平台建议|

## 输入身份分层

|材料|正确用途|本轮处理|
|---|---|---|
|本轮用户需求|作者目标与审查范围|最高任务依据；不把它伪称已注册Book资产|
|stage-comedy/fantasy-cooking/archive-suspense的brief|输入隔离测试作品方案|可验证实际请求，不能继承题材、人物心理或章数|
|sol40作者轻喜剧简报及5000–6000汉字范围|历史单书真实验证|解释样本文本的其他原因，不能变成本轮篇幅要求|
|original-100ch-work候选与修鞋声音测试|未批准创意/短风格样例|可提供反证；不是正式第一章或已接受Canon|
|参考source.txt、拆解/Observation|私有研究证据|未重新传输/拆解；不能直接给Writer|
|MKAOS方法Card/Pack|批准的抽象知识，按阶段选用|代码机制存在；需实际选中与正文应用证据|
|Memo、训练题、受控错误变体、模板|阶段辅导、评测或复用方法|不能冒充完整正文、作者意图或事实|
|候选正文与Revision输出|模型候选|本地5份来自同一章；acceptance/选稿和明确修订祖先尚未核实|

## 约束分类

- CURRENT_PROVEN_INVARIANT：候选不等于接纳；历史事实不由计划/观察改写；业务owner/UoW绑定；同候选精确证据不能换身份。此处“proven”是已查实现合同，不是本轮部署资格声明。
- CURRENT_RUNTIME_FACT：42份历史冻结策划请求与stdin回执相符；5份历史正文输出存在。仅针对这些运行。
- CONFIGURABLE_POLICY：Craft数量/冷却/频率/排名权重、篇幅范围、模型路线、修改预算。不是文学定律。
- HISTORICAL_COMPATIBILITY：旧first-admitted、scene-core-slots、旧输出合同及40章/100章方案。
- UNRESOLVED_DESIGN_CONSTRAINT：调度目标情绪和回报模式逐字锁定能否提升质量；方法学习REQUIRED强度是否过重；模型评分能否代表实际阅读。须对照，不因常量存在而合理化。

## 多题材补充需求（优先于旧表的单书示例）

|用户目标|负责层|实际证据|缺口/建议|
|---|---|---|---|
|公共Prompt题材中立，单书正向目标明确|阶段Pack/I/O与Story Design→Planning|按capability/合同选Skill；已选工作承诺仍强制，未选方法不强制|保留；修仙是首轮Book参数，不替代总目标|
|通用Skill按实际写作问题组织|已有character/prose/quality等Skill＋MKAOS|阶段Skill投影；多维craft context；43核心Card统一窄affinity|知识元数据与评分最小修正建议，非复制题材Skill|
|复合题材、同题材不同叙事|作者Style/brief→Need→MKAOS→Draft|tuple genre_tags及POV/style/reader-effect等输入；合成评分差异可复现|字段与窄排序行为已知，实际文学适配未核实|
|未匹配专门方法仍可创作|Skill binding与MKAOS domain选择|通用topic回退，可选知识为空不在该domain报错|不新增题材门槛；保留作者required知识/合同，完整生产回退未证实|
|生成、审稿、修订、选稿遵循同一作品意图|同creative baseline＋work applicability＋preservation|未选reward/hook为NA；NA质量维度清空阻断/修订；当前纵向奖励仅测量|跨写法模型偏好和文学修订运行证据仍缺|
|公共资料归MKAOS，内容归Book|知识owner与Book/Canon/State owner|现有选择/谱系和Book精确版本隔离|无新知识库/共享世界线建议；差异归属表见06|

完整文件/函数、原文、置信度与反证见[06](06-MULTIGENRE-ADAPTATION-AUDIT.md)。旧表“清楚的修仙成长主线”仅是首轮单书目标，不能作为公共创作默认。
