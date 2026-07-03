# ReviewIssue System Design

Date: 2026-07-03

## Scope

Phase 5 promotes review findings from inline report fields into durable `review_issue` assets. The system unifies Review, MKAOS validation, and Canon conflict issues so blocking items can stop canonical/final draft promotion and release packaging.

## Asset

Asset type: `review_issue`

Storage:

- local JSON: `data/reviews/*.json`
- SQL migration: `review_issues`

Required content:

- `issue_id`
- `issue_type`
- `severity`
- `blocking`
- `status`
- `target_asset_id`
- `target_asset_type`
- `target_asset_path`
- `source_system`
- `review_report_id`
- `review_report_path`
- `message`
- `fix_suggestion`
- `evidence_refs`
- `revision_task_candidate`
- `created_at`

Allowed issue types:

- `mkaos_conflict`
- `canon_conflict`
- `character_drift`
- `foreshadowing_drop`
- `plot_logic_gap`
- `pacing_collapse`
- `ai_style`
- `repetition`
- `platform_policy_risk`
- `source_leakage`
- `context_budget_overflow`

## Blocking Policy

- `critical` issues are blocking by default.
- `high` issues are blocking for MKAOS, Canon, source leakage, context budget, and plot logic.
- Active blocking statuses are `open`, `acknowledged`, and `in_revision`.
- Terminal statuses are `resolved`, `waived`, and `closed`.

## Integration

Service module:

- `src/novel_forge/modules/review_issue/service.py`

Integrated paths:

- Review service persists Review/MKAOS issues after ReviewReport write.
- MKAOS Canon conflict issue candidates can be persisted directly.
- Publish gate absorbs active blocking ReviewIssues.
- Release package fails closed when active blocking ReviewIssues exist.
- Editor final draft promotion checks active blocking ReviewIssues before writing final draft.

## API

Minimal endpoints:

- `GET /product/review-issues`
- `POST /product/review-issues`
- `PATCH /product/review-issues/status`

Existing inline ReviewReport issue status endpoint remains for compatibility.

## Limits

ReviewIssue is durable and blocking-capable, but LoopRun and Agent Center consumption happen in later phases.
