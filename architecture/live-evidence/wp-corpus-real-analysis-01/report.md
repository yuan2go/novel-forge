# WP-CORPUS-REAL-ANALYSIS-01

Overall: **ENGINEERING_COMPLETE_RUNTIME_BLOCKED**. Local engineering delivery is complete;
real model execution requires explicit task/account authorization. No push, PR or merge.

## Identity and verification

| Identity | Full SHA |
|---|---|
| Fetched baseline / end-of-work origin/main | `a6e25375ed568c546a6eb79328376b23b72d3c6d` |
| Initial implementation | `123093802f93ecbffe790dc5b138fea983fe0985` |
| Final implementation | `7e1f638b8df540075166c797adcd4e195853b6e4` |
| Broad focused tests | `4e1a6103542e7fdb9e49b5b4132a3d85d8ce9362` |
| Final affected tests / static gates / native sample preview | `37b9a85b30a5c341a99c623107314daa5d77d541` |

The evidence commit contains this report and `evidence.json`; its full HEAD is reported
in the delivery response. Evidence-only commits retain the tested implementation identity.
The two tested trees, dependencies, configuration, input files, JUnit reports and retained
logs are bound by hashes in [evidence.json](evidence.json).

At `4e1a6103…`: 171 unit/architecture cases (plus 5 subtests) and 31 real PostgreSQL
integration cases passed, with zero failures/skips. The final implementation changes only
the response status of successful expansion repair admission; its native resume paths,
new empty-findings and pre-send budget cases passed in 2 affected PostgreSQL tests at
`37b9a85b…` (208.05 s). These repeated tests are not additional unique coverage. Both trees
passed `make validate head-integrity-check`; old test results retain their original SHA.

## Defects and fixes

1. **Planning completion could lose its first reading work.** The exact independent-worker
   interruption reproduced the baseline planning function leaving Work `SUCCEEDED` with
   zero reading children. This red reproduction used the working test harness, not a
   qualification of the whole baseline tree.
   `_execute_analysis_planning` in `source_import/application.py` now commits the planning
   success, deterministic first Operation/Work and READY transition inside one owning UoW.
   The reading-only profiling-to-planning edge and curated root READY edge also now commit
   atomically. Existing observation/review/revision/next-chapter and synthesis/MKAOS UoWs
   are retained. Exit 75 before child registration and exit 76 after registration but
   before commit leave Work `RUNNING` and zero committed children. After lease takeover,
   the same planning artifact is `REUSED` and exactly one initial child succeeds. Exit 74
   after Provider receipt persistence recovers with one Effect and unchanged replay budget.

2. **Returned, invalid output lost its actual-input coverage.** An isolated reproduction
   loads the exact baseline `_invalid_result`; its result contains only issues, phase,
   repair round and validation error. This narrow reproduction intercepts finalization;
   it is not a baseline full-provider test. Real PostgreSQL/native validation now proves
   the complete repaired path: observation, review, repair and synthesis failures retain
   durable request/receipt evidence. `execution.py`, `reading_evidence.py`,
   `narrative_execution.py`, `reading_scope.py` and `SourceImportOperationsRecords` bind
   final assembled input and derive queries from recorded Effects/receipts. Codex subprocess
   tests separately prove invalid JSON and output Schema failures retain restricted return
   and observed-usage receipts while remaining failed execution results. They are fixtures.

The expanded native API test exposed another concrete defect: `authority_app.py` injected
an unconfigured Source Import application. It now reuses `build_source_import_application`
with the existing Production Execution composition. API preview, bounded admission replay,
failed evidence and cross-project denial are exercised through normal routes.

## Recovery, coverage and failure semantics

`reading_recovery.admit_expansion_repairs` creates a stable reconciliation Operation through
the existing Kernel. `execute_expansion_repair` references the original frozen plan and
adds the missing first child without changing historical terminal results. Concurrent CLI
`resume` calls converge on identical repair Operations and return `PROCESSING`. Current
rights, selection and fence checks remain required. Historical terminal failures need a
new governed request; stale authorization blocks new dispatch. Older frozen runtime
contracts can replay compatible receipts but cannot silently acquire the new runtime for
fresh calls. No parallel queue, Authority, writable state copy or new table was added.

`target_progress` counts the entire frozen logical target set. Missing work is
`NOT_EXPANDED`; retries and revisions do not inflate chapter counts. Expanded, confirmed
input, reviewed, accepted, unprocessed and unexpanded counts are separate. Native empty
findings have four confirmed and reviewed fixture chapters, four
`NO_APPLICABLE_FINDINGS` outcomes and zero Candidates. Blocked/partial runs never report
those omitted targets as complete. Status summaries contain at most 20 targets; `targets`
and `results` paginate without exporting whole text.

The input manifest includes exact chunks, versions, hashes, UTF-8 ranges, unit bindings,
Processing/transform, final request/materialization hash, Prompt/Skill and token policy.
`CONFIRMED_RETURNED` remains true when output validation fails; `PREPARED` is not reading
proof; ambiguous dispatch remains `UNKNOWN`; missing historical manifests are
`NOT_RECORDED`. Receipt reuse references its origin and does not imply another send.
Synthesis reads lower observations and does not count as another full-text read.

Evidence queries enforce project/job/stage, current Source authorization, frozen source
version, recorded input range and UTF-8 boundaries. Native CLI/API queries succeed on
failed-but-returned stages and reject untransmitted chunks, split UTF-8 and other projects.
Pre-send budget rejection retains `PREPARED`, no dispatch receipt and no readable coverage.
Raw failed returns remain restricted diagnostics, not accepted Observations or Candidates.
Repairs receive the exact prior return/candidate, blocker identities, preservation rules and
original evidence range. Dropping a finding cannot resolve its blocker. Recovery reuses
recorded returns; new revision calls share the original budget. Missing observed usage holds
its reservation as unknown. Account entitlement never implies zero cost or zero hidden CLI
usage. Existing post-return authorization revocation and consumption-negative tests pass.

## Prepared real sample and quality boundary

Source: [Project Gutenberg 23962, 西遊記](https://www.gutenberg.org/ebooks/23962), acquired
UTF-8 file, 2,264,069 bytes, SHA-256
`af3c9e408c0c58595b666ed9981b6fa1e9343f4bbc78309b1cb0818c32fc1f58`.
Native Source import, Agent metadata review and reprocessing excluded Gutenberg header and
license footer while preserving raw bytes. Processing is structurally usable with 100
chapter records and **UNKNOWN full-book coverage**, not a complete-book verification.

Project: `wp-corpus-real-analysis-01`. Processing:
`corpus-processing:5a3968b6c14b0c799f126d560009b43b59c2c82a5055ccdc56f8ade919e1f67b`.
Frozen curated revision:
`corpus-curated-revision:365bc0c3dcf692b8ace2a9bab9f6e52c803d7d669a946ae486bafcbda0a536bb`.

The frozen preview selects one member, chapters 1–3, causal constraints, character choice
and cost, and information gap; no adjacent context; at most one repair per object.
The final CLI/API previews are identical. Proposed ceilings are 18 calls / 240000 tokens,
with 10 base model calls and up to 18 calls when every object uses its revision allowance.
These numbers are proposals, not authorization or guaranteed capacity. Final requests need
the actual model/accounting contract; inadequate budget stops explicitly. Hidden Codex
framing is unobserved and is not covered by an application-visible token bound.

A frozen pre-run benchmark has 8 exact-source Agent checks and 4 negative controls.
Examples: the public promise and verified action preceding recognition in chapter 1;
chapter 2's demonstrated skill, actual expulsion and separately framed warning of future
harm; chapter 3's difference between the protagonist's claim of immunity and the recorded
summons, and the court's recruitment purpose. Every check has chunk offsets and hashes.
It distinguishes narrator, character belief/report and analyst inference. It forbids future
chapter facts, unsupported causality, universal commercial claims and protected story
combinations. It is **Agent annotation, not independent human ground truth**. Its freeze
hash is `6fcd4ceef1fececa053c93434dc7d47a7089e9964c6af929d07767b62668a17a`.

**Actual model calls: 0. Actual analysis jobs: none admitted. Read/review/accepted coverage:
0/3. Candidate/Card/Pack counts: 0/0/0. Real analysis quality: NOT_EVALUATED.** No actual
observation or synthesis is invented. The engineering fixture separately produced two
Candidates awaiting review, no Cards, and synthesized referenced lower observations.
Its directed repair changes “A choice occurs” after a `VAGUE_SUMMARY` blocker and preserves
exact evidence/uncertainty; that scripted response is not literary-quality proof. Invalid
review downgrade stays blocked. No semantic accuracy/recall, retention or commercial
improvement is claimed. No original planning, prose generation or Canon mutation was run.

## Native operation, retention and remaining authorization

All executable preparation, preview and post-authorization commands are in
`/Volumes/DevSSD/Development/Workspace/task-data/WP-CORPUS-REAL-ANALYSIS-01/NATIVE-OPERATIONS.md`.
They use `python -m novel_forge.cli.authority corpus` actions `curated`, `reading-preview`,
`analyze`, `run`, `status`, `targets`, `results`, `evidence`, `pause`, `resume`; no internal
scheduler helpers are needed. Reviewed sample identities, exact scopes, request proposal,
account-entitlement route template and pre-run benchmark are adjacent durable files.

The ChatGPT application binary was identified as Codex CLI `0.153.4`; its digest is retained.
The PATH installation failed its version probe with missing native binary and was left
unchanged. No login/key inspection or model invocation supplied authorization. Missing:
explicit user grant for this account/backend/model, exact scope and purpose, shared total
calls/tokens and repair/retry allowance, stop conditions, accounting proof boundary,
authorization reference, and verified account/configuration identity. The template leaves
these fields blank. Existing Pro subscription or an arbitrary string is insufficient.
Real execution remains `AUTHORIZATION_REQUIRED`; Card approval requires its separate
existing decision path and is not a completion condition.

Task-owned PostgreSQL 16.15/pgvector 0.8.6, local object storage and a private virtualenv were
used. Common runtimes and system configuration were not changed. No DDL: migration head
remains `20260910_0128_corpus_operations` (129 registered migrations). No historical migration
rerun was performed to pad evidence; fresh task databases used native migration setup.
No all-repository/P0/UI run, paid API run, full-corpus download, embedding or market/Reader
Feedback expansion. Focused shared-Provider and API regression scope follows the actual
changed composition/receipt boundaries.

Sample and engineering database dumps, fixture object archive, source file, failed evidence
and reports are retained under the Git-external task directory. `pg_restore --list` verifies
the sample dump catalogue; no user database was restored or rebuilt. Temporary tests are
fixtures, not long-term business IDs. Task API and PostgreSQL are stopped; retained data and native restart commands remain.
The original user worktree is unchanged. End fetch
shows no main drift; remote main does not contain this local delivery.

| Verdict | Result |
|---|---|
| READING_EXPANSION_AND_RECOVERY | PASS |
| FAILED_STAGE_INPUT_EVIDENCE | PASS |
| NATIVE_ANALYSIS_OPERATION_LOOP | PASS (native scripted engineering) |
| TARGET_COVERAGE_ACCOUNTING | PASS |
| BOUNDED_ANALYSIS_PREFLIGHT | PARTIAL (real route/account policy still requires authorization) |
| REAL_MODEL_AUTHORIZATION | REQUIRED |
| REAL_MODEL_EXECUTION | NOT_RUN |
| REAL_ANALYSIS_QUALITY | NOT_EVALUATED |
| MKAOS_CANDIDATE_LINEAGE | PARTIAL (mechanism regression passes; real Candidate not produced) |
| FOCUSED_ENGINEERING_QUALIFICATION | PASS |
| REMOTE_MAIN_INCLUDES_DELIVERY | NO |
