# WP-LF-01 Unified Real Long-form Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run and prove a governed real-Codex three-chapter Planning-to-Replan vertical slice on the existing Production Execution Plane.

**Architecture:** Keep Planning, Chapter, and Reader domain contracts separate while sharing the existing Gateway, backend, Command Kernel ExternalEffect lifecycle, recovery, and evidence semantics. Add only the production compositions and governed packs that are absent, close Book deterministic command boundaries, and extend the existing proof infrastructure.

**Tech Stack:** Python 3.11+, PostgreSQL, MinIO, pytest/unittest, Command Kernel, Capability Pack Authority, Production Execution Gateway, Codex CLI.

## Global Constraints

- Do not add a second Gateway, Attempt/Lease/Fence runtime, provider runtime, Planning runtime, or longform orchestrator.
- Reader Outcome is not a Chapter Release node and Reader Judge remains `SHADOW`.
- Model I/O uses Attempt + Lease + Fence + ExternalEffect; deterministic Book mutation uses Transaction Command + CAS + Audit/Event/Outbox.
- `CONTROLLED_PROOF` evidence cannot prove reader calibration or real reader behavior.
- The only promoted target is `SHORT_LONGFORM_RUNTIME_PROVEN=true` when current-HEAD database and Codex evidence support every prerequisite.

---

### Task 1: Planning production execution composition

**Files:**
- Create: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/__init__.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `config/capability_packs/story_planning_pack.json`
- Create: `config/capability_packs/artifacts/story_planning_contract_catalog.json`
- Test: `tests/integration/test_story_planning_production_execution_postgres.py`
- Test: `tests/architecture/test_core_functional_loop_boundaries.py`

**Interfaces:**
- Consumes: `PlanningExecutionPreparer.prepare(...)`, `PostgresPlanningExecutionBundleResolver`, existing Capability Pack compiler/activation APIs and the existing execution-session factory.
- Produces: a production-composed `StoryPlanningGenerationApplication` whose five generator calls create governed PEP candidates.

- [ ] Write a PostgreSQL integration test that installs the Planning Pack, resolves all five generator nodes through the production composition, and independently asserts Operation, Attempt, Snapshot, WorkOrder/runtime binding, ExternalEffect, candidate, and activation evidence.
- [ ] Run the focused test and verify failure because no production Planning composition/preparer and Pack exist.
- [ ] Add the smallest Planning-specific execution preparer/binder over the existing Gateway/ExternalEffect mechanics and a five-node governed Pack/catalog.
- [ ] Run the focused integration and architecture tests until they pass with the scripted transport explicitly classified as fixture-only.

### Task 2: Independent governed Reader Outcome execution

**Files:**
- Create: `src/novel_forge/modules/book_followup_authority/execution.py`
- Modify: `src/novel_forge/modules/book_followup_authority/__init__.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `config/capability_packs/reader_outcome_pack.json`
- Create: `config/capability_packs/artifacts/reader_outcome_contract_catalog.json`
- Test: `tests/integration/test_book_followup_authority_postgres.py`
- Test: `tests/architecture/test_core_functional_loop_boundaries.py`

**Interfaces:**
- Consumes: `BookFollowupAuthorityApplication`, `ReaderOutcomeModelPort`, `ReaderJudgeRuntimeResolver`, Capability Pack Authority and the existing execution-session factory.
- Produces: an independent Reader Outcome pack snapshot and PEP invocation returning the existing three Reader assets without Chapter Pack membership.

- [ ] Add a failing integration test proving Reader Outcome resolves its own Pack and that SHADOW output cannot publish-block, Authority-commit, or mutate plans.
- [ ] Run the focused test and verify failure at the missing Reader governed binding.
- [ ] Implement the Reader-specific binding/model port using shared execution mechanics and compose it into Book Authority.
- [ ] Run focused Reader, Book-to-Chapter, and architecture tests until green.

### Task 3: Book durable mutation command boundary

**Files:**
- Modify: `src/novel_forge/modules/book_authority/application.py`
- Modify: `src/novel_forge/modules/book_authority/repository.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Test: `tests/integration/test_book_authority_postgres.py`
- Test: `tests/architecture/test_core_functional_loop_boundaries.py`

**Interfaces:**
- Consumes: public Book start/submit/accept/pause/resume/abort commands and `execute_transaction_command()`.
- Produces: idempotent transaction-command records with CAS, audit and event/outbox evidence for every durable mutation named by WP-LF-01.

- [ ] Add failing public-command tests and an architecture guard that identify each required mutation by command/event evidence and reject newly introduced direct production writes.
- [ ] Run focused tests and record the uncovered mutations.
- [ ] Move only uncovered durable changes into transaction handlers with stable keys, expected state/version predicates, audit and event/outbox emission.
- [ ] Run Book Authority, Supervisor, Replan and architecture tests until green.

### Task 4: Real-provider retry with frozen governance

**Files:**
- Modify: `src/novel_forge/modules/production_execution/backends.py`
- Modify: `scripts/run_real_capability_codex_proof.py`
- Test: `tests/unit/test_production_execution_backends.py`
- Test: `tests/integration/test_capability_pack_runtime_snapshot_postgres.py`

**Interfaces:**
- Consumes: Codex process evidence, Command Kernel retry classification and prior-attempt Capability Snapshot reuse.
- Produces: a proof-only controlled failure after measured usage/cost and before candidate acceptance, followed by a new successful Attempt with identical frozen governance.

- [ ] Add a failing backend/unit test for the explicit proof fault point and extend the PostgreSQL snapshot test to assert materialization equivalence across different Attempts.
- [ ] Implement a disabled-by-default injectable post-measurement retryable failure that persists process usage/cost evidence.
- [ ] Update proof evidence checks for same Operation, different Attempt, same snapshot/pack/materialization, two provider executions, one commit, and preserved failed-call ledger.
- [ ] Run focused retry and existing recovery tests until green without claiming timeout injection.

### Task 5: Three-chapter Recap/Replan/Resume proof

**Files:**
- Create: `scripts/run_short_longform_codex_proof.py`
- Modify: `tests/integration/test_core_functional_loops_postgres.py`
- Modify: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Test: `tests/integration/test_short_longform_runtime_postgres.py`

**Interfaces:**
- Consumes: production Planning composition, Book Supervisor, Chapter Authority, Book Followup, Longform Recap, `BookReplanCoordinator`, and formal PlanChange approval/activation.
- Produces: a schema-backed proof report tied to exact HEAD with nine prerequisite booleans, traces, receipts, token/cost totals, continuity hashes, Replan lineage and replay evidence.

- [ ] Add a failing PostgreSQL control-flow test for three sequential accepted chapters, Reader sidecars, ChapterGroup completion, formal Recap, controlled future-only Replan, new snapshot, resume and replay.
- [ ] Implement only missing Supervisor/scheduler wiring exposed by that test.
- [ ] Build the real proof command using formal bootstrap APIs and mark all bootstrap and controlled-deviation provenance explicitly.
- [ ] Run the proof against repository PostgreSQL/MinIO provider-validation infrastructure and retain a local report bound to the final commit candidate.

### Task 6: Final validation, review, and commit

**Files:**
- Modify only files required by findings from validation/review.

**Interfaces:**
- Consumes: complete diff from baseline `2b7c621416a726fdff765aa57f1655de618e0c58` and the approved design.
- Produces: a clean committed branch and evidence-backed final report.

- [ ] Run focused tests, PostgreSQL suite, architecture fitness, lint/format checks and full relevant test suite.
- [ ] Run two-axis standards/spec review against the baseline and fix all material findings.
- [ ] Re-run the real proof at the exact commit candidate; do not set any boolean true without matching database/receipt/trace evidence.
- [ ] Commit the verified change, confirm a clean worktree, and report final HEAD, evidence totals, booleans, limitations and next priorities.
