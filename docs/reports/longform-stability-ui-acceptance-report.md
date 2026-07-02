# Longform Stability UI And OS Acceptance Report

Date: 2026-07-02

## Implemented

- Added Longform Stability admin route: `/longform-stability`.
- Added backend dashboard endpoint: `GET /product/longform-stability/dashboard`.
- Added model-assisted extraction endpoint: `POST /product/longform-stability/extract`.
- Added OS acceptance endpoint: `POST /product/longform-stability/acceptance`.
- Added arc visualization payload with arc nodes, edges, and chapter lanes.
- Added persistent OS acceptance gate using `gate_result` with `gate_kind=longform_os_acceptance`.
- Added model gateway evidence for `model_assisted_longform_extraction` through `model_call_log` and runtime ledger.

## UI Panels

- Extraction Controls: project, draft, model-assisted toggle, extract, acceptance, publish gate.
- Gate Summary: canon, arc, gate failures, revision tasks.
- Arc Visualization: chapter lanes showing state, pattern, motif, villain, and gate status.
- Chapter Stability: per-chapter evidence table.
- Acceptance Checks: blocking and warning OS-level checks.
- Latest Longform Assets: latest evidence assets by type.
- Evidence JSON: raw bounded gate and action result preview.

## Acceptance Coverage

The OS acceptance gate checks:

- Canon Database;
- Arc Plan;
- Chapter State;
- Pattern Report;
- Fact Ledger;
- Motif Budget;
- Character/Debt Ledger;
- Foreshadowing Graph;
- Villain Operation Model;
- Publishing Gate long-form integration;
- revision task generation after failed gates;
- model call/cost evidence for assisted extraction;
- workflow/agent runtime evidence.

## Verification

Commands run:

```text
python3 -m unittest tests.unit.test_longform_stability tests.integration.test_longform_quality_gate_e2e tests.unit.test_product_api_routes
npm --prefix web/admin run lint
npm --prefix web/admin test
```

Result: passed.
