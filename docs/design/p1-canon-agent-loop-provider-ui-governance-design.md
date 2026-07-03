# P1 Canon / Agent / Loop / Provider / UI Governance Design

Date: 2026-07-03

## Scope

This design deepens the Post-MKAOS industrialization slice without replacing existing MKAOS, Context Builder, Agent Scheduler, Loop Kernel, ReviewIssue, or publishing services.

Implemented areas:

1. Unified Canon Graph query and conflict checks across `canon_database`, `character_card`, `character_state_ledger`, `arc_plan`, `foreshadowing_graph`, `foreshadowing_thread`, `world_bible`, `continuity_bible`, `power_scale_rule`, and `fact_ledger`.
2. Agent Center operation coverage for context build, canon graph check, review-revision-publish loop, and provider fallback approval.
3. Loop Kernel main-chain loop type: `review_revision_publish`.
4. Provider fallback policy with fail-closed default, explicit approval, and cost prediction.
5. Domain governance editor controls for Canon, Character, Arc, Foreshadowing, and ReviewIssue assets.

## Canon Graph

Module: `src/novel_forge/modules/canon_graph/service.py`

Public functions:

- `build_canon_graph`
- `query_canon_graph`
- `check_canon_graph_conflicts`
- `persist_canon_graph_issues`

API:

- `GET /product/canon-graph/query`
- `GET /product/canon-graph/snapshot`
- `POST /product/canon-graph/check`
- `POST /product/canon-graph/issues`

Conflict output is normalized as ReviewIssue candidates and persisted through `persist_issue_candidates`. This keeps blocking behavior aligned with existing publish gate and release package gates.

## Agent Operations

Added local-service operation contracts:

- `build-context-bundle`
- `check-canon-graph`
- `run-review-revision-publish-loop`
- `preview-provider-fallback`
- `approve-provider-fallback`

These operations use existing `AgentTask` / `AgentRun` infrastructure and return schema-backed outputs where available.

## Loop Main Chain

New loop type: `review_revision_publish`.

Default steps:

1. `context_build`
2. `review_run`
3. `review_issue_gate`
4. `revision_plan`
5. `revision_apply`
6. `re_review`
7. `publish_gate`

The loop writes:

- `review_report`
- `revision_plan`
- revised `draft_chapter`
- re-review `review_report`
- `publish_gate_report`
- `loop_step`, `loop_checkpoint`, `loop_report`

The implementation is deterministic and schema-backed. Provider-backed review/revision can be substituted later behind the same LoopRun contract.

## Provider Fallback

Module: `src/novel_forge/modules/provider_fallback/service.py`

API:

- `POST /product/provider-fallback/preview`
- `POST /product/provider-fallback/approve`
- `POST /product/provider-fallback/resolve`

Rules:

- Silent fallback remains forbidden.
- Hard-stop behavior remains fail-closed.
- Fallback resolution requires a passed `provider_fallback_approval` gate.
- Preview computes usage and cost for primary and fallback candidates.

## UI Domain Editor

File: `web/admin/app/features/os/EditableAssetConsolePage.tsx`

The editable console now includes a `Domain Governance Editor` for:

- `canon_database`
- `character_state_ledger`
- `arc_plan`
- `foreshadowing_graph`
- `review_issue`

ReviewIssue consoles also expose `Bulk Governance Tools` backed by `/product/review-issues/status`.

## Tests

New and updated tests:

- `tests/unit/test_canon_graph.py`
- `tests/unit/test_provider_fallback_policy.py`
- `tests/unit/test_loop_kernel.py`
- `tests/unit/test_agent_scheduler.py`
- `tests/unit/test_product_api_routes.py`
- `web/admin/tests/feature-architecture.test.mjs`

## Non-goals

- No graph database migration.
- No replacement of Novel KG.
- No autonomous provider fallback.
- No full semantic inference engine for canon contradictions.
- No full visual graph editor in this slice.
