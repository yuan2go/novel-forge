# MKAOS Knowledge Graph And Learning Report

Date: 2026-07-03

## Summary

MKAOS has been upgraded from card and rule management into a first-slice multidisciplinary knowledge graph plus explicit effect feedback learning system.

The implementation keeps the existing P0 assets intact and adds graph/learning capabilities as auditable schema-backed assets:

- `knowledge_graph_snapshot`
- `knowledge_learning_snapshot`

## Implemented

1. Schema-backed graph and learning assets.
2. Graph builder over Knowledge Card, Rule Card, Template Card, Usage Binding, Usage Event, Quality Score, and Source Chunk evidence refs.
3. Graph query API with project, flow, discipline, term, and node-type filtering.
4. Graph path API for explainable traversal from knowledge to flow/rule/template/evidence nodes.
5. Effect learning API that aggregates usage effect, review feedback, reader feedback, and quality deltas.
6. Advisory learning by default, with explicit `apply_updates: true` required for weight writeback.
7. Source isolation tests proving no source chunk raw text or clean text enters graph or learning snapshots.

## Key Files

- `src/novel_forge/modules/mkaos/service.py`
- `src/novel_forge/api/routers/mkaos.py`
- `src/novel_forge/modules/mkaos/__init__.py`
- `src/novel_forge/schemas/assets.py`
- `src/novel_forge/schemas/base.py`
- `src/novel_forge/schemas/__init__.py`
- `tests/unit/test_mkaos_knowledge_graph_learning.py`
- `docs/design/mkaos-knowledge-graph-learning-design.md`

## API Surface

- `POST /product/mkaos/knowledge-graph/build`
- `POST /product/mkaos/knowledge-graph/query`
- `POST /product/mkaos/knowledge-graph/paths`
- `POST /product/mkaos/learning/effects`

Compatibility aliases exist under `/api/mkaos/...`.

## Source Isolation

Graph and learning payloads do not include:

- `source_chunk.raw_text`
- `source_chunk.clean_text`
- raw source sentinel content from source imports

They retain only evidence ids, chunk index, source document id, and content hash.

## Learning Policy

Learning recommendations are deterministic and explainable:

- high effect and positive feedback produce `boost`;
- weak effect or negative feedback produce `reduce` or `review`;
- critical risk produces `quarantine`;
- deprecated cards produce `do_not_select`;
- cold-start cards produce `observe`.

Weight updates are not silent. They require `apply_updates: true` and are routed through existing MKAOS weight update code, creating quality score records.

## Tests Run

- `python3 -m unittest tests/unit/test_mkaos_knowledge_graph_learning.py`
- `python3 -m unittest tests/unit/test_mkaos.py tests/unit/test_mkaos_selector_canon.py tests/unit/test_mkaos_os_envelope.py tests/unit/test_mkaos_knowledge_graph_learning.py`
- `python3 -m unittest tests/unit/test_schemas.py`

All passed.

## Remaining Boundaries

1. The graph is in-process JSON asset backed, not a graph database runtime.
2. Learning is deterministic and rule-based; it does not yet train a statistical model.
3. UI dedicated graph and batch learning controls still need a later console pass.
4. Canon Graph remains separate and should not be collapsed into MKAOS graph.
