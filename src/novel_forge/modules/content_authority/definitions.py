"""Disabled-until-enabled OperationDefinitions with concrete domain handlers."""
from __future__ import annotations
from typing import Any
from novel_forge.modules.content_authority.handlers import CONTENT_DOMAIN_HANDLERS

_OUTPUT_TYPES = {
    "creative.brief.create": "creative_brief", "creative.candidates.evaluate": "candidate_evaluation",
    "creative.candidates.cluster": "candidate_cluster", "creative.project.approve": "project_proposal",
    "production.world.generate": "world_bible", "world.validate": "world_rule_conflict_report",
    "production.character.generate": "character_card", "character.relationships.generate": "relationship_state",
    "theme.question.create": "theme_question", "theme.arc.build": "theme_arc",
    "theme.anti_preaching.evaluate": "anti_preaching_report", "ending.closure.plan": "closure_plan",
    "ending.payoff_matrix.build": "payoff_matrix", "ending.quality.evaluate": "ending_quality_report",
    "longform.motivation.evaluate": "motivation_drift_report", "longform.entity_merge.propose": "entity_merge_proposal",
    "longform.foreshadow_payoff.evaluate": "foreshadow_payoff_report", "longform.world_rule.evaluate": "world_rule_conflict_report",
    "longform.power.evaluate": "power_conflict_report", "longform.pattern.evaluate": "pattern_repetition_report",
    "longform.narrative_debt.evaluate": "narrative_debt_report", "longform.recap.enhance": "longform_recap_report",
}

def content_operation_definitions(*, application_build_id: str, commit_sha: str) -> tuple[dict[str, Any], ...]:
    command = {"type": "object", "required": ["project_id", "input_asset_version_ids", "payload"], "properties": {"project_id": {"type": "string"}, "input_asset_version_ids": {"type": "array", "items": {"type": "string"}}, "payload": {"type": "object"}}, "additionalProperties": False}
    result = {"type": "object", "required": ["asset_version_id", "content_hash"], "properties": {"asset_version_id": {"type": "string"}, "content_hash": {"type": "string"}}, "additionalProperties": False}
    return tuple({
        "name": name, "definition_version": "1.0.0", "family": name.split(".")[0],
        "command_schema_version": f"{name}.command.v1", "result_schema_version": f"{name}.result.v1",
        "enabled": False, "definition_status": "handler_bound", "command_schema": command,
        "result_schema": result, "input_contract": command, "output_contract": result,
        "handler_key": f"novel_forge.content_authority.{name}", "handler_contract_version": "1.0.0",
        "application_build_id": application_build_id, "commit_sha": commit_sha, "execution_mode": "worker",
        "permissions": [name], "approval_policy": {"required": name == "creative.project.approve", "policy_key": "operator.project.approval.v1" if name == "creative.project.approve" else "none"},
        "idempotency_scope": "project:content-domain", "concurrency_key_template": f"project:{{project_id}}:{name}",
        "retry_policy": {"max_attempts": 2}, "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"}, "compensation_policy": {"supported": False, "reason": "append_only_asset_versions"},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [], "projection_consumers": [f"{name.split('.')[0]}_console"],
        "migration_owner": "content-intelligence-authority", "legacy_entrypoints": [],
        "evidence_status": {"documented": True, "implemented": True, "handler_bound": True, "integration_proven": False, "real_provider_proven": False, "longform_proven": False},
        "completion_contract": {"version": f"{name}.completion.v1", "required_asset_selectors": [{"selector": _OUTPUT_TYPES[name], "role": "primary", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}], "required_evidence": ["trace", "audit"]},
        "current_entrypoints": [], "current_handlers": [f"novel_forge.content_authority.{name}"], "migration_status": "handler_bound",
    } for name in CONTENT_DOMAIN_HANDLERS)

__all__ = ["content_operation_definitions"]
