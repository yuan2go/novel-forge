from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_forge.schemas.base import BaseAsset


@dataclass
class SourceDocument(BaseAsset):
    type: str = "source_document"


@dataclass
class CleanedText(BaseAsset):
    type: str = "cleaned_text"


@dataclass
class DecompositionReport(BaseAsset):
    type: str = "decomposition_report"


@dataclass
class CommercialPattern(BaseAsset):
    type: str = "commercial_pattern"


@dataclass
class NarrativePattern(BaseAsset):
    type: str = "narrative_pattern"


@dataclass
class CharacterMechanism(BaseAsset):
    type: str = "character_mechanism"


@dataclass
class ConflictPattern(BaseAsset):
    type: str = "conflict_pattern"


@dataclass
class EmotionCurve(BaseAsset):
    type: str = "emotion_curve"


@dataclass
class HookPattern(BaseAsset):
    type: str = "hook_pattern"


@dataclass
class KnowledgeCard(BaseAsset):
    type: str = "knowledge_card"


@dataclass
class MaterialCard(BaseAsset):
    type: str = "material_card"


@dataclass
class TopicSeed(BaseAsset):
    type: str = "topic_seed"


@dataclass
class WorldBible(BaseAsset):
    type: str = "world_bible"


@dataclass
class CharacterCard(BaseAsset):
    type: str = "character_card"


@dataclass
class Outline(BaseAsset):
    type: str = "outline"


@dataclass
class ChapterPlan(BaseAsset):
    type: str = "chapter_plan"


@dataclass
class DraftChapter(BaseAsset):
    type: str = "draft_chapter"


@dataclass
class ReviewReport(BaseAsset):
    type: str = "review_report"
    score: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = "medium"
    revision_suggestions: list[str] = field(default_factory=list)
    next_action: str = "revise"


@dataclass
class RevisionPlan(BaseAsset):
    type: str = "revision_plan"


@dataclass
class ReaderFeedback(BaseAsset):
    type: str = "reader_feedback"


@dataclass
class FeedbackInsight(BaseAsset):
    type: str = "feedback_insight"


@dataclass
class TrainingExercise(BaseAsset):
    type: str = "training_exercise"


@dataclass
class ImagePrompt(BaseAsset):
    type: str = "image_prompt"


@dataclass
class WorkflowRun(BaseAsset):
    type: str = "workflow_run"


@dataclass
class TaskStatus(BaseAsset):
    type: str = "task_status"


@dataclass
class ProjectWorkspaceState(BaseAsset):
    type: str = "project_workspace_state"


SCHEMA_CLASSES = {
    cls().type: cls
    for cls in [
        SourceDocument,
        CleanedText,
        DecompositionReport,
        CommercialPattern,
        NarrativePattern,
        CharacterMechanism,
        ConflictPattern,
        EmotionCurve,
        HookPattern,
        KnowledgeCard,
        MaterialCard,
        TopicSeed,
        WorldBible,
        CharacterCard,
        Outline,
        ChapterPlan,
        DraftChapter,
        ReviewReport,
        RevisionPlan,
        ReaderFeedback,
        FeedbackInsight,
        TrainingExercise,
        ImagePrompt,
        WorkflowRun,
        TaskStatus,
        ProjectWorkspaceState,
    ]
}


def asset_from_dict(data: dict[str, Any]) -> BaseAsset:
    cls = SCHEMA_CLASSES.get(data.get("type"), BaseAsset)
    return cls.from_dict(data)
