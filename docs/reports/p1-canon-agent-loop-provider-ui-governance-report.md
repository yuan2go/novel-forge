# P1 Canon / Agent / Loop / Provider / UI Governance Report

Date: 2026-07-03

## Summary

Completed a focused P1 governance pass for five requested areas:

| Area | Status | Evidence |
|---|---|---|
| Canon Graph 深化 | Done | `src/novel_forge/modules/canon_graph/service.py`, `/product/canon-graph/*`, `tests/unit/test_canon_graph.py` |
| Agent Center operation coverage | Done | `list_agent_operation_contracts`, `tests/unit/test_agent_scheduler.py` |
| Loop Kernel 主链迁移 | Done | `review_revision_publish` loop, `tests/unit/test_loop_kernel.py` |
| Provider fallback policy | Done | `src/novel_forge/modules/provider_fallback/service.py`, `tests/unit/test_provider_fallback_policy.py` |
| UI 领域编辑器 | Done | `web/admin/app/features/os/EditableAssetConsolePage.tsx`, `web/admin/tests/feature-architecture.test.mjs` |

## Functional Detail

### Canon Graph

Added a unified graph builder and conflict checker across Canon, Character, Arc, Foreshadowing, WorldRule, and Fact assets. Conflict checks produce ReviewIssue candidates and can persist them through the existing ReviewIssue service.

Current checks include:

- forbidden canon alias;
- character status contradiction;
- arc forbidden expansion;
- dropped or overdue foreshadowing reuse;
- world-rule forbidden term.

### Agent Center

Added local-service operation contracts for:

- context bundle build;
- canon graph conflict check;
- review-revision-publish LoopRun;
- provider fallback preview;
- provider fallback approval.

This increases production operation coverage without changing existing scheduler semantics.

### Loop Kernel

Added `review_revision_publish` as a first-class LoopRun type. It writes review, revision, revised draft, re-review, and publish gate outputs into the loop report.

Blocking ReviewIssue gates still stop the loop through the existing `review_issue_gate`.

### Provider Fallback

Fallback remains fail-closed. A fallback provider can only be resolved with a passed `provider_fallback_approval` gate. Preview includes cost prediction based on token usage and route fallback cost profiles.

### UI

The editable OS console now exposes typed fields for Canon, Character, Arc, Foreshadowing, and ReviewIssue content while preserving raw JSON editing for advanced use. ReviewIssue consoles support bulk status governance.

## Test Results

Passed:

- `python3 -m compileall -q src/novel_forge/modules/canon_graph src/novel_forge/modules/provider_fallback src/novel_forge/modules/agent_scheduler src/novel_forge/modules/loop_kernel src/novel_forge/api`
- `python3 -m unittest tests.unit.test_canon_graph tests.unit.test_provider_fallback_policy`
- `python3 -m unittest tests.unit.test_loop_kernel tests.unit.test_agent_scheduler`
- `python3 -m unittest tests.unit.test_provider_hard_stop_proof`
- `python3 -m unittest tests.unit.test_product_api_routes`
- `python3 -m unittest tests.unit.test_mkaos`
- `npm --prefix web/admin test`
- `npm --prefix web/admin run build`

Attempted but interrupted:

- `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Interrupted after several minutes while running `tests/integration/test_pipeline.py::test_sample_pipeline_runs`.
  - No assertion failure was emitted before interruption.
  - Focused backend, API, MKAOS, provider, Loop, Agent, and frontend tests above passed.

## Tradeoffs

- Canon Graph is a JSON-asset graph view, not a graph database. This is sufficient for local-first P1 governance and avoids a migration.
- `review_revision_publish` writes deterministic schema-backed outputs. Provider-backed editing can be routed behind the same loop contract later.
- Provider fallback approval is modeled as a `gate_result`, not a new asset type, so existing trace/gate tooling can read it immediately.
- UI batch governance is intentionally bounded to visible ReviewIssue assets to avoid accidental large bulk writes.

## Remaining Risks

| Risk | Priority | Next Step |
|---|---|---|
| Canon conflict semantics are rule/string based, not full causal inference. | P1 | Add Canon Graph semantic scorer and chapter-state comparison. |
| Main-chain LoopRun does not yet call provider-backed review/revision by default. | P1 | Add policy-controlled provider execution behind hard-stop and fallback approval. |
| UI typed editor still stores JSON-backed assets. | P2 | Add list-row editors for entities, clues, and issues. |
| Provider fallback approval has no expiry enforcement yet. | P2 | Enforce `expires_at` in `resolve_provider_fallback`. |
| Agent Center coverage is broader, but not every workflow node is migrated. | P2 | Add workflow-to-agent coverage matrix and migration gate. |
