# 多题材与叙事适配专项补充（覆盖旧题材化表述）

审查目标是多题材小说创作能力。传统修仙仅为首轮完整正文验证作品；此前报告中“本轮作品”的具体修仙要求仅属于该Book。不得推广为公共方法，亦不得将旧报告中的人物、情绪收束、批评或举例变成新模板。源码基线仍为 `7540c51fe587266b8083ef4168271aa5a4ff9f3e`。

**结论：公共阶段接线已具备题材中立与本书要求分离的基础，尚未证明多题材完整正文的质量。最具体的新问题是MKAOS通用方法卡的统一题材/视角亲和标签会影响选择排序。** 没有发现必须先配备题材专用Skill才能创作的默认门槛；不能把这点升级为所有生产路径已验证可回退。首轮正文可通过现有通用能力交付，无需先建完整题材库。

本补充没有改变主报告对可见历史正文的判断：样本较偏规则和验收表达；当前主链的文学效果仍须看完整作品。42份真实策划请求涵盖三个作品方向，正文为零；五份历史正文仍是同一轻喜剧开篇章，不能支持多题材或长篇结论。

## 五层职责与实际接线

|层|职责归属及输入输出|接线事实与生效范围|本轮证据上限/缺口|
|---|---|---|---|
|公共阶段Prompt|Foundation生成候选；Story Design决定语义；Planning/Plan Change维护计划；Draft实现；Review/Quality/Revision/selection判断和改稿|Pack按能力/I/O绑定阶段Skill；[src/novel_forge/modules/capability_pack_authority/application.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/capability_pack_authority/application.py:395) 的 `_select_capability_skill` 不接收genre。当前v11 system包含多个阶段段落，投影缺口详见主报告；不能因Skill阶段正确就称最终指令均已裁剪|WIRED；42历史最终请求可核实，当前部署未核实。无需增加题材Pack选择器|
|通用写作Skill|组织人物欲望、对话潜台词、行动、情绪、节奏、留白、幽默、连续性等方法使用步骤；不承载本书设定|`prompt_methods.project_skill_method`选择Shared及当前Draft/Review/Revision段；离线验证Draft不含Screenplay/Full revision段。topic/world/character/outline等通用能力优先回退；Reader Promise当前校准绑定topic而非沿用商业拆解为统一目标|WIRED + 窄离线EXECUTABLE；不能称所有服务端隐含指令已知。Skills存在不等于都进请求|
|题材与叙事适配|本书作者输入/Style/承诺→阶段和场景Need→MKAOS选择→策略/任务参数→Draft；Review/选稿使用同一基线|[src/novel_forge/modules/story_planning_runtime/execution.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/story_planning_runtime/execution.py:541) 的 `_planning_narrative_intelligence_need` 在689行传task、chapter function、scene goal、reader effect、conflict、POV、characters、emotion、information、genre、pacing、relationship、obligations、style；不只genre。725行过滤原始文本/声音样例/私有作者材料，并限制章节范围|WIRED。`genre_tags`为tuple，可表示复合标签，无固定单题材枚举；未证明复合题材正文自然融合或同题材不同写法均被正确选择|
|单书内容|作者选择后的世界/人物/剧情/规则/状态/承诺/风格属于该Book；候选不得直接写已接受事实|Creative input selection→Story Design→计划→Context/Chapter→Book acceptance/Canon/Narrative State的精确Book/版本绑定，详见指令索引的owner map|既有链保留；当前Book与接纳cursor仍缺DB读证据。不上升为共享世界线|
|公共资料|MKAOS维护抽象方法、适用条件、副作用、谱系、批准和选择；Skill描述使用流程|[src/novel_forge/modules/mkaos_authority/domain.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/domain.py:424) 的 `select_narrative_intelligence`先检查typed applicability，再评分、组合与依赖；原始参考文本不自动进Draft。`craft_catalog._mechanism`的知识元数据偏置见下|WIRED + 合成离线EXECUTABLE；源码目录43张Card不等于运行安装或本书选中43张，不等于质量证据。建议在现有MKAOS修正，不另建知识库|

## 新问题及反证

### P2：通用方法的统一亲和标签导致选择偏差

影响中，指令/排序事实高置信；正文质量影响待验证。[src/novel_forge/modules/mkaos_authority/craft_catalog.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft_catalog.py:72) `_mechanism`统一写入：`affinity.genre = ["wuxia", "xuanhuan", "chinese_serial"]`、`affinity.pov = ["limited", "first_person"]`。43张核心方法全部相同，其中40张不属WUXIA_XUANHUAN family；包含intentional-gap等通用方法。`provenance.confidence = HYPOTHESIS`，`effect_evidence = []`，不是已证明文学适用范围。

[src/novel_forge/modules/mkaos_authority/craft_selection.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft_selection.py:101) `craft_candidate_assessment`将problem/effect/mechanism/applicability/affinity放入同一个searchable词集合，各context维度都对此匹配，任意匹配可得分。[src/novel_forge/modules/mkaos_authority/domain.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/domain.py:492) 调用该评分；无上下文匹配的可选Craft作为dependency-only，不能独立入选；[src/novel_forge/modules/mkaos_authority/craft_solver.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft_solver.py:8)最终组合。**候选得分变化不等于某张卡必然入选，更不等于正文已受影响。**

同一“省去说明/留白”方法的合成离线结果：

|只变一个条件|xuanhuan / first_person|romance / omniscient|含义|
|---|---|---|---|
|只有genre，未给写作问题|xuanhuan得2分，无NO_CONTEXT_MATCH|romance得0分，NO_CONTEXT_MATCH|题材标签可使通用方法进入可选候选|
|相同“省去说明”任务和limited POV，只变genre|5分|4分，仍可匹配|不禁止其他题材，但排序有标签差异|
|相同“省去说明”任务和xuanhuan，只变POV|first_person 5分|omniscient 4分|同题材写法的评分也不同|
|只有POV，无写作问题|first_person 2分|omniscient 0分，NO_CONTEXT_MATCH|视角亲和也可单独匹配|

原始结果及11项检查：[multigenre-offline-checks.json](evidence/multigenre-offline-checks.json)；全文方法：[multigenre-core-catalog.json](evidence/multigenre-core-catalog.json)。这是合成代码行为，不是本书实际选择或Provider样本。

反证/其他解释：真正的武侠力量规则方法可有题材条件；普通方法在romance且问题相同时仍可用。标签或体现最初资料来源/首批适配，不能据此推论全面歧视、禁止其他题材或模型必然武侠化。typed prerequisites/contraindications、作者必选Card、依赖与保留条件应保留。

修改方向（只建议）：逐Card区分真正方法必要条件与曾验证范围；通用方法不统一继承狭窄题材和POV元数据。选择时分别匹配写作问题/效果和场景限制，题材/POV亲和用于有依据的适用调整，不单独证明“这场需要此方法”。不把修仙验证成绩回填其他题材，不简单清空所有affinity，也不增加“先具备题材Card才准生成”的门槛。

### 保留：没有匹配专门方法时仍有通用能力

`_select_capability_skill`按exact I/O、唯一output、通用capability method和唯一required binding选Skill，不查genre专用Skill。合成未知I/O的creative.proposal仍选择topic-development。多义绑定失败是合同歧义保护，不是题材资格要求。MKAOS没有可选Card时domain返回selected=[]；作者明确required Card缺失仍报 `MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE`，这是既有作者承诺与资料边界。

因此不建议新增每题材Skill、整包题材复制或统一genre qualification。上述回退只证明这两处窄入口；没有跑当前完整Book生产接纳链，不称PRODUCTION_PROVEN。显式reselection策略、已选学习REQUIRED与其他必要合同仍可能要求补证，不能用“回退”绕过。

### 保留：评价端已有按本书所选目标判断的边界

[src/novel_forge/modules/story_design_authority/qualification.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/story_design_authority/qualification.py:447)原文：`A method that is absent, explicitly inapplicable or prohibited is not required`；并要求评价作者选择的替代方案、禁止凭修订发明未选方法。允许观察性主题、稳定人物和开放结局；不是统一成长/道德纠错/情绪收束。

[src/novel_forge/modules/chapter_authority/chapter_plan_views.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_authority/chapter_plan_views.py:385) `_method_requirements`将当前合同中明确未选reward/hook等设NOT_APPLICABLE，未知不能冒充未选。[src/novel_forge/modules/chapter_quality_authority/work_semantics.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/chapter_quality_authority/work_semantics.py:20) `finalize_work_dimension`将NA/PROHIBITED维度score/threshold置null、weight0、blockingfalse、revision_strategy=[]。本轮故意输入“reward FAILED并建议invent reward”，输出仍NA且不可阻断。当前work longitudinal reward rhythm是MEASURED/无阈值，不能套历史固定奖励间隔判失败。

候选选择须同creative baseline并检查阻断、修订目的和保留项。代码没有直接按genre评分的候选选稿参数，但模型文学判断仍可能偏好某一种情绪或文风。缺不同题材完整Draft→Review→Revision→selection样本，所以“评价端完全无偏”未证实；后续对照也须读Review及选稿理由，不能仅测生成端。

## 什么属于参数、知识或专门方法

|差异|应归属|是否新增Skill|
|---|---|---|
|修炼/职业/校园等设定，人物利益、事件、规则、主线；一本书的复合题材和篇幅|Book作者参数与已选世界/人物/规划|否；单书内容不能进公共Skill|
|有限/全知/第一人称选择，冷峻/温暖/诙谐声音，读者承诺与阶段场景重点|本书Style、叙事参数与章节开放指导|优先现有能力；不是每个组合复制流程|
|资源争取的约束、悬念信息差、对话遮掩、幽默节奏、留白适用/副作用|MKAOS抽象知识，按当前问题与边界选择|否；Skill负责使用步骤，不另建同名知识库|
|确有独立操作步骤，例如多视角信息分配或不可靠叙述的证据配置|先用已有Skill＋MKAOS＋任务参数；重复任务证明确需独立步骤时再提可组合方法|只能可选提案；本轮未证实需新增，也不以缺少它阻断首批正文|
|真实参考作品的商业结构拆解|现有hot-novel-business-deconstruction等参考分析流程|复用现有，不把拆解出的商业方法变成所有Book必选，也不复制题材知识库|

## 需求核对与有限结论

- 作者明确意图应优先：公共方法中立不豁免本书已选成长/悬念/幽默/关系等正向目标；目的属于Book，技法可按问题选。
- 复合题材和不同写法：字段可表达、多维选择已接线；共享窄标签和词项匹配会影响选择，需要实样验证语义适配。
- 阶段加载：Skill已有投影；v11 system跨阶段并存仍是现行缺口。不要为解决它创建题材框架。
- 评价/修订/选择：工作适用性保护已有；作者采纳文学改稿及跨写法选稿效果仍缺运行证据，继续主报告P2补证。
- 首批交付：先在传统修仙Book取得完整相连正文和实际作者反馈；它只能证明这个Book这一阶段。后续以相同问题跨题材、同题材不同写法验证迁移，不能承诺所有题材改善。

已做8个方法选择对照、11项窄检查，全部PASS仅表示预期代码行为可复现，**不是质量达标**。后续最小对照与中立实施工作包见[04](04-VALIDATION-AND-NEXT-WP.md)。生产与冻结资产修改0，新Provider调用0。
