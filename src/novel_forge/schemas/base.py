from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

from novel_forge.core.ids import make_id, utc_now

T = TypeVar("T", bound="BaseAsset")

COMMON_FIELDS = [
    "id",
    "type",
    "title",
    "name",
    "source",
    "tags",
    "created_at",
    "updated_at",
    "version",
    "content",
    "metadata",
    "references",
]

CONTENT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "source_document": ["text"],
    "cleaned_text": ["text"],
    "decomposition_report": [
        "summary",
        "commercial_patterns",
        "narrative_patterns",
        "character_mechanisms",
        "conflict_patterns",
        "emotion_curve",
        "hook_patterns",
    ],
    "knowledge_card": ["principles"],
    "material_card": ["usable_patterns", "do_not_copy"],
    "topic_seed": ["logline", "reader_attraction", "differentiation"],
    "world_bible": ["setting", "rules", "conflict_system"],
    "character_card": ["role", "external_goal", "internal_need", "motivation_chain"],
    "outline": ["acts"],
    "chapter_plan": ["chapter", "objective", "beats", "hook"],
    "draft_chapter": ["chapter", "text", "copyright_boundary"],
    "review_report": ["rubric", "summary"],
    "revision_plan": ["steps", "target_score", "must_preserve"],
    "reader_feedback": ["rows"],
    "feedback_insight": ["signals", "average_rating", "next_generation_constraints"],
    "training_exercise": ["objective", "prompt", "rubric"],
    "image_prompt": ["prompt"],
    "workflow_run": ["status"],
    "task_status": ["status", "step"],
    "project_workspace_state": [
        "project_id",
        "memory",
        "chapter_states",
        "continuity_threads",
        "open_issues",
    ],
}

TOP_LEVEL_REQUIRED_FIELDS: dict[str, list[str]] = {
    "review_report": [
        "score",
        "strengths",
        "weaknesses",
        "issues",
        "risk_level",
        "revision_suggestions",
        "next_action",
    ],
}


@dataclass
class BaseAsset:
    id: str = ""
    type: str = "asset"
    title: str = ""
    name: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: str = "0.1.0"
    content: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.title and self.name:
            self.title = self.name
        if not self.name and self.title:
            self.name = self.title
        if not self.id:
            self.id = make_id(self.type, self.title or self.name or self.type)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type
        return data

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        allowed = {field.name for field in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in allowed}
        return cls(**filtered)


def validate_common_fields(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in COMMON_FIELDS:
        if key not in data:
            errors.append(f"missing common field: {key}")
    if errors:
        return errors

    if not isinstance(data.get("tags"), list):
        errors.append("tags must be a list")
    if not isinstance(data.get("content"), dict):
        errors.append("content must be an object")
    if not isinstance(data.get("metadata"), dict):
        errors.append("metadata must be an object")
    if not isinstance(data.get("references"), list):
        errors.append("references must be a list")
    if not data.get("id"):
        errors.append("id must not be empty")
    if not data.get("type"):
        errors.append("type must not be empty")
    if not data.get("title") and not data.get("name"):
        errors.append("title or name must not be empty")

    if data.get("type") == "source_document" and not data.get("source"):
        errors.append("source_document must keep original source path")
    if data.get("type") in {"decomposition_report", "knowledge_card", "material_card"}:
        boundary = data.get("metadata", {}).get("copyright_boundary", "")
        if "abstract" not in boundary.lower() and "structure" not in boundary.lower():
            errors.append("reference-derived assets must declare abstract structure copyright boundary")

    asset_type = data.get("type", "")
    content = data.get("content", {})
    if isinstance(content, dict):
        for key in CONTENT_REQUIRED_FIELDS.get(asset_type, []):
            if _is_missing(content.get(key)):
                errors.append(f"{asset_type} content missing required field: {key}")

    for key in TOP_LEVEL_REQUIRED_FIELDS.get(asset_type, []):
        if _is_missing(data.get(key)):
            errors.append(f"{asset_type} missing required field: {key}")
    if asset_type == "workflow_run" and isinstance(content, dict):
        errors.extend(_validate_workflow_run_content(content))
    if asset_type == "task_status" and isinstance(content, dict):
        errors.extend(_validate_task_status_content(content))
    if asset_type == "feedback_insight" and isinstance(content, dict):
        errors.extend(_validate_feedback_insight_content(content))
    if asset_type == "project_workspace_state" and isinstance(content, dict):
        errors.extend(_validate_project_workspace_state_content(content))
    if asset_type == "review_report" and isinstance(content, dict):
        errors.extend(_validate_review_report_content(content))

    return errors


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _validate_workflow_run_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = content.get("status", "")
    outputs = content.get("outputs")
    if status not in {"pending", "running", "completed", "failed"}:
        errors.append("workflow_run status must be pending, running, completed, or failed")
    if "outputs" not in content:
        errors.append("workflow_run content missing required field: outputs")
    elif not isinstance(outputs, list):
        errors.append("workflow_run outputs must be a list")
    elif status == "completed" and not outputs:
        errors.append("completed workflow_run must include output paths")
    if "run_log" in content and not isinstance(content.get("run_log"), list):
        errors.append("workflow_run run_log must be a list")
    if status == "failed":
        if _is_missing(content.get("error_message")):
            errors.append("failed workflow_run must include error_message")
        if _is_missing(content.get("recovery_instruction")):
            errors.append("failed workflow_run must include recovery_instruction")
        if _is_missing(content.get("run_log")):
            errors.append("failed workflow_run must include run_log")
    return errors


def _validate_task_status_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = content.get("status", "")
    if status not in {"pending", "running", "completed", "failed"}:
        errors.append("task_status status must be pending, running, completed, or failed")
    for key in ["input_paths", "output_paths"]:
        if key not in content:
            errors.append(f"task_status content missing required field: {key}")
        elif not isinstance(content.get(key), list):
            errors.append(f"task_status {key} must be a list")
    if "error_message" not in content:
        errors.append("task_status content missing required field: error_message")
    if status == "completed" and not content.get("output_paths"):
        errors.append("completed task_status must include output_paths")
    if status == "failed" and _is_missing(content.get("error_message")):
        errors.append("failed task_status must include error_message")
    return errors


def _validate_feedback_insight_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    chapter_trends = content.get("chapter_trends")
    if chapter_trends is not None:
        if not isinstance(chapter_trends, list):
            errors.append("feedback_insight chapter_trends must be a list")
        else:
            for index, trend in enumerate(chapter_trends):
                if not isinstance(trend, dict):
                    errors.append(f"feedback_insight chapter_trends[{index}] must be an object")
                    continue
                if not isinstance(trend.get("chapter"), int):
                    errors.append(f"feedback_insight chapter_trends[{index}].chapter must be an integer")
                if not isinstance(trend.get("average_rating"), (int, float)):
                    errors.append(f"feedback_insight chapter_trends[{index}].average_rating must be numeric")
    retention_risk = content.get("retention_risk")
    if retention_risk is not None:
        if not isinstance(retention_risk, dict):
            errors.append("feedback_insight retention_risk must be an object")
        elif retention_risk.get("level") not in {"low", "medium", "high", "unknown"}:
            errors.append("feedback_insight retention_risk.level must be low, medium, high, or unknown")
    sentiment_signals = content.get("sentiment_signals")
    if sentiment_signals is not None and not isinstance(sentiment_signals, dict):
        errors.append("feedback_insight sentiment_signals must be an object")
    plot_adjustment_plan = content.get("plot_adjustment_plan")
    if plot_adjustment_plan is not None:
        if not isinstance(plot_adjustment_plan, dict):
            errors.append("feedback_insight plot_adjustment_plan must be an object")
        elif not isinstance(plot_adjustment_plan.get("next_generation_constraints", []), list):
            errors.append("feedback_insight plot_adjustment_plan.next_generation_constraints must be a list")
    return errors


def _validate_project_workspace_state_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(content.get("memory"), dict):
        errors.append("project_workspace_state memory must be an object")
    chapter_states = content.get("chapter_states")
    if not isinstance(chapter_states, list):
        errors.append("project_workspace_state chapter_states must be a list")
    else:
        for index, chapter_state in enumerate(chapter_states):
            if not isinstance(chapter_state, dict):
                errors.append(f"project_workspace_state chapter_states[{index}] must be an object")
                continue
            if not isinstance(chapter_state.get("chapter"), int):
                errors.append(f"project_workspace_state chapter_states[{index}].chapter must be an integer")
            if _is_missing(chapter_state.get("status")):
                errors.append(f"project_workspace_state chapter_states[{index}].status must not be empty")
            if _is_missing(chapter_state.get("asset_id")):
                errors.append(f"project_workspace_state chapter_states[{index}].asset_id must not be empty")
    if not isinstance(content.get("continuity_threads"), dict):
        errors.append("project_workspace_state continuity_threads must be an object")
    if not isinstance(content.get("open_issues"), list):
        errors.append("project_workspace_state open_issues must be a list")
    return errors


def _validate_review_report_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    model_reviews = content.get("model_reviews")
    if model_reviews is not None and not isinstance(model_reviews, list):
        errors.append("review_report model_reviews must be a list")
    score_summary = content.get("score_summary")
    if score_summary is not None:
        if not isinstance(score_summary, dict):
            errors.append("review_report score_summary must be an object")
        else:
            for key in ["average", "minimum", "maximum", "spread"]:
                if key in score_summary and not isinstance(score_summary.get(key), (int, float)):
                    errors.append(f"review_report score_summary.{key} must be numeric")
    return errors
