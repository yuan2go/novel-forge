# Integration ledger scan, 2026-10-07

Working tree: isolated PR133 native integration, fixed main f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609. This is current-source fixture evidence, not merge-SHA validation or real Provider evidence.

## Corrected historical source fixture

`tests/integration/test_authority_legacy_migration_postgres.py:1930` now allocates one owned disposable current-schema database. Current Runtime builds controlled Source/Blob/Legacy/Validation/projection fixture facts. At line2100 the existing materialization helper recreates that exact owned database at the full 0066 DDL and contiguous ledger prefix. No published migration is altered, no migration ledger hole is synthesized, and current Runtime is not executed on historical DDL.

The helper's actual later-only nonempty table inventory is asserted exactly as `{authority_operation_definition_release}` at line2105. These are preparation Runtime release registrations, absent from genuine 0066 DDL. Source, Blob, legacy items, validation records, operations, receipts and Source projections remain in historical tables. Their compatible fixture rows are reconstructed under original SQL guards. Subsequent published migrations generate their own definition release backfill; these rows are untouched rather than deleted to force the generic restore helper's empty-table requirement.

Original ambiguity preflight failure, explicit validation binding recovery, source revalidation and native Source projection assertions are retained. Focused PostgreSQL PASS: 1 passed in6.58s, `chapter-legacy0066-fixture-attempt2.log`; first attempt failed only because restoring later definition releases would conflict with legitimate migration backfill. Ruff PASS. Parent-provided database: nf_pr133_chapter_debug2_test, port59466; generated disposable historical database was cleaned by its owning helper. No Provider calls.

## Entire integration ledger manipulation inventory

| Path:line | Actual construction | Conclusion / safe update |
| --- | --- | --- |
| test_authority_legacy_migration_postgres.py:2100 | Former single0067 deletion replaced by owned full0066 DDL/prefix materialization | Fixed; no ledger DELETE remains |
| test_migration_history_admission_postgres.py:53,55 | Deliberately inserts foreign old-branch identity or deletes migration2 from main159 prefix | Required negative proof; keep rejection and unchanged-facts assertions |
| migration_window_postgres_support.py:72,93,113 | Fresh owned DB, exact sequential registered prefix, then verifies exact set | Safe; already reusable owner helper |
| test_book_projection_repair_upgrade_postgres.py:54,75 | Fresh owned DB `_apply_through` applies registered sequence to named revision; current runtime uses LATEST_MIGRATION_ID:86 | Actual callers keep contiguous prefixes; no current non-prefix fixture found. If generalized to arbitrary pre-populated databases, require exact prefix before manual application |
| test_book_opening_workflow_upgrade_postgres.py:94,106,135 | Fresh DB prefix through0101, then fills sequential0102/0103 up to0104 boundary | Safe contiguous windows; retains historical execution evidence |
| test_book_opening_legacy_reconciliation_postgres.py:365,377 | Fresh DB applies registered sequence until fixed historical migration boundary | Safe; no deletion or future-head subset |
| test_book_opening_branch_reconciliation_upgrade_postgres.py:65,80 | Fresh DB prefix stopping before0103 | Safe; no deletion or future-head subset |
| test_authority_migrations_postgres.py:2302,2444,2531,2635,3000 | Fresh DB sequential prefixes stopping before0102/0008/0101/0102 or through0091 | Safe prefix constructors; file remains root-owned. Other ledger references at673/698/743/753/761/3421 are snapshot/assertion reads |
| test_creative_resource_migration_postgres.py:27 | Snapshot read; owner helper supplies exact historical prefix | Safe; no ledger mutation |
| test_world_causal_migrations_postgres.py:129,218 | Count assertions for published historical source head and complete current chain | Safe; no ledger mutation |
| test_corpus_migrations_postgres.py:111 | Complete-chain count assertion after owner-helper prefix upgrade | Safe; no ledger mutation |
| conftest.py:80 | Autouse business cleanup explicitly excludes nf_schema_migrations | Safe; no ledger mutation |

Scans covered all integration references to nf_schema_migrations and multiline DELETE/TRUNCATE/DROP statements. The only remaining direct ledger DELETE is the intentional discontinuous-history negative test. No other confirmed non-prefix fixture or appended-head deletion assumption remains in the inspected integration tree. Other files were not edited.
