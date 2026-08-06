# Capability Pack Authority Integrity

## Evidence boundary

This design is the PostgreSQL Authority boundary for Capability Pack admission.
It proves immutable fixture facts, deterministic assignment, concurrent CAS, and
runtime reuse. It does not qualify a real model provider, prose quality,
long-form production, multi-book content production, or a production release.

```text
provider_vertical_qualification_status=NOT_STARTED
production_verified=false
```

## One snapshot per Attempt

The Chapter path has one Pack resolution boundary:

```text
Chapter Attempt Admission
  -> resolve current Activation and open Rollout once
  -> persist immutable CapabilityPackAttemptSnapshot under the currently held Fence
  -> give the typed snapshot to ProductionExecutionGateway
  -> give the same typed snapshot to Chapter Agent Binding
  -> persist AgentRuntimeBinding -> exact snapshot id and hash
  -> on Worker restart or Lease takeover, load the existing snapshot
```

`authority_attempt_capability_pack_snapshot.attempt_id` is unique. The database
checks the Attempt/Operation, exact Deployment, Compilation, Binding Set,
Assignment, release SHA, canonical snapshot hash, and trace/span identity. It
stores two different Fence facts: `execution_fencing_token` is the immutable
Attempt execution identity; `snapshot_creation_fencing_token` is the currently
held Lease Fence that authorized the INSERT. They are equal during first
admission and may differ during a legitimate Lease takeover. Snapshot creation
emits its Audit/Event/Outbox facts in the same Authority Unit of Work. The row
is immutable. Recovery loads it before consulting Activation or Rollout, so it
neither reassigns a Book nor increments the resolution count. A retry that
creates a new Attempt may resolve a new snapshot.

Gateway and Agent Binding receive `CapabilityPackAttemptSnapshot`; neither owns
a resolver. Passing an untyped mutable mapping is not an authority boundary.

## PostgreSQL provenance chain

| Fact | Database enforcement |
|---|---|
| Pack | immutable global identity with closed `SYSTEM` or `PROJECT` owner |
| Compilation | unique `(compilation_id, compilation_hash)` and exact Pack version identity |
| Approval | composite FK to the exact Compilation hash; immutable closed approval policy |
| Binding Set | exact Compilation/workflow composite identity; trigger recomputes content hash |
| Deployment | composite FKs to the same Compilation and Binding Set; trigger enforces owner and target scope |
| Activation | trigger validates canonical scope/activation keys and every target field against Deployment |
| Rollout | same scope, environment, workflow, and Pack ID; one non-terminal rollout per baseline |
| Assignment | selected Deployment must be baseline/candidate; SHA-256 bucket and content hash are recomputed; row is immutable |
| Attempt Snapshot | one row per Attempt, original execution Fence plus creation-authorizing Fence, trace/span, exact Deployment/Assignment chain, canonical hash; immutable with transactional Audit/Event/Outbox |
| Runtime Binding | composite snapshot FK and trigger equality for Deployment, Binding Set, Pack version, Compilation, definitions, Fence, and release SHA |
| Dependency | exact version and manifest hash FKs, namespace rule, no self/cycle/floating dependency; immutable |

These constraints supplement the Command Kernel transaction. Application
validation improves error reporting; it is not the sole integrity boundary.

## Rollout and Activation

Activation is the only current pointer. `rollout.complete` locks Rollout and
Activation in one Authority Unit of Work, validates
`expected_activation_version`, promotes the candidate with CAS, updates
Deployment roles, records Rollout `COMPLETED`, and emits Audit/Event/Outbox in
the same transaction. The resolver has no `COMPLETED => candidate` override.

During `CANARY`, `PERCENTAGE`, or `FULL`, the active baseline plus immutable
Assignment selects the effective Deployment. `PAUSED` uses baseline without
deleting the Assignment. Resume therefore restores the same Book assignment.
Rollback moves Activation by CAS; historical Attempt Snapshot and Runtime
Binding rows remain unchanged.

## Approval policy

`CapabilityPackApprovalScope.v1` is a closed protocol. It admits only the named
environment, runtime profile, release channel, target scope, project/workspace/
book, and workflow. It separately controls canary, percentage, full rollout,
and maximum percentage. Unknown keys and invalid value shapes are rejected.

Structured limitations have one of `INFORMATIONAL`, `ADMISSION_CONSTRAINT`,
`ROLLOUT_CONSTRAINT`, or `EXPIRY_CONSTRAINT`. Informational text is display-only;
the other categories are consumed by deployment, rollout, and runtime admission.

## Ownership and dependencies

Pack identity is global; Pack version content has an Authority owner namespace;
Deployment targets a scope. A `SYSTEM` owner has no project. A `PROJECT` owner
has exactly one project and cannot be deployed to another project or at SYSTEM
scope. SYSTEM Deployment accepts only SYSTEM-owned content. Cross-project reuse
requires a later explicit promotion/import operation and is never inferred from
the management Operation's project.

`upstream_packs` resolves an explicit exact-version graph. Registration stores
immutable dependency edges and exact manifest hashes. Trusted Compilation
freezes dependency order, edges, and hashes and does not inject every manifest
from a project. A retired or revoked dependency blocks new admission or recommends
rollback without rewriting historical runtime facts. Dependency drift is also
an admission gate: a revoked, retired, missing, or manifest-mismatched exact
dependency prevents a new runtime snapshot while historical snapshots remain
readable.

## Usage and qualification naming

One receipt is evidence of a call, not provider qualification. Capability Pack
usage exposes `real_provider_call_evidence_count`,
`real_provider_call_evidence_present`, and
`provider_vertical_qualification_status`. `VERTICAL_QUALIFIED` remains reserved
for an exact-release chain covering request, receipt, usage, cost, effect,
candidate, domain commit, asset lineage, quality, publish gate, and no fixture
contamination.
