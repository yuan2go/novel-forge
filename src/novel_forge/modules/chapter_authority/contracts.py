"""Typed boundary between chapter business handlers and PostgreSQL authority."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from novel_forge.modules.command_kernel.errors import KernelError


class ChapterNode(Enum):
    PLAN = (
        "plan",
        "chapter.plan.materialize",
        "chapter_plan",
        "chapter.plan",
        "chapter.plan.materialized",
    )
    CONTEXT = (
        "context",
        "chapter.context.build",
        "context_bundle",
        "chapter.context",
        "chapter.context.materialized",
    )
    DRAFT = (
        "draft",
        "chapter.draft.generate",
        "draft_chapter",
        "chapter.draft",
        "chapter.draft.materialized",
    )
    REVIEW = (
        "review",
        "chapter.review.evaluate",
        "review_report",
        "chapter.review",
        "chapter.review.materialized",
    )
    REVISION = (
        "revision",
        "chapter.revision.apply",
        "draft_version",
        "chapter.revision",
        "chapter.revision.materialized",
    )
    REREVIEW = (
        "rereview",
        "chapter.revision.review",
        "re_review_report",
        "chapter.rereview",
        "chapter.rereview.materialized",
    )
    CANON_EXTRACTION = (
        "canon_extraction",
        "chapter.canon.extract",
        "canon_extraction",
        "chapter.canon_extraction",
        "chapter.canon_extraction.materialized",
    )
    CANON = (
        "canon",
        "chapter.canon.update",
        "canon_patch",
        "chapter.canon",
        "chapter.canon.materialized",
    )
    QUALITY_STRUCTURAL = (
        "quality_structural",
        "chapter.quality.structural.evaluate",
        "chapter_quality_group_report",
        "chapter.quality.structural",
        "chapter.quality.structural.materialized",
    )
    QUALITY_COMMERCIAL = (
        "quality_commercial",
        "chapter.quality.commercial.evaluate",
        "chapter_quality_group_report",
        "chapter.quality.commercial",
        "chapter.quality.commercial.materialized",
    )
    QUALITY_SOURCE_ORIGINALITY = (
        "quality_source_originality",
        "chapter.quality.source_originality.evaluate",
        "chapter_quality_group_report",
        "chapter.quality.source_originality",
        "chapter.quality.source_originality.materialized",
    )
    QUALITY_LONGFORM = (
        "quality_longform",
        "chapter.quality.longform.evaluate",
        "chapter_quality_group_report",
        "chapter.quality.longform",
        "chapter.quality.longform.materialized",
    )
    QUALITY_PLATFORM = (
        "quality_platform",
        "chapter.quality.platform.evaluate",
        "chapter_quality_group_report",
        "chapter.quality.platform",
        "chapter.quality.platform.materialized",
    )
    QUALITY = (
        "quality",
        "chapter.quality.evaluate",
        "quality_score_report",
        "chapter.quality",
        "chapter.quality.materialized",
    )
    PUBLISH_GATE = (
        "publish_gate",
        "chapter.publishing.prepare_release",
        "publish_gate_report",
        "chapter.publish_gate",
        "chapter.publish_gate.materialized",
    )
    EXPORT = (
        "export",
        "chapter.export.render",
        "release_package",
        "chapter.export",
        "chapter.export.materialized",
    )
    FINAL_RELEASE_GATE = (
        "final_release_gate",
        "chapter.publishing.finalize_release",
        "final_release_gate_report",
        "chapter.final_release_gate",
        "chapter.final_release_gate.materialized",
    )

    def __init__(
        self,
        value: str,
        definition_name: str,
        asset_type: str,
        output_key: str,
        completion_topic: str,
    ) -> None:
        self._value_ = value
        self.definition_name = definition_name
        self.asset_type = asset_type
        self.output_key = output_key
        self.completion_topic = completion_topic

    @property
    def handler_key(self) -> str:
        return f"novel_forge.chapter_authority.{self.value}"


QUALITY_GROUP_NODES = (
    ChapterNode.QUALITY_STRUCTURAL,
    ChapterNode.QUALITY_COMMERCIAL,
    ChapterNode.QUALITY_SOURCE_ORIGINALITY,
    ChapterNode.QUALITY_LONGFORM,
    ChapterNode.QUALITY_PLATFORM,
)


@dataclass(frozen=True, slots=True)
class ChapterInputAsset:
    asset_version_id: str
    asset_type: str
    content_hash: str
    content: dict[str, Any]
    blobs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ChapterAuxiliaryOutput:
    asset_type: str
    output_key: str
    role: str
    content: dict[str, Any]
    qualification_policy: str = "chapter-authority-output-v1"
    reference_asset_version_ids: tuple[str, ...] = ()
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ChapterHandlerRequest:
    operation_id: str
    project_id: str
    workspace_id: str
    trace_id: str
    correlation_id: str
    command: dict[str, Any]
    inputs: tuple[ChapterInputAsset, ...]

    def require_input(self, asset_type: str) -> ChapterInputAsset:
        matching = [item for item in self.inputs if item.asset_type == asset_type]
        if len(matching) != 1:
            raise KernelError(
                "CHAPTER_HANDLER_INPUT_INVALID",
                f"expected exactly one {asset_type} input, found {len(matching)}",
            )
        return matching[0]


@dataclass(frozen=True, slots=True)
class ChapterHandlerOutput:
    asset_type: str
    output_key: str
    role: str
    content: dict[str, Any]
    qualification_policy: str = "chapter-authority-output-v1"
    auxiliary_outputs: tuple[ChapterAuxiliaryOutput, ...] = ()


class ChapterNodeHandler(Protocol):
    def execute(self, request: ChapterHandlerRequest) -> ChapterHandlerOutput: ...


class ChapterHandlerRegistry:
    def __init__(self, *, model_effects_required: bool = False) -> None:
        self._handlers: dict[ChapterNode, ChapterNodeHandler] = {}
        self.model_effects_required = model_effects_required

    def register(self, node: ChapterNode, handler: ChapterNodeHandler) -> None:
        if node in self._handlers:
            raise KernelError(
                "CHAPTER_HANDLER_ALREADY_REGISTERED",
                f"handler already registered for {node.value}",
            )
        self._handlers[node] = handler

    def require(self, node: ChapterNode) -> ChapterNodeHandler:
        handler = self._handlers.get(node)
        if handler is None:
            raise KernelError(
                "CHAPTER_HANDLER_NOT_REGISTERED",
                f"handler is not registered for {node.value}",
            )
        return handler

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset(node.handler_key for node in self._handlers)
