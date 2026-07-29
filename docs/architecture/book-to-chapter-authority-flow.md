# Book-to-Chapter Authority Flow

## Ownership

`PostgresBookAuthority` owns book-level scheduling checkpoints.
`ChapterAuthorityApplication` owns Chapter Operations, Saga, Attempts, leases,
fences, ExternalEffects, outputs, and failure state.

```text
Book start Command
→ book.production.coordinate root Operation + Saga
→ durable authority_book_production checkpoint
→ SubmitBookChapterCommand
→ persist SUBMITTING request
→ ChapterAuthorityCommandPort.submit
→ Chapter root Operation + Chapter Saga
→ query Chapter Authority terminal state
→ Reader Outcome child Operation
→ optional Long-form Recap child Operation
→ Book checkpoint / root Saga completion
```

There is no second Chapter state machine in Book Authority. The Book tables hold
only `chapter_request_id`, Chapter root Operation/Saga references, a status
reference, and book decisions.

## Frozen inputs and idempotency

The Book root freezes existing PostgreSQL `AssetVersion` references for
BookDesign, BookPlan, VolumePlan, ArcPlan, Character State, Foreshadowing State,
Quality Trend, Reward Ledger, and Promise Ledger. Missing, duplicate, or
`*:current` references fail admission.

Chapter submission identity is derived from:

```text
book_id
book_plan_version
chapter_number
chapter_plan_version
production_profile_version
```

A repeat with the same identity returns the existing Chapter Operation. A new
ChapterPlan version creates a new auditable request.

## Failure and recovery

The request is committed in `SUBMITTING` before Chapter admission. If admission
succeeds and the response is lost, `recover_chapter_submission` replays the same
stable command; Chapter Command Kernel idempotency returns the existing
Operation. `reconcile_chapter` queries the Chapter projection and maps only its
status reference into the Book checkpoint.

Retryable, terminal, cancelled, and running Chapter states remain Chapter-owned.
Unknown work is queried/reconciled; it is not hidden by regenerating the chapter.
The governed Scheduler advances one durable transition per tick.

Request creation and the `CHAPTER_SUBMITTED` Book slot reservation are one
transaction. The reservation requires `state=READY` and
`chapter_number=current_chapter+1`, so concurrent or out-of-order submissions
fail before reaching Chapter Authority.

Pause/resume use the existing Command Kernel Saga Gate. The durable Book
checkpoint and root Operation/Saga move together; no process-local pause flag is
authoritative.

The older `book.production.run` fixture protocol is retained for tests only and
fails closed in production-like environments.
