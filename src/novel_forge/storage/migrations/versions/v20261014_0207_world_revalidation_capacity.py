from __future__ import annotations

from .v20261012_0203_capacity_availability_observation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261014_0207_world_revalidation_capacity"
DOWN_REVISION = "20261014_0206_world_disclosure_revalidation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Retain exact complete World revalidation proof through unsent capacity succession; preserve original outputs and recovery history."

_ANCHOR = "WHERE r.continuation_id=runtime_id AND r.successor_operation_id=child_id AND r.chain_depth>0"
_BINDING = """AND (
    (r.target_runtime->'world_host_revalidation' IS NULL AND NOT EXISTS(
        SELECT 1 FROM authority_story_planning_runtime_continuation prior
        WHERE prior.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
          AND prior.successor_operation_id=source.operation_id AND prior.target_runtime->'world_host_revalidation' IS NOT NULL))
    OR EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation prior
        JOIN authority_operation registration ON registration.operation_id=prior.registered_by_operation_id
        WHERE prior.continuation_id=source.command_payload#>>'{payload,runtime_continuation_id}'
          AND prior.successor_operation_id=source.operation_id AND prior.successor_command=source.command_payload->'payload'
          AND prior.project_id=source.project_id AND prior.workspace_id=source.workspace_id
          AND prior.book_id=source.command_payload#>>'{payload,book_id}'
          AND registration.status='SUCCEEDED' AND registration.definition_name='story_planning.runtime_continuation.register'
          AND registration.actor_id=source.actor_id AND registration.project_id=source.project_id AND registration.workspace_id=source.workspace_id
          AND r.target_runtime->'world_host_revalidation'=prior.target_runtime->'world_host_revalidation'
          AND r.target_runtime#>>'{world_host_revalidation,contract_version}' IN ('world-host-revalidation.v1','world-host-revalidation.v2')))
"""
assert PREVIOUS[0].count(_ANCHOR) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_ANCHOR, _ANCHOR + "\n" + _BINDING)]
DOWNGRADE_STATEMENTS: list[str] = []
