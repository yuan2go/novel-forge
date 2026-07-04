# Production Fail-Closed Hardening Report

Date: 2026-07-04

## Problem

The generation main chain already had OS Envelope enforcement inside MKAOS pack build, but the flow adapters for Outline, ChapterPlan, Draft, and Review caught pack-build errors and converted them into warning fallback packets. That behavior is acceptable for dev/sample/compat paths, but it is not acceptable in production because a canonical chapter or review could continue without the governed MKAOS/Context Builder pack.

## Fix

The main flow services now accept explicit `environment` and `os_envelope` arguments and pass them into `build_flow_context_bundle`, which forwards them into `build_knowledge_pack`.

Updated paths:

- `src/novel_forge/modules/context_builder/service.py`
- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`
- `src/novel_forge/modules/drafting/service.py`
- `src/novel_forge/modules/review/service.py`
- `src/novel_forge/modules/os_envelope/service.py`

Behavior:

- Production without OS Envelope fails closed.
- Production with a valid OS Envelope proceeds and records enforced envelope metadata.
- Dev/sample/local compatibility paths still use warning fallback to avoid breaking legacy fixtures.

## Test Proof

Added coverage in `tests/unit/test_context_builder_mkaos_flow.py`:

- `test_production_context_builder_requires_os_envelope_and_can_use_enforced_envelope`
- `test_production_outline_fails_closed_on_mkaos_pack_failure`

These tests prove:

1. `build_flow_context_bundle(..., environment="production")` raises before pack fallback when no envelope is supplied.
2. The same call succeeds with a valid production envelope and records `os_envelope.status=enforced`.
3. `generate_outline(..., environment="production")` does not create an outline if MKAOS pack construction fails.

## Remaining Work

- Propagate production envelopes from more Agent Center and workflow scheduler operations instead of relying on service-level optional parameters.
- Add API request-level production envelope fields for draft/review generation surfaces.
- Audit non-MKAOS production write paths for any remaining compatibility fallback.
