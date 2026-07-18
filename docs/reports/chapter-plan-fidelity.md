# ChapterPlan Fidelity

## Closed gap

The chapter root command freezes `chapter_plan_asset_version_id` and
`chapter_plan_content_hash`. The Plan node validates and normalizes that exact
AssetVersion instead of rebuilding a title/premise three-beat template.

`ChapterPlanCompatibilityReport` and `ChapterPlanQualificationReport` distinguish
legacy-compatible warnings from missing production semantics. Draft receives three
explicit views: `DraftPlanView`, `DraftContextView`, and `DraftStyleView`.

## Preserved semantics

The normalized contract covers function/objective, POV/time/location, cast and
relationships, scene sequence and goals, conflict/reveal/curve data, reward and
promise actions, foreshadow/Canon/world/power expectations, theme/antagonist motion,
hook/bridge, prohibited outcomes, style constraints, word count, and quality targets.

## Evidence

- Domain: `src/novel_forge/modules/chapter_authority/plan_domain.py`
- Runtime: `handlers.py`, `orchestrator.py`, `model_effects.py`
- Tests: `tests/unit/test_chapter_plan_fidelity.py`,
  `tests/integration/test_chapter_authority_scheduler_postgres.py`

Replays retain the original version; replacement, stale, revoked, ineligible, and
cross-project plans do not mutate an admitted Operation's frozen input.
