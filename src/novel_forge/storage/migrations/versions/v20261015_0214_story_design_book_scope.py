from __future__ import annotations

from .v20261014_0206_story_design_book_namespace import UPGRADE_STATEMENTS as SCOPE_STATEMENTS

MIGRATION_ID = "20261015_0214_story_design_book_scope"
DOWN_REVISION = "20261015_0213_source_method_isolation"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Bind only proven Story Design Book lineage, reject conflicting ownership before backfill, and retain unproved legacy scope."

_ANCHOR = """SELECT NULLIF(version.content->>'book_id','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=p_project AND version.asset_version_id=p_asset"""
_ADDITIONAL_SCOPE = """
        UNION ALL
        SELECT NULLIF(version.content #>> '{scope,book_id}','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=p_project AND version.asset_version_id=p_asset
        UNION ALL
        SELECT NULLIF(version.content #>> '{creative_input_selection,book_id}','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=p_project AND version.asset_version_id=p_asset
        UNION ALL
        SELECT book.book_id FROM authority_operation_output_asset output
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
        JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=operation.root_operation_id
        JOIN authority_book_production book ON book.book_run_id=request.book_run_id
        WHERE output.asset_version_id=p_asset AND book.project_id=p_project
          AND operation.project_id=p_project"""
assert SCOPE_STATEMENTS[0].count(_ANCHOR) == 1
BOOK_SCOPE_STATEMENT = SCOPE_STATEMENTS[0].replace(_ANCHOR, _ANCHOR + _ADDITIONAL_SCOPE)

_SCOPES = """
    SELECT state.project_id,state.asset_version_id,scope.book_id
    FROM authority_story_design_version_state state
    CROSS JOIN LATERAL (
        SELECT generation.book_id FROM authority_story_planning_candidate candidate
        JOIN authority_story_planning_generation generation USING(generation_id,project_id,book_id)
        WHERE candidate.project_id=state.project_id AND candidate.candidate_asset_version_id=state.asset_version_id
        UNION ALL SELECT binding.book_id FROM story_plan_binding binding
        WHERE binding.project_id=state.project_id AND binding.asset_version_id=state.asset_version_id
        UNION ALL SELECT book_id FROM authority_book
        WHERE project_id=state.project_id AND current_book_design_asset_version_id=state.asset_version_id
        UNION ALL SELECT NULLIF(version.content->>'book_id','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=state.project_id AND version.asset_version_id=state.asset_version_id
        UNION ALL SELECT NULLIF(version.content #>> '{scope,book_id}','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=state.project_id AND version.asset_version_id=state.asset_version_id
        UNION ALL SELECT NULLIF(version.content #>> '{creative_input_selection,book_id}','') FROM authority_asset_version version
        JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=state.project_id AND version.asset_version_id=state.asset_version_id
        UNION ALL SELECT book.book_id FROM authority_operation_output_asset output
        JOIN authority_operation operation ON operation.operation_id=output.operation_id
        JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=operation.root_operation_id
        JOIN authority_book_production book ON book.book_run_id=request.book_run_id
        WHERE output.asset_version_id=state.asset_version_id AND book.project_id=state.project_id
          AND operation.project_id=state.project_id
    ) scope WHERE scope.book_id IS NOT NULL
"""
PREFLIGHT_STATEMENTS = [
    "WITH scopes AS (" + _SCOPES + """), ambiguous AS (
        SELECT project_id,asset_version_id FROM scopes GROUP BY project_id,asset_version_id
        HAVING count(DISTINCT book_id)>1)
    SELECT 'STORY_DESIGN_BOOK_LINEAGE_AMBIGUOUS',count(*) FROM ambiguous
    UNION ALL SELECT 'STORY_DESIGN_BOOK_OWNER_MISSING',count(*) FROM scopes
    WHERE NOT EXISTS(SELECT 1 FROM authority_book book
        WHERE book.project_id=scopes.project_id AND book.book_id=scopes.book_id)""",
]
UPGRADE_STATEMENTS = [BOOK_SCOPE_STATEMENT, *SCOPE_STATEMENTS[1:]]
DOWNGRADE_STATEMENTS: list[str] = []
