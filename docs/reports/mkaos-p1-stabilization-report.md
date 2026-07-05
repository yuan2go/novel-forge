# MKAOS P1 Stabilization Report

Date: 2026-07-05

## Scope

This pass stabilizes MKAOS from first-slice knowledge management toward a local-first Knowledge Asset Operating System kernel for Novel OS.

Focus areas:

1. Governed model-level extraction.
2. Automatic MKAOS production gate entry.
3. Deep lineage and feedback governance.

## Implemented Capabilities

### Governed Model Extraction

Module: `src/novel_forge/modules/mkaos_model_extraction/`

Implemented:

- extraction schema and forbidden-field contract;
- prompt registry with default source-type prompt versions;
- provider runner with disabled/mock/local/configured modes;
- provider output sanitizer;
- candidate validator;
- confidence scoring;
- provider evidence hash asset;
- review queue;
- approve/reject candidate flow;
- benchmark and regression runner.

Default behavior remains deterministic and local. External provider calls require explicit provider configuration and remain opt-in.

### Automatic Production Gate

Module: `src/novel_forge/modules/mkaos_production_gate/`

Implemented:

- shared MKAOS production gate policy;
- gate runner;
- persisted `mkaos_production_gate_report`;
- production fail-closed behavior;
- ReviewIssue persistence for blocking gate failures;
- `mkaos_gate_summary` for Editor-in-Chief Console;
- automatic Context Builder integration in `build_flow_context_bundle`.

Production/strict/operating_system mode blocks on forbidden source text fields, blocking ReviewIssue, and configured critical gate risks.

### Deep Lineage Governance

Module: `src/novel_forge/modules/mkaos_lineage/`

Implemented:

- LocalStorage-based `mkaos_lineage_index`;
- safe node/edge graph without raw source text;
- lineage path query;
- asset impact analysis;
- issue/gate/feedback attribution helpers;
- feedback-to-knowledge attribution asset;
- dry-run weight governance report.

Supported path examples:

- source -> chunk -> knowledge -> pack -> context -> draft;
- knowledge -> draft -> review issue -> gate report;
- reader feedback -> draft -> context -> knowledge -> weight governance.

## API

Added product and compatibility routes:

- `POST /product/mkaos/model-extraction/jobs`
- `GET /product/mkaos/model-extraction/jobs`
- `GET /product/mkaos/model-extraction/jobs/{job_id}`
- `POST /product/mkaos/model-extraction/jobs/{job_id}/run`
- `POST /product/mkaos/model-extraction/jobs/{job_id}/cancel`
- `POST /product/mkaos/model-extraction/candidates/{candidate_id}/approve`
- `POST /product/mkaos/model-extraction/candidates/{candidate_id}/reject`
- `GET /product/mkaos/model-extraction/review-queue`
- `POST /product/mkaos/model-extraction/benchmark/run`
- `POST /product/mkaos/model-extraction/regression/run`
- `GET /product/mkaos/model-extraction/prompts`
- `POST /product/mkaos/model-extraction/prompts`
- `POST /product/mkaos/production-gate/run`
- `GET /product/mkaos/production-gate/reports`
- `GET /product/mkaos/production-gate/latest`
- `POST /product/mkaos/production-gate/policy`
- `POST /product/mkaos/lineage/build-index`
- `GET /product/mkaos/lineage/index`
- `POST /product/mkaos/lineage/query-path`
- `POST /product/mkaos/lineage/asset-impact`
- `POST /product/mkaos/lineage/issue-attribution`
- `POST /product/mkaos/lineage/feedback-attribution`
- `POST /product/mkaos/lineage/gate-attribution`
- `POST /product/mkaos/lineage/feedback-to-knowledge`
- `POST /product/mkaos/lineage/weight-governance`
- `GET /product/mkaos/lineage/reports`

Each route also has `/api/mkaos/...` compatibility routing.

## UI

Added web/admin pages:

- `/mkaos/model-extraction`
- `/mkaos/model-extraction/jobs`
- `/mkaos/model-extraction/review`
- `/mkaos/model-extraction/benchmarks`
- `/mkaos/model-extraction/prompts`
- `/mkaos/production-gate`
- `/mkaos/production-gate/reports`
- `/mkaos/knowledge-graph`
- `/mkaos/lineage`
- `/mkaos/impact`
- `/mkaos/feedback-attribution`

The UI is a first-slice operations surface. It shows jobs, review queue, gate reports, lineage nodes/edges, impact actions, and feedback attribution without rendering raw source text.

## Tests

Added:

- `tests/unit/test_mkaos_model_extraction_schema.py`
- `tests/unit/test_mkaos_model_extraction_sanitizer.py`
- `tests/unit/test_mkaos_model_extraction_confidence.py`
- `tests/unit/test_mkaos_model_extraction_prompt_registry.py`
- `tests/unit/test_mkaos_model_extraction_review_queue.py`
- `tests/unit/test_mkaos_production_gate_runner.py`
- `tests/unit/test_mkaos_lineage_index.py`
- `tests/unit/test_mkaos_asset_impact_analysis.py`
- `tests/unit/test_mkaos_feedback_attribution.py`
- `tests/integration/test_mkaos_model_extraction_to_knowledge_card.py`
- `tests/integration/test_mkaos_gate_context_builder_auto.py`
- `tests/integration/test_mkaos_gate_publish_release_package_auto.py`
- `tests/integration/test_mkaos_source_to_draft_lineage.py`
- `tests/integration/test_mkaos_feedback_to_weight_governance.py`
- `tests/integration/test_mkaos_novel_os_full_chain.py`

Latest targeted results:

- Model extraction / gate / lineage unit subset: 17 tests OK.
- Governance integration subset: 6 tests OK.
- Product API route coverage: OK.
- Full Python regression: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` passed, 473 tests OK, 2 skipped, 358.951s.
- Pipeline idempotency regression: passed after compat gate ReviewIssue persistence was restricted to production/strict and project-reference lookup was hardened.
- `npm --prefix web/admin test`: OK.
- `npm --prefix web/admin run build`: OK.

## Remaining Risks

- Real external model extraction and model judge E2E remain opt-in.
- The default extraction quality is deterministic and benchmarkable, but not a claim of large-corpus semantic extraction quality.
- Production gate is automatic from Context Builder; older non-Context Builder legacy entrypoints should continue migrating to the same gate helper.
- Lineage index is local and dependency-free; large graph diff, advanced ranking and visualization remain P2.
- Feedback weight governance is advisory/dry-run by default; automatic mutation still requires explicit apply policy.
