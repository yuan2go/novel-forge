# MKAOS Ingestion And Creative Extraction Report

Date: 2026-07-04

## Scope

This pass adds a local-first MKAOS Creative Ingestion and Extraction first slice. It keeps the existing MKAOS service, Context Builder, ReviewIssue, OS Envelope metadata, and source isolation behavior intact while adding dedicated modules for ingestion, creative conversion, and quality gates.

## Implemented

### Ingestion Center

New module: `src/novel_forge/modules/mkaos_ingestion/`

Implemented:

- local repository registration;
- GitHub URL record-only path requiring local clone;
- Classical-Modern structure detection;
- TXT / MD / JSON / CSV / PDF / DOCX / EPUB adapters using dependency-free parsing;
- repository manifest generation;
- `SourceRepository`, `RepositoryManifest`, `BookSource`, `BookChapterSource`, `ParallelTextPair`;
- evidence-only parallel pair metadata;
- hash dedupe and resumable job asset shape;
- `ImportQualityReport`.

### CreativeKnowledgeCard

Implemented as a compatibility extension over existing `knowledge_card`.

Added content fields include:

- `source_type`;
- `abstraction_level`;
- `creative_principle`;
- `narrative_function`;
- `conflict_function`;
- `character_function`;
- `worldbuilding_function`;
- `prose_function`;
- `review_function`;
- `positive_usage`;
- `negative_usage`;
- `anti_patterns`;
- `applicable_flows`;
- `originality_boundary`.

Added quality dimensions:

- `creative_usability_score`;
- `flow_binding_score`;
- `anti_exposition_score`;
- `originality_safety_score`.

Deterministic first-slice extractors:

- `classical_text_extractor`;
- `webnovel_extractor`;
- `professional_book_extractor`;
- `mystery_extractor`.

### Creative Asset Converter

New module: `src/novel_forge/modules/mkaos_converters/`

Conversion targets:

- `genre_seed_card`;
- `world_rule_card`;
- `character_archetype_card`;
- `conflict_pattern_card`;
- `scene_material_card`;
- `plot_template_card`;
- `chapter_hook_card`;
- `review_rule_card`;
- `style_rule_card`.

The converter supports `dry_run`, batch inputs, references the source `KnowledgeCard`, preserves evidence refs, writes `mkaos_graph_relation` records, and can additionally create existing `RuleCard` / `TemplateCard` assets for review rules and plot templates.

### Quality Gate

New module: `src/novel_forge/modules/mkaos_quality/`

Implemented:

- `MKAOSExtractionReport`;
- CreativeKnowledgeCard gate;
- quote leakage detector;
- anti-exposition gate;
- near-duplicate first slice;
- source risk gate;
- KnowledgePack source isolation gate.

Production / strict / operating_system mode fails closed and persists blocking `ReviewIssue` for extraction quality or source leakage issues.

### Product API

Added product and compatibility routes:

- `POST /product/mkaos/ingestion/repositories`
- `GET /product/mkaos/ingestion/repositories`
- `POST /product/mkaos/ingestion/repositories/{repository_id}/scan`
- `POST /product/mkaos/ingestion/repositories/{repository_id}/import`
- `GET /product/mkaos/ingestion/jobs`
- `GET /product/mkaos/books`
- `GET /product/mkaos/books/{book_id}/chapters`
- `GET /product/mkaos/parallel-pairs`
- `POST /product/mkaos/extraction/jobs`
- `POST /product/mkaos/convert/creative-assets`
- `POST /product/mkaos/quality/evaluate-extraction`
- `POST /product/mkaos/quality/check-leakage`
- `POST /product/mkaos/quality/gate-knowledge-pack`

Each route also has an `/api/mkaos/...` compatibility route.

### UI

Added first-slice pages:

- `/mkaos/import`
- `/mkaos/repositories`
- `/mkaos/books`
- `/mkaos/extraction-jobs`
- `/mkaos/creative-assets`
- `/mkaos/quality`

The UI shows repository status, book sources, parallel pairs, extraction jobs, creative cards, conversion dry-run, and quality gate actions.

## Source Isolation

Raw source text, source chunk raw text, and parallel pair `source_text` / `target_text` remain evidence-layer data.

Downstream creative assets, conversion outputs, pack gates, and Context Builder integration tests assert that source expressions are not copied into generation context. Policy field names such as `raw_source_text_allowed=false` may appear for auditability, but the source text values themselves must not appear.

## Tests

New tests:

- `tests/unit/test_mkaos_ingestion.py`
- `tests/unit/test_mkaos_classical_modern_adapter.py`
- `tests/unit/test_mkaos_parallel_pair_parser.py`
- `tests/unit/test_mkaos_creative_knowledge_card.py`
- `tests/unit/test_mkaos_creative_converters.py`
- `tests/unit/test_mkaos_extraction_quality.py`
- `tests/unit/test_mkaos_quote_leakage_detector.py`
- `tests/unit/test_mkaos_anti_exposition_gate.py`
- `tests/unit/test_mkaos_source_type_extractors.py`
- `tests/integration/test_mkaos_classical_modern_ingestion_flow.py`
- `tests/integration/test_mkaos_creative_extraction_to_context_builder.py`
- `tests/integration/test_mkaos_ingestion_knowledge_pack_gate.py`

Frontend route/API guard:

- `web/admin/tests/feature-architecture.test.mjs`

## Current Limitations

- PDF parsing now uses optional `pypdf` when installed and falls back to dependency-free extraction. The fallback still cannot guarantee complex layout fidelity.
- DOCX parsing now uses optional `python-docx` when installed and falls back to structured Word XML parsing. EPUB parsing now uses optional `ebooklib` when installed and falls back to ZIP/HTML parsing. Chapter assets retain TOC, section, page manifests, parser quality, and warning metadata without storing section/page source text.
- Extractors remain deterministic by default. Real/model extraction is available only through explicit opt-in provider mode and stores provider evidence hashes/keys rather than raw provider/source text.
- Graph Explorer now includes creative asset nodes, converter relation assets, centrality, relation filters, risk edges, path index, deterministic layout, and path frames. It is still dependency-free and does not attempt full force-directed rendering or community detection.
- Ingestion jobs now support detail, resume, and cancel APIs. Resume is implemented for repository import and creative extraction; richer interactive partial-file resume and queue-level scheduling remain P1/P2.

## Optimization Follow-Up

Updated APIs:

- `GET /product/mkaos/ingestion/jobs/{job_id}`
- `POST /product/mkaos/ingestion/jobs/{job_id}/resume`
- `POST /product/mkaos/ingestion/jobs/{job_id}/cancel`

Optional parser dependencies are declared under `pyproject.toml` extra `ingestion` and are not required for default tests.
