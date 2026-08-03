# PostgreSQL Authority Full-Domain Architecture

## Status and scope

This document defines the full-domain target and records the implemented cutover slice as of 2026-08-01. It is not a declaration that every Legacy implementation has been removed. The machine inventory currently contains 459 migration rows and 2,091 code-evidence findings; unresolved rows remain release blockers.

The production invariant is:

```text
PostgreSQL = business identity, lifecycle, version, governance and execution authority
Object store = immutable large-content bytes referenced by PostgreSQL
Qdrant / pgvector = rebuildable retrieval indexes
Redis = queue, cache and short-lived coordination
Local files = fixtures, explicit import snapshots, exports and non-authoritative cache only
```

Production API selection is fail-closed. `NOVEL_FORGE_ENVIRONMENT=production` requires `NOVEL_FORGE_STORAGE_AUTHORITY=postgresql`; the PostgreSQL app does not import product routers that instantiate filesystem storage.

## One execution kernel

All production commands reuse the existing Command Kernel identities and state machines:

```text
Command admission + database idempotency
  -> Operation / Saga
  -> Attempt
  -> Lease + fencing token
  -> deterministic Domain Handler or ProductionExecutionGateway
  -> Candidate / ExternalEffect
  -> validation + qualification + gate
  -> AssetVersion / receipt
  -> State Event + Audit + Outbox
  -> completion-contract verification
```

No domain may create a second Operation, Saga, Attempt, lease, fencing, ExternalEffect, AssetVersion, outbox or task-state system. A model/provider result is a Candidate. Activation is an Authority decision, never an implicit model side effect.

## Domain ownership map

| Domain | Authority aggregate / AssetType | Command family | Query source | Current status |
|---|---|---|---|---|
| Project / Workspace | `authority_project`, `authority_workspace`, `project_record`, `workspace_record`, `authority_project_binding` | `project_lifecycle.*` | PostgreSQL projection | Implemented and integration-proven |
| Legacy intake | `authority_migration_run`, `authority_legacy_migration_item`, `authority_data_quarantine`, `legacy_import_candidate` | `legacy_migration.asset.import` | PostgreSQL ledger | First JSON snapshot slice implemented and integration-proven |
| Source governance | `source_document`, `source_transform_manifest`, `source_chunk`, Blob/ObjectReference, rights decision | `source.document.register`, `source.transform.commit`; remaining `source.*` | PostgreSQL + object store | Verified-Blob SourceDocument and prepared Transform/Chunk commit integration-proven; upload and processor ExternalEffect pending |
| MKAOS | Knowledge/Rule/Template/Relation/Pack AssetVersions | `knowledge.*` | PostgreSQL; indexes rebuildable | Existing partial Authority assets; remaining Legacy calls inventoried |
| Context | `context_build_plan`, `context_bundle`, manifests and evidence | `context.*` | PostgreSQL projection | Read projection exposed; remaining write chain inventoried |
| Story design / planning | typed design and plan AssetVersions, dependency edges | existing Story Design and Plan Change authorities | PostgreSQL | Existing Authority core retained; Legacy generators remain inventoried |
| Chapter / review / revision | Chapter/Content Authority outputs | existing Chapter/Content operations | PostgreSQL | Production Authority app retained; old development routers remain isolated |
| Publishing | immutable gate/package and external receipt versions | publishing operations + ExternalEffect | PostgreSQL | Read projection exposed; remaining Legacy writes inventoried |
| Feedback / reader | import, exposure, outcome and attribution versions | feedback operations | PostgreSQL | Read projection exposed; remaining Legacy writes inventoried |
| Task / workflow / agent | Operation/Saga/Attempt/Lease/StateEvent/Outbox | Command Kernel and Authority workers | PostgreSQL projection | Task/health projection plus audited Operation/Outbox recovery implemented; wider Legacy scheduler code remains inventoried |

## Project and workspace rules

- `project_id` and `workspace_id` are stable business identities, not directory names.
- Current project/workspace snapshots are qualified `AssetVersion`s.
- projection updates and snapshot commits occur in the same transaction and under the current attempt fence.
- lifecycle is constrained to `ACTIVE`, `PAUSED`, `ARCHIVED`, or `DELETED`; deleted is terminal.
- project version and current AssetVersion are compared on update.
- non-empty keys ending in `_path`, `_file`, or `_directory` are rejected from Project Authority commands.
- active profile bindings use a partial unique index and point to immutable `project_binding_record` AssetVersions. Assign/remove commands are integration-proven; the dedicated frontend binding editor and project-scoped Profile creation flow remain pending, so WP-01 is not reported as fully product-complete.

## Imported-candidate boundary

The import lifecycle deliberately distinguishes historical intake from production activation:

```text
frozen read-only snapshot
  -> deterministic scan + sha256
  -> migration run/item ledger
  -> project shell (PAUSED/BLOCKED when reconstructed)
  -> fenced legacy_migration.asset.import Operation
  -> lifecycle=IMPORTED
  -> eligibility=PENDING_EVALUATION
  -> review / quarantine
```

`IMPORTED` AssetVersions are immutable and cannot satisfy production input qualification. A later reviewed command must create the accepted successor; the importer never edits or activates the imported version.

## Object and retrieval boundary

Large source bytes must be stored through the existing Blob/ObjectReference and external-effect protocol. PostgreSQL retains expected and actual hashes, sizes, object keys, receipts, legal hold and project scope. An index hit is only a candidate identifier: retrieval must resolve the referenced PostgreSQL AssetVersion and re-check lifecycle, qualification, governance and project scope before use.

The first Source write slice accepts only an existing Blob whose Authority state is `AVAILABLE` and whose actual hash, size and object key equal the requested Source metadata. It creates a `source_document` AssetVersion and rights qualification; raw text is absent from the operation payload and relational content. `ACTIVE/ELIGIBLE/CLEAR` is available only for deterministically recognized authorization classes. Unknown or forbidden rights remain Candidate/quarantined. The HTTP command performs Admission only; the Source Authority Worker reconstructs work from PostgreSQL and uses expired-Lease takeover with a new fencing token. This does not yet prove a real object-store upload/receipt adapter or source clean/chunk execution.

Prepared Chunk outputs enter through `source.transform.commit`: the command freezes Source version, normalization/chunking versions, policy Hash, ordered evidence spans and verified Chunk Blob identities. The Authority handler revalidates those receipts under its fence and creates a safe transform manifest plus `source_chunk` evidence assets. Chunk bytes never enter relational columns, and Chunk qualification is `INELIGIBLE` for generic production selection even though the evidence record itself is Active. A separate processor ExternalEffect remains required to claim actual cleaning/chunking execution.

## Query projections

The PostgreSQL production app now exposes Project/Workspace, Task/System health and cross-domain AssetVersion read projections. The Task Center joins Operation, latest Attempt, held Lease, Saga, StateEvent, ExternalEffect and outbox state. It does not inspect task JSON files or Celery state. Recoverable Operations use the existing versioned recovery ledger. Outbox dead-letter repair preserves the source row and creates one audited replacement generation; terminal Operations must be regenerated by their owning Authority. Generic cross-domain projections are read-only; absent Authority write operations fail by route absence instead of falling back.

## External side effects

Model, object-store and publishing-platform actions must pass through `ProductionExecutionGateway` and the existing ExternalEffect protocol. Stable effect identity, dispatch generation, provider correlation, receipt, callback deduplication, UNKNOWN reconciliation, cancellation and stale-fence rejection are mandatory. A `published` state is valid only after a verified receipt/callback; caller-declared publication is not evidence.

## Acceptance boundary

Full cutover is blocked until the inventory and release report prove all of the following, separately: zero production filesystem reads/writes, zero Legacy task authority, all write routes Authority-backed, importer replay/reconciliation, restart recovery, cross-project isolation, Authority worker operation, frontend route coverage, and one/three/ten-chapter fixtures. Fixture, PostgreSQL integration, real-provider and production proof are never interchangeable.
