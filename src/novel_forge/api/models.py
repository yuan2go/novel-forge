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


class AnalysisHandoffRequest(BaseModel):
    input_path: str
    analysis_type: str = "web_fiction_business"
    workspace_path: str | None = None
    purpose: str = ""


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
        "ChapterAuditRequest": ChapterAuditRequest,
        "OriginalityReportRequest": OriginalityReportRequest,
        "PublishGateRequest": PublishGateRequest,
        "ReleasePackageRequest": ReleasePackageRequest,
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
