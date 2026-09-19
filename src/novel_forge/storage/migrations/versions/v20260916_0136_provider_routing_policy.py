from __future__ import annotations

MIGRATION_ID = "20260916_0136_provider_routing_policy"
DOWN_REVISION = "20260914_0135_cost_routing_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "append policy repairs; preserve frozen decisions and existing provider identities"
)

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_runtime_policy_version DROP CONSTRAINT authority_runtime_policy_version_owner_check",
    "ALTER TABLE authority_runtime_policy_version ADD CONSTRAINT authority_runtime_policy_version_owner_check CHECK (owner IN ('CHAPTER_GROUP_EXECUTION', 'READER_PROXY', 'BOOK_CONTROL', 'CREATIVE_EXPERIMENT_BUDGET', 'PROVIDER_ROUTING'))",
    """CREATE INDEX authority_routing_chain_idx ON authority_external_effect
       (project_id, operation_id,
        (request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,chain_id}'))
       WHERE effect_type='model.invoke'""",
]
