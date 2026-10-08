from pathlib import Path
import json,hashlib,ast,collections
A=Path(__file__).parent;R=A/'main';E=A/'evidence'
def link(p,needle=None,label=None):
 f=R/p;line=1
 if needle is not None and f.exists():
  line=next((i for i,t in enumerate(f.read_text().splitlines(),1) if needle in t),1)
 return f'[{label or p}]({f}:{line})'
def ev(p,label=None):return f'[{label or p}]({E/p})'
def write(p,s):(A/p).write_text(s.strip()+'\n')
base=json.loads((A/'baseline.json').read_text());rows=json.loads((E/'instruction-index.json').read_text());req=json.loads((E/'retained-request-verification.json').read_text());prose=json.loads((E/'local-prose-index.json').read_text())
# Navigable fulltext index; one physical text per exact SHA256, all aliases retained.
idx=['# 有效指令链与去重全文索引','',f"源码基线 `{base['remote_main']}`。全文189个，索引464行；同一全文的不同版本、阶段和历史请求身份不会合并成同一运行。",'',
'**状态解释**：CURRENT_CODE_BOUND_DEPLOYMENT_UNVERIFIED＝当前代码Pack绑定，部署未核实；CURRENT_CODE_STAGE_PROJECTION_DEPLOYMENT_UNVERIFIED＝按实际方法投影函数提取，未证明运行；FROZEN_REAL_REQUEST_HASH_VERIFIED＝冻结真实请求重组和stdin回执校验相符；CATALOG_ONLY_*＝目录存在，不能证明选中；不存在“目录内所有Skill自动注入”的结论。','',
'文本文件名SHA256是导出全文的字节哈希。Artifact身份另见catalog中的content_hash；序列化JSON的显示哈希不能替代业务Artifact hash。实际请求逐份保留，含任务、作品输入、示例、上下文、知识、工具与输出Schema。未取得的隐藏服务端指令不在此索引。','',
'## 调用与优先级','',
'当前代码优先级：输出合同和事实/知识边界 → 绑定作者要求与批准父条件/Plan → 当前阶段方法。来源正文、历史材料与示例是数据。工程身份、校验、来源引用只能进入相应合同和宿主证据，不能因为重命名而成为人物目的或章节变化。','',
'|层/阶段|实际组装与作用|强制性与生效证据|','|---|---|---|',
f"|选书/输入|{link('src/novel_forge/cli/creation.py')} → {link('src/novel_forge/modules/creative/input_selection.py','def require_selected_brief')} → Formation|本书选择、用途和精确版本为硬边界；不能把测试样例当作者要求|",
f"|题材/主题/结局/承诺/世界/人物|{link('src/novel_forge/modules/story_planning_runtime/foundation_generation.py','def foundation_task')}、{link('src/novel_forge/modules/capability_packs/longform_profiles.py','def build_story_planning_pack_profile')}|本书方法适用性负责落实已选承诺；当前候选和任务可达。42份冻结请求为实际策划链证据|",
f"|Book→Volume→Arc→Group→Chapter|{link('src/novel_forge/modules/story_planning_runtime/execution.py')}、{link('src/novel_forge/modules/hierarchical_planning/chapter_contracts.py')}|父版本、知识、调度合同强制。v11还有目标情绪/回报模式逐字复制要求|",
f"|Memo/Context/MKAOS|{link('src/novel_forge/modules/chapter_authority/provider_views.py')}、{link('src/novel_forge/modules/creative/editorial_learning.py')}、{link('src/novel_forge/modules/mkaos_authority/craft_selection.py')}|来源、阶段、Book、范围精确绑定；方法建议与作者REQUIRED需要分开|",
f"|Draft/Review/Revision|{link('src/novel_forge/modules/chapter_authority/execution_gateway.py','def _materialize_production_codex_prompt')}|system、一个selected Skill、knowledge、template(task/context)、tool_policy、semantic_contract、schema。XML命名不代表独立API system role|",
f"|CLI实际发送|{link('src/novel_forge/modules/production_execution/backends.py','def _resolved_real_payload')}、{link('src/novel_forge/modules/production_execution/codex_configuration.py','CODEX_INPUT_ONLY_OVERRIDES')}|受控stdin+Schema。ignore-user-config/rules、ephemeral、禁宿主Skill/memories/tools；42份stdin hash有回执。历史正文缺完整指令|",
f"|Retry/repair/resume|{link('src/novel_forge/modules/story_planning_runtime/execution.py','def _repair_context')}、{link('src/novel_forge/modules/book_authority/creation_runtime.py','def continue_creation')}|技术重试复用冻结意图；语义repair携带旧candidate、FAIL report、qualification directives；知识重选追加明确指令。42份真实请求未发现实际repair_context对象，模板提及不能算使用|",
f"|选稿/保存/续写|{link('src/novel_forge/modules/chapter_authority/candidate_selection.py','def compare_candidates')} → {link('src/novel_forge/modules/book_authority/production.py','def accept_chapter')}|版本/比较/保留检查，Book原子推进Canon+State；作者编辑有独立save/accept/reject路径；RuntimeJob不拥有小说事实|",'',
'## 当前代码绑定版本','',
'Chapter Pack 3.0.0；workflow 3.10.0；system v3；template/compiler v12；prose-generation-v4；quality-review-v3；chapter-plan-skill-v3。Planning Pack 2.13.0；system v11；template v1；long-outline-v3；character-design-qualification-v3；narrative-beat-design-qualification-v3。这些是源码构建版本，不是已安装或已运行Pack。', '',
'历史42份真实请求：执行源码939c12ad47db37e3b27fc35897decb525a95cae0；system v11 / template v1；人物Skill为character-design-qualification-v2，不能冒充当前v3。冻结Pack也标2.13.0，但动态pack_id/manifest_hash/binding_set与当前构造内容必须独立核对，同版本号不能等同同字节。使用冻结materialization中的全文重组，42/42哈希一致，42/42匹配process receipt stdin hash。没有任何正文调用。','',
'## 全文索引','',
'|阶段|状态|逻辑身份|来源/实例|全文SHA256|','|---|---|---|---|---|']
for x in rows:
 idx.append('|'+ '|'.join([x.get('stage') or 'catalog',x['status'],x['identity'],x['source'],f"[{x['sha256'][:16]}…](evidence/instruction-fulltext/{x['sha256']}.txt)"] )+'|')
idx+=['','## 实际请求逐份核对','',f"完整元数据：{ev('retained-request-verification.json')}；冻结Artifact全文：{ev('catalog.json')}。",'','|样本|阶段|Effect原状态|请求|重组/回执|','|---|---|---|---|---|']
for x in req:idx.append(f"|{x['case']}|{x['stage']}|{x['effect_status']}|{ev(x['request_file'])}|{x['exact_hash_match']} / {len(x['matching_stdin_receipts'])}|")
write('02-INSTRUCTION-CHAIN-INDEX.md','\n'.join(idx))
# Code symbol line map for reviewer navigation.
paths=['src/novel_forge/cli/creation.py','src/novel_forge/modules/book_design_authority/formation.py','src/novel_forge/modules/book_design_authority/formation_generation.py','src/novel_forge/modules/creative/input_selection.py','src/novel_forge/modules/creative/editorial_learning.py','src/novel_forge/modules/story_planning_runtime/foundation_generation.py','src/novel_forge/modules/story_planning_runtime/execution.py','src/novel_forge/modules/story_design_authority/qualification.py','src/novel_forge/modules/hierarchical_planning/chapter_contracts.py','src/novel_forge/modules/chapter_authority/provider_views.py','src/novel_forge/modules/chapter_authority/prompt_methods.py','src/novel_forge/modules/chapter_authority/handlers.py','src/novel_forge/modules/chapter_authority/execution_gateway.py','src/novel_forge/modules/chapter_authority/candidate_selection.py','src/novel_forge/modules/chapter_authority/author_editor.py','src/novel_forge/modules/book_authority/production.py','src/novel_forge/modules/book_authority/creation_runtime.py','src/novel_forge/modules/review/diagnostics.py','src/novel_forge/modules/chapter_quality_authority/creative_validation.py','src/novel_forge/modules/mkaos_authority/craft_selection.py','src/novel_forge/modules/production_execution/backends.py']
sm=[]
for p in paths:
 for n in ast.walk(ast.parse((R/p).read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):sm.append({'file':p,'symbol':n.name,'start':n.lineno,'end':n.end_lineno})
(E/'source-symbols.json').write_text(json.dumps(sm,ensure_ascii=False,indent=2))
write('01-REQUIREMENTS-TRACE.md',f'''
# 需求追踪：以本轮作者要求为准

本轮目标是同赛道、相近阶段的阅读质量。没有统一精品分数、商业成功、每场代价/成长/升级/反转/和解要求。真人作者感指叙述判断与人物独立性，不指AI检测。传统修仙是这一本验证作品的范围，未批准任何历史人物或固定40/100章方案。本轮不登记新作品、不运行生成。

|作者目标|负责阶段/owner|实际指令与证据|缺口/当前结论|
|---|---|---|---|
|清楚的修仙成长主线、阅读期待、阶段回报、续读理由|Creative Foundation→Reader Promise→Book/Arc/Group→Chapter Mission|{link('skills/topic-development/SKILL.md','## Reader promise')}要求具体期待；{link('src/novel_forge/modules/hierarchical_planning/chapter_contracts.py','serialization_function')}对已选APPLICABLE连载要求不能用null豁免|通用方法可选是正确的；本轮完整作者简报→已选传统修仙Book→章节兑现未核实。不能拿旧轻喜剧目标替代|
|人物主动、有独立利益判断与声音|Character Design→Cast→Scene→Draft|{link('skills/character-design/SKILL.md')}动机、声音、冲突；策划能设计心理，limited narrator仅限制表现。历史修鞋短样例有具体冲突与回避|现有42请求喜剧人物温和合作由测试输入明确指定；不能证明公共层强制。缺连续修仙人物独立行动的完整章节|
|变化自然、叙事有轻重|Outline→chapter plan→Memo/Draft|{link('skills/chapter-outline/SKILL.md')}目标、阻力、改变或未解张力；{link('skills/prose-generation/SKILL.md')}节奏与细节由场景需要决定|历史食堂章流程逐项解释明显；当前continuous-scene能增加实现自由，但文学收益未验证|
|本书/人物辨识度，适量说明、潜台词、幽默、留白|本书Style→Draft/Review→文学修订|{link('src/novel_forge/modules/chapter_authority/chapter_plan_views.py','def build_draft_plan_view')}传递style_constraints；{link('skills/prose-generation/SKILL.md')}动作、声音、留白；原生Craft有具体方法与禁用条件|风格接线不等于读者认可。样例有生活幽默但叙述反复代读者解释判断|
|事实、规则与后果长期成立|Story Design/Hierarchical Planning→Book acceptance→Canon/Narrative State|{link('src/novel_forge/modules/book_authority/production.py','def accept_chapter')}原子绑定ChapterOutcome+Canon+State；{link('skills/quality-review/SKILL.md','## Longform review')}只审实际窗口|保护是必要的；本轮没有足够连续正文，不评价长篇兑现或恢复后文学一致性|
|修订改善体验并保留优势|Review/Quality→Revision→ReReview→selection；作者编辑/Plan Change|{link('src/novel_forge/modules/review/diagnostics.py','def prose_repair_diagnoses')}过滤普通审美建议；{link('src/novel_forge/modules/chapter_authority/candidate_selection.py','def compare_candidates')}保留旧稿、同baseline、改进及preservation；{link('src/novel_forge/modules/chapter_authority/author_editor.py','class ChapterAuthorEditingApplication')}提供作者编辑|非“没有硬错误就完全不能改稿”；Quality有独立LOCAL_REPAIR，作者可提交新文本。缺审美建议经作者选择→模型改写→逐稿对读的运行证据|
|学习成熟起点作品，抽象并应用|Source reading/analysis→MKAOS→editorial_learning→本书选择→Draft|{link('src/novel_forge/modules/mkaos_authority/craft.py')}要求机制/适用/副作用/保留/谱系；{link('src/novel_forge/modules/creative/editorial_learning.py')}KEEP/ADAPT/AVOID/DEFER精确绑定|有原件/索引/受控用例，不等于通读拆解；旧方向明确Observation未作为已批准Card。当前新书未取得已选方法→正文的完整证据|
|每本书独立，公共知识按现有MKAOS使用|输入绑定→所有owner|project/workspace/Book+exact version；{link('src/novel_forge/modules/creative/input_selection.py','def validate_input_selection')}历史样例不可充当当前作者意图|保留。无新共享世界线、Agent、模型训练或资格平台建议|

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
''')
write('03-PROPOSED-PROMPTS.md',f'''
# 建议改写片段：PROPOSAL / NOT_RUNTIME_AUTHORITY

这些段落只存审查目录。不是生产Prompt/Skill修改，也不是本书已批准方案。并不建议把全文同时注入。优先使用既有作者要求/Style/章节指导与MKAOS路径；需要代码修改时另行授权。

## 公共方法：人物设计（建议用于Character cast方法）

> 为人物设计其当前想得到或守住的东西、对局势的判断和会主动采取的做法。配角的利益可以与主角部分重合，也可以长期不一致。用与经历、身份和关系相连的说话与行动区别人物。变化可以是进取、退让、误判后的再尝试、坚持或矛盾延续；根据本书方向选择。不要为了完成成长字段自动安排“听劝—反省—合作”。允许策划设计尚未发生的心理、事件和规则，标记为设计候选；人物和叙述者的知识范围只限制呈现，不能代替策划。

保留现有心理可设计规则；这段增加的是人物独立行动的正面工作方法，不是禁写温和成长。

## 公共方法：大纲/细纲与Draft分工

> 父计划固定必要的因果、已选承诺、必须发生或不得发生的结果、知识与版本边界。标清哪些具体对话、心理结论、节奏和细节确为作者指定，哪些只是实现建议。章节设计须说明人物为何采取本章行动、阻力如何改变行动、这一阶段给读者什么可感知的进展。尚不需确定的呈现过程留给Draft。若阅读问题由动机、冲突或事件结果造成，回到相应Plan Change；不要用润色补出另一个事件。

适用位置：{link('skills/long-outline/SKILL.md')}、{link('skills/chapter-outline/SKILL.md')}。v11的逐字调度合同不能靠新增软Prompt绕过；若确需改绑定类型，应另做最小版本化合同修改并验证必要调度仍完整。

## 公共方法：正文作者判断（Draft建议）

> 先确定此段的叙述注意力：人物此刻在争取、应付、回避或观察什么。选择能改变理解、制造趣味或影响下一步行动的具体细节。对话可以答非所问、试探或掩饰，含义由上下文承担。动作已说明的判断无需再次翻译成心理总结；必要说明仍可直接说清。规则是否得到遵守由人物行动及后果表现，来源和校验过程留给宿主证据，除非它本来就是剧情。保留本书声音与角色不同的表达。连续叙述由情境决定轻重，不按每场统一写代价、反省、升级或钩子。

适用位置：{link('skills/prose-generation/SKILL.md','## Draft')}。保留Schema、Scene顺序、人物知识、事实来源、未受影响的好句与幽默。不要新增禁词或句长配额。

## 公共方法：审稿与作者授权修订

> 先按本书阅读承诺读完整章，指出最影响阅读的少量问题。每项引用原句并说明读者在哪一处失去关注或人物感。分别说明：与绑定要求冲突；可选的文学改进；证据尚不足。给出最小修订目的，以及必须保留的冲突、声音、趣味和留白；不把分数当作者意见。审美建议本身不扣稿。作者选择采纳后，将其转为对精确旧稿、范围、目的和保留项的改写任务；未经选择不自动扩写。改变事件/人物知识/父计划的建议转上游。比较新旧稿是否实现所选目的，有无失去优势，允许保留旧稿。

此建议需要区分普通Review自动repair与作者明确选择。现有`author_editor`已支持作者提供文本；本轮没有证明现成“作者选择审美建议→Provider改写”入口可用，不应只改Prompt就宣称接通。

## 本书要求：简单传统修仙验证作品（供未来简报使用）

> 本书写简单传统修仙成长。主角主动争取修炼条件和具体机会，宗门生活、资源分配和历练让其选择有持续后果。读者应能跟清当前目标、主要阻力、修炼规则，以及阶段努力换来什么实际变化。重要配角各有与自己生活相连的利益和判断；即使帮助主角，也不只负责教主角做人。选择适合本书的节奏与叙述声音，规则直观，说明以当前行动所需为限。阶段回报可以来自本领、机会、关系、认知或兑现的事件，具体形式由本书方案决定。不是每章升级，也不固定每场代价/和解/反转。篇幅、主角、宗门、文风和全书长度由作者选定方案后填写。

此段区分“作品须做到”与“方法可选”。不批准《再试一回》或陆圆食堂，也不新增世界线。

## 章节指导：如何表达任务（结构示范，不是剧情模板）

> 本章人物的实际目标：[从已批准计划读取]。推动他行动的利益或紧迫条件：[读取]。对方的独立目标：[读取]。必须保留的因果/结果/知识边界：[精确引用]。本章或所处阶段要让读者感到的进展：[本书承诺的当地实现]。可由正文选择的对白、心理表达、幽默、镜头重心和段落节奏：[标明开放部分]。无需展示的宿主核验：[标记为证据而非叙事任务]。

若计划没有行动目标或实际阻力，返回上游补齐，不能让Draft擅自补事件。若只是过程解释过多，在不改事实/结果的范围内做文笔对照。示范字段不应全部变成公共Schema必填。
''')
write('04-VALIDATION-AND-NEXT-WP.md',f'''
# 最小充分验证与下一工作包

## 本轮已做与未做

- PASS：冻结main、导出对应源码；42份真实历史策划请求按冻结Artifact离线组装，42/42全文哈希相符，42/42有匹配stdin receipt。保留原SUCCEEDED/UNKNOWN，不重发。
- PASS（SYNTHETIC/OFFLINE）：6项窄验证：无公共不可逆代价必选；v4章合同不要求通用chapter_hook；本书style_constraints保留；普通Review审美建议不进入自动修订、语义冲突可进入；同一最小Scene的旧core slots为5、当前continuous为1。只证明指令/字段行为。
- BLOCKED：一次只读PostgreSQL连接未成功；Docker daemon不可用。没有查询成功的最新Pack、已接纳正文、Review或release身份。保持未核实，未反复尝试、未恢复服务。
- NOT_RUN：新真实Provider调用、完整P0/后端/迁移矩阵、模型评测、读者盲评、传统修仙正式章、跨章文学质量验证、生产接纳/恢复。此次不改变实现，因此没有工程完成或QUALIFIED声明。

执行保护：离线脚本禁socket connect、subprocess、psycopg connect；脚本写入限制为审查目录，禁止main快照。导出正文时只读本地保留的last-message与receipt。早期合成检查漏了两个required lineage字段导致KeyError，补齐**审查脚本的合成输入**后才得最终结果；不改生产源。Default constructor导出的Schema仅为work-mode构造视图；真实Schema由catalog和42份冻结请求记录，不混为部署Schema。

可复核脚本：`offline_audit.py`（不需要网络或数据库）；结果：{ev('offline-checks.json')}、{ev('retained-request-verification.json')}。不能为了复核文学观点启动全仓资格测试。

## 必要补证（不发模型请求）

在原数据库/服务恢复可读后，一次限定只读导出：当前Book作者简报、选题记录及hash；Foundation/Plan版本；当前安装Pack及release；同章Draft/Review/Revision/ReReview/selection；final Provider stdin与schema；ChapterOutcome与Book acceptance；Canon/State cursor。按native ID取，不换run，不将本地5份顺序推为父子。每条列出model/profile、prompt/Skill版本、调用成本/回执及接纳状态；未知成本保持UNKNOWN。

这能改变两个结论：样本解释密度是规划要求、Prompt表现还是修订引入；现成作者授权的文学改稿是否已经可执行。若数据库仍不可读，仅凭文件不得升级。

## 对照1：本书目标是否形成可写行动（改规划）

固定同一本传统修仙作者brief、选定人物与世界、同阶段/章节范围、相同模型路线和预算。A用原当前规划输入；B只把**已明确的本书**修仙成长/连载阅读期待绑定到既有Reader Promise和Chapter Mission，明确人物目标、对方利益、阶段进展；不添加每章升级、代价或固定结构。父事实/知识/版本保持一致，输出Plan候选。只在作者批准某个候选后才能用于正式Draft。

比较：编辑能否从Plan说明“人物下一步为什么行动、读者在等什么、进展如何带来后续问题”；是否仍只是在验证资格或解释规则；是否把配角独立目标压成纠错；是否固定了非必要对白心理结论。先只比较计划，**不把B正文的差异归因于文笔**。若A已充分落实作者目标，则停止这项修改。

## 对照2：说明密度与作者判断（只改文笔）

选两处已有明确行动目标、不同叙事负荷的Scene：资源/机会争取中的人物交锋，和修炼/宗门日常中的较轻段落。固定完整Plan/World/知识/结果、目标篇幅、上下文、模型路线、当前continuous-scene合同。A使用当前Draft方法；B只加入建议的“行动已能说明的判断不再同义翻译；核验留宿主证据，除非本为剧情”的指导。不能改变事件、删因果或另造冲突。

各条件在同一场景至少有重复样本，避免单次幸运。最小探索规模可为2场景×2条件×2输出＝8次Draft调用；**这是计划，不是授权**。Review/压缩/重试等额外真实调用须计入未来总上限与成本，不能隐藏在8次之外。

盲读时先不出总分，记录：能否自然跟住人物行动；哪些句子替读者解释了已有信息；哪些说明确有必要；人物说话是否可辨；细节是否改变理解；幽默/潜台词是否保住；哪一稿更愿继续读，以及相反理由。Schema、因果、知识和事实检查独立；有效说明不得因偏好留白被扣掉。若B只缩短而损失清晰度/声音，否决B。

## 条件性对照3：审美修订能否改善且不磨平

只有选定一个有具体文本证据、作者明确采纳的文学目的才做。冻结旧稿及精确范围，列保留项；A保留旧稿，B由既有可用改稿入口执行所选目的。只比较相同事实/规划下的阅读效果。人物行动或事件结果需要改变时另走Plan Change，不能伪称局部文笔编辑。对读“问题是否改善”和“优势是否丢失”；旧稿可获选，不因模型分数增加采用B。

## 真实调用授权条件

未来另一个执行任务须绑定：选定Book与完整作者输入/来源用途；确切模型路线/推理与相同上下文；包含生成、语义Review、压缩、失败和恢复的调用/token/金额上限；输出位置与native identities；明确仅候选/是否允许接纳；unknown对账与暂停条件。本轮无这些新调用授权，未发送。既有历史授权不自动续用到新Book或新实验。

## 下一项：WP-TRADITIONAL-XIUXIAN-READER-PROMISE-TO-PROSE-01（建议，未执行）

目标：用现有生产链取得本书可读的传统修仙正文与作者判断，先消除作品要求到正文的空档。

1. 将本轮完整阅读目标作为**本书要求**，经既有creative input selection / brief / author design登记；主题、具体人物、文风、篇幅及长度保留作者选择，不沿用历史测试数值。
2. 复用Foundation候选与作者选择，审清主角实际追求、配角独立利益、阶段承诺和易懂规则；选定方案后复用Book/Arc/Group/Chapter规划。已有原生版本与授权可用则复用，不建设新Agent或评分资格。
3. 在一个开始阶段取得少量相连完整章节，读者能跟住一次行动、实际阻力和阶段结果；不要先跑整本，也不宣称这些章足以证明长篇质量。先只运行当前主链，暴露的问题决定是否做上述对照。
4. 作者读完整章，选一个最影响阅读的文学问题和保留项，经现有作者改稿路径或最小必要补接实施；若须改上游，明确Plan Change。保存旧稿、改稿、选择及理由。
5. 交付完整正文、精确请求/版本/成本、阅读反馈、修订前后及选择证据。工程必要checks与文学判断分别报告。完成标准是具体阅读目标在这段文字得到作者确认或明确未达成；不是分数达标或精品承诺。

仅在上述链条确认缺实际入口时，另授权最小实现工作；不要顺便扩大平台或将本报告例子固化为公共模板。
''')
# Literary evidence with exact lines in exported body, without asserted ancestor edges.
body=lambda key:next(x for x in prose if key in x['execution_id'])['body_file']
def quote_ref(key,phrase):
 p=body(key);txt=(E/p).read_text();line=next((i for i,t in enumerate(txt.splitlines(),1) if phrase in t),1)
 return f'[{key}正文]({E/p}:{line})'
write('05-TEXT-EVIDENCE-AND-HYPOTHESES.md',f'''
# 文本证据、反证与七项假设

## 实际读到什么

42份请求是策划调用：stage-comedy 7、fantasy-cooking 7、archive-suspense 28；41成功/1UNKNOWN，draft operations=0。后一个用例做到Formation READY并不等于完整章；随后World前置Schema错误未发送。原运行证据来自{link('reports/audits/2026-10-08-creative-input-isolation/evidence/evidence.json')}，只有这些冻结运行可说EXECUTABLE。

本地sol40保留5份正文语义输出，2 Draft / 3 Revision，均是陆圆灵兽食堂同一开篇章，15个scene artifacts。JSON与process receipt原样保留，审查阅读txt只用空行连接，空行不是已核实正式排版。process成功/authority_bound不等于Book接纳；没有将109个执行目录当109章，也没有将5个输出当5章。

|输出|类型|Operation|输入SHA256|全文/回执|
|---|---|---|---|---|
'''+'\n'.join(f"|{x['execution_id']}|{x['kind']}|{x['operation_id']}|{x['input_sha256']}|{ev(x['body_file'])} / {ev(x['body_file'].replace('.txt','.json'))}|" for x in prose)+f'''

有些Revision共享Operation ID，可说明同Operation产生多份输出；仍缺source_draft_version_id、Review及selection表，因此不能把时序自动画成修订祖先链或称最后一份最佳/接纳稿。

## 可定位的现象与阅读判断

|现象|原文/位置|可能影响|反证及其他解释|置信度|
|---|---|---|---|---|
|动作之后再阐释原则|“浅口碗是他根据眼前桌面提出的做法，现做或延后须由团耳回应。”{quote_ref('44e0e5aa','浅口碗是他')}；“此刻能看见的，只是这一回的触碰；它究竟怎样吃，还要等碗交到它面前。”{quote_ref('44e0e5aa','此刻能看见')}|原本可从选择/吃饭理解的信息被重复解释，潜台词和读者推断空间减小|单独一句可能服务谨慎人物与医疗饮食设定；问题是这类解释覆盖多个环节，不是说明本身错误|样本现象高；读者影响为编辑判断，中；Prompt因果低|
|反复强调证据作用边界|“它没有说这碗适合别的来客，也没有替将来的每一顿作保证。”{quote_ref('1c2816b8','它没有说这碗')}；“这页只说明这一顿怎样完成。”同稿|讲述一顿饭的篇幅反复用于证明不外推，而非人物交锋、关系变化或新信息|现有规则确要求不凭物种猜食性，事实边界应保留；可以通过行为守住，无需每次讲授|现象高；因果未定|
|核算细节成为主要收束|“拿笔核算的这会儿仍是收工的一部分，他想了想，又给记录本身留了一行。”{quote_ref('1c2816b8','记录本身')}；到货→询问→选择→控火→温度→反馈→工时重新全程列账|读者重心落在流程完成；结束只回到明早核货，持续成长阅读期待在该样本中较弱|食堂经营可写记账；若账目引发错估、利益冲突或经营抉择，也能有戏。历史要求本就温暖经营轻喜剧，不能据此宣判修仙长篇|样本结构高；跨书/长篇推广不成立|
|Revision版本补入同一核算轴的更多说明|427d、1c在44e相同片段基础上增加瓜皮/淘米损耗、守锅与等温分开、纸格不令一天变长；{quote_ref('427d95ec','纸上的两行')}|新增篇幅未明显改变人物关系/行动局面；可能增加工整与重复解释|缺原Review和父候选，不能断言由评分、长度repair或何条Prompt造成。历史简报5000–6000汉字可能施压，但其也禁止灌水|文本差异高；修订因果低|
|存在生活幽默与真实动作|“凳面很小，占住的路倒像一张正经椅子。”{quote_ref('44e0e5aa','凳面很小')}；“团耳用爪背一拨，把勺柄挪到了另一侧。”{quote_ref('44e0e5aa','爪背一拨')}|道具/动作有趣，团耳不完全只是主角纠错工具|应保留。不要把客人选择写成新强制冲突，不需给安静结局强加反转|文本存在高；读者效果待人读|

该样本确有“停一下—收回手—做得更谨慎”动作，但不足以证明全系统普遍采用“想反驳—停住—理解—调整”。这里并无必须反省或听劝成长的当前公共指令证据。不能把一种人物节奏直接变为禁令。

## 反证：人物可以有欲望、回避与未解冲突

{link('novels/original-100ch-work/candidates/方向-04.md','“开胶了。”')}中鞋匠问哥哥是否知道，陈满答“开胶了”；手里九文对方要十二；哥哥给三文却要求未时去运货，报名也是未时。物件、钱与时间同时牵动人物利益，误导回答保留了潜台词，关系没有同场和解。状态明确“候选待作者选择”，只是一段原创声音测试，不是完整章或本轮方案。它反驳“模型/Skill只能温和工整”的绝对命题，也不能证明长篇已经达标。

42份请求中的stage-comedy brief则明确“我和妹妹带村民排露天小戏”、幽默温暖、具体失误与协作。其人物voice anchor：“顺序我想过了。你说得对，我还没问你愿不愿意。先问这一项。”具备听劝/调整倾向，却有输入指定与体裁解释。应将此作为该测试人物方案观察，而不是通用公共规则。

## 七项假设判定

|假设|当前证据判断|改变结论所需证据|
|---|---|---|
|1 目标是否落实|公共方法可选正确；已选Book连载承诺不能省。当前本轮传统修仙要求未证明已进入已选Book和真实正文；是任务交付空档，不是已确认全系统目标丢失|精确brief→selection→Book promise→Chapter Mission→完整正文|
|2 人物模板化|历史喜剧候选有温和协作节奏，食堂正文谨慎流程多；当前character Skill无统一听劝成长，新修鞋短样例有相反证据|同类型/同任务多份完整章与人物行动纵向证据|
|3 创作与事实混淆|“策划不能设计人物心理或新事件”在当前main不成立。Foundation将批准父输入视为初始设计条件，角色心理可创作；Actor仅受自己的已知信息约束。accepted source限制Draft借用当前事实，不是禁止上游设计新规则|若实际拒绝候选，需具体failure与最终prompt，不能由Canon字眼推断|
|4 上游锁死正文|确有目标情绪/reward_mode等逐字锁定、相邻entry/exit严格链；当前Draft保留未规定呈现自由，continuous-scene减轻旧槽拆分。是否过锁需要同条件规划对照|实际选中章计划、事件/对白心理固定范围与读者结果|
|5 正文作者判断|该食堂章有具体物件/温度/身体动作，但解释原则/核算重心压过持续人物冲突；旧模型/旧规划/体裁/篇幅均可能解释，不归因当前main|当前传统修仙完整章；同Plan文笔对照|
|6 审稿真正改好|当前Review不仅查事实，Skill明确声音/潜台词/张力。普通AESTHETIC不触发自动repair；Quality有LOCAL_REPAIR，author_editor可写新稿、结构变化转PlanChange。无“分更高必采用”现行证据。作者采纳审美→模型改稿的易用闭环未证实|实际审美反馈→作者选择→改稿→ReReview/selection→保留旧稿；同时保留优势|
|7 对标学习落地|有具体原生Craft机制库，不是仅通用口号；其原始origin为REPOSITORY_ORIGINAL/HYPOTHESIS，无源阅读或效果证据，不能宣称学自起点。参考原件/标题扫描/局部案例与真实语义观察分别存在不同证据。某候选明确Observation非已批准Card，未证明本书应用|阅读范围/Observation→抽象Card→author choice→stage selection→translation→正文span→读者判断完整链|

## MKAOS值得保留与需要核验

{link('src/novel_forge/modules/mkaos_authority/craft_catalog.py','intentional-gap')}的“受控留白”明确“保留行动与后果，省去读者已能推得的连接说明”，禁用条件包括省掉因果/空间/知识必要环节；“长短句节拍”明确不规定全章比例。这比“写得更像真人”具体，宜选用而不堆叠。

{link('src/novel_forge/modules/mkaos_authority/craft_selection.py','def craft_candidate_assessment')}按上下文词项匹配、频率、近章重复与副作用观察排序，值属CONFIGURABLE_POLICY；词项命中/冷却可避免堆叠，但不证明适用性或文学质量。其本身标出`creative_benefit=NOT_PROVEN`/`ACCEPTED_PROSE_OBSERVATION_NOT_READER_EFFECT`，应保留证据上限。

{link('src/novel_forge/modules/creative/editorial_learning.py','"strength": "REQUIRED"')}将所有非DEFER编辑决定编译为REQUIRED/SCENE_INTENT。原文同时带适用条件与副作用，符合作者主动取舍；风险是“有条件采用的方法”若被下游当必展示技巧，会磨平自然变化。当前没有相应真实正文因果证据；优先查既有projection是否保留条件，再考虑允许方法强度，不直接删除REQUIRED或把已有承诺降为可选。

热门榜单查询在可读运行材料中未取得可核验的结果→实际阅读链。参考source-manifest的full_source_semantic_review=NOT_RUN是2026-10-02时点；CODEX-CONTINUE已有后续研究任务，旧manifest不能证明后来从未读过。本轮不重读整本、不凭简介或模型记忆造拆解，不宣称知识卡数量带来质量提升。
''')
write('00-REPORT.md',f'''
# WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01

**从可核实的产出与改稿机制看，当前更接近“先为规则与验收生成材料，再期待它成为好故事”。** 这不是说系统不能讲故事：现行方法已经支持人物欲望、可选技法、声音、幽默和留白，短候选也有真正的利益冲突。但当前能看到的完整章把大量叙述用于证明做法和记录正确；新main最完整的真实请求证据仍停在策划，没有本轮传统修仙目标的完整正文与作者修订闭环。讲故事的方法存在，持续讲好这个目标读者要看的故事尚未被作品证据证明。

置信度：上述“可见产出重心”中高；当前main会否继续产生同类问题中低；持续长篇质量不足以判定。历史同章样本不能证明所有新书风格，也不能把工程PASS升级为文学达标。

## 基线、运行与审查边界

|层|开工确认身份/状态|
|---|---|
|远端main/审查源码|`{base['remote_main']}`；开工UTC `{base['captured_utc']}`；git ls-remote与origin/main相符；仓库外git archive快照|
|本地工作分支|`{base['branch']}` / `{base['local_head']}`；未切分支、未覆盖工作区|
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

来源：{link('skills/topic-development/SKILL.md','## Reader promise')}、{link('src/novel_forge/modules/story_planning_runtime/foundation_generation.py','def foundation_task')}、{link('src/novel_forge/modules/hierarchical_planning/chapter_contracts.py','serialization_function')}。当前任务要求已选修仙成长/连载时落实期待和实际进展；公共层不统一强制升级/奖励/钩子是正确通用性。Chapter Mission对APPLICABLE本书serialization requirement要求具体实现，null不可豁免。Formation有多候选/作者精确选择以及历史兼容策略，不能把模型排名当作者批准。

实际证据：42个测试请求的作品目标是各自生活喜剧、食堂经营与档案悬疑；没有本轮完整作者目标→已选修仙Book→完整章记录。方向-04只有未批准声音测试。主角当前争取什么、阻力是谁的利益、阶段回报怎样继续改变选择，应由Reader Promise/Book/Arc/Chapter owner确定，不能交给Draft凭空补事件。

反证：代码已有上述owner和字段，不能据无当前样本判“没人负责”；离线确认无普遍chapter_hook要求。修改方向：先用现有作者简报/选择/规划链做本书具体落实；不新增公共修仙公式。见{ev('reader.promise.generate.task.json')}及需求表。

### P1 — 历史章的解释与校核过程占据叙事重心，须分清规划问题和文笔问题

影响高；样本现象高置信，当前Prompt因果待验证。

原文：“它没有说这碗适合别的来客，也没有替将来的每一顿作保证”；“拿笔核算的这会儿仍是收工的一部分…给记录本身留了一行。”详见[文本证据](05-TEXT-EVIDENCE-AND-HYPOTHESES.md)。多份输出把到货、同意、温度、当次反馈、工时都再次论证。叙事像人物在完成核验，读者较少面对独立欲望的对撞、未解关系或令人期待的下一行动。

可能入口：既有Plan/Scene及知识边界、历史Draft/repair合同；**这些正文的完整最终请求和Review未取得，不能把该现象直接归因v12、某Skill或高分选稿**。当前3.10.0使用continuous-scene，一Scene一连续单元；旧5类槽拆分不可冒充现行规则。当前{link('src/novel_forge/modules/chapter_authority/realization_composition.py','Write continuous narrative')}明确dialogue/action/interiority是叙述选择并保留silence；方法允许作者判断。

保留：具体碗、手势、米、火候、身体余力及生活幽默；必要规则和来源边界。修改方向：若Plan本身只有核验流程，回上游改行动与关系；若事件已有戏，只在同Plan内减少动作后的同义解释。不得把“少解释”变成删除必要因果或一刀切禁词。

### P2 — 调度把情绪与实现模式逐字锁定；当前Planning system又未按阶段裁剪

影响中高；指令/接线确定，文学危害尚未证明。

{link('config/capability_packs/artifacts/story_planning_system_instruction_v11.md','reader_experience.target_emotion')}：“Also copy its reader_experience.target_emotion and reader_experience.reward_mode exactly”; Chapter Plan对primary/secondary、state delta、promise/reward/ending hook/density逐字复制。必要因果与知识链可保留；目标情绪和具体回报模式是否必须在更早层硬锁，是UNRESOLVED_DESIGN_CONSTRAINT，不能从代码存在推导质量益处。

{link('src/novel_forge/modules/chapter_authority/execution_gateway.py','system.get("version") == "v8"')}只对system v8调用stage projection；当前v11不裁剪。42份真实Foundation/Planning请求确实包含Foundation/Book/Arc/Chapter/World/Actor等全部system段。它们多有“For stage”作用域限定，不是所有规则都要求同一输出；仍形成无关指令竞争。character-design-qualification-v3也不满足general v2 projection判断，但目前全文只有Shared/Character方法，没有发现额外跨阶段污染，优先级低。

修改方向：先标清必要调度结果与可选呈现；若验证显示情绪过程被过锁，再在所属上游合同最小版本化调整。对system v11支持声明的阶段投影是单独可审阅的小修正，保留Shared与该阶段需要的serialization/selector等新段，不能直接复用v8投影漏掉新增规则。只提出，不实施。

### P2 — 普通审美建议不能直接进入自动改稿；作者选择后的文学改稿要有可用路径

影响中高；普通入口限制确定，系统完全不能改稿的假设不成立。

{link('src/novel_forge/modules/review/diagnostics.py','def prose_repair_diagnoses')}只将特定语义/合同/连续性问题视为可执行repair；AESTHETIC限定minor。{link('config/capability_packs/artifacts/chapter_generation_template_v12.md','For an ordinary targeted revision')}明确无可执行诊断时edits=[]。{link('src/novel_forge/modules/revision/domain.py','REVISION_UNAUTHORIZED_DIAGNOSIS')}在宿主再校验，不能靠改Prompt绕过。较低分或更好听的建议本身不授权改稿，这是合理边界。

反证：{link('skills/quality-review/SKILL.md','## Chapter review')}已审声音/潜台词/张力；{link('src/novel_forge/modules/chapter_quality_authority/creative_validation.py','def internal_required_actions')}有独立Quality LOCAL_REPAIR/EVIDENCE_REASSESSMENT；{link('src/novel_forge/modules/chapter_authority/author_editor.py','class ChapterAuthorEditingApplication')}及API支持作者提交精确文本、保存/接受/拒绝，结构改变转Plan Change。{link('src/novel_forge/modules/chapter_authority/candidate_selection.py','def compare_candidates')}有基线、阻断、解决与保留检查，新稿分高不必被采用。

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
''')
print(json.dumps({'reports':[x.name for x in A.glob('0*.md')],'main_sha':base['remote_main'],'instruction_index_rows':len(rows),'dedup_fulltexts':len({x['sha256'] for x in rows}),'new_provider_calls':0},ensure_ascii=False))
# Add the narrow owner, storage and recovery map without extending into a platform audit.
p=A/'02-INSTRUCTION-CHAIN-INDEX.md'
p.write_text(p.read_text()+f'''

## 本专项涉及的owner / UoW / Schema / gate / recovery

实际CLI入口为{link('src/novel_forge/cli/creation.py','def run_creation_command')}调用{link('src/novel_forge/modules/book_authority/creation_runtime.py','def execute_creation_command')}；组合根为{link('src/novel_forge/api/authority_dependencies.py','def build_book_production_composition')}与{link('src/novel_forge/api/authority_dependencies.py','def build_chapter_authority_application')}。这些是被真实42次旧运行使用的native authority-creation start/continue路径，当前源码重新检查了同链；没有调用本轮启动函数。

|内容|owning application / mutation boundary|repository与存储身份|gate / recovery|
|---|---|---|---|
|选题/Formation|StoryFormationApplication.author_decision/advance；生成只候选，Story Design选择激活|{link('src/novel_forge/storage/story_formation_repositories.py')}、{link('src/novel_forge/storage/authority_uow.py')}；migration0100 authority_story_formation_run、0133 evaluation recovery、0180 direction search|精确输入/选项hash、结构与独立语义qualification；resume与历史方向选择保留原身份|
|世界/人物/规划|StoryDesign Authority + Hierarchical Planning；generation/execution不直接改active plan|{link('src/novel_forge/storage/story_design_repositories.py')}、authority_asset_store；migration0038/0039，0041 Plan Change|输入用途、父版本、知识/realization refs，stage schema，independent qualification；repair附FAIL证据，新version不改旧记录|
|Memo/Context/Draft/Review/Revision|ChapterAuthorityApplication→orchestrator→handlers；Effect在业务事务外调用模型|{link('src/novel_forge/storage/chapter_authority_repositories.py')} AuthorityHandlerRepository、{link('src/novel_forge/storage/authority_uow.py')}、asset version；0007 Command Kernel、0017 Effect、0071 Pack|Pack validation/runtime admission、冻结materialization、Provider前视图/Schema/hash校验；UNKNOWN reconciliation，不能盲重发|
|知识学习/选择|Source analysis owner / MKAOS Authority，editorial作者意图仅投影|migration0050 KnowledgeCandidate/Card/Pack；Card不拥有Book Canon|用途/版权/来源和阶段准入；抽象→批准Card→selected Pack→translation，DEFER不应用|
|保存/接纳/续写|PostgresBookAuthority.accept_chapter；Canon/Narrative State与accepted cursor原子绑定|{link('src/novel_forge/storage/book_authority_repositories.py')}、AuthorityUnitOfWork；0034 Book、0035 acceptance、0036 checkpoint、0119 grounded acceptance|ChapterOutcome/Canon/State/质量证据；creation continue复用原run，RuntimeJob仅调度|
|作者文笔修改/旧章替换|ChapterAuthorEditingApplication save/accept/reject；Book author_revision后继，改变结构转PlanChange|author text为asset version；0141 replacement、0144 edition、0181 manuscript delivery|exact old text/hash/range/rationale，rights basis；保留原稿与选择，已接受历史不原地擦改|

以上migration身份均在冻结main及migration-manifest中查到；本轮没有连接成功数据库，**没有证明这些migration已经应用于当前运行集群**。它们用于解释本专项边界，不是新增治理工作建议。

未取得完整运行证据的范围：当前新Book Draft/Review/ReReview/Quality长窗，真实repair追加与知识重选，实际部署的SDK/HTTP路线以及CLI隐藏服务端指令。旧目录/旧模板/旧技能版本可达历史兼容入口；只有“不被当前所查Pack选中”，不能扩大成全系统永不可达。源文本分析Skill不直接选中当前Reader Promise生成，旧hot-novel-business-deconstruction仍是资格资料，不能凭同名目录推为正文方法。
''')
p=A/'00-REPORT.md';p.write_text(p.read_text()+f'''

审查收尾：远端main与开工SHA相同；本地HEAD、git status和tracked diff均与开工记录一致，见{ev('final-boundaries.json')}。宿主PATH的`codex --version`失败（全局npm包对应原生binary缺失），因此此入口实际CLI版本未核实；这不证明应用冻结路线使用的其他binary不可用，也不改变历史42份真实回执。
''')
p=A/'04-VALIDATION-AND-NEXT-WP.md';p.write_text(p.read_text()+f'''

补充环境取证：当前PATH的Codex CLI版本检查返回ENOENT；未修复、安装或重新绑定。实际运行版本应通过原生配置/运行回执核查，不能拿外层会话模型或全局npm包代替。末次仓库状态检查与开工相同。
''')
# Report integrity check: all clickable local files must exist.
import re
missing=[]
for f in A.glob('0*.md'):
 for target in re.findall(r'\]\(([^)]+)\)',f.read_text()):
  name=target.rsplit(':',1)[0] if re.search(r':\d+$',target) else target
  if not name.startswith(('http','mailto')) and not (Path(name) if Path(name).is_absolute() else f.parent/name).exists():missing.append({'file':f.name,'target':target})
(E/'report-link-check.json').write_text(json.dumps({'missing':missing,'pass':not missing},ensure_ascii=False,indent=2))
print(json.dumps({'local_link_check':not missing,'missing':missing,'reports_total_bytes':sum(p.stat().st_size for p in A.glob('0*.md'))},ensure_ascii=False))
p=A/'02-INSTRUCTION-CHAIN-INDEX.md';p.write_text(p.read_text()+f'''

## 关键指令逐项：来源、作用域、强度与实际生效边界

优先级P0是任务输出/事实权限合同；P1是作者绑定及父计划；P2是当前方法。此处是描述现有文本声明，不新增运行优先级。

|关键原文或字段|来源/版本|阶段/作用域|优先级/强制性|实际证据|
|---|---|---|---|---|
|declared output contract and frozen Authority/knowledge boundaries… then author's binding requirements… then stage's method|story planning system v11；chapter system v3|各选中阶段|P0→P1→P2，强制|v11确进42请求；v3为当前代码绑定，正文未取得|
|Elaborate unspecified creative detail；approved parents are initial design conditions, not accepted chapter events|system v11 Foundation|策划者可以设计，不能伪造accepted history|P0事实边界/P2创作许可|42真实策划请求全文；不是禁止新故事内容|
|Character psychology可设计；limited narrator仅约束表现|character-design-qualification-v3全文|Cast/planning|P2许可、声音依据；不是每人必须成长|3份真实character请求使用冻结v2，不含v3新增心理澄清；v3仅当前代码绑定，尚无真实正文验证|
|Require a cost, growth, reward, reversal or hook only when applicable author/obligation contract calls for it|quality-review-v3 Shared/Chapter；prose-generation-v4|本书适用Review/Draft|P1若绑定则必须，否则P2可选|当前源码投影；未证明新正文实际使用|
|APPLICABLE Book serialization requirement必须concrete realization；null仅NOT_APPLICABLE|chapter-mission-scene.v4/system v11|当前连载章节目标|P1强制，但仅所选Book要求|CODE_EXISTS/WIRED；42中没chapter_plan/Draft，不冒充验证|
|copy target_emotion/reward_mode exactly|system v11 Chapter plan|Group调度→Chapter Plan|P1父计划硬复制；是否应硬锁未解决|v11全文进42请求，但没有对应Chapter规划执行；当前路径源码可达|
|same-Scene reveal不能用作scene entry knowledge|system v11；state/knowledge schemas|人物可知与读者可知分离|P0强制|策划系统实际请求含此规则；当前Chapter执行未核实|
|one complete prose unit per Scene；voice/subtext/silence|realization_composition continuous-scene.v1；prose v4|Draft呈现|Scene集合/次序P0；具体对白/节奏P2自由|currentworkflow3.10.0接线+离线1 slot；历史5份正文用15 artifacts，版本不能混用|
|普通targeted无executable diagnosis则edits=[]|chapter template v12 + diagnostics/apply_revision_result|普通自动修订|P0宿主权限强制|离线审美/语义过滤验证；未证明作者文学改稿实际执行|
|preserve effective voice/images/subtext/tension|quality-review-v3；candidate_selection|Review/Revision/选稿|P1本书要求/P2文学判断；选稿有P0preservation检查|CODE_EXISTS/WIRED；无本轮实际新旧稿比较|
|每个active editorial决定strength=REQUIRED、visibility=SCENE_INTENT；DEFER跳过|editorial-learning.v1→author design|所选stage+chapter_range+本Book|P1作者选定取舍，不等于全书统一技法|代码确认；未取到该机制具体真实正文应用|
|methods应用不能recap校核过程，抽象不复制表达|editorial_learning生成文本；MKAOS abstract card|相关Stage/Scene|P0来源隔离；P2表现方法|代码确认；核心Card是REPOSITORY_ORIGINAL/HYPOTHESIS，不能冒充源作品阅读|
|--ignore-user-config --ignore-rules --ephemeral、project_doc_max_bytes=0、memories=false/skip_host_skill_discovery|backends.py/codex_configuration.py|受控CLI子进程|P0宿主执行约束|代码存在；42 stdin receipt相符，隐藏服务端指令和当前binary版本未取得；外层会话记忆不是子请求输入|
|repair_context保留immutable candidate，仅按failed criterion bounded change|system v11 + execution._repair_context|语义repair|P0旧身份不可改/P1失败修订范围|constructor取证；42请求没有非空repair_context对象，未标为实际repair|
|知识重选instruction：Create a new concrete translation… Preserve scene identities… Respect every scoped rejection|execution.py 5722一类动态追加|当前知识reselection repair|P0拒绝/身份/P1重新翻译|源码存在；无这项真实追加请求，待核实|
|技术retry复用冻结Effect，resume按原Formation/Book恢复，UNKNOWN对账|execution.py、creation_runtime、gateway|重试/续写/恢复|P0强制，不能以新的任务取代UNKNOWN|历史UNKNOWN保留；本轮未运行恢复|

工具说明全文在tool_policy索引；实际42请求明确禁止shell/file/MCP/web等工具。章节执行主路径使用单独受控Provider，不自动开启外层Agent会话工具。训练题/反例expected/adjudication未作为本轮创作输入；拆解报告不是直接Writer knowledge，只有经批准抽象和本书选择才能用。
''')
# Keep causal wording conditional where no model comparison exists.
p=A/'00-REPORT.md';p.write_text(p.read_text().replace('仍形成无关指令竞争。','存在无关阶段指令同请求并存、可能形成竞争。'))
# Refresh links and exact-byte evidence manifest after report assembly.
missing=[]
for f in A.glob('0*.md'):
 for target in re.findall(r'\]\(([^)]+)\)',f.read_text()):
  name=target.rsplit(':',1)[0] if re.search(r':\d+$',target) else target
  if not name.startswith(('http','mailto')) and not (Path(name) if Path(name).is_absolute() else f.parent/name).exists():missing.append({'file':f.name,'target':target})
(E/'report-link-check.json').write_text(json.dumps({'missing':missing,'pass':not missing},ensure_ascii=False,indent=2))
manifest={'schema':'read-only-prompt-craft-audit.manifest.v1','baseline_main':base['remote_main'],'new_provider_calls':0,'files':[]}
for f in sorted(A.rglob('*')):
 if f.is_file() and 'main' not in f.relative_to(A).parts and f.name!='MANIFEST.json':manifest['files'].append({'path':str(f.relative_to(A)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size})
(A/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'final_link_check':not missing,'manifest_files':len(manifest['files']),'missing':missing},ensure_ascii=False))
