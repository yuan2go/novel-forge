《雨线之外》作者指导型十二章试生产——部分交付

当前真实生成 **0章**、正式接纳 **0章**，没有作品正文或文学质量结论。本书匹配的远程模型范围与额度尚未获确认；已在任务开始时提出一次授权请求。Source、原生设计生成和正文没有执行，不能把工程fixture当成作品。已修复本轮捕获的知识使用追溯查询超时；最终提交完整资格v5通过，工程证据上限为LOCAL_BACKEND_ENGINEERING。原始失败报告与数据库快照保留。

当前作品与输入

- [作品导航](../novel-forge-author-guided-twelve/novels/yu-xian-zhi-wai/current/README.md)分别链接题材/世界、人物、三卷方向、首弧作者因果底稿、十二章逐场细纲及声音要求。它们是AI协助的作者草案；三卷方向为v2.1，其余为v2。
- 前两章先交付现有28张床；第三章核齐另8张的使用，六章结束原去向与初次交付问题。第七至十二章承接实际缺额与记录口径的后果，实际退床后才分配。十二章候选结局仍为总量36张、学校18/高街10/泵站8，两点各欠2张，不结束180章方向或约24章首弧。
- [作者草案聚焦复核](author-design-focused-review.json)未发现所查范围内必须修订的跨文件矛盾，保留36张流转、实际退床时点、先救助后核查、六章兑现与三卷代价差异。这是代码代理的作者草案复核，不是正文审稿或独立人工批准。
- [输入配置](../novel-forge-author-guided-twelve/config/production/author-guided-twelve)与[片段路由](../novel-forge-author-guided-twelve/novels/yu-xian-zhi-wai/current/input-routing.json)包含六份来源文件和33个有位置/哈希的片段。作者幕后预案仅供对应规划角色，Chapter任务只取本章场景意图。
- 当前冻结输入为[author-inputs-v5](author-inputs-v5)，manifest最终字节哈希 `sha256:ad4a6e414e0fe7414d451f59d2f5c12c67a6d41251b6388d28dd6db7c43c8c68`。历史v2/v3/v4目录及原A/B配置保留。
- [原生登记和回放证据](author-input-registration-v5-replay-evidence.json)：Content输入 `authority-output:a04ccfff-95d5-4efa-942b-c023afcd56da:creative.brief:v1`，内容哈希 `sha256:0e17a03e8d83e9398a0a5acb51d51e9371b70d5be8c1df4dd9e25b158318ac90`，状态 `AUTHOR_INPUT_REGISTERED_NOT_APPROVED`。同一键回放返回同一操作/版本。它不是原生世界、人物、规划生成或语义审批。

生产接线与真实修复

- 现有Content接受creative-brief-v3，Formation/Planning冻结作者角色和范围投影，要求候选对片段记录采用、改造、拒绝或私密保留及实际产物位置。规划采用声明仍不是正文质量证明。
- World Preparation原来漏送作者指导，现与Planning、Evaluation使用同一受保护的作者编译视图；Draft、Review和两条Revision路径保留合法指导。完整来源始终在冻结Context，最终请求用可解析的哈希回执保留来源联系。
- 不提高8192预算上限。真实失败的World目录重复输入被复现并修复；本书33片段在同一有界评估场景下最大估算8178/8192，全部选中文字保留。仅14估算Token余量，实际计划增长仍可能合法阻塞，不能据此声称真实十二章请求都能通过。详见[实际作者包预算反例](actual-author-budget-green.json)。
- 同一个既有预算账本增加最小单书契约：Source、设计、1—6章、7—12章、修复分配与业务授权范围分开核验。Source剩余额度不流入正文，修复保留原业务范围，未知调用继续占用预留；旧v1 A/B合同不能通过换名重置。
- 官方creation driver按真实接纳游标和章组在3/6/9/12停下，通过原生Content读稿记录与BookControl决定继续。六章审阅覆盖整段1—6；旧批准不能解除后来的操作暂停。问题保留身份、严重程度、修复目标、保留要求和原文位置，关闭须给出定位到接纳正文的复核证据。
- 修复了读稿清单被误选为Chapter治理输入、历史批准查询使用合成资产定位两个接线缺陷。检查点属于官方driver约束；其他直接AUTO Book操作不是全局读稿门禁。
- 阅读导出依据COMMITTED接纳、Outcome/Canon/StoryState及实际ChapterGroup血缘工作，支持单书目标游标，兼容原六章路径。候选和fixture不填补缺章；十二章停止不等于全书完成。

关键代码位于 `src/novel_forge/modules/story_design_authority/author_input.py`、`chapter_authority/provider_views.py`、`story_planning_runtime/`、`command_kernel/creative_budget*`，`mkaos_authority/runtime_usage.py`，以及 `scripts/run_creation_synthesis.py`、`creation_checkpoints.py`、`creation_reading.py`、`creation_checkpoint_review.py`。

素材、授权及操作

保留原20项素材和所有45个导入任务/版本历史，未扩库、未重建业务数据。专业液压片段只可用于核实的具体设备机制，不能推成城市排涝或调度知识；本轮情节不依赖它。真实解构、Candidate、批准Card均为0。新书显式采用新的DENY_ALL原创策略，未更改旧ALLOW_ONLY或A/B配置；以后使用Card须经实际审核及合法书级策略/未来计划变更。

[操作手册](../novel-forge-author-guided-twelve/novels/yu-xian-zhi-wai/current/OPERATIONS.md)给出原生冻结/校验、预算配置、Source小样、Formation恢复、第三章后未来PlanChange、读稿登记/决定和接纳正文导出。私有环境包装器为[runtime/nf](runtime/nf)，支持可配置NF_ROOT/NF_PRIVATE_ENV和`--module`；需要数据库的脚本经同一包装器执行，连接凭据不写入本报告或仓库。

当前运行键 `yu-xian-zhi-wai-author-twelve-v2` 对应v5输入。旧v1键只登记过v4输入，没有Book或Provider预留；[版本衔接证据](author-input-supersession-v5.json)保留原版本，项目、Book及预算合同身份不变。该变化修复仓库禁止把交付包编号置入当前配置的规则，没有更改校验或清除用量。

[待确认字段与分期建议](authorization-request.json)不是授权。建议路线为已有Codex CLI 0.154.0、gpt-6-astra/xhigh、`/Users/yuan/.codex-claude`账户引用、ACCOUNT_ENTITLEMENT、并发1，仍须明确确认本项目用途、阶段与累计上限。可仅先批准一个Source小样最多20次/50万可观测Token。完整候选上限480次/1200万，分配20/60/150/150/100次与50/150/375/375/250万Token；后阶段不能由前阶段成功自动获得授权。金额和不可观测开销UNKNOWN，不切换付费API。另一项目Wukong RESEARCH授权不可复用。

本任务平台远程Provider调用0，可观测Token0；没有新增远程费用调用。尚未配置本书授权，不把建议额度写成可用剩余额度。代码代理对话自身的开销不在平台账本统计。人工干预只有用户给出的创作方向/约束；本次文档修订和本机登记由代码代理执行，没有冒充独立人工评审或知识批准。

必要验证与证据边界

- `PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/integration/test_synthesis_formation_postgres.py --tb=short`：2通过，175.31秒，相关源文件测试前后哈希相同；[日志](author-native-pg-v5.log)、[哈希证据](author-native-pg-v5-evidence.json)。使用任务独立PG和脚本化Provider。
- 阶段预算相关18个PG用例、作者/预算/读稿相关单测及十二章driver PG反例已完成针对性验证。集合有重叠，不相加计数。早期十二章fixture在真实事务中接纳12章、完成4个章组，保持Book目标180并停在12，无13章请求；这些结果已由最终提交下的原生十二章用例重新验证。
- 最终提交治理与169个变更相关测试通过（1.09秒）；3884个后端用例通过（122.686秒）、101个迁移兼容性用例通过（280.136秒），失败/错误/跳过均0。756个PG事务用例通过（5518.969秒），失败/错误/跳过均0；其中原生十二章读稿/恢复/导出用例通过（451.300秒），两项作者Formation用例也通过。完整P0 v5、查询计划、Compose运行及资源清理均通过。
- 当前完整矩阵入口：`env -i PATH="$PWD/.venv/bin:$PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" NOVEL_FORGE_GROUP_PILOT_EVIDENCE_DIR="$EVIDENCE_ROOT/final-qualification-v5/native-group-exports" make pr-governance PR_BASE_SHA=5cce48a798b0eaaf3d1e395038ac101544701b99 PR_EVIDENCE_DIR="$EVIDENCE_ROOT/final-qualification-v5" P0_PROFILE=local PYTHONPATH=src:.`。它创建自己的UUID隔离PG，不读取素材业务库私有环境。
- 两次先前资格尝试都止于治理阶段、未启动完整矩阵：首次为当前配置的交付编号，第二次为相关实现变化导致两份活跃提案生命周期失效。修复保持旧输入/失败日志和原未决事项；未放宽校验、改历史资格报告或把提案标完成。

v3完整矩阵有755个PG通过、1个导出失败，原异常未携带具体stage，临时目录已清理，不能追认其确切原因。保留错误反馈后，v4捕获长篇六章导出的`knowledge_runtime_usage`查询触发30秒statement timeout；已备份隔离PG快照，并中止失败矩阵进行诊断。v4最终保留463个结果、2失败、0错误/跳过；第二个Fence失败发生在人工暂停测试进程期间，未暂停的对应恢复回归已通过，不修改原失败报告。

修复把项目、Book、capability及精确Card过滤移入knowledge selection，在同一SQL中先物化该有界集合，再连接Provider输入与回执。未提高timeout，未提前LIMIT，未删除版本/hash、项目、materialization/admission或成功receipt检查；历史撤销卡的既往追溯保留。同一快照旧查询返回空集却扫描Effect表115轮，执行约7.78秒；修复后无Effect扫描、约33毫秒。反向热缓存复测旧约8.27秒、新约90毫秒。它们是隔离现场点测，不能外推生产SLA。详见[SQL、计划和修复复核](query-investigation/fix-review.json)及[完整失败调查](export-failure-investigation.json)。

5个定向原生PG用例全部通过（369.01秒）：已选择不等于送达、11条精确持久化回执和组合过滤、六章目标导出、长篇六章导出、未暂停的Reader失败恢复。40个导出/阅读单测通过（0.84秒）；ruff及diff检查通过。[PG日志](scoped-usage-regression.log)、[JUnit](scoped-usage-regression.xml)。这些用例保留原跨书、回执、实际接纳和恢复断言，fixture不算真实正文。

工程最终资格：PASS_EXACT_SHA_P0；仅证明本地后端工程。

[最终结构化交付](DELIVERY.json)、[完整P0报告](final-qualification-v5/p0-backend-qualification-4c2fee982192346b53f3aff0a2cf40630a8b8545.json)、[治理报告](final-qualification-v5/pr-governance-4c2fee982192346b53f3aff0a2cf40630a8b8545.json)绑定同一完整SHA和实现树身份。

| 维度 | 当前结论 |
| --- | --- |
| ENGINEERING | QUALIFIED / 最终完整SHA的本地后端工程P0通过 |
| AUTHOR_DESIGN_ADOPTION | 原生Content已登记；真实Formation/规划采用未运行，只有工程接线证据 |
| SOURCE_TO_CARD | NOT_RUN / 等待匹配授权 |
| SOURCE_TO_PROSE | NOT_PROVEN |
| REAL_CHAPTERS_GENERATED | 0 / 12 |
| ACCEPTED_CHAPTERS | 0 / 12 |
| CROSS_CHAPTER_CONTINUITY | 工程fixture证据；真实作品未证明 |
| AI_EDITORIAL_REVIEW | 代码代理作者草案一致性复核；没有真实正文审稿 |
| INDEPENDENT_HUMAN_REVIEW | NOT_REVIEWED |

基线 `5cce48a798b0eaaf3d1e395038ac101544701b99`；最终SHA `4c2fee982192346b53f3aff0a2cf40630a8b8545`。隔离分支 `codex/author-guided-twelve-chapter-production-01`，本任务6个本地提交，未push、未创建PR、未合并。业务库在登记前有[备份收据](runtime/pilot-before-author-input-backup.json)，未运行迁移或破坏性测试；[最终只读核对](runtime/pilot-final-4c2fee982192-snapshot.json)确认45个导入任务/版本、零Candidate/Card/Book/预算预留及v4/v5原生输入哈希均保持一致。隔离验证资源已清理，调查用测试容器停止、快照保留。

尚无真实十二章正文及成本依据，不能评价文学质量、知识因果收益或决定扩到约三十章。下一步先在明确获准的阶段内运行Source小样或设计/首章，再根据实际正文与审阅逐段推进。
