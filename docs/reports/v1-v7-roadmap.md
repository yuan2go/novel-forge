# Autonomous Novel OS v1-v7 Roadmap

Date: 2026-07-07

Baseline: branch `feat/v7-content-intelligence-and-longform-proof`, commit `75bb3e3`.

This roadmap translates the project blueprints into engineering phases. It does not rename the repository/package/CLI; `novel-forge` remains the codebase name. The product target is Autonomous Novel OS.

## Phase 1: 单本小说生产闭环

目标:
- Prove one local project can move through topic/world/characters/outline/chapter plan/draft/review/revision/canon update/longform recap/export.
- Produce 10-30 consecutive chapter artifacts with traceable quality records.

范围:
- Project creation and project workspace.
- WorldBible, CharacterCard, Outline, first 30 ChapterPlan assets.
- DraftChapter and DraftVersion generation.
- ReviewReport, ReviewIssue, RevisionPlan, revised draft/re-review.
- Canon/fact/timeline/foreshadow update.
- 5/10 chapter longform recap cadence.
- Export package for operator review.

当前完成度: 50%.

Current evidence:
- Core schemas and many services exist in `src/novel_forge/schemas/assets.py` and `src/novel_forge/modules/`.
- Draft/review/revision services exist.
- Context Builder, MKAOS, Agent runtime, longform stability, and quality foundations exist.
- `chapter_production_bus` now provides a single-chapter canonical contract through chapter plan, context bundle, draft, review, revision, final draft, canon/longform update, local export package, and next chapter plan.

阻塞项:
- No acceptance slice proving 10-30 chapter loop artifact coverage.
- Readable prose/page-turning/mobile gates are not first-class hard blockers.
- ApprovalRequest missing.
- Source policy lifecycle and v1 context source rules need tightening.

推荐切片:
1. Extend canonical v1 chapter loop from one chapter to 10 chapters, then 30 chapters.
2. Stage-specific ContextPackage/MKAOS contract profiles.
3. Readable Prose Gate + Golden Opening Gate + Toxic Point Gate.
4. ReviewIssue-to-RevisionPlan strategy mapping with re-review evidence.
5. Canon/timeline/foreshadow reducer and recap cadence.
6. Export package.

验收标准:
- Create one project.
- Generate/record world, characters, book outline, first 30 chapter plans.
- Generate 10-30 chapters locally.
- Each chapter has plan, context bundle, draft, review report, review issues when applicable, revision plan/draft, re-review, quality record, canon update, trace/cost record.
- Chapters are not outline-like placeholders.
- Blocking issues stop progression until revision or explicit approval.

测试策略:
- `tests.integration.test_novel_os_acceptance` expanded or paired with a v1-specific acceptance test.
- Deterministic 10-chapter and 30-chapter local tests.
- Positive/negative quality gate fixtures.
- Source leakage regression tests.
- Export package fixture.

风险:
- Over-building distant v6/v7 features while v1 remains fragmented.
- Treating UI consoles as workflow proof.
- Fallback/provider fixture proof being confused with real provider proof.

是否依赖前置阶段: no.

## Phase 2: 长篇稳定与网文追读增强

目标:
- Make the single-book loop stable over volume-length production.
- Track reader promises, pleasure points, antagonist pressure, protagonist charm, conflict ladders, and fatigue.

范围:
- CharacterState, TimelineEvent, ForeshadowItem, ReaderPromise, PleasurePoint, ConflictItem.
- Long Review Agent.
- Volume arc and quality trend.
- First 50-100 chapter deterministic/state proof.

当前完成度: 35%.

阻塞项:
- Phase 1 loop must be stable first.
- ReaderPromise and PleasurePoint are not first-class lifecycle models.
- Longform reports exist, but reducers/query/diff are uneven.

推荐切片:
- Reader Promise Ledger.
- Pleasure Point/Reward Ledger integration.
- Protagonist Charm and Antagonist Pressure reports.
- Volume review every 30 chapters.
- Longform trend dashboard backed by artifacts.

验收标准:
- System detects long-running unresolved promises.
- System detects repeated爽点/trope fatigue.
- System blocks or flags chapters that weaken core tension.
- 50-chapter deterministic proof records quality/canon/style/fatigue trends.

测试策略:
- 50-chapter deterministic proof.
- Promise/payoff fixtures.
- Character drift and antagonist pressure fixtures.

风险:
- More reports without actual progression gates.

是否依赖前置阶段: yes, Phase 1.

## Phase 3: 创意、内涵与风格增强

目标:
- Improve originality, theme depth, style identity, and anti-template capability.

范围:
- Creative Engine.
- Novelty Gate.
- Anti-Template Checker.
- Meaning / Philosophy Engine.
- Theme Engine and Anti-Preaching Gate.
- Style Identity Engine hardening.
- Trope Fatigue Detector.
- Originality Risk Engine.

当前完成度: 25%.

阻塞项:
- Theme/meaning assets are mostly implicit.
- Originality checks exist but are not a fully independent engine.
- Provider premium judge proof remains dependent on credentials and approval.

推荐切片:
- ThemeAsset and Anti-Preaching review rule.
- Style policy calibration with authorized samples only.
- Novelty/originality risk gate for topic/outline/chapter.
- Trope fatigue detector based on generated project history.

验收标准:
- Theme appears through character choice/cost, not exposition.
- Style sample raw text is never injected into generation context.
- High originality risk blocks production or requires approval.

测试策略:
- Theme anti-preaching fixtures.
- Style source isolation tests.
- Originality risk positive/negative fixtures.

风险:
- Style imitation or copyrighted structure leakage.

是否依赖前置阶段: yes, Phase 1; Phase 2 recommended.

## Phase 4: MKAOS 资产化成熟

目标:
- Make MKAOS a mature knowledge asset operating system rather than a broad RAG/content library.

范围:
- Asset Conversion Pipeline.
- Template Generator.
- Review Rule Generator.
- Eval Case Generator.
- Knowledge Usage Feedback.
- Source Isolation Regression.
- Asset Lifecycle Manager.
- Failure Taxonomy Manager.

当前完成度: 55%.

阻塞项:
- Reviewable candidates vs approved assets must remain strict.
- Usage feedback and lifecycle states are not uniformly mature.
- Full source governance lifecycle still missing.

推荐切片:
- Approved/rejected asset lifecycle.
- Knowledge usage feedback after each draft/review/revision.
- SourceEvidence standalone model or stronger embedded contract.
- Classical-Modern slow-run continuation with checkpoints only.

验收标准:
- Every approved knowledge card has source evidence, risk, method, confidence, and applicable stage.
- High-risk source-derived assets cannot enter draft context.
- Knowledge usage improves future selection and quality scoring.

测试策略:
- MKAOS query contract tests.
- Candidate-to-card gate tests.
- Source leakage regressions.
- Slow-run resume/skip tests for imports.

风险:
- Accidental raw source leakage or automatic approval.

是否依赖前置阶段: partially; can progress alongside Phase 1.

## Phase 5: 无人化资料与生产

目标:
- Move from manual/operator execution toward controlled unattended operation.

范围:
- Source Governance OS.
- Git/RSS/public domain connectors.
- Material Factory.
- Agent Scheduler complete operations.
- Cost Control.
- Approval Router.
- Security / Sandbox OS.
- Prompt Injection Guard.

当前完成度: 30%.

阻塞项:
- ApprovalRequest missing.
- Full source governance and security audit lifecycle incomplete.
- External connector sandboxing must be proven before automated imports.

推荐切片:
- ApprovalRequest and Approval Router.
- Connector permission policy.
- Prompt injection and malicious source filters.
- Scheduler production governance coverage audit.

验收标准:
- High-risk source/context/publishing actions pause for approval.
- Automated source ingestion cannot bypass source policy.
- Cost and provider budgets are enforced in production-like modes.

测试策略:
- Malicious source fixture tests.
- Scheduler fail-closed tests.
- Approval route tests.

风险:
- Unattended automation can amplify source, quality, or cost failures.

是否依赖前置阶段: yes, Phase 1 for production content; Phase 4 for source maturity.

## Phase 6: 多书并行与 Portfolio

目标:
- Support multiple books without style, memory, source, or cost contamination.

范围:
- Portfolio OS.
- Multi-Book Scheduler.
- Cross-Book Contamination Guard.
- Book Potential Scorer.
- Resource Allocation Planner.
- Book Kill / Pause Gate.
- Series / Universe Manager.
- Cost/quality dashboard.

当前完成度: 20%.

阻塞项:
- PortfolioProject, BookPotentialScore, ResourceAllocationPlan, CrossBookSimilarityReport missing.
- Phase 1 single-book loop not yet proven.

推荐切片:
- Per-book memory isolation.
- Book-level scheduler using existing Agent scheduler.
- Cost/quality dashboard by project.
- Cross-book similarity report.

验收标准:
- Two local projects run without context/memory contamination.
- Scheduler can budget and prioritize by book.
- Similarity report detects repeated premise/style/mechanism.

测试策略:
- Two-book isolation fixtures.
- Cross-book contamination tests.
- Budget allocation tests.

风险:
- Multi-book automation before single-book quality creates more low-quality output.

是否依赖前置阶段: yes, Phase 1 and Phase 5.

## Phase 7: 平台化、连载与反馈闭环

目标:
- Turn the local production system into a platform-aware serial workflow with feedback backflow.

范围:
- Platform-specific adapters.
- Serialization Engine.
- Publishing gates and receipts.
- Platform metric import.
- Comment/feedback analysis.
- Human-gated mutation proposals.
- Drop-off analyzer.
- Autonomy dashboard.
- Full regression harness.

当前完成度: 30%.

阻塞项:
- Current adapters are manual/foundation-level, not real platform SDK/callback/rate-limit integrations.
- Feedback mutation application exists as foundation but should depend on approval and impact analysis.
- Real platform accounts/APIs may require credentials and manual policy decisions.

推荐切片:
- Fanqie/Qidian manual adapters with platform rule versions.
- Receipt parser/status backfill hardening.
- Feedback mutation approval -> patch -> invalidation -> regeneration task workflow.
- Full regression suite for release/publish gates.

验收标准:
- Manual platform package includes checklist, status, receipt, and rule version.
- Feedback does not silently mutate story plans.
- Approved feedback mutation creates patch, impact analysis, invalidation, and regeneration task.

测试策略:
- Platform parser fixtures.
- Feedback approval/application/invalidation tests.
- Release gate positive/negative fixtures.

风险:
- Platform automation claims exceed actual integration.

是否依赖前置阶段: yes, Phase 1; Phase 2 recommended.

## Standard Validation Commands

Use commands that match the touched surface:

```bash
python3 -m compileall -q src/novel_forge tests scripts
python3 -m unittest tests.unit.test_schemas tests.integration.test_novel_os_acceptance
npm --prefix web/admin test
npm --prefix web/admin run lint
make test
```

For docs-only audit changes, minimum local validation is:

```bash
git diff --check
python3 -m compileall -q src/novel_forge tests scripts/import_classical_modern_to_mkaos.py
```

For production-loop slices, add focused tests covering the modified module and at least one integration/acceptance path.
