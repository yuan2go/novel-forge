# Novel OS 创作能力融合技术方案

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — 原生基础已接线；新增机制与创作收益须分别验收。**
>
> **NOT_RUNTIME_AUTHORITY**

本提案只定义外部创作机制的原生吸收边界。代码、schema、migration、runtime wiring 和测试高于这里的判断；本文件不授权模型消费、业务数据变更或作品发布。

审阅日期：2026-09-19。唯一实现基线为执行开始时 fetch 到的 `origin/main`：
`c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4`；implementation identity：
`sha256:4b4a0cbca7dccbaf8e09dc6032c30c5c3d5dd320679560f6d2a4a918643cf838`；migration head：`20260916_0136_provider_routing_policy`。

该路径当时尚未进入 main；已有提案位于 `origin/docs/creative-capability-assimilation-20260914` 的 `43b39710944b9de3c1ae7709e44165d92ae4298c`。本次在最新 main 上修订并带入同一路径，旧分支不是实现基线，也不另立总体蓝图。`PARTIALLY_IMPLEMENTED` 指复用的原生基础，不表示以下 WP02+ 已实施。

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-19",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4",
    "implementation_tree_sha": "sha256:4b4a0cbca7dccbaf8e09dc6032c30c5c3d5dd320679560f6d2a4a918643cf838"
  },
  "scope": [
    "src/novel_forge/modules",
    "src/novel_forge/api",
    "src/novel_forge/storage",
    "config/capability_packs"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py",
      "symbol": "PlanningWorldPreparation"
    },
    {
      "path": "src/novel_forge/modules/story_planning_runtime/knowledge_translation.py",
      "symbol": "validate_knowledge_translations"
    },
    {
      "path": "src/novel_forge/modules/mkaos_authority/applicability.py",
      "symbol": "assess_applicability"
    },
    {
      "path": "src/novel_forge/modules/narrative_state/reality.py",
      "symbol": "NarrativeRealityRevision"
    },
    {
      "path": "src/novel_forge/modules/plan_change_authority/domain.py",
      "symbol": "semantic_plan_diff"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/candidate_selection.py",
      "symbol": "compare_candidates"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {
      "id": "cross-chapter-prose-coverage",
      "description": "DESIGN_REVIEW_REQUIRED: freeze bounded accepted-prose coverage and paired evidence semantics before extending the existing Chapter review contract; never claim whole-book coverage from a window.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/review/diagnostics.py",
          "symbol": "validate_diagnosis"
        }
      ]
    },
    {
      "id": "actor-isolation-value",
      "description": "DESIGN_REVIEW_REQUIRED: compare isolated character decisions with existing WORLD_REASONER and DIRECTOR stages before adding Provider calls.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py",
          "symbol": "PlanningWorldPreparation"
        }
      ]
    },
    {
      "id": "accepted-history-and-editorial-policy",
      "description": "DESIGN_REVIEW_REQUIRED: accepted-history corrections, edition semantics and whole-book human acceptance remain with the industrial blueprint; this proposal adds no competing policy.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/plan_change_authority/domain.py",
          "symbol": "require_approvable_scope"
        }
      ]
    },
    {
      "id": "creative-effect-and-budget",
      "description": "DESIGN_REVIEW_REQUIRED: independently reviewed original prose, negative controls, bounded cost and finite entitlement must justify craft and diagnostic changes; scores alone are not quality.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/chapter_authority/candidate_selection.py",
          "symbol": "compare_candidates"
        }
      ]
    }
  ],
  "remaining_work": [
    {
      "id": "wp02-cross-chapter-repair",
      "description": "Add bounded paired-prose diagnoses to the existing Chapter review/revision consumer, preserving accepted history.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/review/diagnostics.py",
          "symbol": "validate_diagnosis"
        }
      ]
    },
    {
      "id": "wp03-conditional-craft",
      "description": "Use current KnowledgeCard applicability, located translation, Memo and scene craft contracts; extend content or prompts only where controlled prose evidence shows a gap.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_planning_runtime/knowledge_translation.py",
          "symbol": "validate_knowledge_translations"
        }
      ]
    },
    {
      "id": "wp04-private-actor-experiment",
      "description": "HOLD implementation until controlled private-knowledge counterexamples justify extra actor-scoped calls in native world preparation.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/story_planning_runtime/world_preparation.py",
          "symbol": "PlanningWorldPreparation"
        }
      ]
    },
    {
      "id": "wp05-author-workbench",
      "description": "HOLD broad UI redesign; assess exact-base manuscript diff/accept/reject and selectively extend native commands.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/plan_change_authority/domain.py",
          "symbol": "require_approvable_scope"
        }
      ]
    },
    {
      "id": "wp06-long-range-audit",
      "description": "After WP02, extend Book Follow-up with honest accepted-prose coverage and actionable proposals; do not bypass unresolved whole-book human acceptance.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/book_followup_authority/domain.py",
          "symbol": "build_longform_recap_outputs"
        }
      ]
    },
    {
      "id": "wp07-market-observations",
      "description": "HOLD until source access, dataset rights, cohort comparability and native consumer value are established.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/mkaos_authority/applicability.py",
          "symbol": "assess_applicability"
        }
      ]
    }
  ]
}
-->

## 阅读方法与证据边界

机器可读的 [Assimilation Audit](../audits/creative-capability-assimilation.json) 包含全部 17 个上游的 URL、branch、完整 SHA/tree、许可证文件哈希、实际读取区间/定向扫描、仅盘点的 workflow/tests/prompt/schema 路径、30 条机制决策和 12 条原生链路。矩阵通过 `native_chain_ids` 连接完整链路，避免重复抄写同一 Authority。本文 A–E 是这份证据的设计解释，不是第二份当前能力清单。

审计方式是固定 checkout 后按机制追踪入口、调用者、状态写入、失败分支和测试断言；没有运行外部代码、安装其依赖或消费真实 Provider。定向扫描与全文读取分开记录，目录中存在但未读取的文件仅标为 inventory。此审计覆盖全部候选仓库，不等于逐行安全审计、所有依赖审计或所有许可证权利清查。全部仓库均可访问；本次未观察到重命名、迁移或失效。

本包静态追踪的上限是 `WIRED`；没有入口证据的对象只记 `CODE_EXISTS`。baseline Reality projection 的 `EXECUTABLE` 及历史工程 ceiling 在 JSON 中另列，不能冒充本次执行。`QUALIFIED` 必须绑定具体资格记录；`PRODUCTION_PROVEN`、真实长篇效果和独立编辑质量在本包均为 `NOT_PROVEN`。读取测试不等于运行测试；README、演示书、角色数量和自评分不升级证据。

审计 JSON 是提案引用的设计研究附件，无 runtime consumer，不进入 manifest、Reality projection 或业务读写。`architecture/evidence/` 仅保留受 Reality 引用的资格报告，故本附件不放在那里；`architecture/proposals/` 只放有 inline lifecycle 的 Markdown。后续语义设计仅修改本提案；JSON 只记录固定版本的证据、比较和处置。

## A. Novel Forge 当前真实能力

以下路径均相对仓库根；具体固定 SHA 链接、文件哈希、相关 migration 与测试在 JSON 的 `native_chains`。共同 persistence 边界为 `storage/authority_uow.py::AuthorityUnitOfWork`，Repository 不是独立 Authority。

| 原生链路 | 实际入口 → owner / mutation → consumer | 当前边界与不能据此证明的内容 |
|---|---|---|
| N01 Source / MKAOS | `api/routers/source_import.py`、MKAOS API → Source Import worker → Source/MKAOS 审批及版本化 Card → Formation/Planning knowledge selection → Review | 有权限、来源、适用性、采用位置与正文核验，不缺一个笼统的“拆书引擎”。有 Card/译用位置不等于实际写得好。 |
| N02 Story Formation | Book opening / `StoryFormationApplication` → foundation generation → `PostgresStoryDesignAssetAuthority.transition` → approved typed design → Planning | 有故事形成、世界/人物/主题资产和激活边界；模型输出不能自行成为语义决定。 |
| N03 World / Planning | `PostgresBookProductionSupervisor._generate_plan` → `chapter_plan.generate` → `PlanningWorldPreparation.prepare` → WORLD_REASONER 生成、DIRECTOR 评估 → `compile_world_plan` → typed active plan → Chapter | 已有候选世界、有限推演、目标/资源/认知约束、离屏后果、停止/过期条件和滚动规划。当前生成是单个 WORLD_REASONER 阶段，不能称为每个角色独立隔离的模型决策。 |
| N04 Context / Packs | owning operation → frozen retrieval union / `project_role_context` → ContextBundle / frozen CapabilityPack → `execution_gateway` / Provider views | 人物认知投影、来源隔离、预算与 replay 已存在。CHARACTER_REASONER 枚举不证明独立 actor stage；新 digest/index/GC 仍由既有 memory proposal 处理。 |
| N05 Canon / Temporal / Graph | Chapter extraction + support → Canon approval → `PostgresBookAuthority.accept_chapter` → outcome/Canon/state/projection 原子绑定 → immutable reality/event index → Temporal API、下一章 Context | `TemporalQueryService` 和 `/product/temporal-query` 已接线，支持 state/knowledge/belief/relationship/promise 等 chapter-as-of 与 changes-between。accepted lineage、因果/关系/义务查询不是缺失能力；通用推断图、edition/retcon 不能据此视为完成。 |
| N06 Draft / Craft / Memo | Chapter scheduler → Execution Intent / Chapter Memo → `_DraftHandler` → `compile_realization_contract` → Provider draft → `integrate_realization` | v2 从冻结 style policy 启用 whole-chapter + targeted specialisms；ACTION 已含空间/资源/行动回应/代价，DIALOGUE 已含目标/回避/声线，INTERIOR 含选择冲突。slot、词面 marker、Memo 字段通过只证明合同，不证明自然声线、精彩战斗或感情推进。 |
| N07 Review / Revision | `_ReviewHandler` → `normalize_review_result` / `validate_diagnosis` → `_RevisionHandler` → rereview / `verified_resolutions` → `compare_candidates` → release gate | 有精确 Unicode span、preserve、acceptance criteria、未解 issue、候选保留与回退。当前 locator 校验单个候选正文；review task 没有有序跨章正文覆盖合同。现有 Context/retrieval 可以携带历史信息或片段，这不等于按版本完整覆盖跨章正文。分数阈值不是已校准的创作质量标尺。 |
| N08 Plan Change | planning API propose / decide / activate → `semantic_plan_diff` → recursive `asset_dependency_edge` / `record_impacts` → future stale / native resume | 已有级联影响、选择性失效与作者决定。`EXECUTED` 不可改写；`PLANNED`/`SPECULATIVE` 区分保留。不是所有语义影响都能靠已登记边自动发现，缺边检测需要具体失败案例。 |
| N09 Reader / Follow-up | accepted snapshot → follow-up coordinator / worker → Reader Outcome Provider；LongformRecapHandler → `build_longform_recap_outputs` | Reader 读取接纳正文但为 advisory；计划调整是 proposal。**生产 recap handler 是冻结 observations 的确定性归纳，不是跨章全文审稿**；`execute_longform_analysis` 包装函数存在，不能把它当作 recap 已消费。 |
| N10 Book completion | completion API → `PostgresBookCompletionAuthority` → closure case / immutable decision | 有 ending/promise/theme/character/relationship 闭合检查、CAS 和 replay；ACCEPTED 请求仍持久化为 BLOCKED，原生 human whole-book acceptance policy 未闭合。结构完成不等于全书质量验收。 |
| N11 Provider / recovery | ProductionExecutionComposition → ProductionProviderRouter / frozen pack → Kernel ExternalEffect intent → adapter → receipt → owner gate | 最新 main 已接线成本/质量约束路由与 entitlement/budget，不再是“另一个待建 router”。缺质量证据会阻断，benchmark 输出不可升级；CLI 不等于无限额度或零成本。UNKNOWN/commit 不明先 reconcile，重试追加版本。 |
| N12 Agent | Agent API / scheduler → Agent Runtime definition/session/provenance → governed domain tools | 有原生 runtime；不能让编码 Agent 的文件写入、投票或工具回执替代 Canon/Planning/Review Authority。 |

关键直接证据：

- `story_planning_runtime/execution.py` 调用 `PlanningWorldPreparation.prepare`；`book_authority/supervisor.py` 冻结 accepted frontier 后传入 world preparation request。其输出最终在 `book_authority/production.py` 的 acceptance 路径由 `validate_acceptance` / `validate_actual_world_events` 核验，不能跳过正文直接接纳预测。
- `storage/plan_change_repositories.py::record_impacts` 使用递归依赖查询、循环保护、invalidation policy 和 execution scope；不是仅有 PlanChange DTO。`modules/plan_change_authority/application.py` 在批准激活时调用它并处理非当前 plan input。
- `api/authority_app.py` 创建并注册 TemporalQueryService/router；`narrative_reality_repositories.py`、0114/0115 的 SQL 函数/trigger 约束 accepted lineage；不是仅有时态 schema。
- `chapter_authority/handlers.py` 把 Memo、realization contract、knowledge review targets 交给真实 Provider stage；`provider_views.py` 明确 whole-chapter drafting 与 diagnosis-directed editing；`review/knowledge.py` 要求知识核验给出正文位置/条件/异常检查。
- `book_followup_authority/handlers.py:331–416` 从 command payload observations 调用 deterministic recap；`coordinator.py:267–353` 冻结状态/质量/Reader 引用，没有跨章全文 manifest。这是本次优先保留的真实缺口。
- `book_authority/completion_domain.py::completion_result_schema` 对 decide 只允许 BLOCKED/REJECTED；相关 PostgreSQL 测试明确验证没有 native human policy 时持久化阻断。本包不把这解释为需要绕过的 bug。

### 十三个重点方向的处置

| 方向 | 结论与决策 |
|---|---|
| Character Actor/private knowledge/goals | 目标、认知、后果与 role projection 已有。独立 actor 调用是受控比较实验，`ADAPT_MECHANISM`，实现先 HOLD；不是新 Character Authority。 |
| World Arbiter/off-screen | World Preparation + DIRECTOR + accepted consequence reconciliation 已有，`KEEP_NATIVE`；只试验更好的角色动机判断。 |
| rolling horizon/alternative futures | 已有 native candidate/preparation/continuation/horizon，`KEEP_NATIVE`；不复制外部 3 章/3 分支常数。 |
| Temporal Canon/as-of | chapter-as-of 已接 API，`KEEP_NATIVE`。story-time/disclosure-time/edition 的多轴语义仍 `UNRESOLVED_DESIGN_CONSTRAINT`。 |
| Narrative Knowledge Graph | 已有 accepted causal/event/relationship/obligation 与资产依赖图；通用 graphify/图数据库 `HOLD`，先证明具体查询缺口。 |
| cascading revision | 计划递归依赖与未来失效已实现，`KEEP_NATIVE`；接纳历史的补偿/新 edition 交既有工业提案，不新造 retcon 引擎。 |
| battle/romance/humor/hook Craft | 现有 KnowledgeCard/Scene/Memo/Review 已有载体，`ADAPT_MECHANISM` 只吸收条件化机制和诊断差异。无需先建新模块。 |
| modify/evaluate/keep-discard | 已有更严格候选/诊断保留，`KEEP_NATIVE`；拒绝 score-only 成功与 git rollback。 |
| cross-chapter/whole-book audit | 状态与结构检查已有；有覆盖证据的跨章正文诊断不足，`EXTEND_NATIVE`，优先 WP02；whole-book human acceptance 仍待设计。 |
| author diff/accept/reject | 语义 diff/批准/拒绝后端已在，Admin 也有 Review/KG/Context 屏幕；完整 manuscript journey 未实测。`ADAPT_MECHANISM`，小范围 WP05，不宣称 UI 完全缺失。 |
| market trend | 有可参考的抓取/快照机制，尚无可迁移的授权、可比 cohort 与需求推断证据，`HOLD`。 |
| coding-agent workspace | CLI execution 已有原生 ExternalEffect；另建自治文件工作区 `REJECT_IMPLEMENTATION`。 |
| multi-agent debate | 不采纳 vote-to-truth/committee Authority，`REJECT_IMPLEMENTATION`；独立异议最多作为 Review evidence。 |

约束分类：accepted atomicity、fencing、raw-source isolation 是由代码/SQL/测试断言支持的 `CURRENT_PROVEN_INVARIANT`（本包没有重新执行运行证明）；路由已接线和 recap 为确定性 handler 是 `CURRENT_RUNTIME_FACT`；窗口、阈值、预算、轮次数是 `CONFIGURABLE_POLICY` 或尚未抽离的实现常数，不因此成为架构公理；旧 contract v1 支持属 `HISTORICAL_COMPATIBILITY`；edition、人审 quorum、actor 调用收益属 `UNRESOLVED_DESIGN_CONSTRAINT`。

## B. External Assimilation Matrix

完整矩阵在 JSON 的 `assimilation_matrix`，每行均含 executable evidence、problem、原生 equivalent/ceiling、gap、decision/reason、owner/consumer、contract/schema、migration、Provider/Context、failure/recovery、license、priority、WP02+ destination 与 acceptance evidence。下表是按仓库的阅读入口；完整 SHA 不能用下表简写代替。

| 仓库（固定 branch） | 完整 upstream SHA | 许可证文件事实 | 代码结论 / 去重处置 |
| [Narcooo/inkos](https://github.com/Narcooo/inkos/tree/091048383f411eb99948a8764f42b6fd13006f9b) (`master`) | `091048383f411eb99948a8764f42b6fd13006f9b` | AGPL-3.0 | 修订快照、forecast 真接线；stale 仅标记，select 输出 Markdown。保留原生候选与世界准备。 **KEEP_NATIVE**。 |
| [lingfengQAQ/webnovel-writer](https://github.com/lingfengQAQ/webnovel-writer/tree/2dc32458f3c60a3d6496d0c50e2b47142a7deb5c) (`master`) | `2dc32458f3c60a3d6496d0c50e2b47142a7deb5c` | GPL-3.0 | v6 commit/projector 和 CSV craft 检索；不是未发布 v7/v8。保留原子接纳，仅吸收条件化 craft。 **KEEP_NATIVE、ADAPT_MECHANISM**。 |
| [Xiaoyangy/novel-studio](https://github.com/Xiaoyangy/novel-studio/tree/a0326e05325fda90b7c6636f4068c584d1a63f01) (`main`) | `a0326e05325fda90b7c6636f4068c584d1a63f01` | Apache-2.0 | 角色私有视图、保存决策、rehearsal 双阶段可追踪；独立 actor 的增益待实验。 **ADAPT_MECHANISM、KEEP_NATIVE**。 |
| [NousResearch/autonovel](https://github.com/NousResearch/autonovel/tree/d165f267a0ffd34f3b0a70a8a72ac38cb8e4a542) (`master`) | `d165f267a0ffd34f3b0a70a8a72ac38cb8e4a542` | NO_LICENSE_FILE | 真实入口 run_pipeline；缺失分数 -1 可进入比较，git reset 回滚不采纳。全文审稿与片段 reader panel 分开。 **REJECT_IMPLEMENTATION、ADAPT_MECHANISM**。 |
| [EdwardAThomson/StoryDaemon](https://github.com/EdwardAThomson/StoryDaemon/tree/d0c7fa18d573bef38e344791fbdbeb9792c91474) (`main`) | `d0c7fa18d573bef38e344791fbdbeb9792c91474` | NO_LICENSE_FILE | tick/rolling beats 可执行；压力检测 instrument-only，部分合同 opt-in。保留原生义务/规划。 **KEEP_NATIVE、HOLD**。 |
| [ynnyh/jarvis-write](https://github.com/ynnyh/jarvis-write/tree/105eeb61d38868d65318f110b755e58224c2ef66) (`main`) | `105eeb61d38868d65318f110b755e58224c2ef66` | Apache-2.0 | 时态区间查询、最多30章/40伏笔影响扫描与 diff；native as-of/cascade 已更严格。 **KEEP_NATIVE、ADAPT_MECHANISM**。 |
| [AutoFiction-AI/autofiction](https://github.com/AutoFiction-AI/autofiction/tree/685ca031a39b593d9bf3d43950332e928ab054ea) (`main`) | `685ca031a39b593d9bf3d43950332e928ab054ea` | Apache-2.0_CODE / CC-BY-NC-4.0_GENERATED_ARTIFACTS | 真实全稿快照、window/cross audit schema 与 resume；吸收成对正文诊断，不采用编码工作区。 **ADAPT_MECHANISM、REJECT_IMPLEMENTATION**。 |
| [AI-Team-Team/AI-Novel](https://github.com/AI-Team-Team/AI-Novel/tree/8175eadf0c7fb240dd3a287612895236557e265e) (`main`) | `8175eadf0c7fb240dd3a287612895236557e265e` | Apache-2.0 | 委员会解析可直接 resolve_conflict；保留异议概念，不采纳投票真相与多层记忆库。 **REJECT_IMPLEMENTATION**。 |
| [iLearn-Lab/NovelClaw](https://github.com/iLearn-Lab/NovelClaw/tree/226d50d3ec284c9cc037c47eb14af39505f9ed74) (`main`) | `226d50d3ec284c9cc037c47eb14af39505f9ed74` | MIT | workspace agent/RAG editor 可追踪；top5 建议后全篇改写，不替代局部诊断修订。 **HOLD**。 |
| [KazKozDev/NovelGenerator](https://github.com/KazKozDev/NovelGenerator/tree/b1280e9227de6c2f30da6160599b9e31dec12386) (`main`) | `b1280e9227de6c2f30da6160599b9e31dec12386` | MODIFIED_BUSINESS_SOURCE_LICENSE_1.1 | 现版逐 scene writer/tracker；重试耗尽可降格 blocker，semantic scorer 失败可能无 findings。只吸收可证实的反复叙述诊断。 **ADAPT_MECHANISM、REJECT_IMPLEMENTATION**。 |
| [Anshler/graphify-novel](https://github.com/Anshler/graphify-novel/tree/124c9abc473508e081a625e4d2a24b24071581a2) (`master`) | `124c9abc473508e081a625e4d2a24b24071581a2` | MIT | 仅6个跟踪文件；Skill 调外部 graphify，无自身执行/持久化/test 证明。 **HOLD**。 |
| [multi-agent-story-generation/MARP](https://github.com/multi-agent-story-generation/MARP/tree/64d899ef6b96231fbc273b29fe2c1cfca89de5f0) (`main`) | `64d899ef6b96231fbc273b29fe2c1cfca89de5f0` | Apache-2.0_WITH_MIT_SUBTREE | Arena/Story 角色可见性与状态机；内存消息和随机 parse fallback 不适合生产真相。 **HOLD**。 |
| [EdwardAThomson/NovelWriter](https://github.com/EdwardAThomson/NovelWriter/tree/163581a7ddece0fd4a75f12e8fa848b81480fdf5) (`main`) | `163581a7ddece0fd4a75f12e8fa848b81480fdf5` | NO_LICENSE_FILE | adaptive analyses 固定示例分数/空 issues；集成 orchestrator 的 main/core caller 未证实。 **REJECT_IMPLEMENTATION**。 |
| [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode/tree/0ffe7db4fa02489f5d1989e58a22ce62d040a850) (`main`) | `0ffe7db4fa02489f5d1989e58a22ce62d040a850` | MIT | Prompt packet、storyctl/commit 文件门禁、扫榜脚本真实；主 Agent 填语义槽。只吸收机制。 **ADAPT_MECHANISM、KEEP_NATIVE、HOLD**。 |
| [giapnguyen74/xnovelist](https://github.com/giapnguyen74/xnovelist/tree/7abd8c1252fdf65120feeef3c977fc3283c08bfc) (`main`) | `7abd8c1252fdf65120feeef3c977fc3283c08bfc` | MIT | runTool 权限与 AIPanel 接受/拒绝真实；level4/5 actions 为空。只吸收作者交互。 **ADAPT_MECHANISM、REJECT_IMPLEMENTATION**。 |
| [304769384-png/fanqie-novel-skill](https://github.com/304769384-png/fanqie-novel-skill/tree/7d874e032d2de3dace74ae585cd2dbfbac2cde69) (`main`) | `7d874e032d2de3dace74ae585cd2dbfbac2cde69` | NO_LICENSE_FILE_DESPITE_README_MIT | 纯 Skill/参考资料；固定攻防次数、AI 检测阈值不成立为通用门禁。 **REJECT_IMPLEMENTATION、ADAPT_MECHANISM**。 |
| [wen1701/FanqieRankTracker](https://github.com/wen1701/FanqieRankTracker/tree/8d421dec6764a4c28eaf0c33c5d31a1615c68cbc) (`main`) | `8d421dec6764a4c28eaf0c33c5d31a1615c68cbc` | NO_LICENSE_FILE | 定时抓取/快照/rank delta 真脚本；缺可比性/权利/需求因果证据。 **HOLD**。 |

### 许可证与素材边界

所有判断来自固定树中的实际文件，不采用 GitHub license API 或 README 标签代替。没有命名 NOTICE 文件的事实记录在 JSON；不把“未找到”解释成没有其他权利。文件头扫描有明确范围，依赖/数据文件和二进制素材未逐一做法律许可清查，因此**本包和后续默认均不直接复用上游实现**。

- inkos 是 AGPL-3.0；webnovel-writer 根及子项目是 GPL-3.0。机制可研究，代码和 Prompt 不直接搬运。`ADAPT_MECHANISM → native clean implementation` 是本方案默认路径。
- novel-studio、jarvis-write、AI-Novel 的 Apache 文件以及 NovelClaw、graphify-novel、oh-story、xnovelist 的 MIT 文件只解决其适用范围内的许可声明，不自动许可小说、样例、图片、字体或第三方依赖。novel-studio 的 `third_party/litellm/LICENSE` 独立列入。
- NovelGenerator 的 LICENSE 是修改版 Business Source License 1.1：当前 non-production grant、商业生产需另授，Change Date 写为 2029-01-01 后 Apache-2.0。不能因为仓库公开或 API 显示 NOASSERTION 就当 MIT/Apache 使用。
- autofiction 的代码 Apache-2.0 与 ETHICS.md 对生成作品/产物声明的 CC BY-NC 4.0 分开；MARP 的根 Apache 与 `hanna/LICENSE` MIT 分开，均不替其中的故事/数据源做权利担保。
- autonovel、StoryDaemon、NovelWriter、fanqie-novel-skill、FanqieRankTracker 未发现 LICENSE 文件。StoryDaemon 的 setup.py MIT classifier 不代替授权文本；fanqie-novel-skill README 的 MIT 链接指向缺失文件，明确记为冲突而非 MIT 已确认。
- 外部小说正文、角色、设定、场景、独特情节组合、示例措辞、Prompt 文本、封面/图片/字体不进入 native 生产输入。Source 仍需每作品 rights declaration；市场页面可访问也不代表可收集/再发布。允许吸收的是用原创表述重新设计的抽象机制、反例与验收问题。

## C. Gap Closure Map

只保留下列可定位的差异。没有证据的增强不变成新模块，也不以“加 qualification”代替正文消费。

| Gap | 真实缺口 / 去重后的最小边界 | native owner → consumer | 决策 / 依赖 |
|---|---|---|---|
| G01 跨章正文诊断 | 当前 Review 定位单稿，Recap 读 observations；缺冻结的跨章实际正文覆盖和双来源引用校验。先在当前章接纳前做相邻正文诊断与局部修订。 | Chapter Authority / Review / Context Builder → existing revision / rereview / Candidate Selection → Book Acceptance | `EXTEND_NATIVE`，WP02；仅先行开发项。 |
| G02 条件化 craft 的真实收益 | 载体与采用链已完整；缺按具体失败场景验证的中文机制内容、判断一致性及独立正文证据。先验证现有链；失败定位到内容/Prompt/contract 后才修改。 | Source/MKAOS + Planning + Chapter → knowledge_checks / craft tasks / original prose | `ADAPT_MECHANISM`，WP03；复用 WP02 的诊断与对照，禁止先造“Craft Intelligence Authority”。 |
| G03 actor 决策独立性 | role projection 不等于独立 actor call；是否比现有 WORLD_REASONER+DIRECTOR 更可靠尚未证明。 | World Preparation → generated candidate → Hierarchical Planning → current chapter | `ADAPT_MECHANISM`，WP04 仅受控实验；没有泄漏/动机反例及增益，不加调用。 |
| G04 作者可理解的修订决定 | 后端语义 diff 与决定已有；完整 manuscript diff/keep/reject 的可用性、精确 base 和权限仍需实际走查。 | Chapter/Plan Change → author UI → native command | `ADAPT_MECHANISM`，WP05；先走查现有 Admin，不从截图推断。 |
| G05 长程全文覆盖 | 原生 Reader/recap/closure 不等于按真实文本审过每章；需要可量化 coverage、跨窗口复核和可消费建议。 | Book Follow-up → existing Review/Plan Change proposal；Completion 只消费其证据 | `EXTEND_NATIVE`，WP06；依赖 WP02，可读既接纳正文但不得改历史；whole-book acceptance 另待既有政策。 |
| G06 市场观察可信度 | 缺授权来源/可比 cohort/缺失值/观察时间的确定合同及对选题价值证据。 | Source → Book Design/Reader proposal | `HOLD`，WP07；不是先建爬虫或 market scheduler。 |

删除原计划中重复的新增 Temporal Canon、Narrative Graph store、Cascading Revision engine、Candidate Optimization framework、Provider Router、Agent workspace 和 Committee Authority。它们原本要解决的大部分问题已在 N03–N12；剩余 query、UI、calibration 问题附着在现有 owner。不得新增第二套 Canon、Story State、Memory/Planning/Review Authority、Provider runtime、预算账本、scheduler、retry/recovery 或 Agent authority model。

记忆 digest、索引水位、语义 retrieval coverage、GC/cutover 仍留在 [memory lifecycle proposal](narrative-memory-context-lifecycle-closure.md)；accepted edition、长期人审、真实读者 consent/quorum 留在 [industrial proposal](industrial-novel-os-blueprint.md)；语料真实阅读资格留在 [classical corpus proposal](classical-corpus-codex-validation.md)。本包引用这些未决边界，不重复承诺实现。

## D. Revised WP02+ roadmap

编号在本审计后重新定义，后续任务须引用此表而非旧分支的标题。P0/P1/P2/P3 是实施顺序，不是把所有质量差距都升级为架构故障。

| 顺序 | 最小但完整工作包 | 前置 / 输出 / 停止条件 |
|---|---|---|
| P0 · WP02 | **跨章正文证据驱动的当前章定向修订**：冻结相邻已接纳正文；双来源诊断；原有 revision/rereview/keep-discard；真实对照 | N04/N07/N11。输出可定位 issue、实际修订稿及未改坏证据；若成本或 coverage 超限，显式不完成，不能报全文通过。详见 E。 |
| P1 · WP03 | **条件化 Craft 到正文**：先用现有 Card/translation/Memo/v2 realization 对战斗可读性、关系推进/声线各做一个完整切片；幽默与 hook 仅在失败证据要求时加入 | 复用 WP02 判断/修订证据；先改原生内容与 pack，不预设 schema。若现有链已足够，交付批准资产/真实正文证据即可，不强造代码。 |
| P2 · WP04 | **人物私有决策对照实验**：在 World Preparation 内比较单 WORLD_REASONER 与最多必要 actor-scoped 调用；DIRECTOR 不取得 Canon 权限 | 先有信息泄漏/目标违背反例与预算；不依赖新存储。收益不优于成本或正文更机械，则保持现有路径。当前 HOLD 实施。 |
| P2 · WP05 | **作者精确版本修订界面**：当前稿/候选/证据可见、accept/reject、stale-base 拦截和原生 resume | 先实际走查现有 Admin，优先只补一个 manuscript 决定流程；如缺手改候选 admission，须归 Chapter Authority，不能让 UI 直接更新正文。完整重设计 HOLD。 |
| P2 · WP06 | **长程正文覆盖与全书诊断建议**：使用 WP02 locators/coverage，Book Follow-up 分窗口读接纳稿，跨窗口核对人物关系、promise/payoff/重叙/声线，再输出建议 | 不新增 authority。coverage 明确到文本版本和区间；只读历史、对未来提 Plan Change；全书人审/edition 未解决时 completion 继续阻断。 |
| P3 · WP07 | **授权市场观察**：一个授权来源、一个可比 cohort、时间/缺失值/证据链到选题建议 | 先取得数据/访问许可与可验证消费场景；以现有 Source/runtime job 调度，不能独立建账/排程。当前 HOLD。 |

每个包均须交付生产 consumer、失败/恢复路径及实际正文证据；原“最后才做生产实验”的独立 WP09 删除，创作验证并入每个包。WP02 不等待市场、graph、committee、UI 或 actor 新框架。无需因此新建通用 benchmark orchestrator；质量实验使用既有预算、Quality/Reader calibration 和版本化 evidence。

## E. Next Work Package — WP02 跨章正文诊断与当前章定向修订

### Scope 与 native owner

目标是让即将接纳的章节知道它与前文**实际写出的内容**是否发生无意重复、人物动机/关系断裂、声线漂移或空间/因果承接缺失，并只修复可定位的问题。先做一个生产纵向切片，不声称解决整本书。

Owner 是 **Chapter Authority**（候选与 Review/Revision lifecycle），Context Builder 负责 source isolation/预算投影，Review domain 负责诊断合同，Book Authority 提供 exact accepted input references。沿用现有 Candidate Selection、Canon grounding、Book Acceptance 和 Kernel ExternalEffect。Book Follow-up 将来复用 evidence 语义，不成为 WP02 的第二条执行路径。

初始 policy 为最近最多 2 个已接纳章节 + 当前未接纳候选；这是实验起点 `CONFIGURABLE_POLICY`，不是恒定窗口。第一章显式没有前文，不能为凑窗口引用未来稿。若章长超过冻结 token budget，要在调用前明确拒绝当前覆盖请求，或按事先批准的 excerpt policy 记录精确缺口；不把截断摘要标为完整正文。

### Production chain 与改动位置

`Book accepted input resolver → Chapter admission/frozen inputs → Context Builder → _ReviewHandler → existing review capability/PEP/ExternalEffect → normalize_review_result → existing ReviewIssue → _RevisionHandler → rereview → compare_candidates → existing release/Canon support/Book Acceptance`。

实施前复查这些现有 consumer，而不是新开 service：

1. `book_authority/production.py`、`chapter_authority/application.py` 和调度输入解析：从已接纳 cursor 取得 ordered draft version/hash；跨项目、未接纳、重复、倒序或超前引用全部拒绝。输入在 owning UoW 内冻结；不在模型调用中回查“latest”。
2. `context_builder` 与 `chapter_authority/execution_gateway.py`：将这组输入纳入 frozen Context/pack/route 的哈希及 token 预算；review 看受权正文，draft/character role 不因 review window 获得未公开世界知识。
3. `chapter_authority/provider_views.py`、`handlers.py` 和 review output contract：增加有版本的 paired-evidence review 输入/输出；继续使用原 review capability 和一个 review stage。未选择新 policy 的老 frozen contract 走兼容路径，不能静默升级旧 Attempt。
4. `review/diagnostics.py` / service 和 Revision/rereview consumer：校验当前目标 span 与前文支持 span；传递具体矛盾/重复原因、preserve 和 acceptance criteria；复用既有 issue ledger。不同证据的问题不能因 category 相同而被同一个 `code` 合并；稳定 diagnosis code 必须区分目标/来源位置并在本次 repair lineage 中保持一致。
5. Candidate Selection / Book acceptance 不改变决策权：先通过一致性/边界/保留约束，再比较候选；成本、整数计数、judge 分数和多数投票都不能自动证明修订更好。

### Contract / schema / data impact

首选现有 immutable assets 与输入 manifest，**不预设新表或 migration**。新增的是已消费的版本化内容合同（建议名须服从现有命名，不另造 Authority）：

- `review_source_window`：project/workspace/book、accepted-through、ordered source asset version/hash、chapter number、每源覆盖区间、full/excerpt 状态、窗口策略/预算版本、冻结摘要哈希。当前 target candidate 单独绑定，绝不冒充 accepted source。
- 诊断保留现有目标 `evidence`（Unicode code-point start/end/quote），附 `supporting_evidence[]`（source version、text hash、start/end/quote）。所有引用必须来自 frozen allowlist，逐字匹配；hash/offset 不符是合同失败，不能降级成“模型大概看过”。
- 保留 category、judgment_kind、violated_constraint、revision_goal、preserve、acceptance_criteria；审美偏好只允许 minor suggestion。可能的矛盾是模型判断，不新增“确定性文学真值”。
- report 明确 coverage、not-reviewed sources、不可比较/缺证据理由及窗口身份；re-review 绑定原窗口和新 target。保护点必须能定位/复核，不能只有“保留原味”口号。
- Attempt input、CapabilityPack、prompt/Skill、route/model/Provider、trace/span、model-call、usage/cost、quality gate、下游 revision/candidate 版本全部沿用现有账本。若实现发现 generic asset schema 无法维持必要 DB 约束，单独说明最小 migration 及兼容方案后按仓库 gate 实施；禁止先建冗余 window store。

### Failure / recovery / non-goals

失败的模型调用或合同校验保留此前候选，追加失败证据；不以空 issues 当成功。UNKNOWN ExternalEffect 先 reconcile；重启重用已冻结 window/receipt；accepted head 变化不得悄悄换上下文，按当前 stale/re-admission 规则创建新版本。新模型响应无有效 pair/未修复 blocker 时继续保留 open issue。关联的历史章只能作为只读证据，若问题位于已接纳稿，输出 editorial/Plan Change proposal，不能倒写。

Non-goals：全书无人值守重写；修改接纳历史；新增 Canon/Review/Memory Authority；新 scheduler；新模型路由；多 Agent committee；通用 graph/RAG 平台；固定战斗套路；作者全站改版；市场抓取；宣称已经完成独立人审或长期文学质量证明。

### Acceptance criteria 与最小必要测试

工程验收必须同时出现“输入真实到达 Provider”和“诊断被现有修订消费”，只加 DTO/fixture 不算完成：

- 一个原生 Book/Chapter 流程冻结 accepted prose window，并在 Provider request/receipt 中可核对版本与 coverage；越权/未接纳/未来引用、hash 漂移、缺失 source、预算超限均 fail closed。
- 至少一个双源可定位问题产生 ReviewIssue，真实进入 revision/rereview；current-only 修改，未涉片段/人物信息边界/原计划目标保留；新的 blocker 或 preservation failure 令 prior candidate 留存。
- 有意的回顾、角色视角误解、重复意象、尚未兑现的伏笔是负例，不因“重复”一律重写；语义不确定保留为 UNCERTAIN，不自动封锁审美选择。
- 断点/response loss/duplicate delivery 不增加重复 accepted 事实；同一冻结输入的 replay 不偷换前文章节；历史源文本字节不变。

最小聚焦测试：扩展现有 Review location/knowledge/diagnostic 单元测试（多源引用、同类不同 issue、保留检查）；Provider view/Context 测试（role 隔离、coverage 和 token 预算）；一个 Chapter PostgreSQL 纵向测试（freeze→review→revision→selection→acceptance），附一个 receipt/commit loss replay 场景。复用已覆盖的不变量，不复制所有 Kernel 测试。若修改代码、Prompt、Skill 或 wiring，`docs/development.md` 要求 focused tests 后运行 complete exact-SHA P0（含 PostgreSQL/migration/recovery）；该治理要求不是本提案自行扩大测试。不得 skip/xfail/弱化断言。

### Real creative evidence 与 Provider/budget requirement

在有明确预算的原生流程中，选用**原创或明确授权**的中文玄幻/武侠素材；最小探索集为两种情境各 3 个当前章任务：一组战斗/追逐承接与资源代价，一组人物对话/关系推进与动机，分别附实际前文。六个任务是探索设计，不是统计效力或长篇资格门槛。

每个任务冻结同一 plan、前文、人物认知和模型配置，比较 baseline review 与带窗口 review；记录所有失败和被丢弃修订，不只挑成功稿。保存实际正文、双源 issue、修订 diff、preservation 检查、接受/保留理由。至少两名独立评阅者按隐藏条件、打乱顺序比较人物行动可信度、因果连贯、可读性、关系/声线、情绪/hook 与过修；保留分歧和未改进结果，不由生成模型自己的总分决定成功。真实人工评阅尚未到位时标 `HUMAN_EDITORIAL NOT_RUN`，不让 Agent 自称人类完成。

工程 PASS 与创作收益分别报告；只在有可归因的正文改善、负例不过修、无信息边界/Canon 回归且成本可接受时，建议扩大窗口或进入 WP03。六个任务也不能证明百章稳定性；长期关系/伏笔继续追踪且标未证明部分。

所有模型调用走已接线 ProductionProviderRouter/ExternalEffect。实验开始前冻结 provider/model/reasoning、prompt/Skill/pack 版本、单次 token 上限、最多一次定向修订及 re-review 的额外调用上限、任务/全批有限预算与停止条件；评审调用也计费。先报价再申请/使用已有适用预算，不能假设 Codex CLI 免费或 entitlement 无限。当前无本实验专属预算授权，**真实 Provider 创作实验在 WP01 为 NOT_RUN**；WP02 工程实现可先完成可审查的纵向链路，但不得以 scripted PASS 结束创作验收或擅自放宽冷启动资格。

## 本包变更和验证边界

WP01 修订本提案和其机器可读审计附件，并在审阅 Provider 合并差异后刷新另外三份相关提案的失效 lifecycle baseline 与影响说明；没有发现必须在本包先修的、经复现确认的 native P0/P1，因此没有修改生产行为、schema、migration、runtime wiring、Prompt 或 Skill。外部实现的失败分支仅用于吸收决策，不在本仓库修补上游。

必要检查为 proposal lifecycle、审计引用/哈希/字段完整性、documentation governance，以及仓库 every-change `make pr-governance PR_BASE_SHA=c2ff5775f9b636ad983f8b1c77425f3bd0f9aaf4`。具体结果和 final commit 由 PR 记录，不把提交后才能得到的 SHA 写进自身形成循环。实现 identity 不变时完整 P0 按治理为 `NOT_REQUIRED / SAME_IMPLEMENTATION`，实际执行状态为 `NOT_RUN`；外部 tests、真实 Provider、PostgreSQL 业务运行、人类编辑和长篇质量实验均 `NOT_RUN`。

本工作包的完成只表示 17 个候选已得到固定版本的代码级处置、重复设计被移除、下一实施边界可审查；**不声称正文质量已经提高**。
