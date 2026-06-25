# Main Pipeline

## Command

```bash
./novel-forge run-pipeline --sample
```

For normal local runs, execute the sample pipeline through `make demo` or pass `--root .local/demo-workspace`. Generated assets and sample outputs should live in an ignored runtime workspace, not in the repository root.

## Steps

1. Import source material.
2. Clean text.
3. Decompose narrative/commercial mechanisms.
4. Extract knowledge.
5. Build reusable materials.
6. Generate topic.
7. Generate world.
8. Generate characters.
9. Generate outline.
10. Generate chapter plan.
11. Draft chapter.
12. Review draft.
13. Produce revision plan.
14. Import feedback.
15. Analyze feedback.

## Acceptance

A successful run creates a `WorkflowRun` JSON in `<workspace>/data/runs/` and a summary in `<workspace>/examples/sample_outputs/`.
Each pipeline step also writes `TaskStatus` JSON records under `<workspace>/data/runs/` for `pending`, `running`, and `completed`. If a step fails, the failed step writes a `failed` TaskStatus and the pipeline writes a failed `WorkflowRun` with an error message.

`WorkflowRun.content.run_log` contains a readable ordered log built from TaskStatus assets. Failed runs also include `recovery_instruction` and write a recovery note under `<workspace>/data/runs/`.

When `run-pipeline --sample` is used, the pipeline first reads the previous `<workspace>/examples/sample_outputs/pipeline-summary.json` and removes only the sample output files referenced by that summary. This keeps repeated sample runs from accumulating duplicate generated assets while avoiding broad cleanup of user data.
