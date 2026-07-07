# Autonomous Novel OS Blueprint Gap Audit

Date: 2026-07-07

Scope: first-round engineering audit for the Autonomous Novel OS blueprint on the current `novel-forge` codebase.

Baseline observed: branch `feat/v7-content-intelligence-and-longform-proof`, last audited committed slice `6ccc1bd Add v1 single-book chapter loop contract`.

Primary evidence:
- Blueprints: `docs/blueprint/autonomous-novel-os-full-blueprint.md`, `docs/blueprint/novel-os-project-blueprint.md`
- Runtime docs: `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/README.md`, `docs/project-current-state.md`, `docs/roadmap/current-roadmap.md`
- Schemas: `src/novel_forge/schemas/assets.py`, `src/novel_forge/core/constants.py`
- Runtime modules: `src/novel_forge/modules/`, `src/novel_forge/api/routers/`, `src/novel_forge/api/services/product.py`
- UI: `web/admin/app/`
- Tests: `tests/unit/`, `tests/integration/`

## Current Engineering Judgment

The repository is a broad local-first Novel OS runtime foundation, not yet a complete Autonomous Novel OS.

The codebase already has substantial v6/v7 infrastructure: schema-backed assets, local storage, MKAOS ingestion/extraction, Context Builder, Agent contracts/runs/scheduler, workflow nodes, runtime ledger, publish/release gates, genre/style/quality/canon content intelligence, long-chain proof, publishing feedback adapters, and a large Web Admin surface.

The largest gap is orchestration depth, not raw module count. Many assets and services exist. As of 2026-07-07, the `chapter_production_bus` has a single-chapter v1 contract foundation and a 10-chapter sequence acceptance contract, but a true 10-30 chapter v1 single-book slow run is still not proven inside an acceptable runtime envelope:

```text
topic -> world -> characters -> outline -> first 30 chapter plans
-> draft -> review -> revision -> canon update -> longform recap -> export
```

Current implementation proves many slices and fixtures, including a true one-chapter bus path and a 10-chapter sequence-contract acceptance report. It does not yet prove a production-grade, repeatable true 10-30 chapter single-book run where every chapter has a chapter plan, draft, review, revision, quality record, canon update, recap/export evidence, and no bypass.

## Implemented Modules

- Schema-backed asset foundation with `BaseAsset`, `SCHEMA_CLASSES`, `ASSET_DIR_BY_TYPE`, and common validation.
- Product API routers for projects, assets, drafts, reviews, workflow nodes, agents, runtime, context, continuity, genre/style/quality, long-chain proof, publishing feedback, and OS capabilities.
- Agent runtime primitives: `agent_contract`, `agent_task`, `agent_run`, checkpoints, gates, budgets, metrics, dispatch queues, leases, retry/dead-letter, rollback/recovery, operation registry, and scheduler governance.
- MKAOS ingestion, source isolation, knowledge packs, quality, lineage, model extraction candidates, production gates, and Classical-Modern slow import controls.
- Context Builder plans/bundles, source isolation gates, MKAOS query contract helpers, RAG quality report, and context diff.
- Draft/review/revision services with MKAOS pack usage, model adapter boundaries, review issue normalization, revision tasks, re-review, and publish gate links.
- Story/continuity foundation: world bible, character cards, canon graph snapshots, KG, canon patches, longform stability assets, chapter state, fact ledger, foreshadowing graph, reward ledger, reader fatigue report.
- V7 content intelligence foundations: Genre OS, Style OS, Canon Graph plugins/state-machine assets, Quality Eval 2.0, Long-chain Proof, Content Quality Loop, publishing feedback adapters.
- Ops foundation: trace spans, model call logs, cost ledgers, budget policy, audit log, rollback, cost/quality dashboard.
- UI consoles for many runtime domains, including Agent Center, Context, MKAOS, Canon, Genre, Style, Quality, Long-chain Proof, Publishing Feedback, Project Cockpit, and Ops surfaces.

## Partially Implemented Modules

- Single-book production loop: `chapter_production_bus` now provides a one-chapter canonical contract plus a 10-chapter sequence acceptance contract; true 10-30 chapter slow acceptance and stronger quality gates are still pending.
- Source / Material Governance OS: source evidence and MKAOS import are strong, but full source registry, sync jobs, license scanner, source snapshots, and material usage lifecycle are partial.
- Story Bible / Long-form OS: many ledgers and reports exist, but typed lifecycle/query/diff semantics are uneven; some blueprint concepts are stored as report content rather than first-class models.
- Quality / Review / Eval OS: ReviewIssue, Eval Center, Quality Eval 2.0, provider judge, and gates exist, but readable-prose/page-turning/mobile gates are not yet a hard chapter-by-chapter blocker in the v1 loop.
- Portfolio OS: multi-book cockpit and cost snapshots exist, but book potential scoring, cross-book contamination, resource allocation, and kill/pause governance are early.
- Security / Sandbox OS: permissions, source isolation, provider runtime policy, and prompt/source boundaries exist; a full untrusted-source security audit log and connector sandbox lifecycle are not complete.
- Web Novel Enhancement Layer: reward/reader fatigue/platform gates exist, but protagonist charm, antagonist pressure, reader promise, pleasure point, trope fatigue, chapter economy, and mobile reading are not yet first-class blocking engines.

## Not Yet Implemented Or Not Verified As Complete

- A verified true v1 slow run that produces 10-30 consecutive readable chapters with all required artifacts and quality/canon/revision records.
- Full `SourcePolicy`, `SourceSyncJob`, `SourceSnapshot`, `LicenseCheckResult`, and `SourceRiskReport` lifecycle.
- First-class `ApprovalRequest` model and approval routing for high-risk material/context/publishing/story changes.
- Independent lifecycle models for many blueprint concepts currently represented as fields inside broad assets.
- Full typed graph state/query/diff storage for all Canon topic state machines.
- Full provider-backed premium judge and 50-chapter proof using real external credentials and operator-approved budget.
- Platform-specific production adapters beyond manual/checklist/fallback foundations.
- Full autonomous multi-book Portfolio OS.

## Architecture Debt

- `src/novel_forge/api/services/product.py`, `src/novel_forge/modules/mkaos/service.py`, and `src/novel_forge/modules/agent_scheduler/service.py` remain broad services even after previous seam extraction.
- Many schema classes are shallow `BaseAsset` subclasses with flexible `content`; this is useful for local-first evolution but weaker than the blueprint's typed lifecycle models.
- Current roadmap/docs over-emphasize v6/v7 capabilities relative to the new priority: v1 single-book production closure.
- UI surfaces are broader than proven production workflows. Pages must be treated as inspection/operation surfaces, not proof that the underlying workflow is complete.
- Storage is local JSON-first. Postgres/vector/object/graph backends are optional/foundation-level, not a production persistence plane.

## Test Gaps

- Need one slow v1 acceptance command: create project, create world/characters/outline, run 10 true chapters through the bus, and record artifact coverage without entering default unit-test runtime.
- Need 10-30 chapter local deterministic slow run with per-chapter artifact coverage and runtime summary.
- Need hard negative fixtures for source leakage into generation context at each v1 stage.
- Need readable-prose/page-turning/mobile gates with positive and negative fixtures.
- Need approval gate fixtures for high-risk material and major plot mutation.
- Need service-seam characterization tests before further splitting `product.py`, MKAOS, and scheduler.

## Documentation Drift

- `README.md`, `CLAUDE.md`, and docs still use Novel Forge v6 as the headline. That is correct for repository/package/runtime version, but insufficient for the current product target. The docs should now state: product target is Autonomous Novel OS; code package remains `novel-forge` v6 until an explicit versioning decision.
- Several reports describe V7 content intelligence completion, but the current priority is v1 single-book production closure. New control docs must redirect implementation order without denying existing V7 foundations.
- Some docs use "current", "complete", or "production" language for fixture-backed or local/mock-backed evidence. Future edits should state whether proof is deterministic/local, fixture provider, or real external provider.

## High-Risk Areas

- Copyright/source leakage: Classical-Modern and other external sources must remain evidence-only unless source policy explicitly permits context use.
- Mock/fallback confusion: local heuristic/provider fixture proof must not be reported as real provider-backed premium quality proof.
- Workflow bypass: draft/revision/release must not bypass Context Builder, MKAOS policy, Canon/KG, ReviewIssue, provider runtime guard, Evaluation Gate, Publish Gate, trace/cost ledger.
- Over-engineering: the codebase already has broad v6/v7 surfaces; the next phase must prioritize v1 chapter production closure over adding more consoles or distant P6/P7 features.

## v1 Blockers

1. Chapter Blueprint, Draft, Review, Revision, Canon Update, Longform Recap, and Export are proven for one true chapter and for a 10-chapter sequence contract, but not yet for a true 10-30 chapter slow run.
2. Readable Prose / Page-Turning / Mobile Reading gates are not yet first-class hard blockers in the v1 chapter loop.
3. ApprovalRequest and source governance lifecycle are insufficient for high-risk material and major story mutations.
4. Several blueprint data models are represented as flexible content fields rather than typed lifecycle assets.

## Gap Matrix

| 层级 | 模块 | 蓝图目标 | 当前实现 | 缺口 | 风险 | 优先级 | 推荐方案 | 涉及文件 | 测试策略 |
|---|---|---|---|---|---|---|---|---|---|
| Core OS | Agent OS | Autonomous task planning, execution, retries, approvals, trace, cost | Agent contracts/runs/tasks/scheduler/dispatch/rollback exist | Approval routing and full operation coverage still partial | Agent tasks can look complete while business loop remains unproven | P0 | Keep scheduler governance, add v1 chapter-loop operations and approval requests | `modules/agent_scheduler`, `modules/agent_runs`, `api/routers/agents.py` | Scheduler positive/negative v1 operation fixtures |
| Core OS | Source / Material Governance OS | Source registry, policy, license, risk, material usage tracking | Source docs, chunks, MKAOS ingestion, source isolation, Classical-Modern slow import | First-class SourcePolicy/SyncJob/Snapshot/License/Risk lifecycle missing | Copyright/material contamination | P0 | Add source governance lifecycle before expanding external connectors | `modules/mkaos_ingestion`, `scripts/import_classical_modern_to_mkaos.py`, `schemas/assets.py` | Source policy and leakage regression tests |
| Core OS | MKAOS | Evidence-only knowledge asset OS, stage-aware routing | Knowledge cards/packs/lineage/quality/model extraction/gates exist | Asset lifecycle and usage feedback not uniformly mature | RAG becomes ordinary context dump | P0 | Standardize MKAOS Query Contract for v1 stages | `modules/mkaos*`, `context_builder` | Query contract allow/deny fixtures |
| Core OS | Context Builder OS | Safe task-specific ContextPackage | Context plans/bundles, MKAOS contract, RAG quality, source isolation exist | Needs canonical v1 package profiles and stricter stage budgets | Token/source pollution | P0 | Add v1 stage context profiles and acceptance test | `modules/context_builder/service.py` | Stage-by-stage context bundle tests |
| Core OS | Story Bible / Long-form OS | Canon, timeline, characters, foreshadowing, promises, long review | Canon/KG/longform ledgers and recap exist | Some models are reports not typed long-lived state | Long-form drift across chapters | P0 | Build minimal v1 canon/timeline/foreshadow reducer and cadence | `modules/longform_stability`, `modules/canon_graph`, `modules/longform_recap` | 10-30 chapter state continuity fixture |
| Core OS | Quality / Review / Eval OS | Blocking review/eval gates | ReviewIssue, ReviewReport, Eval, Quality Eval 2.0, content quality loop exist | Readability/page-turning/mobile gates not hard v1 blockers | Low-quality chapters advance | P0 | Make post-draft and post-revision quality loop mandatory in v1 | `modules/review`, `modules/quality_eval`, `modules/content_quality_loop` | Positive/negative chapter quality gate fixtures |
| Core OS | Ops / Trace / Cost OS | OSEnvelope, trace, model log, cost, metrics | Runtime ledger, trace span, cost ledger, budget policy, dashboards exist | OSEnvelope is not yet a standalone blueprint-named asset | Hard to audit bypasses | P0 | Keep runtime envelope policy and add v1 acceptance trace assertions | `modules/runtime_ledger`, `modules/runtime_policy` | Trace/cost presence in v1 run |
| Core OS | Portfolio OS | Multi-book portfolio, scoring, allocation, contamination | Multi-book cockpit and cost snapshots foundation exist | Book scoring/allocation/contamination lifecycle missing | Premature P6 complexity | P3 | Defer; preserve project isolation boundaries | `modules/novel_os_cockpit`, `api/routers/os_capabilities.py` | Later multi-book scheduler tests |
| Core OS | Security / Sandbox OS | Untrusted source and tool sandbox | Permission center, provider policy, source isolation, audit log exist | Full connector sandbox/security audit not complete | Prompt injection and unsafe sources | P1 | Add prompt/source risk audit before automated connectors | `modules/permission_center`, `modules/tool_gateway`, `modules/audit_log` | Malicious source fixture tests |
| Engine | Worldbuilding Engine | Produce world rules and gates | `WorldBible`, platform/genre support, continuity assets exist | World rules/factions/resources not all typed | Weak settings cause later drift | P1 | Tie world bible to v1 outline/chapter context | `schemas/assets.py`, `modules/continuity_graph` | World rule context/gate tests |
| Engine | Character Engine | Character profiles, states, arcs, voice | `CharacterCard`, `CharacterStateLedger`, arc and KG support | Voice/relationship lifecycle partial | Characters become decorative | P1 | Add minimal v1 character state and voice checks | `modules/longform_stability`, `modules/novel_kg` | Character drift fixtures |
| Engine | Outline Engine | Book/volume arcs, foreshadow plan | `Outline`, `OutlineVersion`, `LongFormMacroPlan` exist | v1 outline-to-30-chapter proof missing | Outline disconnected from drafts | P0 | Create canonical outline-to-chapter-plan slice | `modules/production_chain`, `modules/long_planning` | Outline/chapter plan chain test |
| Engine | Chapter Blueprint Engine | Scene beats, conflict, info release, hook, emotion curve | `ChapterPlan`, versioning, workflow assets, one-chapter production bus contract, and 10-chapter sequence acceptance contract exist | SceneBeat etc mostly content fields, not standalone lifecycle; true 10-30 chapter slow run pending | Thin plans create thin prose | P0 | Strengthen chapter plan schema conventions and gates while optimizing slow acceptance runtime | `schemas/assets.py`, `modules/chapter_production_bus`, `modules/production_chain` | Chapter plan quality fixtures plus slow sequence acceptance |
| Engine | Readable Prose Engine | Readable, page-turning prose gates | Drafting, style, content quality loop, quality eval exist | Not yet a distinct hard engine in v1 | AI-like or summary-like chapters | P0 | Implement v1 readable-prose gate over DraftChapter | `modules/drafting`, `modules/content_quality_loop` | Bad/good prose fixtures |
| Engine | Revision Engine | Issue-type strategy and re-review | Revision tasks/plans, rework loop, re-review links exist | Needs stronger strategy coverage and diff evidence | Revisions may be cosmetic | P0 | Tie ReviewIssue types to RevisionPlan strategy and re-review | `modules/revision/service.py` | Revision improves gate fixture |
| Engine | Feedback Analysis Engine | Reader feedback to human-gated mutation | Feedback adapters/backflow/mutation application exist | Real embedding/sentiment/drop-off evidence partial | Feedback over-applied or ignored | P2 | Keep human approval; add evidence chain later | `modules/publishing_feedback_adapters`, `modules/feedback` | Approval/apply/invalidate tests |
| Engine | Publishing Adapter Engine | Manual/real platform packages and status | Manual packages, receipt parser, platform gates exist | Real platform SDK/callback/rate limits not bound | False automation claims | P2 | Keep manual adapters, add platform rule versions | `modules/publishing_feedback_adapters`, `modules/publishing` | Fanqie/Qidian parser fixtures |
| Engine | Style Identity Engine | Style policy, drift and rewrite tasks | Style OS exists | Authorized sample lifecycle and deep drift calibration still partial | Style imitation or drift | P1 | Harden rights/source isolation and v1 style gate | `modules/style_os` | Style sample leakage tests |
| Enhancement | Golden Opening Lab | Opening hook and first 300-800 chars gate | Quality Eval opening reports and platform opening gates exist | Not a v1 hard gate yet | Weak start reduces追读 | P0 | Add opening gate to chapter 1-3 v1 loop | `modules/quality_eval`, `modules/platform_strategy` | Opening positive/negative fixtures |
| Enhancement | Reader Promise Ledger | Track promises and payoff | Blueprint docs; related reward/foreshadow assets exist | No first-class ReaderPromise asset | Unpaid promises | P1 | Add promise ledger after v1 basic loop | `schemas/assets.py`, `longform_stability` | Promise/payoff test |
| Enhancement | Pleasure Point Ledger | Manage爽点 cadence | `RewardLedger` foundation | Not tied to chapter economy | Flat chapters | P1 | Use RewardLedger in chapter quality loop | `modules/longform_stability` | Reward cadence fixtures |
| Enhancement | Toxic Point & Drop-off Engine | Detect毒点 and drop-off | Feedback clusters/dropoff reports and quality issues exist | Needs v1 toxicity gate and real feedback analysis | Reader churn | P1 | Add deterministic toxic-point review rules | `modules/feedback`, `quality_eval` | Toxic point fixtures |
| Tool | Public Domain Importer | Evidence-only source import | Classical-Modern importer with slow-run/checkpoint/report | Full provider extraction intentionally not complete | Token/source leakage if abused | P1 | Continue slow auditable batches only | `scripts/import_classical_modern_to_mkaos.py` | Slow-run/resume tests |
| Tool | Exporter | Export final chapters/packages | Draft export and publishing package foundations exist | v1 export artifact not in canonical loop | Hard to inspect production output | P0 | Add v1 export package as final slice | `api/routers/drafts.py`, `modules/publishing` | Export package fixture |

## Next Stage Recommendation

Do not add another broad V7 surface first. The next production slice should be:

```text
V1 canonical true 10-chapter slow acceptance:
run the existing chapter_production_bus path repeatedly so every chapter has
ChapterPlan -> ContextBundle -> DraftChapter -> ReviewReport/ReviewIssue
-> RevisionPlan/RevisionDraft -> Canon/Longform update -> Export package
with runtime/asset-count reporting, and then prove the same path for 30 chapters.
```

The slice should run locally without real external provider credentials, with explicit provider-backed opt-in paths and no source leakage.
