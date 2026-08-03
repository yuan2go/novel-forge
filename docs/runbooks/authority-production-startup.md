# PostgreSQL Authority Production Startup Runbook

## Required configuration

```text
NOVEL_FORGE_ENVIRONMENT=production
NOVEL_FORGE_STORAGE_AUTHORITY=postgresql
NOVEL_FORGE_DATABASE_URL=postgresql://...
NOVEL_FORGE_APPLICATION_BUILD_ID=<immutable release id>
NOVEL_FORGE_COMMIT_SHA=<full 40-character sha>
```

Provider and object-store credentials belong to infrastructure adapters. Domain services must not read them. Start must fail when the production storage authority is not PostgreSQL or release identity is incomplete.

## Startup order

1. PostgreSQL and verified backup/restore capability.
2. Apply the complete forward migration chain from the release artifact.
3. Object store and external-effect adapters, if the enabled operations require them.
4. Redis/queue coordination and rebuildable retrieval services.
5. Authority outbox delivery, external-effect reconciliation/deadline probes and Authority workers, including `novel-forge-source-authority-worker` when Source intake is enabled.
6. PostgreSQL Authority API.
7. Frontend configured only for the Authority API.

Do not start Legacy Celery workers as production task authority. Qdrant/pgvector health cannot override a failed PostgreSQL qualification or project-scope check.

## Admission checks

- `GET /health` reports `storage_authority=postgresql` and no legacy storage loaded.
- `GET /product/system/authority-health` reports database readiness, worker freshness, outbox lag, dead letters and UNKNOWN effects.
- `GET /product/projects` and `/product/tasks` return PostgreSQL projections.
- `GET /product/tasks/recovery-workbench` returns recoverable Operations, UNKNOWN effects, Outbox dead letters and both recovery-command ledgers.
- `GET /product/source-governance/documents?project_id=...` reads the PostgreSQL Source projection. Source registration is admitted only for a verified `AVAILABLE` Blob; absence of an object-store receipt path must block raw-content intake rather than trigger a filesystem fallback.
- Source POST responses are Admission receipts, normally `READY`; worker liveness and completion must be observed through Operation/Attempt/Lease and the Source projection rather than an HTTP request thread.
- release Operation definitions match the current build ID and commit SHA.
- pending migrations, stale workers, dead letters, UNKNOWN effects, open blocking gates or unreconciled import runs block production admission.

## Shutdown and restart

Stop new admissions, request cancellation through Command Kernel, drain/record outbox and active effects, allow workers to release leases, then stop processes. After restart, recover exclusively from PostgreSQL Operation/Attempt/Lease/ExternalEffect/outbox state. Never reconstruct task state by scanning local files.

## Incident rules

- A worker result with an expired fence is rejected and retained as late-result evidence.
- UNKNOWN provider/platform state requires reconciliation before replay.
- callback/receipt duplicates are deduplicated by stable message/effect identity.
- Outbox dead-letter replay creates a new generation and retains the source dead letter; operators never reset rows directly.
- publishing status changes require verified external receipts.
- if PostgreSQL is unavailable, production commands fail closed; there is no fallback to the development legacy app.

## Current release caveat

The 2026-08-01 implementation report proves the changed Project/import/Task slice and verified-Blob SourceDocument registration only. It does not prove real object-store upload/receipt, Source clean/chunk, full MKAOS, or the remaining WP-02 through WP-13 cutover. Do not promote this branch as a full-domain release until those residual items and the report evidence matrix are complete.
