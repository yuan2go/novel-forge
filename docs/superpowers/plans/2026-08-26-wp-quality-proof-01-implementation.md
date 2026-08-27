# WP-QUALITY-PROOF-01 Implementation Plan

> Execute this plan on `codex/wp-quality-proof-01` in
> `/Users/yuan/projects/novel-forge-worktrees/wp-quality-proof-01`.
> Do not modify or merge `main`. Do not execute a real-provider Chapter
> campaign until Tasks 1–11 and the exact-SHA freeze gate have passed.

Design: `docs/superpowers/specs/2026-08-26-wp-quality-proof-01-design.md`

Effective base: `476090195e6718d9a2585f5b2ddd51dc88efd415`

Initial migration head: `20260825_0100_hierarchy_closure`

## Evidence rules for every task

- Use tests first for contract changes and bugs.
- Keep PostgreSQL Authority, Command Kernel, ProductionExecutionComposition,
  Chapter/Book Authority and Reader Calibration ownership intact.
- Fixture/scripted results prove only protocol and engineering behavior.
- Do not lower thresholds or turn missing evidence into zero/pass.
- Commit each completed slice with the listed commit boundary.
- Preserve unrelated worktrees and `.idea/modules.xml`.

## Task 1: Add the 0101 quality-qualification schema

Files:

- Create: `src/novel_forge/storage/migrations/versions/v20260826_0101_quality_qualification.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Create: `tests/unit/test_quality_qualification_migration.py`
- Modify: `tests/unit/test_migration_graph.py` only if the canonical graph test
  requires the new head explicitly.

Steps:

1. Write failing migration tests for:
   - down revision `20260825_0100_hierarchy_closure`;
   - one forward-only migration head;
   - campaign/subject/evidence/decision tables;
   - extensions to human task/pair/decision;
   - `CANNOT_JUDGE`, scope/version/dimension/adjudication constraints;
   - immutable pack export and adjudication tables/views/indexes;
   - no destructive downgrade statements.
2. Run:

   ```bash
   .venv/bin/python -m pytest tests/unit/test_quality_qualification_migration.py -q
   ```

   Expected: fail before implementation.
3. Implement the migration with explicit checks and indexes. Preserve
   historical `REJECT_BOTH` rows while forbidding it for the new protocol.
4. Add `20260826_0101_quality_qualification` to the manifest.
5. Rerun the focused tests and migration manifest check.
6. Commit: `feat: add quality qualification persistence`

## Task 2: Implement fail-closed campaign and evidence contracts

Files:

- Create: `src/novel_forge/modules/chapter_quality_authority/qualification.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/__init__.py`
- Create: `tests/unit/test_quality_qualification_domain.py`

Steps:

1. Write failing tests for:
   - exact manifest fields and canonical digest;
   - lifecycle transitions `DRAFT -> FROZEN -> RUNNING ->
     WAITING_HUMAN_EVIDENCE/EVALUATING -> COMPLETE`;
   - immutable route/pack/profile/Foundation/Planning/Realization/budget
     lineage;
   - exact ChapterGroup ranges `[1,4]` and `[5,8]`;
   - Chapter 9 rejection;
   - L1/L2/L3 separation;
   - severe L1 failure forcing `FAIL`;
   - missing evidence forcing `NOT_PROVEN`;
   - no-human forcing `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`;
   - one-human `HUMAN_EVIDENCE_LIMITED`;
   - two-human evidence remaining `BOUNDED_HUMAN_EVIDENCE`.
2. Implement frozen dataclasses/enums and pure evaluators. Do not add storage
   imports to the domain module.
3. Add diagnostics that state what remains unproven.
4. Run the focused tests.
5. Commit: `feat: define bounded quality evidence semantics`

## Task 3: Fix ChapterOutcome v3 longitudinal compatibility

Files:

- Modify: `src/novel_forge/modules/chapter_quality_authority/accepted_projection.py`
- Modify: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Create or modify: `tests/integration/test_quality_qualification_postgres.py`
- Modify: `tests/unit/test_canon_semantic_quality_authority.py`

Steps:

1. Add a failing PostgreSQL test that accepts Chapter 1 with
   `chapter-outcome-v3`, builds Chapter 2 Context and asserts the exact
   Chapter-1 accepted observation is present.
2. Assert v1 is rejected for current projection, v2 remains readable for
   historical compatibility, and v3 is canonical.
3. Change the query from v2-only to an explicit supported set with v3 as the
   current contract.
4. Bind Canon and Narrative Realization versions where available and reject
   mixed project/Book/chapter lineage.
5. Run focused unit and PostgreSQL tests.
6. Commit: `fix: project accepted chapter outcome v3 into quality`

## Task 4: Build accepted longitudinal momentum/payoff/repetition evidence

Files:

- Create: `src/novel_forge/modules/chapter_quality_authority/longitudinal.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/accepted_projection.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/domain.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/__init__.py`
- Create: `tests/unit/test_quality_longitudinal_evidence.py`
- Modify: `tests/unit/test_canon_semantic_quality_authority.py`

Steps:

1. Add failing tests with an eight-Chapter accepted sequence for:
   - activity without causal progress being stagnation;
   - causal event coverage and irreversible change momentum;
   - protagonist decisions and antagonist responses;
   - obligation created/maintained/escalated/due/paid/partial/overdue/
     abandoned transitions;
   - setup-payoff latency/cadence/clustering;
   - scene-function, conflict-solution, emotional, information, reaction,
     antagonist, hook and prose repetition kept separate;
   - lexical similarity not deciding semantic repetition;
   - Arc evaluation not averaging Chapter scores;
   - Volume slice evaluation not averaging Arc scores;
   - Reader dimensions and source lineage retained;
   - missing semantic observation reported `NOT_OBSERVED`.
2. Extend compact accepted observations using existing Plan, Outcome v3,
   StoryState, Arc/Obligation and quality evidence. Drop full prose after
   bounded feature extraction.
3. Implement deterministic reducers and typed reports for Chapter sequence,
   Arc and Volume slice.
4. Replace the old eight-dimension threshold summary as the canonical report;
   keep a deterministic compatibility projection only if an active consumer
   requires it.
5. Run focused tests.
6. Commit: `feat: add accepted longitudinal quality evidence`

## Task 5: Extend the canonical human blind protocol

Files:

- Modify: `src/novel_forge/modules/reader_calibration/domain.py`
- Modify: `src/novel_forge/modules/reader_calibration/application.py`
- Create: `src/novel_forge/modules/reader_calibration/blind_export.py`
- Modify: `src/novel_forge/modules/reader_calibration/__init__.py`
- Create: `tests/unit/test_human_blind_protocol.py`
- Modify: `tests/integration/test_reader_calibration_postgres.py`
- Modify: `tests/integration/test_quality_qualification_postgres.py`

Steps:

1. Write failing domain tests for:
   - `CANNOT_JUDGE` and no preferred candidate;
   - exactly frozen dimension keys and ordinal ranges;
   - protocol/evaluation version, evaluator identity class, scope and
     confidence validation;
   - eight Chapter pairs balanced 4/4 per evaluator;
   - reviewer 2 complementary ordering;
   - deterministic replay with the same secret and changed ordering with a new
     campaign version;
   - reviewer decisions hidden from other reviewers;
   - disagreement and adjudication preserving raw decisions.
2. Write failing pack-export tests that scan for forbidden identity/provider/
   model/prompt/score/AssetVersion fields and require opaque tokens only.
3. Extend Reader Calibration application methods for versioned tasks, scoped
   pairs, decisions, pack registration, agreement and adjudication.
4. Implement deterministic balanced pack export plus private mapping hash.
5. Add PostgreSQL idempotency and uniqueness tests.
6. Run focused unit/PostgreSQL tests.
7. Commit: `feat: implement auditable human blind comparison`

## Task 6: Converge calibration v2 and remove current v1 registration

Files:

- Modify: `src/novel_forge/modules/chapter_quality_authority/calibration_v2.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/__init__.py`
- Modify: `src/novel_forge/modules/content_authority/handlers.py`
- Modify: `src/novel_forge/modules/content_authority/codecs.py`
- Delete: `src/novel_forge/modules/chapter_quality_authority/calibration.py`
- Delete: `tests/unit/test_quality_calibration_foundation.py`
- Modify: `tests/unit/test_quality_calibration_v2.py`
- Modify: `tests/integration/test_content_authority_runtime_postgres.py`
- Add architecture assertion in the nearest current Quality boundary test.

Steps:

1. Add failing tests for v2 pair choices, scope, dimensions, evaluator class,
   confidence, ordering and independence metadata.
2. Add diagnostics for pairwise agreement, weighted ordinal agreement, rank
   correlation eligibility, false positive/negative, confidence bins,
   position bias and stability.
3. Assert bounded samples always remain `UNCALIBRATED / BOUNDED_EVIDENCE`.
4. Assert same-model or same-provider relationships cannot independently
   activate a profile.
5. Remove v1 operation registrations/codecs/tests and dead imports. Historical
   Authority assets remain untouched.
6. Run Content Authority unit/PostgreSQL tests.
7. Commit: `refactor: converge quality calibration on v2`

## Task 7: Replace hard-coded Reader feedback flags with real evidence

Files:

- Modify: `src/novel_forge/modules/book_followup_authority/query.py`
- Modify: `src/novel_forge/modules/book_followup_authority/coordinator.py`
- Modify: `src/novel_forge/modules/book_followup_authority/domain.py`
- Modify: `src/novel_forge/modules/book_followup_authority/handlers.py`
- Modify: `tests/unit/test_reader_outcome_and_recap_domain.py`
- Modify: `tests/unit/test_reader_outcome_decision_policy.py`
- Modify: `tests/integration/test_book_followup_authority_postgres.py`
- Modify: `tests/integration/test_chapter_group_authority_postgres.py`

Steps:

1. Add failing integration tests proving the coordinator loads the actual
   previous Reader states, qualification decision, disagreement/bias/OOD/drift
   and recent trend rather than constants.
2. Add a two-ChapterGroup test proving Group 1 accepted outcomes feed Reader
   State and Recap before Group 2 future recommendation.
3. Require Reader Proxy reports to say `READER_PROXY_ADVISORY`.
4. Permit an unqualified proxy to create a bounded advisory recommendation
   with `activation_allowed=false`; keep direct body/Canon/StoryState/plan
   mutation forbidden.
5. Ensure only qualified evidence can request an activation-eligible future
   adjustment and Planning/PlanChange still owns activation.
6. Run focused tests.
7. Commit: `fix: feed real reader evidence into governed recap`

## Task 8: Persist campaigns and final qualification through existing Authority

Files:

- Create: `src/novel_forge/modules/chapter_quality_authority/qualification_application.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/__init__.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `src/novel_forge/api/routers/quality_qualification.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `tests/unit/test_quality_qualification_api.py`
- Modify: `tests/integration/test_quality_qualification_postgres.py`
- Add the router to architecture manifests if required.

Steps:

1. Write failing tests for campaign admission/freeze/start, subject binding,
   evidence binding, pack export status, decision recording, query and resume.
2. Require Command Kernel operation identity, project/workspace scope,
   immutable input snapshot, trace/span and exact output AssetVersions.
3. Implement application methods against the 0101 tables and shared Authority
   asset writer. Do not call Providers from transactions.
4. Expose operator endpoints for campaign status, reviewer-safe pack export,
   decision import and final evaluation. Reviewer endpoints must not expose the
   private mapping.
5. Add recovery/idempotency tests around post-commit interruption.
6. Commit: `feat: wire quality qualification through authority`

## Task 9: Implement the bounded scripted campaign dry-run

Files:

- Create: `config/proof_campaigns/quality_qualification_v1.json`
- Create: `src/novel_forge/modules/runtime_proof/quality_campaign.py`
- Modify: `src/novel_forge/modules/runtime_proof/__init__.py`
- Create: `scripts/run_bounded_quality_qualification.py`
- Create: `tests/unit/test_bounded_quality_campaign.py`
- Create: `tests/integration/test_bounded_quality_campaign_postgres.py`

Steps:

1. Write failing manifest tests for exact two-by-four scope, frozen hashes,
   explicit route/pack/profile/budget identities and Chapter 9 rejection.
2. Implement subcommands:
   - `dry-run`
   - `freeze`
   - `run-real`
   - `export-blind-packs`
   - `record-human`
   - `evaluate`
   - `resume`
3. `dry-run` must use scripted providers and the actual Canonical Hierarchy:
   qualified Foundation -> Formation -> BookDesign v5 -> Book/Volume/Arc ->
   Group 1 -> Chapters 1–4 -> Reader/Recap -> Group 2 -> Chapters 5–8 -> final
   longitudinal projection.
4. Assert eight accepted Chapters, no duplicate provider effects, exact
   accepted cursor, one primary Arc evaluation, bounded Volume report and
   exported reviewer packs.
5. Inject recovery after receipt, candidate, acceptance and pack export.
6. Run the scripted dry-run twice and compare deterministic identities while
   allowing nondeterministic timestamps only in explicit envelope fields.
7. Commit: `feat: add bounded quality campaign harness`

## Task 10: Remove obsolete Quality and campaign surfaces

Files:

- Delete: `src/novel_forge/evaluation/quality.py`
- Delete: `src/novel_forge/modules/runtime_proof/longform_campaign.py`
- Delete: `scripts/run_longform_narrative_campaign.py`
- Delete: `scripts/run_long_chain_to_completion.py`
- Delete: `config/proof_campaigns/longform_narrative_v1.json`
- Delete: `config/proof_campaigns/longform_narrative_v2.json`
- Delete: `tests/unit/test_longform_narrative_campaign.py`
- Delete: `tests/unit/test_longform_narrative_campaign_runner.py`
- Delete tracked files under `generated/longchain-webnovel/`.
- Remove dead `/quality-eval-v2` and `/long-chain-proof` routes/components/nav
  entries, or replace `/quality-eval-v2` only with the new live Authority
  console if doing so remains bounded.
- Modify architecture tests/manifests affected by removal.

Steps:

1. Add architecture assertions that obsolete 300/400-Chapter runners and v1
   calibration operation registrations are absent.
2. Remove dead code, configs, generated output and missing-endpoint UI claims.
3. Verify Git history remains the immutable record; do not alter historical
   exact-SHA qualification files.
4. Run admin lint/tests and architecture tests.
5. Commit: `chore: retire obsolete quality proof surfaces`

## Task 11: Synchronize canonical docs and qualification procedures

Files:

- Modify: `docs/architecture/canonical-overall-design.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/product/novel-production-flow.md`
- Modify: `docs/development/testing.md`
- Modify: `docs/README.md`
- Create: `docs/operations/quality-qualification.md`
- Create later at frozen SHA:
  `docs/qualification/2026-08-26-wp-quality-proof-01.md`

Steps:

1. Document L1/L2/L3, blind evidence, Reader Proxy, non-averaging Arc/Volume
   evaluation and fail-closed status semantics.
2. Document dry-run/freeze/run/resume/export/import/report commands and exact
   evidence interpretation.
3. Mark historical exact-SHA reports as historical without rewriting their
   results.
4. State explicitly that two evaluators are bounded evidence and incomplete
   human work yields `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`.
5. Run link/search consistency checks.
6. Commit: `docs: define canonical quality qualification`

## Task 12: Focused and full engineering qualification

Run in this order, fixing real defects before proceeding:

1. Focused unit suites for all changed domains.
2. Focused PostgreSQL suites:

   ```bash
   NOVEL_FORGE_DATABASE_URL=postgresql://yuan@localhost/novel_forge_quality_proof_test \
     .venv/bin/python -m pytest \
       tests/integration/test_quality_qualification_postgres.py \
       tests/integration/test_reader_calibration_postgres.py \
       tests/integration/test_book_followup_authority_postgres.py -q
   ```

3. Fresh migration proof into a new isolated database.
4. Upgrade proof from migration 0100 to 0101 with representative historical
   v1/v2 human rows and ChapterOutcome v2/v3 evidence.
5. Composition root and API/worker reachability.
6. Scripted bounded campaign with recovery injection.
7. Canonical gates:

   ```bash
   make authority-test
   NOVEL_FORGE_DATABASE_URL=postgresql://yuan@localhost/novel_forge_quality_proof_test make authority-postgres-test
   .venv/bin/python -m pytest -q
   npm --prefix web/admin ci
   npm --prefix web/admin run lint
   npm --prefix web/admin test
   make validate
   make authority-compose-config-check
   git diff --check
   ```

8. Run fresh and upgrade migration commands named by the current migration
   test harness.
9. Ensure the worktree is clean after committing fixes.

Commit any regression fixes in bounded commits. Do not freeze a campaign SHA
until every required gate is green or explicitly environment-blocked by a gate
that does not affect code correctness. PostgreSQL/fresh/upgrade/recovery/full
regression are mandatory and cannot be environment-waived.

## Task 13: Freeze and execute the real-provider two-by-four campaign

Preconditions:

- clean named branch;
- exact HEAD recorded;
- migration head 0101;
- all Task 12 mandatory gates green;
- Codex CLI login and version recorded;
- isolated PostgreSQL database and MinIO namespace ready;
- no existing unfinished campaign with the same identity.

Steps:

1. Run `freeze` to materialize and hash the exact manifest.
2. Verify every route/model/reasoning/Pack/Prompt/Skill/Foundation/Planning/
   Realization/Context/Quality/Reader/budget field.
3. Run `run-real` in the foreground with the frozen ceilings.
4. Stop at the first terminal failure for a severe invariant, budget drift,
   route drift or Chapter 9 attempt. Use `resume` only with the same frozen
   manifest and receipts.
5. Require eight committed acceptances, two completed ChapterGroups, Provider
   receipts/usage/failures/retries and final L1/L2/L3 automated reports.
6. Export two reviewer-specific blind packs. Do not inspect or expose the
   private A/B mapping in reviewer artifacts.
7. If human responses are not yet complete, set lifecycle
   `WAITING_HUMAN_EVIDENCE` and qualification `NOT_PROVEN`.

Do not execute 30/100/300 Chapters or any background continuation.

## Task 14: Final report, publication and Draft PR

Steps:

1. Generate the exact-SHA qualification report with all 25 requested handoff
   fields and the bounded-evidence disclaimer.
2. Add actual human/Judge agreement only from recorded human decisions. Never
   generate human evidence with a model.
3. Rerun doc consistency, `git diff --check` and the smallest final smoke gate
   required after report generation.
4. Confirm clean worktree, branch, final SHA, migration head and no unrelated
   changes.
5. Push `codex/wp-quality-proof-01`.
6. Open a Draft PR against `main`; record that it depends on / includes the
   unmerged Hierarchy Closure ancestry unless PR #30 has merged meanwhile.
7. Report exact tests, Provider usage, campaign result, human status, what is
   unproven and recommended next evidence step.
