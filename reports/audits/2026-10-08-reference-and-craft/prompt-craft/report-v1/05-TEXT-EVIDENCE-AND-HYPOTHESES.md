# 文本证据、反证与七项假设

## 实际读到什么

42份请求是策划调用：stage-comedy 7、fantasy-cooking 7、archive-suspense 28；41成功/1UNKNOWN，draft operations=0。后一个用例做到Formation READY并不等于完整章；随后World前置Schema错误未发送。原运行证据来自[reports/audits/2026-10-08-creative-input-isolation/evidence/evidence.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/reports/audits/2026-10-08-creative-input-isolation/evidence/evidence.json:1)，只有这些冻结运行可说EXECUTABLE。

本地sol40保留5份正文语义输出，2 Draft / 3 Revision，均是陆圆灵兽食堂同一开篇章，15个scene artifacts。JSON与process receipt原样保留，审查阅读txt只用空行连接，空行不是已核实正式排版。process成功/authority_bound不等于Book接纳；没有将109个执行目录当109章，也没有将5个输出当5章。

|输出|类型|Operation|输入SHA256|全文/回执|
|---|---|---|---|---|
|chapter-execution:1c2816b8-f31d-4b88-9a81-a0d953c22d38|REVISION_OUTPUT|0c18ef39-5d25-47c2-bc0c-4b41c5dd501c|d3bf966d441612e351362f539e6dab5fc3c82440b6a4742eee0af6a2e2cac409|[chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.txt](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.txt) / [chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.json)|
|chapter-execution:427d95ec-3e8c-4141-ad77-7a300aff792f|REVISION_OUTPUT|3f72d5bd-b616-4d93-baf5-8abd55c2b52b|a35f75564772ad0d75af8bf49d9500618e4b6542a1d18ba4ebb3833a4db20034|[chapter-execution-427d95ec-3e8c-4141-ad77-7a300a-0169470d6b8520d4.txt](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-427d95ec-3e8c-4141-ad77-7a300a-0169470d6b8520d4.txt) / [chapter-execution-427d95ec-3e8c-4141-ad77-7a300a-0169470d6b8520d4.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-427d95ec-3e8c-4141-ad77-7a300a-0169470d6b8520d4.json)|
|chapter-execution:44e0e5aa-2cd4-429f-b8ee-f976a57c81f6|DRAFT_OUTPUT|b4db57d9-4807-4b74-8169-fbfc9f71cab4|bd71fc14d5241c0772ebedbd5d81d0987373ca2301e3fd7afe1a17a7231cbad2|[chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt) / [chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.json)|
|chapter-execution:b85d33d2-5103-4a4b-b33e-1bf6a677c0ed|REVISION_OUTPUT|0c18ef39-5d25-47c2-bc0c-4b41c5dd501c|21c5a3d2f1db1e7d84b085507f2f837e590065e3b08d75a30fa250a4d6ca01ef|[chapter-execution-b85d33d2-5103-4a4b-b33e-1bf6a6-ed51c175bd01d3f0.txt](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-b85d33d2-5103-4a4b-b33e-1bf6a6-ed51c175bd01d3f0.txt) / [chapter-execution-b85d33d2-5103-4a4b-b33e-1bf6a6-ed51c175bd01d3f0.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-b85d33d2-5103-4a4b-b33e-1bf6a6-ed51c175bd01d3f0.json)|
|chapter-execution:cf41d403-ddbc-417b-9d98-3934ff914c91|DRAFT_OUTPUT|a9f90a3b-a805-40bc-bafb-4376fd9bfca1|30217219fbeae561a988a04f204cf9ef382eea6fe32a9b25dc2d0eaf75300e4c|[chapter-execution-cf41d403-ddbc-417b-9d98-3934ff-b455d8677864952b.txt](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-cf41d403-ddbc-417b-9d98-3934ff-b455d8677864952b.txt) / [chapter-execution-cf41d403-ddbc-417b-9d98-3934ff-b455d8677864952b.json](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-cf41d403-ddbc-417b-9d98-3934ff-b455d8677864952b.json)|

有些Revision共享Operation ID，可说明同Operation产生多份输出；仍缺source_draft_version_id、Review及selection表，因此不能把时序自动画成修订祖先链或称最后一份最佳/接纳稿。

## 可定位的现象与阅读判断

|现象|原文/位置|可能影响|反证及其他解释|置信度|
|---|---|---|---|---|
|动作之后再阐释原则|“浅口碗是他根据眼前桌面提出的做法，现做或延后须由团耳回应。”[44e0e5aa正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt:19)；“此刻能看见的，只是这一回的触碰；它究竟怎样吃，还要等碗交到它面前。”[44e0e5aa正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt:33)|原本可从选择/吃饭理解的信息被重复解释，潜台词和读者推断空间减小|单独一句可能服务谨慎人物与医疗饮食设定；问题是这类解释覆盖多个环节，不是说明本身错误|样本现象高；读者影响为编辑判断，中；Prompt因果低|
|反复强调证据作用边界|“它没有说这碗适合别的来客，也没有替将来的每一顿作保证。”[1c2816b8正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.txt:56)；“这页只说明这一顿怎样完成。”同稿|讲述一顿饭的篇幅反复用于证明不外推，而非人物交锋、关系变化或新信息|现有规则确要求不凭物种猜食性，事实边界应保留；可以通过行为守住，无需每次讲授|现象高；因果未定|
|核算细节成为主要收束|“拿笔核算的这会儿仍是收工的一部分，他想了想，又给记录本身留了一行。”[1c2816b8正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-1c2816b8-f31d-4b88-9a81-a0d953-383ee78b544d66a4.txt:51)；到货→询问→选择→控火→温度→反馈→工时重新全程列账|读者重心落在流程完成；结束只回到明早核货，持续成长阅读期待在该样本中较弱|食堂经营可写记账；若账目引发错估、利益冲突或经营抉择，也能有戏。历史要求本就温暖经营轻喜剧，不能据此宣判修仙长篇|样本结构高；跨书/长篇推广不成立|
|Revision版本补入同一核算轴的更多说明|427d、1c在44e相同片段基础上增加瓜皮/淘米损耗、守锅与等温分开、纸格不令一天变长；[427d95ec正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-427d95ec-3e8c-4141-ad77-7a300a-0169470d6b8520d4.txt:55)|新增篇幅未明显改变人物关系/行动局面；可能增加工整与重复解释|缺原Review和父候选，不能断言由评分、长度repair或何条Prompt造成。历史简报5000–6000汉字可能施压，但其也禁止灌水|文本差异高；修订因果低|
|存在生活幽默与真实动作|“凳面很小，占住的路倒像一张正经椅子。”[44e0e5aa正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt:7)；“团耳用爪背一拨，把勺柄挪到了另一侧。”[44e0e5aa正文](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/evidence/chapter-execution-44e0e5aa-2cd4-429f-b8ee-f976a5-1104c2505f1689a2.txt:35)|道具/动作有趣，团耳不完全只是主角纠错工具|应保留。不要把客人选择写成新强制冲突，不需给安静结局强加反转|文本存在高；读者效果待人读|

该样本确有“停一下—收回手—做得更谨慎”动作，但不足以证明全系统普遍采用“想反驳—停住—理解—调整”。这里并无必须反省或听劝成长的当前公共指令证据。不能把一种人物节奏直接变为禁令。

## 反证：人物可以有欲望、回避与未解冲突

[novels/original-100ch-work/candidates/方向-04.md](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/novels/original-100ch-work/candidates/方向-04.md:86)中鞋匠问哥哥是否知道，陈满答“开胶了”；手里九文对方要十二；哥哥给三文却要求未时去运货，报名也是未时。物件、钱与时间同时牵动人物利益，误导回答保留了潜台词，关系没有同场和解。状态明确“候选待作者选择”，只是一段原创声音测试，不是完整章或本轮方案。它反驳“模型/Skill只能温和工整”的绝对命题，也不能证明长篇已经达标。

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

[src/novel_forge/modules/mkaos_authority/craft_catalog.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft_catalog.py:45)的“受控留白”明确“保留行动与后果，省去读者已能推得的连接说明”，禁用条件包括省掉因果/空间/知识必要环节；“长短句节拍”明确不规定全章比例。这比“写得更像真人”具体，宜选用而不堆叠。

[src/novel_forge/modules/mkaos_authority/craft_selection.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/mkaos_authority/craft_selection.py:101)按上下文词项匹配、频率、近章重复与副作用观察排序，值属CONFIGURABLE_POLICY；词项命中/冷却可避免堆叠，但不证明适用性或文学质量。其本身标出`creative_benefit=NOT_PROVEN`/`ACCEPTED_PROSE_OBSERVATION_NOT_READER_EFFECT`，应保留证据上限。

[src/novel_forge/modules/creative/editorial_learning.py](/Volumes/DevSSD/Development/Workspace/audits/WP-WEBNOVEL-PROMPT-CRAFT-AUDIT-01-20261008/main/src/novel_forge/modules/creative/editorial_learning.py:72)将所有非DEFER编辑决定编译为REQUIRED/SCENE_INTENT。原文同时带适用条件与副作用，符合作者主动取舍；风险是“有条件采用的方法”若被下游当必展示技巧，会磨平自然变化。当前没有相应真实正文因果证据；优先查既有projection是否保留条件，再考虑允许方法强度，不直接删除REQUIRED或把已有承诺降为可选。

热门榜单查询在可读运行材料中未取得可核验的结果→实际阅读链。参考source-manifest的full_source_semantic_review=NOT_RUN是2026-10-02时点；CODEX-CONTINUE已有后续研究任务，旧manifest不能证明后来从未读过。本轮不重读整本、不凭简介或模型记忆造拆解，不宣称知识卡数量带来质量提升。
