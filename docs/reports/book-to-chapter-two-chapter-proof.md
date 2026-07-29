# Book-to-Chapter two-chapter proof

Status: `integration_proven=true`, `fixture_proven=true`,
`real_provider_proven=false`, `production_verified=false`.

The governed path is:

```text
book.production.coordinate
→ authority_child_delegation
→ chapter.slice.run
→ independent Chapter worker ticks
→ Book reconciliation
→ book.chapter.accept
→ ChapterOutcome + StoryStateSnapshot
→ atomic Book cursor advance
```

The Book Authority creates only the current child. It stores the child root
Operation and Saga references but never copies Attempt, Lease, Fence, effect, or
provider state. Chapter 2 is admitted only after Chapter 1 acceptance. Its
frozen Context input automatically includes the accepted Canon state snapshots
and aggregate StoryStateSnapshot from Chapter 1.

PostgreSQL constraints enforce one active child per Book, one acceptance per
delegation/request, and unique outcome/state lineage. Failure injection covers
the admission/persistence ambiguity window and the acceptance/cursor atomic
boundary.

Evidence:

- `tests.integration.test_book_to_chapter_authority_vertical_postgres`
- two distinct `chapter.slice.run` roots admitted dynamically;
- two accepted delegations and two append-only ChapterOutcome/StoryState pairs;
- repeated dispatch and acceptance do not create new roots or advance the
  cursor twice;
- Pause blocks new admission, Resume reconciles the existing child, and Cancel
  propagates to the Chapter root.

The provider is the deterministic scripted PEP backend. This is not evidence of
a real Provider or long-form production run.
