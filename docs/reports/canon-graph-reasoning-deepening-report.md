# Canon Graph Reasoning Deepening Report

Date: 2026-07-03

## Scope

This pass deepens Canon Graph from a queryable JSON asset view into a deterministic, evidence-backed reasoning graph across:

- Canon Database
- Character Card / Character State Ledger
- Arc Plan
- Foreshadowing Graph / Foreshadowing Thread
- World Bible / Continuity Bible / Power Scale Rule
- Fact Ledger

The implementation remains local-first and storage-compatible. It does not introduce a graph database or model-assisted semantic inference engine.

## Implemented Capabilities

| Capability | Implementation Evidence | Notes |
|---|---|---|
| Unified graph nodes | `src/novel_forge/modules/canon_graph/service.py::_nodes_from_asset` | Normalizes Canon / Character / Arc / Foreshadowing / WorldRule / Fact into typed nodes. |
| Reasoning edges | `service.py::_infer_reasoning_edges` | Adds `same_identity`, `alias_of`, `forbids_alias`, `participates_in_arc`, `requires_payoff`, `forbids_expansion`, `points_to_truth`, `supports_arc_payoff`, `constrains`, `forbids_term`. |
| Identity clustering | `service.py::_identity_clusters` | Detects cross-asset identity groups by entity id, canonical name, display name, and aliases. |
| Graph-level issues | `service.py::_reason_over_graph` | Emits lifecycle status conflicts, forbidden alias reuse, orphan/overdue foreshadowing, uncovered arc payoffs, and weak WorldRule checks. |
| ReviewIssue candidate conversion | `service.py::_reasoning_issues_to_candidates` and `check_canon_graph_conflicts` | Merges artifact-text conflicts with graph reasoning conflicts. |
| Path explanations | `service.py::query_canon_graph_paths` | BFS path query explains why two Canon/Character/Arc/Foreshadowing/WorldRule items are related. |
| Reasoning API | `src/novel_forge/api/routers/canon_graph.py` | Adds `POST /product/canon-graph/reason` and `POST /product/canon-graph/paths`. |
| Schema-compatible snapshot | `service.py::_schema_projection` and `_write_snapshot` | Persists `canon_graph_snapshot` with `entities`, `relationships`, `state_machines`, `lifecycle_threads`, `event_graph`, `violations`, plus full graph payload. |
| Query observability | `service.py::query_canon_graph` | Query matches now include node degree and graph reasoning summary. |

## Failure And Gate Behavior

- Blocking lifecycle conflicts are emitted as `canon_conflict` candidates.
- Blocking graph issues can be persisted through the existing `persist_issue_candidates` path.
- `reason_canon_graph(..., persist_snapshot=True)` now writes the same reasoning result that it returns, preventing stale snapshot reads.
- Artifact conflict checks still preserve direct text-based checks for forbidden aliases, forbidden arc expansions, dropped foreshadowing reuse, and WorldRule forbidden terms.

## Tests

Added or extended:

- `tests/unit/test_canon_graph.py::test_unified_graph_queries_canon_character_arc_foreshadowing_and_world_rules`
- `tests/unit/test_canon_graph.py::test_reasoning_snapshot_and_paths_explain_graph_conflicts`
- `tests/unit/test_canon_graph.py::test_canon_graph_conflicts_convert_to_review_issues`
- `tests/unit/test_product_api_routes.py`

The regression fixture proves:

- Canon and Character assets are unified through `same_identity`.
- A contradictory Character State Ledger creates a blocking lifecycle issue.
- Arc required payoffs become obligations.
- Foreshadowing can explain an Arc relation through `supports_arc_payoff`.
- Persisted snapshots remain schema-compatible and include reasoning violations.
- New Canon Graph API routes are registered.

## Tradeoffs

- Reasoning is deterministic and conservative. It uses explicit fields, aliases, project-scoped assets, and bounded token overlap for short Chinese terms.
- The graph remains JSON-backed because the current local-first architecture does not require a graph database for P1 governance.
- The path query treats edges as explainable graph relationships, not as probabilistic truth.

## Remaining Work

| Gap | Priority | Recommended Next Step |
|---|---|---|
| No causal temporal graph across every chapter event. | P1 | Add chapter-event extraction into Fact Ledger / Canon Graph event nodes. |
| No visual graph editor. | P2 | Add read-only graph viewer first, then typed edge editing. |
| Semantic overlap is deterministic, not model-assisted. | P2 | Add optional approved scorer behind provider hard-stop and trace ledger. |
| WorldRule checks rely on machine-checkable terms. | P2 | Add required/forbidden pattern authoring UI. |
| Agent operation coverage should consume path explanations directly. | P1 | Route Agent Center canon-check operations through `reason_canon_graph` and `query_canon_graph_paths`. |
