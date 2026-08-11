from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    title: str
    genre: str = ""
    premise: str = ""


class ProjectOpenRequest(BaseModel):
    project_path: str


class BookStartRequest(BaseModel):
    project_id: str
    title: str = ""
    target_chapters: int = 0


class BookRunRequest(BaseModel):
    book_id: str
    max_steps: int = 1


class BookControlRequest(BaseModel):
    book_id: str
    action: str
    reason: str = ""


class AssetCreateRequest(BaseModel):
    asset_type: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str | None = None


class TaskCreateRequest(BaseModel):
    task_type: str
    title: str
    input_assets: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    project_id: str = ""
    workspace_path: str | None = None


class TaskTransitionRequest(BaseModel):
    status: str
    result_assets: list[str] = Field(default_factory=list)
    error: str = ""


class TaskRetryRequest(BaseModel):
    reason: str = ""


class TaskCancelRequest(BaseModel):
    reason: str = ""


class TaskRecoverRequest(BaseModel):
    reason: str = ""


class BatchCreateRequest(BaseModel):
    title: str
    task_ids: list[str]
    project_id: str = ""
    workspace_path: str | None = None


class BatchTransitionRequest(BaseModel):
    status: str
    error: str = ""


class BatchRetryRequest(BaseModel):
    reason: str = ""


class BatchCancelRequest(BaseModel):
    reason: str = ""


class BatchRecoverRequest(BaseModel):
    reason: str = ""


class SourceIngestRequest(BaseModel):
    source_url: str
    title: str = ""
    source_type: str = "web"
    rights_authorization: str = "unknown"
    license_name: str = ""
    copyright_note: str = ""
    allow_downstream_generation: bool = False
    project_id: str = ""
    workspace_path: str | None = None


class SourceCleanRequest(BaseModel):
    source_path: str
    workspace_path: str | None = None


class SourceDecomposeRequest(BaseModel):
    cleaned_text_path: str
    analysis_type: str = "web_fiction_business"
    workspace_path: str | None = None


class SourceConvertRequest(BaseModel):
    decomposition_path: str
    targets: list[str] = Field(default_factory=list)
    workspace_path: str | None = None
    reuse_scope: str = "project"
    human_approved: bool = False
    approval_note: str = ""


class SourceHandoffRequest(BaseModel):
    input_path: str
    analysis_type: str = "web_fiction_business"
    workspace_path: str | None = None
    purpose: str = ""


class SourceGovernanceRequest(BaseModel):
    source_path: str
    status: str
    note: str = ""


class AuthorityProjectCreateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    actor_id: str = ""
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthoritySourceDocumentRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    blob_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_uri: str = ""
    rights_authorization: str = Field(min_length=1)
    license_name: str = ""
    copyright_boundary: str = ""
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthoritySourceChunkCandidateRequest(BaseModel):
    chunk_index: int = Field(ge=0)
    blob_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    character_count: int = Field(gt=0)
    token_count: int = Field(gt=0)
    source_byte_start: int = Field(ge=0)
    source_byte_end: int = Field(gt=0)


class AuthoritySourceTransformCommitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    normalization_version: str = Field(min_length=1)
    chunking_version: str = Field(min_length=1)
    chunking_policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunks: list[AuthoritySourceChunkCandidateRequest] = Field(
        min_length=1, max_length=10_000
    )
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityDeconstructionAnalyzerRequest(BaseModel):
    analyzer_id: str = Field(min_length=2)
    analyzer_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    dimension: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    prompt_id: str = Field(min_length=2)
    prompt_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    skill_id: str = Field(min_length=2)
    skill_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    capability_id: str = Field(min_length=2)
    capability_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    provider_policy_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    aggregation_policy_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")
    recommended_scales: list[str] = Field(min_length=1, max_length=7)


class AuthorityDeconstructionScopeRequest(BaseModel):
    scale: str = Field(min_length=1)
    range_start: int = Field(ge=0)
    range_end: int = Field(ge=0)
    source_document_ids: list[str] = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=500)


class AuthorityDeconstructionEvidenceSpanRequest(BaseModel):
    source_chunk_asset_version_id: str = Field(min_length=1)
    chunk_byte_start: int = Field(ge=0)
    chunk_byte_end: int = Field(gt=0)
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class AuthorityDeconstructionObservationCommitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    execution_asset_version_id: str = Field(min_length=1)
    scope: AuthorityDeconstructionScopeRequest
    analyzer: AuthorityDeconstructionAnalyzerRequest
    observation: dict[str, Any]
    evidence_spans: list[AuthorityDeconstructionEvidenceSpanRequest] = Field(
        default_factory=list, max_length=1_000
    )
    input_observation_asset_version_ids: list[str] = Field(
        default_factory=list, max_length=1_000
    )
    evidence_class: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityReprocessingTargetRequest(BaseModel):
    scope: AuthorityDeconstructionScopeRequest
    analyzer: AuthorityDeconstructionAnalyzerRequest


class AuthoritySourceReprocessingPlanRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    targets: list[AuthorityReprocessingTargetRequest] = Field(
        min_length=1, max_length=1_000
    )
    cause_type: str = Field(min_length=1)
    source_transform_id: str = ""
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


class ProductSourceImportSourceRequest(BaseModel):
    type: str = Field(pattern=r"^github_repository$")
    repository: str = Field(min_length=1, max_length=2_000)
    ref: str = Field(default="HEAD", min_length=1, max_length=255)


class ProductSourceImportPolicyRequest(BaseModel):
    policy_version: str = "source-import-policy.v2"
    include_globs: list[str] = Field(
        default_factory=lambda: ["**/*", "*"], min_length=1, max_length=100
    )
    exclude_globs: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            "**/.git/**",
            "node_modules/**",
            "**/node_modules/**",
            "**/__pycache__/**",
        ],
        max_length=100,
    )
    extension_allowlist: list[str] = Field(
        default_factory=lambda: [
            ".txt",
            ".text",
            ".md",
            ".markdown",
            ".json",
            ".jsonl",
            ".yaml",
            ".yml",
        ],
        min_length=1,
        max_length=100,
    )
    max_file_bytes: int = Field(default=8_000_000, gt=0)
    max_repository_bytes: int = Field(default=500_000_000, gt=0)
    max_files: int = Field(default=20_000, gt=0, le=100_000)
    max_chunk_bytes: int = Field(default=12_000, gt=0, le=100_000)
    allow_symlinks: bool = False
    allow_submodules: bool = False
    allow_git_lfs: bool = False
    normalization_version: str = "source-normalization.v1"
    chunking_version: str = "source-structural-chunking.v1"
    analysis_profile: str = "writing_theory"


class ProductSourceImportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    source: ProductSourceImportSourceRequest
    policy: ProductSourceImportPolicyRequest = Field(
        default_factory=ProductSourceImportPolicyRequest
    )
    rights_authorization: str = Field(min_length=1)
    license_name: str = ""
    copyright_boundary: str = ""
    idempotency_key: str = Field(min_length=1, max_length=255)
    trace_id: str = ""
    correlation_id: str = ""


class ProductSourceReprocessingApplyRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    reprocessing_plan_asset_version_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityMkaosEvidenceSpanRequest(BaseModel):
    source_chunk_asset_version_id: str = Field(min_length=1)
    chunk_byte_start: int = Field(ge=0)
    chunk_byte_end: int = Field(gt=0)
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class AuthorityMkaosKnowledgeCandidateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    execution_asset_version_id: str = Field(min_length=1)
    candidate: dict[str, Any]
    evidence_spans: list[AuthorityMkaosEvidenceSpanRequest] = Field(
        default_factory=list, max_length=1_000
    )
    observation_asset_version_ids: list[str] = Field(
        default_factory=list, max_length=1_000
    )
    abstraction_policy_version: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityMkaosKnowledgeApprovalRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityMkaosPackSelectionRequest(BaseModel):
    knowledge_card_asset_version_id: str = Field(min_length=1)
    usage_role: str = Field(min_length=1)
    frozen_weight: float = Field(gt=0, le=100)


class AuthorityMkaosKnowledgePackRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    target_asset_version_id: str = Field(min_length=1)
    selector_policy_version: str = Field(min_length=1)
    selector_policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    selections: list[AuthorityMkaosPackSelectionRequest] = Field(
        min_length=1, max_length=500
    )
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    supersedes_pack_asset_version_id: str = ""


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


class GenreStrategyPackRequest(BaseModel):
    genre: str
    subgenre: str = ""
    project_id: str = ""
    platform_id: str = "local"
    title: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)


class GenreRiskGateRequest(BaseModel):
    strategy_pack_path: str
    target_path: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class StyleSampleIngestRequest(BaseModel):
    sample_text: str
    project_id: str = ""
    rights: dict[str, Any] = Field(default_factory=dict)
    title: str = "Style sample"
    source: str = "operator-provided"
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class StyleFingerprintRequest(BaseModel):
    sample_path: str
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class StyleProfileBuildRequest(BaseModel):
    fingerprint_path: str
    style_name: str = "Project style profile"
    scope: str = "project"
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class StyleDriftGateRequest(BaseModel):
    style_profile_path: str
    target_path: str
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class QualityRubricPackRequest(BaseModel):
    genre_id: str = ""
    platform_id: str = "local"
    style_profile_path: str = ""
    scope: str = "chapter"
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class QualitySuiteRunRequest(BaseModel):
    suite_type: str
    target_paths: list[str]
    rubric_path: str = ""
    genre_strategy_pack_path: str = ""
    style_profile_path: str = ""
    platform_id: str = "local"
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class QualityGateRunRequest(BaseModel):
    quality_report_path: str
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class ChapterEconomyRequest(BaseModel):
    draft_path: str
    reward_ledger_path: str = ""
    chapter_plan_path: str = ""
    workspace_path: str | None = None
    persist_issues: bool = True


class CharacterPressureRequest(BaseModel):
    draft_path: str
    character_state_ledger_path: str = ""
    villain_operation_plan_path: str = ""
    workspace_path: str | None = None
    persist_issues: bool = True


class MobileReadingRequest(BaseModel):
    draft_path: str
    platform_id: str = "local"
    workspace_path: str | None = None
    persist_issues: bool = True


class ProviderQualityJudgeRequest(BaseModel):
    suite_type: str = "opening_3"
    target_paths: list[str]
    rubric_path: str
    genre_strategy_pack_path: str = ""
    style_profile_path: str = ""
    platform_id: str = "local"
    provider_route: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    provider_runtime_guard: dict[str, Any] = Field(default_factory=dict)
    operator_approval: dict[str, Any] = Field(default_factory=dict)
    budget_cap: float = 0.0
    mode: str = "fixture"
    fixture_judge_response: dict[str, Any] = Field(default_factory=dict)
    allow_mock_fixture: bool = False
    require_external_provider_proof: bool = False
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class CanonGraphPluginRequest(BaseModel):
    plugin: str
    target_path: str | None = None
    artifact_text: str = ""
    project_id: str = ""
    workspace_path: str = ""
    persist_issues: bool = True
    persist_snapshot: bool = False


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
    retrieval_backend: str | None = None
    memory_levels: list[str] = Field(
        default_factory=lambda: ["L0", "L1", "L2", "L3", "L4", "L5"]
    )
    kg_context: bool = True
    quality_memory: bool = True
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
    environment: str = ""
    os_envelope: dict[str, Any] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)
    require_external_provider_proof: bool = False


class AuthorityChapterRunRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityChapterCommandRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    definition_name: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    input: dict[str, Any]
    input_assets: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""


class AuthorityChapterControlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    worker_id: str = ""


class AuthorityChapterRecoveryRequest(BaseModel):
    project_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    worker_id: str = ""
    allow_ambiguous_unknown_reconciliation: bool = False


class AuthorityBookRegisterRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    target_chapters: int = Field(gt=0)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBookInputBindRequest(BaseModel):
    project_id: str = Field(min_length=1)
    input_asset_version_ids: list[str] = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookControlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason: str = ""
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookChapterRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter: int = Field(gt=0)
    plan_asset_version_id: str = Field(min_length=1)
    context_asset_version_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookReserveRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter: int = Field(gt=0)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookAttemptLinkRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter: int = Field(gt=0)
    attempt_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookChapterAcceptRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter: int = Field(gt=0)
    attempt_id: str = Field(min_length=1)
    final_release_asset_version_id: str = Field(min_length=1)
    story_state_asset_version_id: str = ""
    canon_snapshot_asset_version_id: str = ""
    reader_outcome_asset_version_id: str = ""
    longform_recap_asset_version_id: str = ""
    chapter_outcome_asset_version_id: str = ""
    character_state_asset_version_id: str = ""
    relationship_state_asset_version_id: str = ""
    timeline_snapshot_asset_version_id: str = ""
    foreshadow_snapshot_asset_version_id: str = ""
    promise_ledger_asset_version_id: str = ""
    reward_ledger_asset_version_id: str = ""
    world_rule_snapshot_asset_version_id: str = ""
    power_state_snapshot_asset_version_id: str = ""
    plot_thread_snapshot_asset_version_id: str = ""
    resource_state_snapshot_asset_version_id: str = ""
    closure_plan_asset_version_id: str = ""
    theme_arc_asset_version_id: str = ""
    checkpoint_source: str = ""
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = Field(min_length=1)


class AuthorityBookPlanningGenerateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    parent_asset_version_id: str = Field(min_length=1)
    target_scope: dict[str, Any]
    generation_input: dict[str, Any]
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBookTickRequest(BaseModel):
    project_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBookReplanApprovalRequest(BaseModel):
    project_id: str = Field(min_length=1)
    proposal_asset_version_id: str = Field(min_length=1)
    decision: str = Field(pattern=r"^(APPROVE|REJECT)$")
    rationale: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBookProductionRegisterRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    target_chapters: int = Field(gt=0)
    creation_brief_asset_version_id: str = Field(min_length=1)
    planning_policy_asset_version_id: str = Field(min_length=1)
    reader_contract_asset_version_id: str = Field(min_length=1)
    platform_profile_asset_version_id: str = Field(min_length=1)
    source_policy_asset_version_id: str = Field(min_length=1)
    evaluation_profile_asset_version_id: str = Field(min_length=1)
    model_strategy_asset_version_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBookReplanWorkerResumeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AgentRuntimeRegisterRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_type: str = Field(min_length=1)
    capability_pack_ref: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AgentRuntimeDispatchRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    operation_ref: str = Field(min_length=1)
    capability_ref: str = Field(min_length=1)
    input_asset_version_ids: list[str] = Field(default_factory=list)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AgentRuntimeControlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    action: str = Field(pattern=r"^(pause|resume|cancel)$")
    reason: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AgentRuntimeCompleteRequest(BaseModel):
    project_id: str = Field(min_length=1)
    output_asset_version_ids: list[str] = Field(default_factory=list)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AgentRuntimeFailRequest(BaseModel):
    project_id: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    retryable: bool = False
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class CapabilityPackRegisterRequest(BaseModel):
    project_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    manifest: dict[str, Any]
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class CapabilityPackActivateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    runtime_profile: str = Field(min_length=1)
    release_channel: str = Field(min_length=1)
    release_sha: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class CapabilityPackRolloutRequest(BaseModel):
    project_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    rollout_percent: int = Field(ge=0, le=100)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class CapabilityPackSuspendRequest(BaseModel):
    project_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityObjectStoreVerifyRequest(BaseModel):
    project_id: str = Field(min_length=1)
    blob_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityOperationRecoveryRequest(BaseModel):
    project_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    worker_id: str = ""


class AuthorityOutboxReplayRequest(BaseModel):
    project_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityMaintenanceScanRequest(BaseModel):
    project_id: str = Field(min_length=1)
    scan_type: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityBackupRequest(BaseModel):
    project_id: str = Field(min_length=1)
    backup_scope: str = "project"
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityRestoreRequest(BaseModel):
    project_id: str = Field(min_length=1)
    backup_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityPublishingRequest(BaseModel):
    project_id: str = Field(min_length=1)
    platform_id: str = Field(min_length=1)
    release_asset_version_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityFeedbackIngestRequest(BaseModel):
    project_id: str = Field(min_length=1)
    platform_id: str = Field(min_length=1)
    payload: dict[str, Any]
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityEvaluationRequest(BaseModel):
    project_id: str = Field(min_length=1)
    target_asset_version_id: str = Field(min_length=1)
    evaluation_profile_id: str = Field(min_length=1)
    actor_id: str = ""  # compatibility-only; never trusted
    idempotency_key: str = Field(min_length=1)
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityCostReportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    from_ts: str = ""
    to_ts: str = ""
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""
