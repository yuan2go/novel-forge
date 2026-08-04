# Legacy to PostgreSQL Authority Migration Status

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

Status: `POSTGRESQL_AUTHORITY_BACKEND_CUTOVER_COMPLETE`

This status applies to the backend production boundary. It does not mean that all
Legacy source files have been deleted, that Web UI work was performed, or that a
real Provider, a long-form novel, multiple books, or a production deployment was
verified.

## Completion boundary

The standard development, Compose, CLI, API and Worker entrypoints now select
PostgreSQL Authority. A PostgreSQL failure fails closed. Legacy can only be
selected by the explicit compatibility CLI or `compose.legacy.yml --profile
legacy`; it is not a fallback and is not part of the default Compose plane.

The frozen-snapshot importer executes:

```text
SCAN -> CLASSIFY -> IMPORT_CANDIDATE -> SEMANTIC_CONVERT -> VALIDATE
     -> QUALIFY -> ACTIVATE | QUARANTINE -> RECONCILE
```

It preserves snapshot and record hashes, uses stable business identities, checks
project scope and references, routes ambiguous rights and oversized inline blobs
to quarantine, persists checkpoints, and replays without creating duplicate
AssetVersions.

## Current inventory result

| Field | Result |
|---|---:|
| Inventory schema | `legacy-authority-migration-inventory.v2` |
| Inventory rows | 450 |
| Artifact hash | `sha256:11aed5becfdc06f04773e9ba1c29405d9f22f982a8a1375e70f6360eefc75ae4` |
| Production blockers | 0 |
| Unclassified | 0 |
| Explicit compatibility | 445 |
| Import candidate only | 3 |
| Rebuildable | 2 |
| Web excluded | 2 |
| Unapproved dual write | 0 |

The 445 explicit-compatibility findings are code that remains available to the
explicit Legacy profile or frozen import/export tooling. Architecture tests prove
that this code is not reachable from Authority production entrypoints. This is
backend cutover evidence, not Legacy source-retirement evidence.

## Evidence levels

| Level | State | Evidence |
|---|---|---|
| CODE_DEFINED | true | settings, selectors, typed codecs, migration 0055, architecture gates |
| UNIT_PROVEN | true | complete unit suite and focused codec/cutover tests |
| POSTGRESQL_INTEGRATION_PROVEN | true | clean migration, conversion, reconciliation, pool/retry and query-plan tests |
| COMPOSE_SMOKE_PROVEN | true | clean-volume 11-service Authority plane |
| FAULT_INJECTION_PROVEN | true | crash/resume/replay, Worker restart, lease/fence and uncertain-effect recovery |
| REAL_PROVIDER_PROVEN | false | fixture/scripted Provider only |
| LONGFORM_PROVEN | false | not performed |
| PRODUCTION_VERIFIED | false | no production deployment or load/PITR proof |

## Remaining Legacy categories

- `production_blockers=0`
- `development_only=0` inventory rows
- `import_export_only=3`
- `test_fixture_only=0` inventory rows; synthetic migration fixtures remain in tests
- `web_excluded=2`; Web was neither launched nor modified as an Authority UI
- `explicit_compatibility=445`; retirement is optional cleanup after parity, not a
  backend production blocker
