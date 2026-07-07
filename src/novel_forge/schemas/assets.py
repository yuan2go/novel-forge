from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_forge.schemas.base import BaseAsset


@dataclass
class SourceDocument(BaseAsset):
    type: str = "source_document"


@dataclass
class SourcePolicy(BaseAsset):
    type: str = "source_policy"


@dataclass
class SourceSyncJob(BaseAsset):
    type: str = "source_sync_job"


@dataclass
class SourceSnapshot(BaseAsset):
    type: str = "source_snapshot"


@dataclass
class LicenseCheckResult(BaseAsset):
    type: str = "license_check_result"


@dataclass
class SourceRiskReport(BaseAsset):
    type: str = "source_risk_report"


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
class SourceChunk(BaseAsset):
    type: str = "source_chunk"


@dataclass
class KnowledgeUsageBinding(BaseAsset):
    type: str = "knowledge_usage_binding"


@dataclass
class RuleCard(BaseAsset):
    type: str = "rule_card"


@dataclass
class TemplateCard(BaseAsset):
    type: str = "template_card"


@dataclass
class KnowledgePack(BaseAsset):
    type: str = "knowledge_pack"


@dataclass
class KnowledgePackItem(BaseAsset):
    type: str = "knowledge_pack_item"


@dataclass
class KnowledgeUsageEvent(BaseAsset):
    type: str = "knowledge_usage_event"


@dataclass
class KnowledgeQualityScore(BaseAsset):
    type: str = "knowledge_quality_score"


@dataclass
class KnowledgeGraphSnapshot(BaseAsset):
    type: str = "knowledge_graph_snapshot"


@dataclass
class KnowledgeLearningSnapshot(BaseAsset):
    type: str = "knowledge_learning_snapshot"


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
class PlatformRhythmRule(BaseAsset):
    type: str = "platform_rhythm_rule"


@dataclass
class PlatformOpeningGate(BaseAsset):
    type: str = "platform_opening_gate"


@dataclass
class PlatformChapterGate(BaseAsset):
    type: str = "platform_chapter_gate"


@dataclass
class PlatformRetentionRisk(BaseAsset):
    type: str = "platform_retention_risk"


@dataclass
class PlatformPublishAdapter(BaseAsset):
    type: str = "platform_publish_adapter"


@dataclass
class PlatformFeedbackBackflow(BaseAsset):
    type: str = "platform_feedback_backflow"


@dataclass
class PlatformStrategyPack(BaseAsset):
    type: str = "platform_strategy_pack"


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
class NovelKGSnapshot(BaseAsset):
    type: str = "novel_kg_snapshot"


@dataclass
class SemanticExtractionReport(BaseAsset):
    type: str = "semantic_extraction_report"


@dataclass
class KgIdentityResolution(BaseAsset):
    type: str = "kg_identity_resolution"


@dataclass
class CanonPatch(BaseAsset):
    type: str = "canon_patch"


@dataclass
class CanonDatabase(BaseAsset):
    type: str = "canon_database"


@dataclass
class ChapterStatePackage(BaseAsset):
    type: str = "chapter_state"


@dataclass
class ChapterPatternReport(BaseAsset):
    type: str = "chapter_pattern_report"


@dataclass
class FactLedger(BaseAsset):
    type: str = "fact_ledger"


@dataclass
class ArcPlan(BaseAsset):
    type: str = "arc_plan"


@dataclass
class ForeshadowingGraph(BaseAsset):
    type: str = "foreshadowing_graph"


@dataclass
class ReaderPromise(BaseAsset):
    type: str = "reader_promise"


@dataclass
class ReaderPromiseLedger(BaseAsset):
    type: str = "reader_promise_ledger"


@dataclass
class PleasurePoint(BaseAsset):
    type: str = "pleasure_point"


@dataclass
class ChapterEconomyReport(BaseAsset):
    type: str = "chapter_economy_report"


@dataclass
class ProtagonistCharmReport(BaseAsset):
    type: str = "protagonist_charm_report"


@dataclass
class AntagonistPressureReport(BaseAsset):
    type: str = "antagonist_pressure_report"


@dataclass
class MobileReadingReport(BaseAsset):
    type: str = "mobile_reading_report"


@dataclass
class MotifBudgetReport(BaseAsset):
    type: str = "motif_budget_report"


@dataclass
class CharacterStateLedger(BaseAsset):
    type: str = "character_state_ledger"


@dataclass
class VillainOperationPlan(BaseAsset):
    type: str = "villain_operation_plan"


@dataclass
class ReaderFatigueReport(BaseAsset):
    type: str = "reader_fatigue_report"


@dataclass
class StyleControlPlan(BaseAsset):
    type: str = "style_control_plan"


@dataclass
class PlatformAdapterReport(BaseAsset):
    type: str = "platform_adapter_report"


@dataclass
class RewardLedger(BaseAsset):
    type: str = "reward_ledger"


@dataclass
class ReviewScoreSystemReport(BaseAsset):
    type: str = "review_score_system_report"


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
class LongFormMacroPlan(BaseAsset):
    type: str = "long_form_macro_plan"


@dataclass
class LongformRecapReport(BaseAsset):
    type: str = "longform_recap_report"


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
class ReviewIssue(BaseAsset):
    type: str = "review_issue"


@dataclass
class LoopRun(BaseAsset):
    type: str = "loop_run"


@dataclass
class LoopStep(BaseAsset):
    type: str = "loop_step"


@dataclass
class LoopCheckpoint(BaseAsset):
    type: str = "loop_checkpoint"


@dataclass
class LoopReport(BaseAsset):
    type: str = "loop_report"


@dataclass
class RevisionTask(BaseAsset):
    type: str = "revision_task"


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
class ProductionGovernanceReport(BaseAsset):
    type: str = "production_governance_report"


@dataclass
class FallbackDecision(BaseAsset):
    type: str = "fallback_decision"


@dataclass
class PublishingPlan(BaseAsset):
    type: str = "publishing_plan"


@dataclass
class PublishingLog(BaseAsset):
    type: str = "publishing_log"


@dataclass
class ReaderFeedback(BaseAsset):
    type: str = "reader_feedback"


@dataclass
class FeedbackCluster(BaseAsset):
    type: str = "feedback_cluster"


@dataclass
class FeedbackBackflowPlan(BaseAsset):
    type: str = "feedback_backflow_plan"


@dataclass
class PlanAdjustmentProposal(BaseAsset):
    type: str = "plan_adjustment_proposal"


@dataclass
class ReviewRuleUpdateProposal(BaseAsset):
    type: str = "review_rule_update_proposal"


@dataclass
class FeedbackKGPatch(BaseAsset):
    type: str = "feedback_kg_patch"


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
class ReaderSimulationReport(BaseAsset):
    type: str = "reader_simulation_report"


@dataclass
class OperationalMetricSnapshot(BaseAsset):
    type: str = "operational_metric_snapshot"


@dataclass
class ReaderFeedbackBackflowReport(BaseAsset):
    type: str = "reader_feedback_backflow_report"


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
class AgentTask(BaseAsset):
    type: str = "agent_task"


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
class AgentDispatchQueue(BaseAsset):
    type: str = "agent_dispatch_queue"


@dataclass
class AgentRegistryEntry(BaseAsset):
    type: str = "agent_registry_entry"


@dataclass
class AgentVersion(BaseAsset):
    type: str = "agent_version"


@dataclass
class AgentCapability(BaseAsset):
    type: str = "agent_capability"


@dataclass
class AgentLifecycleEvent(BaseAsset):
    type: str = "agent_lifecycle_event"


@dataclass
class AgentEvaluationBinding(BaseAsset):
    type: str = "agent_evaluation_binding"


@dataclass
class AgentRegistrySnapshot(BaseAsset):
    type: str = "agent_registry_snapshot"


@dataclass
class OperationTransaction(BaseAsset):
    type: str = "operation_transaction"


@dataclass
class RollbackPlan(BaseAsset):
    type: str = "rollback_plan"


@dataclass
class RollbackResult(BaseAsset):
    type: str = "rollback_result"


@dataclass
class SchedulerLease(BaseAsset):
    type: str = "scheduler_lease"


@dataclass
class TraceSpan(BaseAsset):
    type: str = "trace_span"


@dataclass
class GateResult(BaseAsset):
    type: str = "gate_result"


@dataclass
class ModelCallLog(BaseAsset):
    type: str = "model_call_log"


@dataclass
class CostLedger(BaseAsset):
    type: str = "cost_ledger"


@dataclass
class BudgetPolicy(BaseAsset):
    type: str = "budget_policy"


@dataclass
class CostAlert(BaseAsset):
    type: str = "cost_alert"


@dataclass
class ProjectCostSnapshot(BaseAsset):
    type: str = "project_cost_snapshot"


@dataclass
class AgentCostSnapshot(BaseAsset):
    type: str = "agent_cost_snapshot"


@dataclass
class ChapterCostSnapshot(BaseAsset):
    type: str = "chapter_cost_snapshot"


@dataclass
class CostQualityDashboard(BaseAsset):
    type: str = "cost_quality_dashboard"


@dataclass
class AuditLog(BaseAsset):
    type: str = "audit_log"


@dataclass
class AuditTrailReport(BaseAsset):
    type: str = "audit_trail_report"


@dataclass
class AuditExportPackage(BaseAsset):
    type: str = "audit_export_package"


@dataclass
class ModelProfile(BaseAsset):
    type: str = "model_profile"


@dataclass
class ModelRoute(BaseAsset):
    type: str = "model_route"


@dataclass
class ModelRouteResolution(BaseAsset):
    type: str = "model_route_resolution"


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
class PromptTemplate(BaseAsset):
    type: str = "prompt_template"


@dataclass
class PromptVersion(BaseAsset):
    type: str = "prompt_version"


@dataclass
class PromptRelease(BaseAsset):
    type: str = "prompt_release"


@dataclass
class PromptNodeBinding(BaseAsset):
    type: str = "prompt_node_binding"


@dataclass
class PromptRegressionReport(BaseAsset):
    type: str = "prompt_regression_report"


@dataclass
class ModelRoutingPolicy(BaseAsset):
    type: str = "model_routing_policy"


@dataclass
class EvaluationSuite(BaseAsset):
    type: str = "evaluation_suite"


@dataclass
class EvaluationCase(BaseAsset):
    type: str = "evaluation_case"


@dataclass
class EvaluationRun(BaseAsset):
    type: str = "evaluation_run"


@dataclass
class EvaluationResult(BaseAsset):
    type: str = "evaluation_result"


@dataclass
class EvaluationMetric(BaseAsset):
    type: str = "evaluation_metric"


@dataclass
class EvaluationGate(BaseAsset):
    type: str = "evaluation_gate"


@dataclass
class EvaluationRegressionReport(BaseAsset):
    type: str = "evaluation_regression_report"


@dataclass
class EvaluationDashboardSnapshot(BaseAsset):
    type: str = "evaluation_dashboard_snapshot"


@dataclass
class ToolDefinition(BaseAsset):
    type: str = "tool_definition"


@dataclass
class ToolInvocation(BaseAsset):
    type: str = "tool_invocation"


@dataclass
class ToolPermissionPolicy(BaseAsset):
    type: str = "tool_permission_policy"


@dataclass
class ApprovalRequest(BaseAsset):
    type: str = "approval_request"


@dataclass
class MCPServerRegistry(BaseAsset):
    type: str = "mcp_server_registry"


@dataclass
class StateEvent(BaseAsset):
    type: str = "state_event"


@dataclass
class StateSnapshot(BaseAsset):
    type: str = "state_snapshot"


@dataclass
class StateReplay(BaseAsset):
    type: str = "state_replay"


@dataclass
class StateConflictReport(BaseAsset):
    type: str = "state_conflict_report"


@dataclass
class AgentMessage(BaseAsset):
    type: str = "agent_message"


@dataclass
class AgentInbox(BaseAsset):
    type: str = "agent_inbox"


@dataclass
class AgentOutbox(BaseAsset):
    type: str = "agent_outbox"


@dataclass
class AgentHandoff(BaseAsset):
    type: str = "agent_handoff"


@dataclass
class AgentConversationTrace(BaseAsset):
    type: str = "agent_conversation_trace"


@dataclass
class MemoryRecord(BaseAsset):
    type: str = "memory_record"


@dataclass
class MemorySelection(BaseAsset):
    type: str = "memory_selection"


@dataclass
class MemoryRetrievalReport(BaseAsset):
    type: str = "memory_retrieval_report"


@dataclass
class MemoryChunk(BaseAsset):
    type: str = "memory_chunk"


@dataclass
class KnowledgeChunk(BaseAsset):
    type: str = "knowledge_chunk"


@dataclass
class ArtifactEmbedding(BaseAsset):
    type: str = "artifact_embedding"


@dataclass
class ReviewMemoryChunk(BaseAsset):
    type: str = "review_memory_chunk"


@dataclass
class EntityMemoryChunk(BaseAsset):
    type: str = "entity_memory_chunk"


@dataclass
class PgVectorSchemaPlan(BaseAsset):
    type: str = "pgvector_schema_plan"


@dataclass
class EmbeddingJob(BaseAsset):
    type: str = "embedding_job"


@dataclass
class HybridRetrievalReport(BaseAsset):
    type: str = "hybrid_retrieval_report"


@dataclass
class AnalyticsEvent(BaseAsset):
    type: str = "analytics_event"


@dataclass
class AnalyticsSyncJob(BaseAsset):
    type: str = "analytics_sync_job"


@dataclass
class AnalyticsDashboardSnapshot(BaseAsset):
    type: str = "analytics_dashboard_snapshot"


@dataclass
class AnalyticsMetricDefinition(BaseAsset):
    type: str = "analytics_metric_definition"


@dataclass
class LocalOpsDrillReport(BaseAsset):
    type: str = "local_ops_drill_report"


@dataclass
class LongChainAcceptanceReport(BaseAsset):
    type: str = "long_chain_acceptance_report"


@dataclass
class GenreProfile(BaseAsset):
    type: str = "genre_profile"


@dataclass
class SubgenreMechanic(BaseAsset):
    type: str = "subgenre_mechanic"


@dataclass
class GenreStrategyPack(BaseAsset):
    type: str = "genre_strategy_pack"


@dataclass
class GenreRiskGate(BaseAsset):
    type: str = "genre_risk_gate"


@dataclass
class PlatformGenreFit(BaseAsset):
    type: str = "platform_genre_fit"


@dataclass
class GenreTemplateBinding(BaseAsset):
    type: str = "genre_template_binding"


@dataclass
class StyleSample(BaseAsset):
    type: str = "style_sample"


@dataclass
class StyleFingerprint(BaseAsset):
    type: str = "style_fingerprint"


@dataclass
class StyleGenerationPolicy(BaseAsset):
    type: str = "style_generation_policy"


@dataclass
class StyleReviewRule(BaseAsset):
    type: str = "style_review_rule"


@dataclass
class StyleDriftReport(BaseAsset):
    type: str = "style_drift_report"


@dataclass
class StyleRewriteTask(BaseAsset):
    type: str = "style_rewrite_task"


@dataclass
class FantasyPowerScaleReport(BaseAsset):
    type: str = "fantasy_power_scale_report"


@dataclass
class MysteryEvidenceChainReport(BaseAsset):
    type: str = "mystery_evidence_chain_report"


@dataclass
class RomanceRelationshipStateReport(BaseAsset):
    type: str = "romance_relationship_state_report"


@dataclass
class HistoricalFactionNetworkReport(BaseAsset):
    type: str = "historical_faction_network_report"


@dataclass
class SciFiRuleConsistencyReport(BaseAsset):
    type: str = "sci_fi_rule_consistency_report"


@dataclass
class HorrorRuleContaminationReport(BaseAsset):
    type: str = "horror_rule_contamination_report"


@dataclass
class QualityRubricPack(BaseAsset):
    type: str = "quality_rubric_pack"


@dataclass
class Opening3Report(BaseAsset):
    type: str = "opening_3_report"


@dataclass
class Golden10Report(BaseAsset):
    type: str = "golden_10_report"


@dataclass
class Volume30Report(BaseAsset):
    type: str = "volume_30_report"


@dataclass
class Longform100Report(BaseAsset):
    type: str = "longform_100_report"


@dataclass
class QualityRegressionReport(BaseAsset):
    type: str = "quality_regression_report"


@dataclass
class ModelJudgeResult(BaseAsset):
    type: str = "model_judge_result"


@dataclass
class ExternalProviderProofReport(BaseAsset):
    type: str = "external_provider_proof_report"


@dataclass
class ContentQualityLoopReport(BaseAsset):
    type: str = "content_quality_loop_report"


@dataclass
class HumanAnnotation(BaseAsset):
    type: str = "human_annotation"


@dataclass
class LongChainRun(BaseAsset):
    type: str = "long_chain_run"


@dataclass
class LongChainCheckpoint(BaseAsset):
    type: str = "long_chain_checkpoint"


@dataclass
class CanonStateMachineSnapshot(BaseAsset):
    type: str = "canon_state_machine_snapshot"


@dataclass
class CanonStateMachineDiffReport(BaseAsset):
    type: str = "canon_state_machine_diff_report"


@dataclass
class CanonStateMachineLedger(BaseAsset):
    type: str = "canon_state_machine_ledger"


@dataclass
class LongChainFailureReport(BaseAsset):
    type: str = "long_chain_failure_report"


@dataclass
class ChapterQualityTrend(BaseAsset):
    type: str = "chapter_quality_trend"


@dataclass
class CanonConflictTrend(BaseAsset):
    type: str = "canon_conflict_trend"


@dataclass
class StyleDriftTrend(BaseAsset):
    type: str = "style_drift_trend"


@dataclass
class ReaderFatigueTrend(BaseAsset):
    type: str = "reader_fatigue_trend"


@dataclass
class CostQualityTrend(BaseAsset):
    type: str = "cost_quality_trend"


@dataclass
class PlatformUploadPackage(BaseAsset):
    type: str = "platform_upload_package"


@dataclass
class PlatformPublishReceipt(BaseAsset):
    type: str = "platform_publish_receipt"


@dataclass
class PlatformReviewStatus(BaseAsset):
    type: str = "platform_review_status"


@dataclass
class PlatformMetricSnapshot(BaseAsset):
    type: str = "platform_metric_snapshot"


@dataclass
class PlatformCommentBatch(BaseAsset):
    type: str = "platform_comment_batch"


@dataclass
class CommentClusterReport(BaseAsset):
    type: str = "comment_cluster_report"


@dataclass
class ChapterDropoffReport(BaseAsset):
    type: str = "chapter_dropoff_report"


@dataclass
class FeedbackPlanMutationProposal(BaseAsset):
    type: str = "feedback_plan_mutation_proposal"


@dataclass
class FeedbackMutationApplicationReport(BaseAsset):
    type: str = "feedback_mutation_application_report"


@dataclass
class FeedbackMutationPatch(BaseAsset):
    type: str = "feedback_mutation_patch"


SCHEMA_CLASSES = {
    cls().type: cls
    for cls in [
        SourceDocument,
        SourcePolicy,
        SourceSyncJob,
        SourceSnapshot,
        LicenseCheckResult,
        SourceRiskReport,
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
        SourceChunk,
        KnowledgeUsageBinding,
        RuleCard,
        TemplateCard,
        KnowledgePack,
        KnowledgePackItem,
        KnowledgeUsageEvent,
        KnowledgeQualityScore,
        KnowledgeGraphSnapshot,
        KnowledgeLearningSnapshot,
        MaterialCard,
        AssetCollection,
        PlatformProfile,
        PlatformRhythmRule,
        PlatformOpeningGate,
        PlatformChapterGate,
        PlatformRetentionRisk,
        PlatformPublishAdapter,
        PlatformFeedbackBackflow,
        PlatformStrategyPack,
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
        NovelKGSnapshot,
        SemanticExtractionReport,
        KgIdentityResolution,
        CanonPatch,
        CanonDatabase,
        ChapterStatePackage,
        ChapterPatternReport,
        FactLedger,
        ArcPlan,
        ForeshadowingGraph,
        ReaderPromise,
        ReaderPromiseLedger,
        PleasurePoint,
        ChapterEconomyReport,
        ProtagonistCharmReport,
        AntagonistPressureReport,
        MobileReadingReport,
        MotifBudgetReport,
        CharacterStateLedger,
        VillainOperationPlan,
        ReaderFatigueReport,
        StyleControlPlan,
        PlatformAdapterReport,
        RewardLedger,
        ReviewScoreSystemReport,
        StyleProfile,
        StyleDecompositionReport,
        StyleBlendPreset,
        QualityStandardProfile,
        ReviewRulePack,
        WritingTemplate,
        CraftTemplate,
        LongFormMacroPlan,
        LongformRecapReport,
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
        ReviewIssue,
        LoopRun,
        LoopStep,
        LoopCheckpoint,
        LoopReport,
        RevisionTask,
        RevisionPlan,
        QualityScoreReport,
        StyleReviewReport,
        ChapterAuditReport,
        OriginalityReport,
        PublishGateReport,
        ReleasePackage,
        ProductionGovernanceReport,
        FallbackDecision,
        PublishingPlan,
        PublishingLog,
        ReaderFeedback,
        FeedbackCluster,
        FeedbackBackflowPlan,
        PlanAdjustmentProposal,
        ReviewRuleUpdateProposal,
        FeedbackKGPatch,
        FeedbackImportBatch,
        FeedbackInsight,
        ReaderSentimentReport,
        ReaderSimulationReport,
        OperationalMetricSnapshot,
        ReaderFeedbackBackflowReport,
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
        AgentTask,
        AgentRun,
        AgentCheckpoint,
        AgentEvent,
        AgentBudget,
        AgentGate,
        AgentMetric,
        AgentFailureReport,
        AgentSlaReport,
        AgentRollbackReport,
        AgentDispatchQueue,
        AgentRegistryEntry,
        AgentVersion,
        AgentCapability,
        AgentLifecycleEvent,
        AgentEvaluationBinding,
        AgentRegistrySnapshot,
        OperationTransaction,
        RollbackPlan,
        RollbackResult,
        SchedulerLease,
        TraceSpan,
        GateResult,
        ModelCallLog,
        CostLedger,
        BudgetPolicy,
        CostAlert,
        ProjectCostSnapshot,
        AgentCostSnapshot,
        ChapterCostSnapshot,
        CostQualityDashboard,
        AuditLog,
        AuditTrailReport,
        AuditExportPackage,
        ModelProfile,
        ModelRoute,
        ModelRouteResolution,
        ModelBenchmarkTask,
        ModelBenchmarkRun,
        ModelComparisonReport,
        PromptTemplate,
        PromptVersion,
        PromptRelease,
        PromptNodeBinding,
        PromptRegressionReport,
        ModelRoutingPolicy,
        EvaluationSuite,
        EvaluationCase,
        EvaluationRun,
        EvaluationResult,
        EvaluationMetric,
        EvaluationGate,
        EvaluationRegressionReport,
        EvaluationDashboardSnapshot,
        ToolDefinition,
        ToolInvocation,
        ToolPermissionPolicy,
        ApprovalRequest,
        MCPServerRegistry,
        StateEvent,
        StateSnapshot,
        StateReplay,
        StateConflictReport,
        AgentMessage,
        AgentInbox,
        AgentOutbox,
        AgentHandoff,
        AgentConversationTrace,
        MemoryRecord,
        MemorySelection,
        MemoryRetrievalReport,
        MemoryChunk,
        KnowledgeChunk,
        ArtifactEmbedding,
        ReviewMemoryChunk,
        EntityMemoryChunk,
        PgVectorSchemaPlan,
        EmbeddingJob,
        HybridRetrievalReport,
        AnalyticsEvent,
        AnalyticsSyncJob,
        AnalyticsDashboardSnapshot,
        AnalyticsMetricDefinition,
        LocalOpsDrillReport,
        LongChainAcceptanceReport,
        GenreProfile,
        SubgenreMechanic,
        GenreStrategyPack,
        GenreRiskGate,
        PlatformGenreFit,
        GenreTemplateBinding,
        StyleSample,
        StyleFingerprint,
        StyleGenerationPolicy,
        StyleReviewRule,
        StyleDriftReport,
        StyleRewriteTask,
        FantasyPowerScaleReport,
        MysteryEvidenceChainReport,
        RomanceRelationshipStateReport,
        HistoricalFactionNetworkReport,
        SciFiRuleConsistencyReport,
        HorrorRuleContaminationReport,
        QualityRubricPack,
        Opening3Report,
        Golden10Report,
        Volume30Report,
        Longform100Report,
        QualityRegressionReport,
        ModelJudgeResult,
        ExternalProviderProofReport,
        ContentQualityLoopReport,
        HumanAnnotation,
        LongChainRun,
        LongChainCheckpoint,
        CanonStateMachineSnapshot,
        CanonStateMachineDiffReport,
        CanonStateMachineLedger,
        LongChainFailureReport,
        ChapterQualityTrend,
        CanonConflictTrend,
        StyleDriftTrend,
        ReaderFatigueTrend,
        CostQualityTrend,
        PlatformUploadPackage,
        PlatformPublishReceipt,
        PlatformReviewStatus,
        PlatformMetricSnapshot,
        PlatformCommentBatch,
        CommentClusterReport,
        ChapterDropoffReport,
        FeedbackPlanMutationProposal,
        FeedbackMutationApplicationReport,
        FeedbackMutationPatch,
    ]
}


def asset_from_dict(data: dict[str, Any]) -> BaseAsset:
    cls = SCHEMA_CLASSES.get(data.get("type"), BaseAsset)
    return cls.from_dict(data)
