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
- WorkflowRun
- TaskStatus
- ProjectWorkspaceState

Validation entry:

```bash
./novel-forge validate
```

## Status Assets

`WorkflowRun` content must include `status` and `outputs`. Completed runs require output paths. Failed runs require `error_message`, `run_log`, and `recovery_instruction`.

`TaskStatus` content must include `step`, `status`, `input_paths`, `output_paths`, and `error_message`. Completed task statuses require output paths. Failed task statuses require an error message.

## Workspace Assets

`ProjectWorkspaceState` content must include `project_id`, `memory`, `chapter_states`, `continuity_threads`, and `open_issues`. It is stored under `data/workspaces/` and is used for long-project memory, multi-chapter continuity, unresolved hooks, and open quality issues.
