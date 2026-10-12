from __future__ import annotations

from .v20261010_0196_stopped_cli_timeout_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = "20261012_0201_working_revision_generation_isolation"
DOWN_REVISION = "20261012_0200_generation_history_observations"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Bind stopped working-prose Review, Revision and ReReview to their owning Book and Kernel Saga without fabricating a Chapter production request."

_OLD = "AND root.actor_id=o.actor_id AND root.status='WAITING_CHILDREN' AND root.definition_name='chapter.slice.run'))"
_NEW = """AND root.actor_id=o.actor_id AND root.status='WAITING_CHILDREN' AND root.definition_name='chapter.slice.run')
 OR EXISTS(SELECT 1 FROM authority_saga_step step
 JOIN authority_saga saga USING(saga_id)
 JOIN authority_operation root ON root.operation_id=saga.root_operation_id
 JOIN authority_book_production book ON book.book_run_id=root.command_payload#>>'{preparation_report,working_revision,book_run_id}'
 JOIN authority_asset_version source ON source.asset_version_id=root.command_payload#>>'{preparation_report,working_revision,source_asset_version_id}'
 JOIN authority_asset source_owner ON source_owner.asset_id=source.asset_id
 WHERE step.operation_id=o.operation_id AND step.saga_id=o.saga_id AND root.operation_id=o.root_operation_id
 AND root.definition_name='chapter.slice.run' AND root.definition_version='3.10.0-working-revision.v1'
 AND root.definition_snapshot#>>'{policy,working_revision_contract}'='chapter-working-revision.v1'
 AND root.command_payload#>>'{preparation_report,working_revision,contract_version}'='chapter-working-revision.v1'
 AND root.status='WAITING_CHILDREN' AND root.actor_id=o.actor_id
 AND root.project_id=NEW.project_id AND root.workspace_id=NEW.workspace_id AND root.command_payload->>'book_id'=NEW.book_id
 AND book.project_id=NEW.project_id AND book.workspace_id=NEW.workspace_id AND book.book_id=NEW.book_id
 AND book.state NOT IN ('PAUSED','ABORTED','CANCELLED')
 AND (root.command_payload->>'chapter')::integer>book.accepted_through_chapter
 AND (root.command_payload->>'chapter')::integer<=book.current_chapter
 AND source_owner.project_id=NEW.project_id AND source.content_hash=root.command_payload#>>'{preparation_report,working_revision,source_content_hash}'
 AND root.input_asset_snapshot @> jsonb_build_array(root.command_payload#>'{preparation_report,working_revision,source_inputs,draft}')
 AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
 WHERE cancellation.project_id=book.project_id AND book.stable_idempotency_key=cancellation.formation_run_id||':production'))))"""
assert PREVIOUS[0].count(_OLD) == 1
UPGRADE_STATEMENTS = [PREVIOUS[0].replace("AND EXISTS(SELECT 1 FROM authority_saga_step step", "AND (EXISTS(SELECT 1 FROM authority_saga_step step", 1).replace(_OLD, _NEW).replace(
    "'chapter.review.evaluate','chapter.revision.apply'", "'chapter.review.evaluate','chapter.revision.apply','chapter.revision.review'")]
DOWNGRADE_STATEMENTS: list[str] = []
