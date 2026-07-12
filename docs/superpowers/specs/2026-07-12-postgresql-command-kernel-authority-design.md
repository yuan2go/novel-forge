# PostgreSQL Command Kernel Authority Design

## Status

Approved technical baseline for implementation planning. This design replaces
all production LocalStorage/JSON authority with a PostgreSQL Command Kernel.
It is the authority-boundary clarification for
`2026-07-12-production-foundation-and-provider-domain-design.md`; the two
documents are read together, and this document wins on storage and execution
authority where they would otherwise differ.

## Goal

Make PostgreSQL the sole production authority for business identity, state,
versions, lineage, production eligibility, object references and hashes,
approvals, gates, execution control, trace, audit and cost. Every enabled
production or governance side effect must enter the Kernel. PostgreSQL Read
Models are rebuildable projections and are never domain authority.

## Non-negotiable boundaries

- This is one whole-system hard cutover. Development may be implemented in
  dependency order, but no production-compatible intermediate, dual-write,
  JSON fallback, or per-family authority migration exists.
- API, CLI, workers, schedulers, event consumers, and external callbacks are
  adapters. They may not directly invoke a mutating domain service.
- LocalStorage and JSON are excluded from production runtime. The existing
  data is a **pre-refactor read-only frozen snapshot**, usable only as optional
  migration input and historical evidence.
- Kernel transactions are short. They admit commands, persist idempotency and
  policy/approval snapshots, change authority state, append events/audit,
  create Outbox rows, and commit. Models, tools, connectors, object storage,
  and publishing platforms execute outside the transaction.
- External work returns through controlled result commands using Attempt,
  Lease/fencing, Inbox/Outbox, ExternalEffect/Dispatch, and reconciliation.
- Future capabilities may stay closed. Every enabled `OperationDefinition` is
  a release blocker and must pass PostgreSQL-only acceptance.

## Architecture

```text
command adapters (API / CLI / worker / scheduler / callback)
                         |
                         v
                 PostgreSQL Command Kernel
 admission | authorization | approval snapshot | idempotency | short UoW
 operation graph | attempt/lease | gates | audit/trace/cost | state event/outbox
                         |
                         +------------------+------------------+
                         v                  v                  v
            domain write repositories  Outbox dispatcher   object/blob intent
                         |                  |                  |
                         v                  v                  v
                 PostgreSQL authority  external execution  immutable object store
                         ^                  |                  |
                         +----- controlled result command ---+

queries requiring authority -> PostgreSQL write model
list/search/dashboard      -> PostgreSQL Read Model + projection watermark
```

The Kernel is a control plane, not a God Service. Registered handlers retain
domain behavior. Operation families are `production`, `workflow`, `agent`,
`review`, `publishing`, `canon`, `context`, `quality`, `source`, `knowledge`,
`feedback`, `project_lifecycle`, `policy`, `portfolio`, and `ops`.

## ER model

```text
OperationDefinition (definition_id, definition_version)
       | snapshot-at-admission
       v
Operation 1 --- * Attempt 1 --- 0..1 Lease
    |  \              |
    |   \             +--- * ExternalEffectDispatch --- 1 ExternalEffect
    |    +--- * OperationDependency (parent/root/causation/saga/step)
    +--- * StateEvent
    +--- * AuditLog
    +--- * OutboxEvent --- * InboxReceipt (per consumer)
    +--- * ApprovalSnapshot / GateEvidence / CostEvidence

DomainAsset 1 --- * AssetVersion 1 --- * AssetVersionBlobReference * --- 1 Blob
                         |
                         +--- * AssetQualification

Saga/Workflow 1 --- * Operation
ReadModelProjection consumes OutboxEvent and records projection_watermark
AuthorityCoverageManifest is an immutable build artifact; its hash is recorded
in PostgreSQL ReleaseEvidence, but the database row is not the proof itself.
```

`Operation` carries `operation_id`, `parent_operation_id`, `root_operation_id`,
`causation_operation_id`, `workflow_id`, `saga_id`, `step_key`, and explicit
dependency rows (`depends_on_operation_id`, dependency condition). These make
parent/child execution and causality auditable without overloading a domain
state machine.

## Authority data model

### Asset versions and qualifications

AssetVersion has three independent, immutable-history dimensions:

| Field | Values | Meaning |
|---|---|---|
| `lifecycle` | `DRAFT`, `ACTIVE`, `SUPERSEDED`, `RETIRED`, `DELETED` | Version lifecycle |
| `eligibility` | `PENDING_EVALUATION`, `ELIGIBLE`, `INELIGIBLE`, `REVOKED` | Production qualification |
| `governance` | `CLEAR`, `QUARANTINED`, `REJECTED`, `LEGAL_HOLD` | Governance isolation |

Only `ACTIVE + ELIGIBLE + CLEAR` may enter production context, a Gate, or a
release. `AssetQualification` records the qualifying policy version, evaluator,
input hashes, evidence references, decision, and timestamp. Historical access
policy is separate from these fields; it does not make a version eligible.

Active versions and Blob references are append-only. A change creates a new
AssetVersion and new immutable references; neither an activated version nor an
existing reference is modified in place.

### Blobs and object storage

Object storage is a byte store only. PostgreSQL makes an object usable by
recording its identity, expected hash/size/key, integrity proof, lifecycle, and
references. Blob states:

```text
PENDING_UPLOAD -> UPLOADING -> UPLOADED -> VERIFYING -> VERIFIED -> AVAILABLE
       |              |            |             |             |
       +------------> FAILED <-----+-------------+-------------+
       +------------> ABANDONED
AVAILABLE -> CORRUPT
AVAILABLE -> DELETE_PENDING -> DELETED
```

An upload intent and its `external_effect_id` are created in the Kernel UoW.
The external upload result is verified against actual object key, hash and
size before `AVAILABLE`. `AssetVersionBlobReference` is the sole asset/blob
relationship and records version, blob, role, ordinal, media type and hash.
Blob deletion must prove no effective AssetVersionBlobReference, audit evidence,
release evidence, provider evidence, or Legal Hold reference remains. Otherwise
the deletion command is rejected.

### External effects

`ExternalEffect` represents one logical side effect. `ExternalEffectDispatch`
represents a concrete delivery generation. Both retain immutable request,
response and uncertainty evidence.

| Entity | State machine |
|---|---|
| `ExternalEffect` | `REQUESTED -> DISPATCHABLE -> IN_FLIGHT -> SUCCEEDED | FAILED | RECONCILIATION_REQUIRED | CANCELLATION_REQUESTED | CANCELLED | COMPENSATION_REQUIRED | COMPENSATED` |
| `ExternalEffectDispatch` | `CREATED -> SENT -> ACKNOWLEDGED -> SUCCEEDED | FAILED | TIMED_OUT | UNKNOWN | CANCEL_REQUESTED | CANCELLED | SUPERSEDED` |

Only when the prior dispatch explicitly failed, the provider's external
idempotency guarantee applies, or reconciliation proves safe may a new
generation be created. Every Dispatch has a unique `(external_effect_id,
generation)` and stores a stable idempotency key, provider correlation ID,
external receipt ID, payload hash and reconciliation evidence. An `UNKNOWN`
dispatch never permits blind retry.

## Kernel execution model

### Operation, Attempt, Lease

Operation is domain-neutral and is distinct from the state machines of Review,
Revision, Canon, publishing, and other domains. Those workflows use child
Operations and Saga orchestration.

| Entity | States |
|---|---|
| `Operation` | `ADMITTED`, `WAITING_APPROVAL`, `READY`, `WAITING_CHILDREN`, `EXECUTING`, `WAITING_EXTERNAL_RESULT`, `WAITING_GATE`, `CANCELLATION_REQUESTED`, `COMPENSATION_REQUIRED`, `RECONCILIATION_REQUIRED`, `COMPLETED`, `CANCELLED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `DEAD_LETTER` |
| `Attempt` | `CREATED`, `QUEUED`, `LEASED`, `RUNNING`, `CHECKPOINTED`, `RESULT_SUBMITTED`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `TIMED_OUT`, `LEASE_LOST`, `CANCELLED`, `SUPERSEDED`, `LATE_RESULT_REJECTED` |
| `Lease` | `AVAILABLE`, `HELD`, `RELEASED`, `EXPIRED` |

An Attempt only records one Worker execution. It never represents domain
reconciliation. A retry creates a new Attempt; an Operation has at most one
effective (nonterminal) Attempt at any time. Acquiring a Lease atomically
increments the fencing token. Worker checkpoints and results must carry the
current token. Stale writes are rejected and recorded as `LATE_RESULT_REJECTED`.
External callbacks do not use Worker fencing; they validate effect ID,
generation, stable external idempotency key, and external receipt ID.

### Cancel, reconciliation, compensation

Cancel is a versioned Kernel command with idempotency, actor, rationale, and
optimistic-concurrency precondition; it is never a direct field mutation. It
prevents new attempts and signals the active attempt. If no external effect was
started, or cancellation is authoritatively confirmed, the Operation becomes
`CANCELLED`. If an external effect may have succeeded, the Operation enters
`RECONCILIATION_REQUIRED`; if a defined compensator is needed, it enters
`COMPENSATION_REQUIRED` and creates a compensating child Operation. A final
state is only written after evidence resolves the external state.

### State transition table

| Entity | From | Allowed transition | Guard / result |
|---|---|---|---|
| Operation | `ADMITTED` | `WAITING_APPROVAL`, `READY`, `FAILED_FINAL` | admission snapshot and validation persisted |
| Operation | `WAITING_APPROVAL` | `READY`, `CANCELLED`, `FAILED_FINAL` | approval accepted, cancelled, or rejected |
| Operation | `READY` | `EXECUTING`, `WAITING_CHILDREN`, `CANCELLATION_REQUESTED` | leaseable Attempt, dependency wait, or versioned cancel |
| Operation | `EXECUTING` | `WAITING_EXTERNAL_RESULT`, `WAITING_GATE`, `WAITING_CHILDREN`, `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `CANCELLATION_REQUESTED` | handler result and frozen Completion Contract |
| Operation | `WAITING_CHILDREN` | `EXECUTING`, `WAITING_GATE`, `COMPLETED`, `FAILED_FINAL`, `CANCELLATION_REQUESTED` | child/Saga dependency outcome |
| Operation | `WAITING_EXTERNAL_RESULT` | `EXECUTING`, `COMPLETED`, `FAILED_RETRYABLE`, `RECONCILIATION_REQUIRED`, `CANCELLATION_REQUESTED` | validated Effect/Dispatch result |
| Operation | `WAITING_GATE` | `COMPLETED`, `FAILED_FINAL`, `CANCELLATION_REQUESTED` | required gate/approval evidence |
| Operation | `FAILED_RETRYABLE` | `READY`, `FAILED_FINAL`, `DEAD_LETTER`, `CANCELLATION_REQUESTED` | new Attempt, retry exhaustion, or cancel |
| Operation | `CANCELLATION_REQUESTED` | `CANCELLED`, `RECONCILIATION_REQUIRED`, `COMPENSATION_REQUIRED` | all effects absent/cancelled, unknown, or compensator required |
| Operation | `RECONCILIATION_REQUIRED` | `EXECUTING`, `COMPLETED`, `FAILED_FINAL`, `COMPENSATION_REQUIRED`, `CANCELLED` | reconciliation evidence resolves all effects |
| Operation | `COMPENSATION_REQUIRED` | `WAITING_CHILDREN`, `COMPLETED`, `FAILED_FINAL`, `RECONCILIATION_REQUIRED` | compensating child outcome |
| Attempt | `CREATED` | `QUEUED`, `CANCELLED`, `SUPERSEDED` | scheduler acceptance |
| Attempt | `QUEUED` | `LEASED`, `CANCELLED`, `SUPERSEDED`, `TIMED_OUT` | worker claim / cancellation / deadline |
| Attempt | `LEASED` | `RUNNING`, `LEASE_LOST`, `CANCELLED`, `TIMED_OUT` | current fencing holder starts / lease expiry |
| Attempt | `RUNNING` | `CHECKPOINTED`, `RESULT_SUBMITTED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `TIMED_OUT`, `LEASE_LOST`, `CANCELLED` | current fencing token required |
| Attempt | `CHECKPOINTED` | `RUNNING`, `RESULT_SUBMITTED`, `LEASE_LOST`, `TIMED_OUT`, `CANCELLED` | checkpoint belongs to active fencing token |
| Attempt | `RESULT_SUBMITTED` | `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `LATE_RESULT_REJECTED` | Kernel validates result and Completion Contract |
| Lease | `AVAILABLE` | `HELD` | atomic acquisition increments fencing token |
| Lease | `HELD` | `RELEASED`, `EXPIRED` | owner release or deadline |
| ExternalEffect | `REQUESTED` | `DISPATCHABLE`, `CANCELLATION_REQUESTED` | intent persisted |
| ExternalEffect | `DISPATCHABLE` | `IN_FLIGHT`, `CANCELLATION_REQUESTED` | eligible Dispatch created |
| ExternalEffect | `IN_FLIGHT` | `SUCCEEDED`, `FAILED`, `RECONCILIATION_REQUIRED`, `CANCELLATION_REQUESTED`, `COMPENSATION_REQUIRED` | validated Dispatch/reconciliation result |
| Dispatch | `CREATED` | `SENT`, `CANCELLED`, `SUPERSEDED` | outbox consumer owns dispatch |
| Dispatch | `SENT` | `ACKNOWLEDGED`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `UNKNOWN`, `CANCEL_REQUESTED` | transport/provider evidence |
| Dispatch | `UNKNOWN` | `SUCCEEDED`, `FAILED`, `CANCELLED`, `SUPERSEDED` | reconciliation only |

### Completion Contract

Each `OperationDefinition` contains a versioned Completion Contract. A complete
copy is frozen into the Operation at admission together with operation/handler
schema versions, authorization and approval policy, provider/source/quality/
budget policies, input asset-version hashes, concurrency key, idempotency scope
and digest, actor, and correlation/causation IDs.

Completion requires, in one or more authoritative short transactions:

1. required domain state/version and child/saga dependency state;
2. required active, eligible, clear AssetVersions and AVAILABLE verified Blobs;
3. required approval and Gate evidence;
4. terminal/reconciled ExternalEffects where applicable;
5. Trace, Audit, and Model/Cost evidence where applicable; and
6. required StateEvent and Outbox rows committed.

It does **not** wait for a final-consistency Read Model projection.

## Command and event schemas

### OperationDefinition

```json
{
  "name": "publishing.submit",
  "definition_version": "1.0.0",
  "family": "publishing",
  "command_schema_version": "1.0.0",
  "handler_version": "1.0.0",
  "required_permissions": ["publishing.submit"],
  "approval_policy_version": "publish-v3",
  "idempotency_scope": "project:operation",
  "concurrency_key_template": "project:{project_id}:release:{release_id}",
  "attempt_policy": {"max_attempts": 3, "lease_seconds": 60},
  "external_capabilities": ["publisher.submit"],
  "completion_contract_version": "1.0.0",
  "compensation_handler_version": "1.0.0",
  "enabled": true
}
```

### CompletionContract

```json
{
  "version": "1.0.0",
  "required_domain_states": [{"aggregate": "release", "state": "submitted"}],
  "asset_requirements": [{"role": "release_package", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}],
  "blob_requirement": "verified_available",
  "required_approvals": ["publish_approval"],
  "required_gates": ["publish_gate"],
  "external_effect_requirement": "terminal_or_reconciled",
  "required_evidence": ["trace", "audit", "cost_when_provider_used"],
  "required_outbox_topics": ["release.submitted"]
}
```

### AuthorityCoverageManifest

The manifest is generated by the build, not authored in the database. It is
immutable JSON containing build/commit identity, generator version, discovered
and enabled OperationDefinitions, API/CLI/worker/scheduler/callback/consumer
entrypoints, each entrypoint's Kernel route, static-architecture test results,
runtime registry dump, E2E evidence IDs, and every detected bypass/unknown path.
The build signs/hashes the artifact and writes the hash plus artifact locator to
PostgreSQL ReleaseEvidence. Release is blocked unless unknown paths and Kernel
bypasses are both zero.

```json
{
  "schema_version": "1.0.0",
  "git_sha": "40-character source commit SHA",
  "enabled_operation_definitions": [{"name": "registered operation name", "version": "definition version"}],
  "entrypoints": [{"kind": "api|cli|worker|scheduler|callback|consumer", "symbol": "fully qualified symbol", "kernel_definition": "registered operation name"}],
  "static_architecture_tests": [{"name": "test identifier", "passed": true}],
  "runtime_registry_hash": "sha256 digest of runtime registry artifact",
  "e2e_evidence": ["immutable test evidence identifier"],
  "unknown_write_paths": [],
  "kernel_bypasses": [],
  "artifact_hash": "sha256 digest of this manifest's canonical JSON"
}
```

## Inbox, Outbox, and reads

At-least-once is the delivery model. A consumer's Inbox insert/check on
`(consumer_name, message_id)`, the consumer's authority writes, StateEvent,
Audit, and successor Outbox entries happen in one short transaction. A duplicate
message with the same payload hash safely ACKs; the same message ID with a
different hash is rejected and raises an alert.

Write-model reads provide read-your-writes for command responses, gates,
approvals and concurrency decisions. Read Models consume Outbox, are explicitly
eventually consistent, and carry `projection_watermark`. List/search/dashboard
requests may require a minimum watermark; if unmet, return pending or read the
authority model for the bounded request.

## Database invariants

1. Partial unique index: one active/nonterminal Attempt per Operation.
2. Lease fencing token is monotonic per Attempt/Operation acquisition.
3. Unique `(idempotency_scope, idempotency_key)`; differing request digest is
   rejected rather than replayed.
4. Unique `(consumer_name, message_id)` Inbox identity; mismatched payload hash
   is a constraint-visible security/operations alert.
5. Unique `(external_effect_id, generation)` for ExternalEffectDispatch.
6. Partial unique index: one `ACTIVE` AssetVersion per Asset.
7. Database triggers/repository guards prohibit in-place mutation of activated
   AssetVersion and AssetVersionBlobReference records.
8. Unique `(aggregate_type, aggregate_id, aggregate_version)` StateEvent.
9. Blob deletion requires a transactional anti-join proving no effective asset,
   audit, release, provider-evidence, or Legal-Hold reference.
10. Result commands require current Attempt fencing or valid Effect/Dispatch
    generation/receipt identity before state transition.

## Whole-system hard cutover and frozen-snapshot migration

The implementation is developed in dependency order only. The final release
gate is whole-system: all enabled definitions and all production mutation
entrances must be PostgreSQL-only. No API, CLI, worker, scheduler, consumer or
callback may call a mutating domain service outside Kernel.

The pre-refactor JSON snapshot is mounted read-only only to an explicit
migration tool. It selectively migrates meaningful, verifiable domain assets;
it need not import fixtures, caches, failed residue, or rebuildable data.
Migration classifies malformed, cross-project, hash-invalid, missing-reference,
or policy-invalid records as `QUARANTINED` with immutable evidence. Critical
violations that undermine business identity, valid asset/version lineage, or
eligible production inputs block release. No post-cutover JSON recovery or
fallback is permitted.

The final production image/configuration has no LocalStorage production
dependency, JSON authority reader, JSON fallback, sync-after-write job, or
dual-write route. PostgreSQL/object-store recovery uses only verified backups
and database-owned object references.

## Acceptance matrix

| Area | Required evidence | Release condition |
|---|---|---|
| Command admission | schema, permission, approval, idempotency tests | unregistered/invalid commands fail closed |
| Operation execution | state/parent-child/Saga/Completion Contract tests | correct authority terminal state and evidence |
| Attempts/leases | concurrent acquire, fencing, late-result tests | one active attempt; stale results rejected |
| External effects | dispatch generations, duplicate receipt, unknown-state tests | no blind retry; reconciliation/compensation controlled |
| Assets/blobs | qualification, immutable refs, upload/verify/corrupt/delete tests | only qualified assets and available blobs are producible |
| Events/Inbox/Outbox | atomic UoW, duplicate/mismatch Inbox, consumer replay tests | exactly-once domain effect over at-least-once delivery |
| Read Models | rebuild and watermark/read-your-writes tests | projections never decide authority state |
| Migration | frozen snapshot import, quarantine, invariant verification | no required data loss; critical failures block |
| Entrypoints | static scan, runtime registry, API/CLI/worker/scheduler/callback E2E | Coverage Manifest reports zero bypasses/unknown writes |
| Runtime exclusion | production-image/configuration test | LocalStorage, JSON fallback and dual-write unavailable |
| Recovery | timeout, lease loss, dead-letter, reconciliation, compensation E2E | persisted recovery instruction and controlled outcome |

## Out of scope

This design does not require future Operation Families to be implemented. They
must be disabled and unreachable until a full Definition, PostgreSQL authority
model, Kernel route, Completion Contract, Coverage Manifest entry, and
PostgreSQL-only acceptance exist.
