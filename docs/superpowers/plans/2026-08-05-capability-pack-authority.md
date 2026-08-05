# Capability Pack Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Capability Pack manifests, compilations, approvals, binding sets, deployments, activations, rollouts, and runtime resolution into PostgreSQL Authority without creating a second execution runtime.

**Architecture:** The existing deterministic compiler remains a pure function. A new Capability Pack Authority application loads immutable Manifest and Artifact Catalog AssetVersions, compiles outside the write transaction, then revalidates locked identities before storing the trusted Compilation AssetVersion and append-only registry facts. Deployments atomically CAS one complete Binding Set, while the Chapter Agent Runtime freezes the selected deployment, activation, binding set, scope, and canary assignment into its existing runtime binding.

**Tech Stack:** Python 3.11+, dataclasses, FastAPI, psycopg 3, PostgreSQL, pytest, Ruff, existing Command Kernel and Authority UoW.

## Global Constraints

- PostgreSQL is the only controlled-production Capability Pack authority.
- Capability Pack owns configuration lifecycle only; it must not create Run, Attempt, Lease, Fence, Retry, Worker, Workflow, Agent, Provider, or ExternalEffect runtimes.
- OperationDefinition retry, timeout, cancellation, compensation, permissions, completion, Attempt, Lease, Fence, and domain commit rules remain authoritative and cannot be overridden.
- Compilation is a pure function outside long database transactions; the write transaction rechecks all input identities.
- Binding Set activation is atomic and CAS-protected; historical Runtime Bindings are immutable.
- Scope precedence is BOOK, WORKSPACE, PROJECT, SYSTEM and fails closed on ambiguity or scope mismatch.
- Canary assignment is stable and append-only; automated rollback is not implemented.
- Fixture, real-provider, long-form, multi-book, and production evidence remain separately classified.

---

### Task 1: Authority domain and PostgreSQL registry

**Files:**
- Create: `src/novel_forge/modules/capability_pack_authority/domain.py`
- Create: `src/novel_forge/storage/capability_pack_authority_repositories.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260805_0071_capability_pack_authority.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `src/novel_forge/storage/authority_repositories.py`
- Test: `tests/unit/test_capability_pack_authority_domain.py`
- Test: `tests/unit/test_capability_pack_authority_migration.py`

**Interfaces:**
- Produces: immutable `CapabilityPackExecutionSnapshot`, `stable_rollout_bucket()`, `binding_set_hash()`, and `CapabilityPackAuthorityRepository` registration/approval/deployment/CAS methods.
- Consumes: existing `authority_asset`, `authority_asset_version`, `authority_operation`, Project/Workspace/Book scope, Audit/Event/Outbox tables.

- [x] Write unit tests for content identity, stable canary bucketing, scope invariants, immutable snapshot hashing, migration head, constraints, triggers, and absence of Pack runtime tables.
- [x] Run the tests and confirm they fail because the domain and migration do not exist.
- [x] Implement the domain contracts and the forward-only 0071 schema with indexed foreign keys, immutable triggers, append-only decisions, deployment history, and CAS activation pointers.
- [x] Add the focused repository to `AuthorityRepositories` and rerun the unit tests.

### Task 2: OperationDefinitions, registration, validation, trusted compilation, and approval

**Files:**
- Create: `src/novel_forge/modules/capability_pack_authority/definitions.py`
- Create: `src/novel_forge/modules/capability_pack_authority/application.py`
- Create: `src/novel_forge/modules/capability_pack_authority/__init__.py`
- Test: `tests/unit/test_capability_pack_authority_definitions.py`
- Test: `tests/unit/test_capability_pack_authority_application.py`

**Interfaces:**
- Produces: `CapabilityPackAuthorityCommand`, `CapabilityPackAuthorityApplication.execute()`, and registered `capability_pack.*` OperationDefinitions.
- Consumes: `load_capability_pack_payload()`, `ExplicitArtifactResolver`, PostgreSQL OperationDefinition snapshots, existing pure `CapabilityPackCompiler`, Authority AssetVersion and event repositories.

- [x] Write failing tests proving callers cannot submit a compiled payload, exact Manifest version identity is immutable, compiler/approver duties can be separated, approval binds the exact compilation hash, and rejected/revoked compilations cannot deploy.
- [x] Implement manifest and artifact-catalog AssetVersion registration through a Command Kernel transaction.
- [x] Implement structural/semantic validation and trusted compilation outside the write transaction, followed by locked identity revalidation and atomic Compilation AssetVersion/registry/outbox storage.
- [x] Implement append-only approve/reject/revoke decisions with exact hash, policy, evidence, scope, expiry, and principal evidence.
- [x] Run focused tests after each vertical slice.

### Task 3: Binding Set, deployment lifecycle, scope resolution, canary, rollback, and drift

**Files:**
- Create: `src/novel_forge/modules/capability_pack_authority/runtime.py`
- Create: `src/novel_forge/modules/capability_pack_authority/query.py`
- Modify: `src/novel_forge/modules/capability_pack_authority/application.py`
- Modify: `src/novel_forge/storage/capability_pack_authority_repositories.py`
- Test: `tests/unit/test_capability_pack_runtime_resolver.py`
- Test: `tests/integration/test_capability_pack_authority_postgres.py`
- Test: consolidated deployment/rollout coverage in `tests/integration/test_capability_pack_authority_postgres.py`

**Interfaces:**
- Produces: `CapabilityPackRuntimeResolver.resolve_active_deployment()`, `resolve_binding_set()`, `resolve_workflow_node()`, `resolve_agent_binding()`, `validate_runtime_admission()`, and `freeze_execution_snapshot()`.
- Consumes: approved trusted Compilation, active Agent Definitions, immutable Artifact snapshots, scope roots, and existing runtime facts for usage projection.

- [x] Write failing lifecycle tests for Register → Validate → Compile → Approve → Materialize → Deploy → Activate → Resolve.
- [x] Materialize one immutable all-node Binding Set and verify exact OperationDefinition, Agent Definition, Capability, Prompt, Skill, Tool, Context, Evaluation, Approval, Budget, Route, and commit-authority hashes.
- [x] Implement deterministic BOOK > WORKSPACE > PROJECT > SYSTEM resolution and explanation evidence.
- [x] Implement CAS activation, disable, deprecate, retire, revoke, rollback, stable canary assignment, pause/resume/complete, and fail-closed drift classification.
- [x] Add usage/cost/quality projection from existing Operation, Attempt, ExternalEffect, provider receipt, cost, quality, publish, reader, and domain-commit facts without creating Pack Run state.
- [x] Run real PostgreSQL lifecycle, concurrency, rollback, tamper, and failure-injection tests.

### Task 4: Chapter and Agent Runtime integration

**Files:**
- Modify: `src/novel_forge/modules/agent_runtime/contracts.py`
- Modify: `src/novel_forge/modules/agent_runtime/application.py`
- Modify: `src/novel_forge/modules/agent_runtime/chapter_binding.py`
- Modify: `src/novel_forge/modules/agent_runtime/repository.py`
- Modify: `src/novel_forge/modules/agent_runtime/definitions.py`
- Modify: `tests/integration/test_unified_agent_runtime_postgres.py`
- Test: `tests/unit/test_chapter_capability_pack_authority_boundary.py`

**Interfaces:**
- Consumes: `CapabilityPackExecutionSnapshot` from PostgreSQL resolution.
- Produces: immutable Agent Runtime Binding fields `capability_pack_deployment_id`, `capability_pack_activation_version`, `capability_pack_binding_set_id`, `capability_pack_binding_set_hash`, `capability_pack_scope_type`, and `capability_pack_assignment_ref`.

- [x] Write failing tests that controlled Chapter binding registration rejects `compiled_capability_pack` and direct per-node activation.
- [x] Change production Chapter binding registration to trusted `pack_id`, `pack_version`, `compilation_hash`, and `binding_set_ref` identities only; retain explicit fixture/bootstrap compatibility classification without silent fallback.
- [x] Resolve and freeze the Pack snapshot before Agent Runtime admission and compare exact prompt, skill, tool, context, evaluation, route, approval, budget, OperationDefinition, Agent Definition, and Capability hashes.
- [x] Persist the exact deployment/binding-set/assignment identities in the existing runtime binding and prove rollback leaves historical rows unchanged.

### Task 5: API, CLI, manifests, fitness tests, and documentation

**Files:**
- Create: `src/novel_forge/api/routers/capability_pack_authority.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/cli/__init__.py`
- Modify: `architecture/manifests/module-manifest.yaml`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`
- Modify: `architecture/manifests/fitness-policy.yaml`
- Modify: `architecture/manifests/legacy-surface-manifest.yaml`
- Test: `tests/unit/test_capability_pack_authority_api.py`
- Test: `tests/architecture/test_capability_pack_authority_boundaries.py`
- Create: `docs/reports/capability-pack-authority-implementation-report.md`

**Interfaces:**
- Produces: governed REST command/query endpoints and `novel-forge authority-capability-pack` CLI actions that call the application/query layer, never direct SQL.
- Consumes: trusted principal resolution, project permission scope, Authority API settings, and exact release identity.

- [x] Add manifest/version, validate/compile, approval, deployment, rollout, rollback, lifecycle, drift, and usage routes with idempotency keys and Operation IDs.
- [x] Add CLI register/validate/compile/approve/deploy/activate/rollback/inspect/drift/usage commands through the application/query services.
- [x] Add architecture tests forbidding inline production compiled payloads, direct node activation, LocalStorage, Pack runtime tables, policy overrides, and mutable historical snapshots.
- [x] Update all registries/manifests and write the implementation/evidence report with explicit non-claims.

### Task 6: Qualification, review, and atomic commit

**Files:**
- Modify only files introduced by Tasks 1-5 as required by test/review findings.

**Interfaces:**
- Produces: one exact-HEAD local evidence set and one atomic commit; no push.

- [x] Run focused Capability Pack and Agent Runtime unit tests, architecture tests, real PostgreSQL integration suites, targeted Ruff, compileall, Compose config, architecture manifests, and fitness checks.
- [x] Run the repository-required code review against start commit `4e941af430481baf64322c24e97cb1a828e996f1`; fix all high-confidence findings and rerun affected tests.
- [x] Run `git diff --cached --check`, create one atomic commit, confirm clean worktree, final migration head, and exact tested commit SHA.
- [x] Report fixture versus real PostgreSQL evidence and preserve `REAL_PROVIDER_PROVEN=false`, `LONGFORM_PROVEN=false`, `MULTI_BOOK_PROVEN=false`, and `PRODUCTION_VERIFIED=false`.
