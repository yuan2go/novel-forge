from __future__ import annotations

MIGRATION_ID = "20260907_0119_grounded_chapter_acceptance"
DOWN_REVISION = "20260907_0118_preparation_event_lineage"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "repair unaccepted evidence through Chapter recovery; never rewrite accepted history"

UPGRADE_STATEMENTS = [
    """
    CREATE FUNCTION authority_grounded_chapter_acceptance_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE outcome jsonb; draft jsonb; canon jsonb; quality jsonb;
            grounding jsonb; definition_version text; expected_hash text;
    BEGIN
        SELECT operation.definition_version INTO definition_version
        FROM authority_book_chapter_request request
        JOIN authority_operation operation ON operation.operation_id=request.chapter_root_operation_id
        WHERE request.chapter_request_id=NEW.chapter_request_id;
        SELECT version.content INTO outcome
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE version.asset_version_id=NEW.chapter_outcome_asset_version_id AND asset.project_id=NEW.project_id;
        grounding := outcome->'grounding';
        IF grounding IS NULL AND COALESCE(split_part(definition_version, '.', 1), '0')::integer < 3 THEN
            RETURN NEW;
        END IF;
        SELECT version.content INTO draft
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE version.asset_version_id=outcome->>'accepted_draft_asset_version_id' AND asset.project_id=NEW.project_id;
        SELECT version.content INTO canon
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE version.asset_version_id=outcome->>'canon_patch_asset_version_id' AND asset.project_id=NEW.project_id;
        SELECT version.content INTO quality
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE version.asset_version_id=outcome->>'quality_aggregate_asset_version_id' AND asset.project_id=NEW.project_id;
        expected_hash := 'sha256:' || encode(digest(convert_to(draft->>'text', 'UTF8'), 'sha256'), 'hex');
        IF grounding IS NULL OR expected_hash IS NULL
           OR grounding->>'contract_version' IS DISTINCT FROM 'grounded-canon.v1'
           OR grounding->>'semantic_status' IS DISTINCT FROM 'SUPPORTED_CANDIDATE'
           OR grounding->>'project_id' IS DISTINCT FROM NEW.project_id
           OR grounding->>'candidate_asset_version_id' IS DISTINCT FROM outcome->>'accepted_draft_asset_version_id'
           OR grounding->>'text_hash' IS DISTINCT FROM expected_hash
           OR canon->'grounding' IS DISTINCT FROM grounding
           OR quality->>'target_asset_version_id' IS DISTINCT FROM outcome->>'accepted_draft_asset_version_id'
           OR quality->>'canon_patch_version_id' IS DISTINCT FROM outcome->>'canon_patch_asset_version_id'
        THEN
            RAISE EXCEPTION 'Grounded acceptance requires exact final candidate, Canon and Quality lineage'
                USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER authority_grounded_chapter_acceptance_exact
    BEFORE INSERT ON authority_book_chapter_acceptance
    FOR EACH ROW EXECUTE FUNCTION authority_grounded_chapter_acceptance_guard()
    """,
]
