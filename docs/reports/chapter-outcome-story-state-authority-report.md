# ChapterOutcome and Story State Authority

Status: `implemented=true`, `handler_bound=true`,
`integration_proven=true`, `real_provider_proven=false`,
`longform_proven=false`, `production_verified=false`.

`book.chapter.accept` validates the terminal Chapter root and Saga, final
release gate, export receipt, quality aggregate, blocking ReviewIssues, Canon,
settled budgets, ExternalEffects, and frozen ChapterPlan identity before
materializing:

- one immutable `chapter_outcome`;
- one immutable `story_state_snapshot`.

Story State is reduced without model calls by a 14-entry reducer registry:
timeline, character, relationship, world, resource, power, foreshadow, mystery,
reader promise, reward, narrative debt, theme, antagonist and Arc
contribution. Each application has a deterministic transition hash and stable
idempotency key.

`authority_story_state_reducer_application` enforces one reducer application per
project, ChapterOutcome and reducer key. If a worker stops after the state asset
is written and only some reducer evidence rows are registered, replay reads the
same immutable output and inserts only missing records. The Book cursor is not
advanced until all reducer evidence is present.

Evidence:

- `tests.unit.test_chapter_outcome_story_state`
- `tests.integration.test_chapter_outcome_story_state_postgres`
- seven reducer records survive an injected mid-registration crash;
- replay converges to exactly fourteen records and one StoryState version;
- the operation output is not duplicated.
