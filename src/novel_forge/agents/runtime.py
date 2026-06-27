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
        "allowed_tools": ["read_file", "write_file", "run_tests", "run_validation", "schema_check"],
        "allowed_write_types": ["workflow_run", "task_status"],
        "forbidden": ["break_schema_compatibility_silently", "overwrite_user_changes", "skip_tests_for_code_changes"],
    },
    "knowledge": {
        "agent": "Knowledge Agent",
        "permission_profile": "reference_to_abstract_knowledge_only",
        "allowed_tools": [
            "read_asset",
            "read_skill",
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
    "analysis": {
        "agent": "Analysis Agent",
        "permission_profile": "reference_analysis_to_abstract_reports_only",
        "allowed_tools": [
            "read_asset",
            "read_skill",
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
        "allowed_tools": ["read_asset", "call_model_adapter", "write_draft_chapter", "run_validation"],
        "allowed_write_types": ["draft_chapter", "task_status", "workflow_run"],
        "forbidden": ["copy_protected_text", "read_unapproved_raw_sources", "overwrite_existing_draft"],
    },
    "review": {
        "agent": "Review Agent",
        "permission_profile": "critique_without_overwrite",
        "allowed_tools": ["read_asset", "call_model_adapter", "write_review_report", "write_revision_plan", "run_validation"],
        "allowed_write_types": ["review_report", "revision_plan", "task_status", "workflow_run"],
        "forbidden": ["overwrite_drafts_directly", "ignore_copyright_boundary", "suppress_quality_warnings"],
    },
    "quality": {
        "agent": "Quality Agent",
        "permission_profile": "validation_and_risk_reporting",
        "allowed_tools": ["read_asset", "run_validation", "write_risk_report", "record_failure"],
        "allowed_write_types": ["workflow_run", "task_status"],
        "forbidden": ["suppress_warnings", "mark_invalid_output_as_passed", "bypass_schema_validation"],
    },
}

SKILL_AGENT_MAP = {
    "hot-novel-deconstruction": "knowledge",
    "hot-novel-business-deconstruction": "analysis",
    "published-fiction-craft-analysis": "analysis",
    "classic-literary-depth-analysis": "analysis",
    "analysis-to-asset-conversion": "analysis",
    "anti-copy-abstraction": "knowledge",
    "multidisciplinary-knowledge": "knowledge",
    "long-outline": "chief_editor",
    "worldbuilding": "material",
    "character-design": "material",
    "chapter-outline": "chief_editor",
    "prose-generation": "draft",
    "quality-review": "review",
    "reader-feedback": "review",
}


def agent_runtime_profile(agent_key: str) -> dict[str, Any]:
    key = _normalize(agent_key)
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
