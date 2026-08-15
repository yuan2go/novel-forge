from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    sample: bool = False
    async_task: bool = True


class StepRunRequest(BaseModel):
    step: str
    input_path: str | None = None
    async_task: bool = True


class ProjectCreateRequest(BaseModel):
    project_id: str | None = None
    workspace_id: str | None = None
    idempotency_key: str | None = None
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


class ProjectBindingAssignRequest(BaseModel):
    target_asset_version_id: str
    expected_project_version: int
    expected_project_asset_version_id: str
    expected_binding_asset_version_id: str = ""
    idempotency_key: str | None = None


class ProjectBindingRemoveRequest(BaseModel):
    expected_project_version: int
    expected_project_asset_version_id: str
    expected_binding_asset_version_id: str
    idempotency_key: str | None = None


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


class LongformExtractionRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    use_model: bool = True


class LongformAcceptanceRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None
    persist: bool = True


class LongformControlAssetRequest(BaseModel):
    asset_type: str
    title: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)


class LongformCalibrationRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    use_model: bool = True
    persist: bool = True


class ReaderPromiseLedgerRequest(BaseModel):
    draft_path: str
    chapter_plan_path: str | None = None
    workspace_path: str | None = None
    persist_issues: bool = True


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


class AuthorityOperationCancelRequest(BaseModel):
    operation_id: str
    project_id: str
    expected_version: int
    idempotency_key: str
    reason: str
    # Compatibility-only. The route deliberately uses its trusted server principal.
    actor_id: str = ""
    trace_id: str
    correlation_id: str


class AuthorityOutboxRecoveryRequest(BaseModel):
    project_id: str
    expected_attempt_count: int = Field(ge=0)
    idempotency_key: str
    reason: str
    actor_id: str = ""  # compatibility-only; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthoritySourceDocumentRegisterRequest(BaseModel):
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
    policy_version: str = "source-import-policy.v1"
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


class ProductSourceIntelligencePolicyRequest(BaseModel):
    policy_version: str = "source-intelligence-policy.v1"
    classifier_id: str = "novel-forge.source-content-classifier"
    classifier_version: str = "1.0"
    classifier_prompt_version: str = "1.0"
    classifier_schema_version: str = "source-content-classification.v1"
    classifier_capability: str = "source.content.classify"
    signal_schema_version: str = "source-profile-signals.v1"
    sample_policy_version: str = "source-profile-sampling.v1"
    routing_policy_version: str = "source-analysis-routing.v2"
    logical_document_policy_version: str = "file-logical-document.v1"
    min_confidence: float = Field(default=0.72, gt=0, le=1)
    min_margin: float = Field(default=0.12, ge=0, le=1)
    max_sample_chunks: int = Field(default=3, gt=0, le=12)
    max_sample_bytes_per_chunk: int = Field(default=6_000, gt=0, le=64_000)
    max_signal_bytes: int = Field(default=128_000, gt=0, le=1_000_000)


class ProductSourceAnalysisOverrideRequest(BaseModel):
    logical_document_scope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_type: str = Field(
        pattern=(
            r"^(WEB_NOVEL|PUBLISHED_FICTION|CLASSIC_LITERATURE|WRITING_THEORY|"
            r"PROFESSIONAL_KNOWLEDGE|HISTORY_SOCIAL_SCIENCE|BIOGRAPHY_MEMOIR|"
            r"PHILOSOPHY_ESSAY|PLATFORM_RULES)$"
        )
    )
    reason: str = Field(min_length=20, max_length=2_000)
    decision_ref: str = Field(min_length=1, max_length=500)


class ProductSourceImportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    source: ProductSourceImportSourceRequest
    policy: ProductSourceImportPolicyRequest = Field(
        default_factory=ProductSourceImportPolicyRequest
    )
    intelligence_policy: ProductSourceIntelligencePolicyRequest = Field(
        default_factory=ProductSourceIntelligencePolicyRequest
    )
    analysis_override: ProductSourceAnalysisOverrideRequest | None = None
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


class LongChainProofRunRequest(BaseModel):
    project_id: str = "local-project"
    mode: str = "deterministic_50"
    target_chapter_count: int | None = None
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    opt_in_slow_provider: bool = False
    provider_route: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    provider_runtime_guard: dict[str, Any] = Field(default_factory=dict)
    operator_approval: dict[str, Any] = Field(default_factory=dict)
    budget_cap: float = 0.0
    fixture_chapter_response: dict[str, Any] = Field(default_factory=dict)
    allow_mock_fixture: bool = False
    require_external_provider_proof: bool = False


class V7ProviderProofRequest(BaseModel):
    project_id: str = "local-project"
    draft_path: str = ""
    genre_strategy_pack_path: str = ""
    style_profile_path: str = ""
    platform_id: str = "local"
    provider_route: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    provider_runtime_guard: dict[str, Any] = Field(default_factory=dict)
    operator_approval: dict[str, Any] = Field(default_factory=dict)
    budget_cap: float = 0.0
    mode: str = "real"
    fixture_chapter_response: dict[str, Any] = Field(default_factory=dict)
    fixture_review_response: dict[str, Any] = Field(default_factory=dict)
    allow_mock_fixture: bool = False
    require_external_provider_proof: bool = True
    environment: str = "production"
    envelope: dict[str, Any] = Field(default_factory=dict)
    target_chapter_count: int = 50


class PlatformUploadPackageRequest(BaseModel):
    release_package_path: str
    platform_id: str = "manual"
    book_metadata: dict[str, Any] = Field(default_factory=dict)
    chapter_payloads: list[dict[str, Any]] = Field(default_factory=list)
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformReceiptRequest(BaseModel):
    platform_id: str
    platform_book_id: str
    platform_chapter_id: str = ""
    review_status: str = "submitted"
    receipt_raw: dict[str, Any] = Field(default_factory=dict)
    operator_note: str = ""
    upload_package_path: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformReceiptParseRequest(BaseModel):
    platform_id: str
    receipt_text: str = ""
    receipt_raw: dict[str, Any] = Field(default_factory=dict)
    operator_note: str = ""
    upload_package_path: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformAdapterGateRequest(BaseModel):
    upload_package_path: str
    platform_id: str = ""
    receipt_path: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformPublishRequest(BaseModel):
    upload_package_path: str
    platform_config: dict[str, Any] = Field(default_factory=dict)
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformMetricsImportRequest(BaseModel):
    platform_id: str
    chapter_metrics: list[dict[str, Any]]
    book_metrics: dict[str, Any] = Field(default_factory=dict)
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PlatformCommentsClusterRequest(BaseModel):
    platform_id: str
    comments: list[dict[str, Any]]
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    persist_issues: bool = False


class FeedbackMutationProposalRequest(BaseModel):
    source_feedback_paths: list[str]
    target_assets: list[dict[str, Any]]
    proposed_changes: list[dict[str, Any]]
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class FeedbackMutationResolveRequest(BaseModel):
    proposal_ref: str
    approved: bool
    actor: str = "operator"
    decision_note: str = ""
    create_application_chain: bool = True
    auto_apply_application_chain: bool = True
    auto_apply_invalidation: bool = True
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class FeedbackMutationApplyRequest(BaseModel):
    proposal_ref: str
    apply_invalidation: bool = True
    actor: str = "workflow"
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class PortfolioProjectRequest(BaseModel):
    title: str
    project_ids: list[str]
    portfolio_id: str = ""
    strategy: dict[str, Any] = Field(default_factory=dict)


class PortfolioScoreRequest(BaseModel):
    portfolio_ref: str = ""
    project_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)


class PortfolioAllocationRequest(BaseModel):
    portfolio_ref: str = ""
    project_ids: list[str] = Field(default_factory=list)
    provider_budget: float = 0.0
    max_parallel_books: int = 2
    daily_chapter_goal: int = 1


class PortfolioSimilarityRequest(BaseModel):
    portfolio_ref: str = ""
    project_ids: list[str] = Field(default_factory=list)
    medium_threshold: float = 0.35
    high_threshold: float = 0.55


class PortfolioSchedulerPlanRequest(BaseModel):
    portfolio_ref: str = ""
    allocation_ref: str = ""
    similarity_ref: str = ""
    project_ids: list[str] = Field(default_factory=list)
    provider_budget: float = 0.0
    max_parallel_books: int = 2
    daily_chapter_goal: int = 1
    environment: str = "local"
    requested_by: str = "portfolio-os"


class PortfolioLifecycleGateRequest(BaseModel):
    portfolio_ref: str = ""
    project_ids: list[str] = Field(default_factory=list)
    environment: str = "local"
    requested_by: str = "portfolio-os"


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
    book_id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)
    title_override: str = ""
    premise_override: str = ""
    explicit_asset_version_overrides: dict[str, str | list[str]] = Field(
        default_factory=dict
    )
    requested_quality_profile: str = "default"
    requested_platform_profile: str = "default"
    operator_decision: dict[str, Any] = Field(default_factory=dict)
    context_token_budget: int = Field(default=6000, ge=1)
    actor_id: str = ""  # deprecated compatibility metadata; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class AuthorityOperationControlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    actor_id: str = ""  # deprecated compatibility metadata; never trusted
    trace_id: str = ""
    correlation_id: str = ""
    expected_version: int | None = Field(default=None, ge=0)
    gate_evidence_id: str = ""


class ContentAuthorityCommandRequest(BaseModel):
    definition_name: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    input_asset_version_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)
    approval: dict[str, Any] | None = None
    actor_id: str = ""  # deprecated compatibility metadata; never trusted
    trace_id: str = ""
    correlation_id: str = ""


class BookAuthorityStartRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    input_snapshot_id: str = ""
    input_mode: Literal["RESOLVED_AUTHORITY_INPUT"] = "RESOLVED_AUTHORITY_INPUT"
    book_design_version: str = ""
    book_plan_version: str = ""
    production_profile_version: str = ""
    longform_context_versions: dict[str, Any] = Field(default_factory=dict)
    target_chapter_count: int = Field(ge=1)
    light_recap_cadence: int = Field(default=5, ge=1)
    formal_recap_cadence: int = Field(default=10, ge=1)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


class BookProductionInputResolveRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    production_profile: str = Field(min_length=1)
    expected_book_version: int = Field(ge=1)
    narrative_chapter_cursor: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


class BookAuthorityChapterRequest(BaseModel):
    chapter_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    chapter_plan_asset_version_id: str = Field(min_length=1)
    context_asset_version_ids: list[str] = Field(min_length=1)
    context_version_refs: dict[str, Any] = Field(default_factory=dict)
    context_token_budget: int = Field(default=6000, ge=1)
    preparation_report: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = ""


class BookAuthorityControlRequest(BaseModel):
    reason: str = Field(min_length=1)
    actor_id: str = ""


class BookReplanApprovalRequest(BaseModel):
    authority_type: str = Field(min_length=1)
    authority_version: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = ""


class BookReplanReevaluationRequest(BaseModel):
    source_recap_asset_version_id: str = Field(min_length=1)
    deviation_report_asset_version_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


class ExternalEffectManualResolutionRequest(BaseModel):
    operation_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: dict[str, Any]
    idempotency_key: str = Field(min_length=1)
    expected_operation_version: int = Field(ge=0)
    actor_id: str = ""
    trace_id: str = ""
    correlation_id: str = ""


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


class V1ChapterProductionWorkflowTemplateRequest(BaseModel):
    name: str = "V1 Chapter Production Workflow"
    chapter: int = 1
    run_to: str = "next_chapter_plan"
    environment: str = ""
    workspace_path: str = ""
    task_status_mode: str = "compact"
    os_envelope: dict[str, Any] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)
    provider_runtime_guard: dict[str, Any] = Field(default_factory=dict)
    require_external_provider_proof: bool = False
    selector_governance_binding_application_report_path: str = ""
    status: str = "active"


class WorkflowGovernanceDriftGateRequest(BaseModel):
    workflow_path_or_id: str = ""
    project_id: str = ""
    environment: str = ""
    mode: str = ""
    limit: int = 100
    persist_report: bool = True


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
    project_id: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


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


class AgentSchedulerRequest(BaseModel):
    project_id: str | None = None
    limit: int = 20
    dry_run: bool = False
    iterations: int = 1
    interval_seconds: float = 0.0
    stop_when_idle: bool = True
    lease_ttl_seconds: int = 300
    lease_owner: str = ""
    force_lease: bool = False
    retry_delay_seconds: int = 0


class AgentDispatchRequest(BaseModel):
    agent_run_path: str
    workflow_run_id: str = ""
    workflow_run_path: str = ""
    workflow_node_id: str = ""
    expected_output_assets: list[str] = Field(default_factory=list)
    token_used: int = 0
    cost_estimate: float = 0.0
    max_attempts: int = 3
    priority: int = 100
    project_id: str = ""
    environment: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)


class AgentDispatchRecoverRequest(BaseModel):
    queue_path: str
    reason: str = "manual recovery"


class AgentTaskCreateRequest(BaseModel):
    agent_type: str
    operation: str
    input_assets: list[str] = Field(default_factory=list)
    output_targets: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "planned"
    project_id: str = ""
    workspace_path: str = ""
    linked_loop_run_path: str = ""
    linked_context_bundle_path: str = ""
    linked_review_issue_path: str = ""
    linked_revision_task_path: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class AgentTaskFromIssueRequest(BaseModel):
    issue_ref: str
    agent_type: str = "review"
    operation: str = "fix_review_issue"
    token_budget: int = 1200
    priority: int = 40


class EditorPatchRequest(BaseModel):
    draft_path: str
    instructions: str = ""
    operations: list[dict[str, Any]] = Field(default_factory=list)
    workspace_path: str | None = None
    environment: str = ""
    os_envelope: dict[str, Any] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)


class EditorPatchApplyRequest(BaseModel):
    patch_path: str
    apply: bool = True
    change_summary: str = "editor patch applied"
    operation_ids: list[str] = Field(default_factory=list)
    operation_indexes: list[int] = Field(default_factory=list)
    environment: str = ""
    os_envelope: dict[str, Any] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)


class DraftDiffReportRequest(BaseModel):
    base_path: str
    target_path: str


class ContinuityGraphSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None


class NovelKGSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None
    limit: int = 1000
    include_content_snapshot: bool = False


class NovelKGRefreshRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None
    changed_asset_path: str | None = None
    apply_invalidation: bool = True


class NovelKGGateRequest(BaseModel):
    target_path: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None


class NovelKGSemanticExtractionRequest(BaseModel):
    target_path: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    extractor_model: dict[str, Any] = Field(default_factory=dict)
    limit: int = 500


class NovelKGIdentityResolutionRequest(BaseModel):
    snapshot_path: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    min_confidence: float = 0.7


class NovelKGIdentityAdjudicationRequest(BaseModel):
    resolution_path_or_id: str
    candidate_id: str
    decision: str = "approve"
    actor: str = "web-kg-workbench"
    note: str = ""
    apply_merge: bool = False


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


class ModelRouteRequest(BaseModel):
    task_type: str
    provider: str = "mock"
    model_name: str = "mock-model"
    fallbacks: list[dict[str, Any]] = Field(default_factory=list)
    selection_rule: str = "balanced"
    max_cost_per_run: float = 0.0
    max_latency_ms: int = 0
    status: str = "active"
    project_id: str | None = None
    workspace_path: str | None = None
    environment: str = ""
    approval_status: str = ""
    approval_id: str = ""
    approved_by: str = ""
    approval_reason: str = ""
    production_provider_allowlist: list[str] = Field(default_factory=list)
    mock_provider_test_mode: bool = False


class ModelRouteResolveRequest(BaseModel):
    task_type: str
    project_id: str | None = None
    workspace_path: str | None = None
    prompt_id: str = ""
    prompt_version: str = ""
    workflow_node_id: str = ""
    trace: dict[str, Any] = Field(default_factory=dict)
    persist: bool = True
    environment: str = ""
    allow_mock_fixture: bool = False


class ModelGatewayCallRequest(BaseModel):
    task_type: str
    operation: str
    prompt_id: str = ""
    prompt_version: str = ""
    project_id: str | None = None
    workspace_path: str | None = None
    input_assets: list[str] = Field(default_factory=list)
    output_assets: list[str] = Field(default_factory=list)
    context_bundle_path: str = ""
    provider_runtime_guard: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    status: str = "succeeded"
    trace: dict[str, Any] = Field(default_factory=dict)
    mode: str | None = None
    environment: str = ""
    allow_mock_fixture: bool = False


class PromptTemplateRequest(BaseModel):
    prompt_id: str
    task_type: str
    template: str
    variables: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    project_id: str | None = None
    workspace_path: str | None = None


class PromptReleaseRequest(BaseModel):
    prompt_id: str
    version: str
    task_type: str
    status: str = "active"
    release_note: str = ""
    project_id: str | None = None
    workspace_path: str | None = None


class PromptNodeBindingRequest(BaseModel):
    prompt_id: str
    workflow_node_id: str
    task_type: str
    version: str = ""
    status: str = "active"
    project_id: str | None = None
    workspace_path: str | None = None


class ToolPermissionPolicyRequest(BaseModel):
    tool_id: str
    agent_types: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    status: str = "active"
    project_id: str | None = None
    workspace_path: str | None = None


class MCPServerRegistryRequest(BaseModel):
    name: str
    transport: str = "stdio"
    tools: list[dict[str, Any]] = Field(default_factory=list)
    endpoint: str = ""
    status: str = "registered"
    project_id: str | None = None
    workspace_path: str | None = None


class ToolInvokeRequest(BaseModel):
    tool_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    agent_type: str = ""
    operation: str = ""
    project_id: str | None = None
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
    enforce_permissions: bool = True


class StateEventRequest(BaseModel):
    stream: str
    subject_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_version: int | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class StateSnapshotRequest(BaseModel):
    stream: str
    subject_id: str
    project_id: str | None = None
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class StateReplayRequest(BaseModel):
    stream: str
    subject_id: str
    from_version: int = 0
    project_id: str | None = None
    workspace_path: str | None = None


class StateConflictRequest(BaseModel):
    stream: str | None = None
    subject_id: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None


class AgentMessageRequest(BaseModel):
    sender_agent: str
    recipient_agent: str
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = ""
    priority: int = 5
    project_id: str | None = None
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class AgentMessageAckRequest(BaseModel):
    message_path_or_id: str
    actor_agent: str = ""
    note: str = ""


class AgentHandoffRequest(BaseModel):
    from_agent: str
    to_agent: str
    payload: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = ""
    status: str = "ready"
    project_id: str | None = None
    workspace_path: str | None = None


class AgentConversationTraceRequest(BaseModel):
    conversation_id: str
    project_id: str | None = None
    workspace_path: str | None = None


class MemoryRecordRequest(BaseModel):
    project_id: str
    level: str
    memory_type: str
    title: str
    summary: str
    content: dict[str, Any] | str = Field(default_factory=dict)
    source_artifact_ids: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    related_chapters: list[int] = Field(default_factory=list)
    priority: int = 5
    stability: str = "stable"
    status: str = "active"
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class MemoryFromAssetRequest(BaseModel):
    source_path: str
    level: str = ""
    memory_type: str = ""
    project_id: str | None = None
    workspace_path: str | None = None


class MemorySelectionRequest(BaseModel):
    target_node: str
    task_type: str
    project_id: str | None = None
    query: str = ""
    max_items: int = 12
    trace: dict[str, Any] = Field(default_factory=dict)


class MemoryRetrievalRequest(BaseModel):
    query: str
    project_id: str | None = None
    levels: list[str] = Field(default_factory=list)
    memory_types: list[str] = Field(default_factory=list)
    limit: int = 20
    persist_report: bool = True


class PgVectorSchemaPlanRequest(BaseModel):
    status: str = "planned"
    project_id: str | None = None
    workspace_path: str | None = None


class EmbeddingJobRequest(BaseModel):
    source_paths: list[str]
    backend: str = "local_hash_embedding"
    project_id: str | None = None
    workspace_path: str | None = None
    chunk_size: int = 900


class HybridRetrievalRequest(BaseModel):
    query: str
    project_id: str | None = None
    retrieval_backend: str = "hybrid"
    limit: int = 12
    levels: list[str] = Field(default_factory=list)
    persist: bool = True


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


class FeedbackBackflowPlanRequest(BaseModel):
    feedback_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None
    require_human_gate: bool = True


class FeedbackBackflowApplyRequest(BaseModel):
    plan_path: str
    confirmed: bool = False
    note: str = ""


class PublishFeedbackLoopRequest(BaseModel):
    feedback_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None
    release_package_path: str | None = None
    apply_mkaos_weight_update: bool = True
    require_human_gate: bool = True


class ReaderSimulationRequest(BaseModel):
    draft_path: str | None = None
    chapter_text: str | None = None
    project_id: str | None = None
    workspace_path: str | None = None
    platform: str = "qidian"
    chapter: int | None = None


class RealFeedbackBackflowRequest(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    workspace_path: str | None = None
    platform: str = "qidian"
    release_package_path: str | None = None
    apply_mkaos_weight_update: bool = True


class OperationalMetricSnapshotRequest(BaseModel):
    feedback_paths: list[str] = Field(default_factory=list)
    project_id: str | None = None
    workspace_path: str | None = None


class ProjectMetricSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None


class RuntimeCostSnapshotRequest(BaseModel):
    project_id: str | None = None
    workspace_path: str | None = None
    chapter: int | None = None
    persist_snapshots: bool = True


class RuntimePolicyCheckRequest(BaseModel):
    operation: str
    project_id: str | None = None
    workspace_path: str | None = None
    input_assets: list[str] = Field(default_factory=list)
    output_assets: list[str] = Field(default_factory=list)
    context_bundle_path: str = ""
    runtime_policy: dict[str, Any] = Field(default_factory=dict)
    token_used: int = 0
    cost_estimate: float = 0.0
    currency: str = "USD"
    trace: dict[str, Any] = Field(default_factory=dict)
    phase: str = "postflight"
    mode: str | None = None
    model_call_log_path: str = ""
    cost_ledger_paths: list[str] = Field(default_factory=list)
    gate_result_paths: list[str] = Field(default_factory=list)
    require_context_bundle: bool | None = None
    require_budget_policy: bool | None = None
    require_model_call_log: bool | None = None
    require_cost_ledger: bool | None = None
    required_gates: list[str] | None = None
    persist_gate_result: bool = True


class RollbackVerifyRequest(BaseModel):
    result_path_or_id: str


class RollbackPreviewRequest(BaseModel):
    transaction_path_or_id: str
    strategy: str = "supersede_outputs"
    reason: str = ""
    persist: bool = True


class RollbackApplyRequest(BaseModel):
    plan_path_or_id: str
    confirm: bool = False
    actor: str = "web-os-console"


class RollbackCoordinateRequest(BaseModel):
    transaction_paths: list[str] = Field(default_factory=list)
    strategy: str = "physical_restore"
    confirm: bool = False
    actor: str = "web-os-console"
    reason: str = ""
    project_id: str | None = None
    workspace_path: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)


class PgVectorMigrateRequest(BaseModel):
    dry_run: bool = True
    project_id: str | None = None


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
    approval_request_ref: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    environment: str = ""
    source_policy: dict[str, Any] = Field(default_factory=dict)


class ReleasePackageRequest(BaseModel):
    draft_path: str
    workspace_path: str | None = None
    publish_gate_path: str | None = None
    channel: str = "local"
    human_override: bool = False
    approval_request_ref: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    environment: str = ""
    source_policy: dict[str, Any] = Field(default_factory=dict)


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
    approval_request_ref: str = ""


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


class RevisionReworkLoopRequest(BaseModel):
    review_path: str
    draft_path: str | None = None
    issue_indexes: list[int] | None = None
    context_bundle_path: str | None = None
    workspace_path: str | None = None
    human_override: bool = False


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
    credibility: str = (
        "registered GitHub source metadata; license review required before raw access"
    )
    scope: str = ""
    project_context: str = ""
    workspace_path: str | None = None


class SourcePolicyCreateRequest(BaseModel):
    source_ref: str
    source_url: str = ""
    source_kind: str = ""
    risk_tier: str = "R2"
    allowed_pipeline: list[str] = Field(default_factory=list)
    forbidden_pipeline: list[str] = Field(default_factory=list)
    review_status: str = ""
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    allow_raw_context: bool = False


class SourceLicenseCheckRequest(BaseModel):
    source_ref: str
    license_name: str = "unknown"
    authorization: str = "unknown"
    allowed_pipeline: list[str] = Field(default_factory=list)
    forbidden_pipeline: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    checked_by: str = "operator"
    notes: str = ""
    project_id: str = ""
    workspace_path: str = ""


class SourceRiskReportRequest(BaseModel):
    source_ref: str
    risk_tier: str = ""
    source_policy_path: str = ""
    license_check_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    include_parallel_pairs: bool = False
    project_id: str = ""
    workspace_path: str = ""


class SourceSnapshotRequest(BaseModel):
    source_ref: str
    source_path: str = ""
    source_type: str = ""
    content_hash: str = ""
    line_range: dict[str, Any] = Field(default_factory=dict)
    span: dict[str, Any] = Field(default_factory=dict)
    source_policy_path: str = ""
    risk_report_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str = ""


class SourceSyncJobRequest(BaseModel):
    source_ref: str
    status: str = "planned"
    sync_mode: str = "metadata_only"
    policy_ref: str = ""
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str = ""


class SourceRefreshReportRequest(BaseModel):
    source_ref: str
    source_policy_path: str = ""
    license_check_path: str = ""
    risk_report_path: str = ""
    snapshot_path: str = ""
    sync_job_path: str = ""
    expected_content_hash: str = ""
    max_snapshot_age_days: int = 0
    connector_execution_requested: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str = ""


class SourceConnectorExecutionPlanRequest(BaseModel):
    source_ref: str
    connector_id: str = "manual_metadata_connector"
    source_refresh_report_path: str = ""
    approval_request_path: str = ""
    source_path: str = ""
    execute: bool = False
    environment: str = "local"
    evidence_refs: list[str] = Field(default_factory=list)
    project_id: str = ""
    workspace_path: str = ""


class SourceConnectorAdapterLifecycleRequest(BaseModel):
    source_ref: str
    connector_id: str = "generic_http_metadata_connector"
    execute_requested: bool = False
    environment: str = "local"
    source_policy_path: str = ""
    source_refresh_report_path: str = ""
    approval_request_path: str = ""
    endpoint: str = ""
    callback_url: str = ""
    rate_limit_policy: dict[str, Any] = Field(default_factory=dict)
    callback_policy: dict[str, Any] = Field(default_factory=dict)
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceDiffRepairPlanRequest(BaseModel):
    source_ref: str = ""
    old_snapshot_path: str
    new_snapshot_path: str
    source_refresh_report_path: str = ""
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceDiffRepairApplyRequest(BaseModel):
    repair_plan_path: str
    approval_request_path: str = ""
    confirm_apply: bool = False
    actor: str = "operator"
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceConnectorRunRequest(BaseModel):
    sync_job_path: str
    approval_request_path: str = ""
    source_path: str = ""
    allowed_roots: list[str] = Field(default_factory=list)
    previous_snapshot_path: str = ""
    create_diff_repair_plan: bool = True
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceDiffRepairRollbackRequest(BaseModel):
    rollback_plan_path: str
    approval_request_path: str = ""
    confirm_rollback: bool = False
    actor: str = "operator"
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceGovernanceApplyRequest(BaseModel):
    governance_report_path: str
    approval_request_path: str = ""
    selected_target_refs: list[str] = Field(default_factory=list)
    confirm_apply: bool = False
    actor: str = "operator"
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceGovernanceRollbackRequest(BaseModel):
    rollback_plan_path: str
    approval_request_path: str = ""
    confirm_rollback: bool = False
    actor: str = "operator"
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class SourceStaleQuarantineSweepRequest(BaseModel):
    project_id: str = ""
    workspace_path: str = ""
    categories: list[str] = Field(default_factory=list)
    max_assets: int = 1000
    include_global: bool = False
    environment: str = "local"
    evidence_refs: list[str] = Field(default_factory=list)


class SourceRetentionExpirySweepRequest(BaseModel):
    project_id: str = ""
    workspace_path: str = ""
    max_snapshot_age_days: int = 30
    max_source_derived_age_days: int = 90
    retention_policy: dict[str, Any] = Field(default_factory=dict)
    max_assets: int = 1000
    include_global: bool = False
    environment: str = "local"
    evidence_refs: list[str] = Field(default_factory=list)


class SourceContextEligibilityRequest(BaseModel):
    source_ref: str
    asset_path: str = ""
    source_policy_path: str = ""
    license_check_path: str = ""
    risk_report_path: str = ""
    risk_tier: str = ""
    intended_stage: str = "generation_context"
    request_raw_context: bool = False
    allow_raw_context: bool = False
    create_approval_request: bool = False
    environment: str = "local"
    project_id: str = ""
    workspace_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)


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
        "ProjectBindingAssignRequest": ProjectBindingAssignRequest,
        "ProjectBindingRemoveRequest": ProjectBindingRemoveRequest,
        "BatchDeconstructRequest": BatchDeconstructRequest,
        "DraftGenerateRequest": DraftGenerateRequest,
        "LongformExtractionRequest": LongformExtractionRequest,
        "LongformAcceptanceRequest": LongformAcceptanceRequest,
        "LongformControlAssetRequest": LongformControlAssetRequest,
        "LongformCalibrationRequest": LongformCalibrationRequest,
        "ReaderPromiseLedgerRequest": ReaderPromiseLedgerRequest,
        "ReviewRunRequest": ReviewRunRequest,
        "RevisionPlanRequest": RevisionPlanRequest,
        "TaskRetryRequest": TaskRetryRequest,
        "TaskCancelRequest": TaskCancelRequest,
        "AuthorityOperationCancelRequest": AuthorityOperationCancelRequest,
        "AuthorityOutboxRecoveryRequest": AuthorityOutboxRecoveryRequest,
        "AuthoritySourceDocumentRegisterRequest": AuthoritySourceDocumentRegisterRequest,
        "AuthoritySourceTransformCommitRequest": AuthoritySourceTransformCommitRequest,
        "ProductSourceImportRequest": ProductSourceImportRequest,
        "ProductSourceReprocessingApplyRequest": ProductSourceReprocessingApplyRequest,
        "AuthorityMkaosKnowledgeCandidateRequest": AuthorityMkaosKnowledgeCandidateRequest,
        "AuthorityMkaosKnowledgeApprovalRequest": AuthorityMkaosKnowledgeApprovalRequest,
        "AuthorityMkaosKnowledgePackRequest": AuthorityMkaosKnowledgePackRequest,
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
        "GenreStrategyPackRequest": GenreStrategyPackRequest,
        "GenreRiskGateRequest": GenreRiskGateRequest,
        "StyleSampleIngestRequest": StyleSampleIngestRequest,
        "StyleFingerprintRequest": StyleFingerprintRequest,
        "StyleProfileBuildRequest": StyleProfileBuildRequest,
        "StyleDriftGateRequest": StyleDriftGateRequest,
        "QualityRubricPackRequest": QualityRubricPackRequest,
        "QualitySuiteRunRequest": QualitySuiteRunRequest,
        "QualityGateRunRequest": QualityGateRunRequest,
        "ChapterEconomyRequest": ChapterEconomyRequest,
        "CharacterPressureRequest": CharacterPressureRequest,
        "MobileReadingRequest": MobileReadingRequest,
        "ProviderQualityJudgeRequest": ProviderQualityJudgeRequest,
        "CanonGraphPluginRequest": CanonGraphPluginRequest,
        "LongChainProofRunRequest": LongChainProofRunRequest,
        "V7ProviderProofRequest": V7ProviderProofRequest,
        "PlatformUploadPackageRequest": PlatformUploadPackageRequest,
        "PlatformReceiptRequest": PlatformReceiptRequest,
        "PlatformReceiptParseRequest": PlatformReceiptParseRequest,
        "PlatformAdapterGateRequest": PlatformAdapterGateRequest,
        "PlatformPublishRequest": PlatformPublishRequest,
        "PlatformMetricsImportRequest": PlatformMetricsImportRequest,
        "PlatformCommentsClusterRequest": PlatformCommentsClusterRequest,
        "FeedbackMutationProposalRequest": FeedbackMutationProposalRequest,
        "FeedbackMutationResolveRequest": FeedbackMutationResolveRequest,
        "FeedbackMutationApplyRequest": FeedbackMutationApplyRequest,
        "PortfolioProjectRequest": PortfolioProjectRequest,
        "PortfolioScoreRequest": PortfolioScoreRequest,
        "PortfolioAllocationRequest": PortfolioAllocationRequest,
        "PortfolioSimilarityRequest": PortfolioSimilarityRequest,
        "PortfolioSchedulerPlanRequest": PortfolioSchedulerPlanRequest,
        "PortfolioLifecycleGateRequest": PortfolioLifecycleGateRequest,
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
        "AuthorityChapterRunRequest": AuthorityChapterRunRequest,
        "AuthorityChapterCommandRequest": AuthorityChapterCommandRequest,
        "AuthorityOperationControlRequest": AuthorityOperationControlRequest,
        "ContentAuthorityCommandRequest": ContentAuthorityCommandRequest,
        "BookAuthorityStartRequest": BookAuthorityStartRequest,
        "BookProductionInputResolveRequest": BookProductionInputResolveRequest,
        "BookAuthorityChapterRequest": BookAuthorityChapterRequest,
        "BookAuthorityControlRequest": BookAuthorityControlRequest,
        "BookReplanApprovalRequest": BookReplanApprovalRequest,
        "BookReplanReevaluationRequest": BookReplanReevaluationRequest,
        "ExternalEffectManualResolutionRequest": ExternalEffectManualResolutionRequest,
        "ChapterProductionResumeRequest": ChapterProductionResumeRequest,
        "ChapterProductionControlRequest": ChapterProductionControlRequest,
        "ChapterProductionRecoverRequest": ChapterProductionRecoverRequest,
        "ProductionInvalidateRequest": ProductionInvalidateRequest,
        "WorkflowDefinitionCreateRequest": WorkflowDefinitionCreateRequest,
        "V1ChapterProductionWorkflowTemplateRequest": V1ChapterProductionWorkflowTemplateRequest,
        "WorkflowGovernanceDriftGateRequest": WorkflowGovernanceDriftGateRequest,
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
        "AgentSchedulerRequest": AgentSchedulerRequest,
        "AgentDispatchRequest": AgentDispatchRequest,
        "AgentDispatchRecoverRequest": AgentDispatchRecoverRequest,
        "AgentTaskCreateRequest": AgentTaskCreateRequest,
        "AgentTaskFromIssueRequest": AgentTaskFromIssueRequest,
        "EditorPatchRequest": EditorPatchRequest,
        "EditorPatchApplyRequest": EditorPatchApplyRequest,
        "DraftDiffReportRequest": DraftDiffReportRequest,
        "ContinuityGraphSnapshotRequest": ContinuityGraphSnapshotRequest,
        "NovelKGSnapshotRequest": NovelKGSnapshotRequest,
        "NovelKGRefreshRequest": NovelKGRefreshRequest,
        "NovelKGGateRequest": NovelKGGateRequest,
        "NovelKGSemanticExtractionRequest": NovelKGSemanticExtractionRequest,
        "NovelKGIdentityResolutionRequest": NovelKGIdentityResolutionRequest,
        "NovelKGIdentityAdjudicationRequest": NovelKGIdentityAdjudicationRequest,
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
        "ModelRouteRequest": ModelRouteRequest,
        "ModelRouteResolveRequest": ModelRouteResolveRequest,
        "ModelGatewayCallRequest": ModelGatewayCallRequest,
        "PromptTemplateRequest": PromptTemplateRequest,
        "PromptReleaseRequest": PromptReleaseRequest,
        "PromptNodeBindingRequest": PromptNodeBindingRequest,
        "ToolPermissionPolicyRequest": ToolPermissionPolicyRequest,
        "MCPServerRegistryRequest": MCPServerRegistryRequest,
        "ToolInvokeRequest": ToolInvokeRequest,
        "StateEventRequest": StateEventRequest,
        "StateSnapshotRequest": StateSnapshotRequest,
        "StateReplayRequest": StateReplayRequest,
        "StateConflictRequest": StateConflictRequest,
        "AgentMessageRequest": AgentMessageRequest,
        "AgentMessageAckRequest": AgentMessageAckRequest,
        "AgentHandoffRequest": AgentHandoffRequest,
        "AgentConversationTraceRequest": AgentConversationTraceRequest,
        "MemoryRecordRequest": MemoryRecordRequest,
        "MemoryFromAssetRequest": MemoryFromAssetRequest,
        "MemorySelectionRequest": MemorySelectionRequest,
        "MemoryRetrievalRequest": MemoryRetrievalRequest,
        "PgVectorSchemaPlanRequest": PgVectorSchemaPlanRequest,
        "EmbeddingJobRequest": EmbeddingJobRequest,
        "HybridRetrievalRequest": HybridRetrievalRequest,
        "BenchmarkFromGenerationRunRequest": BenchmarkFromGenerationRunRequest,
        "FeedbackImportBatchRequest": FeedbackImportBatchRequest,
        "ReaderSentimentReportRequest": ReaderSentimentReportRequest,
        "FeedbackInsightRequest": FeedbackInsightRequest,
        "FeedbackStrategyApplyRequest": FeedbackStrategyApplyRequest,
        "FeedbackBackflowPlanRequest": FeedbackBackflowPlanRequest,
        "FeedbackBackflowApplyRequest": FeedbackBackflowApplyRequest,
        "PublishFeedbackLoopRequest": PublishFeedbackLoopRequest,
        "ReaderSimulationRequest": ReaderSimulationRequest,
        "RealFeedbackBackflowRequest": RealFeedbackBackflowRequest,
        "OperationalMetricSnapshotRequest": OperationalMetricSnapshotRequest,
        "ProjectMetricSnapshotRequest": ProjectMetricSnapshotRequest,
        "RuntimeCostSnapshotRequest": RuntimeCostSnapshotRequest,
        "RuntimePolicyCheckRequest": RuntimePolicyCheckRequest,
        "RollbackPreviewRequest": RollbackPreviewRequest,
        "RollbackApplyRequest": RollbackApplyRequest,
        "RollbackVerifyRequest": RollbackVerifyRequest,
        "RollbackCoordinateRequest": RollbackCoordinateRequest,
        "PgVectorMigrateRequest": PgVectorMigrateRequest,
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
        "RevisionReworkLoopRequest": RevisionReworkLoopRequest,
        "HandoffDeconstructRequest": HandoffDeconstructRequest,
        "HandoffKnowledgeRequest": HandoffKnowledgeRequest,
        "GitHubKnowledgeHandoffRequest": GitHubKnowledgeHandoffRequest,
        "SourcePolicyCreateRequest": SourcePolicyCreateRequest,
        "SourceLicenseCheckRequest": SourceLicenseCheckRequest,
        "SourceRiskReportRequest": SourceRiskReportRequest,
        "SourceSnapshotRequest": SourceSnapshotRequest,
        "SourceSyncJobRequest": SourceSyncJobRequest,
        "SourceRefreshReportRequest": SourceRefreshReportRequest,
        "SourceConnectorExecutionPlanRequest": SourceConnectorExecutionPlanRequest,
        "SourceConnectorAdapterLifecycleRequest": SourceConnectorAdapterLifecycleRequest,
        "SourceDiffRepairPlanRequest": SourceDiffRepairPlanRequest,
        "SourceDiffRepairApplyRequest": SourceDiffRepairApplyRequest,
        "SourceConnectorRunRequest": SourceConnectorRunRequest,
        "SourceDiffRepairRollbackRequest": SourceDiffRepairRollbackRequest,
        "SourceGovernanceApplyRequest": SourceGovernanceApplyRequest,
        "SourceGovernanceRollbackRequest": SourceGovernanceRollbackRequest,
        "SourceStaleQuarantineSweepRequest": SourceStaleQuarantineSweepRequest,
        "SourceRetentionExpirySweepRequest": SourceRetentionExpirySweepRequest,
        "SourceContextEligibilityRequest": SourceContextEligibilityRequest,
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
