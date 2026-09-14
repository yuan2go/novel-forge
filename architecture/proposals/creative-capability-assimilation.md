# Novel OS 创作能力融合技术方案

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — 原生基础已存在；本提案的新增能力与质量收益尚待逐项验证。**
>
> **NOT_RUNTIME_AUTHORITY**

本提案将“吸收优秀 AI 写作仓库”收敛为 Novel Forge 原生创作能力的增量设计。它不是外部项目合并说明，不是当前系统能力声明，也不授权真实模型消费、生产数据库修改或作品发布。

审阅日期：2026-09-14。仓库基线：`3ad3a24c05a791899759cc947f83e5be65cdfaa1`。Git tree：`0745c487abefdec702a39db19ab568cdfe9db01c`。基线 Reality projection 记录的 implementation identity：`sha256:f2ff37fa36ec31862595c9a9a9383baabff13ec0b0956446bf443bd0b7adc713`。该 identity 来自已读取的 projection，不代表本次重新执行了完整仓库资格验证。

生命周期中的 `PARTIALLY_IMPLEMENTED` 指本方案复用的基础机制已有代码，不表示新增融合工作包已交付。当前行为仍以代码、迁移、接线和测试为准；本提案不覆盖 `docs/current-system.md`，也不替代现有工业蓝图、记忆生命周期与语料验证提案。

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-14",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "3ad3a24c05a791899759cc947f83e5be65cdfaa1",
    "implementation_tree_sha": "sha256:f2ff37fa36ec31862595c9a9a9383baabff13ec0b0956446bf443bd0b7adc713"
  },
  "scope": ["src/novel_forge/modules", "src/novel_forge/api"],
  "implemented_refs": [
    {"path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py", "symbol": "PlanningWorldPreparation"},
    {"path": "src/novel_forge/modules/story_planning_runtime/knowledge_translation.py", "symbol": "validate_knowledge_translations"},
    {"path": "src/novel_forge/modules/mkaos_authority/applicability.py", "symbol": "assess_applicability"},
    {"path": "src/novel_forge/modules/narrative_state/reality.py", "symbol": "NarrativeRealityRevision"},
    {"path": "src/novel_forge/modules/plan_change_authority/domain.py", "symbol": "semantic_plan_diff"},
    {"path": "src/novel_forge/modules/chapter_authority/candidate_selection.py", "symbol": "compare_candidates"}
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {"id": "external-evidence-and-rights", "description": "DESIGN_REVIEW_REQUIRED: freeze each external repository revision, trace executable mechanisms and verify file-level reuse rights before selecting implementation inputs.", "evidence_refs": [{"path": "src/novel_forge/modules/story_planning_runtime/knowledge_translation.py", "symbol": "validate_knowledge_translations"}]},
    {"id": "temporal-and-retcon-contract", "description": "DESIGN_REVIEW_REQUIRED: resolve event time, disclosure order, accepted revision and edition semantics without introducing a second Canon owner.", "evidence_refs": [{"path": "src/novel_forge/modules/narrative_state/reality.py", "symbol": "NarrativeRealityRevision"}, {"path": "src/novel_forge/modules/plan_change_authority/domain.py", "symbol": "require_approvable_scope"}]},
    {"id": "quality-and-routing-admission", "description": "DESIGN_REVIEW_REQUIRED: bind the separately planned cost-aware router, calibrated quality constraints, author controls and explicit budget grants to the current governed Provider path.", "evidence_refs": [{"path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py", "symbol": "PlanningProviderStage"}, {"path": "src/novel_forge/modules/chapter_authority/candidate_selection.py", "symbol": "compare_candidates"}]},
    {"id": "creative-effect-validation", "description": "DESIGN_REVIEW_REQUIRED: predeclare independent evaluation, human review coverage and stopping conditions for Chinese fantasy and wuxia before claiming creative improvement.", "evidence_refs": [{"path": "src/novel_forge/modules/mkaos_authority/applicability.py", "symbol": "assess_applicability"}]}
  ],
  "remaining_work": [
    {"id": "wp01-assimilation-diff", "description": "Complete the seventeen-source mechanism-to-native-consumer comparison and remove duplicate or unsupported additions.", "evidence_refs": [{"path": "src/novel_forge/modules/story_planning_runtime/knowledge_translation.py", "symbol": "validate_knowledge_translations"}]},
    {"id": "wp02-craft-transfer", "description": "Extend evidence-backed craft extraction, applicability and prose realization through the existing KnowledgeCard adoption chain.", "evidence_refs": [{"path": "src/novel_forge/modules/mkaos_authority/applicability.py", "symbol": "validate_applicability_contract"}]},
    {"id": "wp03-simulation-window", "description": "Validate and extend actor-scoped decisions, bounded alternative futures and rolling planning using native world preparation.", "evidence_refs": [{"path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py", "symbol": "PlanningWorldPreparation"}]},
    {"id": "wp04-temporal-projections", "description": "Specify missing as-of queries and rebuildable narrative graph projections over accepted lineage.", "evidence_refs": [{"path": "src/novel_forge/modules/narrative_state/reality.py", "symbol": "project_reality"}]},
    {"id": "wp05-revision-propagation", "description": "Extend precise downstream impact analysis, stale candidate handling and author diff review through Plan Change.", "evidence_refs": [{"path": "src/novel_forge/modules/plan_change_authority/domain.py", "symbol": "semantic_plan_diff"}]},
    {"id": "wp06-quality-optimization", "description": "Add calibrated craft and long-range diagnoses without replacing immutable candidate comparison or acceptance gates.", "evidence_refs": [{"path": "src/novel_forge/modules/chapter_authority/candidate_selection.py", "symbol": "compare_candidates"}]},
    {"id": "wp07-market-and-feedback", "description": "Admit cohort-scoped market observations and reader evidence as source and proposal inputs, never automatic Canon or plan mutation.", "evidence_refs": [{"path": "src/novel_forge/modules/plan_change_authority/domain.py", "symbol": "PlanChangeSource"}]},
    {"id": "wp08-author-workbench", "description": "Connect author-visible manuscript, memory, evidence and revision surfaces to native commands rather than direct state edits.", "evidence_refs": [{"path": "src/novel_forge/modules/plan_change_authority/domain.py", "symbol": "require_approvable_scope"}]},
    {"id": "wp09-production-experiment", "description": "Run explicitly authorized controlled creative experiments and report engineering, Provider, editorial and long-form evidence separately.", "evidence_refs": [{"path": "src/novel_forge/modules/narrative_state/reality.py", "symbol": "NarrativeRealityRevision"}, {"path": "src/novel_forge/modules/chapter_authority/candidate_selection.py", "symbol": "bind_selected_review"}]}
  ]
}
-->

## 1. 目标、范围与成功定义

### 1.1 产品目标

建设能够长期生产国风玄幻、武侠等中文长篇小说的 Novel OS。重点不是“自动生成更多字”，而是人物行动可信、打斗有战术与代价、感情发展有积累、幽默与反套路源于人物和情境，读者愿意继续阅读。

目标闭环为：素材与市场观察 → 证据化拆解 → 可复用技法 → 原创题材/世界/人物 → 分层规划与有限推演 → 正文 → 诊断与定向修订 → 正史接纳 → 作者/读者反馈 → 下一轮策略调整。

“融合全部有价值内容”解释为：候选仓库全部进入核查范围；每项机制都有明确处置；适配的机制进入原生生产链；重复、无证据或有害的机制可以明确拒绝。它不要求保留每个仓库的数据库、Agent 数量、界面、模型名称或脚本。

### 1.2 需求追踪

| ID | 对话中提出的需求 | 技术落点 | 完成证据 |
|---|---|---|---|
| R01 | 吸收所有有价值机制，避免只收集仓库 | 第 4 节融合矩阵、WP01 | 每个候选有证据、决策、原生消费者与验收样例 |
| R02 | 从好小说学打斗、感情、行事风格、反套路 | 第 8、13 节 Craft Transfer | 从原文证据到抽象机制，再到原创正文中的定位验证 |
| R03 | 国风玄幻/武侠，有趣有梗、可持续追读 | 题材策略、人物动机、场景技法与读者评价 | 独立评阅正文，不以标签数量或自评分替代 |
| R04 | 世界与人物不为剧情任意让路 | 第 10 节受约束推演 | 行动依据、认知边界、资源消耗与后果可追踪 |
| R05 | 百章之后仍保持连续性 | 第 11、12 节时间状态与规划 | 跨章事实、伏笔、关系和计划偏差验证 |
| R06 | 改一章不破坏后文，也不全书重写 | 第 16 节影响传播 | 局部修改、下游失配、版本 Diff 与安全接纳 |
| R07 | 真正提升正文，不继续堆 qualification-only 层 | WP02 优先完成技法到正文纵向切片 | 接纳正文、修订差异与独立阅读证据 |
| R08 | 控制 token，质量不能为省钱无声下降 | 第 9、15 节采样与路由 | 质量约束先满足，再优化单位合格产出成本 |
| R09 | DeepSeek 与本地 Codex CLI 按任务自动选择 | 复用独立规划的 Cost-Aware Quality-Constrained Provider Router | 固定路由决策、资格、预算与真实回执 |
| R10 | 趋势系统提供素材和方向 | 第 7 节市场观察 | 分频道、题材、时间口径的可追溯建议 |
| R11 | 作者看得见、改得动 | 第 17 节作者工作台 | 作者任务走查、权限、冲突与撤回路径 |
| R12 | 方案进入仓库、可交给开发 Agent 执行 | 提案生命周期与第 20 节工作包 | 文档提交不冒充功能实施或生产资格 |

本次设计不建设视频/有声书平台、通用内容农场、多租户 SaaS、自动账号发布、模型训练集平台或独立图数据库集群。封面、导出、翻译等可作为后续消费既有接纳稿的扩展，不成为核心质量闭环的前置条件。

## 2. 对前面讨论的校正

1. 外部 README、Star、功能名称和示例书只能说明研究线索，不能证明实现成熟或优于 Novel Forge。本提案不是对 17 个仓库的完整代码审计；外部多数材料仍是 README 级线索，必须在 WP01 固定 commit 后追踪真实代码。
2. 当前 Novel Forge 已有世界准备、分层规划、认知投影、KnowledgeCard 适用性/采用、Plan Change、候选保留等机制。不能把前面讨论中的每个英文名都变成新模块。
3. “1–3 章窗口”“2–5 分支”“六层 Judge”“100 章/30 万字”均是可试验参数或观察规模，不是普适架构定律，不自动构成长篇质量资格。
4. 格式、哈希、引用版本、枚举、明确资源约束可以做确定性检查；人物动机、POV 是否自然、战斗是否精彩、关系是否动人不能仅靠规则得到客观真值。
5. Narrative correctness、人物一致性和因果性不是互相独立的固定排序。先满足安全、授权、事实与认知边界，再在作者冻结的创作意图内优化阅读体验；作者可以通过显式版本变更调整设定，而不是被历史模型决定永久锁死。
6. “评分提高”“模型已无意见”“去 AI 味分数降低”都不等于变好。修订必须保护事实与作者意图，完成已定位诊断，并接受独立阅读检验。
7. 本地 Codex CLI 是执行入口，不意味着本地模型推理或免费无限量。订阅权益、调用额度、可观测 token 与现金成本必须分别记录；未知成本不能写成零。
8. 从外部代码提炼机制与直接复制代码/Prompt 是不同复用途径。许可证、资源文件、数据集和小说正文的权限应分别核查，不能以仓库公开可访问代替授权。

## 3. 当前基线与原生承载点

### 3.1 本次核查边界

已读取仓库根规则、canonical 文档规则、当前系统文档、Reality projection、既有提案生命周期样例，并抽查下列原生代码。没有在本次设计阶段运行数据库、生成章节、做真实 Provider campaign 或独立评阅整本书。

下表的“代码抽查”只支持相应代码路径/契约存在，不把它提升为 `EXECUTABLE`、`QUALIFIED` 或 `PRODUCTION_PROVEN`；文档映射行仍需 WP01 做入口到持久化的差分追踪。

| 原生承载点 | 本次依据 | 能确认的边界 | 融合处置 |
|---|---|---|---|
| `story_planning_runtime/world_preparation.py:PlanningWorldPreparation` | 代码抽查 | 固定世界准备输入、检查 frontier、通过有界 Provider stage 生成候选 | 扩展角色决策/窗口策略，不建平行模拟运行时 |
| `story_planning_runtime/knowledge_translation.py:validate_knowledge_translations` | 代码抽查 | 精确 Card 版本、ADOPT/ADAPT/REJECT、用途和适用性检查 | 增强技法内容与正文验证，不另建 Craft 权威库 |
| `mkaos_authority/applicability.py:assess_applicability` | 代码抽查 | 结构化前提、例外、冲突及未知值 | 扩展题材/场景契约，不把文本判断伪装成确定事实 |
| `narrative_state/reality.py:NarrativeRealityRevision` | 代码抽查 | 绑定 Book acceptance、Outcome、State、Canon、projection 的顺序版本 | 承载时间视图与图投影，不复制 Canon |
| `plan_change_authority/domain.py:semantic_plan_diff` | 代码抽查 | 计划字段语义差异、风险分级、已执行范围需单独 Retcon proposal | 增强精确影响传播与作者 Diff，不建立第二套大纲引擎 |
| `chapter_authority/candidate_selection.py:compare_candidates` | 代码抽查 | 候选/审稿版本保留、诊断检查、改善/退化与停止原因 | 扩展评价方法，不以“最新版”覆盖更好候选 |
| Story Design / Book Design / Hierarchical Planning | 当前系统文档及既有蓝图 | 原生 Foundation、typed plan 与激活边界已有承载点 | 复用；高级语义质量仍需验证 |
| Context / Capability Packs / governed Provider | 当前系统文档 | 已有角色投影、上下文预算和外部调用边界 | 复用；不从前端或外部 Skill 直连模型绕过 |
| Book acceptance / Canon grounding | 当前系统文档 | 最终正文、事实支持与原子接纳已有链路 | 保留，不把模拟候选直接接纳为正史 |
| Source Import / SourceWork / SourceUnit | 当前系统文档 | 导入、来源与作品/章节版本已有模型 | 扩展采样/分类策略，不另建语料数据库 |
| Reader / follow-up / recap | 当前系统文档 | 反馈是证据或未来计划建议 | 增加评价覆盖，不直接改 Canon/active plan |
| Admin UI | 仓库 README、开发规则 | 后端资格不覆盖 UI 产品体验 | 单独作者旅程验收 |

特别注意：`compare_candidates` 仍包含评分阈值等当前策略实现。它们不能因代码存在就被解释成已校准的文学标准；应在相应工作包中分类为可配置策略或待审设计约束。

### 3.2 与既有提案的关系

- `industrial-novel-os-blueprint.md`：沿用领域语义与原生权威边界；本提案只展开外部机制吸收、创作效果与工作包映射，不重新定义一套总蓝图。
- `narrative-memory-context-lifecycle-closure.md`：时间视图、检索、压缩、失效和恢复必须在其已有边界内做差分，不能再增加独立 Memory Authority。
- `classical-corpus-codex-validation.md`：复用来源隔离和实验授权；本提案不重复开放已有 campaign 的预算。
- 独立规划的 Cost-Aware Quality-Constrained Provider Router：作为共享依赖对接。WP01 核查其届时实现状态，未接线不宣称可用，不在每个创作模块重复实现路由器。

## 4. 外部仓库覆盖与融合矩阵

### 4.1 证据和决策维度

外部证据采用独立的研究标签：`CATALOGUED`、`README_REVIEWED`、`CODE_TRACED`、`RUN_OBSERVED`。这不是 Novel Forge 的能力状态词汇。

每个机制必须记录：仓库 URL、分支和 commit、文件/符号、上游证据范围、文件许可与资源许可、作用对象、已知失败模式、原生等价机制、差异、复用方式、目标消费者、必要迁移、验证用例和待定问题。未知字段保留未知，不补造版本或运行证据。

决策使用 `KEEP_NATIVE`、`EXTEND_NATIVE`、`ADAPT_MECHANISM`、`HOLD`、`REJECT_IMPLEMENTATION`。下表是设计候选处置，不是已完成的逐仓代码审计结论。

### 4.2 全部 17 个候选

| 来源 | 待吸收的机制线索 | 原生落点与预期增量 | 不直接吸收的内容 |
|---|---|---|---|
| [Narcooo/inkos](https://github.com/Narcooo/inkos) | 统一 action/harness、scoped Skill、章节工作区、分支比较、审稿保留 | `EXTEND_NATIVE`：Agent 调用原生命令、任务相关上下文、候选分支与作者操作 | 不移植第二套文件事实源、执行器或确认系统；旧对标 SHA 不代表当前版本 |
| [lingfengQAQ/webnovel-writer](https://github.com/lingfengQAQ/webnovel-writer) | 章节提交与投影、伏笔/微兑现/追读诊断、学习记忆 | `EXTEND_NATIVE`：Book acceptance 投影、Obligation、Craft/Review Pack | 不建第二个 CHAPTER_COMMIT 权威；README 区分 master/v6、冻结 v7、开发 v8，不能混合版本宣称成熟 |
| [Xiaoyangy/novel-studio](https://github.com/Xiaoyangy/novel-studio) | 角色私有观察、世界裁决、整弧预演、短窗口封存、逐章审阅 | `EXTEND_NATIVE`：World Preparation、role projection、typed planning | 不硬编码三章窗口，不复制 Go runtime、Qdrant 或独立 checkpoint 体系 |
| [NousResearch/autonovel](https://github.com/NousResearch/autonovel) | 修改-评价-保留/丢弃、读者面板、删改诊断、全文审稿、平台期停止 | `ADAPT_MECHANISM`：诊断驱动修订、不可变候选比较与长程审稿 | 不以分数阈值/评委没意见当质量证明；不默认启用美术/有声书流水线 |
| [EdwardAThomson/StoryDaemon](https://github.com/EdwardAThomson/StoryDaemon) | story tick、目标层级、动态记忆、张力、open loops、scene skeleton | `ADAPT_MECHANISM`：动机推进、轨迹调度、场景技法和有界未来推演 | 不默认取消全局方向；实验性 skeleton 不变成每段固定模板；模型张力评分不是读者事实 |
| [ynnyh/jarvis-write](https://github.com/ynnyh/jarvis-write) | 时间化事实、伏笔调度、大纲级联、标签化风格、Diff 接纳 | `EXTEND_NATIVE`：时间查询、Plan Change 影响分析、作者工作台 | 不直接覆写历史 Canon；不采用全书一键重写或去 AI 味分数门禁 |
| [AutoFiction-AI/autofiction](https://github.com/AutoFiction-AI/autofiction) | 文件式 Agent 工作空间、阶段化任务、跨章检索审稿 | `ADAPT_MECHANISM`：受限工具型审稿任务和长程实验 | 不复制跳过权限确认的 CLI 运行方式；不可让同书并行草稿直接并行推进 accepted cursor |
| [AI-Team-Team/AI-Novel](https://github.com/AI-Team-Team/AI-Novel) | 分层记忆、检索过滤、讨论式冲突诊断 | `ADAPT_MECHANISM`：事实/里程碑/细节投影、风险触发的独立复核 | 不引入 ATT 第二套控制面；不让讨论投票授权 SQL/Canon；不能因角色死亡就删除其全部历史信息 |
| [iLearn-Lab/NovelClaw](https://github.com/iLearn-Lab/NovelClaw) | 持续会话、书稿/人物/世界/记忆可视、运行可观察 | `ADAPT_MECHANISM`：现有 Web 作者工作区 | 不复制 Portal、多服务登录或把可编辑 memory bank 当直接改事实权限 |
| [KazKozDev/NovelGenerator](https://github.com/KazKozDev/NovelGenerator) | 角色知识、多线时间、专长任务、草稿 Diff | `ADAPT_MECHANISM`：场景 craft tasks、知识边界与多线验证 | 不照搬固定多 Agent 插槽拼接、固定多轮润色或浏览器事实库 |
| [Anshler/graphify-novel](https://github.com/Anshler/graphify-novel) | Bible/图分离、跨章关系路径、线索查询 | `EXTEND_NATIVE`：accepted lineage 的可重建图视图 | 图的隐含关联是建议，不是事实；不要求迁移到外部目录/图存储模型 |
| [multi-agent-story-generation/MARP](https://github.com/multi-agent-story-generation/MARP) | Designer/Controller/Environment/Player 的职责分离 | `HOLD` 后择机 `ADAPT_MECHANISM`：角色决策与世界后果的独立输入契约 | 研究样机不等于长篇生产方案；不复制整套多 Agent 消息运行时 |
| [EdwardAThomson/NovelWriter](https://github.com/EdwardAThomson/NovelWriter) | Lore→结构→场景→章节、题材策略、分尺度质量趋势 | `KEEP_NATIVE` / `EXTEND_NATIVE`：层级规划及场景/章/弧评价 | 不再建 Lore/Outline Authority，不移植 Tkinter GUI 或默认模型清单 |
| [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode) | 扫榜、拆文、剧情机制、情绪满足、商业写作、针对性去味 | `ADAPT_MECHANISM`：Source/Craft/平台策略 Pack | 不把具体作品情节模块直接拼接成新书；不把宿主安装器搬入生产 |
| [giapnguyen74/xnovelist](https://github.com/giapnguyen74/xnovelist) | AI 自主程度、明确 Accept/Reject、快照、作者优先编辑 | `ADAPT_MECHANISM`：作者控制模式与提案式编辑 | 不移植浏览器直连 Provider/IndexedDB 权威；其 README 把部分高自主等级标为设计/脚手架，不当已实现能力 |
| [304769384-png/fanqie-novel-skill](https://github.com/304769384-png/fanqie-novel-skill) | 战斗代价/战术诊断、重复模式、语义保持式改写 | `ADAPT_MECHANISM`：战斗/节奏 Review Pack | 不硬编码对白≤40%、至少三次攻击、每章同字数；“AI 味被限流”等 README 说法不能当平台已证实规则 |
| [wen1701/FanqieRankTracker](https://github.com/wen1701/FanqieRankTracker) | 定时快照、相邻日差异、多窗口聚合、趋势看板 | `ADAPT_MECHANISM`：上游市场 observation 与题材建议 | 当前 README 聚焦女频新书榜，不能替代玄幻/武侠目标频道；不将排名当质量或真实留存 |

17 个来源均被覆盖，但不要求 17 个独立组件。重合机制统一合并为一个原生消费者。Bishu/DeterminFlow 作为当前仓库已记录的历史对标输入继续保留，不另起第二轮同义工作包。

### 4.3 吸收准入

先读代码再定复用粒度：方法研究、接口/契约借鉴、数据结构适配、算法独立实现、经许可复制组件。每项均需权利审查；本提案没有复制外部代码、Prompt 或小说段落。

许可证不能简化为“GPL/AGPL 一律不能用”或“MIT/Apache 随便复制”。实现工作必须查固定 SHA 的实际 LICENSE、NOTICE、文件头和资源授权，确认预期分发/部署方式；许可不明时暂停复制。独立实现也不是跳过权利核查的理由。代码许可不自动覆盖样例小说、外链语料、字体、图片或另库产物。

## 5. 内容层级必须分开

| 层级 | 资产含义 | 可消费方式 | 禁止混淆 |
|---|---|---|---|
| 素材 | 原始文本、市场快照、专业资料、来源与权利 | 受控解析和分析 | 可访问不等于可用于生成 |
| 拆解 | 有位置证据的结构/节奏/人设/冲突分析 | 生成候选知识 | 分析结论不直接变 Canon |
| 题材 | 读者、情绪承诺、类型机制、差异化方向 | Formation 候选输入 | 热门不等于适合本书 |
| 世界观 | 规则、资源、势力、信息传播与约束 | Story Design 后进入计划/推演 | 外部世界设定不能原样复制 |
| 人物 | 欲望、信念、恐惧、关系、知识、声线 | 动机推演、规划、正文 | 人物自述不等于客观世界事实 |
| 大纲 | 全书方向、结局、卷/弧和人物轨迹 | 约束近程规划 | 未来意图不等于已发生 |
| 细纲 | 章节使命、场景、节拍、信息释放、预期变化 | Chapter Contract/Memo | 预期变化不自动结算 |
| 正文 | 原创草稿、修订稿、接纳稿 | 审稿、最终事实提取、阅读/导出 | 有文件不等于接纳完成 |
| 审稿 | 定位问题、证据、保护项、修复目标 | 定向修订和接纳门 | 分数不能替代问题闭合 |
| 反馈 | 作者、模型读者、真人读者、平台观察 | 分开记录；生成策略建议 | 模拟偏好不是市场反馈 |
| 训练题 | 原创场景任务、判断题、对照样本与 rubric | 能力评测和作者训练 | 不自动进入生产 Context |
| 可复用模板 | 版本化技法契约、题材 Pack、评价模板 | 按适用条件编译到任务 | 模板不是万能剧情公式 |

训练题与评价样本可复用现有评价/内容资产边界；本方案不额外建设模型微调或自动训练流水线。

## 6. 目标架构与所有权

### 6.1 一条主链，两类辅助输入

```text
受控素材/专业资料 ──> Source Import/Deconstruction ──> KnowledgeCard/Craft
市场快照 ──────────> 可解释的题材与读者观察 ──────────┐
作者创作意图/约束 ─────────────────────────────────┤
                                                  v
                           Story Design / Book Design / Foundation
                                                  v
                           Hierarchical Planning + World Preparation
                          / 角色私有观察 -> 行动候选 -> 世界后果 \
                         / 有限未来分支 -> 导演比较 -> 近程计划   \
                                                  v
                           Chapter Contract/Memo + governed Context
                                                  v
                          Whole-chapter Draft + scoped Craft Tasks
                                                  v
                      Review -> Targeted Revision -> Candidate Compare
                                                  v
                      grounded Canon proposal + Quality + Book acceptance
                                                  v
                  accepted Reality/State + projections + next chapter
                                                  |
             作者/读者反馈 -> recap/impact proposal -> Plan Change
```

模拟输出、市场观察、知识、未来计划、候选正文、已接纳事实分别有不同身份和写权限。不存在一个“超级 Agent”可以绕过这些边界。

### 6.2 领域归属

| 能力 | 拟复用的权威/承载点 | 允许写入 | 不允许 |
|---|---|---|---|
| 素材与拆解 | Source Import、Source Authority、Content | 来源版本、分析候选和证据 | 导入时激活技法或改书中事实 |
| 技法适用性与知识 | MKAOS、现有 KnowledgeCard | 知识版本、适用性、选择证据 | 新建“Craft 真值库”与双重批准链 |
| 创作意图/人物/世界设定 | Story Design、Book Design | 候选、语义决策、激活版本 | Writer/Actor 私自改变活跃设计 |
| 推演 | Worldbuilding + Story Planning Runtime | 有界候选与决策证据 | RuntimeJob 自行成为世界事实权威 |
| 规划与重规划 | Hierarchical Planning、Plan Change | 类型化计划和批准的未来变更 | 直接覆盖已执行计划与历史正文 |
| 正文与修订 | Chapter Authority、Review、Quality | 不可变候选、诊断、比较结果 | 最新候选自动取代所有旧稿 |
| 正史接纳 | Book acceptance + Canon/Narrative State | 同事务绑定正文、事实与必要投影 | 外部脚本、图数据库、Agent 直接结算 |
| 图/时间/记忆展示 | 现有 read projection / retrieval | 带 watermark 的派生数据 | 派生数据反向直接修改 Canon |
| Provider 与成本 | 现有 ProductionExecution/Command Kernel | intent、reservation、receipt、settlement | 每个模块建立自己的调用账本 |
| 作者操作 | 现有 API/命令 + Web 客户端 | 版本化请求、提案、批准 | 前端写数据库、导入未审事实 |

这张表是设计约束。WP01 必须进一步映射到实际入口、类/函数、UoW、repository、迁移、Provider effect、gate 和恢复路径。

## 7. 市场趋势：提供方向，不控制正文

### 7.1 数据模型

在既有 Source/Content 资产中表达两种不同对象：

- `MarketObservation`：来源、平台、频道、榜单类型、作品稳定 ID、观测时间、指标名称/单位/原始值、榜单位置、分类、抓取覆盖、原始快照 hash、解析器版本。
- `TrendAssessment`：输入 observation 版本、比较窗口、同类群定义、确定性计算、模型解释、置信限制、建议方向、反例与人工确认项。

这是拟议的版本化内容契约，不是本提案新增的数据库表。原始排名、平台指标与 AI 推断题材必须分栏，不能相互覆盖。

### 7.2 处理规则

先保存快照，再作差异与聚合，最后调用模型解释确有变化的部分。按频道/题材/榜单类型/新书阶段建立 cohort；不能把女频新书榜、男频玄幻榜、完本榜直接合成一个排名变化信号。

缺失榜单不等于掉榜；掉出 Top N 不等于阅读量归零；名次是序数，不直接解释成阅读量增长百分比。指标变更、重置、抓取失败、分类迁移、重复作品必须显式处理。7/14/30 日分析只在实际覆盖该窗口时输出，历史不足时报告覆盖不足。

对用户的玄幻/武侠方向，先验证有授权且稳定的对应数据源，再做频道适配。FanqieRankTracker 可提供技术线索，不能直接提供该目标市场的有效样本。

### 7.3 下游与反馈

输出“题材机会候选”，内容包括目标读者、情绪承诺、近期变化、拥挤度提示、差异化假设与证据时效。由作者/Formation 选择使用，不自动改已开书的题材、人物或结局。市场信号不是剧情因果，不证明某种写法导致高排名。

定时采集属于未来显式配置的运行任务；本提案提交本身不启用任何爬虫、定时器或发布动作。

## 8. Craft Intelligence：从拆解到可验证运用

### 8.1 不建立第二套知识系统

以现有 KnowledgeCard 为身份、版本和批准单元，把场景技法作为其抽象内容的类型化扩展，并复用 `knowledge-applicability.v1` 与已有采用链。若新增字段无法被当前 schema 表达，应升级该资产 schema/编译器并保留旧版本读取；不能在严格 schema 上静默追加未声明字段。

建议的逻辑视图 `TechniqueSpec` 包含：

| 字段组 | 内容 |
|---|---|
| 身份 | 原有 Card AssetVersion、内容 hash、分析 profile/schema 版本 |
| 机制 | narrative function、问题、读者体验假设、动作/信息/情绪转换 |
| 适用性 | 题材、POV、场景类型、前提、例外、冲突、置信限制 |
| 结构 | 可变节拍、关键因果、资源代价、预期状态变化 |
| 使用边界 | 禁用场景、不能复制的表达/组合、保留作者声音的要求 |
| 证据 | 来源 SourceWork/Unit、定位与 hash、支持/反例、分析者/模型版本 |
| 编译 | 目标阶段、可注入角色、目标 plan 字段、原创建议/例子 |
| 验证 | 正文可观察现象、失败模式、需要人工判断的项目 |

技法的叙事功能是可迁移抽象；示例应为原创或具备明确许可，不存储“换名复写某章”的模板。

### 8.2 抽取工作流

```text
来源/权利核查 -> 章节及场景切分 -> 分层采样
 -> 证据化拆解 -> 机制候选 -> 支持/反例对照
 -> 去作品特有表达和实体 -> 适用性审核
 -> 原创迁移训练题 -> 对照评价 -> KnowledgeCard 版本决策
```

一次分析的身份至少包含 normalized content hash、SourceUnit 范围、task/profile/schema 版本、模型/Prompt 版本和分析策略。导入身份与分析身份分离：相同原文可复用导入，但更换分类器/分析 profile 后应重算对应分析，不得因“文件已导入”跳过新分析。

分析输出保留证据跨度；没有看到的章节不推断为已验证的长程回收。人物关系与反套路需要前后因果窗口，不能只拿单句作技法证明。

### 8.3 生产使用链

1. 当前 Book 的 Knowledge access policy 先确定允许的 Card 集合。
2. 对冻结设计/计划输入执行适用性判断；缺条件为 UNKNOWN/CONDITIONAL，不自动通过。
3. Formation/Planning/World Preparation 对每个选中 Card 明确 ADOPT、ADAPT 或 REJECT。
4. 非拒绝项必须落到具体计划字段与用法位置，说明前提如何满足、保护什么、如何验证。
5. Chapter Memo/Context 只携带此计划已经采用的精确 Card 版本和任务相关内容，不重新引入被拒绝的知识。
6. Draft 将技法实现成情节/动作/信息变化，不在正文解释技法名称。
7. Review 对最终候选正文检查实际落点；“已检索”“已注入”与“实际奏效”分别展示。
8. 通过现有 acceptance 绑定正文；技法效果观测另作证据，不能自动提高知识等级或改 Canon。

这条链优先补全“证据 → 适用 → 采用 → 运用 → 验证”之间的薄弱环节，而非新增 Card 数量 KPI。

### 8.4 初始技法范围

首批覆盖：战斗目标/战术与代价、感情潜台词和关系微变化、人物意外但一致的选择、悬念信息控制、情绪压抑与释放、地位反转式幽默、场景转换、对话声线、章节期待与兑现。

具体作品的“打斗好”“感情好”是作者给出的阅读观察，不是本提案已经验证的作品分析结论。后续需用作者提供或获准取得的样本完成证据化拆解。

## 9. 语料与 token 经济性

### 9.1 按价值分层，不全量穷举

L0 做本地解析、归一化、作品/章节识别、精确和近似去重、统计及候选采样，不默认调用模型。L1 用少量代表窗口做来源分类和场景识别。L2 仅对高价值场景作证据化技法拆解。L3 对依赖关系/伏笔/人物弧的问题扩展前后上下文。L4 只对争议、高风险和评价候选做强模型复核。

高价值采样须同时覆盖开篇、日常推进、战斗、关系转折、失败、高潮、回收与低质量反例；不只挑名场面，不把“热门作品”全部当正例。新增作品和 profile 变化按依赖增量计算，不重复全库扫描。

### 9.2 可计算预算

估算模型为：`T_total = Σ(input_tokens + output_tokens + 可观测推理用量) + retry + escalation + evaluation`。现金成本另按当时计价规则、缓存命中/未命中、输出、服务附加项计算，不以字符数冒充 token。

对话中讨论过的 5,000 万～8,000 万 token 只是候选规模，不是已授权额度或必须消费的最低量。本方案不延续此前全量语料需数千亿 token 的做法。实施时先用小样实际测量每类任务成本，再按可接受知识/可接受正文产出外推，并同时报告区间与失败重试开销。

预算分离为 Source 分析、Formation/Planning、Draft、Review/Repair、评价实验、预留六类；父级 Book/Project/shared ledger 约束总量。数值与阶段授权须由现有政策/命令显式冻结，不写进外部 Prompt。

关键指标：每个被接受且实际使用的机制成本、每万接纳汉字成本、每项已解决诊断成本。低价格但大量失败或不能迁移的拆解不视为经济。

## 10. 世界与人物推演

### 10.1 角色行动与世界后果分离

角色决策输入由原生 role projection 产生，只含其可知观察、私有记忆、当前目标/信念/情感、可用资源、关系和可行动作约束。作者全局秘密、其他角色私密动机与未发生未来不能混入 Actor Context。

角色输出为行动提案：意图、行动、所依赖的已知信息、预期结果、可承受代价、风险和备选动作。保留简明理由与证据，不要求保存或展示模型原始思维链。

World Arbiter 输入所有合法行动及世界规则，给出冲突裁决、资源变化、伤害/位置/关系后果和信息传播事件。它可裁决行动失败或代价变化，但不能为了结局方便偷偷替角色改意图。必要改意图须重新生成角色决策，并保留版本。

确定性检查只能覆盖已形式化规则；未建模的战术合理性、社会行为和心理因果仍是有不确定性的语义判断，应由独立评价或作者裁决。

### 10.2 有界推演，不模拟整个世界

沿用 `PlanningWorldPreparation` 和 WorldTransition 的原生承载点。依据当前弧、场景相关性、势力进度和潜在信息影响激活角色；未被激活的远端角色保留其状态，不进行逐人逐 tick 调用。

世界时钟可以支持离屏事件，但事件必须有授权的规则/决策来源；不能因为“模型写了世界更新”就成为事实。输出先处于候选/规划状态，只有原生接纳链允许的实际事件或背景事件才能进入正史。

每轮限制激活角色数、候选数、展开深度、前瞻范围与 token；预算不足先减非必要候选与远端细节，不能移除必须的认知/因果约束。无法在合法边界内完成时返回等待/阻塞，不以低质量结果补齐进度。

### 10.3 拟议推演契约

逻辑结构为 `SimulationRequest` → `ActorDecision[]` → `WorldCandidateSet` → `DirectorAssessment` → 原生 Plan candidate。它们使用现有 AssetVersion 和 RuntimeJob/ExternalEffect lineage，不引入新的业务事实写者。

请求至少绑定 project/book、accepted Reality revision、active design/plan 版本、授权策略、世界/认知快照、候选范围、随机/采样配置、路由与预算政策。每个分支有独立 branch ID 和依赖 hash；选中分支只代表批准的未来计划，不是已发生事实。

## 11. Temporal Canon 与 Narrative Graph

### 11.1 四种时间不能混用

- 故事时间：事件在虚构世界何时发生；可能含不精确区间与部分顺序。
- 叙述位置：读者在第几章/场景获知；倒叙与插叙不等于事件刚发生。
- 人物认知时间：哪个人物何时观察、获知、误解或遗忘。
- 系统版本：事实在哪个接纳 revision/版本体系内被记录、纠正或取代。

第 N 章 as-of 查询至少应明确是“写到第 N 章时系统已接纳的信息”“该章场景时刻的世界状态”还是“该 POV 当时可知的内容”。三种查询不共用一个含糊的 `chapter <= N` 过滤。

### 11.2 先做派生视图

先核查 Canon/Narrative State 现有历史、事件、source locator 和 revision 是否足以构造时间查询；能派生则不复制存储。只有真实查询/索引需求无法满足时才设计增量迁移。

拟议 `TemporalFactView` 以原有 accepted event/claim 为来源，显示 subject/predicate/value、事实性质、故事有效区间、披露位置、认知主体、recorded revision、supersedes、证据引用。它不是新的事实审批表。

同一属性是否单值、区间是否可重叠、未知时间如何处理，由 predicate schema 定义；不能对所有关系一律设置“不允许重叠”。原生 genesis 是单独设计来源，不构造虚假的第 0 章接纳。

### 11.3 图是可重建索引

图视图覆盖人物、地点、事件、物品、势力、承诺、线索、关系与轨迹。边区分 explicit accepted、计划、人物 belief、语义 inferred；后两者不能冒充真实因果。

读取携带 Book/edition/revision、权限、POV 和 projection watermark。图落后时返回可见的 stale 状态；用于必要约束判断时须回查原生权威或阻塞，不能把“检索不到”当事实不存在。

从原生 acceptance/outbox 构建幂等投影。事务内保证接纳所需的原生状态与记录完整；非关键图检索可异步构建并可重放。投影键可由 book、源 accepted event、projection schema 版本组成，删除并重建不得改变 Canon。

初期优先现有 PostgreSQL 关系/事件表与有限路径查询；只有实测需要时再评估图引擎。禁止为展示一张关系图先引入新的生产权威和基础设施。

## 12. 分层规划、预演与未来分支

沿用 Book/Arc/Volume/ChapterGroup/Chapter/Scene 的 typed planning。它们不是必须一一嵌套的固定六级模板：Volume 是作品结构、Arc 是可跨章节的叙事轨迹、ChapterGroup 是执行协调范围，不能互相代替完成标准。

长期只冻结必要方向：主题问题、读者承诺、关键代价、结局约束、主要轨迹。中期预演给出条件性路线和风险。近程细纲明确人物决策、因果链、场景目标、知识边界、兑现和章末变化。

设窗口 H、候选分支 B，均为策略值。普通过渡可以 H=1、B=1；高风险转折在预算与评价资格允许时增加范围。外部项目的 1–3 章和 2–5 分支仅作为实验起点，不写成常量。

分支采用后保存不可变计划输入包；Draft 仍逐章执行。每次接纳后检查实际结果与分支依赖：受影响的未来分支标记失效/需重规划；不受影响的分支只有在依赖 hash、版本兼容与当前授权检查通过时才可复用。

封存表示输入与计划版本确定，不代表该窗口已完成。不能用一次窗口批准替代每章正文审稿、事实支持与原子接纳。反事实分支、被拒候选和未采用推演不得进入普通事实检索。

## 13. 正文生产与场景技法编译

### 13.1 保持全章连贯

优先复用当前 `scene-realization-composition.v2` 所表达的方向：在一次全章写作任务中提供差异化的场景 craft tasks，而不是固定创建对白、动作、描写、感情、笑点等常驻 Agent，再把段落机械拼接。

Writer 的输入分为不可丢约束、当前章必要事实、场景使命、人物声线、采用技法、可选参考。固定 Prompt/Skill 版本与实际传给 Provider 的内容 hash；预算压缩只能删除允许裁剪项，不能截断出半条因果或移除必要知识边界。

Writer 可以在合法范围内提出新的细节与实现方式，但它们仍是正文候选和事实提取对象。计划期已经要求的具体动作/结果是否兑现，以最终正文为准。

### 13.2 四类首批原创迁移训练题

以下是测试设计示例，不是摘录或正文成稿。

| 类型 | 原创任务 | 要检验的机制 | 不应奖励的投机行为 |
|---|---|---|---|
| 战斗 | 受伤护送者须在封桥前带证人过河，对手目标是拖延而非杀人 | 目标不对称、空间/资源约束、预期反转、获胜代价 | 增加技能名/攻击次数、临时开挂、只写金光爆炸 |
| 感情 | 两人各自隐瞒一件并非背叛的事，在危险撤离中必须协作 | 潜台词、行动证据、认知错位、关系微变化 | 突然告白、纯外貌描写、靠误会无限拖延 |
| 人物/反套路 | 主角拒绝看似稳赚的门派奖励，但选择须符合其既有信念与代价 | 意外但一致、可回溯动机、后果承担 | 只为反转而降智、作者强行解释“他早算到了” |
| 幽默/追读 | 一个小人物靠专业知识暂时改变强者的判断，同时留下可兑现问题 | 地位反转、语言节制、人物关系与期待 | 强塞网络梗、羞辱无关人物、章末机械悬念 |

每题采用“无技法输入/有技法输入”对照，冻结同一世界、人物与创作意图；允许多随机种子，但各组使用同样的采样/预算政策。训练题与正式评价样本隔离。

## 14. 质量诊断与定向优化

### 14.1 检查维度，不是固定六次调用

| 层 | 检查内容 | 证据性质 | 触发方式 |
|---|---|---|---|
| 结构/确定性 | schema、hash、版本、权限、明确字数合同、已形式化事实约束 | 可自动复核 | 每个相关动作 |
| 叙事正确性 | 因果、OOC、POV、信息泄漏、资源/时间合理性 | 语义诊断，需位置证据与不确定性 | 逐章，风险决定复核强度 |
| 场景 Craft | 战术可读性、潜台词、声线、描写负担、转场 | 目标相关审稿 | 按场景类型加载 |
| 商业阅读体验 | 承诺/兑现、期待、节奏、情绪、重复模式 | 类型和读者相关评价 | 按作品策略，不强迫每章爽点 |
| Reader Proxy | 不同阅读偏好下的理解、兴趣与困惑 | 模拟反馈 | 里程碑/争议稿，不当真实读者 |
| 长程/全书 | 轨迹、人物关系、结构单调、伏笔、主题与结局 | 跨章证据 + 编辑评价 | 弧/卷/全书里程碑 |

可在一次结构化审稿中覆盖多个维度；高风险、评委分歧或证据不足时才升级独立模型/人工。对相同候选重复询问同一模型多个角色不能自动视为独立证据。

### 14.2 ReviewIssue 契约

每个问题绑定候选 AssetVersion、正文 hash、Unicode code-point span/引用、问题类型、严重度、事实还是审美判断、依据、修复目标、保护项、验收条件、评阅来源和不确定性。原候选的定位不能直接复用为新候选已经验证的证据。

硬性阻塞限定为已批准的可执行合同、安全/来源边界、已确认事实冲突和必须解决的语义问题。作者风格偏好或模型审美不自动升级为客观 blocker。

修订链：原稿 → 定位诊断 → 有界修订任务 → 新候选 → 问题解决/保护项复核 → 比较 → 保留/拒绝。必要时保留原稿并停止，而不是为了达到分数持续重写。

### 14.3 停止与平台期

停止原因区分：已满足要求、无可证明改善、保护项退化、模型分歧、预算不足、授权等待、不可恢复输入错误。平台期只表示继续自动优化的收益不足；仍有 blocker 时不能以平台期为由接纳。

反套话检查用于发现值得阅读的段落，不是 AI 身份鉴定器。允许对白、人物口头禅、文学重复和题材特有修辞的上下文例外。避免以机械缩短句子或删词破坏声线。

### 14.4 全书审稿不必把全文反复塞入模型

优先基于 accepted manuscript 索引、结构摘要、人物/伏笔时间线和定位检索构造审稿任务；重要判断回到实际正文验证。摘要不能代替引用证据，覆盖不到的章节明确标出。具备合法上下文容量与预算时可以全文审阅，但不把全文长上下文当唯一实现。

## 15. Cost-Aware Quality-Constrained Provider Router 对接

### 15.1 目标函数与先后顺序

在授权、数据边界、任务能力、schema/context 容量与最低质量条件均满足的候选路由中，最小化预计的合格产出成本。不是简单选择单价最低模型，也不是按仓库推荐永久绑定某模型。

决策因素覆盖：`task_type × quality_risk × model_benchmark × remaining_budget × cache × retry_history`，并加入正文/转折的重要性、上下文约束、可用性与原生资格状态。

对话中的 Flash、V4 Pro high/max、Codex escalation 是意图层级，不在本文断言它们对应当时可用的具体 API 名称/参数。运行时使用版本化模型目录、能力测试和实际凭据配置确认。

### 15.2 路由生命周期

```text
任务与冻结输入
 -> 检查 Book/阶段授权、数据权限和 Provider 资格
 -> 过滤不支持 schema/context/质量下限的路由
 -> 检查同等语义输入下的可复用缓存
 -> 估计一次成功及可能修复的总成本
 -> 原生预算预留
 -> 固定 RouteSnapshot/决策依据
 -> ExternalEffect dispatch
 -> reconcile receipt / usage / cost
 -> 失败分类或输出接纳
```

`RoutingDecision` 拟记录：任务/输入/策略版本、候选过滤原因、benchmark 版本、质量门槛与未知项、预计用量区间、cache decision、retry history、实际选定 provider/model/reasoning、credential reference、预算 reservation 与 fallback policy。敏感凭据不进入资产、Prompt、日志或 Git。

### 15.3 失败和升级

技术失败与质量失败分开。schema 错误、限流、上下文不支持、输出被截断、语义质量不足分别有策略。不得无限重试一个已经证明不适配的模型。

已发送但结果未知时先通过原生 ExternalEffect reconciliation 处理，不能换模型再发同一个 effect。恢复同一 effect 保留原 RouteSnapshot；升级属于有新授权与预算归属的后继 effect，并保留前后关联。账号、计费方式和数据接收方变化不能静默发生。

价格未知不等于免费；订阅额度使用有限调用/token 配额和观察到的使用回执。远端推理 token 的预留只能是可执行政策下的估计或上界，不能声称本地 CLI 能精确限制所有远端隐含消耗。

### 15.4 缓存与评价隔离

缓存 key 至少覆盖 task/schema、输入资产 hash、Book knowledge policy、POV/角色范围、Prompt/Skill/model/reasoning 版本和适用政策。不能让对照实验、不同书或不同权限范围通过缓存串入知识。

结果缓存与 Provider 前缀缓存分别统计。模型版本变化、政策收紧、来源撤权或正文/计划依赖变化必须重新检查可用性；不能只因 prompt 字符串相同就重用敏感结果。

本提案不批准新的模型付费或订阅额度消费。没有满足质量要求的合格路由时返回等待/升级请求，不自动降级到更便宜但不合格的模型。

## 16. 依赖感知的修改传播

### 16.1 用原生 Plan Change 扩展

沿用 `semantic_plan_diff`、风险分类和 `require_approvable_scope`。依赖区分：结构包含、计划约束、因果、时间、人物认知、信息披露、伏笔承诺、正文实现与来源权限。图上相关不必然意味着需要重写。

影响分析先用精确引用/依赖做确定性闭包，再对可能受影响但未显式建边的语义关系给出建议和置信度。报告必须分为必改、待审、不受影响和无法判断，不能承诺自动发现全部文学连锁后果。

### 16.2 变更流程

```text
AuthorChangeRequest + expected versions
 -> SemanticDiff + ImpactAssessment
 -> 权限/风险/已执行范围检查
 -> 作者或授权策略选择受影响部分
 -> PlanChange approval/activation
 -> 未执行计划生成新版本
 -> 受影响候选/Context/投影标记 stale
 -> 选择性重规划/修订
 -> 原生审稿和接纳
```

已接纳章节保留不可变历史。对历史正文/事实的更正须单独 Retcon/edition 方案与批准；当前普通 Plan Change 禁止把它悄悄当作未来计划修改。本方案没有证明完整 Retcon 产品已经存在，也不在实现前指定新表/新 edition 权威。

### 16.3 例子

作者撤回“第 38 章女主获知男主身份”：系统定位该披露事件、女主知识变化、其后依赖该知识的行动、关系转折及相关承诺。第 39 章纯环境描述可能不受影响，第 41 章基于身份作出的救援决定需重审。实际范围来自依赖和正文证据，不是固定将第 38 章以后全部标为重写。

并发作者编辑需 expected version/乐观并发检查；同一变更重复提交不得生成重复 effect 或重复计划激活。批准后输入漂移要重新评估，不沿用过期 impact report。

## 17. 作者工作台与 API 契约

### 17.1 以作者任务组织，而不是把所有表搬到菜单

建议入口为：素材与技法、创作设计、规划、写作与改稿、书中事实、生产与成本。人物/世界/时间线/关系图是相关任务的视图，不必各自成为独立应用。

核心旅程：选择题材和约束 → 审看人物/世界 → 比较章节方向 → 阅读正文与诊断 → 对照修改 → 接纳 → 查看下一章实际使用了什么。运行异常时显示可恢复状态与操作，不把后台日志当全部产品体验。

Manuscript 为主画面；右侧按需查看本章使命、必要事实、人物已知、采用技法、问题和费用。作者既能看“系统记住了什么”，也能看“为什么这条记忆进入当前任务”。

### 17.2 自主程度

借鉴提案式编辑，但复用现有作者控制/授权政策：只读分析、建议修改、辅助起草、有界自动生产。具体枚举以届时原生 ControlPolicy 为准，不再创建第二套冲突的模式枚举。

明确 Accept/Reject、暂停/继续/取消、计划变更和接纳是不同动作。用户批准某个文字建议不自动批准 Canon 更改、账号切换或新预算。人工编辑后的稿件仍走必要的事实和权限验证。

### 17.3 拟议逻辑操作面

以下是产品动作与契约要求，不是已经存在的新 HTTP 路由；WP01 应优先绑定现有 API/命令，只有真实缺口才新增薄接口。

| 逻辑动作 | 必需输入 | 输出/边界 |
|---|---|---|
| 查询素材/技法 | project、Book policy、过滤、版本 | 权限过滤后的证据与适用性 |
| 请求技法分析 | SourceUnit 范围、profile、授权预算 | 原生分析任务/版本，非同步长请求 |
| 请求推演 | Reality/plan/design 版本、范围、策略 | 隔离候选和比较报告 |
| 采用方向 | 候选 ID、expected versions、批准者 | 计划提案或原生激活结果，不改 Canon |
| 查询时间/图 | Book、系统 revision、故事时刻/叙述位置、POV | 来源与 watermark，明确 stale |
| 请求局部改稿 | 候选 hash、选区、目标、保护项 | Revision candidate 与 Diff |
| 评估计划变更 | before/after、执行范围、版本 | ImpactAssessment 与风险 |
| 批准/拒绝变更 | impact/plan 版本、授权范围 | 原生 Authority 决策 |
| 接纳章节 | 精确候选、Quality/Canon 证据 | Book acceptance 的唯一结果 |
| 查看费用/恢复 | Operation/effect/Book 范围 | 预算、回执、未知项、合法恢复动作 |

所有写动作统一使用原生 command envelope：身份/权限、project/Book、idempotency key、expected revisions、资产引用、策略/授权引用与 correlation ID。幂等键相同而语义输入不同应拒绝，不能覆盖旧请求。

### 17.4 前端与隐私

前端不保存生产 Provider secret，不照搬浏览器直连模型，不直接操作 PostgreSQL、文件式 Canon 或外部 CLI。下载/导出只使用作者有权访问的明确版本；接纳稿、候选稿和分析素材的导出范围分开。

UI 需测试手机/桌面基本阅读与 Diff、空状态、加载失败、陈旧版本、并发编辑、权限不足、预算不足和恢复中断。后端测试通过不代替这些验证。

## 18. 并发、恢复与安全

- 同 Book 的 accepted cursor 继续由原生 acceptance 串行推进。素材分析、独立分支与只读审稿可以有界并行；并行不共享可变写作工作区。
- 使用 Command Kernel 的 Operation/Attempt/Lease/Fence/ExternalEffect，不为各 Agent 再建租约或调用账本。
- 外部 I/O 在业务事务外执行；intent 先持久化，receipt 后对账。未知提交结果先查证，不重放不可判定副作用。
- 技术恢复和语义重新生成分开：前者恢复同一冻结任务；后者创建有 lineage 的新候选/新决策，不能假称同一次调用可确定复现。
- 原文、README、Skill 和模型结果均按不可信内容处理。检索内容不能改变工具权限、系统指令、模型路由、文件路径或预算。
- 外部仓库只读核查默认不执行安装脚本、Hook 或任意 shell。确需实验时使用隔离 workspace、工具/网络 allowlist、无生产凭据、可销毁临时存储。
- Coding Agent 型任务仅能读授权资产和写候选输出。禁止继承其工程开发场景下的无限制文件/SQL/网络权限；不照搬 permission-skipping 运行参数。
- 阅读材料的引用跨度、日志、导出和错误信息不得泄露密钥或其他书的内容；撤权后检索和缓存按政策失效。

## 19. 持久化、版本迁移和回退

### 19.1 最小新增原则

本文所有 DTO 是逻辑契约建议，不是新增表清单。优先使用现有 Content/AssetVersion、KnowledgeCard、Plan、Review、Canon/State、RuntimeJob、ExternalEffect 与 projection。只有需要事务约束、查询性能或生命周期归属时才新增表，并证明不能由现有 owner 表达。

新增 migration 前明确：字段/唯一键、Book/Project 外键、源版本绑定、索引查询、更新/删除政策、回填范围、并发/恢复和 fresh/upgrade 验证。不预占迁移编号，不修改已发布迁移文件。

### 19.2 兼容和上线

版本化契约先读旧/写新，再 shadow 运行和受限 Book 启用。新策略冻结到新任务；旧任务继续使用其原 schema/Prompt/route，不在恢复时静默切换。若旧资产不足以证明新门槛，则明确要求重新验证，不能补造历史证据。

模拟分支、Context 与投影失效使用依赖版本，不以时间戳猜测。非关键图索引可以丢弃重建；accepted 事实、文本、授权和费用终态不可删除重写来“恢复干净”。

回退关闭新能力准入并继续读历史新版本；停止新的效果调用，保留已发送未知 effect 的对账义务。回退不等于撤销已对外消费的费用或已经发布的内容。

### 19.3 切换顺序

只读观察 → shadow 计划/审稿 → 少量新 Book 显式启用 → 同输入对照 → 定向放量。任何关键退化先停在当前接纳 frontier；不得为追进度自动回退到未经作者授权的旧模型或宽松 gate。

## 20. 实施工作包与依赖

本次是设计提案提交，不是以下工作包的执行授权。工作包可以连续推进，但每包必须输出能被下一段生产链消费的能力，不以新增 DTO/表/报告数量验收。

### WP01：代码级差分与吸收决策

覆盖 17 个仓库，固定各自 commit/分支和许可证；把 README 线索追到入口、状态、Provider、失败恢复和样例/测试。对照最新 Novel Forge，记录 KEEP/EXTEND/ADAPT/HOLD/REJECT；对重复项明确关闭，不再开发。结果更新本提案对应章节；不另建永久“能力登记平台”。

验收：每个候选至少有明确处置；每个拟实施机制有原生消费者、证据边界、权利状态与验收用例；无法访问或许可不明的个别仓库标记 HOLD，不阻塞无依赖的其他机制。

### WP02：技法到正文的纵向闭环（首个创作增量）

优先完成战斗、关系/潜台词、人物选择、幽默/期待四类中的代表性样例。从少量受控素材提炼机制，接入原生适用性、采用、Memo、Draft、Review 与 trace。准备隔离对照，不做全库穷举。

验收：至少一个完整“来源证据→抽象技法→采用位置→原创候选正文→定位验证→接纳稿绑定”样例；未解决缺陷不得被更高分抹去。真实调用只有在已有资格与明确预算授权下执行。先通过 3 章级创作切片验证方向，不先等待所有大系统建完。

### WP03：角色推演、窗口和未来分支

扩展现有 World Preparation/role projection，覆盖行动依据、知识隔离、资源后果、导演选择、有限窗口与 stale 分支。优先补实际缺口，不复制外部运行时。

验收：角色不能用未获知秘密行动；失败/有代价选择能进入合法候选；分支选择不写 Canon；接纳漂移能使受影响未来计划失效；同 Book 原生顺序接纳保持。

### WP04：时间查询和图投影

先明确四种时间和原生历史能力，再补时间化 read model、关系/线索查询、watermark、重建与权限。必要时设计最小增量 migration。

验收：倒叙、知识延迟、误解、纠正、复合关系与撤权查询有明确答案；重建图不改变权威事实；落后投影不能用于无提示的关键约束判定。

### WP05：依赖感知改稿与计划级联

基于 Plan Change 增加精确影响报告、受影响资产失效、局部重新规划和作者 Diff。区分未来修改与已接纳历史的 Retcon，后者仅在专门设计获准后开放。

验收：第 38 章披露撤回场景能准确划分必改/待审/保留；并发作者修改与重试安全；不发生全书无依据重写或历史终态覆盖。

### WP06：质量优化与跨章审稿

扩展场景相关诊断、分歧升级、质量收益比较、平台期停止和弧/全书审稿。复用候选保留及 Book acceptance，不建新的最终 Judge Authority。

验收：定位问题有修复与保护项证据；退化新稿被拒；平台期带 blocker 不能接纳；不同评阅维度的证据类型不混淆。

### WP07：市场方向与反馈学习

按目标频道建立受控榜单快照与趋势解释；连接作者反馈、Reader Proxy 与真实读者证据。学习结果形成知识/策略/计划修改提案，而不是运行时自改 Prompt 或自增权限。

验收：缺失数据不产生假跌幅，频道不串用，市场建议有来源和时效；反馈能产生有证据的后续建议，不能直接改既有事实。

### WP08：作者工作台

复用现有 Web/API，交付书稿主场、技法证据、人物知识、计划分支、诊断 Diff、时间查询、成本和恢复操作。按任务组织功能，避免为每种领域对象建立重复菜单。

验收：作者完成新书准备、阅读、局部改稿、影响确认、接纳、失败恢复的真实页面走查；权限和版本冲突不依赖前端自觉。

### WP09：真实创作与长程观察

将前述能力组合到明确授权的真实项目，先 12 章受控比较，再根据质量/成本/风险决定是否扩展到 30、100 章及更长观察。每一级独立预算、停机条件和证据结论；章数本身不是通过标准。

验收：技术、真实 Provider、语义验证、人工编辑、长程稳定性各有独立结论；输出接纳正文而不只运行日志；失败保留并分析，不能换目录抹去失败或重置预算。

### 依赖与顺序

WP01 为差分入口；WP02 优先形成创作价值。WP03 与 WP04 根据实际缺口协作；WP05 依赖清晰的版本/依赖语义；WP06 可从 WP02 的诊断证据迭代；WP07 非正文首个切片前置；WP08 随已有动作渐进开放；WP09 的小样验证贯穿实施，扩容放在相关能力合格之后。

Provider Router 是横切依赖：其实现/资格尚不足时不并行再造，先复用当前合法冻结路由完成小样；自动成本路由上线必须另有验证。不得用“等全融合完成”无限推迟真实正文检查。

## 21. 验证矩阵

### 21.1 必要工程用例

| 场景 | 必须观察到的结果 |
|---|---|
| 同内容更换 analysis profile | 导入可复用，相关分析按新身份重算 |
| 不具备使用权的原文/外部表达 | 不进入未经许可的 Draft Context |
| 外部资料夹带工具指令 | 被当资料而非系统权限/运行配置 |
| Card 前提未知或明确冲突 | 明确适配/拒绝，不以默认值通过 |
| 计划拒绝某 Card | 下游 Draft 不通过重新检索把它加回 |
| Card 只出现在 Context | 不宣称已经在正文实现 |
| 角色不知道秘密 | 决策/POV 输入与输出均检查泄漏 |
| 候选世界分支未采用 | 不进入 accepted Canon/普通事实检索 |
| 分支 seal 后父状态变化 | 校验依赖，过期分支不能直接复用 |
| 多任务并行处理同书 | accepted cursor 和必要投影保持唯一顺序 |
| Provider 已发送后超时 | UNKNOWN/reconcile，不盲目重发/切模型 |
| 预算不足或成本未知 | 明确停机/有限权益控制，不写免费或超额调用 |
| 新候选评分高但保护项退化 | 保留旧稿，问题不因分数消失 |
| 新审稿遗漏原 blocker | blocker 仍待明确处置 |
| 修改原文后复用旧审稿 | hash/版本绑定拒绝陈旧证据 |
| 作者并发改计划 | expected version 冲突可见，不覆盖他人修改 |
| 修改已执行计划 | 普通流程拒绝，转单独 Retcon 提案 |
| 图投影落后/损坏 | 显示 stale、权威回查或阻塞；可重建 |
| 倒叙与认知延迟 | 三种 as-of 读取不混同 |
| 榜单缺失/指标口径变化 | 不伪造排名/读者变化结论 |
| 对照组采用不同知识策略 | 缓存、摘要和上游计划都不串组 |
| 凭据与授权变更 | 日志/导出不泄露密钥，路由变更可追踪 |
| schema/migration 升级 | fresh/upgrade/replay 结果满足原生兼容合同 |
| 暂停/取消/恢复 | 不丢已生成候选，不重复外部副作用或重置预算 |

这不是要求为每条都新增测试文件；先复用当前相关测试，只补真实变更未覆盖的契约、数据库边界和故障场景。

### 21.2 创作效果实验

先冻结评价问题和 rubric，再生成结果。推荐比较 A=现有基线，B=基线+目标技法，C=基线+技法+目标推演/审稿增量；预算受限时先只做 A/B。保持创作简报、知识访问策略、模型/路由政策和采样条件可比；需要测试路由器时将其单独作为变量，不同时改所有因素。

按作品或来源族划分训练/开发/评价样本，不能把同书近似场景一部分当教材、另一部分当独立验证。生成任务不携带被评作品原文；评委盲化候选来源并随机顺序。模型 Judge 结果与真人评阅分开存储，对分歧与低置信样本进行人工复核。

先看硬约束不退化，再看战术清晰、关系推进、人物选择、幽默自然、期待与兑现、声线和整体可读性的成对偏好。统计单位应说明是作品/章节/场景，不能把同书高度相关的段落当大量独立样本。

小样只能提供方向性证据。质量提升/非劣性边界、样本量、置信区间与可接受失败率须在评价前声明；不足时报告不确定，不承诺仅凭 12 章即可证明稳定生产。

### 21.3 验证层级与治理

`CODE_EXISTS → WIRED → EXECUTABLE → QUALIFIED → PRODUCTION_PROVEN` 沿用仓库词汇，且必须注明证据类型/范围。脚本与 mock 只证明其支持的控制流，真实模型回执证明调用，不自动证明文学质量。

开发时跑最小针对性检查；实现变更完成后按当前 `docs/runtime-operations.md` 和 PR governance 执行适用矩阵，不通过 skip/xfail、弱化断言或更新阈值掩盖失败。用户提出的“减少非必要测试”不意味着删除现行必需 gate。

本提案仅新增 proposal Markdown，未改业务实现、schema、Prompt、Skill、Provider、测试或迁移。预期走 same-implementation 文档/提案治理，不应为文档提交启动真实模型或长篇消费；是否 `NOT_REQUIRED / SAME_IMPLEMENTATION` 必须由实际 gate 决定，而非本文自行授予。

## 22. 观测与指标

复用现有操作日志、effect 回执、workspace 和 read query。按 Book、章节、accepted revision、来源/技法版本、模型与策略版本切片，不新增与原账本冲突的监控真值。

| 指标 | 计算/解释边界 |
|---|---|
| 采用覆盖 | 所选 Card 中被明确 ADOPT/ADAPT/REJECT 的比例，不等于运用成功率 |
| 实现验证 | 对已采用机制，在精确正文上完成验证的比例及未决项 |
| 约束违规 | 按已定义约束类型统计，说明覆盖与人工确认，不以未检出等于无问题 |
| 修订收益 | 已定位诊断解决、保护项保留、新问题与成对偏好分别记录 |
| 单位合格正文成本 | 本范围总现金成本 ÷ 去重后的接纳汉字数 × 10,000；订阅未知现金成本单列 |
| token/合格输出 | 包含失败、修复、审稿与升级，不只统计最后成功调用 |
| 伏笔/承诺状态 | 以实际可验证登记、推进、兑现/放弃为准，不要求数量越多越好 |
| 人物/关系连续性 | 认知、动机、资源、关系变更中的已确认问题与未决问题 |
| 趋势可靠性 | 快照覆盖、来源变化、缺失比例、cohort 范围与预测/解释时点 |
| 读者反应 | 作者、模型模拟、真人样本、平台行为分别展示；无数据时不输出留存率 |
| 恢复正确性 | 未知 effect、重复发送、重复接纳、stale 读取和清理结果 |

平台真实留存只有具备合法、可解释的数据口径时才评估；Rank Tracker 的榜单变化不替代留存。

## 23. 开放决策及推荐默认值

| 决策 | 推荐默认 | 实施前需确认 |
|---|---|---|
| 外部组件复制还是机制独立实现 | 以原生机制适配为主 | 固定 SHA 的文件许可、部署/分发条件与具体差异 |
| Temporal Fact 是否需新表 | 先基于 accepted history 派生 | 查询范围、故事时间语义、索引和性能证据 |
| 图引擎 | 先用 PostgreSQL 派生关系和有限查询 | 真正的数据规模、路径查询和重建成本 |
| 角色 Agent 粒度 | 按事件/场景激活，不常驻全世界 | 目标场景收益与实际用量 |
| 规划窗口与候选数量 | 从最小可用范围开始，策略化 | 长程漂移、质量收益和预算实验 |
| Judge 独立性 | 多维可合并，关键争议独立复核 | 模型偏差、人工样本与阈值校准 |
| 模型自动路由 | 复用共享路由器，不在 Prompt 写死 | 当前模型目录、资格、质量 benchmark、明确额度 |
| 历史改稿/Retcon | 普通未来 Plan Change 不开放历史改写 | edition/影响传播/发布内容更正的独立设计 |
| 趋势数据覆盖 | 先目标频道，来源缺失时不泛化 | 玄幻/武侠来源权利、稳定性与指标语义 |
| 验收规模 | 小样方向验证后逐步放量 | 人工评价、预算、统计不确定性与停止条件 |

以上待决事项不是停工借口：不依赖该决策的原生扩展可以推进，但不得用默认猜测跨越授权、事实或成本边界。

## 24. 完成定义与提案退出

每项吸收能力的完成记录应回答：解决哪个创作问题；来源证据是什么；为何原生能力不足；改了哪个消费者；实际正文/作者操作有什么变化；如何失败与恢复；花了多少资源；哪些结论仍不确定。

只有 README/新类/新表/新 Prompt/单元测试，或只有“资格 PASS”但无正文消费者，均不算完成融合。反过来，若原生能力已经更合适，记录 `KEEP_NATIVE` 和证据即为有效处置，不为证明做了工作而重写。

最终应能回答：一段战斗为什么好读、采用了哪项抽象技法、人物凭什么如此行动、后果如何进入正史、修改后影响哪些章节、作者为什么接纳、模型与成本为何这样选择。答案来自版本化产物和阅读证据，不来自 Agent 的口头总结。

每个工作包落地后更新本提案的 implemented references、未决项、审阅基线和范围；当前行为只投影到 canonical 文档与 Reality。所有决策完成/被替代后，按现行生命周期规则删除终态提案，由 Git 保存历史，不长期保留一份与代码竞争的“完成版蓝图”。

## 25. 核查来源与复核入口

### 原生固定基线

以下链接均固定到本次审阅 commit；它们支持路径/契约核查，不代表本次执行了所列测试。

- [仓库 Agent 约束](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/AGENTS.md)
- [文档与提案生命周期规则](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/docs/development.md)
- [当前系统与已有 InkOS/Bishu 机制处置](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/docs/current-system.md)
- [Reality projection](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/architecture/reality-evidence.json)
- [World Preparation](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/story_planning_runtime/world_preparation.py)
- [Knowledge Translation](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/story_planning_runtime/knowledge_translation.py)
- [Applicability](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/mkaos_authority/applicability.py)
- [Accepted Reality revision](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/narrative_state/reality.py)
- [Plan Change 语义和历史边界](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/plan_change_authority/domain.py)
- [不可变候选比较](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/modules/chapter_authority/candidate_selection.py)
- [提案生命周期检查实现](https://github.com/yuan2go/novel-forge/blob/3ad3a24c05a791899759cc947f83e5be65cdfaa1/src/novel_forge/tools/proposal_lifecycle.py)

### 外部证据范围

第 4 节链接是候选来源入口，不是被冻结的实施依赖。本轮及前序讨论读取的 README、公开页面和仓库元数据只支撑候选研究方向；WP01 须重新固定 commit、按功能追代码与许可。特别是开发分支、实验性功能、外部示例产物和自评结论不能自动升级证据级别。

本次新增核查中可辨认的 README blob identity 包括：Autofiction `a6ab86e2f9b84349da9b6da325a17cfb22ba2544`、AI-Novel `43c97bcfa2d94611c637a011949ddde7a32a8db3`、Oh Story `b38d7bf5cab4215ddbcc71046229d2dcbf8617c1`、Fanqie Skill `d798acd232e43489cf4d5fe4eb514b3e3c678dba`、FanqieRankTracker `71c781309a0f4ea2ef7998943699faf35e5a469b`、NovelWriter `d046f974f5d15191ed9894e47957adf98f7f7ed1`。这些是文件 blob SHA，不是 repository commit SHA，不能用于声明整库代码已被冻结或审计完成。
