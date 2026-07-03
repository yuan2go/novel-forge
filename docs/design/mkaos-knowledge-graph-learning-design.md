# MKAOS Knowledge Graph And Effect Learning Design

Date: 2026-07-03

## Objective

Upgrade MKAOS from card-level retrieval into a traceable multidisciplinary knowledge graph and effect feedback learning system without replacing the existing P0 card, binding, pack, OS Envelope, Context Builder, RAG isolation, and ReviewIssue paths.

## Asset Types

### `knowledge_graph_snapshot`

Purpose: auditable graph snapshot for selector reasoning, UI exploration, Agent Center trace, and Context Builder diagnostics.

Required content:

- `graph_id`
- `project_id`
- `nodes`
- `edges`
- `summary`
- `source_isolation`

Node families:

- `knowledge_card`
- `discipline`
- `flow`
- `rule_card`
- `template_card`
- `source_chunk`

Edge families:

- `classified_as`
- `evidence_for`
- `bound_to_flow`
- `governed_by_rule`
- `uses_template`
- `validated_by_rule`
- `instantiates_template`
- `effect_observed`

Source isolation:

- No `source_chunk.raw_text`.
- No `source_chunk.clean_text`.
- Source evidence is represented by id, source document id, chunk index, and content hash only.

### `knowledge_learning_snapshot`

Purpose: aggregate observed effects and feedback into explicit selector learning recommendations.

Required content:

- `learning_id`
- `project_id`
- `learning_items`
- `recommendations`
- `applied_updates`
- `source_metrics`

Learning inputs:

- `knowledge_usage_event.effect_score`
- `knowledge_usage_event.review_result`
- `knowledge_usage_event.reader_feedback`
- `knowledge_quality_score.delta`
- card `risk_level`
- card `status`

Actions:

- `observe`
- `keep`
- `boost`
- `reduce`
- `review`
- `quarantine`
- `do_not_select`

## APIs

- `POST /product/mkaos/knowledge-graph/build`
- `POST /product/mkaos/knowledge-graph/query`
- `POST /product/mkaos/knowledge-graph/paths`
- `POST /product/mkaos/learning/effects`

All APIs also expose the `/api/mkaos/...` compatibility path and return the standard OS Envelope response shape.

## Write Policy

Graph build and query are read-mostly. `build` persists a graph snapshot only when `persist: true`.

Learning is advisory by default. It writes back to card weights only when `apply_updates: true`, using the existing `apply_weight_update` path so quality score records, envelope metadata, and selector effects remain auditable.

## Boundaries

This layer does not replace Canon Graph. MKAOS graph reasons over reusable multidisciplinary knowledge and its observed production effect. Canon Graph remains responsible for story truth, character state, arc state, foreshadowing, and world-rule conflict detection.

This layer does not enter generation RAG. Graph and learning snapshots are stored as runtime/knowledge governance assets with `use_in_generation_rag: false`.

## Verification

Covered by:

- `tests/unit/test_mkaos_knowledge_graph_learning.py`
- `tests/unit/test_mkaos.py`
- `tests/unit/test_mkaos_selector_canon.py`
- `tests/unit/test_mkaos_os_envelope.py`
- `tests/unit/test_schemas.py`
