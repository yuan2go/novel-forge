# Legacy LocalStorage to PostgreSQL Authority Migration

Current tested implementation SHA:
`53b10b896bb934298d1ca11571aa01f24f00a812`

Backend status: `POSTGRESQL_AUTHORITY_BACKEND_CUTOVER_COMPLETE`

The authoritative status and evidence are maintained in:

- [`../reports/legacy-postgresql-authority-migration-status.md`](../reports/legacy-postgresql-authority-migration-status.md)
- [`../reports/legacy-authority-migration-inventory.md`](../reports/legacy-authority-migration-inventory.md)
- [`../reports/native-migration-codec-registry.md`](../reports/native-migration-codec-registry.md)
- [`../reports/current-head-sha-baseline.md`](../reports/current-head-sha-baseline.md)

## Operating rule

PostgreSQL owns backend production commands and query projections. It is the
default for development and Compose. If it is unavailable, the runtime fails
closed; it does not import, read from, write to, or fall back to LocalStorage.

Legacy is retained only for explicit compatibility, frozen snapshot import,
export and synthetic fixtures. No permanent dual write is allowed.

## Migration contract

Frozen snapshots and records are hash-addressed. The typed codec registry maps
the currently used Legacy business types to native AssetVersion schema versions.
Scope, references, qualification and activation are validated before authority
activation. Unsafe or ambiguous data is quarantined with original evidence.
Checkpointed resume and stable identity/content hashing make replay idempotent.

Migration 0055 adds the native-conversion lifecycle and reconciliation evidence.
It is forward-only and requires a pre-migration backup; restore the backup and
replay the immutable snapshot if a restore is required. Migrations 0056 and 0057
add runtime health fields and worker hot-path indexes without changing domain
authority semantics.

## Explicit exclusions

This cutover does not include a Web UI, real Provider credential use, real novel
quality validation, long-form/multi-book proof, or production deployment proof.
