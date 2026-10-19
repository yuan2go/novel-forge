from __future__ import annotations

from .v20261012_0201_working_revision_generation_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = '20261018_0224_working_regeneration_isolation'
DOWN_REVISION = '20261018_0223_working_plan_input_continuation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Retain stopped UNKNOWN history while fencing the exact current unaccepted PlanChange regeneration through existing Kernel isolation.'

ANCESTOR = """CREATE FUNCTION authority_working_group_prefix_preserved(project TEXT, book TEXT, current_version TEXT, ancestor_version TEXT, actor TEXT, workspace TEXT, before_chapter INTEGER)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
WITH RECURSIVE lineage(version_id,path) AS (
 SELECT current_version,ARRAY[current_version]
 UNION ALL
 SELECT correction.target_asset_version_id,lineage.path||correction.target_asset_version_id
 FROM lineage JOIN authority_plan_change_proposal correction ON correction.proposed_asset_version_id=lineage.version_id
 JOIN authority_operation activation ON activation.operation_id=correction.activation_operation_id
 WHERE correction.project_id=project AND correction.book_id=book AND correction.status='ACTIVE'
 AND correction.target_contract_type='CHAPTER_GROUP' AND activation.status='SUCCEEDED'
 AND activation.project_id=project AND activation.workspace_id=workspace AND activation.actor_id=actor
 AND NOT correction.target_asset_version_id=ANY(lineage.path)
 ) SELECT EXISTS(SELECT 1 FROM lineage WHERE version_id=ancestor_version)
 AND EXISTS(SELECT 1 FROM authority_asset_version original JOIN authority_asset original_owner ON original_owner.asset_id=original.asset_id
 JOIN authority_asset_version corrected ON corrected.asset_version_id=current_version
 JOIN authority_asset corrected_owner ON corrected_owner.asset_id=corrected.asset_id
 WHERE original.asset_version_id=ancestor_version AND original_owner.project_id=project AND corrected_owner.project_id=project
 AND original.content->'chapter_range'=corrected.content->'chapter_range'
 AND before_chapter BETWEEN (original.content->'chapter_range'->>0)::integer AND (original.content->'chapter_range'->>1)::integer
 AND NOT EXISTS(SELECT 1 FROM (VALUES ('chapter_function_matrix'),('narrative_event_chain')) field(name)
 WHERE COALESCE(jsonb_typeof(original.content->field.name),'')<>'array' OR COALESCE(jsonb_typeof(corrected.content->field.name),'')<>'array'
 OR (SELECT jsonb_agg(entry.value ORDER BY entry.ordinality) FROM jsonb_array_elements(original.content->field.name) WITH ORDINALITY entry(value,ordinality)
     WHERE (entry.value->>'chapter_number')::integer<before_chapter)
 IS DISTINCT FROM (SELECT jsonb_agg(entry.value ORDER BY entry.ordinality) FROM jsonb_array_elements(corrected.content->field.name) WITH ORDINALITY entry(value,ordinality)
     WHERE (entry.value->>'chapter_number')::integer<before_chapter))) $$"""

_OLD = "root.definition_version='3.10.0-working-revision.v1'"
_NEW = """(root.definition_version='3.10.0-working-revision.v1' OR (
 root.definition_version='3.10.0-working-regeneration.v1'
 AND root.definition_snapshot#>>'{policy,working_regeneration_contract}'='working-plan-regeneration.v1'
 AND root.command_payload#>>'{preparation_report,working_plan_regeneration,contract_version}'='working-plan-regeneration.v1'
 AND book.state='READY' AND book.active_chapter_request_id IS NULL
 AND (root.command_payload->>'chapter')::integer=book.current_chapter
 AND EXISTS(SELECT 1 FROM authority_plan_change_proposal correction
 JOIN authority_operation activation ON activation.operation_id=correction.activation_operation_id
 JOIN story_plan_binding plan ON plan.asset_version_id=root.command_payload#>>'{preparation_report,working_plan_regeneration,corrected_chapter_plan_version_id}'
 JOIN active_story_plan_version active ON active.binding_id=plan.binding_id
 JOIN authority_asset_version version ON version.asset_version_id=plan.asset_version_id
 JOIN authority_book_manuscript_delivery delivered ON delivered.book_run_id=book.book_run_id AND delivered.chapter_number=book.current_chapter
 JOIN authority_book_chapter_request predecessor ON predecessor.chapter_request_id=delivered.chapter_request_id
 JOIN authority_operation original ON original.operation_id=predecessor.chapter_root_operation_id
 WHERE correction.proposal_id=root.command_payload#>>'{preparation_report,working_plan_regeneration,proposal_id}'
 AND correction.status='ACTIVE' AND correction.project_id=book.project_id AND correction.book_id=book.book_id
 AND correction.activation_operation_id=root.command_payload#>>'{preparation_report,working_plan_regeneration,activation_operation_id}'
 AND activation.status='SUCCEEDED' AND activation.actor_id=root.actor_id AND original.actor_id=root.actor_id
 AND original.status='SUCCEEDED' AND plan.project_id=book.project_id AND plan.book_id=book.book_id
 AND plan.contract_type='CHAPTER' AND plan.execution_scope='FROZEN' AND plan.freshness='CURRENT'
 AND (version.content->>'chapter_number')::integer=book.current_chapter
 AND version.content_hash=root.command_payload#>>'{preparation_report,working_plan_regeneration,corrected_chapter_plan_content_hash}'
 AND predecessor.chapter_request_id=root.command_payload#>>'{preparation_report,working_plan_regeneration,predecessor_request_id}'
 AND predecessor.chapter_root_operation_id=root.command_payload#>>'{preparation_report,working_plan_regeneration,predecessor_root_operation_id}'
 AND ((correction.target_contract_type='CHAPTER' AND correction.target_asset_version_id=predecessor.chapter_plan_version
   AND correction.proposed_asset_version_id=plan.asset_version_id)
  OR (correction.target_contract_type='CHAPTER_GROUP' AND correction.proposed_asset_version_id=plan.parent_version_id
   AND authority_working_group_prefix_preserved(book.project_id,book.book_id,correction.proposed_asset_version_id,predecessor.parent_group_version_id,root.actor_id,book.workspace_id,book.current_chapter))))))"""
assert PREVIOUS[0].count(_OLD) == 1
UPGRADE_STATEMENTS = [ANCESTOR, PREVIOUS[0].replace(_OLD, _NEW)]
DOWNGRADE_STATEMENTS: list[str] = []
