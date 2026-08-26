# Testing and evidence

## Local gates

```bash
make validate
make authority-test
npm --prefix web/admin run lint
npm --prefix web/admin test
make authority-compose-config-check
git diff --check
```

These cover Python compilation, focused zero-diagnostic Ruff, repository Ruff debt ratchet, architecture manifests, architecture fitness, Authority-only composition, HEAD integrity, unit/architecture/acceptance suites, TypeScript checking, web route/component tests, and Compose parsing.

The repository does not currently configure mypy, pyright, or another whole-Python static type checker. Python compilation and Ruff must not be described as a full static type proof. The admin console's `lint` script runs `tsc --noEmit`.

## PostgreSQL gates

```bash
make postgres-authority-test-up
make authority-postgres-test
make authority-query-plan-release
make postgres-authority-test-down
```

The PostgreSQL runner is non-skippable and validates the full migration chain in a temporary database before integration tests. It is the evidence boundary for transaction, constraint, lease/fence, migration, query, and recovery behavior that memory fixtures cannot prove.

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
