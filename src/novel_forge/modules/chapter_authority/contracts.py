from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from novel_forge.modules.command_kernel.errors import KernelError


def resolve_stage_context_token_budget(
    command: dict[str, Any], stage: str, *, default: int = 6000
) -> int:

    budget = int(command.get("context_token_budget") or default)
    report = command.get("preparation_report")
    stage_budgets = (
        report.get("stage_context_token_budgets") if isinstance(report, dict) else None
    )
    if isinstance(stage_budgets, dict):
        stage_key = "quality" if stage.startswith("quality_") else stage
        budget = int(stage_budgets.get(stage_key) or budget)
    if budget < 0:
        raise KernelError(
            "CHAPTER_STAGE_CONTEXT_BUDGET_INVALID",
            "frozen Chapter stage context budget cannot be negative",
        )
    return budget


class ChapterNode(Enum):
    PLAN = (
        "plan",
        "chapter.plan.materialize",
        "chapter_plan",
        "chapter.plan",
        "chapter.plan.materialized",
    )
    EXECUTION_INTENT = (
        "execution_intent",
        "chapter.execution_intent.prepare",
        "chapter_execution_intent",
        "chapter.execution_intent",
        "chapter.execution_intent.materialized",
    )
    MEMO = (
        "memo",
        "chapter.memo.generate",
        "chapter_memo",
        "chapter.memo",
        "chapter.memo.materialized",
    )
    RETRIEVAL = (
        "retrieval",
        "chapter.context.retrieve",
        "retrieval_result",
        "chapter.retrieval",
        "chapter.retrieval.materialized",
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
    BEST_CANDIDATE = (
        "best_candidate",
        "chapter.candidate.select_best",
        "best_draft_candidate",
        "chapter.best_candidate",
        "chapter.best_candidate.materialized",
    )
    CANON_EXTRACTION = (
        "canon_extraction",
        "chapter.canon.extract",
        "canon_extraction",
        "chapter.canon_extraction",
        "chapter.canon_extraction.materialized",
    )
    CANON_PROPOSAL = (
        "canon_proposal",
        "chapter.canon.propose_changes",
        "canon_change_proposal",
        "chapter.canon_proposal",
        "chapter.canon_proposal.materialized",
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
class BeatPlan:
    beat_id: str
    ordinal: int
    function: str
    expected_reader_effect: str

    def __post_init__(self) -> None:
        if not self.beat_id or self.ordinal <= 0 or not self.function:
            raise ValueError("BeatPlan requires identity, order, and function")


@dataclass(frozen=True, slots=True)
class ScenePlan:
    scene_id: str
    scene_version: int
    chapter_plan_asset_version_id: str
    ordinal: int
    goal: str
    entry_state: str
    exit_state: str
    beats: tuple[BeatPlan, ...]

    def __post_init__(self) -> None:
        if (
            not self.scene_id
            or self.scene_version <= 0
            or not self.chapter_plan_asset_version_id
            or self.ordinal <= 0
            or not self.goal
            or not self.beats
        ):
            raise ValueError("ScenePlan requires a versioned Chapter-local identity")
        if tuple(beat.ordinal for beat in self.beats) != tuple(
            range(1, len(self.beats) + 1)
        ):
            raise ValueError("ScenePlan Beat order must be contiguous")


@dataclass(frozen=True, slots=True)
class SceneOutcome:
    scene_id: str
    scene_plan_version: int
    status: str
    actual_state_delta: tuple[dict[str, Any], ...]
    resolution_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.scene_id
            or self.scene_plan_version <= 0
            or self.status not in {"MATERIALIZED", "PARTIAL", "NOT_MATERIALIZED"}
        ):
            raise ValueError("SceneOutcome requires its ScenePlan identity and status")
        if self.status == "MATERIALIZED" and not self.resolution_evidence:
            raise ValueError("materialized SceneOutcome requires accepted evidence")


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
    attempt_id: str = ""
    fencing_token: int = 0
    worker_id: str = ""
    database_url: str = ""
    definition_version: str = ""
    source_definition_version: str = ""

    @property
    def semantic_definition_version(self) -> str:
        return self.source_definition_version if self.definition_version in {"2.2.0", "2.3.0", "2.4.0", "2.5.0"} else "3.9.0" if self.definition_version in {"3.9.1", "3.9.2", "3.9.3", "3.9.4", "3.9.5", "3.9.6", "3.9.7", "3.9.8", "3.9.9", "3.9.10", "3.9.11", "3.9.12", "3.9.13", "3.9.14", "3.9.15", "3.9.16", "3.9.17", "3.9.18"} else self.definition_version

    @property
    def work_requirements_enabled(self) -> bool:
        return self.semantic_definition_version in {"3.6.0", "3.6.0-author-input.v2", "3.7.0", "3.7.0-author-input.v2", "3.8.0", "3.8.0-author-input.v2", "3.9.0", "3.9.0-author-input.v2"}

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
    def __init__(
        self,
        *,
        model_effects_required: bool = False,
        semantic_retrieval_available: bool = False,
        agentic_retrieval_available: bool = False,
    ) -> None:
        self._handlers: dict[ChapterNode, ChapterNodeHandler] = {}
        self.model_effects_required = model_effects_required
        self.semantic_retrieval_available = semantic_retrieval_available
        self.agentic_retrieval_available = agentic_retrieval_available

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
