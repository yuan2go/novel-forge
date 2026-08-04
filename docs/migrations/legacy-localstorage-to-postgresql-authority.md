# Legacy LocalStorage to PostgreSQL Authority Migration

Current implementation SHA:
`32e4fd1462509216273cf861c9c4f36a69eb15b4`

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

Frozen snapshots and records are hash-addressed. The typed registry classifies
59 Legacy types, but only 18 core types have real domain adapters. The remaining
41 are archival AssetVersion imports and are not described as domain-native.
Scope, two-pass references, independent approval and typed activation are
validated before domain admission. Unsafe or ambiguous data is quarantined with
original evidence. Durable phase evidence, compare-and-set resume and stable
identity/content hashing make replay idempotent.

Migration 0055 adds the initial conversion lifecycle; 0056 and 0057 add runtime
health and hot-query governance. Forward-only migration 0058 adds materialization
levels, durable phase/reference/decision/reconciliation records, real Worker
health fields and fenced Outbox claims. It requires a pre-migration backup;
restore that backup for rollback or add a forward fix.

## Explicit exclusions

This cutover does not include a Web UI, real Provider credential use, real novel
quality validation, long-form/multi-book proof, or production deployment proof.
