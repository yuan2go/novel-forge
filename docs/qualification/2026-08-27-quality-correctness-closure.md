# Quality correctness closure qualification — 2026-08-27

This is an exact-runtime engineering qualification record for the correctness
closure inside `WP-QUALITY-PROOF-01`. It is not literary-quality evidence,
human preference, Judge calibration, real-provider campaign evidence or
production certification.

## Identity and boundary

- starting SHA: `3511efbd4d83b6716fc6b930b5f86ff16c775eb7`
- qualified runtime SHA: `5fb5d62f9dc48602eaf4ed327665a184719d35ae`
- branch: `codex/wp-quality-proof-01`
- isolated worktree: `/Users/yuan/projects/novel-forge-worktrees/wp-quality-proof-01`
- migration head: `20260826_0101_quality_qualification`
- PostgreSQL qualification database:
  `postgresql:///novel_forge_quality_closure_cf7f0143_test`
- PostgreSQL version: Homebrew PostgreSQL 16.14
- provider boundary: scripted/deterministic fixtures only; this closure made no
  external real-provider call
- campaign boundary: exactly two consecutive four-Chapter groups, eight
  accepted Chapters, in the scripted recovery campaign only

No migration was added. The closure changes runtime projection, admission and
deterministic validation while preserving existing Quality, Context, Canon,
Narrative State, Planning and Reader Authorities.

## Closure implemented

1. Book input snapshots expose the exact qualified Foundation Set. The Book
   Supervisor resolves the unique `CHARACTER_CAST` and `READER_PROMISE`
   AssetVersions and hashes and freezes them into Chapter preparation.
2. CharacterCast and authoritative CharacterCard now require an executable
   identity contract: stable id, canonical name, aliases and pronouns.
   Historical incomplete assets remain readable but cannot enter new Chapter
   Provider execution.
3. Character and Reader Promise semantics use source-bound protected
   projections. Draft and Review receive the same exact semantics. Reader
   Promise remains `FUTURE_EDITORIAL_CONTRACT`, not Canon or Accepted Actual.
4. Deterministic continuity v3 consumes only protected Character identity
   facts. It blocks exact adjacent Chinese pronoun contradictions when one
   unambiguous named antecedent exists. It does not infer names, gender or
   coreference from prose or model judgment.
5. Severe identity contradiction enters the existing Canon conflict/gate path
   as `CHARACTER_IDENTITY_PRONOUN_CONTRADICTION`; editorial scores cannot
   average it away.

## Real-failure regressions

The two observed campaign failures are retained as minimal source excerpts:

- runtime lineage `93846845`: `林遥` has authoritative pronoun `她`, followed
  immediately by `他把底图压在膝上`;
- runtime lineage `f34db8be`: `徐主任` has authoritative pronoun `她`, followed
  immediately by `他没有问路长什么样`.

Both now produce a blocking deterministic conflict. A control without explicit
identity vocabulary remains unclassified, preventing heuristic gender guesses.
The integrated Context-to-Canon regression also proves the first failure is
blocked through the real Chapter domain handler, not only a standalone helper.

## Residual operation governance closure

The abandoned operation was not repaired through direct SQL status mutation.
Before closure, audit showed:

- operation `161bbe98-2c07-4851-910a-5889b89f6c6c`:
  `story_design.semantic_evaluate`, `EXECUTING`, version 2;
- attempt `5174f34e-44f7-4025-82a0-ce6193ba208c`: `RUNNING`;
- lease `0d9dbe27-565b-4bbc-a380-8de08afbed09`: expired in time but still
  recorded `HELD`;
- ExternalEffect rows: 0.

The exact attempt then followed the canonical command chain:

1. targeted `expire_attempt_lease` fenced the attempt to `LEASE_LOST` and the
   lease to `EXPIRED`;
2. recovery command `0fe1bd81-837a-4937-a566-561d4b12664b` recorded
   `LEASE_TAKEOVER_VISIBLE` at expected version 2;
3. cancellation command `b9786daa-aac1-4ec4-a518-c148537ea7bd` requested
   cancellation at expected version 2;
4. cancellation resolved as `no_external_effect` at expected version 3.

After closure, Authority reports operation `CANCELLED` version 4, attempt
`LEASE_LOST`, lease `EXPIRED` with `lease_expired`, zero ExternalEffects, one
recovery command, one cancellation command and six ordered StateEvents. The
campaign database now has 146 `SUCCEEDED`, one `CANCELLED` and no nonterminal
Operation. The database has all 101 migrations with current head 0101.

The same sequence is a repeatable PostgreSQL regression in
`test_command_kernel_recovery_postgres.py`, including idempotent recovery and
cancellation replay.

## Scripted campaign dry-run

The canonical scripted campaign completed exactly Chapters 1–8 in two
ChapterGroups `(1, 4)` and `(5, 8)`, materialized two Narrative Realizations,
eight Reader Outcome projections and two recaps, and did not schedule Chapter
9. It exported two independently addressed blinded packs, each containing
eight Chapter pairs plus one Arc pair. Public packs exclude Canonical/Baseline
identity, provider/model, prompt, Judge/System score, private mapping and asset
version identity, and include `Cannot Judge`.

This is `SCRIPTED_PROTOCOL_ONLY`: `real_provider_call_count=0`. The persisted
campaign correctly remains `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`.

## Regression evidence

~~~text
focused Character/Context/Canon/Book/Quality tests
-> 124 passed, 5 subtests passed

targeted PostgreSQL governed recovery
-> 1 passed

five PostgreSQL failures exposed by the stricter Character contract
-> 5 failed: old shared CharacterCast fixture lacked name/aliases/pronouns
-> fixture repaired without weakening the invariant
-> focused rerun: 5 passed

make authority-postgres-test
-> 224 passed, 60 subtests passed, 0 skipped, 0 failed

make test
-> Python: 1778 passed, 16 warnings, 0 failed
-> Admin: 12 passed, 0 failed
~~~

The PostgreSQL suite includes a clean full migration chain, upgrade from 0007,
upgrade from the previous head, legacy-admission/context-view upgrade,
idempotency, leases/fences, cancellation, replay/recovery, external-effect
reconciliation, Book/Chapter/Hierarchy, Quality/Reader and campaign crash
recovery. The migration manifest has 101 entries and one head at 0101.

An initial full-suite invocation used an isolation database name not ending in
`_test`; the safety fixture rejected all 224 setups before test execution. The
database was replaced with the explicitly scoped `_test` database and one
recovery smoke passed before the suite was rerun. This was an environment
preflight failure, not counted as a code pass.

## Evidence classification

| Classification | Status | Boundary |
|---|---|---|
| Engineering correctness closure | PASS | Protected Foundation Context, deterministic identity gate and governed recovery are implemented and regression-proven. |
| Wired | PASS | Book snapshot/Supervisor, preparation, Context, Draft/Review views and Canon gate share one runtime path. |
| PostgreSQL integration | PASS | Full non-skippable Authority suite and repository suite passed. |
| Fresh/upgrade migration | PASS | Existing 101-migration chain passed fresh and upgrade tests; no migration was required. |
| Scripted 8-Chapter dry-run | PASS_WITH_LIMITATIONS | Two-by-four protocol/recovery proof only; scripted Provider. |
| Real Provider quality campaign | NOT_RUN | No external call was authorized for this closure. |
| Human blind evidence | WAITING_HUMAN_EVIDENCE | Packs exist; no human responses are fabricated. |
| Judge calibration | UNCALIBRATED | Bounded human evaluations are absent and two reviewers would still be insufficient for statistical calibration. |
| Editorial/long-form superiority | NOT_PROVEN | No current human comparison or valid real-provider A/B result. |
| Production quality | NOT_PROVEN | No sustained, market or production evidence. |

The correctness closure is complete. `WP-QUALITY-PROOF-01` as a quality claim
remains `NOT_PROVEN`; real-provider campaign evidence and two independent human
review sequences must exist before any bounded preference conclusion.
