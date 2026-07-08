from __future__ import annotations

from copy import deepcopy
from typing import Any

AGENT_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "chief_editor": {
        "agent": "Chief Editor Agent",
        "permission_profile": "plans_docs_acceptance_only",
        "allowed_tools": ["read_asset", "write_doc", "update_plan", "run_validation", "record_decision"],
        "allowed_write_types": ["workflow_run"],
        "forbidden": ["claim_completion_without_validation", "write_raw_source_text", "bypass_review_gate"],
    },
    "engineering": {
        "agent": "Engineering Agent",
        "permission_profile": "code_tests_workflow_glue",
        "allowed_tools": ["read_file", "write_file", "run_tests", "run_validation", "schema_check", "run_worker_task"],
        "allowed_write_types": ["workflow_run", "task_status"],
        "forbidden": ["break_schema_compatibility_silently", "overwrite_user_changes", "skip_tests_for_code_changes"],
    },
    "workflow": {
        "agent": "Workflow Agent",
        "permission_profile": "workflow_coordination_and_recovery",
        "allowed_tools": ["read_asset", "run_validation", "run_worker_task", "record_checkpoint", "coordinate_loop"],
        "allowed_write_types": ["workflow_run", "task_status", "agent_run", "chapter_production_run", "loop_run", "loop_step", "loop_checkpoint", "loop_report"],
        "forbidden": ["bypass_schema_validation", "suppress_blocking_issue", "execute_unregistered_operation"],
    },
    "context": {
        "agent": "Context Agent",
        "permission_profile": "context_selection_budget_and_replay",
        "allowed_tools": ["read_asset", "build_context_plan", "build_context_bundle", "run_retrieval", "run_validation"],
        "allowed_write_types": ["context_build_plan", "context_bundle", "rag_quality_report", "hybrid_retrieval_report", "memory_retrieval_report"],
        "forbidden": ["include_raw_source_text_in_generation_context", "overfill_token_budget_without_warning", "hide_actual_context"],
    },
    "knowledge": {
        "agent": "Knowledge Agent",
        "permission_profile": "reference_to_abstract_knowledge_only",
        "allowed_tools": [
            "read_asset",
            "read_skill",
            "call_model_adapter",
            "write_knowledge_card",
            "write_decomposition_report",
            "run_validation",
            "record_validation_status",
        ],
        "allowed_write_types": ["knowledge_card", "decomposition_report", "task_status", "workflow_run"],
        "forbidden": ["copy_raw_source_expression", "mix_raw_sources_with_generated_assets", "write_draft_prose"],
    },
    "material": {
        "agent": "Material Agent",
        "permission_profile": "abstract_material_library_only",
        "allowed_tools": ["read_asset", "read_skill", "write_material_card", "run_validation", "record_validation_status"],
        "allowed_write_types": ["material_card", "task_status", "workflow_run"],
        "forbidden": ["copy_story_specific_characters", "copy_story_specific_settings", "write_draft_prose"],
    },
    "topic": {
        "agent": "Planner Agent",
        "permission_profile": "topic_generation_from_abstract_materials_only",
        "allowed_tools": ["read_asset", "call_model_adapter", "write_topic_seed", "run_validation"],
        "allowed_write_types": ["topic_seed", "task_status", "workflow_run"],
        "forbidden": ["copy_protected_premise", "write_draft_prose", "use_unapproved_raw_source"],
    },
    "worldbuilding": {
        "agent": "Worldbuilding Agent",
        "permission_profile": "world_rules_from_project_topic_only",
        "allowed_tools": ["read_asset", "write_world_bible", "run_validation"],
        "allowed_write_types": ["world_bible", "continuity_bible", "foreshadowing_thread", "power_scale_rule", "task_status", "workflow_run"],
        "forbidden": ["copy_source_world", "merge_cross_project_canon", "write_draft_prose"],
    },
    "character": {
        "agent": "Character Agent",
        "permission_profile": "character_design_from_project_world_only",
        "allowed_tools": ["read_asset", "write_character_card", "run_validation"],
        "allowed_write_types": ["character_card", "task_status", "workflow_run"],
        "forbidden": ["copy_story_specific_character", "copy_protected_name_cluster", "write_draft_prose"],
    },
    "outline": {
        "agent": "Outline Agent",
        "permission_profile": "outline_generation_from_project_character_only",
        "allowed_tools": ["read_asset", "call_model_adapter", "write_outline", "write_outline_version", "run_validation"],
        "allowed_write_types": ["outline", "outline_version", "long_form_macro_plan", "task_status", "workflow_run"],
        "forbidden": ["copy_plot_sequence", "write_draft_prose", "ignore_long_form_constraints"],
    },
    "chapter_plan": {
        "agent": "Chapter Plan Agent",
        "permission_profile": "chapter_plan_generation_from_project_outline_only",
        "allowed_tools": ["read_asset", "call_model_adapter", "write_chapter_plan", "write_chapter_plan_version", "run_validation"],
        "allowed_write_types": ["chapter_plan", "chapter_plan_version", "task_status", "workflow_run"],
        "forbidden": ["skip_project_profiles", "ignore_continuity_feedback_or_quality_standard", "write_draft_prose"],
    },
    "creative_asset": {
        "agent": "Material Agent",
        "permission_profile": "schema_backed_creative_asset_library_only",
        "allowed_tools": ["read_asset", "write_creative_asset", "run_validation"],
        "allowed_write_types": [
            "platform_profile",
            "genre_market_profile",
            "creative_strategy_profile",
            "topic_seed",
            "topic_fit_report",
            "world_bible",
            "character_card",
            "continuity_bible",
            "foreshadowing_thread",
            "power_scale_rule",
            "style_profile",
            "style_decomposition_report",
            "style_blend_preset",
            "quality_standard_profile",
            "review_rule_pack",
            "quality_score_report",
            "writing_template",
            "craft_template",
            "material_card",
            "knowledge_card",
            "asset_collection",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["copy_protected_expression", "write_draft_prose", "create_unscoped_project_asset"],
    },
    "analysis": {
        "agent": "Analysis Agent",
        "permission_profile": "reference_analysis_to_abstract_reports_only",
        "allowed_tools": [
            "read_asset",
            "read_skill",
            "call_model_adapter",
            "write_analysis_report",
            "write_converted_creative_asset",
            "run_validation",
            "record_validation_status",
        ],
        "allowed_write_types": [
            "common_novel_analysis_report",
            "web_fiction_business_analysis_report",
            "published_fiction_analysis_report",
            "classic_literary_analysis_report",
            "analysis_conversion_report",
            "material_card",
            "knowledge_card",
            "writing_template",
            "craft_template",
            "review_rule_pack",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["copy_raw_source_expression", "write_draft_prose", "insert_reference_report_into_generation_rag"],
    },
    "draft": {
        "agent": "Draft Agent",
        "permission_profile": "draft_generation_from_approved_context",
        "allowed_tools": ["read_asset", "call_model_adapter", "write_draft_chapter", "write_draft_version", "write_generation_run", "run_validation"],
        "allowed_write_types": ["draft_chapter", "draft_version", "generation_run", "task_status", "workflow_run"],
        "forbidden": ["copy_protected_text", "read_unapproved_raw_sources", "overwrite_existing_draft"],
    },
    "review": {
        "agent": "Review Agent",
        "permission_profile": "critique_without_overwrite",
        "allowed_tools": [
            "read_asset",
            "call_model_adapter",
            "write_review_report",
            "write_revision_plan",
            "write_quality_score_report",
            "write_style_review_report",
            "write_originality_report",
            "write_chapter_audit_report",
            "run_validation",
        ],
        "allowed_write_types": [
            "review_report",
            "revision_plan",
            "quality_score_report",
            "style_review_report",
            "originality_report",
            "chapter_audit_report",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["overwrite_drafts_directly", "ignore_copyright_boundary", "suppress_quality_warnings"],
    },
    "publishing": {
        "agent": "Publishing Agent",
        "permission_profile": "release_packaging_after_quality_gates_only",
        "allowed_tools": [
            "read_asset",
            "write_publish_gate_report",
            "write_release_package",
            "write_publishing_plan",
            "write_publishing_log",
            "run_validation",
        ],
        "allowed_write_types": ["publish_gate_report", "release_package", "publishing_plan", "publishing_log", "task_status", "workflow_run"],
        "forbidden": ["publish_blocked_content", "skip_originality_gate", "write_draft_prose"],
    },
    "platform_strategy": {
        "agent": "Platform Compliance Agent",
        "permission_profile": "platform_strategy_and_publish_adapter_governance",
        "allowed_tools": [
            "read_asset",
            "write_platform_profile",
            "write_platform_strategy_pack",
            "write_platform_gate",
            "write_platform_publish_adapter",
            "write_platform_feedback_backflow",
            "run_validation",
        ],
        "allowed_write_types": [
            "platform_profile",
            "platform_rhythm_rule",
            "platform_opening_gate",
            "platform_chapter_gate",
            "platform_retention_risk",
            "platform_publish_adapter",
            "platform_feedback_backflow",
            "platform_strategy_pack",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["bypass_publish_gate", "weaken_originality_boundary_for_platform_fit", "write_draft_prose"],
    },
    "style": {
        "agent": "Style Agent",
        "permission_profile": "parameterized_style_analysis_without_author_imitation",
        "allowed_tools": [
            "read_asset",
            "write_style_decomposition_report",
            "write_style_review_report",
            "run_validation",
        ],
        "allowed_write_types": [
            "style_decomposition_report",
            "style_review_report",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["imitate_specific_author", "copy_signature_phrases", "write_draft_prose"],
    },
    "ai_editor": {
        "agent": "AI Editor Agent",
        "permission_profile": "patch_based_editing_with_diff_and_rollback",
        "allowed_tools": [
            "read_asset",
            "call_model_adapter",
            "write_editor_patch",
            "write_draft_chapter",
            "write_draft_diff_report",
            "write_draft_version",
            "write_generation_run",
            "run_validation",
        ],
        "allowed_write_types": ["editor_patch", "draft_chapter", "draft_diff_report", "draft_version", "generation_run", "task_status", "workflow_run"],
        "forbidden": ["overwrite_drafts_without_patch", "apply_unreviewed_high_risk_patch", "remove_copyright_boundary"],
    },
    "continuity": {
        "agent": "Continuity Agent",
        "permission_profile": "long_form_consistency_graph_and_reports",
        "allowed_tools": [
            "read_asset",
            "build_continuity_graph",
            "build_novel_kg",
            "write_continuity_graph_snapshot",
            "write_canon_graph_snapshot",
            "write_novel_kg_snapshot",
            "write_canon_patch",
            "write_chapter_continuity_report",
            "write_continuity_bible",
            "run_validation",
        ],
        "allowed_write_types": [
            "continuity_graph_snapshot",
            "canon_graph_snapshot",
            "novel_kg_snapshot",
            "canon_patch",
            "chapter_continuity_report",
            "continuity_bible",
            "foreshadowing_thread",
            "power_scale_rule",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["invent_canon_without_source", "merge_cross_project_continuity", "suppress_continuity_warnings"],
    },
    "model_evaluation": {
        "agent": "Model Evaluation Agent",
        "permission_profile": "benchmark_models_without_story_mutation",
        "allowed_tools": [
            "read_asset",
            "call_model_adapter",
            "write_model_profile",
            "write_model_benchmark_task",
            "write_model_benchmark_run",
            "write_model_comparison_report",
            "write_model_routing_policy",
            "write_prompt_version",
            "write_prompt_regression_report",
            "run_validation",
        ],
        "allowed_write_types": [
            "model_profile",
            "model_benchmark_task",
            "model_benchmark_run",
            "model_comparison_report",
            "model_routing_policy",
            "prompt_version",
            "prompt_regression_report",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["write_draft_prose", "change_default_model_without_benchmark", "ignore_cost_or_failure_rate"],
    },
    "feedback": {
        "agent": "Feedback Agent",
        "permission_profile": "reader_feedback_import_and_aggregate_insight_only",
        "allowed_tools": [
            "read_asset",
            "read_draft_or_explicit_text",
            "normalize_platform_metrics",
            "import_feedback_file",
            "analyze_feedback",
            "create_feedback_backflow_plan",
            "write_feedback_import_batch",
            "write_reader_feedback",
            "write_feedback_cluster",
            "write_feedback_backflow_plan",
            "write_plan_adjustment_proposal",
            "write_review_rule_update_proposal",
            "write_feedback_kg_patch",
            "write_feedback_insight",
            "write_reader_sentiment_report",
            "write_reader_simulation_report",
            "write_operational_metric_snapshot",
            "write_platform_feedback_backflow",
            "write_feedback_learning_assets",
            "write_reader_feedback_backflow_report",
            "update_project_workspace",
            "update_production_feedback_constraints",
            "run_validation",
        ],
        "allowed_write_types": [
            "feedback_import_batch",
            "reader_feedback",
            "feedback_cluster",
            "feedback_backflow_plan",
            "plan_adjustment_proposal",
            "review_rule_update_proposal",
            "feedback_kg_patch",
            "feedback_insight",
            "reader_sentiment_report",
            "reader_simulation_report",
            "operational_metric_snapshot",
            "reader_feedback_backflow_report",
            "platform_feedback_backflow",
            "project_workspace_state",
            "outline",
            "chapter_plan",
            "review_rule_pack",
            "topic_seed",
            "writing_template",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["write_draft_prose", "store_private_reader_identity", "copy_reader_comments_into_story_text"],
    },
    "longform_recap": {
        "agent": "Longform Recap Agent",
        "permission_profile": "longform_recap_memory_and_continuity_writeback",
        "allowed_tools": [
            "read_asset",
            "build_context_bundle",
            "coordinate_loop",
            "write_longform_recap_report",
            "write_canon_patch",
            "write_character_state_ledger",
            "write_foreshadowing_graph",
            "write_revision_task",
            "run_validation",
        ],
        "allowed_write_types": [
            "longform_recap_report",
            "canon_patch",
            "character_state_ledger",
            "foreshadowing_graph",
            "arc_plan",
            "revision_task",
            "review_issue",
            "loop_run",
            "loop_step",
            "loop_checkpoint",
            "loop_report",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["silently_mutate_accepted_canon", "write_draft_prose", "overwrite_recap_history_without_version"],
    },
    "training": {
        "agent": "Training Agent",
        "permission_profile": "exercise_generation_without_production_mutation",
        "allowed_tools": ["read_asset", "write_training_exercise", "run_validation"],
        "allowed_write_types": ["training_exercise", "task_status", "workflow_run"],
        "forbidden": ["turn_training_output_into_canon", "copy_reference_expression", "write_final_chapter"],
    },
    "metrics": {
        "agent": "Chief Editor Agent",
        "permission_profile": "production_observability_snapshot_only",
        "allowed_tools": [
            "read_asset",
            "collect_metrics",
            "run_failure_drill",
            "run_long_chain_acceptance",
            "write_project_metric_snapshot",
            "write_local_ops_drill_report",
            "write_long_chain_acceptance_report",
            "run_validation",
        ],
        "allowed_write_types": [
            "project_metric_snapshot",
            "local_ops_drill_report",
            "long_chain_acceptance_report",
            "task_status",
            "workflow_run",
        ],
        "forbidden": ["mutate_story_assets", "claim_completion_without_validation", "hide_failed_tasks"],
    },
    "settings": {
        "agent": "Engineering Agent",
        "permission_profile": "local_settings_without_saas_features",
        "allowed_tools": ["read_asset", "write_local_settings_profile", "run_validation"],
        "allowed_write_types": ["local_settings_profile", "task_status", "workflow_run"],
        "forbidden": ["enable_saas_auth_billing", "bypass_schema_validation", "disable_project_scope_guard_silently"],
    },
    "quality": {
        "agent": "Quality Agent",
        "permission_profile": "validation_and_risk_reporting",
        "allowed_tools": ["read_asset", "run_validation", "write_risk_report", "record_failure"],
        "allowed_write_types": ["workflow_run", "task_status"],
        "forbidden": ["suppress_warnings", "mark_invalid_output_as_passed", "bypass_schema_validation"],
    },
}

AGENT_PROFILE_ALIASES: dict[str, str] = {
    "editor_in_chief": "chief_editor",
    "chief_editor_agent": "chief_editor",
    "detailed_outline": "chapter_plan",
    "detailed_outline_agent": "chapter_plan",
    "chapter_writer": "draft",
    "chapter_writer_agent": "draft",
    "writer": "draft",
    "reviewer": "review",
    "reviewer_agent": "review",
    "revision": "ai_editor",
    "revision_agent": "ai_editor",
    "canon_guardian": "continuity",
    "canon_guardian_agent": "continuity",
    "foreshadowing": "continuity",
    "foreshadowing_agent": "continuity",
    "character_consistency": "continuity",
    "character_consistency_agent": "continuity",
    "multidisciplinary_knowledge": "knowledge",
    "multidisciplinary_knowledge_agent": "knowledge",
    "platform_compliance": "platform_strategy",
    "platform_compliance_agent": "platform_strategy",
    "eval": "model_evaluation",
    "eval_agent": "model_evaluation",
    "release_gate": "publishing",
    "release_gate_agent": "publishing",
}

SKILL_AGENT_MAP = {
    "agent-loop-governance": "workflow",
    "analysis-to-asset-conversion": "analysis",
    "anti-copy-abstraction": "knowledge",
    "canon-continuity-graph": "continuity",
    "chapter-outline": "chapter_plan",
    "character-design": "character",
    "classic-literary-depth-analysis": "analysis",
    "context-builder-source-isolation": "context",
    "hot-novel-business-deconstruction": "analysis",
    "hot-novel-deconstruction": "knowledge",
    "long-outline": "outline",
    "material-curation": "material",
    "mkaos-knowledge-asset-os": "knowledge",
    "multidisciplinary-knowledge": "knowledge",
    "narrative-beat-design": "outline",
    "novel-os-engineering-audit": "engineering",
    "platform-strategy-os": "platform_strategy",
    "project-planning": "chief_editor",
    "prose-generation": "draft",
    "provider-runtime-policy": "model_evaluation",
    "publish-release-gate-os": "publishing",
    "published-fiction-craft-analysis": "analysis",
    "quality-review": "review",
    "reader-feedback": "feedback",
    "review-issue-gate": "review",
    "skill-governance": "engineering",
    "topic-development": "topic",
    "training-exercise": "training",
    "worldbuilding": "worldbuilding",
}


def agent_runtime_profile(agent_key: str) -> dict[str, Any]:
    key = _canonical_agent_key(agent_key)
    if key not in AGENT_RUNTIME_PROFILES:
        raise ValueError(f"unknown agent runtime profile: {agent_key}")
    return deepcopy(AGENT_RUNTIME_PROFILES[key])


def runtime_profile_for_skill(skill: str) -> dict[str, Any]:
    key = SKILL_AGENT_MAP.get(skill, "quality")
    profile = agent_runtime_profile(key)
    profile["skill"] = skill
    profile["boundary_contract"] = {
        "input_traceability_required": True,
        "schema_validation_required": True,
        "output_path_required": True,
        "validation_status_required": True,
        "storage_boundary": "write only schema-backed assets in the allowed write types",
    }
    return profile


def validate_tool_allowed(profile: dict[str, Any], tool_name: str) -> None:
    allowed = {str(item) for item in profile.get("allowed_tools", [])}
    if tool_name not in allowed:
        raise PermissionError(
            f"{profile.get('agent', 'agent')} cannot use tool {tool_name!r}; "
            f"allowed tools: {', '.join(sorted(allowed))}"
        )


def validate_write_type_allowed(profile: dict[str, Any], asset_type: str) -> None:
    allowed = {str(item) for item in profile.get("allowed_write_types", [])}
    if asset_type not in allowed:
        raise PermissionError(
            f"{profile.get('agent', 'agent')} cannot write asset type {asset_type!r}; "
            f"allowed write types: {', '.join(sorted(allowed))}"
        )


def enforce_agent_action(profile: dict[str, Any], tool_name: str, output_type: str | None = None) -> None:
    validate_tool_allowed(profile, tool_name)
    if output_type:
        validate_write_type_allowed(profile, output_type)


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" agent", "").replace(" ", "_").replace("-", "_")


def _canonical_agent_key(agent_key: str) -> str:
    normalized = _normalize(agent_key)
    return AGENT_PROFILE_ALIASES.get(normalized, normalized)
