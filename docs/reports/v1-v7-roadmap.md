# Autonomous Novel OS v1-v7 Roadmap

Date: 2026-07-07

Baseline: branch `feat/v7-content-intelligence-and-longform-proof`, last audited committed slice `6ccc1bd`.

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

当前完成度: 60%.

Current evidence:
- Core schemas and many services exist in `src/novel_forge/schemas/assets.py` and `src/novel_forge/modules/`.
- Draft/review/revision services exist.
- Context Builder, MKAOS, Agent runtime, longform stability, and quality foundations exist.
- `chapter_production_bus` now provides a single-chapter canonical contract through chapter plan, context bundle, draft, review, revision, final draft, canon/longform update, local export package, and next chapter plan.
- `run_chapter_production_sequence()` adds a 10-chapter sequence contract and writes a strict `long_chain_acceptance_report` over required V1 artifact paths.
- `production_context` project-safe reference indexing now updates incrementally so repeated chapter runs do not rescan unchanged project assets.
- `scripts/run_v1_chapter_sequence_acceptance.py` ran the true 10-chapter local slow acceptance successfully: 10/10 chapters, 1460.716s, 7,615 asset writes/updates, report `docs/reports/v1-chapter-sequence-slow-acceptance.md`.
- Development after that baseline added compact sequence task-status recording and lazy single-profile Agent Registry sync. This is runtime governance work only; no new chapter acceptance was run.
- Context Builder now emits and enforces `stage-context-profile-v1` contracts for topic/world/character/outline/chapter-plan/prose/review/revision/recap/publish/feedback contexts. Bundles include source policy, source isolation, allowed/forbidden asset types, and manual-selection policy rejections. Unit coverage is in `tests/unit/test_context_builder_stage_profiles.py`.
- Chapter planning now emits `chapter-blueprint-contract-v1` inside `ChapterPlan`, preserves it in `ChapterPlanVersion`, and hands it into `DraftChapter` as `chapter_plan_blueprint` evidence. Unit coverage is in `tests/unit/test_chapter_blueprint_contract.py`.
- Content quality loop now includes `readable-prose-gate-v1` as a local explainable gate that writes `quality_score_report`, blocking `ReviewIssue`, and `RevisionTask` assets for thin or unreadable prose. Unit coverage is in `tests/unit/test_content_quality_loop.py`.
- ReviewIssue repair now uses `review-issue-revision-strategy-v1`: issue types and readable-prose dimensions map to strategy ids, patch scope, required output evidence, and re-review focus. `RevisionTask`, `RevisionPlan`, Loop Kernel, and Agent Scheduler dispatch preserve this contract.
- Long-form state update now includes a v1 reducer: `create_longform_artifacts_for_draft()` writes chapter state/fact/character/foreshadow/reward projections into existing CanonGraph `canon_state_machine_ledger`, `canon_state_machine_snapshot`, and `canon_state_machine_diff_report` assets. Chapter bus outputs expose the reducer paths.
- Longform recap trigger policy now distinguishes 5-chapter light recap, 10-chapter formal recap, overdue formal recap, exception recap, and forced chapter checkpoints. Reports persist recap level, cadence boundary, next recap chapters, and forced checkpoint status.
- Local export package hardening now writes a generated-draft-only markdown file plus a JSON manifest containing hash/size, provenance over review/revision/canon/reducer/recap evidence, source-isolation policy, operator checklist, rollback instructions, and manual handoff to operator review before publish gate.
- ApprovalRequest foundation now exists as a schema-backed Permission Center asset/API with approve/reject/expire lifecycle, risk/environment/blocking policy, evidence refs, rollback plan, and snapshot aggregation.
- Project cockpit snapshots now expose V1 artifact coverage from chapter production run outputs, reducer/recap/export status, and ApprovalRequest summaries for operator inspection without running a chapter acceptance pass.

阻塞项:
- True 30-chapter local slow acceptance is intentionally deferred until the unified acceptance phase and is not yet passing inside an acceptable runtime envelope.
- 10-chapter runtime growth is high: chapter 1 took 22.571s, chapter 10 took 306.933s.
- Readable prose/page-turning/mobile has a first local gate, but provider/human calibration and final full-loop proof remain pending.
- ApprovalRequest caller migration is still pending for every high-risk source/context/publish/story mutation path.
- Source policy lifecycle now has schema-backed policy/license/risk/snapshot/sync-job assets and context eligibility evaluation; caller migration into every Context Builder/MKAOS/material path still needs tightening.
- ReaderPromise lifecycle now has schema-backed promise/ledger assets and draft-to-longform integration; payoff detection remains deterministic and needs calibration plus final multi-chapter proof.

推荐切片:
1. Continue reducing per-chapter runtime growth and asset-volume amplification in the true chapter bus without running chapter acceptance during development.
2. PleasurePoint / chapter economy lifecycle so爽点 cadence and watery-chapter risks are first-class.
3. ApprovalRequest caller migration for high-risk source/context/publish/story changes.
4. Continue reducing per-chapter runtime growth and asset-volume amplification before the final unified acceptance phase.

验收标准:
- Create one project.
- Generate/record world, characters, book outline, first 30 chapter plans.
- Generate 10-30 chapters locally.
- Each chapter has plan, context bundle, draft, review report, review issues when applicable, revision plan/draft, re-review, quality record, canon update, trace/cost record.
- Chapters are not outline-like placeholders.
- Blocking issues stop progression until revision or explicit approval.

测试策略:
- `tests.integration.test_novel_os_acceptance` expanded or paired with a v1-specific acceptance test.
- Deterministic 10-chapter sequence contract regression plus explicit slow 10-chapter evidence and 30-chapter local acceptance run.
- Positive/negative quality gate fixtures.
- Source leakage regression tests.
- Export package manifest/provenance fixture.
- Approval approve/reject/expire fixtures.

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
- ReaderPromise has a first-class local lifecycle foundation; PleasurePoint is still not a first-class lifecycle model.
- Longform reports exist, but reducers/query/diff are uneven.

推荐切片:
- Pleasure Point/Reward Ledger integration.
- Reader Promise provider/human payoff calibration.
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
- Source governance lifecycle foundation exists; usage feedback, connector refresh, and Context Builder/MKAOS caller migration remain partial.

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
- Approval Router and calling-module migration.
- Security / Sandbox OS.
- Prompt Injection Guard.

当前完成度: 30%.

阻塞项:
- ApprovalRequest foundation exists; approval routing and full caller migration remain incomplete.
- Source governance lifecycle foundation exists; full connector sandbox and security audit lifecycle are incomplete.
- External connector sandboxing must be proven before automated imports.

推荐切片:
- ApprovalRequest caller migration and Approval Router.
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
