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
- Agent Scheduler now registers `start-chapter-production` and `resume-chapter-production` as Workflow Agent operations. The runners call the canonical chapter production bus, preserve production `environment` / OS envelope / source policy / provider runtime evidence, and write scheduler output assets without running a chapter acceptance pass.
- Workflow ProcessorRegistry now registers `chapter_production_start` and `chapter_production_resume`. The processors call the canonical chapter production bus, preserve production runtime policy evidence, and fail closed in production when OS envelope, source policy, or provider runtime guard evidence is missing.
- Workflow service/API now writes a canonical v1 chapter-production `workflow_definition` template. The template points to the governed `start-chapter-production` processor, carries runtime policy placeholders, records required production evidence fields, and explicitly does not run chapter acceptance when created.
- Workflow DAG/dependency/ready-queue/runtime-console outputs now expose the canonical workflow template contract, required production evidence, missing evidence, and production fail-closed status without executing chapters.
- Workflow Nodes now expose a schema-backed workflow governance drift report/gate that flags missing canonical template contracts, missing governed chapter processors, missing production runtime evidence, and local warning vs production fail-closed status without executing chapters.
- Workflow execution and resume now invoke the workflow governance drift gate in production/operating-system/strict modes before node execution, record gate/report paths in WorkflowRun lineage, and fail before node runs when definitions are drifted.
- Workflow scheduler tick now treats governance preflight failed resumes as errors/dead-letter queue evidence, records gate/report paths on `dead_letter_evidence`, and does not acknowledge the queue as successful.
- Workflow runtime console now surfaces workflow governance preflight status, gate/report paths, and scheduler dead-letter queue evidence without raw JSON inspection.
- Focused runtime-growth regression now includes workflow governance template, drift gate, production execute/resume preflight, scheduler dead-letter, and runtime console evidence fixtures without running chapter acceptance or provider proof.
- Project Cockpit now surfaces workflow governance readiness from latest drift gate, WorkflowRun preflight lineage, ready-node dead-letter evidence, and Admin OS console read-only tables.
- Product API route coverage now proves `/product/os/cockpit/project` preserves workflow governance readiness status, failed preflight count, dead-letter count, and evidence paths.
- Focused runtime-growth regression now includes Project Cockpit service/API workflow-governance readiness fixtures without running chapter acceptance or provider proof.
- Project Cockpit service/API now has clean/passed workflow-governance readiness fixtures, so missing evidence remains `missing`, blocked evidence remains `blocked`, and passed gate/preflight without dead-letter reports `passed`.
- Focused runtime-growth regression now includes both blocked/dead-letter and clean/passed Project Cockpit workflow-governance readiness fixtures.
- Project Cockpit service/API now explicitly pins missing workflow-governance evidence to `missing`, preventing no-evidence states from looking ready.
- Focused runtime-growth regression now includes missing, blocked/dead-letter, and clean/passed Project Cockpit workflow-governance readiness fixtures.
- Permission Center now writes a non-mutating `approval-request-caller-readiness-v1` `project_metric_snapshot` over source/context/publish/feedback/story-mutation caller evidence; the Product API and Project Cockpit expose the latest readiness state without creating or resolving approvals.
- Focused runtime-growth regression now includes ApprovalRequest caller readiness missing/ready/pending-blocking fixtures and the Product API readiness route without running chapter acceptance or provider proof.
- `/product/os/cockpit/project` now has explicit route coverage for ApprovalRequest caller readiness evidence and is included in the focused runtime-growth regression bundle.
- Source Intake now writes a non-mutating `source-guarded-apply-readiness-v1` `project_metric_snapshot` over source diff repair plans, source approval refs, stale source-derived assets, regeneration AgentTasks, and rollback evidence; `/product/sources/guarded-apply-readiness` exposes it without connector execution, mutation, dispatch, provider proof, or chapter acceptance.
- `scripts/run_source_governance_regression.py` and `make source-governance-regression` now provide focused no-side-effect coverage for source refresh, connector planning, diff repair, guarded apply readiness, and route evidence while excluding connector execution, chapter acceptance, provider proof, and broad `make test`.
- Project Cockpit and `/product/os/cockpit/project` now surface latest source guarded apply readiness status, stale pending regeneration counts, dispatch-ready task counts, evidence paths, quality counters, and production gate board state without executing source apply, rollback, connector execution, regeneration, provider proof, or chapter acceptance; the focused source-governance regression includes this Cockpit service/API path.
- Source Intake now exposes `run_source_governance_runtime_gate()` and `/product/sources/runtime-gate`; the gate writes a standard `source_governance_runtime` `gate_result`, passes with clean sweeps, warns locally for blockers, fails closed in production for missing sweep evidence, stale/quarantined impacts, or unguarded source-derived assets, and is visible through Project Cockpit.
- PublishGate now runs source governance runtime gate and records it in gate data plus production governance evidence; ReleasePackage production evidence requires `source_governance_gate`; Context Builder writes source governance runtime gate evidence into ContextBundle metadata/content and fails closed in production if the source gate fails.
- Focused source-governance regression now includes source gate caller fixtures for PublishGate, ReleasePackage gate evidence, and Context Builder source gate evidence while still excluding connector execution, provider proof, chapter acceptance, and broad `make test`.
- Agent Scheduler now propagates source governance runtime gate evidence from context-builder service results/output reuse into checkpoint and execution evidence, and Workflow runtime policy now requires ContextBundle source gate evidence in strict/production modes while recording source gate paths/status on NodeRun runtime policy evidence.
- Agent Center, Workflow Runtime Console, and Project Cockpit now expose source governance runtime gate evidence, counts, latest paths, failed status, and drawer/gate-board rows from AgentRun, AgentCheckpoint, and NodeRun evidence without executing source repair, connector, provider proof, or chapter acceptance.

阻塞项:
- True 30-chapter local slow acceptance is intentionally deferred until the unified acceptance phase and is not yet passing inside an acceptable runtime envelope.
- 10-chapter runtime growth is high: chapter 1 took 22.571s, chapter 10 took 306.933s.
- Readable prose/page-turning/mobile has a first local gate, but provider/human calibration and final full-loop proof remain pending.
- ApprovalRequest caller readiness, source guarded apply readiness, and source governance runtime gate evidence are visible through read-only reports, Product API routes, Project Cockpit summaries, Agent Center, Workflow Runtime Console, and focused no-acceptance regression bundles; publish/release/context/scheduler/workflow callers now consume, propagate, or expose source gate evidence, while project-scoped runtime evidence hardening remains the next gap.
- ApprovalRequest caller migration is still pending for every high-risk source/context/publish/story mutation path.
- Source policy lifecycle now has schema-backed policy/license/risk/snapshot/sync-job/refresh-report assets and context eligibility evaluation; MKAOS knowledge/material seams plus analysis conversion and Context Builder selected/rejected summaries consume eligibility evidence, while Context Bundle writes knowledge/material usage feedback, lineage governance emits reviewable invalidation recommendations, and connector execution plans are ApprovalRequest-gated with no side effects.
- ReaderPromise, PleasurePoint/ChapterEconomy, Character Pressure, and Mobile Reading lifecycles now have schema-backed local foundations and draft-to-longform or chapter-bus integration; payoff, scene-value, agency, pressure, and mobile rhythm detection remain deterministic and need calibration plus final multi-chapter proof.

推荐切片:
1. Continue reducing per-chapter runtime growth and asset-volume amplification in the true chapter bus without running chapter acceptance during development.
2. Portfolio project boundary for future multi-book scheduling and cost/quality rollups.
3. Harden project-scoped source governance runtime evidence lookup in Agent Center and Project Cockpit when scheduler runs/checkpoints have sparse metadata but linked context/output assets carry project scope.
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
- Fallback/provider fixture proof confusion is reduced by the provider proof manifest; real execution still requires credentials and operator budget.

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
- ReaderPromise, PleasurePoint/ChapterEconomy, Character Pressure, and Mobile Reading have first-class local lifecycle foundations, but trope fatigue remains shallow and all deterministic gates need calibration.
- Longform reports exist, but reducers/query/diff are uneven.

推荐切片:
- Platform-specific manual adapters.
- Reader Promise provider/human payoff calibration.
- Pleasure Point / Chapter Economy provider-human calibration.
- Character Pressure provider/human calibration.
- Mobile Reading provider/human calibration.
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
- Source governance lifecycle foundation exists; caller migration covers MKAOS/material/analysis/context seams, audit-only refresh reports exist, Context Bundle usage feedback exists, usage/source-refresh governance is reviewable, and connector execution plans are ApprovalRequest-gated; guarded source diff repair remains partial.

推荐切片:
- Approved/rejected asset lifecycle.
- Knowledge/material usage feedback after each context-selected draft/review/revision asset, with source-refresh-aware reviewable weight governance before auto-selection changes.
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
- Source diff repair plans, approval-bound stale marking, sandboxed local-file connector runner, non-local connector adapter lifecycle receipts, source-aware rollback execution, stale/quarantine sweep evidence, and retention/expiry no-delete cleanup planning are available; next work is approved governance application policy.

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

当前完成度: 45%.

阻塞项:
- PortfolioProject, BookPotentialScore, and ResourceAllocationPlan now exist as schema-backed non-dispatching planning assets.
- CrossBookSimilarityReport now exists as local fingerprint guard evidence.
- Approval-gated multi-book scheduler plan evidence now exists without dispatch.
- BookLifecycleGateReport now exists for continue/pause/kill recommendations with blocking ApprovalRequest refs.
- Post-approval multi-book dispatch/status mutation remains future.
- Phase 1 single-book loop not yet proven.

推荐切片:
- Source diff repair and downstream invalidation/regeneration planning.
- Book-level scheduler using existing Agent scheduler.
- Cost/quality dashboard by project.

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
- Platform-specific manual adapters with rule snapshots.
- Serialization Engine.
- Publishing gates and receipts.
- Platform metric import.
- Comment/feedback analysis.
- Human-gated mutation proposals.
- Drop-off analyzer.
- Autonomy dashboard.
- Full regression harness.

当前完成度: 38%.

阻塞项:
- Current adapters are manual/rule-snapshot-level, not real platform SDK/callback/rate-limit integrations.
- Feedback mutation application now creates patch, invalidation, regeneration, AgentTask, re-review, and publish-gate rerun plans; automatic dispatch remains future work.
- Real platform accounts/APIs may require credentials and manual policy decisions.

推荐切片:
- ApprovalRequest caller migration before enabling deeper multi-book scheduling.
- ApprovalRequest caller migration for high-risk platform publish/story mutation decisions.
- Full regression suite for release/publish gates.

验收标准:
- Manual platform package includes checklist, status, receipt, parser confidence, project-scoped rule snapshot, and rule version.
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
