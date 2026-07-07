# Autonomous Novel OS Next Production Slices

Date: 2026-07-07

Ordering principle: prioritize v1 single-book production closure before broader platform, multi-book, or fully autonomous features.

Implementation status note:
- 2026-07-07: `V1-S1 Canonical Single-Book Loop Contract` has a single-chapter foundation in `src/novel_forge/modules/chapter_production_bus/service.py`. The bus now runs through chapter plan, context bundle, draft, review, revision, final draft, canon/longform update, local export package, and next chapter plan. This does not yet prove the 10-30 chapter v1 acceptance run.

| 切片 | 目标 | 为什么优先 | 涉及模块 | 涉及数据模型 | 涉及 API / Service | 测试 | 文档 | 风险 |
|---|---|---|---|---|---|---|---|---|
| V1-S1 Canonical Single-Book Loop Contract | Define one canonical local workflow for topic/world/character/outline/chapter-plan/draft/review/revision/canon/recap/export | Current services exist but the mainline is fragmented | Production Chain, Workflow Nodes, Agent Scheduler, Context Builder, Drafting, Review, Revision, Longform | ProjectWorkspaceState, Outline, ChapterPlan, ContextBundle, DraftChapter, ReviewReport, ReviewIssue, RevisionPlan, CanonDatabase, LongformRecapReport | Implemented single-chapter foundation in `chapter_production_bus`; still needs 10-30 chapter acceptance | One deterministic end-to-end acceptance test for one chapter exists in `tests/unit/test_context_and_production_chain.py` | Update architecture and roadmap docs | Could duplicate existing paths if not carefully routed; continue extending this bus instead |
| V1-S2 Stage Context Profiles | Make Context Builder produce stage-specific packages for topic/world/outline/chapter/review/revision | Prevents source leakage and inconsistent context | Context Builder, MKAOS, Production Context | ContextBuildPlan, ContextBundle, KnowledgePack, SourceEvidence | Context profile helper and policy checks | Positive/negative source isolation tests | Context Builder docs | Over-tight policy can block useful local workflows |
| V1-S3 Chapter Blueprint Deepening | Ensure ChapterPlan contains scene goal, conflict, hook, emotion, info release, payoff target | Thin plans create outline-like prose | Chapter Blueprint, Outline, Quality | ChapterPlan, SceneBeat fields, ConflictBeat fields, HookPlan fields | ChapterPlan validation/service helpers | Good/bad chapter plan fixtures | Creation pipeline docs | Avoid massive schema rewrite |
| V1-S4 Readable Prose Gate | Turn readable-prose goals into blocking ReviewIssue sources | v1 requires chapters that are readable, not just generated | Drafting, Content Quality Loop, Review, Quality Eval | DraftChapter, ReviewIssue, QualityScoreReport, ReadabilityReport-equivalent | Gate function after draft/revision | Good/bad prose fixtures; first 300 chars no-event fixture | Quality docs | Heuristic may be noisy; keep explainable |
| V1-S5 ReviewIssue to Revision Strategy | Map issue types to revision strategies and require re-review evidence | Revision must improve quality, not only create a new asset | Review, Revision, Editor, Loop Kernel | ReviewIssue, RevisionTask, RevisionPlan, DraftDiffReport | Revision service strategy map | Failing issue -> revision -> re-review passes fixture | Review/Revision docs | Strategy overfit if too rigid |
| V1-S6 Canon/Timeline/Foreshadow Reducer | Update continuity state after every accepted chapter | Long-form stability depends on persistent state | Canon Graph, Novel KG, Longform Stability | CanonFact, TimelineEvent, ForeshadowItem, FactLedger, CanonStateMachineSnapshot | Reducer/update service | 10-chapter continuity update test | Story Bible docs | Need avoid parallel canon systems |
| V1-S7 Longform Recap Cadence | Trigger light recap every 5 chapters and formal recap every 10 | v1 acceptance requires longform review, not just isolated chapters | Longform Recap, Agent Scheduler, Workflow Nodes | LongformRecapReport, ChapterStatePackage, QualityTrend | Scheduler/workflow cadence operation | 10-chapter recap cadence fixture | Longform docs | Cadence must be configurable later |
| V1-S8 Exportable Chapter Package | Produce reviewable/exportable local package after revised chapter acceptance | Makes v1 output inspectable and usable | Drafts, Publishing, Exporter | DraftChapter, DraftVersion, PublishingPlan, PublishingLog, ReleasePackage-lite | Product API export service | Export package fixture | Engineering/export docs | Do not imply platform auto-publish |
| V1-S9 ApprovalRequest Foundation | Add human gate model for high-risk sources, context, publish, major plot mutation | Required for safe autonomy and source governance | Agent OS, Source Governance, Publishing, Feedback | ApprovalRequest, SourcePolicy, ReviewIssue | Approval service/API minimal foundation | Approve/reject/expired fixtures | Agent/security docs | Needs clear non-blocking local mode |
| V1-S10 v1 Acceptance Dashboard Data | Expose real artifact coverage for one project | UI must show workflow truth, not static completion | Product API, Novel OS Cockpit, Metrics | ProjectMetricSnapshot, QualityMetric, TraceSpan, CostLedger | Cockpit data aggregation | API route tests | UI docs | Avoid UI-only proof |
| P1-S1 Source Governance Lifecycle | Add SourcePolicy, SourceRiskReport, license check result lifecycle | External corpora and MKAOS need stronger boundaries | Source Governance, MKAOS, Context Builder | SourcePolicy, LicenseCheckResult, SourceRiskReport, SourceEvidence | Source policy service/API | Source policy gate tests | Source governance docs | Too much ceremony can slow local use |
| P1-S2 Reader Promise Ledger | Track promise/payoff lifecycle | Needed for追读 and longform stability | Longform, Web Novel Enhancement, Review | ReaderPromise, ForeshadowItem, ReviewIssue | Promise ledger service | Broken promise fixtures | Longform docs | Requires good chapter annotations |
| P1-S3 Pleasure Point / Chapter Economy Gate | Track爽点 cadence and scene value | Prevents flat or watery chapters | Reward Ledger, Quality, Chapter Blueprint | PleasurePoint, RewardLedger, ConflictItem | Quality loop extension | Cadence and water-chapter fixtures | Quality docs | Heuristic false positives |
| P1-S4 Character Charm and Antagonist Pressure | Score protagonist agency and villain pressure | Core web novel quality lever | Character, Longform, Review | CharacterState, VillainOperationPlan, QualityMetric | Review/longform report extension | Charm/pressure fixtures | Character docs | Subjective metrics need calibration |
| P1-S5 Mobile Reading Gate | Check paragraph rhythm and mobile scanability | Web novel reading happens on mobile | Readable Prose, Quality | MobileReadingReport-equivalent, ReviewIssue | Quality gate extension | Mobile paragraph fixtures | Quality docs | Avoid overfitting one platform |
| P1-S6 Provider Proof Harness | Separate real provider proof from fixture/local proof | Prevents false production claims | Model Router, Quality Eval, Runtime Ledger | ModelRouteResolution, ExternalProviderProofReport, ModelJudgeResult | Provider proof runner/API | Provider unavailable fallback; real-provider opt-in | Ops/provider docs | Requires credentials/budget approval |
| P2-S1 Platform-Specific Manual Adapters | Harden Fanqie/Qidian manual package/checklist/receipt | Useful after export and publish gate | Publishing Feedback Adapters | PlatformUploadPackage, PlatformPublishReceipt, PlatformReviewStatus | Adapter service/API | Receipt parser fixtures | Publishing docs | Real APIs remain out of scope |
| P2-S2 Feedback Mutation Apply Workflow | Approval -> patch -> invalidation -> regeneration task | Closes feedback loop safely | Feedback, Workflow, Change Impact, Agent Scheduler | FeedbackPlanMutationProposal, FeedbackMutationPatch, ChangeImpactReport, AgentTask | Workflow processor | Approval/apply/invalidate tests | Feedback docs | Must not silently mutate story |
| P3-S1 Portfolio Project Model | Introduce multi-book project portfolio boundary | Needed before multi-book scheduling | Portfolio, Project, Cost Dashboard | PortfolioProject, BookPotentialScore, ResourceAllocationPlan | Portfolio service/API | Two-book isolation fixture | Portfolio docs | Do not distract from v1 |
| P3-S2 Cross-Book Similarity Guard | Detect repeated style/premise/mechanism | Prevents multi-book sameness | Portfolio, Style, Genre, MKAOS | CrossBookSimilarityReport, StyleProfile, GenreProfile | Similarity service | Similar/different book fixtures | Portfolio docs | Needs corpus and embeddings later |

## Recommended Next Slice

Continue from `V1-S1 Canonical Single-Book Loop Contract`.

The single-chapter foundation now exists. Next acceptance should extend the same path, not a new path:

```text
10 local chapters
each with chapter plan, context bundle, draft, review, revision/final draft,
canon/longform update, export package, and traceable output paths
```

After 10 chapters pass, extend the same path to 30 chapters.
