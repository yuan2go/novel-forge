# Real Provider Single-Chapter Readiness

Date: 2026-07-18.

## Verdict

`READY_FOR_REAL_PROVIDER_SINGLE_CHAPTER`

This verdict means the runtime can safely start a bounded, operator-observed single
chapter proof. It does not mean the chapter will pass semantic Quality, does not
permit external publishing, and does not establish production or long-form proof.

## Entry checklist

- Configure trusted local operator and worker Principals with explicit project scope.
- Configure full 40-character `NOVEL_FORGE_COMMIT_SHA` and build identity.
- Configure explicit Draft/Review/Revision/Canon-extraction and grouped Quality
  Provider/model routes.
- Set Provider request timeout, query/cancel reconciliation capability, stable-key
  behavior, and per-call/project/chapter/daily budget caps.
- Prepare eligible ChapterPlan, StylePolicy, QualityProfile, PlatformProfile,
  checklist, governed Context inputs, and chapter-appropriate prior Snapshots.
- Keep external platform publishing disabled.
- Run exactly one chapter through asynchronous API/worker, observe UNKNOWN/manual
  reconciliation and Canon gates if raised, and capture cost/model logs.
- Expect semantic Quality dimensions without calibrated current-Revision evidence to
  block at `INTERNAL_REVIEW_RELEASE`; do not waive non-waivable gates.

## Low-cost verification completed

- Unit: 916 passed.
- PostgreSQL Authority suite: 96 passed; additional Content recovery/budget suite: 12 passed.
- Architecture: 5 passed.
- API/permission focused tests and `compileall`: passed.
- Catalog: 124 Definitions (`65 candidate`, `17 mapped`, `42 integration_proven`,
  `0 production_verified`).

## Deferred proof

Real Provider, 3/10/30/100 chapters, multi-book concurrency, real network connectors,
and external publishing were not run. Therefore `real_provider_proven=false`,
`longform_proven=false`, and `production_verified=false`.
