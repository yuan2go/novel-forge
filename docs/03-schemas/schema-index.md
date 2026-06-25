# Schema Index

All schemas inherit common fields: `id`, `type`, `title`, `name`, `source`, `tags`, `created_at`, `updated_at`, `version`, `content`, `metadata`, `references`.

Implemented schema classes:

- SourceDocument
- CleanedText
- DecompositionReport
- CommercialPattern
- NarrativePattern
- CharacterMechanism
- ConflictPattern
- EmotionCurve
- HookPattern
- KnowledgeCard
- MaterialCard
- AssetCollection
- TopicSeed
- WorldBible
- CharacterCard
- Outline
- ChapterPlan
- DraftChapter
- ReviewReport
- RevisionPlan
- ReaderFeedback
- FeedbackInsight
- TrainingExercise
- ImagePrompt
- ClaudeCodeHandoff
- WorkflowRun
- TaskStatus
- TaskDeadLetter
- BatchTaskItem
- ProjectWorkspaceState

Validation entry:

```bash
./novel-forge validate
```

## Status Assets

`WorkflowRun` content must include `status` and `outputs`. Completed runs require output paths. Failed runs require `error_message`, `run_log`, and `recovery_instruction`.

`TaskStatus` content must include `step`, `status`, `input_paths`, `output_paths`, and `error_message`. Completed task statuses require output paths. Failed task statuses require an error message.

`TaskDeadLetter` content must include `task_name`, `task_id`, `error_message`, and `payload`. Worker failures write these assets under `data/runs/` so failed Celery jobs remain inspectable and retryable from the task center.

`BatchTaskItem` content must include `batch_id`, `item_index`, `source_path`, `status`, `steps`, `output_paths`, and `error_message`. Failed items may keep empty `output_paths`; completed items must include produced asset paths. Batch item assets are stored under `data/runs/` so retries, failures, and per-file outputs remain auditable.

Batch item review gates write `content.review_status` and `metadata.review_gate` with `approved`, `rejected`, or `needs_revision`, so batch deconstruction can pause for human approval before downstream use.

`ClaudeCodeHandoff` content must include `operation`, `runtime`, `runtime_model`, `skill`, `status`, `input_files`, `expected_output_type`, `expected_output_dir`, `instructions`, and `acceptance_checks`. It is stored under `data/runs/` and represents an auditable manual Claude Code/Codex analysis request. Handoffs reference source paths and skill files; they must not embed source text.

`AssetCollection` content must include `purpose` and `asset_paths`. It is stored under `data/materials/` and represents a saved asset search result, task input set, or reusable material set while retaining references to the original asset ids.

## Workspace Assets

`ProjectWorkspaceState` content must include `project_id`, `memory`, `chapter_states`, `continuity_threads`, and `open_issues`. It is stored under `data/workspaces/` and is used for long-project memory, multi-chapter continuity, unresolved hooks, open quality issues, and project lifecycle metadata. Product deletion is a soft lifecycle state, not physical file removal.

## Source Rights

`SourceDocument.metadata.rights` is required for imported materials. It records `authorization`, `license`, `copyright_boundary`, `source_url`, and `allow_downstream_generation`.

Allowed authorization values are:

- `owned`
- `licensed`
- `public_domain`
- `permission_granted`
- `test_fixture`
- `unknown`

Unknown rights are recorded explicitly so downstream workflows can treat them as risk-bearing sources instead of silently mixing them into generated assets.
