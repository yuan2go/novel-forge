# Database upgrade and zero-send recovery qualification

FROZEN_QUALIFICATION_EVIDENCE / NOT_RUNTIME_AUTHORITY.

Work package: `WP-NF-DB-UPGRADE-AND-ZERO-SEND-RECOVERY-QUALIFICATION-01`.
Frozen remote main: `c9987b86f761de755e5d53191999793415304e61`.
Tested candidate code: `f96c377884c1d25674656893141ef941915928f5`.
Target: `20261016_0222_planning_host_frozen_definition`.

| Qualification | Result | Scope |
|---|---|---|
| STATIC_COMPATIBILITY | FAIL | Registry/resources/frozen-request subchecks pass; full current integration contract qualification fails |
| ISOLATED_DB_UPGRADE | PASS | Main/candidate fresh and synthetic 0218 prefix; actual legal 0211 and 0220 snapshots; role, catalog, backup restore and immutable-data checks |
| ZERO_CALL_RUNTIME_RECOVERY | BLOCKED | Installed same-Book read/export and normal Reader release binding pass; no eligible actual 0219/0220 source; native continue refuses missing membership authorization |
| PRODUCTION_ROLLOUT_ADMISSION | BLOCKED | Actual native recovery, source-global-role evidence and historical source isolation are not fully qualified; no formal upgrade/real continuation authorization |

Canonical P0 is **FAIL** at tested SHA: backend/static gates and the complete migration matrix pass; full PostgreSQL integration records 242 failures and 11 errors across 2281 JUnit records, with zero skips and no timeout. Query-plan, Compose runtime and finalization gates are NOT_RUN after this failure. Ownership-checked resource cleanup passes with zero remaining resources. Full gate states, source/artifact identities and failure references are in `qualification.json`. The P0 uses scripted Providers in separate disposable resources. A matching head, a passing SQL fixture or a successful read/export does not establish actual native recovery, Provider behavior or production operation. Current remote main remains distinct from this unmerged candidate.

The failure signatures include planning-result repair exhaustion, current Style/Realization bindings, protected Context budgets, narrative contracts and retained Canon/character-reference paths. `canonical-failure-classification.json` records every failed node and diagnostic group in the archive. This package repairs the exposed migration executor, package/import, Planning Host and exact 0219/0220 recovery compatibility issues; it does not publish broad fixture regeneration or Chapter semantic-wire changes. Pending separate P0 edits are not treated as a fix or as passing evidence. These unresolved failures block broader compatibility and production admission.

## Compatibility repairs

Existing unpublished P0 repairs were reused by their exact original commits, rather than reimplemented: execution liveness/text serialization/Principal boundaries, the current typed Book-schema fixture and the forward 0221 indexes. Other dirty/conflicted workspaces were preserved.

The shared migration runner now takes a transaction advisory lock before ledger DDL, enforces declared backups for existing ledgers, preserves its legacy status fields while naming the actual/target heads, and labels lost commit acknowledgements for reconciliation. Backup subprocesses retain explicit private libpq HOME/service configuration while excluding unrelated environment variables. Snapshot backups retain private archives and hashes; archive readability does not claim restore qualification. A separate actual restore proof is retained.

Published migration bodies and historical fork IDs remain unchanged. Forward 0222 repairs the Planning Host function's reference to the nonexistent `authority_operation.definition_hash`, using the original immutable `definition_snapshot.definition_hash` instead. Reference and Arc branches, missing/wrong hashes, the prior nine predicates and the two added predicates were exercised.

Chapter recovery now distinguishes a terminal `FAILED_FINAL` Operation from its latest `FAILED_RETRYABLE` Attempt and avoids changing an already terminal source. Historical `production_execution` asset keys and receipt readers remain intact. Historical provenance manifests are included in the wheel. Qualification tooling uses module paths for process classification, and the public catalog parser uses an equivalent selector compatible with SoupSieve 3.

A later read-only refresh observed 36 uncommitted paths in the separate working-consumption P0 workspace, covering Chapter fixture wire/span alignment, Canon retained recovery effective-version access and legacy cast projection. Their paths and hashes are retained in `pending-other-workspace-p0.json`; the source workspace is untouched and those pending changes are not part of this candidate or evidence of passing this run. Any canonical failures remain blocking for their scope.

## Data and execution boundary

The original production cluster was not started or upgraded. Restores used a fresh exclusive PGDATA, internal WAL, no external tablespaces/symlinks, explicit configuration paths, disabled archive/recovery commands and a private Unix socket. Existing logical dumps were copied and hashed, restored with original applied history and ownership, and compared before/after. No fork was relabelled as a main prefix.

The source snapshots' global role attributes are unavailable: the tested non-superuser role was an explicit NOLOGIN surrogate. The earlier work package's tablespace-link incident still lacks complete original source-before/source-after proof. This package cannot retroactively erase that limitation. A first diagnostic attempted the default test port because its intended DSN was not propagated; all connections were refused, with no query or write at that endpoint. Its evidence is retained separately from successful isolated execution.

The original same-Book four chapters retain text digest `sha256:d22cae0c4242a6953292b7cb4e3389253ed0f9eae9d0ffc71f2a05d1f5d0cc43`, working cursor 4, accepted cursor 0 and Book version 21. Original candidate/selection/Context/World/recovery/Operation/Attempt/Effect/Receipt rows are preserved. The database's 19 UNKNOWN Effects and 19 HELD_UNKNOWN reservations remain; the same Project retains its original 15 of each. Only normal Reader Pack release evidence, its exact deployment pointers and two old Pack lifecycle fields are allowed differences. All old content hashes remain identical. New asset versions are Pack manifests/catalogs/compilations, with no new prose or model-call assets.

The 996 execution files were copied, read and hashed with source-before/source-after/copy equality. The supplied snapshot has no Blob rows or Blob references; an exclusive task object store was used. A claimed zero-send source without the required experimental policy/selected-method inputs was correctly rejected. No UNKNOWN was reclassified as unsent, no budget hold was cleared and no author acceptance was performed.

Installed read/export, 91 exact frozen prompt/envelope/output-Schema reconstructions, Reader drift reproduction and normal registration/compilation/approval/activation were run without production Provider credentials. The Reader binding now matches the exact candidate release. The full native continue still refuses `CODEX_MEMBERSHIP_AUTH_UNAVAILABLE` under the empty credential home. Synthetic SQL/Kernel checks are separate from this actual-snapshot limitation.

## Production procedure — not executed

1. Freeze the reviewed code SHA, wheel, dependency snapshot, runtime resource bundle and exact deployment bindings. Reconcile the actual server/system identifier, PGDATA/tablespaces/WAL, storage and execution roots; do not infer identity from a database name.
2. After separate formal upgrade authorization, stop all API, worker, outbox and maintenance writers, including host processes, and keep dispatch stopped. Record active work, leases, cancellations, original UNKNOWN/HELD_UNKNOWN and accepted/working cursors; reconcile or retain them through their owning paths.
3. Take mutually consistent private database/global-role, Blob and execution-file backups. Restore them into a provably isolated environment and verify content, receipts, permission and cursor hashes. An archive listing alone is insufficient.
4. Use compatible PostgreSQL clients in the installed release environment, inspect status as a read-only operation, require the exact registered prefix, then run one migration executor with an absolute private backup directory. A foreign/discontinuous ledger is a stop condition; do not edit applied IDs. On commit uncertainty, query the same ledger/catalog and reconcile rather than resending blindly.
5. Verify actual functions, triggers, constraints, indexes, ownership/ACLs, required extensions and permitted data differences. Read and export the same original text; recheck frozen requests, Sources, World receipts, execution ledgers and cursors. Use normal Pack publication/binding paths for release drift, preserving all old frozen requests.
6. Keep production rollout blocked until its actual recovery prerequisites and relevant complete engineering gates are met. Only a separate author authorization may permit real continuation, with exact current account/model/Pack/capacity/budget/cancellation controls. No current test or merge grants that authorization.
7. 0219/0220 have no downgrade. A pre-upgrade snapshot is a recovery option only if it would discard no later manuscript or execution evidence. Once newer results exist, preserve them and use compatible code recovery or a forward repair; restoring an older snapshot is not lossless rollback.

The following are templates for the separately authorized procedure, not commands executed against production by this package. Set the release environment and all scope identities from verified deployment evidence first. Keep dispatch paused throughout these read/export checks:

```bash
export NOVEL_FORGE_NO_MODEL_DISPATCH=1
python -m novel_forge.cli.authority authority-migrate --status
python -m novel_forge.cli.authority authority-migrate --backup-directory "$PRIVATE_BACKUPS"
python -m novel_forge.cli.authority authority-manuscript read --project-id "$PROJECT_ID" --book-run-id "$BOOK_RUN_ID"
python -m novel_forge.cli.authority authority-manuscript export --project-id "$PROJECT_ID" --book-run-id "$BOOK_RUN_ID" --output "$NEW_PRIVATE_EXPORT_PATH"
```

Use a new export path; the native exporter rejects an existing destination. These commands neither authorize a real continuation nor replace the snapshot/catalog/receipt checks above.

## Reproduction and privacy

`qualification-evidence.zip` contains sanitized commands, expanded SQL, source/provenance identities, selected passing/failing diagnostics, immutable-data differences and the canonical P0 report. `evidence-index.json` binds their hashes and the retained private originals. Raw dumps, credentials, private manuscript text and raw Provider execution files are excluded. The private task evidence directory retains full commands and outputs for authorized local review.

Failed attempts remain failures: the frozen main's three failures, pre-fix Operation/Attempt and Planning Host failures, dependency/selector failures, resource exhaustion, braked synthetic receipt checks and interrupted redundant diagnostics are retained. No failure is promoted by a later report. The exact-SHA P0 governs only its own local scripted engineering scope.

New real Provider calls: **0**. New prose: **0**. Actual continuation, literary improvement and human acceptance: **NOT_RUN**. This package does not deliver the 100/600 chapter targets.
