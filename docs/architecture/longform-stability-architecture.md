# Long-Form Stability Architecture

## Purpose

Long-form stability turns a generated chapter into a controlled state transition. The module prevents drift, metadata leakage, repeated structure, uncontrolled clues, motif overload, untracked debts, and antagonist absence.

## Runtime Position

```text
chapter_plan
  -> previous chapter_state required
  -> draft generation
  -> output sanitizer
  -> chapter_state
  -> chapter_pattern_report
  -> fact_ledger
  -> motif_budget_report
  -> character_state_ledger
  -> foreshadowing_graph
  -> villain_operation_plan
  -> publish_gate_report
  -> revision_task on fail
```

## Storage Boundary

Long-form control assets are schema-backed JSON assets:

- continuity assets: canon, state, pattern, facts, arcs, clues, motifs, character/debt, villain, reward;
- review assets: fatigue and review score;
- style/platform assets: style control and platform adapter.

These are local-first assets under `data/`, with optional PostgreSQL write-through like existing assets.

## Draft Integration

`src/novel_forge/modules/drafting/service.py` now:

- reads previous chapter state for chapter > 1;
- includes previous state in model context;
- runs `sanitize_chapter_text`;
- blocks failed sanitizer output before draft storage;
- writes long-form artifacts after draft storage;
- links artifact paths into draft content/metadata.

## Gate Integration

`src/novel_forge/modules/audit/service.py` now calls `evaluate_longform_stability_gate` inside `create_publish_gate_report`.

Gate results are merged into:

- `content.gates.longform_*`
- `content.blocking_issues`
- `content.required_reports.longform_stability_reports`
- `content.longform_stability`

When the decision is not `ready`, `create_revision_task_from_gate` writes a `revision_task`.

## Deterministic First Slice

The first implementation keeps deterministic extraction as the hard fallback. Model-assisted extraction is now an optional operating layer on top of the deterministic extractor:

- API: `POST /product/longform-stability/extract`
- service: `model_assisted_longform_extraction`
- operation: `model_assisted_longform_extraction`
- task type: `longform_extraction`
- evidence: `model_call_log`, `cost_ledger`, provider guard `gate_result`, and generated long-form assets

The model layer may improve extraction quality, but it cannot bypass deterministic schema-backed output or Publishing Gate checks.

## UI Management Page

The admin UI exposes a dedicated long-form control page:

- route: `/longform-stability`
- component: `web/admin/app/features/os/LongformStabilityPage.tsx`
- data API: `GET /product/longform-stability/dashboard`

The page provides:

- project and draft selectors;
- model-assisted extraction action;
- persistent OS acceptance gate action;
- Publishing Gate action;
- chapter stability table;
- latest long-form asset table;
- acceptance check table;
- evidence JSON preview.

## Arc Visualization

`longform_stability_dashboard` returns `arc_visualization` with:

- arc id, title, and chapter range;
- nodes for arc question, protagonist goal, villain goal, and chapter evidence;
- edges for goal/question/progress relationships;
- lanes that show per-chapter state, pattern, motif, villain, and gate status.

The current UI uses a dependency-free timeline lane. This keeps the console reliable in local-first deployments and avoids adding a heavy chart dependency before graph editing is needed.

## OS Acceptance

`longform_os_acceptance_report` checks evidence coverage across:

- Canon Database;
- Arc Plan;
- Chapter State;
- Pattern Report;
- Fact Ledger;
- Motif Budget;
- Character/Debt Ledger;
- Foreshadowing Graph;
- Villain Operation Model;
- Publishing Gate integration;
- revision task generation on failed gates;
- model call/cost evidence for assisted extraction;
- workflow/agent runtime evidence.

When `persist=true`, the acceptance result is written as a `gate_result` with `gate_kind=longform_os_acceptance`.

## API/UI Fields Needed

UI panels should read:

- `publish_gate_report.content.longform_stability`
- draft `content.longform_stability_artifacts`
- `chapter_state.content.forbidden_next`
- `chapter_pattern_report.content.fingerprint`
- `motif_budget_report.content.window_usage`
- `character_state_ledger.content.characters[].debt_ledger`
- `villain_operation_plan.content.operations`
- `revision_task.content.issues`
