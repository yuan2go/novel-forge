# Content Authority Runtime Convergence Implementation Plan

Date: 2026-07-18  
Design: `docs/superpowers/specs/2026-07-18-content-authority-runtime-convergence-design.md`

## 1. Protect the baseline

- Run the focused existing chapter/content/context/review/canon/quality tests.
- Add architecture tests that demonstrate the current missing codec/runtime boundary.
- Preserve unrelated local work and perform `git diff --check` before every commit.

## 2. Extract the generic authority handler envelope

- Add generic input, request, output, registration, and execution result contracts.
- Generalize frozen input loading and output materialization in the existing authority
  repository rather than adding parallel tables.
- Move the chapter runtime's fence/load/materialize/event flow behind the generic
  executor and keep the chapter API compatible.
- Test stale fence, project isolation, stale/revoked input, replay, pre/post-output
  crash boundaries, lineage, audit, outbox, and incomplete Completion.

## 3. Add Content Authority codecs and application runtime

- Create explicit codecs for all 22 definitions.
- Register codecs and handlers together and assert catalog completeness.
- Bind frozen inputs to the existing storage-free domain cores without `**payload`.
- Enable and promote batches only after their PostgreSQL proof suite passes.

## 4. Materialize governed context views

- Add Context Segment and Stage Context View domain contracts.
- Enforce stage profiles and allowed-use isolation.
- Derive actual safe content and a content-sensitive digest.
- Propagate root command context fields.
- Make Source eligibility terminal by severity and add combination tests.

## 5. Add authoritative re-review

- Change revision transitions to `RESOLUTION_CLAIMED`.
- Add `chapter.revision.review`, its codec/handler/definition, independent report, issue
  lineage, regression detection, and `RevisionQualityDelta`.
- Require re-review evidence in Quality and Publish Gate.

## 6. Add stateful canon extraction and reduction

- Freeze explicit historical state inputs and first-chapter baselines.
- Extract canon/state candidates independently of the revision provider response.
- Detect fact, temporal, identity, relationship, world-rule, power, foreshadow, and
  promise conflicts.
- Emit append-only project-scoped snapshots and prove rebuild/rollback behavior.

## 7. Aggregate quality evidence

- Adapt existing quality reports into `ChapterQualityAggregate` dimensions.
- Replace the fixed score with evidence-weighted calibrated results and honest
  `UNCALIBRATED` statuses.
- Make Publish Gate fail closed on missing/revoked/stale blocking evidence and require
  real checklist/approval and blob-verification assets.

## 8. Converge the Chapter Production Bus

- Introduce authority command/query adapters and a rebuildable run projection.
- Block LocalStorage first writes for migrated asset types in production.
- Retain explicit development-only compatibility reads/exports with warnings and
  counters.

## 9. Close evidence and documentation

- Run focused unit, architecture, schema, and PostgreSQL suites only.
- Regenerate the OperationDefinition catalog and authority coverage evidence against
  the final source HEAD.
- Update current-state and convergence/migration reports with exact maturity labels,
  test commands, remaining LocalStorage paths, and commit SHAs.
- Do not claim real-provider, production, or long-form proof.
