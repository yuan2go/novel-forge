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
