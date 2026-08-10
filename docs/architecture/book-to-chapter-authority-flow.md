# Book-to-Chapter Authority Flow

## Composition root

`build_book_production_composition` constructs the only production Book graph,
`BookProductionComposition`. Authority API routes and the Book Worker both use
this builder. The composition contains the existing `PostgresBookAuthority`,
`StoryPlanningGenerationApplication`, `PostgresChapterGroupAuthority`,
`ProductionPreparationService`, `BookFollowupAuthorityApplication`,
`PostgresPlanChangeAuthority`, `BookProductionInputResolver`,
`BookReplanCoordinator`, and `PostgresBookProductionSupervisor`.

Composition is mandatory: the resolved-input API path has no runtime `getattr`
fallback, and startup fails closed when a required dependency cannot be built.

## Ownership

`PostgresBookAuthority` owns book-level scheduling checkpoints.
`ChapterAuthorityApplication` owns Chapter Operations, Saga, Attempts, leases,
fences, ExternalEffects, outputs, and failure state.

```text
Resolved Book admission
→ Story Planning candidate, approval/activation and resolved input snapshot
→ book.production.coordinate root Operation + Saga
→ durable authority_book_production checkpoint
→ ChapterGroup and ChapterPlan
→ SubmitBookChapterCommand
→ persist SUBMITTING request
→ ChapterAuthorityCommandPort.submit
→ Chapter root Operation + Chapter Saga
→ query Chapter Authority terminal state
→ Narrative Checkpoint and Ending Reachability report
→ Reader Outcome child Operation
→ cadence Long-form Recap, or forced Recap for a blocking checkpoint finding
→ no-replan next chapter, or explicit Replan approval flow
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

## Replan approval boundary

When followup evidence requires Replan, the Worker invokes the existing
`BookReplanCoordinator` to create one replacement Planning candidate and one
PlanChange proposal. It then stops at durable `REPLAN_APPROVAL_PENDING`.
Repeated ticks and process restarts return the existing candidate/proposal.

Only a principal holding the distinct `book.authority.approve_replan`
permission may use the formal Authority endpoint to approve the proposal:

```text
POST /product/production/book-authority/runs/{book_run_id}/replans/{replan_id}/approve
```

The Book Worker principal deliberately lacks that permission. The command also
requires authority type/version and evidence. The Worker never supplies
approval and no fixture or low-risk policy bypasses it. After approval, the
same composition activates PlanChange,
supersedes the obsolete inactive ChapterGroup when safe, resolves a new Book
input snapshot, resumes the Book, and continues with the next chapter.

Request creation and the `CHAPTER_SUBMITTED` Book slot reservation are one
transaction. The reservation requires `state=READY` and
`chapter_number=current_chapter+1`, so concurrent or out-of-order submissions
fail before reaching Chapter Authority.

Pause/resume use the existing Command Kernel Saga Gate. The durable Book
checkpoint and root Operation/Saga move together; no process-local pause flag is
authoritative.

The older `book.production.run` fixture protocol is retained for tests only and
fails closed in production-like environments.
