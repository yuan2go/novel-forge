from __future__ import annotations

MIGRATION_ID = "20260914_0135_cost_routing_indexes"
DOWN_REVISION = "20260914_0134_opening_capacity_continuation"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append index repairs; retain immutable Provider identities and routing evidence"

UPGRADE_STATEMENTS = [
    """CREATE INDEX authority_effect_model_budget_idx ON authority_external_effect
       (project_id, model_id, external_effect_id) WHERE effect_type='model.invoke'""",
    """CREATE INDEX authority_routing_decision_asset_idx ON authority_asset
       (project_id,asset_id) WHERE asset_type='routing_decision'""",
    """CREATE INDEX authority_model_call_evidence_idx ON authority_asset_version
       ((COALESCE(content->'provider_evidence',content)->>'provider_id'),
        (COALESCE(content->'provider_evidence',content)->>'model_id'),created_at DESC)
       WHERE content->>'type'='model_call_log' OR content->>'schema_version'='source-model-call-log.v1'""",
]
