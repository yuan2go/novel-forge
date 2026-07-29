# P0 Unified Production Execution Plane Code-Fact Audit

Date: 2026-07-29

Baseline branch: `feat/v7-content-intelligence-and-longform-proof`

Baseline HEAD: `0e4c1f5825892176d3c8ff97c04824e45abc6743`

Baseline worktree: clean

## Audit method

This audit follows real imports, constructors, command admission, handler registration,
repository calls, and tests. Documentation is supporting context only.

## Current call-path facts

| Module | Current entry | Current mutation/effect boundary | Command Kernel | Production status | Finding |
| --- | --- | --- | --- | --- | --- |
| Chapter production | `ChapterAuthorityApplication.admit` | PostgreSQL Authority repositories, shared attempt runtime, external effects | Yes | production architecture | Existing governed path is the primary reuse target. |
| Legacy chapter bus | `start_chapter_production`, `run_chapter_production_sequence` | `LocalStorage` | No | production blocked | Twelve compatibility steps remain useful for parity enumeration and fixtures only. |
| Book authority | `admit_book_production` | PostgreSQL operations executed by fixture codecs | Partial | fixture proof only | `book.chapter.dispatch` fabricates an acceptance record; it does not submit a Chapter Authority command. |
| Reader outcome | judge capability/evidence helpers | no Reader Outcome authority asset or projection | No formal business operation | not integrated | A production-execution capability exists, but no command, operation, handler, asset lineage, or recovery flow exists. |
| Long-form recap | `run_longform_recap` | direct `LocalStorage` writes to recap, canon, character, plan, foreshadowing, issue, and task records | No | legacy/development | The scheduler can invoke the legacy service directly. This is a production bypass unless fail-closed. |
| Content authority | `ContentAuthorityApplication.admit` | PostgreSQL Operation/Attempt and shared authority handler runtime | Yes | production architecture | This is the closest reusable operation shape for Reader Outcome and Recap. |
| Provider execution | `ProductionExecutionGatewayExternalEffectAdapter` | ExternalEffect plan/dispatch/receipt, budget and model ledgers | Yes | production architecture, provider proof varies | Reader Outcome needs a routed stage; Recap can initially be deterministic and remain governed. |
| API | `create_authority_app` | command applications | Yes for authority app | PostgreSQL-only | Legacy/local app remains a distinct development compatibility surface. |
| CLI | authority CLI selected by storage-authority policy | Chapter Authority application | Yes in production policy | production fail-closed | New parity and book authority commands must retain this boundary. |

## Legacy Chapter Bus parity inventory

The source of truth is `CHAPTER_PRODUCTION_STEPS` in
`src/novel_forge/modules/chapter_production_bus/service.py`:

1. `outline_checkpoint`
2. `chapter_plan`
3. `stability_preflight`
4. `context_bundle`
5. `draft_v0`
6. `review`
7. `revision_plan`
8. `final_draft`
9. `quality_repair`
10. `canon_longform_update`
11. `export_package`
12. `next_chapter_plan`

The current Chapter Authority operation graph has finer-grained plan, context, draft,
review/revision, canon, quality, publish, export, and final-release operations. Parity
must therefore be an explicit many-to-many business mapping, not a name comparison.

## Direct-write classification

| Location | Classification | Required treatment |
| --- | --- | --- |
| Legacy chapter bus `LocalStorage` writes | explicit compatibility/fixture path | keep production runtime guard and include in architecture tests |
| Long-form recap service writes | illegal production bypass | add production guard; replace production scheduler path with governed operation |
| Authority asset handler runtime | production authority write | retain; it validates current attempt fence and atomically creates output lineage |
| Projection repositories/views | rebuildable read model | expose query-only use to callers |
| tests and fixture builders | pure test fixture | retain with explicit non-authoritative metadata |
| import/migration tools | controlled tooling | outside live production request path; keep separately classified |

## Reuse decisions

- Reuse Command Kernel definitions, PostgreSQL admission, Operation/Saga/Attempt,
  lease/fence, retry/cancel, ExternalEffect, AssetVersion, outbox, and projection
  mechanisms.
- Reuse `execute_authority_handler` for atomic schema-validated output
  materialization and evidence.
- Reuse the Chapter Authority command application and queries; Book Authority
  stores only request and status references.
- Reuse the model ExternalEffect adapter and production execution gateway for
  Reader Outcome.
- Do not add another attempt table, scheduler protocol, provider adapter, message
  system, or execution state machine.

## Required corrections

1. Add a typed, machine-validated authority parity manifest for all twelve legacy
   steps.
2. Make legacy LocalStorage surfaces fail closed in production-like environments.
3. Replace fixture-only book chapter dispatch with a persistent command-port
   integration to Chapter Authority.
4. Add `reader_outcome.evaluate` as a formal governed operation with effect and
   versioned output assets.
5. Add `longform.recap` as a formal governed operation that emits observation and
   proposal assets but cannot mutate plans.
6. Persist book scheduling/checkpoint references and recover exclusively from
   PostgreSQL Authority state.
7. Prove the full flow with fake provider evidence, without upgrading it to real
   provider or production proof.

## Baseline evidence

- Remote branch and local branch were equal at
  `0e4c1f5825892176d3c8ff97c04824e45abc6743`.
- `git pull --ff-only` reported “Already up to date.”
- The worktree was clean.
- The full baseline test command was `make test`; its final result is recorded in
  the implementation report after completion.
