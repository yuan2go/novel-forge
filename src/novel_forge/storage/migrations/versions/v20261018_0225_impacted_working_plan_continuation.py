from __future__ import annotations

from .v20261018_0223_working_plan_input_continuation import PERMITTED as PREVIOUS

MIGRATION_ID = '20261018_0225_impacted_working_plan_continuation'
DOWN_REVISION = '20261018_0224_working_regeneration_isolation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Continue the exact unsent Chapter correction after native upstream PlanChange removed its impacted active binding; retain zero-send and all historical guards.'

_OLD_JOIN = ''' JOIN active_story_plan_version active ON active.project_id=r.project_id AND active.book_id=r.book_id
 JOIN story_plan_binding binding ON binding.binding_id=active.binding_id AND binding.asset_version_id=change.content->>'target_plan_version_id' '''.rstrip()
_NEW_JOIN = ''' JOIN story_plan_binding binding ON binding.project_id=r.project_id AND binding.book_id=r.book_id
   AND binding.asset_version_id=change.content->>'target_plan_version_id'
 LEFT JOIN active_story_plan_version active ON active.binding_id=binding.binding_id'''
_OLD_SCOPE = "binding.freshness='CURRENT'"
_NEW_SCOPE = '''((binding.freshness='CURRENT' AND active.binding_id IS NOT NULL) OR (
 binding.freshness='IMPACTED' AND binding.contract_type='CHAPTER'
 AND NOT EXISTS(SELECT 1 FROM active_story_plan_version competing WHERE competing.project_id=r.project_id
   AND competing.book_id=r.book_id AND competing.logical_key=binding.logical_key)
 AND EXISTS(SELECT 1 FROM authority_book_manuscript_delivery delivered
 JOIN authority_book_chapter_request original USING(chapter_request_id)
 JOIN authority_operation original_root ON original_root.operation_id=original.chapter_root_operation_id
 JOIN authority_plan_change_proposal correction ON correction.proposal_id=change.content->>'upstream_plan_change_proposal_id'
 JOIN authority_operation activation ON activation.operation_id=correction.activation_operation_id
 JOIN active_story_plan_version parent ON parent.asset_version_id=correction.proposed_asset_version_id
   AND parent.project_id=correction.project_id AND parent.book_id=correction.book_id
 WHERE delivered.book_run_id=book.book_run_id AND delivered.chapter_number=book.current_chapter
 AND original.chapter_plan_version=binding.asset_version_id AND original.parent_group_version_id=binding.parent_version_id
 AND original_root.status='SUCCEEDED' AND original_root.actor_id=source.actor_id
 AND correction.project_id=r.project_id AND correction.book_id=r.book_id AND correction.status='ACTIVE'
 AND correction.target_contract_type='CHAPTER_GROUP' AND activation.status='SUCCEEDED'
 AND activation.project_id=r.project_id AND activation.workspace_id=r.workspace_id AND activation.actor_id=source.actor_id
 AND r.source_command#>>'{input_versions,chapter_group_plan}'=correction.proposed_asset_version_id
 AND authority_working_group_prefix_preserved(r.project_id,r.book_id,correction.proposed_asset_version_id,
   original.parent_group_version_id,source.actor_id,r.workspace_id,book.current_chapter))))'''
assert PREVIOUS.count(_OLD_JOIN) == PREVIOUS.count(_OLD_SCOPE) == 1
UPGRADE_STATEMENTS = [PREVIOUS.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1).replace(_OLD_JOIN, _NEW_JOIN).replace(_OLD_SCOPE, _NEW_SCOPE)]
DOWNGRADE_STATEMENTS: list[str] = []
