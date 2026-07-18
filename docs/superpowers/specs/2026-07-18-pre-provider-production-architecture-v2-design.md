# Pre-Provider Production Architecture V2 Design

## Status and scope

This design promotes the local PostgreSQL architecture from
`FUNCTIONALLY_READY_FOR_PROVIDER_VALIDATION` to
`PRE_PROVIDER_PRODUCTION_ARCHITECTURE_COMPLETE`. It never invokes a real Provider,
generates a real chapter, or proves long-form/multi-book production quality.

## Chosen architecture

Four deep modules extend the existing Command Kernel:

1. **Provider control module** — a registry freezes qualified v2 routes; an injected
   OpenAI-compatible transport proves timeout/idempotency/query/cancel/receipt behavior
   without network. Durable callbacks enter one Authority Operation and reconcile the
   existing ExternalEffect/Attempt/Budget chain.
2. **Production semantics module** — ChapterPlan Contract v3 owns the only field
   registry and profile-driven qualification. Quality Context v2 owns multi-entity
   state selection, deterministic token budgeting, and coverage evidence. Calibration
   uses ordinary Operation/AssetVersion/Qualification/Audit/Outbox primitives.
3. **Continuity governance module** — typed empty snapshots require an Authority
   producer; Canon re-extraction freezes a policy, detects repeated digests/no progress,
   caps generations/cost/deadline, and records generation steps in the existing Saga
   timeline.
4. **Book orchestration module** — `book.production.run` is a root Operation/Saga whose
   child nodes are existing Chapter root Operations and deterministic recap/plan-
   adjustment Operations. It adds no parallel task runtime and never uses the legacy
   Chapter Bus.

The catalog retains historical Definitions and adds supersession metadata. A single
Creative candidate generator proves the Generator seam; validators remain labelled
Validator/Evaluator rather than being described as generators.

## Data and authority decisions

- Migration 0030: durable provider callback receipts/attempts and worker-health
  projection.
- Migration 0031: no parallel calibration tables; Authority Assets remain canonical,
  while a dataset membership table enforces project/dataset/sample uniqueness.
- Migration 0032: trusted typed-empty producer binding plus Canon generation policy,
  digest/progress/cost/deadline fields and generation timeline steps.
- Migration 0033: Book-to-Chapter Authority bindings and recap schedule projection.
- All output content is append-only AssetVersion data. Projection rows never satisfy
  Completion.

## Failure semantics

- Validation/production route qualification rejects fixture and legacy adapters.
- Callback signature failure, message hash conflict, unknown request identity, or
  cross-provider spoof cannot mutate ExternalEffect state.
- Context critical-fact overflow fails closed; non-critical omissions become a
  versioned coverage report.
- Calibration promotion requires a policy-passing report and explicit Authority
  promotion Operation.
- Empty-state initialization refuses existing state or incomplete prior reduction.
- Canon no-progress/cap/budget/deadline enters operator waiting, never loops silently.
- Book skip is forbidden; pause/cancel/budget/no-progress are durable root states.

## Test strategy

Unit contracts precede implementation. PostgreSQL tests cover callback replay and
concurrency, calibration promotion/revoke, typed-empty creation, Canon generation
governance, Book recovery/cadence, project isolation, and migrations. Architecture
tests forbid LocalStorage, uncontrolled Provider routes, non-Authority callbacks,
untrusted empty states, and legacy Book dispatch. Hosted CI remains credential-free.

## Honest maturity

The highest possible state is fixture/mock `integration_proven`. The following remain
false: `real_provider_proven`, `longform_proven`, `production_verified`,
`multi_book_proven`, and `external_publish_proven`.
