# V7 Content Intelligence Foundation Report

Date: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`
Starting commit: `3f68522`
Scope: Content Intelligence Foundation, Long-chain Proof Center slice, Publishing/Feedback Adapter 2.0 slice, Agent/Workflow/API/UI coverage

This report records the current verified implementation state for the V7 content intelligence foundation. Code and tests are the evidence source; V7 planning docs remain design intent unless listed here with implementation paths.

## Completed In This Pass

| Area | Implemented evidence | Notes |
|---|---|---|
| Genre OS | `src/novel_forge/modules/genre_os/service.py`, `src/novel_forge/api/routers/genre_os.py`, `tests/unit/test_genre_os.py` | Builds genre profiles, subgenre mechanics, platform fit, template binding, strategy packs, and genre risk gates. Risk gates can emit `ReviewIssue` paths. |
| Style OS | `src/novel_forge/modules/style_os/service.py`, `src/novel_forge/api/routers/style_os.py`, `tests/unit/test_style_os.py` | Ingests authorized samples, extracts abstract fingerprints, builds style profiles/policies/rules, and produces style drift reports without putting raw samples into generation context. |
| Canon Graph 2.0 plugins | `src/novel_forge/modules/canon_graph/service.py`, `tests/unit/test_canon_graph_plugins.py` | Adds genre-specific plugin reports for fantasy power scale, mystery evidence chain, romance relationship state, historical faction network, sci-fi rules, and horror contamination. Critical conflicts can become `ReviewIssue` paths. |
| Quality Eval 2.0 | `src/novel_forge/modules/quality_eval/service.py`, `src/novel_forge/modules/evaluation_center/__init__.py`, `tests/unit/test_quality_eval_v2.py` | Adds rubric packs, quality suites, quality gates, model judge result, human annotation, and regression report assets. Local heuristic fallback is explicitly labeled as not premium judgment. |
| Long-chain Proof Center | `src/novel_forge/modules/long_chain_proof/service.py`, `tests/unit/test_long_chain_proof.py`, `tests/integration/test_long_chain_50_chapter_content_intelligence.py` | Supports deterministic 50-chapter pressure runs, mock 100 runs, state-only 300 simulation, and opt-in provider 30 slow runs. Records checkpoints, trends, and acceptance/failure evidence. |
| Publishing/Feedback Adapter 2.0 | `src/novel_forge/modules/publishing_feedback_adapters/service.py`, `src/novel_forge/api/routers/publishing_feedback_adapters.py`, `tests/unit/test_publishing_feedback_adapters.py` | Implements manual upload packages, publish receipts, platform metrics, comment clustering, dropoff reports, and human-gated mutation proposals. |
| Schema registry and storage mapping | `src/novel_forge/schemas/assets.py`, `src/novel_forge/schemas/base.py`, `src/novel_forge/core/constants.py`, `src/novel_forge/storage/local.py` | New V7 assets are schema-backed and mapped to asset directories. Common field validation includes required V7 fields. |
| Context/RAG integration | `src/novel_forge/modules/context_builder/service.py`, `src/novel_forge/storage/rag_context.py`, `tests/integration/test_content_intelligence_context_builder.py` | Genre/style/quality/canon evidence can enter context buckets; raw `style_sample` is blocked from generation RAG. |
| Agent operations | `src/novel_forge/modules/agent_scheduler/service.py` | Registers V7 operations for genre, style, canon plugins, quality, long-chain proof, upload packages, receipts, metrics, comments, and feedback mutation proposals. |
| Workflow processors | `src/novel_forge/modules/workflow_nodes/service.py` | Registers service processors for V7 build/run/import/cluster/proposal operations. |
| Product API | `src/novel_forge/api/models.py`, `src/novel_forge/api/routers/genre_os.py`, `style_os.py`, `quality_eval_v2.py`, `long_chain_proof.py`, `publishing_feedback_adapters.py`, `canon_graph.py`, `tests/unit/test_product_api_routes.py` | Adds inspect/run routes under `/product/genre/*`, `/product/style/*`, `/product/quality/*`, `/product/long-chain-proof/*`, `/product/publishing-adapters/*`, `/product/feedback-adapters/*`, and `/product/canon-graph/plugin`. |
| Web Admin consoles | `web/admin/app/features/content-intelligence/ContentIntelligencePages.tsx`, route pages under `web/admin/app/*` | Adds Genre, Style, Canon Graph 2.0, Quality Eval 2.0, Long-chain Proof, Publishing Feedback 2.0, and Agent Operation Coverage consoles with API-backed actions. |

## Risk Closure Addendum

Follow-up risk closure is recorded in [v7-content-intelligence-risk-closure-report.md](v7-content-intelligence-risk-closure-report.md). The main changes are provider-backed quality judge evidence, opt-in provider 50-chapter long-chain proof, generic HTTP platform publish adapter, and V7 UI Artifact Inspector/compare/needs-review workflow.

## Tests Run

| Command | Result |
|---|---|
| `python3 -m unittest tests.unit.test_genre_os tests.unit.test_style_os tests.unit.test_canon_graph_plugins tests.unit.test_quality_eval_v2 tests.unit.test_long_chain_proof tests.unit.test_publishing_feedback_adapters` | Passed: 13 tests |
| `python3 -m unittest tests.integration.test_content_intelligence_context_builder tests.integration.test_genre_style_quality_to_draft_chain tests.integration.test_feedback_to_mutation_proposal tests.integration.test_long_chain_50_chapter_content_intelligence` | Passed: 4 tests |
| `python3 -m unittest tests.unit.test_product_api_routes tests.unit.test_schemas tests.integration.test_novel_os_acceptance` | Passed: 19 tests |
| `python3 -m unittest tests.unit.test_agent_workflow_and_impact tests.unit.test_loop_kernel tests.integration.test_workflow_steps` | Passed: 7 tests |
| `python3 -m compileall -q src/novel_forge tests` | Passed |
| `npm --prefix web/admin run lint` | Passed |
| `npm --prefix web/admin test` | Passed: 10 passed, 1 skipped optional browser-related test |
| `make test` | Passed after risk closure: Python 527 tests OK, skipped=2; Web Admin 10 passed, 1 skipped |

## Remaining Risks

1. Real external provider execution still requires configured provider routes, credentials, budget policy, and operator approval; tests use fixture adapters.
2. The generic HTTP platform adapter is implemented, but no specific commercial platform SDK is hardcoded.
3. UI repair remains conservative and human-gated; it marks assets for review rather than mutating story plans silently.
4. V7 content intelligence is wired into Context Builder and RAG buckets, but deeper draft-generation policy use remains the next integration layer.

## Follow-up Priority

1. Connect quality suite and style/genre policies more deeply into draft and revision services without bypassing Context Builder or provider runtime guard.
2. Run an operator-approved provider-backed quality judge and provider 50-chapter proof in a budgeted environment.
3. Add platform-specific adapters only after credentials, terms, callback behavior, and rate limits are reviewed.
4. Add more calibrated fixtures per genre/subgenre and platform profile.
5. Expand UI route smoke after Playwright is available in the local environment.
