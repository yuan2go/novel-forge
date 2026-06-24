# Skill Usage Workflow

## Module Goal

This workflow explains how Claude Code, Codex, DeepSeek, ChatGPT, and project Agents use `skills/` inside the V5 pipeline.

## Inputs

- Task or user request.
- Responsible Agent.
- `docs/09-skills/agent-skill-map.md`.
- Relevant `skills/*/SKILL.md`.
- Schema-backed input assets.

## Outputs

- Skill-guided analysis, plan, draft, review, or revision.
- Traceable output asset or documentation change.
- Review or validation result.

## File Paths

```text
docs/02-workflows/skill-usage.md
docs/09-skills/agent-skill-map.md
skills/
data/
```

## Execution Flow

1. Identify the task stage: deconstruction, abstraction, topic, world, character, outline, chapter plan, draft, review, or feedback.
2. Select the responsible Agent from `AGENTS.md`.
3. Select the Skill from `docs/09-skills/agent-skill-map.md`.
4. Read the corresponding `SKILL.md`.
5. Verify required inputs and copyright boundary.
6. Execute the Skill workflow.
7. Write output to the correct data or docs path.
8. Run `quality-review` or validation before downstream use.

## Common Routes

```text
Popular novel analysis
  -> hot-novel-deconstruction
  -> anti-copy-abstraction
  -> KnowledgeCard / MaterialCard

Creative planning
  -> worldbuilding
  -> character-design
  -> long-outline
  -> chapter-outline

Drafting
  -> chapter-outline
  -> prose-generation
  -> quality-review

Originality risk review
  -> anti-copy-abstraction
  -> quality-review

Reader feedback loop
  -> reader-feedback
  -> quality-review
  -> RevisionPlan / next ChapterPlan constraints

Project planning
  -> project-planning
  -> task pool / roadmap / acceptance criteria

Multidisciplinary knowledge
  -> multidisciplinary-knowledge
  -> KnowledgeCard / review checks

Topic development
  -> material-curation
  -> topic-development
  -> TopicSeed

Training
  -> training-exercise
  -> quality-review
  -> TrainingExercise
```

## Acceptance

- Task reports should name the Skills used when relevant.
- Drafting must not skip `chapter-outline`.
- Draft outputs must not skip `quality-review`.
- Reference-work analysis must not skip `anti-copy-abstraction`.
- DeepSeek or future draft adapters cannot produce final text directly.

## Risks And Boundaries

- Skill selection does not expand Agent permissions.
- Skills do not replace model adapters or CLI commands.
- Skills do not store source text.
- Skills output must obey schema, storage, and workflow boundaries.
