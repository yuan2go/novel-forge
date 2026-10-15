from __future__ import annotations

from .v20260806_0073_core_functional_loops import UPGRADE_STATEMENTS as ORIGINAL

MIGRATION_ID = "20261014_0209_planning_input_scope_point_reads"
DOWN_REVISION = "20261014_0208_book_method_scope_context"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Preserve Planning input scope checks while locating each immutable input version before reading its Book metadata."

_FUNCTION = next(s for s in ORIGINAL if "CREATE OR REPLACE FUNCTION novel_forge_validate_core_functional_scope()" in s)
_OLD = """EXISTS (
                SELECT 1
                FROM jsonb_array_elements(NEW.input_snapshot) AS item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=item->>'asset_version_id'
                      AND asset.project_id=NEW.project_id
                      AND COALESCE(version.content->>'book_id', NEW.book_id)=NEW.book_id
                )
            )"""
assert _FUNCTION.count(_OLD) == 1
UPGRADE_STATEMENTS = [
    """CREATE FUNCTION authority_planning_input_scope_valid(snapshot JSONB, project TEXT, book TEXT)
    RETURNS BOOLEAN LANGUAGE plpgsql STABLE AS $$
    DECLARE item JSONB; owner_project TEXT; owner_book TEXT;
    BEGIN
        FOR item IN SELECT * FROM jsonb_array_elements(snapshot) LOOP
            SELECT asset.project_id, version.content->>'book_id' INTO owner_project,owner_book
            FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
            WHERE version.asset_version_id=item->>'asset_version_id';
            IF NOT FOUND OR owner_project IS DISTINCT FROM project
                OR COALESCE(owner_book,book) IS DISTINCT FROM book THEN
                RETURN FALSE;
            END IF;
        END LOOP;
        RETURN TRUE;
    END; $$""",
    _FUNCTION.replace(_OLD, "NOT authority_planning_input_scope_valid(NEW.input_snapshot,NEW.project_id,NEW.book_id)"),
]
DOWNGRADE_STATEMENTS: list[str] = []
