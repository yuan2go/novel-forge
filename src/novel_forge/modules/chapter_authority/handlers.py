"""Storage-free chapter handlers for PostgreSQL authority execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.domain_handlers import (
    build_canon_patch,
    build_chapter_plan,
    build_context_bundle,
    build_export_package,
    build_quality_report,
    normalize_draft_result,
    normalize_review_result,
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
        return _output(
            ChapterNode.CONTEXT,
            build_context_bundle(
                plan=plan.content,
                plan_asset_version_id=plan.asset_version_id,
                plan_content_hash=plan.content_hash,
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
        reviewed = self.provider.invoke(
            request,
            stage="review",
            payload={"draft": draft.content},
        )
        return _output(
            ChapterNode.REVIEW,
            normalize_review_result(
                draft=draft.content,
                draft_asset_version_id=draft.asset_version_id,
                result=reviewed.output,
                provider_evidence=_provider_evidence(reviewed),
            ),
        )


@dataclass(frozen=True, slots=True)
class _RevisionHandler:
    provider: ChapterModelPort

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        revised = self.provider.invoke(
            request,
            stage="revision",
            payload={"draft": draft.content, "review": review.content},
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
            ),
        )


@dataclass(frozen=True, slots=True)
class _CanonHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        return _output(
            ChapterNode.CANON,
            build_canon_patch(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _QualityHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        canon = request.require_input("canon_patch")
        return _output(
            ChapterNode.QUALITY,
            build_quality_report(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                canon=canon.content,
                canon_asset_version_id=canon.asset_version_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class _ExportHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        quality = request.require_input("quality_score_report")
        return _output(
            ChapterNode.EXPORT,
            build_export_package(
                revision=revision.content,
                revision_asset_version_id=revision.asset_version_id,
                quality=quality.content,
                quality_asset_version_id=quality.asset_version_id,
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
    registry.register(ChapterNode.CANON, _CanonHandler())
    registry.register(ChapterNode.QUALITY, _QualityHandler())
    registry.register(ChapterNode.EXPORT, _ExportHandler())
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
