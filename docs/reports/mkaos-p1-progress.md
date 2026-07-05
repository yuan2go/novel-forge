# MKAOS P1 Progress

## Current Baseline

MKAOS has been upgraded from a P0 knowledge governance base into a first-slice Knowledge Asset OS kernel for Novel OS. The implementation remains local-first and uses LocalStorage assets, OS Envelope enforcement, Context Builder pack policy, ReviewIssue integration, and web/admin.

## Completed In This Pass

| Phase | Status | Implementation |
| --- | --- | --- |
| 1. Fail-closed policy | Complete | Existing `pack_policy.py` remains the shared fail-closed helper; regression coverage was re-run. |
| 2. Agent Context Contract | Complete baseline | Existing Context Builder/AgentRun contract tests remain passing. |
| 3. Selector v2 | Complete first slice | Task goal, discipline, platform, genre, quality dimensions, risk, status, priority, weight, budget, and feedback delta now contribute to selector decisions. |
| 4. Quality Score subdimensions | Complete first slice | Knowledge cards store quality dimensions and overall quality. Recalculation writes mutation audit. |
| 5. KnowledgeRelation / Graph v1 | Complete first slice | `knowledge_relation` assets support relation edges in graph snapshots. |
| 6. Cross-discipline fusion | Complete first slice | Fusion paths produce abstract story applications without source text. |
| 7. Knowledge conflict detector | Complete graph first slice | Source policy, risk, status, relation contradiction/forbids/requires, platform, task, canon-result, and opt-in model-judge result conflicts are checked. |
| 8. Feedback Learning v1 | Complete first slice | Existing learning snapshot can recommend/apply weight updates; weight updates now write mutation audit. |
| 9. Reader feedback attribution | Complete first slice | Deterministic feedback classification maps reader signals to knowledge candidates. |
| 10. MKAOS issue -> ReviewIssue | Complete first slice | MKAOS issues can persist as ReviewIssue and become RevisionTask candidates. |
| 11. Source Evidence Span | Complete first slice | Evidence spans capture page/section/paragraph/sentence/char metadata and hash only. |
| 12. Lineage Audit | Complete first slice | Lineage report traces source/knowledge/binding/pack/context/usage/issue/feedback/mutation. |
| 13. Versioning | Complete first slice | Knowledge versions support list, diff, and rollback with audit. |
| 14. Mutation Audit | Complete first slice | Create/update/weight/status/rollback actions write sanitized audit assets. |
| 15. Pack Debugger | Complete first slice | Debug reports explain selected/rejected items, budget, score, quality, feedback, and risks. |
| 16. Import Pipeline | Complete first slice | Source-kind policies, dry run, duplicate count, import report. |
| 17. Extraction Agent | Complete first slice | Deterministic candidate generation and approval flow. Model-assisted extraction is explicitly opt-in and mock/provider candidates are source-expression checked. |
| 18. Application Template | Complete first slice | Knowledge can be converted into template cards with anti-copy rules. |
| 19. Anti-Encyclopedia | Complete first slice | Detector expanded with regression examples and rewrite suggestions. |
| 20. Knowledge-to-Revision Task | Complete first slice | MKAOS ReviewIssue can produce blocking RevisionTask candidates. |
| 21. Platform weights | Complete first slice | Selector reports platform weight source and uses platform-specific weights. |
| 22. Genre weights | Complete first slice | Selector uses genre-specific weights with global fallback. |
| 23. Status lifecycle | Complete first slice | deprecated/quarantined/do_not_select are excluded; needs_review is excluded in production. |
| 24. Impact analysis | Complete first slice | Knowledge changes can report affected packs, contexts, issues, releases, rebuilds, and rechecks. |
| 25. API envelope/errors | Complete compatibility layer | MKAOS POST/PATCH mutation responses now return the standard `success/request_id/trace_id/envelope_id/data/error/warnings` shape while retaining legacy top-level fields for old clients. Product middleware blocks production mutation without envelope. |
| 26. Source leakage regression | Complete first slice | Tests prove source evidence does not enter pack/preview/graph payloads as source text. |
| 27. Regression Case Center | Complete first slice | Regression cases and suite runner persist reports. |
| 28. Acceptance Suite | Complete first slice | `run_mkaos_acceptance_suite` covers import, span, candidate, knowledge, pack, issue, revision, feedback, learning, lineage, debug, regression. |
| 29. web/admin UI | Complete first slice | MKAOS console now includes source evidence, quality dashboard, pack debugger, lightweight graph canvas, knowledge evolution, lineage, mutation, regression, and acceptance panels. |
| 30. Knowledge evolution loop | Complete first slice | `run_knowledge_evolution_cycle` orchestrates graph snapshot, effect learning, review-rule candidates, hot-template backflow, reader-feedback aggregation, and low-effect elimination recommendations. |
| 31. Professional book import run | Complete first slice | `run_professional_book_import` parses text/Markdown and optional PDF/EPUB/DOCX files, creates section-aware chunks, evidence spans, batch extraction candidates, rule/template candidates, approval queue items, and candidate graph relations. |
| 32. Abstraction quality benchmark | Complete first slice | `run_knowledge_abstraction_quality_benchmark` tests professional book, webnovel analysis, and classic analysis sources for transferable mechanism quality, actionability, anti-encyclopedia safety, flow coverage, and source overlap. |
| 33. Canon semantic graph bridge | Complete first slice | `check_canon_semantic_graph_conflict` combines explicit MKAOS canon checks with Canon Graph reasoning and returns ReviewIssue-compatible issue candidates. |
| 34. Longitudinal effect learning | Complete first slice | `run_longitudinal_knowledge_effect_learning` aggregates chapter quality, review scores, reader completion/ratings, platform retention, issue tags, and usage evidence into weight recommendations and optional updates. |
| 35. Governed model extraction pipeline | Complete first slice | `mkaos_model_extraction` adds prompt versions, provider runner, output sanitizer, schema validator, confidence scoring, review queue, benchmark/regression, candidate approval and source-isolated provider evidence. |
| 36. Automatic production gate | Complete first slice | `mkaos_production_gate` runs automatically from Context Builder and exposes run/list/latest/policy APIs. Gate reports persist source isolation, weak-card, ReviewIssue and recommendation evidence; production mode fails closed. |
| 37. Deep lineage governance | Complete first slice | `mkaos_lineage` builds a local graph index and supports lineage path query, impact analysis, issue/gate/feedback attribution, feedback-to-knowledge attribution and dry-run weight governance. |

## Key Files

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/modules/mkaos/__init__.py`
- `src/novel_forge/api/routers/mkaos.py`
- `tests/unit/test_mkaos_*`
- `tests/acceptance/test_mkaos_knowledge_asset_os.py`
- `web/admin/app/features/mkaos/api.ts`
- `web/admin/app/features/mkaos/MkaosConsolePage.tsx`

## Verification

Passed:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos tests.unit.test_mkaos_fail_closed_policy tests.unit.test_mkaos_agent_context_contract tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_mkaos_selector_v2 tests.unit.test_mkaos_quality_score tests.unit.test_mkaos_knowledge_graph_v1 tests.unit.test_mkaos_conflict_detector tests.unit.test_mkaos_feedback_learning_v1 tests.unit.test_mkaos_source_leakage_regression tests.acceptance.test_mkaos_knowledge_asset_os
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_selector_v2 tests.unit.test_mkaos_quality_score tests.unit.test_mkaos_knowledge_graph_v1 tests.unit.test_mkaos_cross_discipline_fusion tests.unit.test_mkaos_conflict_detector tests.unit.test_mkaos_feedback_learning_v1 tests.unit.test_mkaos_reader_feedback_attribution tests.unit.test_mkaos_review_issue_integration tests.unit.test_mkaos_evidence_span tests.unit.test_mkaos_lineage_audit tests.unit.test_mkaos_versioning tests.unit.test_mkaos_mutation_audit tests.unit.test_mkaos_pack_debugger tests.unit.test_mkaos_import_pipeline tests.unit.test_mkaos_extraction_agent tests.unit.test_mkaos_application_template tests.unit.test_mkaos_anti_encyclopedia tests.unit.test_mkaos_revision_task_integration tests.unit.test_mkaos_platform_specific_weight tests.unit.test_mkaos_genre_specific_weight tests.unit.test_mkaos_status_lifecycle tests.unit.test_mkaos_pack_impact_analysis tests.unit.test_mkaos_api_envelope tests.unit.test_mkaos_source_leakage_regression tests.unit.test_mkaos_regression_center tests.acceptance.test_mkaos_knowledge_asset_os
PYTHONPATH=src python3 -m unittest tests.integration.test_pipeline
npm --prefix web/admin test
npm --prefix web/admin run build
```

Latest results:

- Current Python discover: 473 tests passed, 2 skipped, 358.951s.
- Current MKAOS focused regression: 62 tests passed, 100.148s.
- Current targeted evolution/envelope/provider/conflict tests: 14 tests passed, 2.115s.
- Current pipeline integration: passed; sample pipeline second-run idempotency preserved after compat gate issue persistence and project-reference lookup hardening.
- Current web/admin test: 9 passed, 1 optional Playwright smoke skipped.
- Current web/admin lint: passed.
- Current web/admin build: passed.
- Current model extraction / production gate / deep lineage unit tests: 17 tests passed.
- Current MKAOS governance integration tests: 6 tests passed.
- Current product API route coverage: passed.
- Current web/admin test: 10 pass, 1 optional Playwright smoke skipped.
- Current web/admin build: passed, 67 routes generated.
- Current quality gate / ingestion pack gate / pipeline regression: 6 tests passed, 57.531s.

## Idempotency Note

Selector decisions and knowledge pack mutation audits now use stable ids for repeatable pack builds. This preserves sample pipeline second-run idempotency while still keeping auditable selector/debug output.

## Latest Risk Closure

- P0 `/api/mkaos` mutation compatibility remains, but responses now expose the standard envelope shape and legacy fields together.
- Conflict detector is still deterministic by default, but graph reasoning now handles `contradicts`, `forbids`, and missing `requires`; model judge input is accepted only through explicit opt-in.
- Extraction Agent remains local-first by default. Model-assisted extraction records opt-in state and rejects or sanitizes source-like provider candidates.
- web/admin graph remains dependency-free, but the console now includes a lightweight SVG graph canvas instead of summary-only tables.
- Knowledge asset evolution now exists as an auditable orchestration cycle instead of disconnected learning primitives.
- Follow-up hardening added transitive graph conflict inference, extraction provider quality reports, guarded automatic rule/template promotion and quarantine, and a larger Graph Explorer first slice.
- Provider E2E is now represented by `run_mkaos_provider_e2e_probe`: without explicit opt-in it reports `opt_in_required`; with mock opt-in it validates model-judge and extraction-provider output without network calls.
- Deep semantic conflict review is now explicit through `run_semantic_conflict_review`, which combines graph reasoning, deterministic semantic profiles, model-judge opt-in results, confidence, and `requires_model_review`.
- Human approval first slice now exists through `knowledge_governance_approval` assets and create/list/resolve APIs. Evolution can create approval requests for rule activation, template activation, and low-effect quarantine; applying still requires explicit approval.
- Graph Explorer now returns deterministic clusters, layout positions, sampling policy, and path animation frames while remaining dependency-free and source-text safe.
- Professional book import now has a complete first slice: section-aware chunking, evidence spans, full-book batch extraction, candidate approval queue, rule/template candidate generation, and relation auto-linking.
- Knowledge abstraction quality is now measurable through a benchmark report across professional books, webnovel analysis, and classic-novel analysis fixtures; this is not yet a claim of real corpus stability.
- Canon conflict can now opt into Canon Graph semantic reasoning through MKAOS and produce ReviewIssue candidates with graph evidence.
- Knowledge effect learning now has a longitudinal report path that combines quality, reader, platform, and review signals over chapters instead of only single feedback deltas.

## Remaining Risks

- Real model-judge and extraction providers remain opt-in; default implementation validates provider outputs locally but does not call external services.
- Knowledge evolution defaults to advisory mode. `guarded_auto` can apply safe promotions/quarantine, and a first-slice approval asset/API exists; full approval inbox, policy routing, reviewer assignment, and SLA remain P2.
- UI graph visualization is dependency-free and now has Graph Explorer sampling, clustering, layout metadata, and path frames; large-scale graph search, animated exploration, graph diff, and community detection remain P2.
- PDF / EPUB / DOCX professional-book parsing is dependency-optional; robust parser quality validation and rich TOC/footnote/table handling remain P2.
- Full “越写越强” proof still needs longer multi-chapter production telemetry and real reader feedback volume beyond synthetic/local fixtures, although the longitudinal aggregation path now exists.
- Abstraction quality benchmark uses local deterministic fixtures by default; large-scale professional-book, webnovel, and classic-novel corpus proof remains P2.
- Canon semantic graph reasoning is integrated, but deeper semantic ambiguity still needs opt-in model judge or richer graph inference.
- Model-level extraction is now governed and benchmarkable locally, but external provider E2E quality validation remains opt-in and has not been run in this default test pass.
- Production gate now auto-runs from Context Builder; continued hardening should wire the same helper through every legacy non-Context Builder route until no compat-only entrypoint remains.
- Deep lineage is local-index based; graph database scale, graph diff visualization and advanced semantic path ranking remain P2.

## Latest Stabilization: Gate Coverage, Lineage Diff/Export, Explicit Weight Apply

This pass closes the three remaining operational risks without changing the local-first architecture:

- Added `mkaos_gate_coverage_report` so the system can audit core operations against observed `ContextBundle` and `mkaos_production_gate_report` artifacts. Missing historical entrypoints are now visible as `compat_gap`, and critical gaps are listed in `forbidden_bypass_operations`.
- Added LocalStorage lineage diff/export reports. The export includes deterministic clusters, layout positions, relation counts, and semantic edge weights while keeping raw source fields excluded.
- Added semantic path ranking for lineage query results. Paths are ranked by governance-critical relations such as gate blocks, review issues, feedback attribution, and production usage.
- Changed lineage weight governance from advisory-only to explicit apply mode. Default remains dry-run; writes require `apply_updates=true` and `apply_policy=explicit` or `guarded_auto`.
- Fixed feedback impact semantics: negative feedback attribution now recommends review/reduction instead of incorrectly boosting knowledge weight; positive feedback can still increase weight.
- Added web/admin controls for gate coverage, lineage diff/export, and explicit weight governance apply.

New targeted tests:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_production_gate_coverage tests.unit.test_mkaos_lineage_diff_export tests.unit.test_mkaos_weight_governance_apply_policy tests.unit.test_mkaos_feedback_attribution tests.unit.test_mkaos_production_gate_runner tests.unit.test_product_api_routes
```

Result: 10 tests passed.

Updated residual risks:

- Historical non-ContextBuilder entrypoints are now auditable through coverage reports, but any route marked `compat_gap` still needs migration before claiming full production surface closure.
- Lineage remains a LocalStorage graph index. It now supports diff/export/ranking for local governance, but graph database scale, community detection, and complex animated visualization remain P2.
- Weight governance is no longer silently advisory-only, but automatic write-back still requires explicit policy. Full human approval workflow and reviewer assignment remain P2.

## Current Distance To A Full Knowledge Asset OS

MKAOS now satisfies the local-first kernel requirements: source evidence isolation, abstract knowledge assets, graph relations, selector/pack explainability, usage and feedback learning, ReviewIssue integration, mutation/version/lineage audit, regression cases, and an operations console.

The remaining gap is no longer “knowledge base vs OS” at the P1 level; it is operational maturity:

1. Rich graph inference across Canon/Character/Arc/Foreshadowing/WorldRule and MKAOS relations.
2. Real model-judge adapters under Runtime Policy and provider hard-stop.
3. Larger feedback corpus and platform-specific statistically meaningful learning.
4. Human approval workflow for rule/template promotion and knowledge quarantine.
5. Large-scale UI graph workbench with advanced filtering and diff.
6. Long-horizon acceptance showing multiple chapters improving selection quality over time.
