# Authority Data Migration and Recovery Runbook

## Safety boundary

Never import a live writable LocalStorage tree. Take a filesystem snapshot, record its origin, make the snapshot recursively read-only, and back up PostgreSQL before admission. The importer is additive: it does not delete or activate source data.

## Preflight

1. Verify production uses PostgreSQL Authority and the target database has the complete migration chain.
2. Create and verify a PostgreSQL backup/restore point.
3. Copy the Legacy tree to a dedicated snapshot outside the live write path.
4. Record operator, workspace, source host, snapshot time and legal/rights context.
5. Make the snapshot read-only. Non-dry-run import rejects a writable root.

## Dry run

```bash
novel-forge authority-import-legacy --root /absolute/read-only/snapshot --dry-run
```

Review counts and every duplicate, conflict, missing reference, cross-project reference, rights rejection, parse failure and oversize decision. Dry run does not require a database and performs no production mutation.

## Import and resume

```bash
novel-forge authority-import-legacy --root /absolute/read-only/snapshot
novel-forge authority-import-status --migration-run-id MIGRATION_RUN_ID
```

The snapshot hash determines the stable migration run. Re-run the same command to resume after process or database restart. Terminal items are skipped; valid pending records retain stable idempotency keys. Do not alter the snapshot between runs—use a new frozen snapshot and migration run.

## Verification

```bash
novel-forge authority-verify-migration \
  --migration-run-id MIGRATION_RUN_ID \
  --root /absolute/read-only/snapshot
```

Verification must pass snapshot hash, item/target counts, target hashes, zero unexpected production activation and relationship/scope checks before any Legacy deletion. `IMPORTED/PENDING_EVALUATION` is expected and is not an error.

## Quarantine

```bash
novel-forge authority-quarantine-list --migration-run-id MIGRATION_RUN_ID
```

Quarantine is durable evidence. Resolve through a reviewed repair/reject decision; do not edit the row or discard payload evidence manually. A repaired source is imported as a new immutable version/run identity as appropriate.

## Recovery cases

- **Process interruption:** rerun import with the same snapshot; the run/item ledger resumes.
- **Duplicate invocation:** stable operation and item constraints replay without duplicate versions.
- **Hash mismatch:** stop, quarantine the item and investigate snapshot mutation or parser drift.
- **Cross-project reference:** quarantine; never silently re-scope.
- **Database restart:** wait for PostgreSQL health, then use status and rerun. No in-process cursor is authoritative.
- **Stale attempt fence:** reject the result and preserve late-result evidence.
- **Unknown external effect:** do not retry blindly; run the existing reconciliation protocol.
- **Retryable Operation:** `POST /product/tasks/{operation_id}/recover` with project ID, expected Operation version and stable idempotency key. The command is rejected on stale version, active lease or unsupported terminal state.
- **Outbox dead letter:** `POST /product/tasks/outbox/{outbox_id}/requeue` with project ID, expected attempt count and stable idempotency key. The source remains immutable dead-letter evidence; a new outbox generation is created. Do not update the old row manually.
- **Terminal Operation dead letter:** use the owning Chapter/Book/Content/Publishing Authority to admit a new Operation generation. Generic recovery intentionally fails closed.
- **Migration defect:** stop writes, restore the pre-migration database backup, remount the unchanged frozen snapshot, and rehearse the corrected forward migration in an isolated database.

## SourceDocument registration boundary

`POST /product/source-governance/documents` accepts object metadata only after the referenced `authority_blob` is `AVAILABLE` and its verified actual hash, size and object key match. The request must include project/workspace scope and a stable idempotency key. Unknown rights are expected to produce a quarantined Candidate; they must not be force-activated. If a prior Source operation exists but is not `SUCCEEDED`, recover or reconcile that Operation instead of registering a second document identity. Never paste raw source text into the registration request or a ContextBundle.

`POST /product/source-governance/documents/{source_document_id}/transforms` is a prepared-manifest commit boundary. Submit only ordered Chunk Blob identities with canonical Hash/size/counts and in-bounds evidence spans. Every Blob must already be `AVAILABLE`, text media, and project-scoped. The endpoint does not accept text and does not prove that a processor ran; preserve the external processor receipt separately until the processor ExternalEffect operation is implemented. Quarantined Sources and cross-project Chunk Blobs fail closed.

## Deletion gate

Delete a Legacy source path only after verification PASS, accepted quarantine disposition, count/hash/relationship reconciliation, replacement API/worker/frontend tests, restart recovery and an architecture inventory with no production dependency on that path. Keep a retention-controlled snapshot until the restore rehearsal is accepted.
