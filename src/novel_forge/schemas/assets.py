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
class CreativeStrategyProfile(BaseAsset):
    type: str = "creative_strategy_profile"


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
class ChapterContinuityReport(BaseAsset):
    type: str = "chapter_continuity_report"


@dataclass
class ContinuityGraphSnapshot(BaseAsset):
    type: str = "continuity_graph_snapshot"


@dataclass
class CanonGraphSnapshot(BaseAsset):
    type: str = "canon_graph_snapshot"


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
class OutlineVersion(BaseAsset):
    type: str = "outline_version"


@dataclass
class ChapterPlan(BaseAsset):
    type: str = "chapter_plan"


@dataclass
class ChapterPlanVersion(BaseAsset):
    type: str = "chapter_plan_version"


@dataclass
class ContextBuildPlan(BaseAsset):
    type: str = "context_build_plan"


@dataclass
class ContextBundle(BaseAsset):
    type: str = "context_bundle"


@dataclass
class RagQualityReport(BaseAsset):
    type: str = "rag_quality_report"


@dataclass
class GenerationRun(BaseAsset):
    type: str = "generation_run"


@dataclass
class ChapterProductionRun(BaseAsset):
    type: str = "chapter_production_run"


@dataclass
class DraftChapter(BaseAsset):
    type: str = "draft_chapter"


@dataclass
class DraftVersion(BaseAsset):
    type: str = "draft_version"


@dataclass
class EditorPatch(BaseAsset):
    type: str = "editor_patch"


@dataclass
class DraftDiffReport(BaseAsset):
    type: str = "draft_diff_report"


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
class FeedbackImportBatch(BaseAsset):
    type: str = "feedback_import_batch"


@dataclass
class FeedbackInsight(BaseAsset):
    type: str = "feedback_insight"


@dataclass
class ReaderSentimentReport(BaseAsset):
    type: str = "reader_sentiment_report"


@dataclass
class ProjectMetricSnapshot(BaseAsset):
    type: str = "project_metric_snapshot"


@dataclass
class LocalSettingsProfile(BaseAsset):
    type: str = "local_settings_profile"


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
class WorkflowDefinition(BaseAsset):
    type: str = "workflow_definition"


@dataclass
class WorkflowNode(BaseAsset):
    type: str = "workflow_node"


@dataclass
class NodeRun(BaseAsset):
    type: str = "node_run"


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


@dataclass
class ChangeImpactReport(BaseAsset):
    type: str = "change_impact_report"


@dataclass
class AgentContract(BaseAsset):
    type: str = "agent_contract"


@dataclass
class AgentRun(BaseAsset):
    type: str = "agent_run"


@dataclass
class AgentCheckpoint(BaseAsset):
    type: str = "agent_checkpoint"


@dataclass
class AgentEvent(BaseAsset):
    type: str = "agent_event"


@dataclass
class AgentBudget(BaseAsset):
    type: str = "agent_budget"


@dataclass
class AgentGate(BaseAsset):
    type: str = "agent_gate"


@dataclass
class AgentMetric(BaseAsset):
    type: str = "agent_metric"


@dataclass
class AgentFailureReport(BaseAsset):
    type: str = "agent_failure_report"


@dataclass
class AgentSlaReport(BaseAsset):
    type: str = "agent_sla_report"


@dataclass
class AgentRollbackReport(BaseAsset):
    type: str = "agent_rollback_report"


@dataclass
class ModelProfile(BaseAsset):
    type: str = "model_profile"


@dataclass
class ModelBenchmarkTask(BaseAsset):
    type: str = "model_benchmark_task"


@dataclass
class ModelBenchmarkRun(BaseAsset):
    type: str = "model_benchmark_run"


@dataclass
class ModelComparisonReport(BaseAsset):
    type: str = "model_comparison_report"


@dataclass
class PromptVersion(BaseAsset):
    type: str = "prompt_version"


@dataclass
class PromptRegressionReport(BaseAsset):
    type: str = "prompt_regression_report"


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
        CreativeStrategyProfile,
        TopicSeed,
        TopicFitReport,
        WorldBible,
        CharacterCard,
        ContinuityBible,
        ForeshadowingThread,
        PowerScaleRule,
        ChapterContinuityReport,
        ContinuityGraphSnapshot,
        CanonGraphSnapshot,
        StyleProfile,
        StyleDecompositionReport,
        StyleBlendPreset,
        QualityStandardProfile,
        ReviewRulePack,
        WritingTemplate,
        CraftTemplate,
        Outline,
        OutlineVersion,
        ChapterPlan,
        ChapterPlanVersion,
        ContextBuildPlan,
        ContextBundle,
        RagQualityReport,
        GenerationRun,
        ChapterProductionRun,
        DraftChapter,
        DraftVersion,
        EditorPatch,
        DraftDiffReport,
        ReviewReport,
        RevisionPlan,
        QualityScoreReport,
        StyleReviewReport,
        ChapterAuditReport,
        OriginalityReport,
        PublishGateReport,
        ReleasePackage,
        ReaderFeedback,
        FeedbackImportBatch,
        FeedbackInsight,
        ReaderSentimentReport,
        ProjectMetricSnapshot,
        LocalSettingsProfile,
        TrainingExercise,
        ImagePrompt,
        ClaudeCodeHandoff,
        WorkflowRun,
        WorkflowDefinition,
        WorkflowNode,
        NodeRun,
        TaskStatus,
        TaskDeadLetter,
        BatchTaskItem,
        ProjectWorkspaceState,
        ChangeImpactReport,
        AgentContract,
        AgentRun,
        AgentCheckpoint,
        AgentEvent,
        AgentBudget,
        AgentGate,
        AgentMetric,
        AgentFailureReport,
        AgentSlaReport,
        AgentRollbackReport,
        ModelProfile,
        ModelBenchmarkTask,
        ModelBenchmarkRun,
        ModelComparisonReport,
        PromptVersion,
        PromptRegressionReport,
    ]
}


def asset_from_dict(data: dict[str, Any]) -> BaseAsset:
    cls = SCHEMA_CLASSES.get(data.get("type"), BaseAsset)
    return cls.from_dict(data)
