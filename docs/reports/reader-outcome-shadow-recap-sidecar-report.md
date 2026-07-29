# Reader Outcome Shadow and deterministic Recap Sidecar

Status: `implemented=true`, `handler_bound=true`,
`integration_proven=true`, `real_provider_proven=false`,
`longform_proven=false`, `production_verified=false`.

Reader Outcome and Long-form Recap are standalone Authority root Operations and
Sagas causally linked to an accepted Chapter. They do not become steps in the
Book Saga and do not change the Book cursor or Book production status.

Reader evidence is explicitly constrained to:

```text
mode=SHADOW
calibration_status=UNCALIBRATED
score_semantics=RAW_SCORE
publish_blocking=false
```

The report records the judge/profile target, reader segment, frozen input
manifest, RouteSnapshot, evidence spans, raw scores, ordinal band, OOD and
stability status, plus usage/cost receipt references. Unmeasured fields say
`NOT_MEASURED`/`NOT_EVALUATED`; no completion probability is emitted.

The deterministic Recap consumes accepted ChapterOutcome, StoryState and Canon
state plus the Reader Shadow output. It emits a recap, deviation report and
PlanAdjustmentProposal, with an optional ReplanRequest. The handler cannot
mutate an active plan or Canon.

Evidence:

- `tests.integration.test_book_followup_authority_postgres`
- `tests.integration.test_book_to_chapter_authority_vertical_postgres`
- Book is already `COMPLETED` while Reader and Recap remain independently
  schedulable/recoverable;
- the Recap frozen input snapshot contains the accepted ChapterOutcome;
- cadence idempotency is enforced by the unique
  `(chapter_request_id, followup_type)` constraint.
