from __future__ import annotations

from .v20261006_0160_optional_world_continuation import (
    UPGRADE_STATEMENTS as PREVIOUS_GUARDS,
)
from .v20260913_0131_planning_result_recovery import (
    UPGRADE_STATEMENTS as SOURCE_CONTRACT,
)

MIGRATION_ID = "20261006_0162_stage_repair_policy"
DOWN_REVISION = "20261006_0161_gateway_result_revalidation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain monotonic repair counters and rejected history; bounded stage repair policy applies only to authorized unexecuted creative work"
UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_story_planning_generation DROP CONSTRAINT authority_planning_repair_source_check",
    SOURCE_CONTRACT[3].replace("repair_number<=2", "repair_number<=4"),
    PREVIOUS_GUARDS[0]
    .replace(
        "t->>'version'='creative-execution-template.v3'",
        "t->>'version' IN ('creative-execution-template.v3','creative-execution-template.v4')",
    )
    .replace(
        "        RETURN NEW;",
        """        IF TG_OP='INSERT' AND NEW.repair_of_operation_id IS NOT NULL AND NEW.repair_number>2 AND NOT EXISTS (
            SELECT 1 FROM authority_runtime_policy_selection s
            JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
            JOIN authority_operation policy ON policy.operation_id=v.created_by_operation_id
            JOIN LATERAL jsonb_array_elements(v.content->'execution_templates') t ON TRUE
            WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=NEW.project_id AND policy.status='SUCCEEDED'
              AND t->>'book_id'=NEW.book_id AND t->>'version'='creative-execution-template.v4'
              AND t->>'mode'='CREATIVE_VALIDATION' AND t->'require_literary_qualification'='false'::jsonb
              AND t #>> '{repair_routing,version}'='native-repair-routing.v2'
              AND (t #>> '{repair_routing,max_same_route_repairs}')::int BETWEEN 1 AND 2
        ) THEN
            RAISE EXCEPTION 'PLANNING_STAGE_REPAIR_POLICY_REQUIRED' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;""",
    ),
]
DOWNGRADE_STATEMENTS: list[str] = []
