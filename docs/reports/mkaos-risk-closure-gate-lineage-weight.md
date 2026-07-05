# MKAOS Risk Closure: Gate, Lineage, Weight Governance

## Scope

This report records the risk closure work for three remaining MKAOS P1 concerns:

1. legacy non-ContextBuilder production entrypoints;
2. LocalStorage lineage depth, diff, ranking, and export;
3. feedback weight governance being dry-run/advisory by default.

## Implemented

### Gate Coverage

- Added `build_gate_coverage_report`.
- Added `mkaos_gate_coverage_report`.
- Added API:
  - `GET/POST /product/mkaos/production-gate/coverage`
  - `GET/POST /api/mkaos/production-gate/coverage`
- The report compares observed `context_bundle` assets and `mkaos_production_gate_report` assets across core operations.
- Critical missing operations are listed in `forbidden_bypass_operations`.

### Lineage Diff / Export

- Added `diff_lineage_indexes`.
- Added `export_lineage_graph`.
- Added `mkaos_lineage_diff_report` and `mkaos_lineage_export_package`.
- Added API:
  - `POST /product/mkaos/lineage/diff`
  - `POST /product/mkaos/lineage/export`
  - `/api/mkaos` compatibility routes.
- Lineage paths now carry `semantic_score` and are sorted by governance-critical relation weights.
- Export includes deterministic cluster layout, relation counts, semantic edge ranking, and source-isolation flags.

### Explicit Weight Governance Apply

- `apply_lineage_weight_governance` still defaults to dry-run.
- Real write-back now requires `apply_updates=true` plus `apply_policy=explicit` or `guarded_auto`.
- Positive feedback can boost weight.
- Negative feedback now recommends review/reduction instead of being treated as an automatic boost.
- Applied updates call existing MKAOS mutation/quality paths, preserving audit records.

## UI

Updated `web/admin` MKAOS pages with:

- production gate coverage action and summary;
- lineage diff/export actions;
- explicit weight governance apply action;
- first-slice local graph export explanation.

## Tests

Targeted verification:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_production_gate_coverage tests.unit.test_mkaos_lineage_diff_export tests.unit.test_mkaos_weight_governance_apply_policy tests.unit.test_mkaos_feedback_attribution tests.unit.test_mkaos_production_gate_runner tests.unit.test_product_api_routes
```

Result: passed, 10 tests.

## Remaining P2 Boundaries

- Coverage reports identify historical gaps but do not automatically rewrite legacy routes.
- LocalStorage graph export is suitable for local governance and UI exploration; it is not a graph database.
- `guarded_auto` policy exists as an explicit contract, but full approval inbox, reviewer assignment, and SLA routing remain P2.
