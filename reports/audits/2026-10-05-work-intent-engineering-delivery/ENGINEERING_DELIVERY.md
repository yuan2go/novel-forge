# Novel Forge 作品意图贯穿与创作指令体系一致性：工程交付

本轮完成正式链上的代码、合同、Prompt/Skill 资产、质量动作、接纳与恢复修改；不是再一次只读审计。工程结论的上限为受影响主链的 `WIRED` / `EXECUTABLE`。未授予 `QUALIFIED`、`PRODUCTION_PROVEN`、`PRODUCTION_READY` 或 `CREATIVE_QUALITY_PROVEN`。

## 1. 冻结身份与边界

| 项目 | 身份 / 状态 |
|---|---|
| 仓库 | https://github.com/yuan2go/novel-forge |
| 执行时核验 main | `5b472b7719336929f7e5c24e5ce8d38151a0944a` |
| 原审计参考 | `b1d42e6107d871442baa71823f7c21bfeec841b1`；仅作历史线索，已对照本轮代码 |
| 开始时间记录 | `baseline.json` 的 `2026-10-04T16:01:35.096807+00:00` 为补录时刻；精确执行开始时刻 `NOT_RECORDED` |
| 代码/测试/资产提交 | `d943e401e8f9599db689895831a662d0b2054990` |
| 最终本地提交 | `bed701b2467b83766a24d3f4e3d2df94af17f674` |
| implementation identity | `sha256:52d03d242189d062a1e56cfb8cba424311bc34c71748fdd77a28316d1fb89edb`；两次提交相同，后者只更新文档投影 |
| 工作区 | `/Users/yuan/.codex/worktrees/work-intent-consistency/novel-forge`，分支 `codex/work-intent-consistency` |
| 修改规模 | 107 个文件；完整差异 `implementation.patch`；完整修改后源文件 `changed_source/` |
| 原工作区 | 保留 `codex/wp02-author-approved-run` / `ceb69fa2ff1c56f07005154bb5797616e933e8c2`，既有未跟踪产物未读取、覆盖或提交 |
| 外部边界 | 0 次真实 Provider、0 次生产数据库访问、0 次部署、push、PR、merge；仅本轮 disposable PostgreSQL 和 Python 替身子进程 |

执行结束 main 及最终状态见 `final-status.json`。该记录中的远端变化只作报告，没有混入执行基线。

## 2. 文档阅读、清理与保留

先阅读现行 `docs/README.md`、`docs/current-system.md`、`docs/runtime-operations.md`、`docs/development.md`，并对照作者入口、Foundation、Story Design、Planning、Context、Provider、Review/Revision、Book acceptance、Narrative State 和恢复代码。读取仓库审计及授权本地审计目录的 ENGINEERING_OPTIMAL_CHANGE_PLAN、AUDIT、REWRITE_PROPOSALS、inventory 与相关证据；这些材料不替代本轮代码事实。

生产修改前清理了收敛提案中把历史“只保存规格/草稿 PR”写成当前实施授权的句子，改为提案不授予执行权限、隔离实施以当前用户授权为准；README 明确历史审计不是额外 canonical 文档。生产修改后更新 current-system、runtime-operations 的实际版本、零增量、质量动作和兼容边界；reality-evidence 更新派生源码身份及 migration 0149 引用，不改写历史资格记录。

四份涉及本次源码范围的现行提案更新生命周期 SHA、implementation identity、review 日期，修正正文与元数据基线不一致。保留它们的 PARTIALLY_IMPLEMENTED、未解决设计、真实 Provider/文学验证及完整适用资格目标；未删除尚有效目标。未扩成全仓文档重整。历史审计包、旧模板 v7、旧专业 Skill v1、旧 Foundation/Planning/Chapter/Outcome 合同、既有请求与 accepted history 均保留。

## 3. 逻辑同源的实际生产链

现有作者 API/Brief → Foundation task/schema/normalization → Story Design 精确候选评价/作者监督 → BookDesign v6 → Book/Volume/Arc/ChapterGroup/Chapter typed planning → Narrative Realization v2 资格/批准/freeze → Production Preparation → ExecutionIntent v4、Memo、Context → 当前 Pack 模板 v8、实际 SDK/HTTP/隔离 CLI → Draft/Review/Revision/ReReview → QualityContext v5/质量报告/动作/候选比较 → Book 原子接纳/Outcome v4 → Canon、Narrative State、游标和下一章 → 原冻结请求恢复。

没有新增 Authority、Agent、配置 DSL 或题材套餐。`creative-baseline.v1` 是从精确计划和合法 Context 投影派生的阶段证据，不是装载全部资料的超级对象，也不能自行决定作品方向。宿主保留完整引用与私有来源，Provider 只收任务需要的公开角色/范围投影。

| 要求来源 | 传递及实际消费者 | 冲突/范围处理 |
|---|---|---|
| Brief 的 idea、genre、audience、constraints、source_boundaries | 现有 content Authority 保存 → 六类 Foundation → BookDesign v6/style projection v3 → 当前计划及 Writer Context | 无新增题材 enum 或未知题材回落；Foundation 对齐本书目标 |
| 已有 author_design 强度、可见性、章节范围及作者决定 | 既有精确 span/decision receipt → Foundation/规划的 host source binding → 公开 author guidance → Memo/Writer/Review/Revision | AUTHOR_ONLY 不泄漏给 Writer；DIRECTION/SCENE_INTENT 不升级成全书 REQUIRED |
| ChapterPlan.style_constraints | 在 DraftPlan v2 首次显式保留 → baseline → Draft、Review、Revision、ReReview、Quality | 不能以别处偶然重复补救缺失；候选与审读/接纳核验同一 baseline |
| 独立 style_policy.constraints | ProductionPreparation 首个投影点保留到 style_constraints fact → DraftStyle v2 → baseline/声音合同 | 顶层与已有结构化约束冲突显式报错，不按最后写入静默覆盖 |
| POV、target_word_count、禁止结果、章目标/功能 | 当前计划投影、baseline 和 QualityContext | 既有字段贯通；未新增专用 tense 等产品字段，也不声称自然语言输入已成为新增强类型能力 |
| 可选方法、空集合、零增量 | Foundation 字段级 applicability；ChapterMission v3；Realization feature_status；baseline method_requirements；Quality 适用性 | 明确不适用、禁止、未知、缺失与已确认无增量分开；已选择/到期承诺仍需证明执行 |
| quality_profile 的阈值、单位、权重 | Preparation 保留 → work policy v2 一次编译 → 正常/fallback 计算、报告、聚合、动作 | 缺少审美阈值是证据不足；不能静默用短句/段长偏好补齐 |
| 已接纳事实、知识与 accepted frontier | 接纳绑定 Outcome/Canon/State → 后续 Context；accepted quality host projection | 模型建议不自动变成事实；质量历史单独留给宿主，不混入 Writer 指令 |

## 4. P01—P08：问题 → 修改 → 实际消费者 → 验证 → 缺口

| 问题 / 责任包 | 修改与消费者 | 验证证据 | 剩余缺口 |
|---|---|---|---|
| P01，W1/W2/W5/W8：Foundation 无条件不可逆代价、升级、回报等 | `foundation_generation.py` 新 v2 task/schema/validator；optional 字段支持 null/空集合和字段级理由；Formation 规范化及 raw repair 使用同一冻结模式；BookDesign v6 消费六项当前 Foundation，style projection v3 保留 genre/audience/本书体验 | work_foundation_contract 正反例；原生六阶段 Formation/评价/激活 PostgreSQL | 未用真实模型评价新 profile；旧书不自动重写 |
| P02，W2/W3/W8：固定语义资格及作者监督被重要求独立资格 | 新 work qualification profile hash/criteria 以本书选择为准；Volume/层级输出 Schema 同步；Realization 使用精确 ACTIVE 作者监督 receipt；BookDesign/storage/Formation 均识别 v6，不把新 schema 默认标成已通过 | profile 新旧交叉拒绝、严格 FAIL；原生作者决定/receipt 持久化检查，supervised realization 分支/过期拒绝单测；activation 故障回滚及恢复 | 监督只证明作者决定，文学与独立资格不升级；原生作者 receipt 与 realization 投影分别验证，未另跑整条监督模式 PG 组合；未运行全平台重新资格化 |
| P03，W1/W3/W4：第 1 章/终章强制固定商业结构 | ChapterMission/Scene v3、计划资格/标准化和 current Schema 联动；每章计划、场景/beat 及到期执行仍严格，允许观察章、无反派、无新增披露、开放收尾和无后续 bridge | work_realization 正反例、已有层级/Chapter contract 检查；零增量原生接纳 | 零增量数据库用合成 typed plan，不冒充真实作者书的规划效果 |
| P04，W1/W4/W7：style_constraints 和独立 style_policy 首次投影丢失 | 修 Preparation、DraftPlan/Style、ExecutionIntent、Memo、Provider view 白名单；公开 guidance/voice contract 贯通；candidate comparison、ReReview、Quality、acceptance 绑定 baseline | 两种相反风格 × Draft/Review/Revision/ReReview 的实际 materializer；SDK/HTTP/CLI 发送边界与来源快照 | 未跑浏览器交互；未验证线上自定义 Pack/DB 覆盖项 |
| P05，W4/W6/W7：风格漂移/AI味脱离本书且不确定诊断触发正文修订 | 当前 QualityContext 持有 baseline；需可定位缺陷；非适用不给分/权重/动作；普通 Revision 过滤 UNCERTAIN/AESTHETIC，限定诊断 Scene/段落，禁止把建议 claim 为 resolved；Quality repair 冻结精确候选与允许范围 | located edit、未经授权跨段落编辑拒绝、建议/不确定无编辑、候选/审读 baseline 漂移拒绝；原生 Review→Revision→ReReview→接纳 | 无匿名文学效果评审；语义评价本身仍需合格模型/证据 |
| P06，W4/W6/W8：阈值、公式、单位、权重和 fallback 不一致 | work quality policy v2 明确单位/公式/冻结配置；正常/fallback 共用；NA/不足证据为 null score/0 weight；不足证据走 reassessment，不自动正文修订；旧 cache 需 policy/baseline/hash/语义版本一致 | 配置→计算→报告→动作正反例；重复 dimension、旧 profile 缓存和不同基准拒绝；longitudinal 正反例 | 确定性计算不证明文学质量；全局 backend P0 未运行 |
| P07，W5/W8：专业资料分析无条件优先爽点、追读 | multidisciplinary-knowledge 1.1 按当前分析目的/本书目标；Source methodology 精确版本/hash 路由；保留 1.0 原文资产；Writer 与源分析的版权/抽象隔离职责继续分开 | Source Import 相关单测、Skill 同步 check、Pack/hash/catalog 断言 | 未调用真实 Source Provider，也未读取/导出用户参考小说 |
| P08，W3/W6/W7/W8：每个 realization 强制非空状态/披露/义务与不可逆变化 | contract/proof v2 + mission v3 + Canon extraction v6/grounded v2 + Outcome v4 + reducer/rebuild/views 0149 联动；显式零增量可接纳两章、推进 cursor、重建空事件；不制造 revision_digest Canon 事实；宿主纵向质量排除确认零增量分母，但真实到期债务仍严检 | 9 章无固定章数 realization、lost-response replay、两章空事实/披露/State/Obligation 原子接纳/幂等/下一章；初始/0148 前向迁移 | 不自动迁移受旧默认影响的 accepted 计划/正文；需授权显式未来变更 |

### W1—W8 的闭环位置

W1：复用 Brief/author_design/BookDesign/style_policy 与派生 baseline。W2：task、Schema、规范化、独立资格、repair、v6 存储与 Formation 交接一起修。W3：层级合同→proof→slice→Chapter/Cannon/Outcome 消费一致。W4：修第一次丢失，再核验实际发送。W5：当前 Pack 2.10/template8/current operation hashes/compiler 与根 Skill 同步。W6：质量配置、测量、分数、报告、排序、动作和限域修订同语义。W7：选中/审读/接纳精确版本及 baseline，原子 accepted frontier 推进。W8：旧定义、Schema、资产和源版本保留；技术恢复不能升级创作语义。

## 5. 关键版本与兼容

| 合同 | 新任务 | 历史兼容 |
|---|---|---|
| Planning / Pack | 1.17.0 / 2.9.0；Foundation v2、work profile v2、BookDesign v6 | 1.11.0—1.16.0、Foundation v1、BookDesign v5 与历史 profile 保持解释；历史定义不能据此自由准入新任务 |
| Chapter / Pack / 模板 | 3.6.0；作者输入 3.6-author-input.v2；Pack 2.10.0；template/compiler v8 | 冻结 3.4.1/3.5.0、旧 author-input 与 template v7 保留；native reference sampling 同时识别受支持旧版本 |
| 计划/实现 | Mission/Scene v3；Realization contract/proof v2 | v2 mission / v1 realization 保留原冻结合同 |
| 投影/质量 | DraftPlan/Style v2、Intent v4、creative-baseline.v1、QualityContext v5、compiled work policy v2 / evaluation work-quality.v1 | 缓存及比较须匹配来源/基准/策略，旧 fixture waiver 不升级当前新语义 |
| 修订 | revision-domain-v4、quality-corrective-revision-v3 | 旧 v3/v2 保持旧候选执行含义 |
| 接纳 | book.chapter.accept 1.1 / handler2 / Outcome v4；Canon extraction v6 | 原 1.0/handler1/Outcome v3、旧提取 v5 仍可回放，不改 accepted 历史 |
| SQL | 0149 forward-only、backup-required；扩展已接纳事件和 rebuild views | 已发布迁移正文未修改；v1—v3 rebuild 和 v2—v3 event projection 保留 |
| 专业源方法 | 1.1.0 / 当前 Skill hash | 1.0.0 精确 legacy-v1.md/hash；未知版本失败，不静默用新文本解释旧请求 |

恢复缺陷的修复：raw-result repair 与 runtime continuation 保留源 execution_contract_version；新续接首次准入必须匹配精确操作员批准的 Pack/route。已准入 successor 包括等待域审批的候选，重放使用冻结 Attempt 和任务身份，不再因活动 Pack 升级而重新解释。仍核验 exact command、release、source/successor 关联与 snapshot；UNKNOWN 先调和、未派发证明和预算释放仍为取消/续接前提。并发注册只产生一个 successor，旧 source CANCELLED/history/snapshot 不改写，重复跟随无新增 Provider 调用。

frontier 修复：统一现有 Canon/State 两种字段别名，仅当双方版本和值完整一致才允许当前 v4 检索依赖；缺失和冲突不能通过规范化掩盖。宿主 accepted quality history 分离，最终 Writer 输入中不出现 host-only marker。


### 约束性质

`CURRENT_PROVEN_INVARIANT`：本轮测试范围内的精确候选/基准绑定、原子接纳、幂等与已接纳历史边界。`CURRENT_RUNTIME_FACT`：当前版本任务/Schema/投影/consumer 的具体语义；不能从常量存在推成永恒文学标准。`CONFIGURABLE_POLICY`：作品要求、选定方法、Context/request 预算、质量阈值/单位/权重及既有审批模式。`HISTORICAL_COMPATIBILITY`：被冻结的旧定义、原文资产、profile、SQL历史语义及 receipt。`UNRESOLVED_DESIGN_CONSTRAINT`：本书评价的实际文学可靠性、现场任务资格和未覆盖的监督模式串联；这些限制不能靠本轮单测升级成最终架构或文学质量证明。

## 6. 验证与证据

### 受影响检查

- `delivery-units-final.xml/log`：902 passed，1324 subtests passed。37 个受影响单测文件，未把重复运行相加为更多独立证据。
- `revision-version-final.xml/log`：109 passed，验证显式新修订版本后的普通/Quality 限域修订回归。
- `native-chain-committed.xml/log`：12 passed、18 deselected（499.58 秒），绑定最终 implementation identity 的 Formation、迁移、realization/接纳合并检查。
- 之前的 `native-formation-delivery` 为 5 PASS/1 FAIL；该 FAIL 由 `native-runtime-recovery-second` 1 PASS 闭合。`native-migration-zero-final` 为 6 PASS。它们是中间定位/验证，不冒充一次全绿矩阵。
- static architecture fitness、migration manifest、required-test manifest、instruction surface、historical reality、test reality、Skill sync、Ruff、diff check 和最终 SHA 的 documentation reality 均通过；proposal lifecycle 仍为 PARTIALLY_IMPLEMENTED。

### 最终发送快照

`final_inputs/manifest.json`、八份 `.prompt.txt/.json` 保存相反风格的 Draft/Review/Revision/ReReview 最终 Prompt、顺序、实际 output Schema、materializer 版本、变量与来源、Provider admission，以及实际 OpenAI SDK 参数与 DeepSeek 原生 JSON HTTP 请求体。真实发送函数被执行，仅客户 SDK/HTTP 外部 I/O 替身；CLI 用实际受控 Gateway/backend/supervisor，仅替换最终命令为 Python fixture，保存 stdin。均标记 `SYNTHETIC`，不含真实凭证/HTTP 认证头。

DeepSeek 正式 Chapter binder 本来采用 JSON mode。第一次错误地把审计构造的 strict 请求当成原生模式，失败保留在 `final-wire-boundaries.log`；修正检查为实际 JSON 协议后的 65 PASS 见 second 日志。未放宽生产输出验证或更改协议来制造通过。既有 strict adapter 检查也执行，不能据此宣称所有 Provider/Schema 或线上 strict 支持已验证。

`native_chain/` 保存本轮合成 Foundation/恢复/三章接纳业务边界与对应合成正文，以及四个完整生产组合的精确 accepted bindings；raw-result repair 和人工候选选择两个 Formation 检查在进入 Chapter 前结束；Foundation 业务输入不是完整 SDK/HTTP 请求，明确标注 `complete_sdk_or_http_request:false`。`native_fixture_temp/` 是本轮隔离测试状态，交付压缩包不包含它，不作为用户真实作品。

### 原生 PostgreSQL 的证明范围

直接使用现有 Production composition、Command Kernel、Authority/UoW、Pack 激活、Formation worker、Planning/Chapter scheduler、Review/Revision/ReReview、Canon/Quality、Book 接纳和 Narrative State。替身边界只在模型外部 I/O，数据库真实执行。测试里的 application release SHA 是明确的合成身份，
不是声称部署了同名 Git release；实际执行源码 SHA/implementation identity 由宿主证据单独绑定。Foundation/Realization 单独的零增量用可辨识合成 seed/qualification fixture；不把 fixture 资格称为真实独立模型资格。测试配置显式使用 128K Chapter Context budget，较小预算被硬门禁拒绝的中间失败保留；没有改变生产默认预算、开通出站或绕过压缩资格。

中间失败含 v6 未被实际 repository/Formation 识别、旧版本恢复活动 Pack 漂移、Context frontier 字段别名、raw repair v2 未到原生验证器、缺失 fixture applicability/版本字段和测试全局幂等键碰撞等。修了实际消费者或明确的测试输入；未删除失败断言、将 blocker 改 false 或 xfail。`test-results-index.json` 与保留的 XML/log 可区分失败和后续闭合。最早少量开发首失败没有磁盘全文，明确为记录缺口，不声称已保存全部首失败。

## 7. 尚未验证与上线条件

| 层次 | 结论 |
|---|---|
| 本工作包代码实现 | 已进入现有正式 owner/装配/消费者；受影响纵向范围 `WIRED`、原生隔离检查后 `EXECUTABLE` |
| 原生离线链 | 已通过最终发送对照及 12 项合并 PostgreSQL 正反例 |
| 现场部署 | `NOT_RUN` |
| 真实 Provider | `NOT_RUN`，0 次调用 |
| 文学收益 | `NOT_PROVEN`；合成正文/计算分数不证明阅读效果 |
| 全量 backend P0 / 无关矩阵 | `NOT_RUN`，不升级为全系统 QUALIFIED |

上线前需对目标 release 的应用/worker、migration 0149、Pack/Schema/profile 同一身份做现有适用准入与资格；按现有发布流程验证备份和前向迁移；限定范围核对现场旧资产/请求、Context budget、真实模型 Schema/协议与新审读 profile；如有旧默认污染，只经授权创建明确未来 plan change，不自动重写历史。原 16K 配置仍可能因真实必需上下文过大而失败，应按目标任务选择/资格化合适预算或压缩，不能静默截断。作者监督 receipt→realization 的模式分支与旧 receipt 拒绝由单测核验，原生 PostgreSQL 作者决定/receipt 检查独立通过；该模式尚未另做完整串联 PostgreSQL 案例，保留为模式组合覆盖缺口。任意自定义 Pack、部署覆盖、真实数据库资产及用户作品本轮未接触，不能宣称已全部排除。

小规模真实文学验证另需有效授权：固定两个差异明显、原始作者目标可见的作品与可控模型/预算；每组只改变一项已核实机制，保留原始要求及 exact request/版本；各取少量重复样本避免单次随机性，按本书目标匿名比较。分别记录身份/风格遵循、必要承诺、有效段落保留和阅读评价，不以阻断减少、评分提高或 Provider 成功替代文学收益。一次合格候选仍不能证明长篇稳定性。

本次交付的结果是：公共阶段能力继续明确约束资料使用、执行覆盖和接口；作品具体方向从当前 Brief、公开作者要求、已接纳方案及适用计划决定。历史模板保持可解释，但不再作为新任务的隐蔽全局创作偏好。

隔离数据库已按本轮专属 Compose project 删除容器和网络。工作区干净；本轮没有留下生产服务或运行任务。
