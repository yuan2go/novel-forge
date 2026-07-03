# Phase 3 MKAOS Selector / Canon Report

Date: 2026-07-03

## Completed

- Hardened Knowledge Pack selector with explicit `selector_policy`.
- Added per-item `selector_decision`, `selection_score`, `quality_adjusted_score`, and `estimated_tokens`.
- Added selector rejection records for explicit risk-source-policy exclusions.
- Made `knowledge_quality_score` feedback deltas influence later pack ordering.
- Preserved `apply_weight_update` as a card-weight mutation path and included that weight in selection.
- Upgraded Canon conflict checking from a narrow facts/entities stub into a stable adapter.
- Added `check_canon_conflict` and `canon_conflict_to_issue_candidate`.
- Expanded Canon context collection to Character, Arc, Foreshadowing, FactLedger, Continuity Bible, and world-rule assets.
- Kept `validate_canon_conflict` backward compatible.

## Tests

| Command | Result |
| -- | -- |
| `python3 -m unittest tests/unit/test_mkaos_selector_canon.py` | 3 tests OK |
| `python3 -m unittest tests/unit/test_mkaos.py` | 5 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_isolation.py` | 4 tests OK |
| `python3 -m unittest tests/unit/test_mkaos_os_envelope.py` | 5 tests OK |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK, 257.578s |

## Tradeoffs

- No migration was added. Existing JSON asset types were sufficient for selector and Canon adapter hardening.
- Risk filtering is opt-in to avoid changing P0 pack behavior unexpectedly.
- Canon semantic reasoning is still heuristic. The output shape is now stable enough for ReviewIssue in Phase 5.

## Remaining Work

- Phase 4 must consume MKAOS packs through Context Builder rather than direct service prompt assembly.
- Phase 5 must persist `issue_candidates` as ReviewIssue and enforce blocking gates.
- Phase 7 can reuse Canon references for longform recap writeback.
