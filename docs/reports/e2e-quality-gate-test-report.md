# E2E Quality Gate Test Report

Date: 2026-07-02

## Scope

This report records the end-to-end verification slice for the Novel OS longform stability gate. The test covers a chapter draft moving through state extraction, canon checks, sanitizer checks, pattern checks, motif budget checks, longform artifact creation, review score generation, and Publishing Gate decision integration.

## Test Entry Points

- Unit coverage: `tests/unit/test_longform_stability.py`
- Integration coverage: `tests/integration/test_longform_quality_gate_e2e.py`
- Publishing integration coverage: `tests/unit/test_publishing_center.py`

## Verified Flow

1. A controlled chapter draft is written as a schema-backed `draft_chapter` asset.
2. A project-scoped Canon Database is created and registered before gate evaluation.
3. A project-scoped Arc Plan is created so arc progress checks have a target question, required payoff policy, motif budget, and villain agent.
4. `create_longform_artifacts_for_draft` creates the required evidence assets:
   - `chapter_state`
   - `chapter_pattern_report`
   - `fact_ledger`
   - `motif_budget_report`
   - `character_state_ledger`
   - `foreshadowing_graph`
   - `villain_operation_plan`
   - `reader_fatigue_report`
   - `style_control_plan`
   - `platform_adapter_report`
   - `reward_ledger`
   - `review_score_system_report`
5. `evaluate_longform_stability_gate` requires a pre-existing `chapter_state` before allowing the chapter to pass the longform Publishing Gate.
6. Canon consistency, output sanitizer, pattern similarity, motif budget, arc progress, foreshadowing, villain operation, reader fatigue, style control, platform adapter, reward ledger, and review score results are merged into one structured gate result.
7. `create_publish_gate_report` merges the longform gate into the existing publish decision.
8. Failed longform gate items generate a schema-backed `revision_task`.

## Negative Cases Covered

- A chapter containing `{"text": ...}` plus `notes` is not accepted as clean body text.
- A chapter containing forbidden protagonist aliases fails Canon consistency.
- Three consecutive chapters using the same investigation method and old-debt hook fail Pattern Similarity.
- A Publishing Gate failure creates a `revision_task` with structured longform reasons.
- A chapter without a pre-existing `chapter_state` fails the longform gate.

## Commands Run

```text
python3 -m py_compile src/novel_forge/modules/longform_stability/service.py src/novel_forge/modules/drafting/service.py src/novel_forge/modules/audit/service.py
python3 -m unittest tests.unit.test_schemas
python3 -m unittest tests.unit.test_longform_stability
python3 -m unittest tests.unit.test_publishing_center
python3 -m unittest tests.unit.test_module_services
python3 -m unittest tests.unit.test_context_and_production_chain
python3 -m unittest tests.integration.test_longform_quality_gate_e2e
make validate
```

## Result

Status: passed.

The E2E slice now blocks bad chapters before canonical publishing, produces traceable longform stability artifacts, and creates executable revision tasks when the gate fails.
