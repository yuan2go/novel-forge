# Legacy to PostgreSQL Authority Migration Status

Implementation target: core domain migration qualification at migration head
`20260804_0067_activated_migration_archival_binding`. Remote proof is determined
by the exact-SHA CI artifact, not by a status sentence in this file.

## Materialization levels

| Level | Count | Meaning |
|---|---:|---|
| `DOMAIN_NATIVE` | 18 | server validation, independent decision, domain activation and projection reconciliation are implemented |
| `ARCHIVAL_NATIVE` | 41 | immutable scoped AssetVersion and archival reconciliation only; domain completion is not claimed |

Archival state and domain state are separate columns. `validation_scope` records
which contract was executed, and `run_completion_level` distinguishes
`ARCHIVAL_RECONCILED`, `DOMAIN_RECONCILED` and `RELEASE_READY`. Run status uses
`IMPORT_RUNNING`, `ARCHIVAL_RECONCILED`, `DOMAIN_REVIEW_PENDING`,
`DOMAIN_ACTIVATION_PARTIAL`, `DOMAIN_RECONCILED`, `QUARANTINED`, `FAILED` and
`CANCELLED`; the ambiguous legacy `SUCCEEDED` meaning is not used for new runs.

`verify(required_level=ARCHIVAL_NATIVE|DOMAIN_NATIVE|RELEASE_READY)` fails closed
unless the caller supplies the current source snapshot and its deterministic
hash matches the recorded run snapshot.
Domain verification requires pending-domain count, actual domain failures,
validation failures, reconciliation failures and required-reference failures all
to be zero.

## Validation and activation authority

`migration.item.validate` locks the item, freezes item/source/target/adapter/
validator identity, executes the server validator, hashes input/result, and
writes Validation, StateEvent, Audit and Outbox in one transaction. Validation
records have `PASS`, `FAIL`, `STALE` or `REVOKED` state.

Approval accepts a `migration_validation_id`, not client evidence. It reloads and
matches run, item/version, source hash, target version, adapter and latest valid
validator implementation. Activation reloads the Decision and Validation,
rechecks their bindings and all required activated dependencies, and records the
validation/result hash in the domain transition. Item, source, target, reference,
adapter, validator or dependency changes invalidate reuse.

## Structured references

Structured references carry business key, relation, optionality, expected source
and target type, expected content hash, cardinality and ordinal. Legacy strings
are normalized to explicit compatibility references and retain compatibility
evidence. Project/workspace, ambiguity, type, hash, cardinality and supported
relation checks fail closed. Required domain dependencies are topologically
activated; cycles quarantine the affected graph.

## Forward migration chain

| Migration | Purpose |
|---|---|
| 0059 | server-side Migration Validation aggregate and decision binding |
| 0060 | archival/domain item state and run completion semantics |
| 0061 | structured references and dependency graph |
| 0062 | non-business Runtime Job execution plane |
| 0063 | Outbox execution evidence, Worker health and fleet metrics |
| 0064 | Runtime Job composite execution identity and legacy run-state forward fix |
| 0065 | Runtime Job Attempt/Lease identity closure across job, lease, worker and fence |
| 0066 | Deferred reverse FK requiring every Runtime Job Attempt to own its exact Lease |
| 0067 | Recover immutable archival bindings for already-activated Domain items and enforce their presence |

All nine are forward-only, backup-required migrations with forward-fix recovery.
Migrations 0001–0058 are unchanged.

## Remaining boundary

The 41 archival types are not silently promoted. Legacy compatibility remains
explicit and non-default. Real Provider, production load/SLO, backup/PITR,
long-form, multi-book and autonomous Book Loop proof remain outside this release.
