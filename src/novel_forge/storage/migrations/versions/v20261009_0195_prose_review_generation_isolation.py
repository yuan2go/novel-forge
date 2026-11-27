from __future__ import annotations

from .v20261009_0194_multi_model_generation_isolation import UPGRADE_STATEMENTS as PREVIOUS

MIGRATION_ID = '20261009_0195_prose_review_generation_isolation'
DOWN_REVISION = '20261009_0194_multi_model_generation_isolation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'Fence a stopped read-only prose review sidecar and resolve its native linked root successor independently of original remote outcome.'

UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_generation_current_operation(source_id text) RETURNS text LANGUAGE sql STABLE AS $$
        WITH RECURSIVE lineage(id,depth) AS (SELECT source_id,0 UNION ALL
          SELECT edge.successor_operation_id,lineage.depth+1 FROM authority_saga_step_successor edge
          JOIN lineage ON edge.predecessor_operation_id=lineage.id WHERE lineage.depth<16)
        SELECT id FROM lineage ORDER BY depth DESC LIMIT 1 $$""",
    PREVIOUS[0].replace("root.definition_name='chapter.slice.run')))", """root.definition_name='chapter.slice.run')) OR (
        o.definition_name='longform.prose_review' AND o.definition_snapshot->>'family'='book_followup_authority'
        AND o.root_operation_id=o.operation_id AND o.parent_operation_id IS NULL
        AND o.definition_snapshot#>>'{policy,body_mutation_allowed}'='false'
        AND o.definition_snapshot#>>'{policy,plan_mutation_allowed}'='false'
        AND o.definition_snapshot#>>'{irreversible_effect_policy,allowed}'='false'
        AND o.command_payload#>>'{payload,book_id}'=NEW.book_id
        AND NEW.proof->>'continuation_id'='followup-generation-successor:'||o.operation_id
        AND EXISTS(SELECT 1 FROM authority_book_prose_review_event event
          JOIN authority_book_prose_review_run run USING(run_id)
          JOIN authority_book_production book USING(book_run_id)
          WHERE event.kind='WINDOW_ADMITTED' AND authority_generation_current_operation(event.content->>'operation_id')=o.operation_id
          AND run.project_id=NEW.project_id AND book.project_id=NEW.project_id
          AND book.workspace_id=NEW.workspace_id AND book.book_id=NEW.book_id)))"""),
]
DOWNGRADE_STATEMENTS: list[str] = []
