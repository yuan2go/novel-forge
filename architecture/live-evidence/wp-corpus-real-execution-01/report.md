# WP-CORPUS-REAL-EXECUTION-01

**READY_FOR_AUTHORIZATION.** No real model invocation, analysis job, observation,
synthesis, revision or MKAOS Candidate was created. The verified local sample
is restored and the no-model preparation is executable. Authorization and
model/account choice remain pending; configuration references cannot grant usage.

| Identity | Full SHA |
|---|---|
| Fetched baseline / final origin/main | `dfb84a946f61a74714633bceb599609c8e8fcde4` |
| Initial implementation | `347e0602d8904f7a5aa57c535d219195b01a7e9b` |
| Final implementation | `60ebe29059034c985881c22fd96bc599092b7c67` |
| Broad focused tests / native CLI/API | `395ac21ac50401e66ec69c1654f42810870675ee` |
| Final affected tests / static gates / offline flags | `31d14a4f1f1c0f060c818df3eabc2a4339e5940e` |

The evidence commit owns this report and [evidence.json](evidence.json); its full HEAD is
reported in the delivery response. No push, PR or merge. Main includes the prior analysis
work package through PR 75, but not this delivery. End fetch found no drift. The original
user worktree was preserved.

## Restored local sample

Task storage is `/Volumes/DevSSD/Development/Workspace/task-data/WP-CORPUS-REAL-EXECUTION-01`.
The original sample dump was verified against prior evidence and **actually restored**
`pg_restore --exit-on-error --no-owner` into a new private PostgreSQL cluster,
`corpus_real_execution` on loopback port 52112. No shared database was changed.
All 49 prior artifact hashes matched. Both original and restored dumps are retained.
The new task reuses the prior private PostgreSQL 16.15/pgvector installation and a copied
virtualenv; it does not upgrade the common runtime or depend on `/tmp` business IDs.

Native migration status confirms all 129 migrations, head
`20260910_0128_corpus_operations`. No DDL, new migration or historical migration rerun.
470 available Blob references verified against copied bytes/digests; two Source Bridges,
Project/Workspace, SourceWork, Edition/Processing and current frozen selection were checked.
The native CLI/API previews also verify exact selected bytes, UTF-8 unit coverage and
current availability. A missing object is rejected; cross-project preview is rejected.

Sample: Gutenberg 23962, 《西遊記》 underlying-public-domain RESEARCH sample.
Raw file: 2,264,069 bytes, SHA-256
`af3c9e408c0c58595b666ed9981b6fa1e9343f4bbc78309b1cb0818c32fc1f58`.
Project/Workspace: `wp-corpus-real-analysis-01` / `ws-corpus-real-analysis-01`.
Processing: `corpus-processing:5a3968b6c14b0c799f126d560009b43b59c2c82a5055ccdc56f8ade919e1f67b`.
Revision: `corpus-curated-revision:365bc0c3dcf692b8ace2a9bab9f6e52c803d7d669a946ae486bafcbda0a536bb`.
Exact Edition, SourceWork and Bridge references are in `prepared-identities.json` source file.

Scope: one member, first three logical chapters, no adjacent context; action causality,
character choice/cost and information gaps; one repair per observation/synthesis object.
Normalized chapter bodies total 65,082 bytes; six chunks include boundary whitespace and
total 65,086 bytes. These are bytes, not tokens. Chapter ordering and original raw locations
match the earlier frozen benchmark. Header/footer exclusions remain in the reviewed
Processing. Full-book coverage remains **UNKNOWN**, not COMPLETE.

## Codex configuration and bounded preparation

Explicit executable: `/Applications/ChatGPT.app/Contents/Resources/codex`.
Observed version: `codex-cli 0.153.4`.
Binary SHA-256: `c147aa90d34139599711fb568102ceefc6319ca1ac5cb6f4056ca46a1834edd9`.
No global install was upgraded or replaced. The application path is explicit; no PATH fallback.
Current process environment contains `/Users/yuan/.codex-claude`; this is an observation,
not designation or authorization. Authentication files were not read. Requested, frozen
real-route, invocation and observed model identities are **unset/not invoked**.

The real gaps fixed are in `CodexCliExecutionBackend._prepare_payload`,
`build_production_execution_composition`, `codex_configuration.inspect_local_codex`,
and `reading_scope.preview_reading`, exposed through existing CLI/API `reading-preview`:

- Freeze the explicit `NOVEL_FORGE_CODEX_HOME` and local policy into route identity;
  override inherited account-directory selection. Changed binding needs a new request.
- Disable external-content tools and host Skill/AGENTS discovery at CLI configuration,
  alongside existing isolated workspace, ignored user config/rules and returned tool checks.
  Account-entitlement invocation forces ChatGPT login mode; no paid fallback.
- Verify actual local Chunk/Blob bytes in no-model preflight, while marking them `NOT_SENT`.
  Optional local Codex inspection reports process identity/drift and missing configuration,
  and explicitly leaves remote availability and authorization unverified.

The configured feature overrides were checked using the actual local executable's offline
feature listing. A failed early probe showed `unified_exec=false` is not an effective local
restriction in this version; it was removed as an ineffective setting. Shell access is
controlled by `shell_tool=false`. The separate native `view_image` feature is explicitly
disabled too. [OpenAI configuration reference](https://developers.openai.com/codex/config-reference/)
and [tool registration source](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs)
support the distinction. This is local configuration evidence, not real remote enforcement
or remote availability proof. Existing post-return tool checks remain active.

Proposed grant: 18 platform calls / 240000 application-observable tokens, concurrency 1.
Classification, reading, review, repairs, synthesis, extraction and retries share the total.
Existing project ledger caps and conservative unknown reservations apply across new requests;
request ceilings cannot increase those absolute project caps. No new budget/approval system.
The proposed allowance is not an authorized remaining allowance. Actual model reservations,
sends and observed tokens are zero. No unknown reservation exists. Unobserved internal Codex
framing/retry overhead is not represented as zero or as a complete remote hard bound.
Later-stage tokens require actual outputs and final assembled-request admission.

## Quality and knowledge boundary

The unchanged pre-run benchmark's digest is
`6fcd4ceef1fececa053c93434dc7d47a7089e9964c6af929d07767b62668a17a`.
All eight exact-source Agent checks match restored chunks and UTF-8 positions; the four
negative controls and frozen reading identity remain unchanged. It is Agent annotation,
not independent human truth, and is not provided to the analysis model.

Actual reading/review/acceptance: **0/3, 0/3, 0/3**. Source preflight is not reading evidence.
No real observation/synthesis examples or repair comparisons exist to report. No mechanical
output pass rate or semantic accuracy/recall is claimed. Real quality is NOT_EVALUATED.
Native MKAOS queries: Candidate 0, Card 0, Pack 0. No approval or production consumption.

## Verification, retention and next operation

At `395ac21…`: 50 focused tests and 5 subtests passed, no failure or skip; native CLI/API
previews were identical against the restored PostgreSQL sample. Missing-object and
cross-project negatives passed. At `31d14a4…`: the final image-tool restriction passed the
23 affected Codex/configuration tests and the offline effective-feature probe. The earlier
50-test/native results retain their original SHA; repeated cases are not added as unique
coverage. Both tested trees passed `make validate head-integrity-check`.
No full-suite/P0/UI run, model ping, paid API call or real-model crash injection.

One initial development test command omitted `PYTHONPATH=src` and loaded an old installed
package from the copied venv; its failures were corrected by running the intended tree.
Its counts are not used as product-regression failures or acceptance evidence. Dependency
identity uses installed metadata; no pip/system installation was added to collect it.

`NATIVE-OPERATIONS.md` in the task directory contains restart, exact CLI/API preflight,
authorization-dependent analyze/run/status/targets/results/evidence/pause/resume commands,
fixed-cap cumulative accounting instructions and stop commands. The route template leaves
account, model and grant fields blank. Source/raw data, benchmark, backups, logs, JUnit,
object inventories and configuration remain outside Git; hashes bind the retained evidence.
The private API and PostgreSQL are stopped and their ports verified closed.

Missing user confirmation: designated account directory, explicit model (or approval of a
verified Source ModelProfile), the declared scope and shared allowance, concurrency/repair
limits, stopping conditions and the application-visible accounting boundary. Only after
that confirmation may a normal first stage test remote execution within the same budget.

| Verdict | Result |
|---|---|
| LOCAL_RUNTIME_RESTORATION | PASS |
| CODEX_BACKEND_CONFIGURATION | PARTIAL — binary/local policy verified; account/model/grant pending |
| REAL_EXECUTION_AUTHORIZATION | REQUIRED |
| NATIVE_REAL_ANALYSIS | NOT_RUN |
| ACTUAL_READING_COVERAGE | confirmed 0/3; reviewed 0/3; accepted 0/3 |
| EVIDENCE_AND_REPAIR | NOT_EVALUATED |
| REAL_ANALYSIS_QUALITY | NOT_EVALUATED |
| REAL_MKAOS_CANDIDATES | 0; none created, Card/Pack 0/0 |
| FOCUSED_REGRESSION | PASS |
| REMOTE_MAIN_INCLUDES_DELIVERY | NO |
