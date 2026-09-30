# Novel Forge 开发规格：生成合同收敛与创作执行改进

> **PROPOSAL**
>
> **NOT_RUNTIME_AUTHORITY**
>
> 主工作包：`WP-PROMPT-AND-GENERATION-CONTRACT-CONVERGENCE-01`
>
> 需求就绪状态：`READY_FOR_IMPLEMENTATION`，仅适用于本文件 R-001～R-016。
> 仓库提案生命周期：`PARTIALLY_IMPLEMENTED`。本文件不是功能完成报告，也不授予运行、审批、发布或付费调用权限。

| 文档信息 | 内容 |
|---|---|
| 目标仓库 | `yuan2go/novel-forge` |
| 核验日期 | 2026-10-01，UTC+8 |
| 核验分支 | `codex/real-prose-quality-closure-01` |
| 当前生命周期代码基线 | `868f197ec97a957b433859f4c6ef174f4a2b0f55` |
| Git tree | `1606eb4704fbd6b37e6e74087b2466a45cd240db` |
| 当前事实核验 | 源代码、冻结合同、正式装配及定向单测/PostgreSQL 回归；现有持久库仅只读核验，未调用真实 Provider |
| 实现及效果状态 | 规格形成时仅交付需求；后续工程实现已进入正式主链，真实 Provider 与文学收益仍未验证。当前状态以代码、冻结合同和当次验收为准 |
| 规格边界 | 现有小说生成主链的职责、Prompt、输出、Context、方法及下游消费收敛；不是整个 Industrial Autonomous Novel OS 的一次性交付蓝图 |

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-10-01",
  "review_due": "2026-10-30",
  "decision_free_since": "2026-09-30",
  "reality_baseline": {
    "sha": "868f197ec97a957b433859f4c6ef174f4a2b0f55",
    "implementation_tree_sha": "sha256:5a8e42f340292bfe663706f7427fda244f96667368ffd02a911098bc8afa7298"
  },
  "scope": [
    "src/novel_forge/modules/chapter_authority",
    "src/novel_forge/modules/context_builder",
    "src/novel_forge/modules/review",
    "src/novel_forge/modules/revision",
    "src/novel_forge/modules/canon_graph",
    "src/novel_forge/modules/production_execution",
    "src/novel_forge/modules/story_planning_runtime",
    "src/novel_forge/modules/book_followup_authority",
    "config/capability_packs",
    "skills",
    "src/novel_forge/modules/creative",
    "src/novel_forge/modules/mkaos_authority"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/chapter_authority/execution_gateway.py",
      "symbol": "ChapterCapabilityPreflight"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/provider_output_contracts.py",
      "symbol": "chapter_provider_output_schema"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/realization_composition.py",
      "symbol": "derive_targeted_revision_slots"
    },
    {
      "path": "src/novel_forge/modules/book_authority/production.py",
      "symbol": "PostgresBookAuthority.accept_chapter"
    },
    {
      "path": "src/novel_forge/modules/production_execution/backends.py",
      "symbol": "RemoteProviderExecutionBackend._record_provider_result"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/execution_gateway.py",
      "symbol": "_project_prose_skill"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/realization_composition.py",
      "symbol": "_scene_craft_tasks"
    },
    {
      "path": "src/novel_forge/modules/review/cross_model_binding.py",
      "symbol": "freeze_review_requirement"
    },
    {
      "path": "src/novel_forge/modules/provider_callback_authority/service.py",
      "symbol": "ProviderCallbackAuthorityService.consume_pending"
    },
    {
      "path": "src/novel_forge/modules/command_kernel/external_effect_runtime.py",
      "symbol": "reconcile_external_effect"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [],
  "remaining_work": [
    {
      "id": "real-provider-and-editorial-validation",
      "description": "在本轮有效作品、模型、预算、期限和人工审批授权下，完成原生真实正文审读、必要修订、接纳后后续 Context 消费，再以有界盲评前后对照验证实际阅读收益。尚无本轮正文和对照，不将工程检查、历史授权或已部署旧 Pack 当成真实作品与质量证据；长期稳定性仍需独立样本。",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/chapter_authority/candidate_selection.py",
          "symbol": "bind_selected_review"
        }
      ]
    },
    {
      "id": "applicable-engineering-qualification",
      "description": "完整适用验收尚未通过。旧 0103 快照测试在升级前调用了依赖后续迁移的当前 Runtime；十二章夹具的必需 accepted 因果证据超过冻结 world-production-policy.v1 的 16000 字节预算。兼容语义与预算适用性仍需按真实记录闭合，不绕过当前授权、删除必需来源或改写历史迁移。",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/reality_projection.py",
          "symbol": "project_role_context"
        }
      ]
    }
  ]
}
-->

生命周期中的 implementation identity 由仓库现有 implementation_tree_identity 工具对精确提交重算，并由生命周期检查器核对。该值与提案生命周期均不授予生产资格。review_due 是现有提案检查器所需的维护日期，不是开发期限、生产排期或定时任务。

## 1. 审查结论与可读取材料边界

本轮确定的需求已经能够进入开发：目标、必要行为、状态归属、异常处理、兼容边界和验收条件已在 R-001～R-016 中明确。剩余实现选择不需要改变业务语义，可以交给 Codex。没有阻塞这些需求的用户业务决策。

这不表示整个百万字工业化小说系统已经被完整规格化。长期的 Narrative Intelligence、Creative Intelligence、Quality Proof 方向继续保留，但未经确认的新模块、具体实验规模和完整目标架构不自动成为本包工作。

审查材料包括本会话当前可见的完整业务讨论、用户提供的七项工作包，以及同一固定 SHA 下针对性核验的代码。早期工具调用部分被截断，不能声称逐条重读其全部输出；“另一个任务”仅有用户在本会话转述的方向，全文未能取回。没有用未读取的其他会话、用户本地文件、历史 PASS 或未公开运行环境补齐事实。

“Novel Forge 现在还没法生产小说”作为用户报告的使用问题保留；它不等于所有生成代码都不存在。“InkOS 有商业能力”作为用户选择参考对象的背景保留；本规格不据此宣称已验证其收入、可用性或百万字文学质量。

## 2. 需求演变、来源与处置

本表中的来源均为可识别的会话原话或讨论主题，不是平台消息编号。“明确提出”与“允许本次执行开发或付费”是不同事项。

| 来源或讨论主题 | 来源性质 | 本次处置 |
|---|---|---|
| “长期、稳定、规模化生产高质量长篇网络小说的 Industrial Autonomous Novel OS” | 用户明确目标 | 保留为长期方向；本包交付可接入并可验证的主链改进，不宣称完成全部目标 |
| “不考虑工程量、开发成本和重构成本……寻找最终最优实现” | 用户明确约束 | 允许在本包必要范围重构，不因现有类或目录存在而维护错误边界；不等于授权无关平台重建 |
| “要根据程序真正执行了什么” | 用户明确方法要求 | 当前状态必须有入口、调用、数据或提交依据；实现、接线、运行和效果分别报告 |
| “需要从中吸收能力让 Novel Forge 更优秀” | 用户明确改进目标 | 吸收 InkOS 的有效机制而不是移植整套运行时；保持唯一正式生产链 |
| “转向由真实作品驱动的 Narrative Intelligence、Creative Intelligence 与 Quality Proof” | 用户引入并要求安排的方向；外部任务全文不可读 | 本包用真实作品、失败和对照提供后续改进依据；不推定外部任务中还有哪些模块或已批准实验 |
| “执行模型简洁性；Context 快速路径与方法组织” | 用户明确点名需核对融入的能力目标 | 以 R-007、R-009、R-010 的行为契约纳入，不锁定新的 Facade、Composer 服务或 Agent 框架 |
| “不是再建更多 Agent 或 Skill，而是修正现有主链” | 用户提供工作包的明确范围 | 必做范围修正现有能力及绑定，不把新增目录、框架、Agent 或 Skill 数量当成果 |
| 用户工作包的四项 P0：指令分离、输出协议、单份正文、机械工作程序化 | 用户明确提出的工作 | 纳入 R-002～R-006；连同下游和异常边界一起实施 |
| 用户工作包的三项 P1：相关方法、适用策略、真实对照及连续章节 | 用户明确提出的工作 | 纳入 R-007～R-009、R-014～R-015，不降格为只改提示词文件 |
| “小说创作、程序数据装配、质量判断、审计证明和操作员工作，混成了同一次模型任务” | 用户明确问题诊断 | 作为贯穿所有必做项的职责边界；不为分开职责而机械增加模型调用 |
| 两个自治角色、CreativeAction / ExecutionContext / CapabilityResult、新增 Chapter Creative Brief、独立 Creative Runtime、完整 Harvest Program | 助手提出，未获具体实现确认 | 只保留能满足本包行为要求的实现自由度；不强制新类、新公共 API、新持久化对象或新增编排层 |
| 固定三章、样本 2～3 个、3→10→30→100、固定 WP-01A/B/C/D 排期 | 助手建议，未获用户确认 | 不作为验收数量、排期或预算；以实际生产关系和显式运行计划验收 |
| 全面停止 Platform Engineering、先独立建 Harvest 长期分支 | 助手建议，不是用户批准的绝对禁令 | 不采用。只允许与本包真实阻塞或必要兼容直接相关的平台修改 |
| 所有场景正文删除、所有 ID 禁止模型输出、每次模型必须走 Agent Loop、JSON 天然不适合写作 | 早期建议可能导致的过度解读，已在后续分析澄清 | 排除：保留场景语义、语义引用选择及合适传输协议；确定性能力不必自治 |

本包不能把助手最新一次建议当成用户自动确认。以下内容属于工程推导：精确版本绑定、唯一正文真源、协议与领域对象分离、引用歧义失败关闭、旧合同兼容、调用授权隔离以及必要异常回归。这些内容用于实现已提出需求，不增加新的产品功能。

## 3. 本轮目标、范围与非目标

使用者是作者、现有生产操作员，以及调用正式创作能力的现有工作流。完成后，应减少模型的非创作负担和可避免的格式失败，同时让已有审读、事实提取、接纳与导出继续正确工作。

本轮必做范围由三部分组成：

- **P0：职责与数据合同修正。** 完整模型输入隔离、单一传输协议、每候选单份模型生成正文、程序元数据与证据定位，以及由此必需的正式接线、恢复和兼容。
- **P1：创作输入与执行改进。** 任务相关方法、策略适用性、满足安全和覆盖条件时的 Context 快速路径、消除本包暴露的重复装配。错绑 Skill 导致错误任务或伪造来源属于 P0 缺陷，纯方法优化仍按 P1。
- **P1：真实作品与对照交付。** 在有效运行授权下完成有限对照，并证明新合同正文经原生接纳后成为后续章节输入。真实运行未做时，不得把本包报告为真实生产闭合。

不做：全仓重写、增加通用 Agent/Skill/治理/评测平台、整套 InkOS 移植、新资料库、批量语料拆解、多书调度平台、长篇全局智能新模块、自动发布、固定章数资格战役或绕过严格模式的便捷入口。图像、建筑提示词、作文训练题和新的多内容形态不属于本包。

素材/拆解仍走既有来源治理；题材、世界观、人物、大纲和细纲只处理共享提示与合同污染及必要回归；正文、审稿、修订、事实提取、反馈是本包直接消费面。不得把素材原文、拆解结论、创作计划、角色信念、读者猜测与已接纳故事事实混作同一类真相。

## 4. 当前实现与真实集成边界

以下引用均以本文件基线 SHA 为准。代码能定位或调用可达不等于已在本次运行中成功执行。本文不把测试存在或文档陈述提升为实际效果证明。

| 证据 | 已核验位置与符号 | 现状及对实施的影响 |
|---|---|---|
| E-01 | `chapter_authority/provider_output_contracts.py:149–253`，`_draft_schema`、`_revision_schema`、`_review_schema`、`_canon_schema` | Draft/Revision 要求整章 text 和 scene_artifacts[].text；Review/Canon 要求模型返回精确位置。需要改实际 Schema，不只是改说明文字。Revision 已有正文纯度描述，不应把已有保护全部重写 |
| E-02 | `chapter_authority/handlers.py:1281–1450`，`_DraftHandler.execute`、`_ReviewHandler.execute`、`_RevisionHandler.execute` | 正式 Handler 读取 Plan/Intent/Memo/Context，调用 Provider 并标准化输出；存在作者稿件接入分支。不能新建另一条 Writer→Accept 链绕过这些路径 |
| E-03 | `chapter_authority/realization_composition.py`，`compile_realization_contract`、`serialize_realization`、`integrate_realization` | Scene/Slot/Actor/可知事实/Voice 及正文序列化已经有关联合同。去掉双份正文必须保留必要关系，不能直接删掉场景校验 |
| E-04 | `chapter_authority/creative_memo.py`，`qualify_creative_memo`、`creative_memo_schema` | 已有创作目标、视角、声音、人物选择和场景指令；人物选择包含 cost 等强制字段。不是缺少一个名为 Creative Brief 的新对象，而是需要检查现有约束适用性 |
| E-05 | `chapter_authority/execution_gateway.py:3000–3200, 3500–3710, 4160–4295`，`PostgresProductionExecutionPayloadResolver.resolve`、`_stage_semantic_contract`、`_materialize_production_codex_prompt` | 读取冻结 ExternalEffect/Materialization，拼装 system/Skill/knowledge/template/stage/schema，再核对 Provider admission。附加阶段指令也强制 text 等于槽位拼接；不能只修改 root Skill。已有完整 Prompt 与分组件 hash/消耗观察，无需新建审计平台 |
| E-06 | `skills/prose-generation/SKILL.md`；`config/capability_packs/chapter_generation_pack.json` | Skill 含 operator handoff、资产装配、自检和 Markdown 输出要求；Pack 有绑定。最终哪些内容到达哪个 Provider 必须经真实渲染验证，而非根据文件名字推断 |
| E-07 | `config/capability_packs/artifacts/chapter_generation_contract_catalog.json:7–20` | 存在将每个决定性行为的后果或不可逆代价作为 CONSTRAINT 的规则。策略化需覆盖 knowledge、Schema、审稿和校验，不限于措辞 |
| E-08 | `chapter_authority/handlers.py`，`_ContextHandler.execute`；`chapter_authority/provider_views.py` | 已有 Context 的版本/接纳边界匹配及任务输入投影。快路径必须接入这些机制，不能成为“跳过 Authority 的全量拼接” |
| E-09 | `chapter_authority/candidate_selection.py`，`compare_candidates`、`bind_selected_review`；`book_authority/production.py`，`PostgresBookAuthority.accept_chapter`；`storage/book_authority_repositories.py`，`BookAuthorityRepository.commit_chapter_acceptance` | 已有候选比较、审读稿件绑定与 Book 接纳边界；本包保全这些语义，不把输出 Schema 成功视为接纳 |
| E-10 | `chapter_authority/model_effects.py`，`ExternalEffectChapterModelPort.invoke`；`chapter_authority/execution_gateway.py` 的冻结请求与预算检查 | 真实调用身份、预算、ExternalEffect 与恢复不是模型自报。提示、Skill、输出合同变更会影响冻结身份与资格，必须一并处理 |

上述模块短路径均位于 `src/novel_forge/modules/`，storage 路径位于 `src/novel_forge/storage/`。正式入口沿既有 Authority API/Command、Book 协调及 Chapter Worker/Scheduler；`ChapterAuthorityApplication.run` 不得因易于测试而被当成新的生产入口。

为方便核验，关键固定源码入口：

- [输出合同](https://github.com/yuan2go/novel-forge/blob/dbaadc19688d22f8547aea6ae407d2e1c6c3eb0f/src/novel_forge/modules/chapter_authority/provider_output_contracts.py#L149-L253)
- [真实 Draft / Review / Revision 调用](https://github.com/yuan2go/novel-forge/blob/dbaadc19688d22f8547aea6ae407d2e1c6c3eb0f/src/novel_forge/modules/chapter_authority/handlers.py#L1281-L1450)
- [完整 Provider Prompt 拼装与观察](https://github.com/yuan2go/novel-forge/blob/dbaadc19688d22f8547aea6ae407d2e1c6c3eb0f/src/novel_forge/modules/chapter_authority/execution_gateway.py#L4160-L4295)
- [现有 Creative Memo](https://github.com/yuan2go/novel-forge/blob/dbaadc19688d22f8547aea6ae407d2e1c6c3eb0f/src/novel_forge/modules/chapter_authority/creative_memo.py)

InkOS 参考限于此前审读的 `8fc2ae57080b9821257dee3e37cc677e2b6f389a`：`packages/core/src/agents/composer.ts` 的按预算完整使用/选择、`agents/base.ts` 的方法注入、`harness/tools/longform-production.ts` 的清晰能力调用。吸收机制，不复制巨型 Runner、文件系统事实权威、审读不可用仍正常推进或全历史语义扫描。参考不是商业成功或真实文学质量证明。

## 5. 缺口审查与闭合决定

| 分类 | 原缺口或冲突 | 本次处理 |
|---|---|---|
| A：依据已有讨论/代码解决 | “缺一个 Creative Brief”可能重复已有 Memo | 复用并修正 Memo/Intent/任务投影；不要求新增对象 |
| A | 清理 Prompt 后 Schema、Tool 描述、重试消息仍可能要求双份正文 | 审查并修改整条模型输入及输出消费链，见 R-002～R-006 |
| A | 助手曾把固定三章和更大阶梯当成验收 | 移出规范性要求；要求证明接纳→后续消费关系，规模由明确运行输入确定 |
| A | Writer 策略可选，Reviewer 却继续按全局代价/成长弧扣分 | 两端及确定性校验统一适用规则；作者明确硬约束不降级 |
| A | 小型对照被当作文学收益/百万字生产证明 | 工程、真实执行、比较结论和长期质量分开，见 R-014～R-016 |
| A | 需求目录与仓库文档 gate 冲突 | 使用 architecture/proposals，保留生命周期，不增加 docs 下平行现状文档 |
| B：实现自由度 | 整章 text 或有序场景正文为模型真源 | Codex 根据现有场景合同选取，必须只生成一次且确定性得到下游规范正文，不能降低场景/角色信息边界 |
| B | Facade、函数拆分、适用策略表示、局部引用选择形式 | 不锁定类名或框架；必须服从本规格行为、版本和 Authority 边界 |
| B | Context 什么情况下走快路径 | 由既有冻结策略、必要覆盖、权限和完整请求预算决定，不另造固定 token 数；已满足时直接复用并举证 |
| C：需要用户决定才可改变的事项 | 付费额度、真实运行作品/模型/账户、自动审批或发布权限 | 本规格不替用户选择；作为调用前显式运行输入和现有授权检查。没有授权时不能调用，不妨碍无副作用开发，也不能宣称真实验收完成 |
| C：本轮开发阻塞 | 是否还存在影响 R-001～R-016 实现方向的未决业务冲突 | 无。更大架构或实验范围未确认的部分已排除，不用默认值偷渡 |
| D：可选增强 | 新自治 Agent 模型、专用 Composer 平台、更多 Craft 机制、长期多书 Campaign | 后续候选；需要真实问题与独立范围定义，不因尚未确定而阻塞本包 |

## 6. 功能需求

每项需求的“程序处理”均指现有正式能力/工作流及其必要修改；不默认新增持久化实体或新 Authority。验收映射见第 9 节。

### R-001 正式生产链与唯一职责归属（P0）

**来源：**“修正现有主链”“真实生产能力”；必要集成约束。

触发于现有作者/操作员生成、审读、修订或继续生产请求。输入为当前已授权命令、冻结的书籍/计划/接纳状态，而不是测试 fixture 的预填通过结果。

新合同必须由正式装配选用，经既有 Provider Runtime、标准化、AssetVersion、审读、事实提取、接纳和导出消费。模型返回候选与语义判断；程序负责装配；各 Authority 负责决策与提交。不得新建旁路 DB 写入、第二个 accepted cursor 或单独 Writer 服务绕过 Gate。

已有能力满足需求时复用并证明可达，不为显示“新功能”增加包装。必要重构不受保留现有类的限制，但不得改变未获授权的业务语义。

### R-002 最终模型输入的职责隔离（P0）

**来源：**“将模型执行指令与操作员、开发说明分离”；用户的混合职责问题。

每次受影响模型调用，只接收任务所需的作者意图、创作/审读目标、允许上下文、适用方法、必要硬约束和明确输出协议。完整渲染面包括 system、模板、Skill 与引用、Context 内嵌说明、Tool/Schema 描述、阶段附加指令及修复/重试输入。

剥离无关落库、测试、PR 交接、工程完成报告、操作员规程和“自证已批准/已通过”的要求；这些责任在宿主保留。不得通过删权限和来源约束来缩短 Prompt，也不得用关键词黑名单误删小说中的档案、编号或庭审情节。

输出为任务纯化后的真实请求及可追溯版本/摘要。首发与重试采用同一职责边界；模型输出不能伪造系统回执。

### R-003 唯一传输合同与正文纯度（P0）

**来源：**“消除 Draft 的 Markdown、自检与 JSON 竞争”。

每个受影响阶段有一种无歧义返回协议。JSON/工具参数可以承载正文；不再同时要求 JSON 外 Markdown 正文、自检表和完成报告。模型生成的正文载荷仅含读者应读的内容，不含工程说明、Schema 或审计附录。

允许写作方法中的内部自检，不要求 Writer 输出独立验收证明。合法小说内的书信、账册、标题或代码式文本不得仅因形式相似而剥除。协议不合法时保留原始结果并分类修复，不将其直接计为文学失败。

### R-004 每候选单份模型生成正文（P0）

**来源：**“取消完整正文与槽位正文双份输出”；“单份正文可完整进入现有审读、接纳与导出链”。

Draft/Revision 同一候选只产生一份模型负责维护的正文。可采用整章正文加派生定位，或有序场景正文加确定性拼接；不要求模型返回两份应完全相同的内容。目标是模型输出真源唯一，而不是禁止程序保存可重建投影。

保留 Scene/Slot/Actor、视角/可知信息、计划和局部编辑的必要关联。不得用任意切段或第一个匹配伪造场景覆盖。语义场景归属无法确定时进入显式待处理，不把“已拼接”当成融合质量证明。

原稿与修订稿是合法的不同候选。审读、事实提取、候选选择、接纳与导出都绑定所选候选；显示/导出仅能确定性变换，不重写情节。删双份输出不得删除旧候选或版本关系。

### R-005 程序接管已知元数据和确定性装配（P0）

**来源：**“将已知元数据复制……收回程序”。

宿主从冻结输入、命令和真实执行记录填充已知 project/workspace/book/chapter、输入版本/hash、输出身份、字数、Provider/Prompt/Skill/调用/费用回执等字段，不要求模型重复抄写。对属于传输或存储信封而非模型语义返回的字段，调整 Schema 分层及标准化入口。

模型仍可选择涉及哪个角色、哪条义务或哪个来源；程序用有界引用目录或明确选择结果映射真实身份。未知/越界/错版本引用失败关闭，禁止填默认合法 ID。程序不得把推测的故事事实、语义日期或角色认知当作“元数据”自动补真。

### R-006 宿主证据定位与语义支持分离（P0）

**来源：**“精确证据位置计算收回程序”“引用安全和证据精度不降低”。

Review、Re-review、Revision 编辑目标、Canon 及受本包影响的质量证据中，模型承担问题/事实/语义关系判断及证据选择；可由程序推出的精确位置由程序计算。模型可以使用原文引用、上下文或有界来源选择，不必数长篇正文字符。

按精确目标版本定位：唯一匹配才绑定区间；多处匹配需要消歧；无匹配拒绝或局部修复。定义并测试现有 Unicode code-point、换行和区间口径；冻结摘要后不再偷偷标准化文本。历史章引用和修订稿引用不得混用。

字符匹配只证明文字存在，不证明语义蕴含；既有语义支持与事实校验保留。引用/位置错误优先修复证据，不无条件重生成正文。局部替换不得扩大到授权外文本；未解决歧义不能继续以有效证据接纳。

### R-007 任务相关方法与反馈来源隔离（P0 错绑修复，P1 方法优化）

**来源：**“按任务修正 Skill 绑定与内容”“真实反馈分析不再混入模拟读者评价”；“方法组织”。

根据现有 stage、作者意图及必要范围选用方法：规划服务题材/世界/人物/大纲/细纲，Writer 服务正文，Reviewer 服务有据审读，Reviser 服务受限修订。方法不能扩张权限、改变 Canon 身份或产生审批资格。尽量修正已有 Skill/绑定；不以扩大目录为目标。

真实反馈只能由可追溯的实际输入归纳，保留来源、范围、样本和未知项；没有反馈时明确无数据，不能补造评论。模拟读者输出明确标记为模型代理观察，不能写成真实用户调查。两者可以在已有流程并存，但来源、目的和后续权限必须分离。

Writer 原生约束和适用创作方法可以保留；移除的是错误任务和无关机械/操作员要求，而不是所有质量目标。

### R-008 创作策略适用性与审稿一致（P1）

**来源：**“将商业套路、代价、成长弧改成适用策略”。

依据当前章节功能、人物类型、作者方向、已有状态和承诺决定方法是否适用，允许不使用某套路。不得为过 Schema 而强制给每个角色、每个场景补代价、成长、反转或钩子。

检查 Skill、Knowledge rules、Memo/Plan Schema、附加 Prompt、校验器及 Reviewer；不能只改 Writer 措辞，而由 Reviewer 或非空字段重新强制模板。作者明确的硬约束、已经接纳的事实和本章必须履行的承诺不得被当成可选风格降级。

输出保持能说明本章采用/不采用哪些相关指导；复用现有字段或轻量表达，不要求新策略平台。适用性不明时保留未知或沿用现有授权策略，不通过一律设为“不适用”绕过质量。

### R-009 有条件的 Context 快速路径（P1；泄漏/错状态为 P0）

**来源：**用户点名“Context 快速路径”。

在当前任务的有界候选/工作集中，已确定来源资格、书籍/接纳边界、角色可知范围、必要证据覆盖与相关性，且完整 Provider 请求预算可满足时，直接确定性编译，不再增加没有必要的语义筛选/压缩调用。预算包括方法、Schema、指令、输出预留与既有安全余量；不以单独 Context 字符数冒充实际准入。

“放得下”不是相关性或充分性证明。不得以快路径跨过强制检索/支持判断、把全库历史灌入模型、泄露未来/他书/读者专属信息，或省略必需近章证据。

不满足条件时沿现有受控选择/检索/压缩或明确阻塞路径；不得为证明智能而强制增加 LLM selector。关键内容放不下不静默删除。已有路径已零额外调用时复用并举证，不另建快路径平台。

输出仍是正式冻结 Context 与已有追溯记录。重用结果需绑定真实影响输入、计划/接纳状态、策略、方法及预算身份；同一章编号不是有效缓存键。上游变更须重新解析或使依赖失效。

### R-010 创作执行简化而非新增框架（P1）

**来源：**用户点名“执行模型简洁性”；“不是再建更多 Agent 或 Skill”。

让一项创作操作的调用者、输入投影、模型职责、输出标准化、错误分类与下游消费清晰且无重复责任。把本包暴露的已知引用复制、两份正文、重复输出证明移出模型，不让作者手动拼工程信封。

复用现有 Intent/Memo、Handler、Provider、Kernel 和 Authority；可合并或重构重复装配，但不强制 CreativeAction/ExecutionContext/CapabilityResult 新类、公共 API、新自治角色或专用工作流。纯确定性计算无需工具选择 Agent 回合。

验收依据修改前后实际入口调用图与请求/结果样本：不存在第二个模型调用通道、事实写入点或重复生产链；不使用代码行数、Agent 数量、模块数量作为简洁性或质量分数。

### R-011 正式接纳与已接纳内容保护（P0）

**来源：**真实生产要求及“单份正文进入现有接纳链”；必要工程约束。

保留 Plan、候选、Review、Canon proposal、正式 Canon 和 Narrative State 的区别。合法 Schema、模型自评分或审稿服务故障均不能自动批准章节。采用现有批准模式与权限；本规格不打开 AUTO、不创造人工批准或独立文学资格。

保全所选稿件自己的审读/质量/事实支持绑定、人物信息边界、原稿优点保护以及较差修订可被拒绝的能力。Book acceptance 继续在其正式事务边界提交 Outcome、Canon、State、投影和游标；下一章读取正式接纳边界。

已接纳正文和历史事实不得因新 Prompt、策略或快路径被回写。需要历史修改时走现有受控版本/Edition 流程，不由本包静默迁移故事内容。

### R-012 失败、部分成功与恢复（P0）

**来源：**减少不必要输出失败点；必要执行约束。

区分协议/引用定位失败、叙事正确性失败、创作质量问题、权限/预算阻塞和外部/提交结果 UNKNOWN。使用现有状态体系，不新增一套平行恢复状态机。

正文已生成而审读失败时保留候选和回执，不正式接纳、不丢弃结果、不从头重跑整本书。已取得响应但标准化/物化失败时优先恢复本地处理；只有明确、授权、可重试的外部步骤可再次调用。UNKNOWN 必须先查询或对账，禁止改幂等键规避旧未知结果。

重试/取消/Worker crash/租约失效/迟到响应/重复提交/并发计划变更均保留既有 Fence、版本和幂等约束。取消不能被解释为确定没执行或零费用。局部修复同样计入现有调用预算，不能无限循环。

### R-013 合同版本、兼容与回退（P0）

**来源：**现有主链修正不能损坏既有产物；必要工程约束。

同步处理模型物理输出 Schema、内部领域表示、Prompt/Skill/Pack 绑定、Provider materialization、路由 producer 身份及下游消费者。不得用新 Schema 重新解释旧冻结请求，或在旧内容 hash/版本下修改 Prompt、Skill、证据和正文。

保留旧产物只读与必要的版本化适配。新旧数据可以在同一受控主链通过明确版本分派读取，但不能形成第二个独立生产系统。对受影响在途调用，保持冻结合同可恢复，或明确停止并提供前向恢复路径；不能静默切换到新合同重新发送。

源数据、已接纳状态及旧审读证据不破坏性重写；需要存储变更才新增必要迁移，既有迁移正文不可编辑。回退不意味着撤销已接纳历史。

Prompt/Skill/Context/输出语义改变后重新核对适用准入与资格；旧 benchmark/qualification 不得被自动当成新 producer 的质量证明。保留作者稿件接入的来源证据，不为作者稿件补造模型生成回执。

### R-014 小型真实对照与连续章节接入（P1，需独立运行授权）

**来源：**“做小型真实对照并接入连续章节”“交付真实正文、失败记录、盲评与成本”。

在运行前冻结获授权作品/版本、被比较合同、Provider/模型配置、输入边界、预算和评价方案。规模不由本规格虚构；必须足以覆盖本次所宣称的合同变更及接纳后继续消费关系。单个孤立输出或纯 fixture 不能验收此项。

先分离合同变化与方法/策略变化；比较合同本身时尽量保持相同语义输入和模型配置，评估 Context/策略变化时记录实际差异。模型不保证可复现随机种子；报告不可控差异和混杂，不强制全因子实验。

保留原始/规范正文、实际 Provider 输入身份、失败/修复、延迟与全链调用消耗。成本包括筛选、审读、修订、失败、重试，不仅 Writer；金额不可测或权益计费时标明未知/计量方式，不写成免费。

真实生产证据必须覆盖：候选经既有审核与接纳；随后章节的请求/Context 绑定该已接纳正文产生的 Canon/State，而非预填快照。实验候选不能冒充生产合格候选；必须按既有权限进入生产或留在隔离实验。

盲评隐藏版本、处理标签、生成/修订身份和已有 Judge 分数；映射不交给评审。模型盲评和真人审读分开标注。旧合同无正文只支持可执行性比较，不支持虚构文学胜出。

### R-015 真实问题驱动后续 Narrative / Creative Intelligence（P1）

**来源：**用户引入的真实作品驱动方向；本包真实对照要求。

将实际正文或失败记录中的问题按层归因：合同/装配、Context 缺失、人物/因果/义务一致性、场景/声音/节奏/趣味、审稿/过修或运行条件。每项可追溯到确切版本及证据；不可观测内容标未知。

区分工程收益和文学判断。已有代码、方法送入 Prompt、Craft 被选择，均不等于正文有效使用或读者受益。对照结论允许“改善、无明确收益、退化、证据不足”，不得只保留好样本。

优先形成能解释真实问题的后续候选，不自动增加状态类型、Craft 目录或 Agent，不让反馈直接修改已接纳 Canon/计划。本项是本次交付的分析与证据要求，不要求建设新反馈平台或自动优化系统。

### R-016 最小必要验证与分层交付（P0 验证保护；P1 效果证据）

**来源：**用户要求可客观验收、只做必要测试、不把模拟通过当实际效果。

复用现有测试与检查，补本包风险相关的少量直接断言和正式链集成，不以测试数量或截图数量为交付。开发中用定向检查；最终遵守仓库当前适用的治理/回归要求，不为减少测试修改 gate 或标记虚假豁免。

分别报告需求状态、工程实现、正式接线、实际执行、对照结果及长期质量边界。没有授权/环境/人工评价时记录未执行及可恢复位置；可报告工程部分完成，不能报告真实对照或整个工作包完全完成。

## 7. 流程、接口与数据合同

### 7.1 主流程

```text
现有作者/操作员请求
→ 既有命令接纳、书籍与计划/已接纳状态解析
→ 现有 Intent / Memo 与任务适用方法
→ 受控 Context 编译（满足条件时走确定性快速路径）
→ 冻结实际模型指令、输出合同、身份与预算
→ 既有 Provider Runtime / ExternalEffect
→ 模型语义输出
→ 程序解析、引用映射、正文规范化与证据位置绑定
→ 不可变候选 + 真实执行回执
→ 既有审读、受控修订/复审与候选选择
→ 从所选正文提取并验证事实和状态变化
→ 既有 Quality / Release 及 Book 正式接纳
→ 已接纳 Canon / Narrative State 进入后续章节
```

该图表达业务依赖，不要求修改当前所有 Workflow 节点顺序。不得为实现图形而增加模型调用；现有导出/Release 与接纳依赖需核对并兼容，不在本包擅自重新定义发布架构。

### 7.2 四层输出分工

| 层 | 内容与所有者 |
|---|---|
| 模型语义输出 | 创作正文，或当前任务的分析/诊断/事实候选/语义引用选择；不含自造运行回执 |
| 程序标准化 | 规范正文、确定性派生表示、已知身份、精确区间及版本绑定；不补造叙事事实 |
| 领域判断 | Review、Canon 支持、质量、Plan/Book 各自决策；不能因结构化成功越过审批 |
| 运行与审计记录 | 来自实际命令、Attempt、Effect、预算、提交和操作员身份；不以模型文字替代 |

这四层是职责契约，不要求新增四套 Schema、四个服务或四个数据库。已有模型输出、领域对象与存储信封分层足够时直接沿用。

### 7.3 重要异常路径

| 场景 | 必需行为 |
|---|---|
| 请求缺少正式计划/授权/必要 Context | 沿现有入口拒绝或提示具体缺项，不能用 fixture 默认值补齐 |
| 正文输出合法但复审未完成 | 保留候选；不产生正式接纳或下一章正常推进 |
| 引用多处匹配/不存在/绑定旧稿 | 局部消歧或修复；不可静默选择、猜 offset 或改目标稿件 |
| 响应已保存后程序失败 | 恢复同一响应的校验/标准化，不无故再次调用 Provider |
| 对外请求或提交结果未知 | 使用现有 reconciliation；旧预算和占用保留，不能当失败后免费重跑 |
| 中途取消、Worker crash、过期 Fence | 旧尝试不可晚提交；保留已发生副作用与合法候选，按现有状态恢复 |
| 快路径期间计划或接纳边界变化 | 拒绝失效产物用于当前提交；重新冻结或恢复原合同，不原地替换输入 |
| 多次提交同一接纳请求 | 保持既有幂等行为，不重复推进 cursor、State 或义务 |
| 修订比原稿差 | 保留现有候选比较/回退能力；不因为“新版本”就覆盖原稿 |

## 8. 非功能、运行与安全边界

**授权。** 当前文档任务只授权保存规格和草稿 PR，不授权真实模型、数据库写入、部署或生产恢复。后续运行必须从现有系统获得有效账号、模型/任务资格、作用域、期限及有限额度；订阅存在、环境里有密钥、文档写了预算或允许开发都不是运行授权。没有授权先完成无副作用实现和验证，停止在实际调用前。

**数据。** 原始响应、候选与诊断按现有安全存储处理；导出对照包去除密钥、账户凭据、无关私有信息和不允许暴露的素材。完整 Prompt 观察复用已有 hash/组件记录及受控检查，不新增全量敏感输入的无权限日志。

**一致性。** PostgreSQL 仍拥有正式状态；跨 Provider I/O 不包入长事务。新合同不削弱 Scope、Lease、Fence、幂等、权限、已冻结版本和唯一接纳边界；Recovery 不通过覆写终态历史“修好结果”。

**性能。** 不规定无依据的秒数、token 数或百分比。衡量实际链路输入/输出、选择调用、重试与开销；快路径不能通过跳过必要语义工作、权限或事实校验取得表面提速。

**部署与回退。** 本包开发交付须说明 Pack/Schema/Prompt/Skill、路由资格和在途操作的兼容顺序；生产部署与真实迁移另行授权。不能删除现有历史版本或重置数据库来使新合同通过。

## 9. 验收矩阵与证据层次

“自动”是确定性检查；“集成”必须覆盖真实应用/存储边界，可使用明确标注的 scripted Provider 证明协议；“真实”是获授权 Provider 及正式连续消费；“审读”是独立意见。四者不能互相替代。

| 验收 | 需求 | 可执行条件及负例 | 证据类型 |
|---|---|---|---|
| A-001 | R-001、R-010 | 记录一个正常生成/审读/继续请求的实际入口→装配→Handler→Provider→下游；不存在新增旁路接纳或第二条生产链。独立测试入口不算完成 | 源码追踪＋集成 |
| A-002 | R-002、R-007 | 使用正式 renderer 检查首发、重试、相关 Skill/Schema/阶段附加指令；无无关交接/测试/落库自证要求，仍保留任务所需安全约束；小说中类似词汇不被误删 | 自动＋受控请求样本 |
| A-003 | R-003 | 每阶段模型协议与解析器一致；正文含合法文学结构不被误判；JSON 外报告/非正文自检被正确拒绝或局部处理，不污染正文 | 自动 |
| A-004 | R-004、R-011 | 模型只生成一份候选正文；程序得到规范 text 及合法场景关联；Review/Canon/Selection/Acceptance/Export 使用该候选；不同原稿/修订候选不被去重丢失 | 自动＋集成 |
| A-005 | R-005 | 模型不返回已知工程信封字段也能完成领域装配；未知引用、跨书/旧版本选择无法被默认 ID 补齐；模型未决定的叙事事实不被程序补真 | 自动＋集成 |
| A-006 | R-006 | 唯一、重复、缺失引用及中英文/换行/组合 Unicode 情况正确定位或失败关闭；稿件变更后旧 span 不能继续通过；exact match 不冒充语义支持 | 自动＋语义支持回归 |
| A-007 | R-006、R-012 | 证据修复不触发无理由整章重写；局部修订不能改动冻结范围外的文本；过期版本和歧义不接受 | 自动＋集成 |
| A-008 | R-007 | 无真实反馈时不生成“真实用户意见”；模拟意见保留代理标签；不同 stage 收到相关方法且不获额外工具/审批权限 | 自动＋真实输入样本审查 |
| A-009 | R-008 | 适用与不适用场景均可走通；不用某套路不会被非空字段或 Reviewer 自动打回；作者明确代价/承诺硬约束仍被执行 | 自动＋真实对照/审读 |
| A-010 | R-009 | 合法、必要覆盖充分且完整请求预算内的案例无需多余 selector/压缩调用；超预算、保护内容过量、未来/他书数据及旧缓存按正确分支处理；两路径都产生正常冻结 Context | 自动＋集成 |
| A-011 | R-011 | Review unavailable、State/Canon 拒绝、质量未完成不会推进接纳；选中原稿时使用原稿自己的审读；已接纳内容不被新合同回写 | 集成 |
| A-012 | R-012 | 响应已得后崩溃可复用结果；UNKNOWN 不盲重发；重复请求、取消、租约失效、迟到结果和并发边界改变不产生重复接纳 | 定向故障集成 |
| A-013 | R-013 | 旧产物及冻结在途请求仍按原合同读取/恢复；新版本被明确选择；同身份新内容被拒绝；作者稿件不获得虚构模型回执；资格不跨 producer 静默复用 | 自动＋集成/必要升级测试 |
| A-014 | R-014 | 交付实际模型原始/规范正文、失败与全链消耗；新合同候选按现有规则接纳，后续章节实际输入能追溯该 Canon/State；缺任何一项不得称真实连续闭合 | 真实 |
| A-015 | R-014、R-015 | 比较输入/处理差异和盲评映射隔离可检查；模型、真人、代理与参考评价分开；旧臂无正文或样本不足时不宣称文学胜出；包含负面/无收益结果 | 真实＋审读 |
| A-016 | R-016 | 交付范围、基线/最终 SHA、必要测试、真实运行和未验证边界分别报告；未调用真实模型或未获人工意见的项目明确未执行，不用历史 PASS 补证 | 交付核查 |

不设置预先保证“文学显著改善”的分数或比例。本包可以客观验收合同、安全、连续消费和对照完整性；文学收益必须依据实际评价独立下结论。明显退化必须记录、处置并在发布建议中说明；工程测试通过不能把退化改写为质量通过。

真实验证的作品、篇幅、模型、样本量、预算和评审安排在调用前由运行计划明确，沿既有授权执行；缺少这些运行输入时 R-014/A-014～A-015 保持待执行，不影响规格的实现方向，但阻止报告“整个工作包已完成”。

## 10. Codex 实施顺序与交付

本文件不给 Codex 隐含会话前提。执行开发前读取最新 main、适用 AGENTS 和现有文档/规则，比较与本文件基线的差异。相同需求已完成时举证复用，不重复实现；重大业务冲突必须明确报告，不能静默删改需求。

建议在同一正式链中逐步完成，不设强制工作包数量或固定章节数：

1. 固定相关生产入口、现行 Prompt/Skill/Schema/标准化/下游绑定和代表性失败，确认真实职责污染位置。
2. 确定物理输出与领域信封分层、单份正文及场景定位方案；先维护兼容，再更改生产选择。
3. 同步修正最终输入、输出 Schema、阶段附加指令、元数据/引用程序装配、局部修复与下游消费者。
4. 在现有 Memo/Context/方法组织中落实适用性与有条件快路径；已有正确实现不新增包装。
5. 完成相关异常/恢复/版本回归与原生接纳消费；合并必要文档变更后再进入获授权真实对照。
6. 报告本包收益与缺口，形成有正文依据的后续 intelligence 候选，不自动开始后续平台项目。

必须提供：变更文件与理由、可复核入口链和代表性请求/输出、正文版本及下游绑定、错误/恢复与兼容说明、实际执行命令和必要测试结果、真实对照及消耗或明确未执行原因。复用现有查询/导出/回执，不创建第二套资格数据库或审计目录体系。

开发时只更新确有变化的 canonical 当前文档、指令/运行/测试清单及 Reality projection；不得把未来计划写成当前能力。遵守 `skills/` 源文件与生成副本规则，不直接编辑生成副本。历史迁移及终态证据保持不可变。没有明确部署/付费权限，不自动部署、运行或恢复生产。

本次规格提交仅允许本 Markdown 文件和确有必要的文档索引，不修改源码、运行配置、依赖或迁移。本文件不需要加入 runtime instruction manifest，也不能被作为模型方法注入。完成/替代后的提案清理遵循现有生命周期规则，Git 保留历史。

## 11. 后续方向及明确未批准的方案

InkOS Harvest、Narrative Intelligence、Creative Intelligence、Quality Proof 在本包不是四个平行平台项目。当前先收敛可导致失败和错误职责的合同，在同一链落实已明确点名的执行/Context/方法改进，再以真实作品决定后续最值得做的能力。

下一阶段可能涉及人物持续动机、长程因果/伏笔、Arc/Promise 兑现、声音/趣味/节奏、修订净收益和长篇退化。但本会话没有给出这些新功能各自完整的输入、权威状态和验收范围，不能由本规格自动批准。既有能力因本包修改受影响时需要回归，不代表新增这些目标模块。

以下方案没有成为当前必做决定：只保留两个自治 Agent；把全部能力迁入新 Harness；增加独立 Creative Brief/Composer 服务；无条件跳过审稿或更改修订 DAG；强制特定题材/模型；固定 3/10/30/100 章；统一永久暂停所有 Platform Engineering；全量吸收 InkOS 代码。工程选择必须服务 R-001～R-016，而不是反向创造需求。

## 12. 相关既有文档与维护

- [仓库规则](../../AGENTS.md)
- [Canonical 文档范围](../../docs/README.md)
- [当前系统](../../docs/current-system.md)
- [运行与回归要求](../../docs/runtime-operations.md)
- [开发及提案维护规范](../../docs/development.md)
- [既有长期蓝图提案](industrial-novel-os-blueprint.md)
- [既有叙事记忆/Context 提案](narrative-memory-context-lifecycle-closure.md)
- [既有语料验证提案](classical-corpus-codex-validation.md)

上述提案仅作范围关系导航，不因被引用获得本包授权；其中历史实验的固定样本、章数或运行参数不得自动继承。本文件是本次 R-001～R-016 的主规格，不新增平行现状权威。必要需求均在第 6 节标明来源，并在第 9 节对应可执行验收。
