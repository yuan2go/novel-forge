"""Pure chapter handlers for the first PostgreSQL-authoritative slice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterNode,
)


class ChapterContentProvider(Protocol):
    provider_id: str

    def draft(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]: ...

    def review(self, *, draft: dict[str, Any]) -> dict[str, Any]: ...

    def revise(
        self,
        *,
        draft: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]: ...


class DeterministicFixtureChapterProvider:
    """Deterministic acceptance provider; never presented as a real model call."""

    provider_id = "deterministic_chapter_fixture_v1"

    def draft(
        self,
        *,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        premise = str(plan["premise"])
        return {
            "text": (
                f"{premise} The choice is made in public. "
                "The promise is kept, but its cost remains too abstract."
            ),
            "context_digest": context["context_digest"],
            "provider": self.provider_id,
        }

    def review(self, *, draft: dict[str, Any]) -> dict[str, Any]:
        return {
            "decision": "NEEDS_REVISION",
            "score": 72,
            "issues": [
                {
                    "code": "COST_NOT_CONCRETE",
                    "severity": "blocking",
                    "message": "The promised cost must become visible in the scene.",
                }
            ],
            "provider": self.provider_id,
            "draft_hash_basis": draft["text"],
        }

    def revise(
        self,
        *,
        draft: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        issue_codes = [str(item["code"]) for item in review["issues"]]
        return {
            "text": (
                f"{draft['text']} The protagonist surrenders the only safe route home "
                "before the witnesses leave, making the cost irreversible."
            ),
            "resolved_issue_codes": issue_codes,
            "provider": self.provider_id,
        }


@dataclass(frozen=True, slots=True)
class _PlanHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        chapter = int(request.command["chapter"])
        premise = str(request.command.get("premise") or "")
        title = str(request.command.get("title") or f"Chapter {chapter}")
        return _output(
            ChapterNode.PLAN,
            {
                "chapter": chapter,
                "title": title,
                "premise": premise,
                "objective": "force a consequential choice and preserve continuity",
                "beats": ["promise tested", "public choice", "visible cost"],
                "closing_hook": "the cost creates a new obligation",
                "trace_id": request.trace_id,
            },
        )


@dataclass(frozen=True, slots=True)
class _ContextHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        return _output(
            ChapterNode.CONTEXT,
            {
                "chapter": plan.content["chapter"],
                "goal": plan.content["objective"],
                "selected_asset_version_ids": [plan.asset_version_id],
                "context_digest": plan.content_hash,
                "actual_context": {
                    "premise": plan.content["premise"],
                    "beats": plan.content["beats"],
                    "copyright_boundary": "abstract project-owned fixture context only",
                },
                "forbidden_source_count": 0,
            },
        )


@dataclass(frozen=True, slots=True)
class _DraftHandler:
    provider: ChapterContentProvider

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        plan = request.require_input("chapter_plan")
        context = request.require_input("context_bundle")
        generated = self.provider.draft(plan=plan.content, context=context.content)
        return _output(
            ChapterNode.DRAFT,
            {
                "chapter": plan.content["chapter"],
                "title": plan.content["title"],
                "text": generated["text"],
                "context_bundle_id": context.asset_version_id,
                "provider_evidence": {
                    "provider_id": self.provider.provider_id,
                    "mode": "deterministic_fixture",
                    "real_model_call": False,
                },
            },
        )


@dataclass(frozen=True, slots=True)
class _ReviewHandler:
    provider: ChapterContentProvider

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        reviewed = self.provider.review(draft=draft.content)
        return _output(
            ChapterNode.REVIEW,
            {
                "chapter": draft.content["chapter"],
                "target_asset_version_id": draft.asset_version_id,
                "decision": reviewed["decision"],
                "score": reviewed["score"],
                "issues": reviewed["issues"],
                "blocking_issue_count": sum(
                    1 for item in reviewed["issues"] if item["severity"] == "blocking"
                ),
                "provider_evidence": {
                    "provider_id": self.provider.provider_id,
                    "mode": "deterministic_fixture",
                    "real_model_call": False,
                },
            },
        )


@dataclass(frozen=True, slots=True)
class _RevisionHandler:
    provider: ChapterContentProvider

    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        draft = request.require_input("draft_chapter")
        review = request.require_input("review_report")
        revised = self.provider.revise(draft=draft.content, review=review.content)
        return _output(
            ChapterNode.REVISION,
            {
                "chapter": draft.content["chapter"],
                "title": draft.content["title"],
                "text": revised["text"],
                "source_draft_version_id": draft.asset_version_id,
                "review_version_id": review.asset_version_id,
                "resolved_issue_codes": revised["resolved_issue_codes"],
                "provider_evidence": {
                    "provider_id": self.provider.provider_id,
                    "mode": "deterministic_fixture",
                    "real_model_call": False,
                },
            },
        )


@dataclass(frozen=True, slots=True)
class _CanonHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        return _output(
            ChapterNode.CANON,
            {
                "chapter": revision.content["chapter"],
                "source_asset_version_id": revision.asset_version_id,
                "facts": [
                    {
                        "subject": "protagonist",
                        "predicate": "gave_up",
                        "object": "safe_route_home",
                        "effective_chapter": revision.content["chapter"],
                    }
                ],
                "conflicts": [],
                "gate": "PASSED",
            },
        )


@dataclass(frozen=True, slots=True)
class _QualityHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        canon = request.require_input("canon_patch")
        visible_cost = "surrenders the only safe route home" in revision.content["text"]
        passed = visible_cost and canon.content["gate"] == "PASSED"
        if not passed:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "CHAPTER_QUALITY_GATE_FAILED",
                "Quality output cannot be qualified while a blocking check fails",
            )
        return _output(
            ChapterNode.QUALITY,
            {
                "chapter": revision.content["chapter"],
                "target_asset_version_id": revision.asset_version_id,
                "canon_patch_version_id": canon.asset_version_id,
                "score": 91,
                "checks": {
                    "blocking_review_issue_resolved": visible_cost,
                    "canon_conflict_free": not canon.content["conflicts"],
                },
                "gate": "PASSED",
            },
        )


@dataclass(frozen=True, slots=True)
class _ExportHandler:
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput:
        revision = request.require_input("draft_version")
        quality = request.require_input("quality_score_report")
        if quality.content["gate"] != "PASSED":
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "Export requires a passed quality gate")
        return _output(
            ChapterNode.EXPORT,
            {
                "chapter": revision.content["chapter"],
                "title": revision.content["title"],
                "rendered_text": revision.content["text"],
                "source_asset_version_id": revision.asset_version_id,
                "quality_asset_version_id": quality.asset_version_id,
                "release_status": "READY_FOR_BLOB_VERIFICATION",
                "media_type": "text/plain",
            },
        )


def build_chapter_handler_registry(
    provider: ChapterContentProvider,
) -> ChapterHandlerRegistry:
    registry = ChapterHandlerRegistry()
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
