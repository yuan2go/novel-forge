from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    sample: bool = False
    async_task: bool = True


class StepRunRequest(BaseModel):
    step: str
    input_path: str | None = None
    async_task: bool = True


class ProjectCreateRequest(BaseModel):
    title: str
    series_title: str | None = None
    book_number: int | None = None
    platform_profile_path: str | None = None
    genre_market_profile_path: str | None = None
    quality_standard_profile_path: str | None = None
    style_profile_path: str | None = None
    continuity_bible_path: str | None = None


class ProjectConfigRequest(BaseModel):
    genre: str | None = None
    target_platform: str | None = None
    target_word_count: int | None = None
    update_cadence: str | None = None
    quality_threshold: int | None = None
    audience: str | None = None
    status: str | None = None
    platform_profile_id: str | None = None
    platform_profile_path: str | None = None
    genre_market_profile_id: str | None = None
    genre_market_profile_path: str | None = None
    quality_standard_profile_id: str | None = None
    quality_standard_profile_path: str | None = None
    style_profile_id: str | None = None
    style_profile_path: str | None = None
    style_blend_preset_id: str | None = None
    style_blend_preset_path: str | None = None
    continuity_bible_id: str | None = None
    continuity_bible_path: str | None = None


class ProjectDuplicateRequest(BaseModel):
    title: str | None = None
    series_title: str | None = None
    book_number: int | None = None
    copy_references: bool = True


class BatchDeconstructRequest(BaseModel):
    input_path: str
    title: str | None = None
    rights_authorization: str = "unknown"
    license_name: str = ""
    copyright_note: str = ""
    source_url: str = ""
    allow_downstream_generation: bool = False
    workspace_path: str | None = None
    analysis_mode: str = "auto"
    async_task: bool = True


class DraftGenerateRequest(BaseModel):
    chapter_plan_path: str | None = None
    workspace_path: str | None = None
    chapter: int | None = None
    update_workspace: bool = True


class ReviewRunRequest(BaseModel):
    draft_path: str | None = None
    workspace_path: str | None = None
    chapter: int | None = None
    comparison: bool = False
    update_workspace: bool = True


class RevisionPlanRequest(BaseModel):
    review_path: str | None = None
    workspace_path: str | None = None


class TaskRetryRequest(BaseModel):
    status_path: str | None = None
    run_id: str | None = None
    step: str | None = None
    workspace_path: str | None = None
    async_task: bool = False


class TaskCancelRequest(BaseModel):
    task_id: str
    terminate: bool = False
    signal: str = "SIGTERM"


class TaskControlRequest(BaseModel):
    max_concurrent_batches: int | None = None
    max_concurrent_steps: int | None = None


class DeadLetterRetryRequest(BaseModel):
    dead_letter_path: str


class BatchItemRetryRequest(BaseModel):
    item_path: str
    workspace_path: str | None = None


class BatchItemsBulkRetryRequest(BaseModel):
    item_paths: list[str]
    workspace_path: str | None = None


class BatchItemReviewRequest(BaseModel):
    item_path: str
    decision: str
    note: str | None = None


class BatchItemContinueRequest(BaseModel):
    item_path: str
    decomposition_path: str | None = None
    knowledge_path: str | None = None
    workspace_path: str | None = None


class BatchItemHandoffRequest(BaseModel):
    item_path: str
    reason: str = ""
    workspace_path: str | None = None


class AssetCollectionRequest(BaseModel):
    title: str
    purpose: str = "task_input"
    asset_paths: list[str]
    tags: list[str] = []
    workspace_path: str | None = None


class AssetEditRequest(BaseModel):
    path: str
    title: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    notes: str | None = None
    risk_level: str | None = None
    rights_authorization: str | None = None
    license_name: str | None = None
    copyright_note: str | None = None
    source_url: str | None = None
    allow_downstream_generation: bool | None = None


class AssetContentEditRequest(BaseModel):
    path: str
    content: dict[str, Any]


class AssetTypedEditRequest(BaseModel):
    path: str
    fields: dict[str, Any]


class CreativeAssetCreateRequest(BaseModel):
    asset_type: str
    title: str
    scope: str = "project"
    project_id: str | None = None
    workspace_path: str | None = None
    source: str = ""
    tags: list[str] = Field(default_factory=list)
    content: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)


class StyleDecomposeRequest(BaseModel):
    source_path: str
    workspace_path: str | None = None


class StyleReviewRequest(BaseModel):
    draft_path: str
    style_profile_path: str | None = None
    workspace_path: str | None = None


class QualityScoreRequest(BaseModel):
    target_path: str
    workspace_path: str | None = None


class AnalysisRunRequest(BaseModel):
    source_path: str
    analysis_type: str = "web_fiction_business"
    workspace_path: str | None = None


class AnalysisConvertRequest(BaseModel):
    report_path: str
    targets: list[str] = Field(default_factory=list)
    workspace_path: str | None = None
    reuse_scope: str = "project"
    human_approved: bool = False
    approval_note: str = ""


class AnalysisHandoffRequest(BaseModel):
    input_path: str
    analysis_type: str = "web_fiction_business"
    workspace_path: str | None = None
    purpose: str = ""


class ContextBuildPlanRequest(BaseModel):
    target_path: str
    query: str = ""
    top_k: int = 8
    token_budget: int = 4000
    backend: str = "auto"
    context_profile: str = "chapter_generation"
    workspace_path: str | None = None


class ContextBundleRequest(BaseModel):
    build_plan_path: str
    max_items: int | None = None
    selected_asset_paths: list[str] = Field(default_factory=list)
    disabled_asset_paths: list[str] = Field(default_factory=list)
    priority_asset_paths: list[str] = Field(default_factory=list)
    final_confirmed: bool = False


class ContextBundleDiffRequest(BaseModel):
    left_path: str
    right_path: str
    persist: bool = True


class OutlineVersionRequest(BaseModel):
    outline_path: str
    change_summary: str = "manual outline version"
    status: str = "active"


class ChapterPlanVersionRequest(BaseModel):
    chapter_plan_path: str
    change_summary: str = "manual chapter plan version"
    status: str = "active"


class DraftVersionRequest(BaseModel):
    draft_path: str
    change_summary: str = "manual draft version"
    status: str = "active"


class GenerationRunRequest(BaseModel):
    input_path: str
    context_bundle_path: str
    output_path: str | None = None
    provider: str = "local-rules"
    model: str = "local-rules"
    prompt_version: str = "prompt-v1"
    status: str = "succeeded"


class ChapterProductionRunRequest(BaseModel):
    outline_path: str
    chapter_plan_path: str | None = None
    workspace_path: str | None = None
    chapter: int | None = None
    run_to: str = "next_chapter_plan"
    async_task: bool = False


class ChapterProductionResumeRequest(BaseModel):
    run_path: str
    from_step: str | None = None
    run_to: str | None = None
    force: bool = False
    async_task: bool = False


class ChapterProductionControlRequest(BaseModel):
    run_path: str
    reason: str = ""
    terminate: bool = False
    signal: str = "SIGTERM"


class ChapterProductionRecoverRequest(BaseModel):
    run_path: str
    run_to: str | None = None
    force: bool = True
    async_task: bool = False


class ProductionInvalidateRequest(BaseModel):
    target_path: str
    max_depth: int = 4
    project_id: str | None = None
    reason: str = "upstream asset changed"
    apply: bool = True


class WorkflowDefinitionCreateRequest(BaseModel):
    name: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    entry_node_id: str
    status: str = "active"
    version: str = "0.1.0"


class WorkflowNodeCreateRequest(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    operation: str
    input_types: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    processor: dict[str, Any] = Field(default_factory=dict)
    quality_gate: dict[str, Any] = Field(default_factory=dict)


class NodeRunCreateRequest(BaseModel):
    run_id: str
    node_id: str
    node_type: str
    operation: str
    status: str = "succeeded"
    input_assets: list[str] = Field(default_factory=list)
    output_assets: list[str] = Field(default_factory=list)
    processor: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkflowExecuteRequest(BaseModel):
    workflow_path_or_id: str
    input_assets: list[str] = Field(default_factory=list)
    run_id: str | None = None
    start_node_id: str | None = None
    max_nodes: int | None = None
    dispatch_agents: bool = True
    execute_agents: bool = False
    apply_invalidation: bool = True
    workspace_path: str | None = None


class WorkflowResumeRequest(BaseModel):
    workflow_run_path_or_id: str
    resume_node_id: str | None = None
    agent_run_path: str | None = None
    output_assets: list[str] = Field(default_factory=list)
    token_used: int = 0
    cost_estimate: float = 0.0
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    human_gate: dict[str, Any] = Field(default_factory=dict)
    tool_name: str | None = None
    output_type: str | None = None
    max_nodes: int | None = None
    apply_invalidation: bool = True
    workspace_path: str | None = None
    archive_previous: bool = True


class WorkflowSchedulerRequest(BaseModel):
    project_id: str | None = None
    limit: int = 20
    max_nodes_per_resume: int = 5
    dry_run: bool = False
    async_task: bool = False
    iterations: int = 1
    interval_seconds: float = 0.0
    apply_invalidation: bool = True
    stop_when_idle: bool = True
    lease_ttl_seconds: int = 300
    lease_owner: str = ""
    force_lease: bool = False


class WorkflowRunControlRequest(BaseModel):
    workflow_run_path_or_id: str
    action: str
    reason: str = ""
    resume_node_id: str | None = None
    output_assets: list[str] = Field(default_factory=list)
    token_used: int = 0
    cost_estimate: float = 0.0
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    human_gate: dict[str, Any] = Field(default_factory=dict)
    tool_name: str | None = None
    output_type: str | None = None
    max_nodes: int | None = None
    apply_invalidation: bool = True
    workspace_path: str | None = None
    archive_previous: bool = True


class ChangeImpactRequest(BaseModel):
    target_path: str
    max_depth: int = 4
    project_id: str | None = None


class AgentContractCreateRequest(BaseModel):
    agent_key: str = ""
    skill: str = ""
    operation: str
    input_types: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    quality_gates: list[dict[str, Any]] = Field(default_factory=list)


class AgentRunCreateRequest(BaseModel):
    agent_key: str = ""
    skill: str = ""
    operation: str
    input_assets: list[str] = Field(default_factory=list)
    output_assets: list[str] = Field(default_factory=list)
    status: str = "running"
    contract_path: str | None = None
    workspace_path: str | None = None
    model_provider: str = "local"
    model_name: str = "local"
    prompt_version: str = "prompt-v1"
    token_budget: int = 0


class AgentEventCreateRequest(BaseModel):
    agent_run_path: str
    event_type: str
    status: str = "info"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunStatusRequest(BaseModel):
    agent_run_path: str
    status: str
    output_assets: list[str] = Field(default_factory=list)
    error: str = ""
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    human_gate: dict[str, Any] = Field(default_factory=dict)


class AgentSlaRequest(BaseModel):
    agent_run_path: str
    sla_seconds: int = 1800


class AgentRollbackRequest(BaseModel):
    agent_run_path: str
    rollback_strategy: str = "mark_outputs_rolled_back"
    apply: bool = False
    reason: str = ""


class AgentExecutorRunRequest(BaseModel):
    agent_run_path: str
    tool_name: str
    output_type: str | None = None
    token_used: int = 0
    cost_estimate: float = 0.0
    output_assets: list[str] = Field(default_factory=list)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    human_gate: dict[str, Any] = Field(default_factory=dict)


class EditorPatchRequest(BaseModel):
    draft_path: str
    instructions: str = ""
    operations: list[dict[str, Any]] = Field(default_factory=list)
    workspace_path: str | None = None


class EditorPatchApplyRequest(BaseModel):
    patch_path: str
    apply: bool = True
    change_summary: str = "editor patch applied"
    operation_ids: list[str] = Field(default_factory=list)
    operation_indexes: list[int] = Field(default_factory=list)


class DraftDiffReportRequest(BaseModel):
    base_path: str
    target_path: str


class ContinuityGraphSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None


class ChapterContinuityReportRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None


class CanonPatchRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None


class CanonPatchApplyRequest(BaseModel):
    patch_path: str
    confirmed: bool = False
    note: str = ""


class ModelProfileRequest(BaseModel):
    provider: str
    model_name: str
    task_types: list[str] = Field(default_factory=list)
    status: str = "candidate"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    cost_profile: dict[str, Any] = Field(default_factory=dict)


class ModelBenchmarkTaskRequest(BaseModel):
    task_type: str
    input_assets: list[str] = Field(default_factory=list)
    rubric: dict[str, Any] = Field(default_factory=dict)
    expected_output_type: str = "generate"
    prompt_template: str = ""
    workspace_path: str | None = None


class ModelBenchmarkRunRequest(BaseModel):
    task_path: str
    provider: str = "mock"
    model_name: str = "mock-model"


class ModelComparisonRequest(BaseModel):
    run_paths: list[str]
    task_type: str = ""
    workspace_path: str | None = None


class ModelBenchmarkBatchRequest(BaseModel):
    task_paths: list[str]
    candidates: list[dict[str, str]] = Field(default_factory=list)
    workspace_path: str | None = None


class ModelRoutingPolicyRequest(BaseModel):
    comparison_paths: list[str]
    status: str = "active"
    workspace_path: str | None = None


class PromptVersionRequest(BaseModel):
    prompt_id: str
    version: str
    task_type: str
    template: str
    status: str = "draft"


class PromptRegressionRequest(BaseModel):
    prompt_id: str
    baseline_version: str
    candidate_version: str
    benchmark_runs: list[str] = Field(default_factory=list)


class BenchmarkFromGenerationRunRequest(BaseModel):
    generation_run_path: str
    task_type: str = "generation"
    expected_output_type: str = "generate"
    prompt_template: str = ""


class FeedbackImportBatchRequest(BaseModel):
    input_path: str
    workspace_path: str | None = None
    source_label: str = ""
    platform: str = "manual"


class ReaderSentimentReportRequest(BaseModel):
    feedback_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None


class FeedbackInsightRequest(BaseModel):
    input_path: str | None = None


class FeedbackStrategyApplyRequest(BaseModel):
    report_path: str
    workspace_path: str | None = None


class OperationalMetricSnapshotRequest(BaseModel):
    feedback_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None


class ProjectMetricSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None


class LocalSettingsProfileRequest(BaseModel):
    title: str = "Local production settings"
    profile_id: str | None = None
    model_routing: dict[str, Any] = Field(default_factory=dict)
    storage_config: dict[str, Any] = Field(default_factory=dict)
    agent_defaults: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    workspace_path: str | None = None


class ChapterAuditRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    quality_path: str | None = None
    style_path: str | None = None
    originality_path: str | None = None


class OriginalityReportRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None


class PublishGateRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    chapter_audit_path: str | None = None
    human_override: bool = False


class ReleasePackageRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    publish_gate_path: str | None = None
    channel: str = "local"
    human_override: bool = False


class PublishingPlanRequest(BaseModel):
    release_package_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None
    channel: str = "local"
    cadence: str = "daily"
    start_date: str = ""


class PublishingLogRequest(BaseModel):
    release_package_path: str
    publishing_plan_path: str | None = None
    channel: str = "local"
    status: str = "published"
    external_url: str = ""
    rollback_note: str = ""


class PublishingAdapterRequest(BaseModel):
    release_package_path: str
    publishing_plan_path: str | None = None
    adapter_key: str = "manual_web"
    dry_run: bool = True
    external_url: str = ""


class LongFormMacroPlanRequest(BaseModel):
    workspace_path: str | None = None
    source_path: str | None = None
    target_word_count: int = 1_000_000
    volume_count: int = 5
    chapters_per_volume: int = 80


class LocalOpsDrillRequest(BaseModel):
    include_external_services: bool = False


class LongChainAcceptanceRequest(BaseModel):
    project_id: str | None = None
    chapter_count: int = 10


class DraftSaveRequest(BaseModel):
    draft_path: str
    text: str
    title: str | None = None
    status: str = "edited"
    workspace_path: str | None = None
    chapter: int | None = None


class DraftExportRequest(BaseModel):
    draft_path: str
    format: str = "markdown"


class ReviewIssueStatusRequest(BaseModel):
    review_path: str
    issue_index: int
    status: str
    note: str | None = None


class RevisionApplyRequest(BaseModel):
    revision_path: str
    draft_path: str | None = None
    workspace_path: str | None = None
    confirmed: bool = False
    review_after: bool = True


class HandoffDeconstructRequest(BaseModel):
    input_path: str
    genre: str = ""
    target_reader: str = ""
    purpose: str = ""
    workspace_path: str | None = None


class HandoffKnowledgeRequest(BaseModel):
    input_path: str
    discipline: str = ""
    credibility: str = ""
    scope: str = ""
    project_context: str = ""
    workspace_path: str | None = None


class GitHubKnowledgeHandoffRequest(BaseModel):
    repo_refs: list[str]
    discipline: str = ""
    credibility: str = "registered GitHub source metadata; license review required before raw access"
    scope: str = ""
    project_context: str = ""
    workspace_path: str | None = None


class HandoffOutputRequest(BaseModel):
    handoff_path: str
    output_path: str
    mark_completed: bool = True
    workspace_path: str | None = None
    auto_continue_batch: bool = True
    semantic_review: bool = True


class QdrantIndexRequest(BaseModel):
    recreate: bool = False
    batch_size: int = 32
    no_resume: bool = False
    force_reembed: bool = False


class QdrantSearchRequest(BaseModel):
    query: str
    category: str | None = None
    asset_type: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    tags: list[str] = []
    limit: int = 20


class MinioSyncRequest(BaseModel):
    categories: list[str] = []


class EventArchiveRequest(BaseModel):
    before: str | None = None
    keep_latest: int = 500
    confirm: bool = False


class PublishExportRequest(BaseModel):
    export_path: str
    channel: str = "local"
    note: str = ""


class HandoffAcceptanceRequest(BaseModel):
    handoff_path: str
    check_index: int
    status: str
    note: str | None = None


class HandoffRetryRequest(BaseModel):
    handoff_path: str
    reason: str = ""
    workspace_path: str | None = None


class HandoffFailRequest(BaseModel):
    handoff_path: str
    reason: str = ""


class ProjectScopeAuditRequest(BaseModel):
    project_id: str | None = None
    repair: bool = False


class LocalRestoreRequest(BaseModel):
    backup_path: str
    confirm: bool = False


def product_model_map() -> dict[str, type[BaseModel]]:
    return {
        "PipelineRunRequest": PipelineRunRequest,
        "StepRunRequest": StepRunRequest,
        "ProjectCreateRequest": ProjectCreateRequest,
        "ProjectConfigRequest": ProjectConfigRequest,
        "ProjectDuplicateRequest": ProjectDuplicateRequest,
        "BatchDeconstructRequest": BatchDeconstructRequest,
        "DraftGenerateRequest": DraftGenerateRequest,
        "ReviewRunRequest": ReviewRunRequest,
        "RevisionPlanRequest": RevisionPlanRequest,
        "TaskRetryRequest": TaskRetryRequest,
        "TaskCancelRequest": TaskCancelRequest,
        "TaskControlRequest": TaskControlRequest,
        "DeadLetterRetryRequest": DeadLetterRetryRequest,
        "BatchItemRetryRequest": BatchItemRetryRequest,
        "BatchItemsBulkRetryRequest": BatchItemsBulkRetryRequest,
        "BatchItemReviewRequest": BatchItemReviewRequest,
        "BatchItemContinueRequest": BatchItemContinueRequest,
        "BatchItemHandoffRequest": BatchItemHandoffRequest,
        "AssetCollectionRequest": AssetCollectionRequest,
        "AssetEditRequest": AssetEditRequest,
        "AssetContentEditRequest": AssetContentEditRequest,
        "AssetTypedEditRequest": AssetTypedEditRequest,
        "CreativeAssetCreateRequest": CreativeAssetCreateRequest,
        "StyleDecomposeRequest": StyleDecomposeRequest,
        "StyleReviewRequest": StyleReviewRequest,
        "QualityScoreRequest": QualityScoreRequest,
        "AnalysisRunRequest": AnalysisRunRequest,
        "AnalysisConvertRequest": AnalysisConvertRequest,
        "AnalysisHandoffRequest": AnalysisHandoffRequest,
        "ContextBuildPlanRequest": ContextBuildPlanRequest,
        "ContextBundleRequest": ContextBundleRequest,
        "ContextBundleDiffRequest": ContextBundleDiffRequest,
        "OutlineVersionRequest": OutlineVersionRequest,
        "ChapterPlanVersionRequest": ChapterPlanVersionRequest,
        "DraftVersionRequest": DraftVersionRequest,
        "GenerationRunRequest": GenerationRunRequest,
        "ChapterProductionRunRequest": ChapterProductionRunRequest,
        "ChapterProductionResumeRequest": ChapterProductionResumeRequest,
        "ChapterProductionControlRequest": ChapterProductionControlRequest,
        "ChapterProductionRecoverRequest": ChapterProductionRecoverRequest,
        "ProductionInvalidateRequest": ProductionInvalidateRequest,
        "WorkflowDefinitionCreateRequest": WorkflowDefinitionCreateRequest,
        "WorkflowNodeCreateRequest": WorkflowNodeCreateRequest,
        "NodeRunCreateRequest": NodeRunCreateRequest,
        "WorkflowExecuteRequest": WorkflowExecuteRequest,
        "WorkflowResumeRequest": WorkflowResumeRequest,
        "WorkflowSchedulerRequest": WorkflowSchedulerRequest,
        "WorkflowRunControlRequest": WorkflowRunControlRequest,
        "ChangeImpactRequest": ChangeImpactRequest,
        "AgentContractCreateRequest": AgentContractCreateRequest,
        "AgentRunCreateRequest": AgentRunCreateRequest,
        "AgentEventCreateRequest": AgentEventCreateRequest,
        "AgentRunStatusRequest": AgentRunStatusRequest,
        "AgentSlaRequest": AgentSlaRequest,
        "AgentRollbackRequest": AgentRollbackRequest,
        "AgentExecutorRunRequest": AgentExecutorRunRequest,
        "EditorPatchRequest": EditorPatchRequest,
        "EditorPatchApplyRequest": EditorPatchApplyRequest,
        "DraftDiffReportRequest": DraftDiffReportRequest,
        "ContinuityGraphSnapshotRequest": ContinuityGraphSnapshotRequest,
        "ChapterContinuityReportRequest": ChapterContinuityReportRequest,
        "CanonPatchRequest": CanonPatchRequest,
        "CanonPatchApplyRequest": CanonPatchApplyRequest,
        "ModelProfileRequest": ModelProfileRequest,
        "ModelBenchmarkTaskRequest": ModelBenchmarkTaskRequest,
        "ModelBenchmarkRunRequest": ModelBenchmarkRunRequest,
        "ModelComparisonRequest": ModelComparisonRequest,
        "ModelBenchmarkBatchRequest": ModelBenchmarkBatchRequest,
        "ModelRoutingPolicyRequest": ModelRoutingPolicyRequest,
        "PromptVersionRequest": PromptVersionRequest,
        "PromptRegressionRequest": PromptRegressionRequest,
        "BenchmarkFromGenerationRunRequest": BenchmarkFromGenerationRunRequest,
        "FeedbackImportBatchRequest": FeedbackImportBatchRequest,
        "ReaderSentimentReportRequest": ReaderSentimentReportRequest,
        "FeedbackInsightRequest": FeedbackInsightRequest,
        "FeedbackStrategyApplyRequest": FeedbackStrategyApplyRequest,
        "OperationalMetricSnapshotRequest": OperationalMetricSnapshotRequest,
        "ProjectMetricSnapshotRequest": ProjectMetricSnapshotRequest,
        "LocalSettingsProfileRequest": LocalSettingsProfileRequest,
        "ChapterAuditRequest": ChapterAuditRequest,
        "OriginalityReportRequest": OriginalityReportRequest,
        "PublishGateRequest": PublishGateRequest,
        "ReleasePackageRequest": ReleasePackageRequest,
        "PublishingPlanRequest": PublishingPlanRequest,
        "PublishingLogRequest": PublishingLogRequest,
        "PublishingAdapterRequest": PublishingAdapterRequest,
        "LongFormMacroPlanRequest": LongFormMacroPlanRequest,
        "LocalOpsDrillRequest": LocalOpsDrillRequest,
        "LongChainAcceptanceRequest": LongChainAcceptanceRequest,
        "DraftSaveRequest": DraftSaveRequest,
        "DraftExportRequest": DraftExportRequest,
        "ReviewIssueStatusRequest": ReviewIssueStatusRequest,
        "RevisionApplyRequest": RevisionApplyRequest,
        "HandoffDeconstructRequest": HandoffDeconstructRequest,
        "HandoffKnowledgeRequest": HandoffKnowledgeRequest,
        "GitHubKnowledgeHandoffRequest": GitHubKnowledgeHandoffRequest,
        "HandoffOutputRequest": HandoffOutputRequest,
        "HandoffAcceptanceRequest": HandoffAcceptanceRequest,
        "HandoffRetryRequest": HandoffRetryRequest,
        "HandoffFailRequest": HandoffFailRequest,
        "QdrantIndexRequest": QdrantIndexRequest,
        "QdrantSearchRequest": QdrantSearchRequest,
        "MinioSyncRequest": MinioSyncRequest,
        "EventArchiveRequest": EventArchiveRequest,
        "PublishExportRequest": PublishExportRequest,
        "ProjectScopeAuditRequest": ProjectScopeAuditRequest,
        "LocalRestoreRequest": LocalRestoreRequest,
    }
