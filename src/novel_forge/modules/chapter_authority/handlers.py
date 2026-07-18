"""Storage-free chapter handlers for PostgreSQL authority execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.chapter_authority.contracts import (
    ChapterAuxiliaryOutput,
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.domain_handlers import (
    build_canon_extraction,
    build_canon_patch,
    build_chapter_plan,
    build_context_bundle,
    build_export_package,
    build_final_release_gate,
    build_publish_gate,
    build_quality_report,
    normalize_draft_result,
    normalize_review_result,
    normalize_rereview_result,
    normalize_revision_result,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelPort,
    ModelProviderResult,
)


class DeterministicFixtureChapterProvider:
    """Deterministic acceptance provider; never presented as a real model call."""

    provider_id = "deterministic_chapter_fixture_v1"
    external_effect_backed = False

    def invoke(
        self,
        request: ChapterHandlerRequest,
        *,
        stage: str,
        payload: dict[str, Any],
    ) -> ModelProviderResult:
        if stage == "draft":
            plan = payload["plan"]
            output = {
                "text": (
                    f"{plan['premise']} The choice is made in public. "
                    "The promise is kept, but its cost remains too abstract."
                )
            }
        elif stage == "review":
            output = {
                "decision": "NEEDS_REVISION",
                "score": 72,
                "issues": [
                    {
                        "code": "COST_NOT_CONCRETE",
                        "severity": "blocking",
                        "message": "The promised cost must become visible in the scene.",
                    }
                ],
            }
        elif stage == "revision":
            draft = payload["draft"]
            review = payload["review"]
            output = {
                "text": (
                    f"{draft['text']} The protagonist surrenders the only safe route home "
                    "before the witnesses leave, making the cost irreversible."
                ),
                "resolved_issue_codes": [str(item["code"]) for item in review["issues"]],
                "canon_assertions": [
                    {
                        "subject": "protagonist",
                        "predicate": "gave_up",
                        "object": "safe_route_home",
                        "effective_chapter": draft["chapter"],
                    }
                ],
            }
        elif stage == "rereview":
            revision = payload["revision"]
            review = payload["review"]
            output = {
                "decision": "PASSED",
                "score": 88,
                "issues": [],
                "resolved_issue_codes": [
                    str(item["code"]) for item in review.get("issues", [])
                ],
                "target_content_hash": str(revision.get("content_hash", "")),
            }
        else:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError("MODEL_EFFECT_STAGE_UNSUPPORTED", f"unsupported fixture stage: {stage}")
        return ModelProviderResult(
            output=output,
            provider_id=self.provider_id,
            model_id="deterministic-fixture-model-v1",
            prompt_version=f"chapter-{stage}-fixture-v1",
            skill_version="deterministic-fixture-v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


@dataclass(frozen=True, slots=True)
class _PlanHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        chapter = int(request.command["chapter"])
        premise = str(request.command.get("premise") or "")
        title = str(request.command.get("title") or f"Chapter {chapter}")
        return _output(
            ChapterNode.PLAN,
            build_chapter_plan(
                chapter=chapter,
                title=title,
                premise=premise,
                trace_id=request.trace_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ContextHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        candidate_metadata = {
            str(item.get("asset_version_id")): dict(item)
            for item in request.command.get("context_candidates", [])
        }
        governed_candidates = []
        frozen_candidates = [item for item in request.inputs if item.asset_type != "chapter_plan"]
        if set(candidate_metadata) != {item.asset_version_id for item in frozen_candidates}:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CONTEXT_FROZEN_INPUT_MISMATCH",
                "governed context candidates must equal frozen AssetVersion inputs",
            )
        for item in frozen_candidates:
            metadata = candidate_metadata[item.asset_version_id]
            governed_candidates.append(
                {
                    **metadata,
                    "asset_type": item.asset_type,
                    "content_digest": item.content_hash,
                    "safe_summary": str(item.content.get("safe_summary") or metadata.get("safe_summary") or ""),
                    "structured_facts": list(item.content.get("structured_facts") or metadata.get("structured_facts") or []),
                }
            )
        return _output(
            ChapterNode.CONTEXT,
            build_context_bundle(
                plan=plan.content,
                plan_asset_version_id=plan.asset_version_id,
                plan_content_hash=plan.content_hash,
                project_id=request.project_id,
                created_by_operation_id=request.operation_id,
                governed_candidates=governed_candidates,
                version_refs=dict(request.command.get("context_version_refs", {})),
                token_budget=int(request.command.get("context_token_budget", 6000)),
            ),
        )


@dataclass(frozen=True, slots=True)
class _DraftHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        context = request.require_input("context_bundle")
        generated = self.provider.invoke(
            request,
            stage="draft",
            payload={"plan": plan.content, "context": context.content},
        )
        return _output(
            ChapterNode.DRAFT,
            normalize_draft_result(
                plan=plan.content,
                context_asset_version_id=context.asset_version_id,
                result=generated.output,
                provider_evidence=_provider_evidence(generated),
            ),
        )


@dataclass(frozen=True, slots=True)
class _ReviewHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        context = request.require_input("context_bundle")
        reviewed = self.provider.invoke(
            request,
            stage="review",
            payload={"draft": draft.content, "context": context.content},
        )
        return _output(
            ChapterNode.REVIEW,
            normalize_review_result(
                draft=draft.content,
                draft_asset_version_id=draft.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _RevisionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        context = request.require_input("context_bundle")
        revised = self.provider.invoke(
            request,
            stage="revision",
            payload={"draft": draft.content, "review": review.content, "context": context.content},
        )
        return _output(
            ChapterNode.REVISION,
            normalize_revision_result(
                draft=draft.content,
                review=review.content,
                draft_asset_version_id=draft.asset_version_id,
                review_asset_version_id=review.asset_version_id,
                result=revised.output,
                provider_evidence=_provider_evidence(revised),
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ReReviewHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        revision = request.require_input("draft_version")
        context = request.require_input("context_bundle")
        reviewed = self.provider.invoke(
            request,
            stage=(
                "review"
                if getattr(self.provider, "external_effect_backed", False)
                else "rereview"
            ),
            payload={
                "draft": revision.content,
                "original_draft": draft.content,
                "review": review.content,
                "revision": revision.content,
                "context": context.content,
            },
        )
        return _output(
            ChapterNode.REREVIEW,
            normalize_rereview_result(
                draft_asset_version_id=draft.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                context_bundle_version_id=context.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
                project_id=request.project_id,
            ),
        )
@dataclass(frozen=True, slots=True)
class _CanonHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        extraction = request.require_input("canon_extraction")
        context = request.require_input("context_bundle")
        content = build_canon_patch(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            extraction=extraction.content,
            context_bundle=context.content,
        )
        snapshot_outputs = tuple(
            ChapterAuxiliaryOutput(
                asset_type=str(snapshot["asset_type"]),
                output_key=f"chapter.canon.snapshot.{snapshot['state_kind']}",
                role="state_snapshot",
                content=dict(snapshot),
                reference_asset_version_ids=tuple(
                    sorted(
                        {
                            revision.asset_version_id,
                            extraction.asset_version_id,
                            context.asset_version_id,
                            *snapshot.get("previous_asset_version_ids", []),
                        }
                    )
                ),
                evidence={
                    "authority_family": "chapter",
                    "state_kind": snapshot["state_kind"],
                    "append_only": True,
                },
            )
            for snapshot in content["snapshot_candidates"]
        )
        primary = _output(
            ChapterNode.CANON,
            content,
        )
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=snapshot_outputs,
        )


@dataclass(frozen=True, slots=True)
class _CanonExtractionHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        context = request.require_input("context_bundle")
        return _output(
            ChapterNode.CANON_EXTRACTION,
            build_canon_extraction(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                project_id=request.project_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _QualityHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        content = build_quality_report(
            revision=revision.content,
            revision_asset_version_id=revision.asset_version_id,
            canon=canon.content,
            canon_asset_version_id=canon.asset_version_id,
            review=review.content,
            review_asset_version_id=review.asset_version_id,
            project_id=request.project_id,
            context_bundle_version_id=context.asset_version_id,
            context_bundle=context.content,
        )
        primary = _output(
            ChapterNode.QUALITY,
            content,
        )
        evidence_outputs = tuple(
            ChapterAuxiliaryOutput(
                asset_type="chapter_quality_evidence",
                output_key=f"chapter.quality.evidence.{report['dimension']}",
                role="quality_evidence",
                content=dict(report),
                reference_asset_version_ids=(
                    revision.asset_version_id,
                    review.asset_version_id,
                    canon.asset_version_id,
                    context.asset_version_id,
                ),
                evidence={
                    "dimension": report["dimension"],
                    "calibration_status": report["calibration_status"],
                    "production_verified": False,
                },
            )
            for report in content["evidence_reports"]
        )
        return ChapterHandlerOutput(
            asset_type=primary.asset_type,
            output_key=primary.output_key,
            role=primary.role,
            content=primary.content,
            qualification_policy=primary.qualification_policy,
            auxiliary_outputs=evidence_outputs,
        )


@dataclass(frozen=True, slots=True)
class _PublishGateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        quality = request.require_input("quality_score_report")
        context = request.require_input("context_bundle")
        return _output(
            ChapterNode.PUBLISH_GATE,
            build_publish_gate(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                quality=quality.content,
                quality_asset_version_id=quality.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                canon=canon.content,
                canon_asset_version_id=canon.asset_version_id,
                context_bundle=context.content,
                context_bundle_version_id=context.asset_version_id,
                project_id=request.project_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ExportHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        publish_gate = request.require_input("publish_gate_report")
        return _output(
            ChapterNode.EXPORT,
            build_export_package(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                quality=publish_gate.content,
                quality_asset_version_id=publish_gate.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _FinalReleaseGateHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        export = request.require_input("release_package")
        publish_gate = request.require_input("publish_gate_report")
        quality = request.require_input("quality_score_report")
        review = request.require_input("re_review_report")
        canon = request.require_input("canon_patch")
        context = request.require_input("context_bundle")
        return _output(
            ChapterNode.FINAL_RELEASE_GATE,
            build_final_release_gate(
                project_id=request.project_id,
                export_package=export.content,
                export_asset_version_id=export.asset_version_id,
                export_blobs=export.blobs,
                publish_gate=publish_gate.content,
                publish_gate_asset_version_id=publish_gate.asset_version_id,
                quality=quality.content,
                quality_asset_version_id=quality.asset_version_id,
                review=review.content,
                review_asset_version_id=review.asset_version_id,
                canon=canon.content,
                canon_asset_version_id=canon.asset_version_id,
                context_bundle_version_id=context.asset_version_id,
            ),
        )


def build_chapter_handler_registry(
    provider: ChapterModelPort,
) -> ChapterHandlerRegistry:
    registry = ChapterHandlerRegistry(
        model_effects_required=bool(getattr(provider, "external_effect_backed", False))
    )
    registry.register(ChapterNode.PLAN, _PlanHandler())
    registry.register(ChapterNode.CONTEXT, _ContextHandler())
    registry.register(ChapterNode.DRAFT, _DraftHandler(provider))
    registry.register(ChapterNode.REVIEW, _ReviewHandler(provider))
    registry.register(ChapterNode.REVISION, _RevisionHandler(provider))
    registry.register(ChapterNode.REREVIEW, _ReReviewHandler(provider))
    registry.register(ChapterNode.CANON_EXTRACTION, _CanonExtractionHandler())
    registry.register(ChapterNode.CANON, _CanonHandler())
    registry.register(ChapterNode.QUALITY, _QualityHandler())
    registry.register(ChapterNode.PUBLISH_GATE, _PublishGateHandler())
    registry.register(ChapterNode.EXPORT, _ExportHandler())
    registry.register(ChapterNode.FINAL_RELEASE_GATE, _FinalReleaseGateHandler())
    return registry


def _output(node: ChapterNode, content: dict[str, Any]) -> ChapterHandlerOutput:
    return ChapterHandlerOutput(
        asset_type=node.asset_type,
        output_key=node.output_key,
        role="primary",
        content=content,
    )


def _provider_evidence(result: ModelProviderResult) -> dict[str, Any]:
    evidence = result.to_evidence()
    evidence.pop("result", None)
    return evidence
