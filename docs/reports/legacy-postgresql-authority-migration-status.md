# Legacy to PostgreSQL Authority Migration Status

Current engineering status: `LEGACY_DOMAIN_MIGRATION_PARTIAL`.

PostgreSQL is the default fail-closed storage authority. Legacy has no default
read, write, silent-fallback or dual-write path; it is available only through an
explicit compatibility CLI/profile or the audited frozen-snapshot importer.

## Evidence levels

| Level | State | Evidence |
|---|---|---|
| `ARCHIVAL_NATIVE` | implemented | immutable scoped AssetVersion, source/target hash, basic schema envelope, Audit, Outbox, replay and quarantine |
| `DOMAIN_NATIVE` | implemented for 18 source types | real Book/Design, StoryDesign, Planning, Source, MKAOS and Project Authority paths |
| all registered types domain native | false | 41 mappings intentionally remain archival |

Every non-project-shell record begins as `IMPORTED`,
`PENDING_EVALUATION`, `NEEDS_REVIEW`. The durable state machine is:

```text
SCAN -> CLASSIFY -> IMPORT_CANDIDATE -> SEMANTIC_CONVERT -> VALIDATE
     -> QUALIFY -> ACTIVATE | QUARANTINE -> RECONCILE -> COMPLETE
```

Each phase stores version, timestamps, attempts, input/output hashes, evidence,
errors and next phase. Expected-version compare-and-set protects concurrent
advancement; resume starts at the last successful `next_phase`.

References resolve in two passes from Legacy business key through migration
item to Asset, AssetVersion and domain projection. Required missing,
cross-project and ambiguous references fail closed. Replay identity combines
run, source item, ordinal, relation and target version.

Independent approval persists actor, decision, reason, expected item version,
source hash, target AssetVersion, domain-validation evidence, idempotency key,
Audit and Outbox. Source self-assertions never activate an item.

## Current inventory

| Field | Result |
|---|---:|
| Inventory schema | `legacy-authority-migration-inventory.v3` |
| Inventory rows | 450 |
| Authority entrypoints | 15 |
| Transitive modules | 719 |
| Reachable files | 454 |
| Production blockers | 0 |
| Unclassified | 0 |
| Web excluded | 2 |

The static graph covers API, dependencies, CLI, all Worker groups, healthcheck,
callback/effect dispatch, console/Compose commands and static dynamic imports.
Guarded compatibility paths are retained as evidence, not erased from the graph.

## Remaining migration gaps

- `material_card`, `rule_card`, and `template_card` lack typed MKAOS projections.
- Canon, StoryState, Context, Draft/Review/Revision, Feedback, Publishing and
  Agent/Workflow historical records remain archival.
- Runtime system-call tracing of Legacy path access is not a release gate in this
  slice; static graph plus no Legacy mount/fail-closed tests are the current proof.
