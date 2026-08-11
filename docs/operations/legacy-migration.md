# Legacy snapshot migration

Legacy support is an offline, migration-only surface. It cannot be registered in the production API or worker fleet and cannot be imported by production roots.

## Retained commands

```bash
novel-forge-migrate authority-import-legacy --root /read-only/snapshot --dry-run
novel-forge-migrate authority-import-legacy --root /read-only/snapshot
novel-forge-migrate authority-import-status --migration-run-id RUN_ID
novel-forge-migrate authority-verify-migration --migration-run-id RUN_ID --root /read-only/snapshot
novel-forge-migrate authority-quarantine-list --migration-run-id RUN_ID
```

`--dry-run` scans, parses, validates, hashes, and classifies records without requiring PostgreSQL or mutating production state. A real import requires `NOVEL_FORGE_DATABASE_URL`, a read-only snapshot root, and a valid release identity.

## Retained behavior

- deterministic snapshot scan and hash;
- necessary Legacy schema/codec/parser/validator and domain mapping;
- resumable run status;
- typed native materialization through the current Authority runtime;
- verification levels `ARCHIVAL_NATIVE`, `DOMAIN_NATIVE`, and `RELEASE_READY`;
- quarantine listing and reconciliation evidence.

Imported data does not become active merely because it decoded successfully. Codec validation, target materialization level, activation policy, and Authority acceptance remain explicit.

## Removed behavior

There is no Legacy product CLI, API, Celery application, workflow engine, Agent scheduler, production kernel, LocalStorage runtime, source/MKAOS pipeline, compose file, or UI. Do not recreate one as a bridge, facade, adapter, feature flag, or fallback.

The exact allowed files and retired paths are declared in `architecture/manifests/migration-surface-manifest.yaml`; architecture fitness enforces the boundary.
