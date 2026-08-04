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
validator implementation or dependency invalidates the old record.

Approval takes only `migration_validation_id` as validation authority. It reloads
the record under lock and verifies run/item/version/source/target/adapter/latest-
valid/status bindings. The Decision persists Validation ID and result hash.
Activation reloads both Decision and Validation, checks their current bindings,
requires all references and domain dependencies to remain resolved/activated,
then records the same Validation identity in the domain transition.

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
archival/domain/run semantics. Both are forward-only; repair uses a new forward
migration.
