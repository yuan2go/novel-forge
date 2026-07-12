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
