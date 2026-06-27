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
    "common_novel_analysis_report": [
        "source_asset_id",
        "analysis_scope",
        "structure_map",
        "character_map",
        "conflict_map",
        "theme_map",
        "risk_boundary",
        "reusable_findings",
    ],
    "web_fiction_business_analysis_report": [
        "source_asset_id",
        "platform_pattern",
        "reader_promise",
        "hook_system",
        "payoff_loop",
        "pacing_model",
        "monetization_nodes",
        "abstraction_boundary",
        "reusable_assets",
    ],
    "published_fiction_analysis_report": [
        "source_asset_id",
        "craft_dimensions",
        "scene_design",
        "character_arc",
        "narrative_distance",
        "language_texture",
        "transferable_techniques",
        "do_not_copy",
    ],
    "classic_literary_analysis_report": [
        "source_asset_id",
        "deep_structure",
        "theme_system",
        "symbol_system",
        "social_relation_model",
        "fate_curve",
        "non_transferable_elements",
        "transferable_abstractions",
    ],
    "analysis_conversion_report": [
        "source_report_id",
        "source_report_type",
        "conversion_targets",
        "created_assets",
        "rejected_items",
        "reuse_scope",
        "copyright_risk",
        "abstraction_level",
    ],
    "knowledge_card": ["principles"],
    "material_card": ["usable_patterns", "do_not_copy"],
    "asset_collection": ["purpose", "asset_paths"],
    "platform_profile": [
        "platform_id",
        "platform_name",
        "business_model",
        "reader_expectation",
        "chapter_length_range",
        "update_frequency",
        "review_risks",
        "genre_fit",
        "style_tendency",
    ],
    "genre_market_profile": [
        "genre",
        "platform_id",
        "reader_promise",
        "common_hooks",
        "common_conflicts",
        "fatigue_points",
        "differentiation_axes",
        "chapter_rhythm_template",
    ],
    "topic_seed": ["logline", "reader_attraction", "differentiation"],
    "topic_fit_report": ["topic_seed_id", "platform_id", "genre", "scores", "recommendation", "must_adjust"],
    "world_bible": ["setting", "rules", "conflict_system"],
    "character_card": ["role", "external_goal", "internal_need", "motivation_chain"],
    "continuity_bible": ["project_id", "worldview_rules", "timeline", "entities", "open_threads", "constraints"],
    "foreshadowing_thread": ["thread_id", "setup", "payoff_plan", "status", "related_chapters"],
    "power_scale_rule": ["scale_id", "levels", "constraints", "violation_checks"],
    "style_profile": [
        "style_id",
        "name",
        "scope",
        "source_boundary",
        "language_parameters",
        "narrative_parameters",
        "emotion_parameters",
        "forbidden_patterns",
    ],
    "style_decomposition_report": [
        "source_asset_id",
        "extract_level",
        "style_features",
        "usable_parameters",
        "do_not_copy",
        "risk_level",
    ],
    "style_blend_preset": ["name", "components", "conflict_resolution"],
    "quality_standard_profile": ["standard_id", "name", "dimensions", "hard_gates"],
    "review_rule_pack": ["rule_pack_id", "name", "dimensions", "checks", "severity_policy"],
    "quality_score_report": ["target_asset_id", "standard_id", "overall_score", "scores", "gate_results", "recommendation"],
    "style_review_report": [
        "target_draft_id",
        "expected_style_profile_id",
        "style_match_score",
        "drift_points",
        "ai_taste_points",
        "rewrite_suggestions",
        "copyright_style_risk",
    ],
    "chapter_audit_report": [
        "target_asset_id",
        "dimension_scores",
        "issues",
        "gate_results",
        "linked_reports",
        "recommendation",
    ],
    "originality_report": [
        "target_asset_id",
        "source_asset_ids",
        "similarity_checks",
        "forbidden_element_hits",
        "plot_skeleton_risk",
        "character_setup_risk",
        "style_expression_risk",
        "risk_level",
        "recommendation",
        "human_gate_required",
    ],
    "publish_gate_report": [
        "target_asset_id",
        "gates",
        "decision",
        "blocking_issues",
        "required_reports",
        "human_override",
    ],
    "release_package": [
        "target_asset_id",
        "publish_gate_report_id",
        "title_candidates",
        "summary",
        "tags",
        "channel",
        "status",
    ],
    "writing_template": ["template_id", "name", "template_kind", "structure", "usage_constraints", "anti_copy_rules"],
    "craft_template": ["template_id", "name", "craft_domain", "pattern", "use_cases", "risks"],
    "outline": ["acts"],
    "chapter_plan": ["chapter", "objective", "beats", "hook"],
    "draft_chapter": ["chapter", "text", "copyright_boundary"],
    "review_report": ["rubric", "summary"],
    "revision_plan": ["steps", "target_score", "must_preserve"],
    "reader_feedback": ["rows"],
    "feedback_insight": ["signals", "average_rating", "next_generation_constraints"],
    "training_exercise": ["objective", "prompt", "rubric"],
    "image_prompt": ["prompt"],
    "claude_code_handoff": [
        "operation",
        "runtime",
        "runtime_model",
        "skill",
        "status",
        "input_files",
        "expected_output_type",
        "expected_output_dir",
        "instructions",
        "acceptance_checks",
    ],
    "workflow_run": ["status"],
    "task_status": ["status", "step"],
    "task_dead_letter": ["task_name", "task_id", "error_message", "payload"],
    "batch_task_item": ["batch_id", "item_index", "source_path", "status"],
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

_REFERENCE_DERIVED_ASSET_TYPES = {
    "decomposition_report",
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "analysis_conversion_report",
    "knowledge_card",
    "material_card",
    "style_decomposition_report",
    "style_profile",
    "style_blend_preset",
    "writing_template",
    "craft_template",
}

_ANALYSIS_ASSET_TYPES = {
    "common_novel_analysis_report",
    "web_fiction_business_analysis_report",
    "published_fiction_analysis_report",
    "classic_literary_analysis_report",
    "analysis_conversion_report",
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
    if data.get("type") == "source_document":
        errors.extend(_validate_source_rights(data.get("metadata", {})))
    if data.get("type") in _REFERENCE_DERIVED_ASSET_TYPES:
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
    if asset_type == "claude_code_handoff" and isinstance(content, dict):
        errors.extend(_validate_claude_code_handoff_content(content))
    if asset_type == "task_status" and isinstance(content, dict):
        errors.extend(_validate_task_status_content(content))
    if asset_type == "task_dead_letter" and isinstance(content, dict):
        errors.extend(_validate_task_dead_letter_content(content))
    if asset_type == "batch_task_item" and isinstance(content, dict):
        errors.extend(_validate_batch_task_item_content(content))
    if asset_type == "feedback_insight" and isinstance(content, dict):
        errors.extend(_validate_feedback_insight_content(content))
    if asset_type == "project_workspace_state" and isinstance(content, dict):
        errors.extend(_validate_project_workspace_state_content(content))
    if asset_type == "review_report" and isinstance(content, dict):
        errors.extend(_validate_review_report_content(content))
    if asset_type == "platform_profile" and isinstance(content, dict):
        errors.extend(_validate_platform_profile_content(content))
    if asset_type == "topic_fit_report" and isinstance(content, dict):
        errors.extend(_validate_topic_fit_report_content(content))
    if asset_type in {"quality_standard_profile", "review_rule_pack"} and isinstance(content, dict):
        errors.extend(_validate_quality_dimensions_content(asset_type, content))
    if asset_type == "quality_score_report" and isinstance(content, dict):
        errors.extend(_validate_quality_score_report_content(content))
    if asset_type in {"style_profile", "style_decomposition_report", "style_blend_preset", "style_review_report"} and isinstance(content, dict):
        errors.extend(_validate_style_asset_content(asset_type, content, data.get("metadata", {})))
    if asset_type in {"continuity_bible", "foreshadowing_thread", "power_scale_rule"} and isinstance(content, dict):
        errors.extend(_validate_continuity_asset_content(asset_type, content))
    if asset_type in {"chapter_audit_report", "originality_report", "publish_gate_report", "release_package"} and isinstance(content, dict):
        errors.extend(_validate_release_gate_content(asset_type, content))
    if asset_type in _ANALYSIS_ASSET_TYPES and isinstance(content, dict):
        errors.extend(_validate_analysis_asset_content(asset_type, content, data.get("metadata", {})))

    return errors


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
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


def _validate_claude_code_handoff_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = content.get("status", "")
    if status not in {"pending", "in_progress", "completed", "failed", "superseded"}:
        errors.append("claude_code_handoff status must be pending, in_progress, completed, failed, or superseded")
    if content.get("runtime") != "claude-code":
        errors.append("claude_code_handoff runtime must be claude-code")
    if _is_missing(content.get("runtime_model")):
        errors.append("claude_code_handoff runtime_model must not be empty")
    if not isinstance(content.get("input_files"), list):
        errors.append("claude_code_handoff input_files must be a list")
    else:
        for index, item in enumerate(content.get("input_files", [])):
            if not isinstance(item, dict):
                errors.append(f"claude_code_handoff input_files[{index}] must be an object")
                continue
            if _is_missing(item.get("path")):
                errors.append(f"claude_code_handoff input_files[{index}].path must not be empty")
            if _is_missing(item.get("role")):
                errors.append(f"claude_code_handoff input_files[{index}].role must not be empty")
    for key in ["instructions", "acceptance_checks"]:
        value = content.get(key)
        if not isinstance(value, list):
            errors.append(f"claude_code_handoff {key} must be a list")
        elif not value:
            errors.append(f"claude_code_handoff {key} must not be empty")
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


def _validate_task_dead_letter_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if _is_missing(content.get("task_name")):
        errors.append("task_dead_letter task_name must not be empty")
    if _is_missing(content.get("task_id")):
        errors.append("task_dead_letter task_id must not be empty")
    if _is_missing(content.get("error_message")):
        errors.append("task_dead_letter error_message must not be empty")
    if not isinstance(content.get("payload"), dict):
        errors.append("task_dead_letter payload must be an object")
    return errors


def _validate_batch_task_item_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = content.get("status", "")
    if status not in {"pending", "running", "waiting_handoff", "completed", "failed"}:
        errors.append("batch_task_item status must be pending, running, waiting_handoff, completed, or failed")
    if not isinstance(content.get("item_index"), int):
        errors.append("batch_task_item item_index must be an integer")
    for key in ["steps", "output_paths"]:
        if key not in content:
            errors.append(f"batch_task_item content missing required field: {key}")
        elif not isinstance(content.get(key), list):
            errors.append(f"batch_task_item {key} must be a list")
    if "error_message" not in content:
        errors.append("batch_task_item content missing required field: error_message")
    if status == "completed" and not content.get("output_paths"):
        errors.append("completed batch_task_item must include output_paths")
    if status == "failed" and _is_missing(content.get("error_message")):
        errors.append("failed batch_task_item must include error_message")
    return errors


def _validate_source_rights(metadata: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rights = metadata.get("rights")
    if not isinstance(rights, dict):
        return ["source_document metadata.rights must be recorded"]
    authorization = rights.get("authorization")
    allowed = {"owned", "licensed", "public_domain", "permission_granted", "test_fixture", "unknown"}
    if authorization not in allowed:
        errors.append("source_document metadata.rights.authorization is invalid or missing")
    if _is_missing(rights.get("copyright_boundary")):
        errors.append("source_document metadata.rights.copyright_boundary must not be empty")
    if not isinstance(rights.get("allow_downstream_generation"), bool):
        errors.append("source_document metadata.rights.allow_downstream_generation must be boolean")
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
    trend_metrics = content.get("trend_metrics")
    if trend_metrics is not None:
        if not isinstance(trend_metrics, dict):
            errors.append("feedback_insight trend_metrics must be an object")
        else:
            for key in ["rating_slope", "rating_volatility", "low_rating_ratio"]:
                if key in trend_metrics and not isinstance(trend_metrics.get(key), (int, float)):
                    errors.append(f"feedback_insight trend_metrics.{key} must be numeric")
            confidence = trend_metrics.get("confidence")
            if confidence is not None and confidence not in {"none", "low", "medium", "high"}:
                errors.append("feedback_insight trend_metrics.confidence must be none, low, medium, or high")
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


def _validate_platform_profile_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    business_model = content.get("business_model")
    if business_model not in {"paid_serial", "free_ad", "ip_publish", "mixed", "custom"}:
        errors.append("platform_profile business_model must be paid_serial, free_ad, ip_publish, mixed, or custom")
    length_range = content.get("chapter_length_range")
    if not isinstance(length_range, dict):
        errors.append("platform_profile chapter_length_range must be an object")
    else:
        values: dict[str, float] = {}
        for key in ["min", "max", "ideal"]:
            value = length_range.get(key)
            if not isinstance(value, (int, float)):
                errors.append(f"platform_profile chapter_length_range.{key} must be numeric")
            else:
                values[key] = float(value)
        if len(values) == 3 and not (values["min"] <= values["ideal"] <= values["max"]):
            errors.append("platform_profile chapter_length_range must satisfy min <= ideal <= max")
    for key in ["reader_expectation", "review_risks", "genre_fit", "style_tendency"]:
        if key in content and not isinstance(content.get(key), list):
            errors.append(f"platform_profile {key} must be a list")
    return errors


def _validate_topic_fit_report_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scores = content.get("scores")
    if not isinstance(scores, dict):
        errors.append("topic_fit_report scores must be an object")
    else:
        for key, value in scores.items():
            if not isinstance(value, (int, float)):
                errors.append(f"topic_fit_report scores.{key} must be numeric")
            elif value < 0 or value > 100:
                errors.append(f"topic_fit_report scores.{key} must be between 0 and 100")
    if not isinstance(content.get("must_adjust"), list):
        errors.append("topic_fit_report must_adjust must be a list")
    return errors


def _validate_quality_dimensions_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    dimensions = content.get("dimensions")
    if not isinstance(dimensions, dict):
        errors.append(f"{asset_type} dimensions must be an object")
    elif not dimensions:
        errors.append(f"{asset_type} dimensions must not be empty")
    else:
        total_weight = 0.0
        for name, dimension in dimensions.items():
            if not isinstance(dimension, dict):
                errors.append(f"{asset_type} dimensions.{name} must be an object")
                continue
            weight = dimension.get("weight")
            threshold = dimension.get("threshold")
            if not isinstance(weight, (int, float)) or weight < 0:
                errors.append(f"{asset_type} dimensions.{name}.weight must be a non-negative number")
            else:
                total_weight += float(weight)
            if threshold is not None and (not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 100):
                errors.append(f"{asset_type} dimensions.{name}.threshold must be between 0 and 100")
        if total_weight <= 0:
            errors.append(f"{asset_type} dimensions total weight must be greater than zero")
    for key in ["hard_gates", "checks"]:
        if key in content and not isinstance(content.get(key), list):
            errors.append(f"{asset_type} {key} must be a list")
    return errors


def _validate_quality_score_report_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    score = content.get("overall_score")
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        errors.append("quality_score_report overall_score must be between 0 and 100")
    scores = content.get("scores")
    if not isinstance(scores, dict):
        errors.append("quality_score_report scores must be an object")
    else:
        for key, value in scores.items():
            if not isinstance(value, (int, float)) or value < 0 or value > 100:
                errors.append(f"quality_score_report scores.{key} must be between 0 and 100")
    gate_results = content.get("gate_results")
    if not isinstance(gate_results, dict):
        errors.append("quality_score_report gate_results must be an object")
    return errors


def _validate_style_asset_content(asset_type: str, content: dict[str, Any], metadata: Any) -> list[str]:
    errors: list[str] = []
    if _contains_author_imitation_request({"content": content, "metadata": metadata}):
        errors.append(f"{asset_type} must not request specific author imitation")
    if asset_type == "style_profile":
        if content.get("scope") not in {"platform", "genre", "project", "blend"}:
            errors.append("style_profile scope must be platform, genre, project, or blend")
        source_boundary = content.get("source_boundary")
        if not isinstance(source_boundary, dict):
            errors.append("style_profile source_boundary must be an object")
        else:
            if source_boundary.get("allowed_usage") not in {"parameter_only", "abstract_reference_only"}:
                errors.append("style_profile source_boundary.allowed_usage must be parameter_only or abstract_reference_only")
            if not isinstance(source_boundary.get("derived_from_protected_text"), bool):
                errors.append("style_profile source_boundary.derived_from_protected_text must be boolean")
            if source_boundary.get("copyright_risk") not in {"low", "medium", "high", "unknown"}:
                errors.append("style_profile source_boundary.copyright_risk must be low, medium, high, or unknown")
        if not isinstance(content.get("forbidden_patterns"), list) or not content.get("forbidden_patterns"):
            errors.append("style_profile forbidden_patterns must be a non-empty list")
    if asset_type == "style_decomposition_report":
        if content.get("extract_level") != "abstract_parameters_only":
            errors.append("style_decomposition_report extract_level must be abstract_parameters_only")
        if content.get("risk_level") not in {"low", "medium", "high", "unknown"}:
            errors.append("style_decomposition_report risk_level must be low, medium, high, or unknown")
        if not isinstance(content.get("do_not_copy"), list):
            errors.append("style_decomposition_report do_not_copy must be a list")
    if asset_type == "style_blend_preset":
        components = content.get("components")
        if not isinstance(components, list) or not components:
            errors.append("style_blend_preset components must be a non-empty list")
        else:
            for index, component in enumerate(components):
                if not isinstance(component, dict):
                    errors.append(f"style_blend_preset components[{index}] must be an object")
                    continue
                weight = component.get("weight")
                if not isinstance(weight, (int, float)) or weight <= 0:
                    errors.append(f"style_blend_preset components[{index}].weight must be greater than zero")
    if asset_type == "style_review_report":
        score = content.get("style_match_score")
        if not isinstance(score, (int, float)) or score < 0 or score > 100:
            errors.append("style_review_report style_match_score must be between 0 and 100")
        if content.get("copyright_style_risk") not in {"low", "medium", "high", "unknown"}:
            errors.append("style_review_report copyright_style_risk must be low, medium, high, or unknown")
    return errors


def _validate_continuity_asset_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "continuity_bible":
        for key in ["worldview_rules", "timeline", "entities", "open_threads", "constraints"]:
            if not isinstance(content.get(key), list):
                errors.append(f"continuity_bible {key} must be a list")
    if asset_type == "foreshadowing_thread":
        if content.get("status") not in {"planned", "seeded", "developing", "paid_off", "abandoned"}:
            errors.append("foreshadowing_thread status must be planned, seeded, developing, paid_off, or abandoned")
        if not isinstance(content.get("related_chapters"), list):
            errors.append("foreshadowing_thread related_chapters must be a list")
    if asset_type == "power_scale_rule":
        for key in ["levels", "constraints", "violation_checks"]:
            if not isinstance(content.get(key), list):
                errors.append(f"power_scale_rule {key} must be a list")
    return errors


def _validate_release_gate_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "chapter_audit_report":
        scores = content.get("dimension_scores")
        if not isinstance(scores, dict):
            errors.append("chapter_audit_report dimension_scores must be an object")
        else:
            for key, value in scores.items():
                if not isinstance(value, (int, float)) or value < 0 or value > 100:
                    errors.append(f"chapter_audit_report dimension_scores.{key} must be between 0 and 100")
        if not isinstance(content.get("issues"), list):
            errors.append("chapter_audit_report issues must be a list")
        if not isinstance(content.get("gate_results"), dict):
            errors.append("chapter_audit_report gate_results must be an object")
        if not isinstance(content.get("linked_reports"), dict):
            errors.append("chapter_audit_report linked_reports must be an object")
        if content.get("recommendation") not in {"pass", "revise", "block_publish"}:
            errors.append("chapter_audit_report recommendation must be pass, revise, or block_publish")
    if asset_type == "originality_report":
        for key in ["plot_skeleton_risk", "character_setup_risk", "style_expression_risk", "risk_level"]:
            if content.get(key) not in {"low", "medium", "high", "unknown"}:
                errors.append(f"originality_report {key} must be low, medium, high, or unknown")
        if content.get("recommendation") not in {"pass", "revise_before_publish", "block_publish"}:
            errors.append("originality_report recommendation must be pass, revise_before_publish, or block_publish")
        if not isinstance(content.get("human_gate_required"), bool):
            errors.append("originality_report human_gate_required must be boolean")
        for key in ["source_asset_ids", "similarity_checks", "forbidden_element_hits"]:
            if not isinstance(content.get(key), list):
                errors.append(f"originality_report {key} must be a list")
        for index, item in enumerate(content.get("similarity_checks", []) if isinstance(content.get("similarity_checks"), list) else []):
            if not isinstance(item, dict):
                errors.append(f"originality_report similarity_checks[{index}] must be an object")
                continue
            score = item.get("similarity")
            if not isinstance(score, (int, float)) or score < 0 or score > 1:
                errors.append(f"originality_report similarity_checks[{index}].similarity must be between 0 and 1")
    if asset_type == "publish_gate_report":
        if not isinstance(content.get("gates"), dict):
            errors.append("publish_gate_report gates must be an object")
        if content.get("decision") not in {"ready", "needs_revision", "blocked"}:
            errors.append("publish_gate_report decision must be ready, needs_revision, or blocked")
        if not isinstance(content.get("blocking_issues"), list):
            errors.append("publish_gate_report blocking_issues must be a list")
        if not isinstance(content.get("required_reports"), dict):
            errors.append("publish_gate_report required_reports must be an object")
        if not isinstance(content.get("human_override"), bool):
            errors.append("publish_gate_report human_override must be boolean")
    if asset_type == "release_package":
        if not isinstance(content.get("title_candidates"), list) or not content.get("title_candidates"):
            errors.append("release_package title_candidates must be a non-empty list")
        if not isinstance(content.get("tags"), list):
            errors.append("release_package tags must be a list")
        if content.get("status") not in {"draft", "ready", "blocked", "published"}:
            errors.append("release_package status must be draft, ready, blocked, or published")
    return errors


def _validate_analysis_asset_content(asset_type: str, content: dict[str, Any], metadata: Any) -> list[str]:
    errors: list[str] = []
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    risk = content.get("copyright_risk", metadata_dict.get("copyright_risk", metadata_dict.get("risk_level", "unknown")))
    if risk not in {"low", "medium", "high", "unknown"}:
        errors.append(f"{asset_type} copyright_risk must be low, medium, high, or unknown")
    abstraction_level = content.get("abstraction_level", metadata_dict.get("abstraction_level", "abstract"))
    if abstraction_level not in {"abstract", "mechanism", "template"}:
        errors.append(f"{asset_type} abstraction_level must be abstract, mechanism, or template")
    if metadata_dict.get("use_in_generation_rag") is True and asset_type != "analysis_conversion_report":
        errors.append(f"{asset_type} must not enter generation RAG directly; convert to abstract assets first")
    if asset_type != "analysis_conversion_report":
        for key in ["structure_map", "character_map", "conflict_map", "theme_map", "craft_dimensions", "scene_design"]:
            if key in content and not isinstance(content.get(key), (dict, list)):
                errors.append(f"{asset_type} {key} must be an object or list")
        for key in ["reusable_findings", "reusable_assets", "transferable_techniques", "transferable_abstractions"]:
            if key in content and not isinstance(content.get(key), list):
                errors.append(f"{asset_type} {key} must be a list")
    if asset_type == "analysis_conversion_report":
        if content.get("source_report_type") not in _ANALYSIS_ASSET_TYPES - {"analysis_conversion_report"}:
            errors.append("analysis_conversion_report source_report_type must be an analysis report type")
        if not isinstance(content.get("conversion_targets"), list):
            errors.append("analysis_conversion_report conversion_targets must be a list")
        if not isinstance(content.get("created_assets"), list):
            errors.append("analysis_conversion_report created_assets must be a list")
        if not isinstance(content.get("rejected_items"), list):
            errors.append("analysis_conversion_report rejected_items must be a list")
        if content.get("reuse_scope") not in {"project", "global", "research_only"}:
            errors.append("analysis_conversion_report reuse_scope must be project, global, or research_only")
    return errors


def _contains_author_imitation_request(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered_key = str(key).lower()
            if lowered_key in {"author", "author_name", "target_author", "source_author", "imitate_author"} and not _is_missing(item):
                return True
            if _contains_author_imitation_request(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_author_imitation_request(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    blocked = [
        "imitate author",
        "author imitation",
        "copy author style",
        "specific author style",
        "write like ",
        "模仿作者",
        "仿写作者",
        "复刻作者",
        "照着作者",
    ]
    return any(token in lowered for token in blocked)
