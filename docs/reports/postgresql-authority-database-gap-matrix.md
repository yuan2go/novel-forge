# PostgreSQL Authority Database Gap Matrix

Date: 2026-07-12

| Design capability | Current evidence | Gap | Required implementation |
|---|---|---|---|
| Domain asset authority | `nf_assets` / `nf_asset_versions` are sync targets in migration `v20260625_0001` | JSON remains canonical; no lifecycle/eligibility/governance model | replace with Asset, immutable AssetVersion, AssetQualification and authoritative repositories |
| Operation snapshots/graph | `production_operation` in `v20260712_0005` | only parent ID/metadata; no fixed Definition/Contract or saga/dependencies | extend/recreate operation schema with snapshot, root/causation/workflow/saga/step/dependency fields |
| Attempt/Lease fencing | `operation_attempt`, `operation_lease` | thin statuses; lease version is not enforced fencing | add complete state/lease tables, active-attempt index and token-checked result procedures |
| External effects | none | no logical effect/dispatch/generation/receipt evidence | add `external_effect`, `external_effect_dispatch`, reconciliation and compensation evidence |
| Inbox | `outbox_consumer_delivery` | delivery-only dedup; no payload-hash conflict or atomic consumer writes | add Inbox with payload hash, outcome and alert invariant |
| Blobs | object store helpers only | no controlled upload/verify/delete authority model | add Blob and immutable AssetVersionBlobReference tables plus verification/delete guards |
| State events | `state_event` / snapshot tables | usable base, but no complete aggregate version contract or repository surface | preserve append-only base; enforce version invariant and add reducers/projections |
| Read models | `nf_assets` indexed reads and local scans | current index is a sync projection and can fall back | add rebuildable PostgreSQL projections and watermarks |
| Coverage evidence | none | no build artifact or release hash | add Coverage Manifest generator and `release_evidence` hash record |
| Migration/quarantine | `sync_from_local` | no frozen snapshot classification or exception ledger | add importer, migration run, quarantine records and validation reports |

## Existing tables to retire from production semantics

`nf_assets`, `nf_asset_versions`, `nf_task_statuses`, and `nf_projects` may be
used as migration inputs only until replacement repositories/read models are
complete. They must not remain the production source of truth after the final
release gate.

## Domain-level target matrix

| Domain | Current code/table | Target table | Action | Authority/repository/query/tests |
|---|---|---|---|---|
| Project / Workspace | `nf_projects`, `workspace/service.py` | `project`, `workspace` | recreate | Write Model / ProjectRepository / project current query / integration |
| Asset / Version / Qualification | `nf_assets`, JSON assets | `asset`, `asset_version`, `asset_qualification` | recreate | Write Model / AssetRepository / active-version query / integration |
| Blob / Reference | object-store helpers | `blob`, `asset_version_blob_reference` | new | Write Model / BlobRepository / verified-blob query / integration |
| Source / Material / License / Lineage | source modules, MKAOS tables | `source_document`, `source_lineage` | alter | Write Model / SourceRepository / scoped query / integration |
| MKAOS cards/packs | migration `v20260702_0003` | versioned knowledge tables | alter | Write Model / KnowledgeRepository / pack projection / integration |
| Context | JSON context assets | `context_manifest`, `context_item`, `compression_manifest` | new | Write Model / ContextRepository / manifest query / integration |
| Provider execution | adapter logs | `provider_input_projection`, `provider_execution_manifest` | new | Write Model / ProviderRepository / audit query / integration |
| Topic/World/Character/Outline | JSON module assets | versioned `asset_version` payloads | migrate | AssetRepository / strong current query / integration |
| Chapter / Draft / Review / Revision | JSON assets, `review_issues` | domain tables plus AssetVersion | alter | domain repositories / strong current query / integration |
| Canon / StoryState | JSON graph assets | `story_state`, `story_state_event` | new | State table authority / StoryStateRepository / replay verification |
| Quality / Gate | JSON reports | `quality_evaluation`, `gate_decision` | new | GateRepository / strong gate query / integration |
| Model usage / Cost | runtime ledger assets | `model_call`, `usage_ledger`, `cost_ledger` | new | LedgerRepository / audit query / integration |
| Operation / Attempt / Lease | `v20260712_0005` | authority operation tables | recreate | KernelRepository / CAS query / concurrency integration |
| External effect / Dispatch | none | `external_effect`, `external_effect_dispatch` | new | EffectRepository / reconciliation query / integration |
| Inbox / Outbox | outbox + delivery table | `inbox_message`, `outbox_event` | alter | Inbox/OutboxRepository / consumer query / integration |
| Approval / Audit / Trace | `audit_log`, JSON approvals | snapshots/evidence tables | alter | EvidenceRepository / authority query / integration |
| Release / Receipt | JSON release package | `release`, `publish_receipt` | new | PublishingRepository / release query / integration |
| Feedback / Patch | JSON feedback | `feedback`, `feedback_patch` | new | FeedbackRepository / projection query / integration |
| Policy / Portfolio | JSON settings | `policy_bundle`, `portfolio_decision` | new | PolicyRepository / strong policy query / integration |
| Read Model / Watermark | `nf_assets` indexes | `read_model_*`, `projection_watermark` | recreate | ProjectionRepository / eventual query / rebuild test |
| Migration / Quarantine | `sync_from_local` | `migration_run`, `data_quarantine` | new | MigrationRepository / audit query / import integration |
| Release evidence | none | `release_evidence` | new | ReleaseEvidenceRepository / release query / architecture test |
