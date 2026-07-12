# PostgreSQL Authority Legacy Deletion List

Date: 2026-07-12

The complete file-and-symbol action inventory is generated in
[`postgresql-authority-legacy-actions.json`](postgresql-authority-legacy-actions.json).
It is derived from the same canonical baseline as coverage and is the source
for deletion/replacement work; this page is only the human summary.

These are final-cutover deletions or production exclusions, not early cleanup.

| Target | Reason | Replacement / proof |
|---|---|---|
| `src/novel_forge/storage/local.py` production use | JSON authority and write-through sync | test-only frozen-snapshot importer; architecture test proves no production import |
| `src/novel_forge/storage/postgres.py` sync APIs | PostgreSQL is currently indexed from LocalStorage | authoritative repositories and query services |
| `src/novel_forge/api/services/postgres_fallback_policy.py` | JSON fallback conflicts with fail-closed authority | fail-closed database health/availability policy |
| `src/novel_forge/workers/runtime.py` `sync_postgres_after_task` | post-task dual write | Outbox/Attempt result command |
| `src/novel_forge/workflows/industrial.py` `postgres_sync` | local-to-Postgres synchronization | explicit one-off frozen-snapshot migration tool |
| `IndustrialSettings.postgres_write_through/strict` | dual-write and strict-local modes | mandatory database configuration/health gate |
| `production_kernel/service.py` LocalStorage facade | JSON parent operation/idempotency source | PostgreSQL CommandKernel/UoW implementation |
| local asset index/read fallbacks in `api/services/product.py` and `api/app.py` | authority reads can silently fall back | PostgreSQL write/query repositories |
| legacy LocalStorage tests | encode obsolete production behavior | PostgreSQL unit/integration/E2E fixtures |

`storage/local.py` can survive only in a clearly named, non-production frozen
snapshot importer/test-fixture package. It must not be importable by production
runtime modules, images, workers, or command adapters.
