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

## First vertical slice boundary

The deterministic PostgreSQL-only single-chapter handler slice is implemented
under `src/novel_forge/modules/chapter_authority/`. It owns one Saga root and
eight standard child Operations for ChapterPlan, ContextBundle, Draft, Review,
Revision, Canon, Quality Gate, and Export. Its handler boundary is pure: handler
code returns typed output descriptions while the authority runtime alone owns
AssetVersion materialization, qualification, output binding, Completion, and
evidence writes. Export bytes use the Generic ExternalEffect/Blob path.

This is a bounded authority proof, not a claim that legacy production is
migrated. Its deterministic provider records `real_model_call=false`; it does
not call model adapters or write model-call/cost ledgers because no model call
occurs. Production provider handlers must use explicit provider effects and
AgentRun/cost evidence rather than replacing the fixture provider silently.

## Remaining migration boundary

Saga compensation children use standard admission, reverse dependencies,
Attempt/Completion, and fenced coordination. The existing Chapter Production
Bus, Context Builder, Draft, Review/Revision, Canon, Quality, and Publishing
services remain LocalStorage-authoritative and are not called by the new slice.
The next migration step is to replace one deterministic handler at a time with
a PostgreSQL-native adapter to the corresponding domain capability while
keeping LocalStorage and `nf_*` tables projection-only. No real-provider or
long-form acceptance is currently claimed.
