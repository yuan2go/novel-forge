# Legacy Authority Migration Implementation Report

## Executive result

The repository now has an integration-proven Project/Workspace Authority, a fenced and resumable Legacy JSON intake path, PostgreSQL Task/System projections, audited Operation recovery and immutable Outbox dead-letter generation recovery, and the first Source Governance write slice: an already verified, project-scoped Blob can be admitted and registered as a governed `source_document` AssetVersion without copying raw source text into PostgreSQL. The Source API now performs Admission only; a standalone PostgreSQL Source Authority Worker executes and recovers the Operation through Attempt/Lease/Fence takeover. Cross-domain AssetVersion read projections and the production API boundary do not load legacy product routers. This is material migration progress, not full-domain completion.

The regenerated inventory reports:

- inventory rows: 459;
- code-evidence findings: 2,091;
- files with findings: 214;
- fallback findings: 54;
- sync findings: 13;
- unknown findings: 4;
- inventory artifact hash: `sha256:76cfee039ceafe1249bb5b6d6682b5fc306a6e4ce458587c32b2612fd6fcf92b`.

The hash excludes the volatile generation timestamp and is stable across repeated generation of the same canonical inventory content.

## Implemented files

Primary additions and changes:

- migrations `v20260801_0043_project_workspace_and_legacy_migration_authority.py` through `v20260801_0049_source_transform_fk_indexes.py`;
- Project Authority domain, definitions, application, repository and query modules;
- Legacy migration scanner, application, service and operation definition;
- Task Authority PostgreSQL query and recovery application modules;
- Source Governance domain, Operation definition, application, PostgreSQL repository/query and API router;
- Source Authority scheduler and standalone worker backed only by PostgreSQL Operation/Attempt/Lease state;
- production Project, Task/System and AssetVersion API routers with project-scope authorization;
- production app service wiring and product API request models;
- generic Authority handler lifecycle/qualification support;
- CLI import/status/verify/quarantine commands;
- executable JSON/Markdown inventory generator;
- unit, architecture and PostgreSQL integration tests;
- Task Center frontend identity display, versioned Operation recovery, and Outbox new-generation recovery controls;
- MKAOS frontend Source intake changed from raw-text Legacy POST to project-scoped verified-Blob registration, and its overview read changed to the PostgreSQL AssetVersion projection.

The exact working-tree list is obtained with `git status --short`; unrelated `.idea` modifications predated this work and are not part of the implementation.

## New tables and indexes

New tables: `authority_project`, `authority_workspace`, `authority_project_binding`, and `authority_legacy_migration_item`. Existing migration-run and quarantine tables receive resumability, scope, count, resolution and operation-reference columns. The migration adds query, unique active-binding, idempotency/resume, open-quarantine, foreign-key and prior missing-FK indexes. It expands the existing AssetVersion and qualification CHECK constraints without creating parallel version/qualification tables.

Migration 0044 makes every relational Project binding point to a unique `project_binding_record` AssetVersion. The active relation remains a partial-unique projection; assign/remove decisions retain Operation, qualification, audit, event and outbox evidence.

Migration 0045 adds `authority_outbox_recovery_command` and its project/outbox/time query index. Every command binds the immutable source dead-letter to one unique replacement Outbox generation, expected attempt count, trusted actor, reason, trace and correlation identity. The source row stays `dead_letter`; recovery creates a new `pending` row and never mutates away the failure receipt. Existing `authority_recovery_command` remains the sole Operation recovery ledger.

Migration 0046 adds `authority_source_document`. Its stable `source_document_id` is the existing `authority_asset` identity; its unique `asset_version_id` is the immutable `authority_asset_version`; and its Blob and creating Operation are foreign-keyed to the existing Authority tables. A project/content-hash unique constraint prevents duplicate document identity, while rights, governance, size and media-type constraints reject invalid state. PostgreSQL stores metadata, hashes, rights/governance decisions and the object reference only, never raw source bytes.

Migration 0047 aligns the shared AssetVersion lifecycle constraint with the existing handler contract by adding `CANDIDATE`. This lifecycle is required for quarantined or pending Source intake and does not make the version Active or production eligible. The migration also adds the Source Operation query index.

Migration 0048 adds `authority_source_transform` and `authority_source_chunk` as projections over the existing Asset/AssetVersion/Blob/Operation authorities. Neither table has raw or cleaned text columns: a Chunk retains only a verified Blob identity, Hash/size, deterministic counts and an in-bounds evidence span. A partial unique index allows one Active transform per SourceDocument. Migration 0049 is a forward follow-up that supplies the three foreign-key indexes found by the clean-database audit; it was added instead of rewriting an already applied 0048 migration.

## New Operation definitions

- `project_lifecycle.create@1.0.0`
- `project_lifecycle.update@1.0.0`
- `project_lifecycle.transition@1.0.0`
- `project_binding.assign@1.0.0`
- `project_binding.remove@1.0.0`
- `legacy_migration.asset.import@1.0.0`
- `source.document.register@1.0.1`
- `source.transform.commit@1.0.0`

All reuse Command Kernel admission, database idempotency, Attempt, Lease, fencing, StateEvent, Audit, Outbox and completion contracts.

## Migrated domains

- Project/Workspace identity, configuration snapshot, lifecycle, stage, health, count and production queries;
- Legacy JSON discovery, hashing, classification, resume ledger, import candidate and quarantine;
- Task Center and system health read authority;
- versioned/idempotent Operation recovery and immutable Outbox dead-letter generation recovery;
- verified-Blob SourceDocument registration, content-hash deduplication, deterministic rights classification, Candidate/Active isolation, qualification and Source projection;
- prepared Source transform manifest admission and verified Chunk-Blob commit with evidence spans; Chunk assets are `ACTIVE/INELIGIBLE/CLEAR` evidence-only inputs and cannot satisfy generic production qualification;
- analysis/context/manuscript/review/feedback/publishing/MKAOS/planning AssetVersion read projections.

The latter are read projections only. Their remaining legacy write commands are not represented as migrated.

## Removed and retained Legacy paths

No source data or broad Legacy module was deleted in this slice because reconciliation and call-chain replacement are incomplete. Production selection already excludes the legacy app and fails closed when production is not PostgreSQL. The development-only legacy app, old routers, Celery tasks and filesystem services remain compatibility code and are listed by the executable inventory. Their deletion condition is WP-12 zero reachable production dependencies plus reconciled imports and replacement tests.

## Migration and quarantine result

The PostgreSQL integration fixture imported two valid JSON records. Both became immutable `legacy_import_candidate` AssetVersions with lifecycle `IMPORTED`, eligibility/qualification `PENDING_EVALUATION`, and zero production activations. Re-running resumed the same migration run and created no duplicates. The fixture had zero quarantine items. Corrupt JSON, missing references, cross-project references and unauthorized source cases are covered by scanner unit tests, not claimed as production-data results.

No real repository Legacy dataset was mutated or imported during this change; therefore `legacy_data_reconciled=false` for production data.

The Source PostgreSQL fixtures registered one already `AVAILABLE` Blob as an `ACTIVE/ELIGIBLE/CLEAR` SourceDocument and replayed the stable command without creating another AssetVersion. Unknown rights produced a `CANDIDATE/NEEDS_REVIEW/QUARANTINED` source, and a cross-project Blob was rejected. Separate API/worker execution proved Admission leaves the operation `READY`; a new worker instance completed it from PostgreSQL. A crash fixture committed the Source output, expired the first worker lease, then proved a restarted worker acquired fencing token 2, replayed the existing output and retained one SourceDocument. Transform fixtures committed two verified text Blobs as evidence-only SourceChunk AssetVersions, rejected a quarantined Source and cross-project Chunk Blob, and stored no raw/clean text in PostgreSQL. Blob receipts were fixture setup, not proof of a real object-store adapter, upload callback or processor.

## Commands and actual results

```text
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.unit.test_project_authority_domain \
  tests.unit.test_project_authority_migration \
  tests.unit.test_legacy_migration_scanner \
  tests.unit.test_legacy_migration_cli \
  tests.unit.test_legacy_authority_migration_inventory
```

Result: passed.

```text
NOVEL_FORGE_DATABASE_URL=postgresql://.../novel_forge_authority_test \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.integration.test_authority_migrations_postgres \
  tests.integration.test_authority_project_workspace_postgres \
  tests.integration.test_authority_legacy_migration_postgres \
  tests.integration.test_authority_task_projection_postgres
```

Result for the focused changed slice: 15 tests passed. This includes a clean database through migration 0049, upgrade from migration 0007, idempotent Project and Binding commands, binding removal, stale-version/path rejection, import resume/reconciliation, Task/System projections, Operation recovery, immutable Outbox generation recovery, Source Hash replay, Candidate isolation, cross-project Blob rejection, API/worker separation, expired-Lease output replay and Source transform isolation.

The non-skippable PostgreSQL Authority gate was also run after migration 0049:

```text
make postgres-authority-test
```

The first full run after 0048 found three missing foreign-key indexes through the clean-database audit while the other 135 tests passed. Migration 0049 was added instead of mutating the already applied migration, and the focused clean/upgrade/Source suite then passed 8/8. The subsequent complete gate passed 136/136 tests in 150.669 seconds. The failed pre-0049 run is retained as migration-audit evidence and is not counted as proof.

Repository-wide validation also passed:

- `make test`: 1,365 Python tests passed with 9 skipped; 11 web tests passed with 1 optional Playwright test skipped.
- `make lint`: Python source/test compilation passed.
- `npm run lint` in `web/admin`: TypeScript check passed.
- `npm run build` in `web/admin`: Next.js production build passed and generated 74 static pages.
- Authority OpenAPI smoke generated 70 paths, including Source register/list/detail, transform commit/list and Chunk list routes, versioned Project binding query/assign/remove, Operation recovery and Outbox generation-requeue paths; all required product read paths were present.
- In-process PostgreSQL API smoke: 10 migrated read endpoints returned HTTP 200.
- project-scoped API denial smoke: Task, Asset, Project and cancellation endpoints all returned HTTP 403 for an out-of-scope project; cancellation ignores request-supplied actor identity.
- `make authority-parity-check`: passed using an isolated temporary Git index containing the new files; the user's real staging area was not modified. The raw working-tree invocation correctly reports new required files as untracked until they are committed.

The PostgreSQL suite includes existing complete-worker-restart fixtures, but a deployed supervisor/process restart drill was not executed in this slice. Real provider, real platform, browser Playwright and production deployment were also not executed.

## Remaining risks and failed/unrun proof

- 459 inventory rows remain and the Legacy finding goal is not zero.
- Project binding persistence and backend commands are implemented; a dedicated frontend binding editor and project-scoped Profile creation flow remain incomplete.
- several requested write APIs have only PostgreSQL read projections.
- legacy Celery/workflow/agent implementations remain in development compatibility code;
- Source registration and transform commit currently require existing `AVAILABLE` Authority Blobs. Object-store upload request/receipt API, the actual clean/chunk processor ExternalEffect, real binary import and production-data quarantine/reconciliation remain unproven. `source.transform.commit` validates and commits a prepared manifest; it does not claim to have executed the processor. The Source worker is integration-proven but has not been deployed under a real production supervisor.
- remaining MKAOS extraction, card/pack governance and ingestion pages still contain Legacy write paths; only the overview read and SourceDocument registration slice moved here.
- provider/platform receipts, restart recovery, one/three/ten-chapter regression and production deployment are unproven here.
- Operation dead letters still require the owning Authority to create a new Operation generation; generic recovery deliberately refuses to mutate a terminal Operation.

## Evidence matrix

```text
code_implemented=partial
unit_proven=true_for_changed_slice
integration_proven=true_for_changed_postgresql_slice
migration_proven=true_for_fixture_json_snapshot
restart_recovery_proven=integration_fixture_only
frontend_connected=partial_reads_plus_source_registration
authority_worker_proven=chapter_and_source_postgresql_scheduler_fixtures_only
real_provider_proven=false
longform_proven=false
production_verified=false
```

Accordingly, the full migration completion criteria are not met and must not be declared complete.
