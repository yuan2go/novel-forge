# MKAOS Selector and Canon Conflict Design

Date: 2026-07-03

## Scope

Phase 3 hardens the existing MKAOS P0 implementation without replacing it. The goal is to make pack selection and Canon validation stable enough for Phase 4 Context Builder and Phase 5 ReviewIssue.

## Selector V2

Selector V2 is implemented in `src/novel_forge/modules/mkaos/service.py` through:

- `build_knowledge_pack`
- `_selector_policy`
- `_selector_decision`
- `_select_pack_items`
- `_quality_feedback_delta`

Selection now considers:

- project scope;
- task flow / usage binding;
- priority;
- base quality score;
- feedback quality deltas;
- card weight;
- risk level;
- explicit source policy risk exclusion;
- token estimate;
- recency bonus.

The pack records `selector_policy`, `selector_rejections`, per-item `selector_decision`, `selection_score`, `quality_adjusted_score`, and `estimated_tokens`.

Compatibility rule: risk filtering is explicit. Existing P0 behavior still includes high-risk items as warnings unless caller passes `source_policy.exclude_risk_levels`, `blocked_risk_levels`, `exclude_high_risk`, or `exclude_critical_risk`.

## Feedback / Weight Closure

`record_review_feedback` creates `knowledge_quality_score` records. Selector V2 reads those deltas and clamps their total influence to `[-0.5, 0.5]`.

`apply_weight_update` still mutates the card weight. Selector V2 combines quality delta and card weight, so feedback can affect later pack order without requiring a new table.

## Canon Conflict Adapter

The stable service surface is:

- `check_canon_conflict(storage, payload)`
- `validate_canon_conflict(storage, payload)` as backward-compatible alias;
- `canon_conflict_to_issue_candidate(issue, check_input)`.

The check input normalizes:

- `project_id`;
- `target_asset_id`;
- `target_asset_type`;
- artifact text;
- structured claims;
- project Canon context;
- optional payload Canon overrides.

The Canon context now reads:

- `canon_database`;
- `character_card`;
- `character_state_ledger`;
- `fact_ledger`;
- `arc_plan`;
- `foreshadowing_thread`;
- `continuity_bible`;
- `power_scale_rule`.

The result returns:

- `passed`;
- `issues`;
- `issue_candidates`;
- `input`;
- `canon_source`;
- `checked_asset_types`;
- `references`.

Issue candidates use `issue_type=canon_conflict` and `source_system=mkaos.canon_conflict`, so Phase 5 can persist them as ReviewIssue without re-parsing MKAOS output.

## Limits

This phase does not create a durable ReviewIssue table and does not implement full semantic Canon reasoning. It creates a stable adapter and structured proof path. Blocking persistence belongs to Phase 5.
