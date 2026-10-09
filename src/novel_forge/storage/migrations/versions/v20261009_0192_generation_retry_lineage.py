from __future__ import annotations

from .v20261009_0187_chapter_generation_isolation import UPGRADE_STATEMENTS as CAPACITY_STATEMENTS

MIGRATION_ID = '20261009_0192_generation_retry_lineage'
DOWN_REVISION = '20261009_0191_provider_schema_successor'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Allow verified recovery ancestry to retain completed native stages while enforcing original persisted fault allowance.'

HISTORICAL_CONSTRAINT = next(statement for statement in CAPACITY_STATEMENTS if 'ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check' in statement).split(' CHECK ', 1)[1]
UPGRADE_STATEMENTS = [
    'ALTER TABLE authority_story_planning_runtime_continuation DROP CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check',
    'ALTER TABLE authority_story_planning_runtime_continuation ADD CONSTRAINT authority_story_planning_runtime_continuation_chain_depth_check CHECK (COALESCE(' + HISTORICAL_CONSTRAINT + """,FALSE) OR COALESCE((
      chain_depth>=3
      AND decision_evidence #>> '{failure_retry_counter,counter_source}'='NATIVE_DISPATCH_LINEAGE'
      AND decision_evidence #>> '{failure_retry_counter,scope}'='ORIGINAL_LOGICAL_GENERATION'
      AND (decision_evidence #>> '{failure_retry_counter,failure_attempts}')::int>=1
      AND (decision_evidence #>> '{failure_retry_counter,failure_attempts}')::int <
          (decision_evidence #>> '{failure_retry_counter,maximum_failure_attempts}')::int
      AND ((target_runtime #>> '{generation_isolation,contract_version}'='pure-generation-isolation.v1'
          AND decision_evidence #>> '{remote_outcome}'='UNKNOWN')
        OR (target_runtime #>> '{provider_schema_correction,wire_correction,contract_version}'='codex-nullable-shared-types.v3'
          AND decision_evidence->>'host_revalidation'='provider-schema-correction.v1'
          AND decision_evidence->'failure_retry_counter'=target_runtime #> '{provider_schema_correction,failure_retry_counter}'))
    ),FALSE))""",
]
DOWNGRADE_STATEMENTS: list[str] = []
