# Data Flow

```text
examples/sample_inputs/sample_novel.txt
  -> data/raw/SourceDocument
  -> data/cleaned/CleanedText
  -> data/decompositions/DecompositionReport
  -> data/knowledge/KnowledgeCard
  -> data/materials/MaterialCard
  -> data/topics/TopicSeed
  -> data/worlds/WorldBible
  -> data/characters/CharacterCard
  -> data/outlines/Outline
  -> data/chapter_plans/ChapterPlan
  -> data/drafts/DraftChapter
  -> data/reviews/ReviewReport
  -> data/reviews/RevisionPlan
examples/sample_inputs/sample_feedback.csv
  -> data/feedback/ReaderFeedback
  -> data/feedback/FeedbackInsight
```

Every asset contains `source` and `references` so lineage remains traceable.

Industrial projections are derived from the same assets:

```text
data/**/*.json -> PostgreSQL nf_assets / nf_asset_versions / nf_task_statuses
data/**/*.json -> Qdrant collection payloads and vectors
data/**/*.json -> MinIO artifact objects
characters/worlds/outlines -> optional Neo4j graph projection
```

These projections can be rebuilt. They do not bypass schema validation or replace the JSON audit trail.
