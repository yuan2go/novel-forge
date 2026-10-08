from pathlib import Path
import json, shutil, hashlib, re

A=Path(__file__).parent
R=A/'main'
E=A/'evidence'
V=A/'report-v1'
V.mkdir(exist_ok=True)
for p in A.glob('0*.md'):
    if not (V/p.name).exists(): shutil.copy2(p,V/p.name)
if (A/'MANIFEST.json').exists() and not (V/'MANIFEST.json').exists():
    shutil.copy2(A/'MANIFEST.json',V/'MANIFEST.json')

def link(path,line=1):
    return f'[{path}]({R/path}:{line})'
def write(name,text):
    (A/name).write_text(text.strip()+'\n')
def append(name,text):
    p=A/name
    if text.strip() not in p.read_text():p.write_text(p.read_text().rstrip()+'\n\n'+text.strip()+'\n')

write('06-MULTIGENRE-ADAPTATION-AUDIT.md',f'''
# 多题材与叙事适配专项补充（覆盖旧题材化表述）

审查目标是多题材小说创作能力。传统修仙仅为首轮完整正文验证作品；此前报告中“本轮作品”的具体修仙要求仅属于该Book。不得推广为公共方法，亦不得将旧报告中的人物、情绪收束、批评或举例变成新模板。源码基线仍为 `7540c51fe587266b8083ef4168271aa5a4ff9f3e`。

**结论：公共阶段接线已具备题材中立与本书要求分离的基础，尚未证明多题材完整正文的质量。最具体的新问题是MKAOS通用方法卡的统一题材/视角亲和标签会影响选择排序。** 没有发现必须先配备题材专用Skill才能创作的默认门槛；不能把这点升级为所有生产路径已验证可回退。首轮正文可通过现有通用能力交付，无需先建完整题材库。

本补充没有改变主报告对可见历史正文的判断：样本较偏规则和验收表达；当前主链的文学效果仍须看完整作品。42份真实策划请求涵盖三个作品方向，正文为零；五份历史正文仍是同一轻喜剧开篇章，不能支持多题材或长篇结论。

## 五层职责与实际接线

|层|职责归属及输入输出|接线事实与生效范围|本轮证据上限/缺口|
|---|---|---|---|
|公共阶段Prompt|Foundation生成候选；Story Design决定语义；Planning/Plan Change维护计划；Draft实现；Review/Quality/Revision/selection判断和改稿|Pack按能力/I/O绑定阶段Skill；{link('src/novel_forge/modules/capability_pack_authority/application.py',395)} 的 `_select_capability_skill` 不接收genre。当前v11 system包含多个阶段段落，投影缺口详见主报告；不能因Skill阶段正确就称最终指令均已裁剪|WIRED；42历史最终请求可核实，当前部署未核实。无需增加题材Pack选择器|
|通用写作Skill|组织人物欲望、对话潜台词、行动、情绪、节奏、留白、幽默、连续性等方法使用步骤；不承载本书设定|`prompt_methods.project_skill_method`选择Shared及当前Draft/Review/Revision段；离线验证Draft不含Screenplay/Full revision段。topic/world/character/outline等通用能力优先回退；Reader Promise当前校准绑定topic而非沿用商业拆解为统一目标|WIRED + 窄离线EXECUTABLE；不能称所有服务端隐含指令已知。Skills存在不等于都进请求|
|题材与叙事适配|本书作者输入/Style/承诺→阶段和场景Need→MKAOS选择→策略/任务参数→Draft；Review/选稿使用同一基线|{link('src/novel_forge/modules/story_planning_runtime/execution.py',541)} 的 `_planning_narrative_intelligence_need` 在689行传task、chapter function、scene goal、reader effect、conflict、POV、characters、emotion、information、genre、pacing、relationship、obligations、style；不只genre。725行过滤原始文本/声音样例/私有作者材料，并限制章节范围|WIRED。`genre_tags`为tuple，可表示复合标签，无固定单题材枚举；未证明复合题材正文自然融合或同题材不同写法均被正确选择|
|单书内容|作者选择后的世界/人物/剧情/规则/状态/承诺/风格属于该Book；候选不得直接写已接受事实|Creative input selection→Story Design→计划→Context/Chapter→Book acceptance/Canon/Narrative State的精确Book/版本绑定，详见指令索引的owner map|既有链保留；当前Book与接纳cursor仍缺DB读证据。不上升为共享世界线|
|公共资料|MKAOS维护抽象方法、适用条件、副作用、谱系、批准和选择；Skill描述使用流程|{link('src/novel_forge/modules/mkaos_authority/domain.py',424)} 的 `select_narrative_intelligence`先检查typed applicability，再评分、组合与依赖；原始参考文本不自动进Draft。`craft_catalog._mechanism`的知识元数据偏置见下|WIRED + 合成离线EXECUTABLE；源码目录43张Card不等于运行安装或本书选中43张，不等于质量证据。建议在现有MKAOS修正，不另建知识库|

## 新问题及反证

### P2：通用方法的统一亲和标签导致选择偏差

影响中，指令/排序事实高置信；正文质量影响待验证。{link('src/novel_forge/modules/mkaos_authority/craft_catalog.py',72)} `_mechanism`统一写入：`affinity.genre = ["wuxia", "xuanhuan", "chinese_serial"]`、`affinity.pov = ["limited", "first_person"]`。43张核心方法全部相同，其中40张不属WUXIA_XUANHUAN family；包含intentional-gap等通用方法。`provenance.confidence = HYPOTHESIS`，`effect_evidence = []`，不是已证明文学适用范围。

{link('src/novel_forge/modules/mkaos_authority/craft_selection.py',101)} `craft_candidate_assessment`将problem/effect/mechanism/applicability/affinity放入同一个searchable词集合，各context维度都对此匹配，任意匹配可得分。{link('src/novel_forge/modules/mkaos_authority/domain.py',492)} 调用该评分；无上下文匹配的可选Craft作为dependency-only，不能独立入选；{link('src/novel_forge/modules/mkaos_authority/craft_solver.py',8)}最终组合。**候选得分变化不等于某张卡必然入选，更不等于正文已受影响。**

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

{link('src/novel_forge/modules/story_design_authority/qualification.py',447)}原文：`A method that is absent, explicitly inapplicable or prohibited is not required`；并要求评价作者选择的替代方案、禁止凭修订发明未选方法。允许观察性主题、稳定人物和开放结局；不是统一成长/道德纠错/情绪收束。

{link('src/novel_forge/modules/chapter_authority/chapter_plan_views.py',385)} `_method_requirements`将当前合同中明确未选reward/hook等设NOT_APPLICABLE，未知不能冒充未选。{link('src/novel_forge/modules/chapter_quality_authority/work_semantics.py',20)} `finalize_work_dimension`将NA/PROHIBITED维度score/threshold置null、weight0、blockingfalse、revision_strategy=[]。本轮故意输入“reward FAILED并建议invent reward”，输出仍NA且不可阻断。当前work longitudinal reward rhythm是MEASURED/无阈值，不能套历史固定奖励间隔判失败。

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
''')

p=A/'00-REPORT.md';s=p.read_text()
s=s.replace('## 基线、运行与审查边界','**范围更新：审查多题材小说能力；传统修仙只用于首轮正文验证，不成为公共默认。** 新增取证确认MKAOS通用方法卡的统一题材/视角标签会影响排序，且其他题材在问题匹配时仍可使用。职责分层、通用回退和评价端边界详见[多题材专项补充](06-MULTIGENRE-ADAPTATION-AUDIT.md)。修仙样稿的效果不能推广为所有题材效果。\n\n## 基线、运行与审查边界',1)
s=s.replace('## 最优先的四项','## 最优先的问题')
s=s.replace('## 保留项及不能成立的旧诊断','## P2补充 — 通用方法卡的狭窄亲和标签影响多题材选择\n\n43张核心方法统一带武侠/玄幻和limited/first_person标签，其中40张不属武侠玄幻方法族。合成离线取证证明，通用留白方法仅凭题材或POV也可取得候选分数；同一问题换题材或叙事方式会改变排序。不是题材硬禁令，文学影响未证实。建议在现有MKAOS区分方法必要条件、验证范围和亲和评分，不新增题材整包或生产门槛。证据、反证和保留项见[06专项补充](06-MULTIGENRE-ADAPTATION-AUDIT.md)。\n\n## 保留项及不能成立的旧诊断',1)
s=s.replace('5. [逐稿文本证据、反证、七项假设](05-TEXT-EVIDENCE-AND-HYPOTHESES.md)','5. [逐稿文本证据、反证、七项假设](05-TEXT-EVIDENCE-AND-HYPOTHESES.md)\n6. [多题材适配职责、排序偏差、回退与评价边界](06-MULTIGENRE-ADAPTATION-AUDIT.md)')
write(p.name,s)

append('00-REPORT.md',"补充审查收尾见[多题材最终边界](evidence/multigenre-final-boundaries.json)。本地HEAD、同选项git status、tracked diff及远端main与开工记录一致；完整untracked逐文件清单另存。追加的11项窄检查不升级文学或生产证据。")

append('01-REQUIREMENTS-TRACE.md','''
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
''')

append('02-INSTRUCTION-CHAIN-INDEX.md','''
## 多题材适配补充索引

原189份去重全文与42冻结真实请求索引保留。新增的[MKAOS核心方法全文](evidence/multigenre-core-catalog.json)是当前代码生成的知识候选目录，不是已安装Pack或实际全部进入请求的证明。新增[多题材离线结果](evidence/multigenre-offline-checks.json)是合成输入/代码行为，不是章节输出。

公共阶段Skill由capability/I/O选择，不按genre整包加载；Need由阶段、问题、效果、POV、风格、场景和Book边界组装；选择后才进入该任务的知识投影。作者已选意图与合同优先，方法Card不能覆盖。Review/Revision/selection同样使用工作适用性和creative baseline；不可把未选方法改成修订目的。具体来源/范围/接线状态和缺口见[06五层表](06-MULTIGENRE-ADAPTATION-AUDIT.md)。未匹配可选Card的domain回退不代表每个完整生产路径均已验证；作者必选知识仍保留既有门槛。
''')

append('03-PROPOSED-PROMPTS.md','''
## 公共阶段职责与方法选择（补充建议）

> 按本书作者意图、叙事方式、读者承诺、文风和当前阶段任务工作。公共层规定职责与事实/版本边界，不默认任何题材结构。策划提出并区分候选设计与既有事实；规划落实本书已选目标；正文在批准因果和知识边界内选择表达；审稿与修订按同一作品要求判断。题材标签是适配信息，不能替作者选择人物结构、成长方向、情绪结论或每章公式。

> 使用写作方法前，指出当前具体问题、所需读者效果、适用边界及保留项；从现有MKAOS选择本阶段需要的抽象资料。只传当前任务所需的方法，不因题材相同加载整包。未匹配专门方法时，用现有通用Skill完成任务；不擅自发明知识，不豁免作者明确必选的资料和必要合同。不为展示技法额外增加剧情。

> 审稿、修订与候选选择继续绑定同一本书的意图和叙述方式。方法没被选择、明确不适用或禁止时，不因它缺席扣稿或要求补写；本书明确承诺仍须实现。引用正文说明阅读问题和修改目的，并检查新稿是否保留旧稿的声音、冲突、幽默与留白。叙事方式或事件改变转所属上游版本，不靠改稿偷换。

这些是职责/工作方法建议，不是新的公共必填Schema或题材资格。前文“简单传统修仙验证作品”段只可进入首轮Book作者简报；前文人物、章节示范不能固定所有书的情绪与过程。例子及知识留在现有MKAOS，Skill不复制题材知识库。
''')

p=A/'04-VALIDATION-AND-NEXT-WP.md';s=p.read_text()
start=s.index('## 对照1：');end=s.index('## 真实调用授权条件')
s=s[:start]+'''## 必要对照优先级：叙事方式与写作问题交叉

本轮追加8个同方法选择合成对照及11项窄检查，全部PASS；包括同题材换POV、同问题换题材、只有题材/POV时的选择、通用Skill回退、可选Card为空、作者required Card保持阻断和评价NA边界。详见[离线结果](evidence/multigenre-offline-checks.json)。不代表模型质量，也不表示现行偏差已经修复。

### 对照A：同题材不同叙事方式

先复用同一传统修仙Book的既有事实、人物利益和场景任务，用两份**实验用**叙事参数，例如近距离第三人称与第一人称；作者实际采用的写法仍由作者选择。每种写法分别冻结其POV知识边界，不通过实验越过已批准计划。若任务/合同已固定视角，需要另有实验计划投影；不能冒充只改Prompt的同Plan对照。

在每种写法内部A/B仅改变一项：通用方法选择是否以当前“说明重复/潜台词”等问题为依据，或只改变对应Draft表达指导。方法选择与文笔试验分开，不同时改规划。看方法是否由实际需求匹配、留白在该叙述距离是否合适，人物声音、必要说明和继续阅读的理由是否保留。不能预设两种写法应得到同一方法组合或同样的信息密度。

### 对照B：不同题材使用同一种写作方法

选择一个确有同类问题的其他Book场景，例如当代生活或作者已选其他题材的对话隐瞒/过度说明；与传统修仙场景都使用同一种通用方法（如intentional-gap或对话潜台词）。各Book保留自己的世界、人物、承诺、篇幅及任务；不得移植具体剧情/表达。对同一方法的适用性做跨题材检查，**阅读效果采用各Book内部A/B**，不以两个不同故事的总分互相排名。

最小探索网格可为三种场景条件：同一修仙场景的两种叙事方式＋另一题材同问题场景；每种条件两种指令×两次重复，共12个Draft候选。模型路线/篇幅目标/预算在每个比较内一致。少量结果只能发现适配风险，不能证明普遍提升；Review/Revision/压缩/重试等额外调用另计未来总额。若第二Book缺授权输入，跨题材文学对照保持NOT_RUN，**不阻断首轮完整正文交付**。此规模是必要验证设计，不是新调用授权。

### 规划问题与文笔问题分别处理

若已选Book没有清楚行动目标/阶段承诺，先在同Book、同阶段做原规划与“只补作者已选正向目标”的候选对读，不能将改变事件的收益说成文笔提高。若Plan已有戏，只改变表达指导，保留事实与结果。不得把修仙场景中的修炼、宗门、资源或升级写入公共条件。

### 审稿、修订与选稿须一同检查

盲读记录人物行动、必要说明、独立声音、潜台词、幽默、节奏和继续读的理由及反对意见。Review须按每份冻结Style/承诺判，不因选了某POV或没用某题材常见方法扣稿。作者选择一个具体文学目的和保留项后才进行改稿，旧稿可获选；事件/知识变化转Plan Change。检查新稿是否消冲突或磨平个性，不因模型分高采用。无正文证据时不能判质量，通过Schema/工程检查也不能代替阅读。

''' +s[end:]
s=s.replace('WP-TRADITIONAL-XIUXIAN-READER-PROMISE-TO-PROSE-01','WP-WORK-ADAPTATION-AND-READER-PROMISE-TO-PROSE-01')
s=s.replace('目标：用现有生产链取得本书可读的传统修仙正文与作者判断，先消除作品要求到正文的空档。','目标：复用通用生产链将本书作者目标落实为完整正文。首轮Book为传统修仙；工作包职责与方法保持多题材，不建立题材框架，不以完备题材库为交付前提。')
s=s.replace('5. 交付完整正文','5. 若方法选择确实受本补充确认的窄affinity排序影响，另授权既有MKAOS内的最小元数据/评分修正，保持typed适用边界、作者required资料、版本与依赖，不复制题材Skill。首批正文不必等此调整。\n6. 交付完整正文')
write(p.name,s)

append('05-TEXT-EVIDENCE-AND-HYPOTHESES.md','''
## 多题材结论边界

本节历史食堂正文现象只属于所读同章样本；不能证明所有题材或当前新Book都如此。修鞋声音测试仅作反证，不推广其题材、人设或文风。多题材方法选择的代码偏差由[06](06-MULTIGENRE-ADAPTATION-AUDIT.md)的合成离线证据支持，不能用这里的历史正文建立其质量因果。跨题材及同题材不同叙述方式的完整正文对照本轮NOT_RUN。
''')

write('REBUILD.md','''
# 审查报告复建说明

所有脚本只用于仓库外审查产物，不能生成生产权威或启动真实Provider。

原 `build_report.py` 保留首轮报告生成器；`report-v1/`保存用户多题材补充前的报告与哈希清单，属历史版本。重建时先运行原生成器，再运行 `supplement_multigenre.py` 应用覆盖；不要把原生成器单独输出当现行报告。`offline_multigenre.py`追加当前快照的窄合成检查及核心方法全文，禁止网络/子进程/DB连接和写源码快照。方法目录不证明当前运行装载。

源码main快照、冻结真实请求与历史正文证据保持分离，历史版本不改。最终 `MANIFEST.json` 为当前导出文件字节哈希；最终边界与链接检查另存evidence。脚本重建不得修复环境、换运行ID重发、变更Book或生产资产。
''')
print('Multi-genre report supplement applied in audit directory only')
