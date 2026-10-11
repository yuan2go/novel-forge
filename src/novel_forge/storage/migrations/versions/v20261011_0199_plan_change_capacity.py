from __future__ import annotations

from .v20261010_0197_authorized_planning_capacity import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261011_0199_plan_change_capacity"
DOWN_REVISION = "20261010_0198_recovery_reference_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Admit unsent ChapterGroup capacity succession bound to an exact native Plan Change request without requiring a Narrative Search."

_SEARCH = """AND r.source_command #>> '{narrative_search_planning_horizon,level}'='CHAPTER_GROUP'
          AND jsonb_array_length(r.source_command #> '{narrative_search_planning_horizon,chapter_range}')=2
          AND r.source_command->>'narrative_search_id' IS NOT NULL"""
_CHANGE = """AND ((r.source_command #>> '{narrative_search_planning_horizon,level}'='CHAPTER_GROUP'
          AND jsonb_array_length(r.source_command #> '{narrative_search_planning_horizon,chapter_range}')=2
          AND NULLIF(r.source_command->>'narrative_search_id','') IS NOT NULL)
          OR (COALESCE(r.source_command->>'narrative_search_id','')=''
          AND context.content->>'planning_exact_reference_projection_version'='planning-exact-value-reference.v1'
          AND EXISTS(SELECT 1 FROM authority_asset_version request
            JOIN authority_asset request_asset ON request_asset.asset_id=request.asset_id
            JOIN authority_operation_output_asset request_output ON request_output.asset_version_id=request.asset_version_id
            JOIN authority_operation request_operation ON request_operation.operation_id=request_output.operation_id
            WHERE r.source_command->'change_evidence_version_ids' ? request.asset_version_id
              AND request_asset.asset_type='replan_request' AND request_asset.project_id=r.project_id
              AND request_operation.status='SUCCEEDED'
              AND request_operation.definition_name='planning.change_request.author'
              AND request_operation.project_id=r.project_id AND request_operation.workspace_id=r.workspace_id
              AND request_output.output_key='planning.change_request'
              AND request.content->>'book_id'=r.book_id
              AND request.content->>'affected_scope'='CHAPTER_GROUP'
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(prior.input_snapshot) input
                WHERE input->>'asset_version_id'=request.asset_version_id
                  AND input->>'content_hash'=request.content_hash
                  AND input->>'asset_type'='replan_request'))))"""
assert _SEARCH in PREVIOUS[0]
UPGRADE_STATEMENTS = [PREVIOUS[0].replace(_SEARCH, _CHANGE)]
DOWNGRADE_STATEMENTS: list[str] = []
