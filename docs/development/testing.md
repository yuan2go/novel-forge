# Testing and evidence

## Canonical P0 backend qualification

```bash
python -m pip install -e '.[test,industrial]'
test -z "$(git status --porcelain --untracked-files=all)"
P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-p0 \
  make p0-backend-qualification
```

This Make target is the sole authoritative backend entry locally and in
`.github/workflows/core-os-ci.yml`. It runs the manifest/static gates, the full
architecture/unit/acceptance collections, the full PostgreSQL integration
collection, fresh migration and migration-head checks, representative query
plans, and the scripted Compose enqueue/recovery/restart/subsequent-work proof.
It does not invoke npm and the CI job has no dependency on the Admin UI.

The four pytest roots are complete collections. PostgreSQL qualification is not
a curated filename list: every collected node under `tests/integration` must be
present in the machine collection report, and any unclassified or excluded
PostgreSQL test fails closed. Test counts, duration, failures, errors, and skips
come from JUnit XML; human stdout is not Authority evidence.

Migration expectation comes from the canonical migration manifest. The runner
does not encode the current migration ID as a permanent contract.

The repository does not currently configure mypy, pyright, or another
whole-Python static type checker. Python compilation and Ruff must not be
described as a full static type proof. Current Admin sources are deferred, so no
UI type-check or build result participates in this backend gate.

## Qualification identity and reproducibility

Every run binds its clean source SHA/tree, UUID resource identity, canonical
manifest hashes, Python identity, and resolved dependency digest. Git SHA alone
does not reproduce the dependency environment while version ranges remain
unlocked. A PASS is valid only for the resolved snapshot recorded in that
report; if dependency drift is observed, introduce a bounded constraints freeze
before comparing runs rather than claiming SHA-only reproducibility.

Qualification uses Docker-assigned loopback ports plus distinct project,
database, network, volume, and artifact identities. Cleanup requires the exact
captured resource set and run/project labels. An ownership mismatch is a failed
gate requiring receipt inspection, never permission for unscoped cleanup.

The runner never reads `.env` for a database DSN and refuses real-provider
credentials. Focused tests and `make p0-backend-static` remain useful iteration
tools, but no partial or historical result can replace a clean final-SHA run.

## Test placement

- Unit tests cover pure invariants, schema validation, and deterministic policy.
- Architecture tests cover import direction, runtime reachability, retired paths, and composition ownership.
- Acceptance tests exercise a user-visible vertical contract with controlled fixtures.
- Integration tests exercise PostgreSQL, MinIO, providers, or other real dependencies and must name the dependency.

A failing test may be removed only when its production path is proven retired and the obsolete implementation is removed with it. Never weaken an assertion or substitute a fixture to make a production gate green.

## Proof interpretation

| Test result | Permitted claim |
|---|---|
| Pure/unit green | behavior is `implemented` for covered inputs |
| Architecture green | forbidden dependency/reachability patterns were not found |
| Fixture acceptance green | bounded path is `fixture-proven` |
| Non-skippable PostgreSQL green | covered database behavior is `integration-proven` |
| Real provider receipt and assertions | covered call is `real-provider-proven` |
| Operated deployment evidence | named scenario may be `production-verified` |

Do not promote claims across rows. Missing Docker or credentials is `ENVIRONMENT_BLOCKED`, not a pass or product failure.

## Scope and evidence ceilings

The current `web/admin` pages are an unsupported snapshot awaiting a dedicated
whole-UI reconstruction. They are not an Authority client and remain
`DEFERRED / NOT_RUN_BY_SCOPE`; backend qualification does not create UI or
product-experience evidence.

P0 backend qualification also preserves these ceilings exactly:

| Evidence class | P0 status |
|---|---|
| `REAL_PROVIDER` | `NOT_RUN_BY_SCOPE` |
| `HISTORICAL_ORPHAN_MUTATION` | `NOT_RUN_BY_SCOPE` |
| `EIGHT_CHAPTER` | `NOT_RUN_BY_SCOPE` |
| `HUMAN_REVIEW` | `NOT_RUN_BY_SCOPE` |
| `LONGFORM` | `NOT_PROVEN` |
| `MULTIBOOK` | `NOT_PROVEN` |
| `PRODUCTION` | `NOT_PROVEN` |

Fixture execution, PostgreSQL integration, or Compose recovery must not upgrade
any of these claims implicitly.

## Repository operational Exit Gate

Repository branch governance is `OPEN / NOT_CLOSED` until every step below has
completed in order:

1. Freeze the implementation final SHA.
2. Run clean zero-state qualification from that exact SHA.
3. Push that exact SHA.
4. Observe the remote `P0 Backend Qualification` check green for that SHA.
5. Enable `P0 Backend Qualification` as a required check and enable branch governance.
6. Verify the repository actually enforces both settings.

Code completion or local PASS does not close this operational gate. Until steps
5 and 6 are verified, do not claim merge governance is closed.

## Quality Qualification gates

Quality proof adds an orthogonal evidence matrix; a green engineering gate does
not imply a literary result:

| Evidence | Permitted interpretation |
|---|---|
| L1 accepted-history checks | covered hard-correctness invariants at exact accepted boundaries |
| Automated L2 Judge | model-attributable editorial evidence with recorded dependence; never human truth |
| Reader Outcome v3 | Reader Proxy/advisory trend evidence; never Canon or real-reader proof |
| Scripted 4+4 campaign | bounded protocol, wiring, PostgreSQL and recovery proof |
| Real-provider 4+4 campaign | bounded Provider/runtime evidence for the frozen route and eight Chapters |
| One valid blinded reviewer | `HUMAN_EVIDENCE_LIMITED` |
| Two valid blinded reviewers | bounded human preference evidence; not statistical calibration |
| No completed human review | `WAITING_HUMAN_EVIDENCE / NOT_PROVEN` |

Arc and Volume-slice tests must assert causal/longitudinal semantics rather than
averaging Chapter scores. Severe L1 failures must remain visible through final
decision. Judge-human diagnostics with an insufficient sample remain
`UNCALIBRATED / BOUNDED_EVIDENCE`; tests must not lower thresholds to make them
estimable.

The real-provider evidence gate also rejects fixture ModelCallLogs,
Provider/model route drift, unclassified calls, missing measured usage,
successful effects without receipts, unresolved/breached budgets, missing or
drifted Pack snapshots, absent Prompt/Skill/policy hashes, and a non-dedicated
Project/BookRun. Provider ceilings are asserted after each Chapter and
follow-up tick, not only after completion.

The focused canonical suites are:

```bash
PYTHONPATH=src pytest -q \
  tests/unit/test_quality_qualification_domain.py \
  tests/unit/test_quality_longitudinal_evidence.py \
  tests/unit/test_quality_calibration_v2.py \
  tests/unit/test_reader_calibration.py \
  tests/unit/test_bounded_quality_campaign.py \
  tests/unit/test_bounded_quality_campaign_cli.py

NOVEL_FORGE_DATABASE_URL="$NOVEL_FORGE_DATABASE_URL" PYTHONPATH=src pytest -q \
  tests/integration/test_quality_qualification_postgres.py \
  tests/integration/test_reader_calibration_postgres.py \
  tests/integration/test_book_followup_authority_postgres.py \
  tests/integration/test_bounded_quality_campaign_postgres.py
```

The campaign procedure and evidence interpretation are in
[`../operations/quality-qualification.md`](../operations/quality-qualification.md).
