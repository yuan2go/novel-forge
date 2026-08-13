# Long-form Narrative Proof Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and validate one cumulative 300-chapter Novel Forge book through the current PostgreSQL Production Runtime with immutable, queryable evidence.

**Architecture:** Add a pure contract/evaluation module and a resumable operator harness around existing Book/Chapter/Planning Authority surfaces. Keep PostgreSQL/MinIO and current Operation/Attempt/Lease/Fence/ExternalEffect/Provider/Quality/Replan/MKAOS implementations as the only execution and truth planes.

**Tech Stack:** Python 3.12, PostgreSQL 16, psycopg, MinIO, Codex CLI, pytest, Ruff, JSON/Markdown evidence exports.

## Global Constraints

- Baseline is exact `origin/main@3d89e805175ccb4a40c208ce434ed3fe946b38d0` with migration head `20260812_0086_corrective_generation_terminal_lineage`.
- Campaign version is `longform-narrative-v1`; Ground Truth and thresholds never mutate after Chapter 1.
- No new Agent, Workflow Engine, scheduler, retry plane, Provider, database, Canon, or Proof Authority.
- Chapters 1-30, 31-100, and 101-300 belong to one Book run and are accepted sequentially.
- Fixture/mock evidence cannot satisfy a real-provider, longform, reader, or production gate.
- Code changes require full Engineering Qualification before affected runtime proof continues.

---

### Task 1: Frozen Campaign contract

**Files:**
- Create: `config/proof_campaigns/longform_narrative_v1.json`
- Create: `src/novel_forge/modules/runtime_proof/longform_campaign.py`
- Modify: `src/novel_forge/modules/runtime_proof/__init__.py`
- Test: `tests/unit/test_longform_narrative_campaign.py`

**Interfaces:**
- Consumes: canonical JSON and current Git/migration/provider identities.
- Produces: `LongformCampaignContract`, `load_campaign_contract(path)`, `contract_identity(contract)`, and deterministic 300-row chapter matrix validation.

- [ ] Write tests that reject mutable/missing thresholds, non-contiguous chapter rows, invalid obligation windows, future knowledge exposure, and hash drift.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_longform_narrative_campaign.py -v` and require the new tests to fail before implementation.
- [ ] Implement the minimal frozen contract loader, canonical hashing, schema validation, and checkpoint/probe indexes.
- [ ] Add the original ten-volume book contract with 300 deterministic chapter rows and no placeholders.
- [ ] Rerun the focused tests and require PASS.
- [ ] Commit the design, plan, contract, module, and tests.

### Task 2: Resumable canonical Campaign harness

**Files:**
- Create: `scripts/run_longform_narrative_campaign.py`
- Modify: `scripts/run_short_longform_runtime_proof.py`
- Test: `tests/unit/test_longform_narrative_campaign_runner.py`

**Interfaces:**
- Consumes: `LongformCampaignContract`, existing short-proof bootstrap helpers, Production Execution composition, Book/Chapter/Planning Authority, and PostgreSQL queries.
- Produces: `bootstrap`, `run --through-chapter N`, `evaluate --checkpoint N`, `export`, and append-only failure records; durable business state remains Authority-owned.

- [ ] Write tests for current-branch exact-HEAD admission, first-run bootstrap, resume without duplicate chapter, checkpoint bounds `30|100|300`, and failure classification.
- [ ] Run the new runner tests and require initial failure.
- [ ] Remove the obsolete fixed feature-branch restriction while preserving clean-worktree and exact-SHA checks.
- [ ] Implement idempotent bootstrap/resume, sequential plan generation, existing scheduler ticks, cadence followups, and Authority-backed exports.
- [ ] Rerun focused runner, short-proof, architecture, and head-integrity tests.
- [ ] Commit the harness change.

### Task 3: Requalification and real-provider vertical proof

**Files:**
- Create: `proof-campaigns/longform-narrative-v1/evidence/engineering-qualification.json`
- Create: `proof-campaigns/longform-narrative-v1/reports/engineering-qualification.md`

**Interfaces:**
- Consumes: final Task 2 SHA and all qualification commands.
- Produces: Qualified SHA and an exact-HEAD real Codex one-chapter/three-chapter vertical proof.

- [ ] Run `make validate`, `make test`, `make authority-postgres-test`, Skill drift, Capability Pack tests, Admin lint/build, `uv build`, production image build, Compose fault smoke, and query-plan release serially.
- [ ] Run the Codex CLI vertical proof with a fresh project/root and require real Provider calls, receipts, measured usage/cost semantics, and accepted Chapter outputs.
- [ ] Classify and repair only observed failures; retain every failed root and rerun on a new root when immutable storage requires it.
- [ ] Freeze the Qualified SHA and real-provider status in the engineering report.

### Task 4: 30/100/300 cumulative proof

**Files:**
- Create: `proof-campaigns/longform-narrative-v1/novel/chapters/chapter_001.md` through `chapter_300.md`
- Create: `proof-campaigns/longform-narrative-v1/novel/the-ledger-under-rain.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/30-chapter-validation.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/100-chapter-validation.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/300-chapter-validation.md`

**Interfaces:**
- Consumes: one Campaign project/book/run and frozen contract.
- Produces: cumulative chapter text and checkpoint evaluations with failure/fix/rerun lineage.

- [ ] Run through Chapter 30 and evaluate every frozen correctness/context/recovery threshold.
- [ ] On failure, classify, preserve evidence, make the smallest root-cause repair, requalify a new SHA, and rerun only affected unaccepted work.
- [ ] Continue the same Book through Chapter 100 and repeat checkpoint evaluation/failure handling.
- [ ] Continue the same Book through Chapter 300 and repeat checkpoint evaluation/failure handling.
- [ ] Export 300 immutable accepted chapter versions and merge them in chapter order.

### Task 5: Controlled experiments and reader calibration

**Files:**
- Create: `proof-campaigns/longform-narrative-v1/reports/mkaos-ab.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/quality-ab.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/replan-ab.md`
- Create: `proof-campaigns/longform-narrative-v1/reports/real-reader-calibration.md`

**Interfaces:**
- Consumes: frozen checkpoints and matched Provider/model/sampling/context settings.
- Produces: paired sample rows, effect sizes, variance/uncertainty, and a calibrated or BLOCKED human-reader verdict.

- [ ] Run multiple MKAOS ON/OFF pairs with selected-versus-consumed lineage.
- [ ] Run same-draft Quality correction pairs and record correctness/quality regressions as well as gains.
- [ ] Run original-plan versus approved-Replan future segments from a real drift checkpoint.
- [ ] Search current Authority/input assets for real human outcomes; if absent, freeze the contract/builder/split/evaluation protocol and report BLOCKED.

### Task 6: Final regression and evidence freeze

**Files:**
- Create: `proof-campaigns/longform-narrative-v1/manifest.json`
- Create: `proof-campaigns/longform-narrative-v1/reports/final-validation-report.md`
- Create: `proof-campaigns/longform-narrative-v1/evidence/final-measurements.json`

**Interfaces:**
- Consumes: final code SHA, all runtime evidence, chapters, experiments, and reader report.
- Produces: content-addressed Evidence Freeze and the required fail-closed verdict matrix.

- [ ] Rerun complete Engineering Qualification on the final SHA.
- [ ] Verify every passing report references that SHA and migration 0086 or a forward migration introduced by an observed fix.
- [ ] Hash all contract, chapter, report, measurement, trace/receipt reference, failure, and experiment exports into the manifest.
- [ ] Write the final verdict with explicit engineering/provider/30/100/300/A-B/reader/single-book/multibook/production claims.
- [ ] Commit, push the Campaign branch, and open a Draft PR only after evidence and Git state agree.
