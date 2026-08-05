# Capability Pack Authority Migration Guide

## Scope

Migration `20260805_0071_capability_pack_authority` is forward-only. It adds PostgreSQL Pack registry, compilation, approval, Binding Set, deployment, activation, rollout, assignment, deprecation, and runtime-binding snapshot columns. It does not rewrite existing Operations, Attempts, Agent runs, or historical Chapter node bindings.

## Bootstrap sequence

For each Pack version:

1. Register the Manifest and an inline, content-authenticated Artifact Catalog through `capability_pack.manifest.register`.
2. Validate and compile against PostgreSQL OperationDefinitions using the running exact release SHA.
3. Register and activate exact Agent Definitions referenced by the Compilation.
4. Approve the trusted Compilation from a separate principal when duties separation is enabled.
5. Create a Deployment for `SYSTEM`, `PROJECT`, `WORKSPACE`, or `BOOK` scope.
6. Activate with `expected_activation_version=0` for the first pointer, then use the returned version for every later promotion or rollback.
7. Verify drift and resolve a dry runtime snapshot before enabling controlled Chapter traffic.

## Legacy Chapter binding boundary

`agent.chapter_binding.register` and `agent.chapter_binding.activate` are no longer controlled-production Pack authority. In validation, provider-validation, and production they fail with `CAPABILITY_PACK_DEPLOYMENT_REQUIRED`.

Development, test, and migration fixtures may temporarily use the old path only with an explicit `authority_mode` of `DEVELOPMENT_FIXTURE`, `LEGACY_MIGRATION`, or `BOOTSTRAP_ADAPTER`. There is no silent fallback. Production migration must create and activate a trusted Deployment. Controlled runtime bindings freeze the selected Deployment, activation version, Binding Set, scope, and rollout assignment directly; Pack activation never mutates the global legacy Chapter-node pointer.

## Rollback and forward fix

Never delete or mutate historical Pack facts. To roll back, activate a previously approved Deployment with the current expected activation version. Existing Agent Runtime Bindings continue to reference the original deployment and Binding Set.

If a migration or content defect is discovered after release, preserve all facts, register a corrected Pack version or Compilation, approve it, create a successor Deployment, and switch the CAS pointer. Revoked compilations block new admission and require an explicit rollback decision.

## Verification commands

```bash
make postgres-authority-test-up
NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@127.0.0.1:55432/novel_forge_authority_test \
  .venv/bin/pytest -q tests/integration/test_capability_pack_authority_postgres.py
make architecture-manifests-check architecture-fitness-check
```

These commands prove local code and local PostgreSQL behavior only. They do not establish real-provider, long-form, multi-book, or production qualification.
