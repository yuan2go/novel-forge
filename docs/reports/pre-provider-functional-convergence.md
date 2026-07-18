# Pre-Provider Functional Convergence

Date: 2026-07-18. Source commit: `2e506f1467321e688d82365ef2734c9f70b7caaa`.

## Result

The bounded pre-provider implementation is functionally converged. The Authority
runtime now preserves a frozen ChapterPlan, represents explicit empty history as
typed AssetVersions, exposes Provider Adapter v2 control contracts, gives each
Quality group a governed context view, and completes Canon defer/reopen and
re-extraction generations. Worker supervision and split CI guard these boundaries.

This result is `fixture_proven` and `integration_proven` where the catalog says so.
It is not `real_provider_proven`, `longform_proven`, or `production_verified`.

## Evidence map

| Slice | Implementation | Focused proof | Status |
|---|---|---|---|
| ChapterPlan fidelity | `modules/chapter_authority/plan_domain.py`, codecs and handlers | `test_chapter_plan_fidelity.py`, PostgreSQL scheduler tests | integration proven |
| Typed empty state | `modules/production_preparation/typed_empty_state.py` | preparation and chapter-2 PostgreSQL tests | integration proven |
| Provider v2 | `modules/provider_control/`, Migration 0028 | scripted adapter and ExternalEffect PostgreSQL tests | protocol/fixture proven |
| Quality context | `modules/chapter_quality_authority/context_views.py` | quality context and full Saga tests | integration proven |
| Canon recovery | `canon_graph/approval_authority.py`, Migration 0029 | defer/reopen/re-extraction PostgreSQL tests | integration proven |
| Calibration foundation | `chapter_quality_authority/calibration.py` | deterministic calibration unit tests | implemented |
| Worker/CI guardrails | `command_kernel/worker_execution.py`, `core-os-ci.yml` | unit and architecture tests | implemented |

## Deferred boundary

No paid call, real-provider chapter, multi-chapter proof, external connector, or
external publish action ran. Provider-specific SDK capability conformance remains a
required part of the controlled single-chapter proof.

## Verification

- Unit discovery: 942 cases, exit 0; focused convergence slice: 35 cases, all pass.
- PostgreSQL focused suite: 35 cases covering Chapter/Content recovery,
  ExternalEffect, budgets, clean/legacy migrations, and schema; all pass.
- Architecture: 7 cases, all pass.
- `make lint`, `make validate`, `compileall`, Catalog/Coverage binding, and
  `git diff --check`: pass.
- CI workflow definition is locally validated by the same commands; hosted GitHub
  execution is not claimed because this task does not push.
