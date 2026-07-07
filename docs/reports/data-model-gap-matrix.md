# Autonomous Novel OS Data Model Gap Matrix

Date: 2026-07-07

Baseline: branch `feat/v7-content-intelligence-and-longform-proof`, commit `75bb3e3`.

Primary schema evidence:
- `src/novel_forge/schemas/assets.py`
- `src/novel_forge/core/constants.py`
- Supporting services under `src/novel_forge/modules/`

Status legend:
- `yes`: first-class schema asset exists.
- `partial`: represented by a nearby asset or content fields, but not a full standalone lifecycle model.
- `no`: not found as a schema-backed model in current code scan.

## Matrix

| 数据模型 | 蓝图用途 | 当前是否存在 | 当前实现位置 | 缺失字段 | 生命周期状态 | 关联模块 | 优先级 |
|---|---|---|---|---|---|---|---|
| Source | 外部/内部来源登记 | partial | `SourceDocument`, importer metadata, Source Governance assets | source snapshot diff, sync refresh state, usage feedback | evidence asset plus governance foundation | MKAOS ingestion, source governance | P0 |
| SourcePolicy | 来源使用规则 | yes-foundation | `SourcePolicy`, `modules/source_intake/service.py` | connector-level expiry/renewal policy, per-stage budget | create/evaluate asset lifecycle | Context Builder, MKAOS | P0 |
| SourceSyncJob | 来源同步任务 | yes-foundation | `SourceSyncJob`, `modules/source_intake/service.py` | schedule runner, cursor retry execution, connector adapter binding | planned/checkpoint asset lifecycle | Source Governance OS | P2 |
| SourceSnapshot | 来源快照 | yes-foundation | `SourceSnapshot`, `modules/source_intake/service.py` | snapshot diff and retention policy | evidence-only snapshot asset | Source Governance OS | P2 |
| LicenseCheckResult | 许可检查结果 | yes-foundation | `LicenseCheckResult`, `modules/source_intake/service.py` | expiry/renewal and legal reviewer workflow | create asset lifecycle | Source Governance OS | P0 |
| SourceRiskReport | 来源风险报告 | yes-foundation | `SourceRiskReport`, `modules/source_intake/service.py` | Context Builder/MKAOS caller migration and recurring risk refresh | R0-R4 report asset lifecycle | MKAOS, Context Builder | P0 |
| RawDocument | 原始文档 | partial | `SourceDocument` | raw/document distinction, storage boundary | basic asset | MKAOS ingestion | P1 |
| CleanDocument | 清洗后文档 | yes | `CleanedText` | stronger provenance spans | basic asset | Analysis, MKAOS | P1 |
| DocumentChunk | 切片 | yes | `SourceChunk`, `KnowledgeChunk`, `MemoryChunk` | chunk policy, leakage flags | usable | RAG, MKAOS | P1 |
| ExtractionResult | 抽取结果 | partial | MKAOS model extraction candidates/reports | unified accepted/rejected lifecycle | embedded/report | MKAOS model extraction | P0 |
| DedupRecord | 去重记录 | no | duplicate helpers exist in services | content hash registry, duplicate reason | missing | Source/material ingestion | P1 |
| MaterialCard | 素材卡 | yes | `MaterialCard` | usage lifecycle and risk flags can deepen | basic asset | Material/MKAOS | P0 |
| MaterialTag | 素材标签 | partial | asset tags/content fields | controlled taxonomy | embedded | MKAOS, assets | P2 |
| MaterialFunction | 素材功能 | partial | content fields | stage/function enum | embedded | MKAOS | P1 |
| MaterialRisk | 素材风险 | partial | risk fields/gates | standalone risk report | embedded | Source Governance, MKAOS | P0 |
| MaterialUsage | 素材使用追踪 | partial | `KnowledgeUsageEvent`, `KnowledgeUsageBinding` | material-specific usage ledger | nearby asset | MKAOS, Context Builder | P1 |
| KnowledgeAsset | 知识资产 | yes | `KnowledgeCard` | lifecycle states can deepen | usable | MKAOS | P0 |
| CreativePrinciple | 创作原则 | partial | `RuleCard`, `KnowledgeCard` | standalone principle type | embedded | MKAOS, Review | P2 |
| NarrativeMechanism | 叙事机制 | partial | `NarrativePattern`, `CommercialPattern` | lifecycle and usage feedback | basic asset | Analysis, MKAOS | P1 |
| TemplateAsset | 模板资产 | yes | `TemplateCard`, `WritingTemplate`, `CraftTemplate` | approval/versioning | basic asset | MKAOS, creation | P1 |
| ReviewRule | 审稿规则 | partial | `RuleCard`, `ReviewRulePack`, `StyleReviewRule` | rule execution lifecycle | usable pack | Review/Eval | P0 |
| EvalCase | 评测用例 | yes | `EvaluationCase` | generation linkage and golden-set status | usable | Eval Center | P1 |
| SourceEvidence | 来源证据 | partial | source refs/evidence fields across assets | standalone evidence span model | embedded | All source-derived assets | P0 |
| ContextPackage | Agent 上下文包 | yes as `ContextBundle` | `ContextBundle`, `ContextBuildPlan`, `stage-context-profile-v1` bundle contract | blueprint name differs; final full-loop profile assertions still pending | usable with stage contract | Context Builder | P0 |
| NovelProject | 小说项目 | partial | `ProjectWorkspaceState`, project API records | full project lifecycle, genre/platform/readers | usable foundation | Projects, Product API | P0 |
| GenreProfile | 题材画像 | yes | `GenreProfile`, `GenreMarketProfile` | lifecycle/versioning | usable | Genre OS | P1 |
| PlatformProfile | 平台画像 | yes | `PlatformProfile` | platform-specific rules can deepen | usable | Platform Strategy | P1 |
| ReaderProfile | 读者画像 | partial | `ReaderSentimentReport`, `ReaderSimulationReport` | reader segment profile | embedded/report | Feedback, Reader simulation | P2 |
| WorldBible | 世界观圣经 | yes | `WorldBible` | typed child models | usable | Worldbuilding, Context | P0 |
| WorldRule | 世界规则 | partial | `WorldBible`, `PowerScaleRule` | standalone rule state/diff | embedded/basic | Worldbuilding, Canon | P1 |
| PowerRule | 战力/能力规则 | yes | `PowerScaleRule`, Canon plugin state | resource economy/breakthrough typed graph | partial | Canon Graph, Genre | P1 |
| FactionProfile | 势力档案 | partial | canon graph reports, world bible content | standalone faction model | embedded/report | Historical/faction canon | P1 |
| LocationProfile | 地点档案 | partial | world bible/canon content | location lifecycle and map refs | embedded | Worldbuilding | P2 |
| ResourceRule | 资源规则 | partial | canon plugin/PowerScale content | resource flow ledger | embedded | Genre/Canon | P1 |
| CharacterProfile | 人物档案 | yes as `CharacterCard` | `CharacterCard` | state/voice separation | usable | Character Engine | P0 |
| CharacterState | 人物状态 | yes | `CharacterStateLedger`, `ChapterStatePackage` | query/update reducer | usable foundation | Long-form OS | P0 |
| CharacterArc | 人物弧光 | partial | `ArcPlan`, CharacterCard fields | standalone arc state | partial | Outline/Long-form | P1 |
| ProtagonistCharmReport | 主角魅力/能动性报告 | yes-foundation | `ProtagonistCharmReport`, `modules/character_pressure/service.py`, quality loop, longform reducer | provider/human calibration and guided repair UI | create/report gate lifecycle with ReviewIssue/RevisionTask hook | Character Engine, Web Novel Enhancement, Review | P1 |
| AntagonistPressureReport | 反派/外部压迫报告 | yes-foundation | `AntagonistPressureReport`, `modules/character_pressure/service.py`, VillainOperationPlan evidence, quality loop, longform reducer | provider/human calibration and guided repair UI | create/report gate lifecycle with ReviewIssue/RevisionTask hook | Character Engine, Web Novel Enhancement, Review | P1 |
| RelationshipEdge | 关系边 | partial | Novel KG edges/content | typed relationship state machine | partial | Novel KG, Canon | P1 |
| VoiceProfile | 口吻档案 | partial | `StyleProfile`, character fields | per-character voice model | embedded | Style/Character | P1 |
| CanonFact | 正史事实 | partial | `FactLedger`, `CanonDatabase`, v1 `canon_state_machine_ledger` projection | confidence/span can deepen | reducer-backed foundation | Canon/Long-form | P0 |
| TimelineEvent | 时间线事件 | partial | `FactLedger`, chapter state, `TimelineEventReducer` projection in CanonGraph state-machine assets | first-class timeline event asset | reducer-backed embedded | Long-form OS | P0 |
| ForeshadowItem | 伏笔项 | yes | `ForeshadowingThread`, `ForeshadowingGraph`, `ForeshadowingReducer` projection | payoff SLA/status transitions can deepen | reducer-backed foundation | Long-form OS | P0 |
| ReaderPromise | 读者承诺 | yes-foundation | `ReaderPromise`, `ReaderPromiseLedger`, `modules/reader_promise/service.py`, longform reducer `ReaderPromiseReducer` | provider/human payoff calibration, richer promise taxonomy, cockpit repair workflow depth | create/evaluate ledger lifecycle with ReviewIssue/RevisionTask hook | Web Novel Enhancement, Long-form OS, Review | P1 |
| PleasurePoint | 爽点 | yes-foundation | `PleasurePoint`, `ChapterEconomyReport`, `RewardLedger`, `modules/chapter_economy/service.py`, longform reducer `ChapterEconomyReducer` | provider/human calibration, richer taxonomy, UI repair workflow | create/report gate lifecycle with ReviewIssue/RevisionTask hook | Web Novel Enhancement, Quality, Long-form OS | P1 |
| ConflictItem | 冲突项 | partial | `ConflictPattern`, chapter plan content | active conflict lifecycle | embedded/basic | Outline/Chapter | P1 |
| EventLog | 事件日志 | partial | `AuditLog`, `TraceSpan`, `StateEvent` | business event taxonomy | usable nearby | Ops/State Bus | P1 |
| BookOutline | 整本大纲 | yes | `Outline`, `OutlineVersion` | validation against v1 goals | usable | Outline Engine | P0 |
| VolumeOutline | 分卷大纲 | partial | `LongFormMacroPlan`, `ArcPlan` | standalone volume outline | partial | Long-form OS | P1 |
| MainArc | 主线弧 | partial | `ArcPlan`, outline content | typed arc status | partial | Outline/Long-form | P1 |
| SubArc | 支线弧 | partial | `ArcPlan`, outline content | typed arc status | partial | Outline/Long-form | P1 |
| ThemeArc | 主题弧 | partial | outline/quality fields | standalone theme arc | embedded | Meaning Engine | P3 |
| ConflictLadder | 冲突阶梯 | partial | outline/chapter content | escalation model | embedded | Outline/Chapter | P1 |
| ClimaxMap | 高潮图 | partial | outline content | payoff/climax model | embedded | Outline | P2 |
| ForeshadowPlan | 伏笔计划 | partial | `ForeshadowingThread`, outline content | plan vs actual diff | partial | Outline/Long-form | P1 |
| ChapterBlueprint | 章节细纲 | yes as `ChapterPlan` | `ChapterPlan`, `ChapterPlanVersion`, `chapter-blueprint-contract-v1` | standalone ChapterBlueprint asset not required for v1; final workflow assertions pending | usable with embedded contract | Chapter Blueprint | P0 |
| SceneBeat | 场景节拍 | partial | `ChapterPlan.content.scene_beats`, `DraftChapter.content.chapter_plan_blueprint` | standalone beat schema/lifecycle | embedded contract | Chapter Blueprint | P0 |
| ConflictBeat | 冲突节拍 | partial | `ChapterPlan.content.conflict_beats` | standalone beat schema/lifecycle | embedded contract | Chapter Blueprint | P0 |
| InfoReleasePoint | 信息释放点 | partial | `ChapterPlan.content.info_release_points` | standalone release model | embedded contract | Chapter Blueprint | P1 |
| HookPlan | 钩子计划 | partial | `ChapterPlan.content.hook_plan`, platform gates | hook type/payoff state lifecycle | embedded contract | Chapter Blueprint | P0 |
| EmotionCurve | 情绪曲线 | yes | `EmotionCurve` analysis asset, `ChapterPlan.content.emotion_curve` | production curve lifecycle and trend binding | partial | Analysis/Chapter | P1 |
| ChapterDraft | 章节正文 | yes | `DraftChapter`, `DraftVersion` | v1 loop coverage | usable | Drafting | P0 |
| SceneDraft | 场景正文 | partial | DraftChapter content | scene-level draft model | embedded | Drafting | P2 |
| DialoguePass | 对话专项稿 | no | Not found | pass type, diff, review | missing | Revision/Style | P2 |
| StyleProfile | 风格档案 | yes | `StyleProfile`, Style OS assets | authorized sample lifecycle | usable | Style OS | P1 |
| ReadabilityReport | 可读性报告 | partial as `quality_score_report` | `readable-prose-gate-v1` writes `QualityScoreReport`, ReviewIssue, RevisionTask | standalone readability asset and calibration set | usable embedded report | Quality/Readable Prose | P0 |
| AntiAIReport | AI 味报告 | partial | review/quality fields | standalone anti-AI metrics | embedded | Quality/Revision | P0 |
| PageTurningReport | 追读报告 | partial | `Opening3Report`, platform retention risk | standalone page-turning gate | embedded/report | Quality/Web Novel | P0 |
| MobileReadingReport | 移动阅读报告 | no | Not found | paragraph rhythm, mobile scan metrics | missing | Quality/Web Novel | P1 |
| ReviewReport | 审稿报告 | yes | `ReviewReport` | v1 hard-block coverage | usable | Review | P0 |
| ReviewIssue | 审稿问题 | yes | `ReviewIssue`, `review-issue-revision-strategy-v1` candidate contract | issue taxonomy can keep expanding with new gates | usable | Review/Revision/Gates | P0 |
| RevisionPlan | 修订计划 | yes | `RevisionPlan` now carries `revision_strategy_plan`, `required_output_evidence`, and `re_review_focus` | real improvement metrics and provider/human calibration | usable | Revision | P0 |
| RevisionDraft | 修订稿 | partial | `DraftVersion`, `EditorPatch` | standalone revised draft asset | partial | Revision/Editor | P0 |
| RevisionDiff | 修订差异 | yes | `DraftDiffReport`, `EditorPatch` | issue-to-diff verification against strategy ids | usable | Revision/Editor | P1 |
| PortfolioProject | 项目组合项 | no | Not found | portfolio metadata/lifecycle | missing | Portfolio OS | P3 |
| BookPotentialScore | 单书潜力评分 | no | Not found | scoring dimensions/evidence | missing | Portfolio OS | P3 |
| ResourceAllocationPlan | 资源分配计划 | no | Not found | capacity/budget/priority | missing | Portfolio OS | P3 |
| CrossBookSimilarityReport | 跨书相似报告 | no | Not found | similarity vectors/evidence | missing | Portfolio OS | P3 |
| AgentTask | Agent 任务 | yes | `AgentTask` | business v1 task coverage | usable | Agent OS | P0 |
| AgentRun | Agent 运行 | yes | `AgentRun` | provider hard-stop coverage per op | usable | Agent OS | P0 |
| TaskPlan | 任务计划 | partial | `WorkflowDefinition`, `LoopRun`, task DAG | standalone plan model | partial | Workflow/Agent | P1 |
| TaskDependency | 任务依赖 | partial | workflow DAG/dependencies | first-class dependency asset | embedded | Workflow/Agent | P1 |
| TaskFailure | 任务失败 | yes | `AgentFailureReport`, `TaskDeadLetter` | recovery taxonomy can deepen | usable | Agent Scheduler | P0 |
| ApprovalRequest | 人工审批 | yes foundation | `ApprovalRequest`, `modules/permission_center/service.py`, `/product/permission-center/approval-requests` | caller migration and deeper approval router policies | usable foundation | Agent/Security/Publishing | P0 |
| OSEnvelope | OS 执行信封 | partial | runtime policy/envelope dicts, trace/cost assets | standalone schema asset | embedded | Runtime Governance | P0 |
| TraceLog | 追踪日志 | yes as `TraceSpan` | `TraceSpan` | cross-artifact query helpers | usable | Runtime Ledger | P0 |
| CostLog | 成本日志 | yes as `CostLedger` | `CostLedger`, cost snapshots | provider billing calibration | usable | Runtime Ledger | P1 |
| QualityMetric | 质量指标 | yes | `QualityScoreReport`, `EvaluationMetric`, trend assets | unified quality metric registry | usable foundation | Quality/Eval | P1 |
| RegressionReport | 回归报告 | yes | `EvaluationRegressionReport`, `QualityRegressionReport` | v1 golden set baseline | usable foundation | Eval Center | P1 |
| FailureCase | 失败案例 | partial | `AgentFailureReport`, `TaskDeadLetter`, eval failures | reusable failure taxonomy | partial | Agent/Eval | P1 |
| SecurityAuditLog | 安全审计日志 | partial | `AuditLog`, permission/tool logs | security-specific schema | partial | Security/Sandbox | P1 |

## Immediate Data-Model Priorities For v1

1. `OSEnvelope` or a documented runtime envelope schema contract: needed to prove every v1 step is governed.
2. ApprovalRequest caller migration: publish/context/source/story mutation callers should record `approval_request` refs instead of local approval notes only.
3. MobileReadingReport or equivalent lifecycle: needed next so mobile scanability is not only a field inside readable prose checks.
4. Readable prose/page-turning/mobile review models: needed after `chapter-blueprint-contract-v1` so draft quality is not limited by thin prose gates.
5. `PageTurningReport` / `AntiAIReport` calibration: readable prose now has an embedded gate; dedicated reports can deepen provider/human calibration later.
6. `ReaderPromise`, `ChapterEconomyReport`, `ProtagonistCharmReport`, and `AntagonistPressureReport` calibration and cockpit depth: foundations exist, but detection remains local/deterministic and still needs provider/human calibration plus final 10-30 chapter proof.

## Notes

- The current schema layer intentionally supports many asset types as light `BaseAsset` subclasses. This is useful for rapid local-first evolution, but the Autonomous Novel OS blueprint requires lifecycle-rich models for core OS modules.
- The next production slice should avoid a broad schema rewrite. Prefer adding the minimum first-class lifecycle models that unblock v1 acceptance, then migrate flexible content fields gradually.
