# Canon Snapshot, Final Release, and Content Recovery Implementation Plan

> **For Codex:** Execute this plan task-by-task with focused verification and single-scope commits. Do not run real providers or long-form generation.

**Goal:** Close the remaining authority proof gaps by materializing independent Canon state snapshots, gating release only after verified Blob delivery, and proving Content Authority recovery through the existing PostgreSQL Attempt scheduler semantics.

**Architecture:** Extend the shared authority handler envelope to atomically materialize one primary output plus deterministic auxiliary outputs in existing `authority_asset*` tables. Enrich frozen input assets with verified Blob bindings so a storage-free final release handler can validate the Export receipt. Add a Content Authority recovery application over existing Operation/Attempt/lease/fencing primitives; do not create a parallel scheduler or persistence model.

**Tech Stack:** Python dataclasses, PostgreSQL Command Kernel repositories, psycopg transactions, unittest/pytest fixtures, existing catalog generators.

---

## Task 1: Atomic multi-output authority materialization

**Files:**
- Modify: `src/novel_forge/modules/authority_handler_runtime/contracts.py`
- Modify: `src/novel_forge/modules/authority_handler_runtime/runtime.py`
- Test: `tests/integration/test_chapter_authority_runtime_postgres.py`

1. Add a typed auxiliary-output contract and a stable list of all materialized outputs to the execution result.
2. Validate unique `(output_key, role)` identities and reject malformed auxiliary output contracts.
3. Materialize primary and auxiliary outputs in one fenced transaction using `AuthorityHandlerRepository.materialize_output`.
4. Emit one operation event containing the complete output lineage; replay must create neither new versions nor duplicate events.
5. Run the shared authority runtime PostgreSQL test.

## Task 2: Independent Canon Snapshot AssetVersions

**Files:**
- Modify: `src/novel_forge/modules/canon_graph/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/runtime.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Test: `tests/unit/test_stateful_canon_domain.py`
- Test: `tests/integration/test_postgresql_only_chapter_slice.py`

1. Define explicit append-only snapshot types for Canon, character, relationship, timeline, foreshadow, promise, reward, world-rule, and power state.
2. Convert Canon reduction candidates into nine independent auxiliary outputs with version lineage, previous version references, rebuild and rollback metadata.
3. Require every snapshot selector in `chapter.canon.update` Completion; embedded candidates alone must not satisfy Completion.
4. Preserve legacy state type aliases as context inputs while preferring new snapshot asset types.
5. Assert the full chapter slice creates and qualifies all independent snapshot AssetVersions and that replay is idempotent.

## Task 3: Post-Blob Final Release Gate

**Files:**
- Modify: `src/novel_forge/storage/chapter_authority_repositories.py`
- Modify: `src/novel_forge/modules/authority_handler_runtime/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Modify: `src/novel_forge/modules/publishing/domain.py`
- Test: `tests/unit/test_chapter_authority_domain_handlers.py`
- Test: `tests/integration/test_postgresql_only_chapter_slice.py`

1. Include project-scoped Blob binding and verified receipt fields in frozen authority inputs.
2. Add `chapter.publishing.finalize_release` after Export in the Saga, consuming Export plus pre-release Review/Canon/Quality/Context evidence.
3. Fail closed unless the bound Blob is AVAILABLE, its expected and actual hash/size agree, the upload effect succeeded, and rollback metadata is present.
4. Materialize a `final_release_gate_report` that records accepted version IDs and the authoritative Blob/effect receipt while keeping external publication disabled.
5. Prove that tampered or missing Blob evidence blocks the gate and that the root Saga completes only after the final gate.

## Task 4: Content scheduler recovery proof

**Files:**
- Modify: `src/novel_forge/modules/content_authority/application.py`
- Add: `src/novel_forge/modules/content_authority/scheduler.py`
- Modify: `src/novel_forge/modules/content_authority/__init__.py`
- Add: `tests/integration/test_content_authority_scheduler_recovery_postgres.py`

1. Separate admission from one-attempt execution while preserving the current synchronous facade.
2. Add scheduler recovery methods that inspect authoritative Operation/Attempt/output state and either create a retry Attempt or take over an expired in-flight Attempt.
3. For crash-before-output, create a new Attempt/version after retryable failure; for crash-after-output-before-completion, replay the same deterministic output and then evaluate Completion.
4. Prove stale fencing rejection, lease takeover, idempotent output binding, audit/outbox uniqueness, and successful command replay.
5. Keep approval-blocked and exhausted operations fail closed with stable recovery error codes.

## Task 5: Evidence, catalog, and documentation convergence

**Files:**
- Modify: `docs/reports/content-authority-runtime-convergence.md`
- Modify: `docs/reports/core-functional-convergence-progress.md`
- Modify: `docs/reports/postgresql-domain-migration-matrix.md`
- Modify: `docs/project-current-state.md`
- Regenerate: `docs/reports/postgresql-operation-definition-catalog.json`
- Regenerate: `docs/reports/postgresql-authority-coverage-*.json`

1. Run focused unit, architecture, and PostgreSQL integration suites for the three slices.
2. Regenerate Catalog and Coverage Evidence from the final committed implementation.
3. Record exact implementation and test maturity; keep `real_provider_proven` and `longform_proven` false.
4. Run `git diff --check`, review the final diff, and commit documentation/catalog evidence separately.

