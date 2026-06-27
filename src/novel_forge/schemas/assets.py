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
class CommonNovelAnalysisReport(BaseAsset):
    type: str = "common_novel_analysis_report"


@dataclass
class WebFictionBusinessAnalysisReport(BaseAsset):
    type: str = "web_fiction_business_analysis_report"


@dataclass
class PublishedFictionAnalysisReport(BaseAsset):
    type: str = "published_fiction_analysis_report"


@dataclass
class ClassicLiteraryAnalysisReport(BaseAsset):
    type: str = "classic_literary_analysis_report"


@dataclass
class AnalysisConversionReport(BaseAsset):
    type: str = "analysis_conversion_report"


@dataclass
class KnowledgeCard(BaseAsset):
    type: str = "knowledge_card"


@dataclass
class MaterialCard(BaseAsset):
    type: str = "material_card"


@dataclass
class AssetCollection(BaseAsset):
    type: str = "asset_collection"


@dataclass
class PlatformProfile(BaseAsset):
    type: str = "platform_profile"


@dataclass
class GenreMarketProfile(BaseAsset):
    type: str = "genre_market_profile"


@dataclass
class TopicSeed(BaseAsset):
    type: str = "topic_seed"


@dataclass
class TopicFitReport(BaseAsset):
    type: str = "topic_fit_report"


@dataclass
class WorldBible(BaseAsset):
    type: str = "world_bible"


@dataclass
class CharacterCard(BaseAsset):
    type: str = "character_card"


@dataclass
class ContinuityBible(BaseAsset):
    type: str = "continuity_bible"


@dataclass
class ForeshadowingThread(BaseAsset):
    type: str = "foreshadowing_thread"


@dataclass
class PowerScaleRule(BaseAsset):
    type: str = "power_scale_rule"


@dataclass
class StyleProfile(BaseAsset):
    type: str = "style_profile"


@dataclass
class StyleDecompositionReport(BaseAsset):
    type: str = "style_decomposition_report"


@dataclass
class StyleBlendPreset(BaseAsset):
    type: str = "style_blend_preset"


@dataclass
class QualityStandardProfile(BaseAsset):
    type: str = "quality_standard_profile"


@dataclass
class ReviewRulePack(BaseAsset):
    type: str = "review_rule_pack"


@dataclass
class WritingTemplate(BaseAsset):
    type: str = "writing_template"


@dataclass
class CraftTemplate(BaseAsset):
    type: str = "craft_template"


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
class QualityScoreReport(BaseAsset):
    type: str = "quality_score_report"


@dataclass
class StyleReviewReport(BaseAsset):
    type: str = "style_review_report"


@dataclass
class ChapterAuditReport(BaseAsset):
    type: str = "chapter_audit_report"


@dataclass
class OriginalityReport(BaseAsset):
    type: str = "originality_report"


@dataclass
class PublishGateReport(BaseAsset):
    type: str = "publish_gate_report"


@dataclass
class ReleasePackage(BaseAsset):
    type: str = "release_package"


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
class ClaudeCodeHandoff(BaseAsset):
    type: str = "claude_code_handoff"


@dataclass
class WorkflowRun(BaseAsset):
    type: str = "workflow_run"


@dataclass
class TaskStatus(BaseAsset):
    type: str = "task_status"


@dataclass
class TaskDeadLetter(BaseAsset):
    type: str = "task_dead_letter"


@dataclass
class BatchTaskItem(BaseAsset):
    type: str = "batch_task_item"


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
        CommonNovelAnalysisReport,
        WebFictionBusinessAnalysisReport,
        PublishedFictionAnalysisReport,
        ClassicLiteraryAnalysisReport,
        AnalysisConversionReport,
        KnowledgeCard,
        MaterialCard,
        AssetCollection,
        PlatformProfile,
        GenreMarketProfile,
        TopicSeed,
        TopicFitReport,
        WorldBible,
        CharacterCard,
        ContinuityBible,
        ForeshadowingThread,
        PowerScaleRule,
        StyleProfile,
        StyleDecompositionReport,
        StyleBlendPreset,
        QualityStandardProfile,
        ReviewRulePack,
        WritingTemplate,
        CraftTemplate,
        Outline,
        ChapterPlan,
        DraftChapter,
        ReviewReport,
        RevisionPlan,
        QualityScoreReport,
        StyleReviewReport,
        ChapterAuditReport,
        OriginalityReport,
        PublishGateReport,
        ReleasePackage,
        ReaderFeedback,
        FeedbackInsight,
        TrainingExercise,
        ImagePrompt,
        ClaudeCodeHandoff,
        WorkflowRun,
        TaskStatus,
        TaskDeadLetter,
        BatchTaskItem,
        ProjectWorkspaceState,
    ]
}


def asset_from_dict(data: dict[str, Any]) -> BaseAsset:
    cls = SCHEMA_CLASSES.get(data.get("type"), BaseAsset)
    return cls.from_dict(data)
