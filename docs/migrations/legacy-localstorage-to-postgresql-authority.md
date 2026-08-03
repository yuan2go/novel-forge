# Legacy LocalStorage to PostgreSQL Authority Migration

## Migration state

This is a forward migration program, not a mirror or permanent dual-write plan. The current implementation establishes the Project/Workspace Authority slice, a resumable reviewed import path, production query projections and production API isolation. It does not yet close every inventory row.

| Work package | State | Evidence / remaining work |
|---|---|---|
| WP-00 audit and executable inventory | Implemented | JSON and Markdown inventory generated from AST/code evidence |
| WP-01 Project / Workspace | Backend implemented, PostgreSQL integration-proven | Dedicated binding editor and project-scoped Profile creation UI remain |
| WP-02 Source governance/object store | SourceDocument plus prepared Transform/Chunk commit and Source worker recovery implemented and PostgreSQL integration-proven | Existing verified Blobs are admitted without raw SQL content; upload receipt API, actual processor ExternalEffect and large-object importer remain |
| WP-03 MKAOS | Partial pre-existing Authority, not complete | Remove directory selection and migrate remaining lifecycle/governance writes |
| WP-04 Context Builder | Read projection added; write path incomplete | Deterministic retrieval manifest operation still required for every entrypoint |
| WP-05 Story design/planning | Existing authorities retained; Legacy residue remains | Route every generator and change through the typed authorities |
| WP-06 Draft/review/revision | Production Chapter/Content Authority retained | Delete or migration-isolate remaining direct legacy adapters |
| WP-07 Publishing | Read projection only in this slice | Receipt-backed external-action commands remain |
| WP-08 Feedback/reader | Read projection only in this slice | Import/exposure/outcome command migration remains |
| WP-09 Task/workflow/agent | Task/System PostgreSQL projection and audited Operation/Outbox recovery implemented | Remaining filesystem scheduler/task assets remain in inventory; terminal Operation rerun belongs to its owning Authority |
| WP-10 API/worker/frontend | Production app and Task Center recovery controls expanded | All frontend actions and all product write routes are not yet covered |
| WP-11 import/reconciliation/quarantine | JSON snapshot first slice implemented and proven | Binary/blob and all legacy category codecs remain |
| WP-12 remove Legacy production paths | Not complete | Deletion waits on zero inventory blockers and reconciliation |
| WP-13 regression/release gate | Partial | Full suite, web build, worker/longform/provider/production proofs remain |

## Database migration 0043

`20260801_0043_project_workspace_and_legacy_migration_authority` adds:

- `authority_project` and `authority_workspace` with lifecycle, health, stage, version and current AssetVersion constraints;
- `authority_project_binding` and the partial unique active-binding index;
- resumable fields on `authority_migration_run`;
- `authority_legacy_migration_item` with stable run/source and run/business-hash uniqueness;
- quarantine scope and resolution fields;
- the `IMPORTED` AssetVersion lifecycle and `PENDING_EVALUATION` qualification decision;
- missing foreign-key indexes detected by the clean-migration audit.

The migration is forward-only. It does not alter the source semantics of released historical migration modules. Restore uses a pre-migration database backup plus the frozen snapshot and hash reconciliation described in the runbook.

## Database migration 0044

`20260801_0044_project_binding_authority` binds every relational Project binding to its immutable `project_binding_record` AssetVersion. `project_binding.assign` and `project_binding.remove` reuse the Project concurrency key, Command Kernel admission, Attempt/Lease/Fence execution, qualification, Audit, StateEvent and Outbox. Targets are accepted only when they belong to the same project and are `ACTIVE`, `ELIGIBLE`, and governance `CLEAR`.

## Database migration 0045

`20260801_0045_task_recovery_authority` adds an audit ledger for manual Outbox dead-letter recovery. The command is unique by project/source outbox/idempotency key and binds an expected attempt count to one replacement outbox ID. Recovery locks the source row, checks scope and version, preserves the dead-letter row, creates a new `pending` generation, and records StateEvent, Audit and Outbox evidence in one transaction. Operation recovery continues to use the pre-existing `authority_recovery_command`; no task or retry state table was added.

## Database migrations 0046 and 0047

`20260801_0046_source_document_authority` adds the `authority_source_document` projection over the existing Asset, AssetVersion, Blob and Operation authorities. It enforces project/content-hash uniqueness, immutable version identity, rights/governance states and indexed project/workspace/blob/operation access. Raw source bytes are not a column; `object_key` is an object-store reference whose actual hash and size must already be verified in `authority_blob`.

`20260801_0047_candidate_asset_lifecycle` adds the `CANDIDATE` AssetVersion lifecycle already required by the shared Authority handler contract. A Source with unknown or forbidden rights is committed as a non-active Candidate with `NEEDS_REVIEW` or `INELIGIBLE` qualification and `QUARANTINED` governance. It cannot satisfy production input qualification.

`source.document.register@1.0.1` runs through the existing Operation, Attempt, Lease and fencing path. It validates Blob scope/hash/size/key before admission, derives stable content identity and idempotency, materializes AssetVersion/BlobReference/Qualification/Source projection, and writes StateEvent/Audit/Outbox evidence atomically. The production API stops after Admission. `novel-forge-source-authority-worker` polls eligible Operations from PostgreSQL, excludes active leases and supports expired-Lease takeover. An integration crash fixture proves output replay under fencing token 2 without a duplicate SourceDocument. The synchronous `execute` facade remains test/operator composition only; clean/chunk operations are still required before WP-02 is complete.

## Database migrations 0048 and 0049

`20260801_0048_source_transform_authority` adds Source transform and Chunk projections whose identities are existing Authority Assets/AssetVersions and whose bytes are verified Blobs. It deliberately does not reuse the Legacy `source_chunks.raw_text/clean_text` schema. Chunk evidence records ordered byte spans, Hashes, sizes and deterministic counts. The transform has one partial-unique Active projection per SourceDocument. `20260801_0049_source_transform_fk_indexes` supplies the workspace/project foreign-key indexes detected by the clean-database migration audit without rewriting applied 0048 semantics.

`source.transform.commit@1.0.0` accepts a prepared metadata-only candidate manifest, freezes the eligible SourceDocument AssetVersion and policy Hash, rechecks every Chunk Blob receipt under the current fence, and atomically commits the transform manifest plus evidence-only Chunk AssetVersions, qualifications, BlobReferences, projection rows, Audit/StateEvent/Outbox. Chunk AssetVersions are deliberately `INELIGIBLE` for generic production selection. The upstream clean/chunk processor and its ExternalEffect receipt are still pending, so this Operation is reported as a commit boundary rather than proof of processing.

## Import algorithm

```text
scan frozen snapshot
-> parse JSON
-> compute per-record sha256 and whole-tree snapshot hash
-> infer stable project/workspace and business keys
-> classify duplicate/conflict/missing/cross-project/rights/parse errors
-> create or reuse PAUSED Project Authority shell
-> admit one legacy_migration.asset.import Operation per valid record
-> run shared Attempt/Lease/Fence handler
-> write IMPORTED/PENDING_EVALUATION AssetVersion and qualification
-> record migration item target identities and evidence
-> quarantine failures without dropping payload evidence
-> checkpoint counts/cursor
-> reconcile hashes, counts and relationships
```

The run ID is stable for the snapshot hash. Re-running with resume does not create duplicate items, operations or AssetVersions. Non-dry-run import rejects writable snapshot roots.

## Deletion conditions

Legacy code may be deleted only after: the corresponding inventory rows are Authority-backed or explicitly rebuildable; imported counts and hashes reconcile; quarantine is resolved or accepted by a recorded decision; production/read/frontend routes no longer call the path; restart and idempotency tests pass; and the architecture gate reports no unapproved production reachability. No importer deletes source data.
