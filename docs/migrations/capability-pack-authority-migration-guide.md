# Capability Pack Authority Migration Guide

## Scope

Migrations `20260805_0071_capability_pack_authority` and
`20260806_0072_capability_pack_integrity_hardening` are forward-only. The first
adds PostgreSQL Pack registry, compilation, approval, Binding Set, deployment,
activation, rollout, assignment, deprecation, and Runtime Binding columns. The
second adds exact provenance constraints, versioned approval policy, ownership,
immutable dependencies, and the one-per-Attempt snapshot. Neither creates a new
Run, Attempt, Lease, Fence, or Worker, and neither rewrites historical runtime
facts.

## Bootstrap sequence

For each Pack version:

1. Register the Manifest, exact owner namespace, exact `upstream_packs`, and a content-authenticated Artifact Catalog through `capability_pack.manifest.register`.
2. Validate and compile only the explicit dependency graph against PostgreSQL OperationDefinitions using the running exact release SHA.
3. Register exact Agent Definition versions referenced by the Compilation.
4. Approve the trusted Compilation from a separate principal when duties separation is enabled, using closed `CapabilityPackApprovalScope.v1` and structured limitations.
5. Create a Deployment for an approval-authorized `SYSTEM`, `PROJECT`, `WORKSPACE`, or `BOOK` scope.
6. Activate with `expected_activation_version=0` for the first pointer, then use the returned version for every later promotion or rollback.
7. Verify drift and execute a real fixture Attempt admission so the immutable Attempt Snapshot and Runtime Binding chain are checked before enabling controlled Chapter traffic.

## Legacy Chapter binding boundary

`agent.chapter_binding.register` and `agent.chapter_binding.activate` are no longer controlled-production Pack authority. In validation, provider-validation, and production they fail with `CAPABILITY_PACK_DEPLOYMENT_REQUIRED`.

Development, test, and migration fixtures may temporarily use the old path only with an explicit `authority_mode` of `DEVELOPMENT_FIXTURE`, `LEGACY_MIGRATION`, or `BOOTSTRAP_ADAPTER`. There is no silent fallback. Production migration must create and activate a trusted Deployment. Chapter Attempt admission resolves and persists one immutable `CapabilityPackAttemptSnapshot`; Gateway, PEP contracts, and Agent Binding consume that same typed snapshot. The snapshot preserves the original Attempt execution Fence separately from the currently held Fence that authorizes first persistence; its trace/span and Audit/Event/Outbox are committed in the same Authority Unit of Work. Recovery reuses it without reading the current Activation or assigning the Book again. Pack activation never mutates the global legacy Chapter-node pointer.

## Rollout cutover

`capability_pack.rollout.complete` requires the current
`expected_activation_version`. It atomically promotes the candidate Activation
pointer and completes the Rollout in the same Authority Unit of Work. Runtime
resolution never treats `COMPLETED` as a second current pointer. A stale
Activation version fails closed and requires a new operator decision.

## Rollback and forward fix

Never delete or mutate historical Pack, Dependency, Assignment, Attempt Snapshot,
or Runtime Binding facts. To roll back, activate a previously approved Deployment
with the current expected activation version. Existing Attempt Snapshots and
Agent Runtime Bindings continue to reference the original Deployment and Binding
Set.

If a migration or content defect is discovered after release, preserve all facts, register a corrected Pack version or Compilation, approve it, create a successor Deployment, and switch the CAS pointer. Revoked compilations and revoked, retired, missing, or hash-drifted exact dependencies block new admission and require an explicit rollback decision.

## Verification commands

```bash
make postgres-authority-test-up
NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@127.0.0.1:55432/novel_forge_authority_test \
  uv run --extra test pytest -q \
    tests/integration/test_capability_pack_registration_compilation_postgres.py \
    tests/integration/test_capability_pack_approval_policy_postgres.py \
    tests/integration/test_capability_pack_activation_concurrency_postgres.py \
    tests/integration/test_capability_pack_scope_resolution_postgres.py \
    tests/integration/test_capability_pack_rollout_postgres.py \
    tests/integration/test_capability_pack_runtime_snapshot_postgres.py \
    tests/integration/test_capability_pack_integrity_constraints_postgres.py \
    tests/integration/test_capability_pack_dependency_postgres.py
make architecture-manifests-check architecture-fitness-check
```

These commands prove local code and local PostgreSQL behavior only. They do not establish real-provider, long-form, multi-book, or production qualification.
