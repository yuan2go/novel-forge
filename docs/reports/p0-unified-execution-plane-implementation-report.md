# P0 Unified Production Execution Plane Implementation Report

> Date: 2026-07-29
> Branch: `feat/v7-content-intelligence-and-longform-proof`
> Initial HEAD: `0e4c1f5825892176d3c8ff97c04824e45abc6743`
> Evidence grade: L4 automated PostgreSQL/scripted-Provider integration
> Real Provider: not run
> Sustained production: not verified

Worktree delivery: 55 files (29 new, 26 modified), one forward-only migration,
20 new test methods, no deleted files, no commits created.

## 1. Executive judgment

Before this work, Chapter Authority already had the strongest production path,
but business integration was incomplete:

- Legacy Chapter parity was implicit;
- Book Authority used fixture dispatch rather than a Chapter Authority command;
- Reader Outcome was a capability/service seam, not a business Operation;
- Long-form Recap could synchronously write LocalStorage and planning/state assets;
- LocalStorage did not identify or enforce its non-authoritative production role.

The implementation now provides one governed vertical path:

```text
PostgresBookAuthority root Operation / Saga
→ transactional Chapter request reservation
→ ChapterAuthorityCommandPort
→ Chapter Authority Saga / Attempts / PEP
→ Final Draft + Canon outputs
→ reader_outcome.evaluate / ExternalEffect / PEP
→ longform.recap
→ Book checkpoint / root Saga terminal
```

No second Attempt, lease, fence, effect, receipt, or execution-state authority was
introduced.

Implementation status:

```text
UNIFIED_PRODUCTION_EXECUTION_PLANE_BUSINESS_INTEGRATION_COMPLETE
```

This status means the P0 business slice and production fail-closed boundaries are
implemented and automatically proven. It does not mean real Provider, full
BookDesign autonomy, full long-novel completion, or sustained production is
verified.

## 2. Authority parity

Source: `config/authority/authority-parity-manifest.json`.

| Capability | Legacy | Authority Operation | Handler | Automated evidence | Status |
| --- | --- | --- | --- | --- | --- |
| Planning checkpoint | `outline_checkpoint` | `chapter.slice.run`, `chapter.plan.materialize` | root, plan | PG fixture | TESTED_WITH_FAKE |
| Chapter plan | `chapter_plan` | `chapter.plan.materialize` | plan | PG fixture | TESTED_WITH_FAKE |
| Stability preflight | `stability_preflight` | plan/context dependency gate | plan, context | PG fixture | TESTED_WITH_FAKE |
| Context | `context_bundle` | `chapter.context.build` | context | PG fixture | TESTED_WITH_FAKE |
| Draft | `draft_v0` | `chapter.draft.generate` | draft | PEP/ExternalEffect fixture | TESTED_WITH_FAKE |
| Review | `review` | `chapter.review.evaluate` | review | PEP/ExternalEffect fixture | TESTED_WITH_FAKE |
| Revision plan/apply | `revision_plan` | review + revision | review, revision | PEP/ExternalEffect fixture | TESTED_WITH_FAKE |
| Final draft | `final_draft` | revision + rereview | revision, rereview | PG fixture | TESTED_WITH_FAKE |
| Quality repair | `quality_repair` | five quality groups + aggregate | quality handlers | PG fixture | TESTED_WITH_FAKE |
| Canon/long-form update | `canon_longform_update` | Canon extract/commit + `longform.recap` | Canon, Recap | PG fixture | TESTED_WITH_FAKE |
| Export | `export_package` | export render/verify/final release | export handlers | PG fixture | TESTED_WITH_FAKE |
| Next plan | `next_chapter_plan` | publish/release terminal + Book checkpoint | publish, Book coordinator | PG fixture | TESTED_WITH_FAKE |

Final machine report:

```text
Legacy capabilities: 12
Fully mapped: 12
Production enabled: 12
Direct-write bypasses in governed boundary: 0
Missing handlers: 0
Missing output contracts: 0
Authority parity: PASS
```

`Production enabled` is not `PRODUCTION_PROVEN`; every manifest record remains
truthfully graded `TESTED_WITH_FAKE`.

## 3. Bypass governance

### Replaced or blocked

- Legacy Chapter entrypoints fail before reads/writes in production-like
  environments.
- Legacy Long-form Recap fails before LocalStorage mutation.
- The older fixture Book Authority admission and Scheduler fail closed in
  production-like environments.
- `LocalStorage.write_json` and `write_asset` fail with
  `PRODUCTION_DIRECT_WRITE_FORBIDDEN: AUTHORITY_COMMAND_REQUIRED`.
- The production Authority API mounts PostgreSQL command/query routers, including
  Book start, Chapter submission, reconcile, tick, pause, resume, and query.

### Legally retained

The older local product API, CLI, workflows, fixtures, import/export tools, and
rebuildable projections still reference LocalStorage for development and test
compatibility. They cannot write when `NOVEL_FORGE_ENVIRONMENT` is production,
staging, or production-like. Their mere presence is not production authority.

The machine parity bypass count deliberately scans the governed Chapter/Book
boundary. The repository still contains many legacy/development LocalStorage
call sites; their migration is not misreported as deletion.

## 4. Four-module result

### Full-book/volume/arc/chapter chain

Book root commands freeze real PostgreSQL AssetVersions for BookDesign, BookPlan,
VolumePlan, ArcPlan, Character State, Foreshadowing State, Quality Trend, Reward
Ledger, and Promise Ledger. ChapterPlan and context assets are resolved through
PostgreSQL before Chapter command admission.

The P0 slice coordinates one sequential Chapter at a time. Full autonomous
BookDesign/Volume/Arc generation and replan are still later capability depth.

### Unified execution plane

Reader model work and all Chapter uncertain stages use the same
`ProductionExecutionGatewayExternalEffectAdapter`, route snapshot, qualified
backend, effect, receipt, usage/cost ledger, Attempt, lease, and fence. Recap is
deterministic, so it correctly creates no fake Provider effect.

### Reader Outcome Judge

Formal definition: `reader_outcome.evaluate@1.0.0`.

Outputs:

- `reader_outcome_report`;
- `reader_state_transition`;
- `reader_issue_set`;
- `authority_reader_outcome_projection`.

Its multi-dimensional gate is explainable and cannot mutate prose.

### Book Design Authority and long-form loop

Formal definition: `longform.recap@1.0.0`.

Outputs:

- `longform_recap`;
- `longform_deviation_report`;
- `plan_adjustment_proposal`;
- optional `replan_request`;
- `authority_longform_recap_projection`.

Recap cannot mutate a plan. Blocking deviations move the Book checkpoint to
`REPLAN_REQUIRED`; a later Book Design Authority decision/replan package must
perform the plan change.

## 5. Persistence and concurrency

Migration `20260729_0034_unified_business_authority` adds:

- `authority_book_production`;
- `authority_book_chapter_request`;
- `authority_book_followup_operation`;
- Reader Outcome and Long-form Recap projection views;
- status, uniqueness, foreign-key, idempotency, JSON shape, and range checks;
- query and foreign-key indexes.

Chapter request creation and Book slot reservation are atomic. The update requires
`READY` and `current_chapter = requested_chapter - 1`; concurrent or out-of-order
requests fail before Chapter dispatch.

The migration is forward-only. Automated downgrade does not drop Authority audit
tables. Operational rollback disables the new definitions/routes and preserves
state, followed by a forward repair.

## 6. Recovery and idempotency

- Stable Book and Chapter idempotency keys replay original Operations.
- A request is stored as `SUBMITTING` before Chapter admission.
- Lost responses are recovered by replaying the same Chapter command.
- Book state is reconciled from Chapter Authority rather than regenerated.
- Repeated Reader Outcome admission creates one Attempt/effect/output.
- Shared stale-fence, lease takeover, retry/dead-letter, cancel, UNKNOWN effect,
  callback, receipt, and crash-recovery tests apply unchanged.
- Pause/resume use the existing Saga Gate and a durable Book checkpoint.
- Root Operation/Saga completion happens only after required follow-up children
  succeed.

## 7. Vertical proof

The PostgreSQL vertical test proves:

```text
Book start / frozen AssetVersions
→ pause / resume through Saga Gate
→ Chapter request + transactional slot reservation
→ Chapter Authority full fixture chain
→ Final Draft + Canon
→ Reader Outcome PEP ExternalEffect
→ Reader State / issue assets
→ cadence-triggered Long-form Recap
→ deviation + adjustment assets
→ Book root Operation and Saga SUCCEEDED
```

Additional assertions prove:

- duplicate Chapter submission reaches Chapter Authority once;
- Reader Outcome creates one Provider ExternalEffect;
- root/Reader/Recap freeze 9/4/11 AssetVersions respectively;
- a Chapter 2 request before Chapter 1 is rejected before dispatch;
- projection content is queryable after process-local objects are discarded.

## 8. Test evidence

Final evidence is recorded after the last source change:

| Command | Passed | Failed | Skipped | Duration |
| --- | ---: | ---: | ---: | ---: |
| `make postgres-authority-test` | 114 | 0 | 0 | 142.836s |
| focused Book/Reader/Recap PostgreSQL tests | 3 | 0 | 0 | 13.713s |
| focused API/architecture tests | 49 | 0 | 0 | 185.119s |
| `make test` Python | 1296 | 0 | 9 | 741.273s |
| `make test` Web | 11 | 0 | 1 | 106.342ms |
| `make lint` | compileall passed | 0 | 0 | <1s |
| `make validate` | validation passed | 0 | 0 | ~30s |
| `make authority-parity-check` | PASS | 0 | 0 | <1s |
| `git diff --check` | PASS | 0 | 0 | <1s |

The repository has no `scripts/check_docs_links.py`; no unavailable command is
reported as a successful docs-link check.

## 9. Evidence levels

| Capability | Level | Boundary |
| --- | --- | --- |
| Parity schema/validator | L4 | exact source-step and catalog tests |
| Production LocalStorage/Legacy guards | L4 | architecture + runtime tests |
| Book → Chapter command | L4 | PostgreSQL vertical fixture |
| Reader Outcome Operation | L4 | PEP/ExternalEffect PostgreSQL fixture |
| Long-form Recap Operation | L4 | PostgreSQL deterministic handler fixture |
| Pause/resume and sequential reservation | L4 | PostgreSQL vertical fixture |
| Real Provider | below L5 | not run |
| Real long-novel proof | below L5 | not run |
| Sustained production | below L6 | not verified |

## 10. Remaining gaps and P1

- Real Reader Outcome Provider calibration and paid-call proof are absent.
- The P0 Scheduler is a one-checkpoint tick exposed through the Authority API; a
  continuously supervised deployment loop still needs production operations
  evidence.
- Full BookDesign approval, Volume/Arc impact analysis, formal Adjustment
  decision, and Replan execution remain the next domain depth.
- The legacy development product surface still contains LocalStorage callers,
  although production writes are fail-closed.
- UI controls for the new Book Authority endpoints were not added.

The next work package should be:

```text
Book Design Authority Collaborative Vertical Slice
```

The execution semantics needed by that slice are now closed at L4; the next
highest-value gap is Domain Authority decision/replan depth, not another execution
framework.
