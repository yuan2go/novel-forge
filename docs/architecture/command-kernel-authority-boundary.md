# Command Kernel Authority and Projection Boundary

Status: adopted for new PostgreSQL Command Kernel work; legacy migration remains incomplete.

## Write authority

The following PostgreSQL aggregates are the intended command-side authority:

| Aggregate | Authority table | Required write path |
|---|---|---|
| Operation | `authority_operation` | admission, lifecycle CAS, Completion finalization |
| Attempt | `authority_attempt` | Attempt runtime with lease/fencing |
| Asset version | `authority_asset`, `authority_asset_version` | Asset command runtime |
| Operation output | `authority_operation_output_asset` | explicit output binding command |
| Blob | `authority_blob` | reservation, Generic ExternalEffect receipt, verification |
| External effect | `authority_external_effect` | Generic dispatcher, receipt inbox, reconciliation |
| Saga | `authority_saga`, `authority_saga_step` | fenced coordinator |

New business mutations must not introduce another LocalStorage-authoritative
path or another vendor-specific effect dispatcher. PostgreSQL writes must emit
StateEvent, AuditLog, and Outbox evidence in the same transaction.

## Compatibility and projection models

| Model | Current role | Migration rule |
|---|---|---|
| `production_operation` / `ProductionOperation` | legacy production runtime and compatibility record | no new command-side authority; migrate callers to `authority_operation`, then rebuild as projection if still needed |
| `AgentRun` | agent-specific execution/read model with checkpoints, budget, gate and metrics | retain domain detail; link to authoritative Operation rather than replace Operation lifecycle |
| `WorkflowRun` / `LoopRun` | workflow/loop orchestration projection and legacy runtime state | retain read/operator shape; future writes originate from Operation/Saga lifecycle |
| `ChapterProductionRun` | chapter production evidence and operator projection | retain chapter-specific evidence; future authoritative command/output IDs must be linked |
| `nf_assets`, `nf_asset_versions` | LocalStorage synchronization/index projection | rebuildable projection only; not valid Completion evidence |
| LocalStorage JSON assets | current production compatibility authority for many modules | explicitly unmigrated; do not use for new Command Kernel authority paths |

This document does not claim that LocalStorage has stopped being the production
authority across Novel Forge. It defines the target boundary and the rule for
new code while migration proceeds vertically.

## Output evidence rule

Completion Contracts may only consume AssetVersions explicitly bound through
`authority_operation_output_asset` for the current Operation. Project-scoped
asset discovery, an old active AssetVersion, an admission audit, or a revoked
qualification cannot satisfy Completion.

An output binding freezes:

- `operation_id`;
- `asset_id` and `asset_version_id`;
- `output_key` and role;
- the bound content hash.

Blob requirements are evaluated by status, role, and minimum count over those
bound AssetVersions. Qualification is the latest effective decision.

## External effect rule

Blob upload is a specialization of the Generic ExternalEffect protocol:

```text
Blob reservation
  -> ExternalEffect intent
  -> dispatch lease + fencing
  -> adapter
  -> generic receipt inbox
  -> Blob receipt projection
  -> verification
  -> AssetVersion binding
```

`DISPATCHABLE / IN_FLIGHT / SENT` are migration-only legacy states. Runtime
uses `READY / DISPATCHING / DISPATCHED` for Effect intent and
`CREATED / DISPATCHING / ACKNOWLEDGED` for dispatch progress. A provider ACK is
not final business success unless the frozen completion policy is
`synchronous_final`, in which case the runtime still materializes a verified
receipt through the same inbox path.

## Remaining migration boundary

The first PostgreSQL-only business vertical slice is not yet complete. Chapter
Plan, ContextBundle, Draft, Review, Revision, Canon, Quality Gate, and Export
handlers still need operation definitions and migration adapters that invoke
existing domain services without restoring LocalStorage as command authority.
