# WP-LONGFORM-PLOT-PROGRESSION-AND-READER-PROOF-01：结构对账

这是工程与编辑审读记录，不是作者选稿决定、真人反馈或正式接纳。原库未写入；决定及激活发生在原实例可追溯副本。完整输入、原生记录与失败日志保存在本工作包的外置证据目录。

## 现场与文档清理

起点 main 为 `ecc666748166cd1d92cec789ebb84dd5607bf6a0`，PR #153、#154、#155 已合并，#156 的工作连续性与审读根因路由亦已在 main。原实例的只读对账见 `current-original-readonly.json`。原书为16章工作稿、正式接纳0、PAUSED；运行配置仍绑定 `d13e13b2b240d44da7c2864a16a5c7311d971629`，禁止模型派发，缺迁移0198。这些是本次现场结果，未直接沿用旧报告。

业务代码修改前的提交 `86e187c0` 修订了现有 `docs/current-system.md` 与 `docs/runtime-operations.md`：根 Skill 版本不等于冻结 Pack 版本，生成的操作窗口与正式接纳边界不属于虚构世界事实；结构停滞须回到未来计划变更。此前已归档的设计提案保持原样，五份 canonical docs 的权威范围不扩张；正文、旧合同、旧 Skill、迁移和失败证据均保留。

## 作品依据与停滞位置

原始作者 Brief 为 `authority-output:8bb703c5-c9fc-4027-80f3-c781cc7332cf:creative.brief:v1`：十六岁普通山村少年沈砚主动争取学习，经历宗门任务、资源竞争和山林行动，最终独自御剑远行。原定240章及本轮40章目标保持。入门、初次引气、首次结伴采药、正式课的近期次序已在所选1—8章实现，不再重新申请同一课位。

| 层级 | 现场结果 | 对本次方案的影响 |
|---|---|---|
| Reader Promise / Book | 主动成长与最终独行；上层允许任务反馈、关系及学习累积 | 不改变作品目的，不提前授予飞剑能力 |
| Volume 1 | 第12—18章新教学与有限事务；19—25章跨场所检验；33—40章一段完整行动 | 允许18章新课堂、19章走到山道，40不是卷末 |
| Arc | 沈砚累积实践；陆衡保留自己的练习；程观只处理交回职责；许庭有教学边界 | 角色的边界应落实为选择和行动，不能人人只核范围 |
| 原 ChapterGroup 16—19 | 16独练；17问范围；18再劳动；19课堂短暂结果 | 将准备和执行拆得过细，使12、16及未来17—19不断延后 |
| Chapter Mission / Scene | 观察、暂停、解释不能确定、下次再问占据主要篇幅 | 表达润色不足以解决，先合法调整未来任务 |

已完整阅读所选1—16章，并对照后续父计划。第5章采药交付、第13章热饭与唐穗对话、第14章搬桩合作有具体结果和人物温度，应保留。第12章大量重述气感未发生并等待药叶回话；第16章整章在无木片状态观察悬手，最后仍等询问和课堂。单独安静场景有效，问题在于其连续重复与下一动作的延后。

作者要求、世界约束与生成限制分别处理：普通起点、原创性、人物知识来源和未会御剑继续保留；“问清范围再动手”可在一次完整行动内完成，不必独占章节；正式接受0只限制 Canon/状态提交，不否认精确已选工作稿中人物经历。并发、事务、Provider授权属于工程边界，不转成角色口吻。未全局禁用任何词。

## 原生变更与已保留的失败

首方案通过真实 Provider 生成、比较、隔离运营者决定和激活，但保留了16—19章范围；它不能在工作进度16的检查点新冻结。`REALIZATION_WORKING_BOUNDARY_INVALID` 被保留，没有放宽门禁。后继方案将新执行范围收为17—19，16章只作为选定来源，见 `new-group-candidate-v2.json`、`activation-v2.json`、`resume-v2.json`。原生类型 `HUMAN_FEEDBACK` 在此是 operator change-request 的既有枚举名称；记录明确为隔离运营者方案，真人评价及原库作者采纳均未发生。

| 章节 | 旧方案 | 合法后继 |
|---|---|---|
| 17 | 询问、缩小范围，等待劳动 | 接下并完成一处场边清理；陆衡拒绝新增劳动去练自己的木杆；矮案有可用场地 |
| 18 | 再做劳动与交回 | 清出的场地投入课堂；以木片反馈学习主动收势，保留有限能力 |
| 19 | 课堂再试短暂亮纹 | 实际走到山道选取干直落枝、处理湿路和负重、返程交回；用途与来源当场可见 |

初检上层的事件方向允许17—19这些推进；逐章实际审读17后继续核验硬限制，发现Volume1另有禁止提前卷二“稳定重复与任务工具”功能的生成节奏限制。它会阻碍20—40的累积结果，需要再在原生变更中修改未来Volume及相应Arc，而不是让Writer违背父约束。Book的作者目标不要求这个绝对延期。检索的共用人物/父源命中保留 DEFER，未将身份重叠自动认定为因果冲突或批量使上层失效。语义穷尽性仍未证明；后续正文出现上层矛盾须再次原生变更。

恢复途中发现输入重绑定丢失初始 Story State/Canon 配对。修复现有 BookReplanCoordinator 的继承逻辑；对已确认成功但内容缺失的快照，以原生 pause → resolve → bind → resume 创建可追溯后继，不修改旧快照。七项定向回归通过，旧无配对合同兼容。后继17—19已经通过现有 Working Realization 冻结门禁。

## 运行选择与证据边界

正文默认 Pack 仍绑定 v4；本次只为显式实验 Pack 选择 `prose-generation-v5` 的准确内容哈希。沿用 v3 工作连续性/人物反应/行动后果机制，近期三章完整正文必需，旧文在18000字符预算内按来源及范围选择；遗漏随冻结投影记录。沿用 main 已存在的最终请求 v13 共用上下文去重与容量校验，不更改硬上限、输出目标或授权模型。会员调用的金额与权益用量若无实测，保持 UNKNOWN。

规划、v5 Skill、v3投影及现有v13容量处理是组合路径；不能凭本段编辑意见证明单因素或普遍市场效果。第17章已经由真实Provider保存、读回并精确版本导出，清理实际完成，但仍是低变化样本；不能据此宣布文学改善。18起继续运行，逐章证据另见导出与continuation。本记录不以计划激活替代正文交付。

真实 Writer 首次请求在 Provider 前置 Schema 校验被拒绝：v3工作稿投影加入可选 `working_memory_json`，而 Codex严格输出要求所有 property列入required。v6只在working-memory合同中以可空传输并在解码时恢复可选语义，原领域Schema及正文检查不变。原始v5拒绝、两次未派发Pack预检失败及其后继均保留；最终修复继续绑定普通coordinated Chapter合同与准确的现行Pack，不重置历史Attempt。没有以增大容量或降低正文输出要求处理此问题。

## Future parent correction and history read boundary

The activated Volume successor invalidated its six dependent Arc bindings through the
native lineage owner. All six were regenerated and activated; additional native Arc
Plan Change corrected Xu Ting's frozen female identity and a copied historical three
chapter profile assertion. The effective native delivery window remains40; the Book
strategic total remains240. Old versions and rejected/provisional candidates remain.

A19–23 Group candidate was generated after preserving the original preflight failure.
Its five small steps (start, route, sort, partial delivery, remainder) still risked slow
progression. It was retained unactivated for comparison. A separate governed input asks
for the limited common task to finish by21, then22–23 consume actual results in choices,
practice and relationships; no early grant of the later stable ability is authorized.
This is a semantic planning successor with changed frozen evidence, not an unknown
Provider resend or four versions of one Chapter.

Future parent invalidation also reached already delivered, unaccepted working prose.
The native input loader now asks Book to verify the next writing frontier, current
selected preceding versions and exact frozen working hashes. It can then read only
historical draft/author-edit sources invalidated by active same-Book Plan Change.
Invalidation records remain; governance/qualification remain required. Current plans,
Intent and Memo are excluded, so the unproduced19 graph still requires its separate
native upstream recovery and corrected typed Chapter lineage. No Canon acceptance or
human author approval is inferred from this historical read permission.

Focused historical input and existing selection/handler tests:24 PASS. Working projection,
native continuation and plan recovery regression:53 PASS. These are engineering tests;
actual prose and literary evidence are reported separately.

The compressed19–23 successor is now active and Frozen. Its limited task is first
performed20 and completely delivered21;22–23 consume actual food, retained practice time,
material feedback and relationship consequences. No stable cultivation ability is granted
before the parent teaching sequence. The alternate slower Group remains unactivated.
The Group prospectively binds the explicit v3 working snapshot; the Book default Arc
projection remains legacy. Chapter planning and Writer selections are traced individually.

The corrected19 Chapter Plan is current and Frozen. Native Book recovery retired the old
preprose graph after preserving its settled Memo, then appended generation2/predecessor
binding. Exact retirement replay exposed and corrected Kernel payload nesting. The new
Memo's indirect sources also exposed a loader scope defect: its undispatched terminal
Attempt is retained through a bounded exact Kernel successor. Context Build reads direct
historical sources and retries its original remaining Attempt. Neither path resets a
Provider semantic exhaustion counter or rewrites terminal history.

The canonical Runtime guide consolidates the duplicate historical working-source paragraph into its working-memory recovery procedure; the replacement retains exact Book reservation, current selection, range/hash and active same-Book PlanChange checks. No historical evidence or frozen prose was removed.
