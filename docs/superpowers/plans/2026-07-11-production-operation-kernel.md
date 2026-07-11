# Production Operation Kernel Implementation Plan

> **For agentic workers:** This plan is executed inline in the current session. Each task ends with a focused verification and an independently reviewable commit.

**Goal:** Persist one schema-backed `ProductionOperation` parent for every registered production dispatch, bind the normalized Execution Envelope to it, and make duplicate idempotency requests return the existing parent safely.

**Architecture:** Keep `ChapterProductionRun`, `WorkflowRun`, `AgentRun`, and `LoopRun` as child state authorities. Add only a parent operation record in `data/runs`; the Kernel creates it before routing and updates it after routing. The parent owns request identity, envelope evidence, child references, lifecycle projection, and recovery metadata; it does not duplicate child state machines.

**Tech Stack:** Python 3.12, stdlib `unittest`, dataclass schemas, `LocalStorage` JSON assets, existing OS Envelope v2 and runtime trace assets.

## Global Constraints

- Code and tests are the source of truth; historical reports remain evidence-insufficient until rechecked.
- Production environments fail closed when the Envelope is missing or incomplete.
- Existing child Run types remain state authorities; no fifth child state machine is introduced.
- Fixture/compatibility dispatch remains explicitly marked and cannot be reported as production evidence.
- Duplicate requests use `idempotency_key`; conflicting request payloads fail safely instead of mutating an existing operation.
- No raw source text, credentials, or generated runtime artifacts are committed.

---

### Task 1: Add the persisted ProductionOperation schema

**Files:**
- Modify: `src/novel_forge/schemas/assets.py`
- Modify: `src/novel_forge/schemas/base.py`
- Modify: `src/novel_forge/schemas/__init__.py`
- Modify: `src/novel_forge/core/constants.py`
- Test: `tests/unit/test_production_entrypoint_contract.py`

**Interfaces:**
- Produces `ProductionOperation` with required content fields: `operation_id`, `operation`, `state_owner`, `status`, `idempotency_key`, `request_digest`, `execution_envelope`, `input_refs`, `expected_output_types`, `created_at`, and `updated_at`.
- Valid statuses are `planned`, `running`, `checkpointed`, `needs_review`, `accepted`, `needs_revision`, `failed`, `recovering`, `cancelled`, and `completed`.

- [x] Add the dataclass, schema registry import/export, `production_operation -> runs` mapping, required fields, and status validation.
- [x] Add a schema test proving a valid parent is accepted and an invalid status or missing envelope is rejected.
- [x] Run `PYTHONPATH=src python3 -m unittest tests.unit.test_production_entrypoint_contract -v`.
- [x] Run `git diff --check` and commit `feat(kernel): add production operation parent schema`.

### Task 2: Persist and reconcile the Kernel parent operation

**Files:**
- Modify: `src/novel_forge/modules/production_kernel/service.py`
- Modify: `src/novel_forge/modules/production_kernel/entrypoints.py`
- Test: `tests/unit/test_production_entrypoint_contract.py`

**Interfaces:**
- `dispatch_production_operation(storage, operation, **command)` persists the normalized envelope before child routing.
- The response includes `production_operation_path`, `production_operation_id`, `idempotency_key`, and `kernel_route`.
- Reusing the same idempotency key and request digest returns the existing operation and child result without a second child dispatch.
- Reusing the same idempotency key with a different request digest raises a safe conflict.

- [x] Add stable request digest calculation over operation, project scope, envelope identity, input refs, expected outputs, and routable command refs (excluding transient flags).
- [x] Add lookup and write helpers using `storage.list_json("runs")`, scoped by project and idempotency key.
- [x] Persist `ProductionOperation` before routing with `status=running`, then update it to `completed` or `accepted` with child result and error/recovery evidence.
- [x] Make production responses and failures preserve the parent path so an operator can resume or inspect the child.
- [x] Add positive, duplicate, conflict, missing production envelope, and child failure tests.
- [x] Run `PYTHONPATH=src python3 -m unittest tests.unit.test_production_entrypoint_contract tests.unit.test_os_envelope_v2 -v`.
- [x] Run `git diff --check` and commit `feat(kernel): persist idempotent production operations`.

### Task 3: Record the current evidence and phase boundary

**Files:**
- Create: `docs/reports/autonomous-novel-os-phase-01-report.md`
- Modify: `docs/reports/novel-os-16-priority-issues-progress.md`
- Modify: `docs/reports/module-maturity-matrix.md`
- Modify: `docs/project-current-state.md`
- Modify: `docs/roadmap/current-roadmap.md`

- [x] Record code paths, focused tests, parent/child state authority, and the fact that only registered Kernel dispatches are covered.
- [x] Mark unregistered legacy/direct callers and industrial PostgreSQL transaction authority as `partial` or `evidence-insufficient`, not complete.
- [x] Run `make lint`, `make validate`, `git diff --check`, and the focused Kernel tests.
- [x] Commit `docs: record phase one kernel evidence`.

## Self-review coverage

This slice closes the Phase 1 parent-envelope persistence and idempotency gap. It intentionally does not claim universal CLI/API/Worker/Revision/Recap/Publish migration, Context Builder convergence, real provider calibration, or 10/30-chapter acceptance; those remain separate phases with their own evidence.
