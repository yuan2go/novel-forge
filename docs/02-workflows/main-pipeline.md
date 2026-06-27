# Main Pipeline

## Purpose

The main pipeline is the executable baseline for Novel Forge as a local-first AI novel production platform.

It should remain testable and deterministic by default while evolving toward a workflow-node, artifact-version, context-bundle, and quality-gate architecture.

## Command

```bash
./novel-forge run-pipeline --sample
```

For normal local runs, execute the sample pipeline through `make demo` or pass `--root .local/demo-workspace`. Generated assets and sample outputs should live in an ignored runtime workspace, not in the repository root.

## Current Executable Steps

```text
ingest
  -> clean
  -> decompose
  -> extract-knowledge
  -> build-materials
  -> generate-topic
  -> generate-world
  -> generate-characters
  -> generate-outline
  -> generate-chapter-plan
  -> draft
  -> init-workspace
  -> update-workspace-draft
  -> review
  -> review-derived reports
  -> update-workspace-review
  -> revise
  -> import-feedback
  -> analyze-feedback
```

## Current Acceptance

A successful run creates:

- a `WorkflowRun` JSON in `<workspace>/data/runs/`;
- `TaskStatus` JSON records in `<workspace>/data/runs/` for pipeline steps;
- a summary in `<workspace>/examples/sample_outputs/`.

If a step fails:

- the failed step records failed status;
- the pipeline writes a failed `WorkflowRun`;
- the run includes error message, readable run log, recovery instruction, and recovery note path.

When `run-pipeline --sample` is used, the pipeline removes only sample output files referenced by the previous sample summary. It must not broadly clean user data.

## Platform Direction

The current pipeline should be incrementally migrated toward this target:

```text
project strategy
  -> platform/genre strategy
  -> analysis center
  -> analysis-to-asset conversion
  -> context build plan
  -> context bundle
  -> topic/world/character planning
  -> outline version
  -> chapter-plan version
  -> generation run
  -> draft version
  -> review pipeline
  -> editor patch / revision task
  -> continuity and platform gates
  -> release package
  -> publishing plan/log
  -> reader feedback analytics
  -> next chapter plan update
```

## Node Contract

Every future pipeline step should be expressible as a node with:

| Contract Field | Required Meaning |
|---|---|
| node id/type | stable name and production role |
| inputs | artifact paths, project/workspace id, parameters |
| context bundle | actual model/retrieval context when applicable |
| processor | service, model adapter, handoff, worker, or future Agent |
| output artifact | schema-backed asset or version |
| gate | pass/fail/needs_revision criteria |
| run record | timing, provider, status, errors, prompt/Skill version |
| recovery | retry, rollback, rerun, manual handoff, or invalidation path |

## Priority Migration

1. Keep existing CLI pipeline stable.
2. Add workflow/node run and artifact-version contracts around current steps.
3. Keep Context Builder schema/service/API/UI stable and add manual curation plus stale-context warnings.
4. Keep versioned outline/chapter-plan/draft/generation-run records stable and add chapter queue plus invalidation.
5. Deepen Analysis Center semantic scoring and conversion review gates after the production chain can consume analysis outputs reliably.
6. Add long-form stability, editor patches, Agent runs, publishing, feedback analytics, and model evaluation after the core chain is traceable.

## Non-Negotiable Boundaries

- Raw reference text must not be injected into draft generation.
- Analysis outputs are abstract mechanisms, not draft prose.
- Draft generation must not skip chapter plan.
- Drafts must not skip review before release decisions.
- Revisions must create a new artifact/version or patch record.
- Failed runs must produce recovery information.
- Provider calls must be opt-in and schema-validated.
