# ChapterGroup Authority and Rolling Horizon

Status: `documented=true`, `implemented=true`, `handler_bound=true`,
`fixture_proven=true`, `integration_proven=true`,
`real_provider_proven=false`, `longform_proven=false`,
`production_verified=false`.

## Authority shape

`chapter_group.production.run` owns only group checkpoints and references. It
does not copy Chapter Operation, Saga, Attempt, Lease, Fence, effect or receipt
state. Chapter execution remains:

```text
ChapterGroup Authority
→ Book Authority command port
→ Chapter Authority
→ Chapter root Operation / Saga / Attempt
→ Book chapter acceptance
→ ChapterOutcome / StoryState
→ ChapterGroup checkpoint
```

The group dynamically admits one current Chapter. Starting a group does not
precreate future Chapter Operations. Pause gates both Book and ChapterGroup
Sagas; resume reconciles the existing Book child before another dispatch;
cancel propagates through Book Authority to the active Chapter and cancels the
group root.

The group root records deterministic child Operations for prepare, plan
resolution, function-matrix validation, chapter dispatch/reconcile/accept,
Recap observation, plan-vs-actual evaluation, adjustment proposal and close.
Those operations run through the shared fenced Authority handler runtime.

## Closure

Closure requires every chapter in the frozen three-to-eight-chapter range to be
accepted and a successful deterministic boundary Recap. It materializes a
`PlanVsActualReport` and a future-only
`GroupPlanAdjustmentProposal`; neither can mutate an Active Plan.

The same transaction closes the group, supersedes the previous current
`PlanningHorizon`, writes one new current horizon and emits state, audit and
outbox evidence. The tested three-chapter horizon is:

```text
executed=3
frozen=3
planned=10
speculative=23
```

## Evidence

- `tests.unit.test_chapter_group_authority`
- `tests.integration.test_chapter_group_authority_postgres`
- three independent Chapter Sagas using the repository Scripted Provider;
- exactly three Book child requests, roots, delegations and acceptances;
- all three ChapterOutcome assets bind the frozen ChapterGroup version;
- one boundary Recap and one adjustment proposal;
- active-child exclusion, pause/resume and cancel propagation.

Scripted Provider evidence proves the integration protocol, not a real model or
continuous long-form production.
