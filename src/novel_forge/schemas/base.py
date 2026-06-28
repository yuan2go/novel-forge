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
    "creative_strategy_profile": [
        "strategy_id",
        "reader_promise",
        "volume_goals",
        "pleasure_rhythm",
        "long_hooks",
        "platform_pacing",
        "verification_rules",
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
    "long_form_macro_plan": [
        "plan_id",
        "project_id",
        "target_word_count",
        "volume_plans",
        "mainline_matrix",
        "subplot_matrix",
        "character_arc_curves",
        "climax_ladder",
        "commercial_pacing_table",
        "verification_gates",
    ],
    "context_build_plan": [
        "target_asset_id",
        "target_asset_type",
        "target_path",
        "query",
        "token_budget",
        "selection_policy",
        "candidate_assets",
        "exclusions",
    ],
    "context_bundle": [
        "build_plan_id",
        "target_asset_id",
        "selected_assets",
        "compressed_context",
        "token_budget",
        "token_estimate",
        "actual_context",
        "source_asset_ids",
    ],
    "rag_quality_report": [
        "target_asset_id",
        "retrieval_backend",
        "recall_explanation",
        "omission_check",
        "copyright_filter",
        "context_budget_score",
        "recommendation",
    ],
    "outline": ["acts"],
    "outline_version": ["outline_id", "version_index", "base_outline_id", "acts", "change_summary", "status"],
    "chapter_plan": ["chapter", "objective", "beats", "hook"],
    "chapter_plan_version": [
        "chapter_plan_id",
        "version_index",
        "base_chapter_plan_id",
        "chapter",
        "objective",
        "beats",
        "hook",
        "word_budget",
        "conflict",
        "information_points",
        "status",
    ],
    "generation_run": [
        "run_id",
        "input_asset_id",
        "input_asset_path",
        "context_bundle_id",
        "output_asset_id",
        "provider",
        "model",
        "prompt_version",
        "status",
        "started_at",
        "finished_at",
    ],
    "chapter_production_run": [
        "run_id",
        "status",
        "current_step",
        "chapter",
        "step_order",
        "steps",
        "timeline",
        "created_at",
        "updated_at",
    ],
    "draft_chapter": ["chapter", "text", "copyright_boundary"],
    "draft_version": ["draft_id", "version_index", "chapter", "text", "source_draft_id", "change_summary", "status"],
    "editor_patch": ["target_draft_id", "target_draft_path", "operations", "status", "created_at"],
    "draft_diff_report": ["base_draft_id", "target_draft_id", "diff_summary", "operations", "created_at"],
    "review_report": ["rubric", "summary"],
    "revision_plan": ["steps", "target_score", "must_preserve"],
    "reader_feedback": ["rows"],
    "feedback_import_batch": ["batch_id", "source", "rows", "row_count", "columns", "status", "imported_at"],
    "feedback_insight": ["signals", "average_rating", "next_generation_constraints"],
    "reader_sentiment_report": [
        "feedback_asset_ids",
        "sentiment_distribution",
        "clusters",
        "reader_expectations",
        "poison_points",
        "sweet_points",
        "recommendations",
        "confidence",
    ],
    "project_metric_snapshot": [
        "project_id",
        "snapshot_at",
        "throughput",
        "quality",
        "task_health",
        "agent_health",
        "storage_health",
        "recommendations",
    ],
    "local_settings_profile": ["profile_id", "local_mode", "model_routing", "storage", "agent_defaults", "validation", "status"],
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
    "workflow_definition": ["workflow_id", "name", "version", "nodes", "entry_node_id", "status"],
    "workflow_node": ["node_id", "workflow_id", "node_type", "operation", "input_types", "output_types", "processor", "quality_gate"],
    "node_run": [
        "run_id",
        "node_id",
        "node_type",
        "operation",
        "status",
        "input_assets",
        "output_assets",
        "processor",
        "started_at",
        "finished_at",
    ],
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
    "change_impact_report": ["target_asset_id", "target_path", "impacted_assets", "impact_edges", "severity_summary", "recommendation"],
    "agent_contract": [
        "contract_id",
        "agent_type",
        "operation",
        "input_types",
        "output_types",
        "permissions",
        "tool_allowlist",
        "allowed_write_types",
        "quality_gates",
    ],
    "agent_run": [
        "run_id",
        "agent_type",
        "operation",
        "status",
        "input_assets",
        "output_assets",
        "contract_id",
        "permissions",
        "started_at",
    ],
    "agent_checkpoint": ["agent_run_id", "checkpoint_id", "status", "state", "created_at"],
    "agent_event": ["agent_run_id", "event_type", "status", "message", "created_at"],
    "agent_budget": ["agent_run_id", "token_budget", "token_used", "cost_estimate", "status"],
    "agent_gate": ["agent_run_id", "gate_id", "gate_type", "status", "result", "created_at"],
    "agent_metric": ["agent_run_id", "metric_name", "value", "created_at"],
    "agent_failure_report": ["agent_run_id", "error_type", "error_message", "recovery_instruction", "created_at"],
    "agent_sla_report": ["agent_run_id", "status", "started_at", "deadline_at", "elapsed_seconds", "sla_seconds", "breach"],
    "agent_rollback_report": ["agent_run_id", "rollback_id", "target_asset_paths", "rollback_strategy", "status", "created_at"],
    "agent_dispatch_queue": ["dispatch_id", "idempotency_key", "status", "agent_run_id", "agent_run_path", "operation", "attempt_count"],
    "scheduler_lease": ["lease_key", "owner", "status", "acquired_at", "expires_at"],
    "trace_span": ["trace_id", "span_id", "parent_span_id", "span_type", "name", "status", "started_at"],
    "gate_result": ["gate_id", "gate_kind", "status", "target_paths", "created_at"],
    "model_call_log": ["call_id", "provider", "model", "operation", "status", "usage", "cost", "created_at"],
    "cost_ledger": ["ledger_id", "scope", "amount", "currency", "source_type", "source_id", "created_at"],
    "budget_policy": ["policy_id", "scope", "limits", "status"],
    "cost_alert": ["alert_id", "scope", "severity", "message", "status", "created_at"],
    "chapter_continuity_report": ["target_asset_id", "chapter", "continuity_checks", "violations", "recommendation"],
    "continuity_graph_snapshot": ["project_id", "nodes", "edges", "summary", "created_at"],
    "canon_graph_snapshot": ["snapshot_id", "project_id", "entities", "relationships", "state_machines", "lifecycle_threads", "event_graph", "violations"],
    "canon_patch": ["patch_id", "target_draft_id", "status", "proposed_events", "entity_updates", "thread_updates", "relationship_updates", "apply_plan", "human_gate"],
    "model_profile": ["provider", "model_name", "capabilities", "cost_profile", "status"],
    "model_benchmark_task": ["task_id", "task_type", "input_assets", "rubric", "expected_output_type"],
    "model_benchmark_run": ["task_id", "provider", "model_name", "scores", "latency_ms", "status", "created_at"],
    "model_comparison_report": ["task_type", "runs", "winner", "score_summary", "recommendation"],
    "prompt_version": ["prompt_id", "version", "task_type", "template", "status"],
    "prompt_regression_report": ["prompt_id", "baseline_version", "candidate_version", "benchmark_runs", "recommendation"],
    "model_routing_policy": ["policy_id", "task_routes", "fallbacks", "cost_quality_tradeoffs", "effective_from", "status"],
    "operational_metric_snapshot": ["project_id", "snapshot_at", "read_metrics", "engagement_metrics", "character_heat", "chapter_dropoffs", "recommendations"],
    "publishing_plan": ["plan_id", "project_id", "calendar", "chapter_queue", "platform_targets", "gate_policy", "status"],
    "publishing_log": ["log_id", "release_package_id", "channel", "status", "published_at", "rollback_plan"],
    "local_ops_drill_report": ["drill_id", "scenarios", "results", "recovery_actions", "status", "created_at"],
    "long_chain_acceptance_report": ["run_id", "chapter_count", "checks", "quality_trends", "canon_conflicts", "publish_gate_summary", "recommendation"],
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
    if asset_type in {"workflow_definition", "workflow_node", "node_run"} and isinstance(content, dict):
        errors.extend(_validate_workflow_contract_content(asset_type, content))
    if asset_type == "claude_code_handoff" and isinstance(content, dict):
        errors.extend(_validate_claude_code_handoff_content(content))
    if asset_type == "task_status" and isinstance(content, dict):
        errors.extend(_validate_task_status_content(content))
    if asset_type == "task_dead_letter" and isinstance(content, dict):
        errors.extend(_validate_task_dead_letter_content(content))
    if asset_type == "batch_task_item" and isinstance(content, dict):
        errors.extend(_validate_batch_task_item_content(content))
    if asset_type in {"feedback_import_batch", "feedback_insight", "reader_sentiment_report"} and isinstance(content, dict):
        errors.extend(_validate_feedback_content(asset_type, content))
    if asset_type == "project_metric_snapshot" and isinstance(content, dict):
        errors.extend(_validate_project_metric_snapshot_content(content))
    if asset_type == "local_settings_profile" and isinstance(content, dict):
        errors.extend(_validate_local_settings_profile_content(content))
    if asset_type == "project_workspace_state" and isinstance(content, dict):
        errors.extend(_validate_project_workspace_state_content(content))
    if asset_type == "review_report" and isinstance(content, dict):
        errors.extend(_validate_review_report_content(content))
    if asset_type == "platform_profile" and isinstance(content, dict):
        errors.extend(_validate_platform_profile_content(content))
    if asset_type == "topic_fit_report" and isinstance(content, dict):
        errors.extend(_validate_topic_fit_report_content(content))
    if asset_type == "creative_strategy_profile" and isinstance(content, dict):
        errors.extend(_validate_creative_strategy_profile_content(content))
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
    if asset_type in {"context_build_plan", "context_bundle"} and isinstance(content, dict):
        errors.extend(_validate_context_asset_content(asset_type, content))
    if asset_type == "rag_quality_report" and isinstance(content, dict):
        errors.extend(_validate_rag_quality_report_content(content))
    if asset_type in {"outline_version", "chapter_plan_version", "draft_version", "generation_run", "chapter_production_run"} and isinstance(content, dict):
        errors.extend(_validate_versioned_production_content(asset_type, content))
    if asset_type in {"editor_patch", "draft_diff_report"} and isinstance(content, dict):
        errors.extend(_validate_editor_asset_content(asset_type, content))
    if asset_type == "change_impact_report" and isinstance(content, dict):
        errors.extend(_validate_change_impact_report_content(content))
    if asset_type.startswith("agent_") and isinstance(content, dict):
        errors.extend(_validate_agent_asset_content(asset_type, content))
    if asset_type in {"scheduler_lease", "trace_span", "gate_result", "model_call_log", "cost_ledger", "budget_policy", "cost_alert"} and isinstance(content, dict):
        errors.extend(_validate_runtime_observability_content(asset_type, content))
    if asset_type in {"chapter_continuity_report", "continuity_graph_snapshot", "canon_graph_snapshot", "canon_patch"} and isinstance(content, dict):
        errors.extend(_validate_deep_continuity_content(asset_type, content))
    if asset_type in {"model_profile", "model_benchmark_task", "model_benchmark_run", "model_comparison_report", "prompt_version", "prompt_regression_report", "model_routing_policy"} and isinstance(content, dict):
        errors.extend(_validate_model_evaluation_content(asset_type, content))
    if asset_type in {
        "long_form_macro_plan",
        "operational_metric_snapshot",
        "publishing_plan",
        "publishing_log",
        "local_ops_drill_report",
        "long_chain_acceptance_report",
    } and isinstance(content, dict):
        errors.extend(_validate_industrial_extension_content(asset_type, content))

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
    if status not in {"pending", "running", "paused", "completed", "failed", "cancelled", "superseded"}:
        errors.append("workflow_run status must be pending, running, paused, completed, failed, cancelled, or superseded")
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


def _validate_runtime_observability_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "scheduler_lease":
        if content.get("status") not in {"active", "released", "expired", "stolen"}:
            errors.append("scheduler_lease status must be active, released, expired, or stolen")
    if asset_type == "trace_span":
        if content.get("status") not in {"running", "succeeded", "failed", "cancelled", "skipped"}:
            errors.append("trace_span status must be running, succeeded, failed, cancelled, or skipped")
    if asset_type == "gate_result":
        if content.get("status") not in {"passed", "failed", "warning", "skipped"}:
            errors.append("gate_result status must be passed, failed, warning, or skipped")
        if not isinstance(content.get("target_paths"), list):
            errors.append("gate_result target_paths must be a list")
    if asset_type == "model_call_log":
        if content.get("status") not in {"succeeded", "failed", "skipped"}:
            errors.append("model_call_log status must be succeeded, failed, or skipped")
        if not isinstance(content.get("usage"), dict):
            errors.append("model_call_log usage must be an object")
        if not isinstance(content.get("cost"), dict):
            errors.append("model_call_log cost must be an object")
    if asset_type == "cost_ledger":
        if not isinstance(content.get("amount"), (int, float)) or float(content.get("amount", 0)) < 0:
            errors.append("cost_ledger amount must be a non-negative number")
    if asset_type == "budget_policy":
        if content.get("status") not in {"active", "disabled", "archived"}:
            errors.append("budget_policy status must be active, disabled, or archived")
        if not isinstance(content.get("limits"), dict):
            errors.append("budget_policy limits must be an object")
    if asset_type == "cost_alert":
        if content.get("severity") not in {"info", "warning", "critical"}:
            errors.append("cost_alert severity must be info, warning, or critical")
        if content.get("status") not in {"open", "acknowledged", "resolved"}:
            errors.append("cost_alert status must be open, acknowledged, or resolved")
    return errors


def _validate_workflow_contract_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "workflow_definition":
        nodes = content.get("nodes")
        if not isinstance(nodes, list):
            errors.append("workflow_definition nodes must be a list")
        elif not nodes:
            errors.append("workflow_definition nodes must not be empty")
        if content.get("status") not in {"draft", "active", "archived"}:
            errors.append("workflow_definition status must be draft, active, or archived")
    if asset_type == "workflow_node":
        for key in ["input_types", "output_types"]:
            if not isinstance(content.get(key), list):
                errors.append(f"workflow_node {key} must be a list")
        if not isinstance(content.get("processor"), dict):
            errors.append("workflow_node processor must be an object")
        if not isinstance(content.get("quality_gate"), dict):
            errors.append("workflow_node quality_gate must be an object")
    if asset_type == "node_run":
        if content.get("status") not in {
            "planned",
            "prepared",
            "running",
            "checkpointed",
            "waiting_human",
            "verifying",
            "succeeded",
            "needs_revision",
            "failed",
            "dead_letter",
            "recovered",
            "cancelled",
        }:
            errors.append("node_run status is invalid")
        for key in ["input_assets", "output_assets"]:
            if not isinstance(content.get(key), list):
                errors.append(f"node_run {key} must be a list")
        if not isinstance(content.get("processor"), dict):
            errors.append("node_run processor must be an object")
        if "quality_gate" in content and not isinstance(content.get("quality_gate"), dict):
            errors.append("node_run quality_gate must be an object")
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
    if status not in {"pending", "running", "completed", "failed", "paused", "cancelled"}:
        errors.append("task_status status must be pending, running, completed, failed, paused, or cancelled")
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


def _validate_feedback_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "feedback_import_batch":
        if content.get("status") not in {"imported", "failed", "partial"}:
            errors.append("feedback_import_batch status must be imported, failed, or partial")
        if not isinstance(content.get("rows"), list):
            errors.append("feedback_import_batch rows must be a list")
        if not isinstance(content.get("row_count"), int) or content.get("row_count", 0) < 0:
            errors.append("feedback_import_batch row_count must be a non-negative integer")
        if not isinstance(content.get("columns"), list):
            errors.append("feedback_import_batch columns must be a list")
    if asset_type == "feedback_insight":
        errors.extend(_validate_feedback_insight_content(content))
    if asset_type == "reader_sentiment_report":
        distribution = content.get("sentiment_distribution")
        if not isinstance(distribution, dict):
            errors.append("reader_sentiment_report sentiment_distribution must be an object")
        else:
            for key in ["positive", "neutral", "negative"]:
                if key in distribution and (not isinstance(distribution.get(key), int) or distribution.get(key, 0) < 0):
                    errors.append(f"reader_sentiment_report sentiment_distribution.{key} must be a non-negative integer")
        clusters = content.get("clusters")
        if not isinstance(clusters, list):
            errors.append("reader_sentiment_report clusters must be a list")
        else:
            for index, cluster in enumerate(clusters):
                if not isinstance(cluster, dict):
                    errors.append(f"reader_sentiment_report clusters[{index}] must be an object")
                    continue
                if _is_missing(cluster.get("label")):
                    errors.append(f"reader_sentiment_report clusters[{index}].label must not be empty")
                if "count" in cluster and (not isinstance(cluster.get("count"), int) or cluster.get("count", 0) < 0):
                    errors.append(f"reader_sentiment_report clusters[{index}].count must be a non-negative integer")
        for key in ["feedback_asset_ids", "reader_expectations", "poison_points", "sweet_points", "recommendations"]:
            if not isinstance(content.get(key), list):
                errors.append(f"reader_sentiment_report {key} must be a list")
        if content.get("confidence") not in {"none", "low", "medium", "high"}:
            errors.append("reader_sentiment_report confidence must be none, low, medium, or high")
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


def _validate_project_metric_snapshot_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ["throughput", "quality", "task_health", "agent_health", "storage_health"]:
        if not isinstance(content.get(key), dict):
            errors.append(f"project_metric_snapshot {key} must be an object")
    recommendations = content.get("recommendations")
    if not isinstance(recommendations, list):
        errors.append("project_metric_snapshot recommendations must be a list")
    quality = content.get("quality") if isinstance(content.get("quality"), dict) else {}
    for score_key in ["average_review_score", "review_pass_rate", "originality_risk_rate"]:
        if score_key in quality and not isinstance(quality.get(score_key), (int, float)):
            errors.append(f"project_metric_snapshot quality.{score_key} must be numeric")
    task_health = content.get("task_health") if isinstance(content.get("task_health"), dict) else {}
    for count_key in ["failed", "running", "waiting_handoff", "dead_letters"]:
        if count_key in task_health and (not isinstance(task_health.get(count_key), int) or task_health.get(count_key, 0) < 0):
            errors.append(f"project_metric_snapshot task_health.{count_key} must be a non-negative integer")
    return errors


def _validate_local_settings_profile_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(content.get("local_mode"), bool):
        errors.append("local_settings_profile local_mode must be boolean")
    for key in ["model_routing", "storage", "agent_defaults", "validation"]:
        if not isinstance(content.get(key), dict):
            errors.append(f"local_settings_profile {key} must be an object")
    if content.get("status") not in {"draft", "active", "archived"}:
        errors.append("local_settings_profile status must be draft, active, or archived")
    model_routing = content.get("model_routing") if isinstance(content.get("model_routing"), dict) else {}
    if "default_provider" in model_routing and _is_missing(model_routing.get("default_provider")):
        errors.append("local_settings_profile model_routing.default_provider must not be empty when present")
    validation = content.get("validation") if isinstance(content.get("validation"), dict) else {}
    if "strict_local_prod" in validation and not isinstance(validation.get("strict_local_prod"), bool):
        errors.append("local_settings_profile validation.strict_local_prod must be boolean")
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


def _validate_creative_strategy_profile_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(content.get("reader_promise", "")).strip():
        errors.append("creative_strategy_profile reader_promise must not be empty")
    for key in ["volume_goals", "pleasure_rhythm", "long_hooks", "platform_pacing", "verification_rules"]:
        if not isinstance(content.get(key), (dict, list)):
            errors.append(f"creative_strategy_profile {key} must be an object or list")
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


def _validate_context_asset_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    token_budget = content.get("token_budget")
    if not isinstance(token_budget, dict):
        errors.append(f"{asset_type} token_budget must be an object")
    else:
        max_tokens = token_budget.get("max_tokens")
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            errors.append(f"{asset_type} token_budget.max_tokens must be a positive integer")
    if asset_type == "context_build_plan":
        if not isinstance(content.get("selection_policy"), dict):
            errors.append("context_build_plan selection_policy must be an object")
        for key in ["candidate_assets", "exclusions"]:
            if not isinstance(content.get(key), list):
                errors.append(f"context_build_plan {key} must be a list")
        top_k = content.get("top_k")
        if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
            errors.append("context_build_plan top_k must be a positive integer")
    if asset_type == "context_bundle":
        selected_assets = content.get("selected_assets")
        if not isinstance(selected_assets, list):
            errors.append("context_bundle selected_assets must be a list")
        source_asset_ids = content.get("source_asset_ids")
        if not isinstance(source_asset_ids, list):
            errors.append("context_bundle source_asset_ids must be a list")
        token_estimate = content.get("token_estimate")
        if not isinstance(token_estimate, (int, float)) or token_estimate < 0:
            errors.append("context_bundle token_estimate must be a non-negative number")
        if not isinstance(content.get("compressed_context"), (dict, list, str)):
            errors.append("context_bundle compressed_context must be an object, list, or string")
    return errors


def _validate_rag_quality_report_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ["recall_explanation", "omission_check", "copyright_filter", "context_budget_score"]:
        if not isinstance(content.get(key), dict):
            errors.append(f"rag_quality_report {key} must be an object")
    score = (content.get("context_budget_score") or {}).get("score") if isinstance(content.get("context_budget_score"), dict) else None
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        errors.append("rag_quality_report context_budget_score.score must be between 0 and 100")
    if content.get("recommendation") not in {"pass", "pass_with_warnings", "revise", "block"}:
        errors.append("rag_quality_report recommendation must be pass, pass_with_warnings, revise, or block")
    return errors


def _validate_versioned_production_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = content.get("status")
    allowed_version_status = {"draft", "active", "superseded", "archived"}
    if asset_type in {"outline_version", "chapter_plan_version", "draft_version"}:
        version_index = content.get("version_index")
        if not isinstance(version_index, int) or version_index < 0:
            errors.append(f"{asset_type} version_index must be a non-negative integer")
        if status not in allowed_version_status:
            errors.append(f"{asset_type} status must be draft, active, superseded, or archived")
    if asset_type == "outline_version" and not isinstance(content.get("acts"), list):
        errors.append("outline_version acts must be a list")
    if asset_type == "chapter_plan_version":
        if not isinstance(content.get("beats"), list):
            errors.append("chapter_plan_version beats must be a list")
        if not isinstance(content.get("information_points"), list):
            errors.append("chapter_plan_version information_points must be a list")
        word_budget = content.get("word_budget")
        if not isinstance(word_budget, (dict, int, float)):
            errors.append("chapter_plan_version word_budget must be an object or number")
    if asset_type == "generation_run":
        if status not in {"planned", "prepared", "running", "succeeded", "failed", "cancelled"}:
            errors.append("generation_run status must be planned, prepared, running, succeeded, failed, or cancelled")
        for key in ["input_asset_path", "context_bundle_id", "provider", "model", "prompt_version", "started_at", "finished_at"]:
            if not isinstance(content.get(key), str):
                errors.append(f"generation_run {key} must be a string")
        if "source_asset_ids" in content and not isinstance(content.get("source_asset_ids"), list):
            errors.append("generation_run source_asset_ids must be a list")
        if "metrics" in content and not isinstance(content.get("metrics"), dict):
            errors.append("generation_run metrics must be an object")
    if asset_type == "chapter_production_run":
        if status not in {"planned", "running", "paused", "waiting_human", "succeeded", "failed", "cancelled", "recovered"}:
            errors.append("chapter_production_run status must be planned, running, paused, waiting_human, succeeded, failed, cancelled, or recovered")
        if not isinstance(content.get("chapter"), int) or content.get("chapter", 0) < 1:
            errors.append("chapter_production_run chapter must be a positive integer")
        for key in ["step_order", "timeline"]:
            if not isinstance(content.get(key), list):
                errors.append(f"chapter_production_run {key} must be a list")
        if not isinstance(content.get("steps"), dict):
            errors.append("chapter_production_run steps must be an object")
        if not isinstance(content.get("current_step"), str):
            errors.append("chapter_production_run current_step must be a string")
        if "outputs" in content and not isinstance(content.get("outputs"), dict):
            errors.append("chapter_production_run outputs must be an object")
    return errors


def _validate_editor_asset_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "editor_patch":
        operations = content.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append("editor_patch operations must be a non-empty list")
        elif any(not isinstance(item, dict) for item in operations):
            errors.append("editor_patch operations must contain objects")
        if content.get("status") not in {"proposed", "applied", "rejected", "rolled_back"}:
            errors.append("editor_patch status must be proposed, applied, rejected, or rolled_back")
    if asset_type == "draft_diff_report":
        operations = content.get("operations")
        if not isinstance(operations, list):
            errors.append("draft_diff_report operations must be a list")
        summary = content.get("diff_summary")
        if not isinstance(summary, dict):
            errors.append("draft_diff_report diff_summary must be an object")
    return errors


def _validate_change_impact_report_content(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    impacted = content.get("impacted_assets")
    if not isinstance(impacted, list):
        errors.append("change_impact_report impacted_assets must be a list")
    else:
        for index, item in enumerate(impacted):
            if not isinstance(item, dict):
                errors.append(f"change_impact_report impacted_assets[{index}] must be an object")
                continue
            if item.get("severity") not in {"low", "medium", "high", "blocking"}:
                errors.append(f"change_impact_report impacted_assets[{index}].severity must be low, medium, high, or blocking")
            if _is_missing(item.get("path")):
                errors.append(f"change_impact_report impacted_assets[{index}].path must not be empty")
    edges = content.get("impact_edges")
    if not isinstance(edges, list):
        errors.append("change_impact_report impact_edges must be a list")
    summary = content.get("severity_summary")
    if not isinstance(summary, dict):
        errors.append("change_impact_report severity_summary must be an object")
    if content.get("recommendation") not in {"no_action", "review_impacts", "regenerate_downstream", "block_until_resolved"}:
        errors.append("change_impact_report recommendation must be no_action, review_impacts, regenerate_downstream, or block_until_resolved")
    return errors


def _validate_agent_asset_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "agent_contract":
        for key in ["input_types", "output_types", "tool_allowlist", "allowed_write_types", "quality_gates"]:
            if not isinstance(content.get(key), list):
                errors.append(f"agent_contract {key} must be a list")
        for key in ["permissions"]:
            if not isinstance(content.get(key), dict):
                errors.append(f"agent_contract {key} must be an object")
    if asset_type == "agent_run":
        if content.get("status") not in {
            "planned",
            "prepared",
            "running",
            "checkpointed",
            "waiting_human",
            "verifying",
            "succeeded",
            "needs_revision",
            "failed",
            "dead_letter",
            "recovered",
            "cancelled",
        }:
            errors.append("agent_run status is invalid")
        for key in ["input_assets", "output_assets"]:
            if not isinstance(content.get(key), list):
                errors.append(f"agent_run {key} must be a list")
        if not isinstance(content.get("permissions"), dict):
            errors.append("agent_run permissions must be an object")
    if asset_type == "agent_checkpoint" and not isinstance(content.get("state"), dict):
        errors.append("agent_checkpoint state must be an object")
    if asset_type == "agent_event" and content.get("status") not in {
        "info",
        "warning",
        "planned",
        "prepared",
        "running",
        "checkpointed",
        "waiting_human",
        "verifying",
        "succeeded",
        "needs_revision",
        "failed",
        "dead_letter",
        "recovered",
        "cancelled",
    }:
        errors.append("agent_event status is invalid")
    if asset_type == "agent_budget":
        for key in ["token_budget", "token_used", "cost_estimate"]:
            value = content.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                errors.append(f"agent_budget {key} must be a non-negative number")
        if content.get("status") not in {"within_budget", "near_limit", "exceeded"}:
            errors.append("agent_budget status must be within_budget, near_limit, or exceeded")
    if asset_type == "agent_gate":
        if content.get("status") not in {"pending", "passed", "failed", "waived", "needs_human"}:
            errors.append("agent_gate status must be pending, passed, failed, waived, or needs_human")
        if not isinstance(content.get("result"), dict):
            errors.append("agent_gate result must be an object")
    if asset_type == "agent_metric":
        if not isinstance(content.get("value"), (int, float, str, bool)):
            errors.append("agent_metric value must be scalar")
    if asset_type == "agent_sla_report":
        if content.get("status") not in {"within_sla", "breached", "unknown"}:
            errors.append("agent_sla_report status must be within_sla, breached, or unknown")
        for key in ["elapsed_seconds", "sla_seconds"]:
            value = content.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                errors.append(f"agent_sla_report {key} must be a non-negative number")
        if not isinstance(content.get("breach"), bool):
            errors.append("agent_sla_report breach must be boolean")
    if asset_type == "agent_rollback_report":
        if not isinstance(content.get("target_asset_paths"), list):
            errors.append("agent_rollback_report target_asset_paths must be a list")
        if content.get("status") not in {"planned", "applied", "failed", "not_required"}:
            errors.append("agent_rollback_report status must be planned, applied, failed, or not_required")
    if asset_type == "agent_dispatch_queue":
        if content.get("status") not in {"queued", "claimed", "running", "waiting_human", "acked", "retry_scheduled", "dead_letter", "cancelled"}:
            errors.append("agent_dispatch_queue status is invalid")
        for key in ["attempt_count", "max_attempts", "priority"]:
            value = content.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                errors.append(f"agent_dispatch_queue {key} must be a non-negative integer")
        if not isinstance(content.get("result", {}), dict):
            errors.append("agent_dispatch_queue result must be an object")
        if not isinstance(content.get("trace", {}), dict):
            errors.append("agent_dispatch_queue trace must be an object")
    return errors


def _validate_deep_continuity_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "chapter_continuity_report":
        if not isinstance(content.get("continuity_checks"), list):
            errors.append("chapter_continuity_report continuity_checks must be a list")
        if not isinstance(content.get("violations"), list):
            errors.append("chapter_continuity_report violations must be a list")
        if content.get("recommendation") not in {"pass", "revise", "block"}:
            errors.append("chapter_continuity_report recommendation must be pass, revise, or block")
    if asset_type == "continuity_graph_snapshot":
        for key in ["nodes", "edges"]:
            if not isinstance(content.get(key), list):
                errors.append(f"continuity_graph_snapshot {key} must be a list")
        if not isinstance(content.get("summary"), dict):
            errors.append("continuity_graph_snapshot summary must be an object")
    if asset_type == "canon_graph_snapshot":
        for key in ["entities", "relationships", "state_machines", "lifecycle_threads", "event_graph", "violations"]:
            if not isinstance(content.get(key), (dict, list)):
                errors.append(f"canon_graph_snapshot {key} must be an object or list")
    if asset_type == "canon_patch":
        for key in ["proposed_events", "entity_updates", "thread_updates", "relationship_updates"]:
            if not isinstance(content.get(key), list):
                errors.append(f"canon_patch {key} must be a list")
        if not isinstance(content.get("apply_plan"), dict):
            errors.append("canon_patch apply_plan must be an object")
        if not isinstance(content.get("human_gate"), dict):
            errors.append("canon_patch human_gate must be an object")
        if content.get("status") not in {"proposed", "accepted", "applied", "rejected"}:
            errors.append("canon_patch status must be proposed, accepted, applied, or rejected")
    return errors


def _validate_model_evaluation_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset_type == "model_profile":
        for key in ["capabilities", "cost_profile"]:
            if not isinstance(content.get(key), dict):
                errors.append(f"model_profile {key} must be an object")
        if content.get("status") not in {"active", "candidate", "disabled", "failed"}:
            errors.append("model_profile status must be active, candidate, disabled, or failed")
    if asset_type == "model_benchmark_task":
        if not isinstance(content.get("input_assets"), list):
            errors.append("model_benchmark_task input_assets must be a list")
        if not isinstance(content.get("rubric"), dict):
            errors.append("model_benchmark_task rubric must be an object")
    if asset_type == "model_benchmark_run":
        if not isinstance(content.get("scores"), dict):
            errors.append("model_benchmark_run scores must be an object")
        latency = content.get("latency_ms")
        if not isinstance(latency, (int, float)) or latency < 0:
            errors.append("model_benchmark_run latency_ms must be a non-negative number")
        if content.get("status") not in {"succeeded", "failed", "skipped"}:
            errors.append("model_benchmark_run status must be succeeded, failed, or skipped")
    if asset_type == "model_comparison_report":
        if not isinstance(content.get("runs"), list):
            errors.append("model_comparison_report runs must be a list")
        if not isinstance(content.get("score_summary"), dict):
            errors.append("model_comparison_report score_summary must be an object")
    if asset_type == "prompt_version":
        if content.get("status") not in {"draft", "active", "archived"}:
            errors.append("prompt_version status must be draft, active, or archived")
    if asset_type == "prompt_regression_report":
        if not isinstance(content.get("benchmark_runs"), list):
            errors.append("prompt_regression_report benchmark_runs must be a list")
        if content.get("recommendation") not in {"promote", "keep_baseline", "needs_revision"}:
            errors.append("prompt_regression_report recommendation must be promote, keep_baseline, or needs_revision")
    if asset_type == "model_routing_policy":
        for key in ["task_routes", "fallbacks", "cost_quality_tradeoffs"]:
            if not isinstance(content.get(key), dict):
                errors.append(f"model_routing_policy {key} must be an object")
        if content.get("status") not in {"draft", "active", "archived"}:
            errors.append("model_routing_policy status must be draft, active, or archived")
    return errors


def _validate_industrial_extension_content(asset_type: str, content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    list_fields = {
        "long_form_macro_plan": [
            "volume_plans",
            "mainline_matrix",
            "subplot_matrix",
            "character_arc_curves",
            "climax_ladder",
            "commercial_pacing_table",
            "verification_gates",
        ],
        "operational_metric_snapshot": ["character_heat", "chapter_dropoffs", "recommendations"],
        "publishing_plan": ["calendar", "chapter_queue", "platform_targets"],
        "local_ops_drill_report": ["scenarios", "results", "recovery_actions"],
        "long_chain_acceptance_report": ["checks", "canon_conflicts"],
    }
    for key in list_fields.get(asset_type, []):
        if not isinstance(content.get(key), list):
            errors.append(f"{asset_type} {key} must be a list")
    if asset_type == "publishing_plan":
        if not isinstance(content.get("gate_policy"), dict):
            errors.append("publishing_plan gate_policy must be an object")
        if content.get("status") not in {"draft", "active", "archived"}:
            errors.append("publishing_plan status must be draft, active, or archived")
    if asset_type == "publishing_log":
        if not isinstance(content.get("rollback_plan"), dict):
            errors.append("publishing_log rollback_plan must be an object")
        if content.get("status") not in {"planned", "published", "failed", "rolled_back"}:
            errors.append("publishing_log status must be planned, published, failed, or rolled_back")
    if asset_type == "operational_metric_snapshot":
        for key in ["read_metrics", "engagement_metrics"]:
            if not isinstance(content.get(key), dict):
                errors.append(f"operational_metric_snapshot {key} must be an object")
    if asset_type == "local_ops_drill_report" and content.get("status") not in {"passed", "warning", "failed"}:
        errors.append("local_ops_drill_report status must be passed, warning, or failed")
    if asset_type == "long_chain_acceptance_report":
        if not isinstance(content.get("quality_trends"), dict):
            errors.append("long_chain_acceptance_report quality_trends must be an object")
        if not isinstance(content.get("publish_gate_summary"), dict):
            errors.append("long_chain_acceptance_report publish_gate_summary must be an object")
        if content.get("recommendation") not in {"pass", "revise", "block"}:
            errors.append("long_chain_acceptance_report recommendation must be pass, revise, or block")
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
