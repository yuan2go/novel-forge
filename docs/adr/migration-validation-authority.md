# ADR: Migration Validation Is a Server Authority Operation

- Status: Accepted
- Date: 2026-08-04

## Context

Legacy migration approval formerly accepted client-supplied domain validation
evidence. Checking its declared status and validator name could not prove that a
server validator had executed against the current item, source and target.

## Decision

`migration.item.validate` is a PostgreSQL Transaction Command. In one transaction
it locks the Migration Item, checks expected item version/source hash/target
AssetVersion, freezes adapter and validator implementation identity, executes the
server validator, calculates input/result hashes, and writes the Validation
aggregate, StateEvent, Audit, Outbox and item state.

The Validation aggregate is immutable by identity and has `PASS`, `FAIL`,
`STALE`, or `REVOKED` status. Its uniqueness binds item/version and validator
implementation. A newer item, source, target, reference resolution, adapter,
validator dependency manifest or target dependency invalidates the old record.
The implementation hash is derived from an explicit, versioned source-file
dependency manifest; unrelated repository commits do not invalidate it. An
already activated projection can be revalidated only by creating a new
append-only Validation record, never by rewriting the historical decision.

Approval takes only `migration_validation_id` as validation authority. It reloads
the record under lock and verifies run/item/version/source/target/adapter/latest-
valid/status bindings. The Decision persists Validation ID and result hash.
Activation reloads both Decision and Validation, checks their current bindings,
requires all references and domain dependencies to remain resolved/activated,
then records the same Validation identity in the domain transition. A Run-level
transaction advisory lock plus row locks retain this validation/decision/
dependency scope while the owning domain Authority commits. Explicit coordinated
UnitOfWork savepoints keep nested domain commands on the same PostgreSQL
connection, so this remains atomic even with the bounded one-connection
migration pool. Validation and Decision acquire the Run lock through the
Transaction Command guard before idempotency admission; `verify()` takes the
same lock before freshness reads. This single lock order prevents an admission
row lock and Run advisory lock from forming a deadlock cycle.

Client evidence may be retained as non-authoritative request context but can
never establish a pass.

## Consequences

- forged or stale client evidence cannot authorize activation;
- validation and decision replay are idempotent and auditable;
- validator upgrades make older evidence stale instead of silently reusing it;
- Story Design uses the reusable versioned validator suite rather than adapter-
  supplied booleans;
- archival-only types remain reviewable without being described as domain-
  validated.

Migration 0059 introduces the aggregate and binding. 0060 adds explicit
archival/domain/run semantics. Migration 0067 recovers archival identity for
already-activated rows only when the highest-authority candidate is unique, then
enforces the binding with a database CHECK. All are forward-only; repair uses a
new forward migration.
