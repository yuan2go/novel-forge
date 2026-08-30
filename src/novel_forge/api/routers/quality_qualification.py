from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_quality_authority import (
    EvidenceLayer,
    EvidenceSeverity,
    EvidenceStatus,
    QualityCampaignManifest,
    QualityEvidenceBindingCommand,
    QualitySubjectBindingCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    BlindScope,
    EvaluatorIdentityClass,
    HumanBlindDecision,
    PreferenceChoice,
)


class CampaignAdmissionRequest(BaseModel):
    manifest: dict[str, Any]
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class LifecycleRequest(BaseModel):
    expected_version: int = Field(ge=0)


class SubjectBindingRequest(BaseModel):
    subject_id: str = Field(min_length=1)
    scope_type: str = Field(pattern="^(CHAPTER|ARC)$")
    scope_key: str = Field(min_length=1)
    chapter_start: int = Field(ge=1, le=8)
    chapter_end: int = Field(ge=1, le=8)
    arc_plan_version_ids: list[str] = Field(default_factory=list)
    canonical_asset_version_id: str = Field(min_length=1)
    canonical_content_hash: str = Field(pattern="^sha256:")
    baseline_asset_version_id: str = Field(min_length=1)
    baseline_content_hash: str = Field(pattern="^sha256:")
    chapter_plan_asset_version_id: str = ""
    narrative_realization_asset_version_id: str = ""


class EvidenceBindingRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    subject_id: str = ""
    evidence_layer: str
    evidence_type: str = Field(min_length=1)
    evidence_asset_version_id: str = Field(min_length=1)
    evidence_content_hash: str = Field(pattern="^sha256:")
    status: str
    severity: str
    source_asset_version_ids: list[str] = Field(min_length=1)
    evaluator_lineage: dict[str, Any] = Field(default_factory=dict)
    provider_lineage: dict[str, Any] = Field(default_factory=dict)


class EvaluationRequest(BaseModel):
    human_collection_closed: bool = False


class BlindDecisionRequest(BaseModel):
    decision_id: str = Field(min_length=1)
    pair_token: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    evaluator_identity_class: str
    protocol_version: str = Field(min_length=1)
    evaluation_version: str = Field(min_length=1)
    scope_type: str
    chapter_start: int = Field(ge=1, le=8)
    chapter_end: int = Field(ge=1, le=8)
    choice: str
    dimension_scores: dict[str, dict[str, int | None]]
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(
        prefix="/api/quality-qualification",
        tags=["quality-qualification"],
    )
    authority = ctx.services.quality_qualification_authority

    def principal():
        return build_trusted_principal_resolver().resolve_api_principal()

    def execute(operation):
        try:
            return operation(principal())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/campaigns")
    def admit_campaign(request: CampaignAdmissionRequest) -> dict[str, Any]:
        manifest = QualityCampaignManifest.from_mapping(request.manifest)
        return execute(
            lambda actor: authority.admit_campaign(
                manifest,
                stable_idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                principal=actor,
            )
        )

    @router.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str) -> dict[str, Any]:
        return execute(
            lambda actor: authority.require_campaign(campaign_id, principal=actor)
        )

    @router.post("/campaigns/{campaign_id}/freeze")
    def freeze(campaign_id: str, request: LifecycleRequest) -> dict[str, Any]:
        return execute(
            lambda actor: authority.freeze_campaign(
                campaign_id,
                expected_version=request.expected_version,
                principal=actor,
            )
        )

    @router.post("/campaigns/{campaign_id}/start")
    def start(campaign_id: str, request: LifecycleRequest) -> dict[str, Any]:
        return execute(
            lambda actor: authority.start_campaign(
                campaign_id,
                expected_version=request.expected_version,
                principal=actor,
            )
        )

    @router.post("/campaigns/{campaign_id}/resume")
    def resume(campaign_id: str, request: LifecycleRequest) -> dict[str, Any]:
        return execute(
            lambda actor: authority.resume_campaign(
                campaign_id,
                expected_version=request.expected_version,
                principal=actor,
            )
        )

    @router.post("/campaigns/{campaign_id}/subjects")
    def bind_subject(
        campaign_id: str, request: SubjectBindingRequest
    ) -> dict[str, Any]:
        command = QualitySubjectBindingCommand(
            campaign_id=campaign_id,
            subject_id=request.subject_id,
            scope_type=request.scope_type,
            scope_key=request.scope_key,
            chapter_start=request.chapter_start,
            chapter_end=request.chapter_end,
            arc_plan_version_ids=tuple(request.arc_plan_version_ids),
            canonical_asset_version_id=request.canonical_asset_version_id,
            canonical_content_hash=request.canonical_content_hash,
            baseline_asset_version_id=request.baseline_asset_version_id,
            baseline_content_hash=request.baseline_content_hash,
            chapter_plan_asset_version_id=request.chapter_plan_asset_version_id,
            narrative_realization_asset_version_id=(
                request.narrative_realization_asset_version_id
            ),
        )
        return execute(lambda actor: authority.bind_subject(command, principal=actor))

    @router.post("/campaigns/{campaign_id}/evidence")
    def bind_evidence(
        campaign_id: str, request: EvidenceBindingRequest
    ) -> dict[str, Any]:
        command = QualityEvidenceBindingCommand(
            campaign_id=campaign_id,
            evidence_id=request.evidence_id,
            subject_id=request.subject_id,
            evidence_layer=EvidenceLayer(request.evidence_layer),
            evidence_type=request.evidence_type,
            evidence_asset_version_id=request.evidence_asset_version_id,
            evidence_content_hash=request.evidence_content_hash,
            status=EvidenceStatus(request.status),
            severity=EvidenceSeverity(request.severity),
            source_asset_version_ids=tuple(request.source_asset_version_ids),
            evaluator_lineage=request.evaluator_lineage,
            provider_lineage=request.provider_lineage,
        )
        return execute(lambda actor: authority.bind_evidence(command, principal=actor))

    @router.post("/campaigns/{campaign_id}/evaluate")
    def evaluate(campaign_id: str, request: EvaluationRequest) -> dict[str, Any]:
        return execute(
            lambda actor: authority.evaluate_campaign(
                campaign_id,
                human_collection_closed=request.human_collection_closed,
                principal=actor,
            )
        )

    @router.get("/campaigns/{campaign_id}/blind-packs")
    def blind_pack_status(campaign_id: str) -> dict[str, Any]:
        return execute(
            lambda actor: authority.blind_pack_status(campaign_id, principal=actor)
        )

    @router.get("/blind-packs/{pack_id}")
    def reviewer_pack(
        pack_id: str,
        reviewer_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        return execute(
            lambda actor: authority.reviewer_pack(
                pack_id=pack_id,
                reviewer_id=reviewer_id,
                principal=actor,
            )
        )

    @router.post("/blind-decisions")
    def record_blind_decision(
        request: BlindDecisionRequest,
    ) -> dict[str, Any]:
        decision = HumanBlindDecision(
            decision_id=request.decision_id,
            pair_token=request.pair_token,
            reviewer_id=request.reviewer_id,
            evaluator_identity_class=EvaluatorIdentityClass(
                request.evaluator_identity_class
            ),
            protocol_version=request.protocol_version,
            evaluation_version=request.evaluation_version,
            scope_type=BlindScope(request.scope_type),
            chapter_start=request.chapter_start,
            chapter_end=request.chapter_end,
            choice=PreferenceChoice(request.choice),
            dimension_scores=request.dimension_scores,
            confidence=request.confidence,
            rationale=request.rationale,
            evidence_spans=tuple(request.evidence_spans),
        )
        return execute(
            lambda actor: authority.record_human_decision(decision, principal=actor)
        )

    return router


__all__ = ["create_router"]
