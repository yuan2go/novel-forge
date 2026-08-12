from __future__ import annotations


MIGRATION_ID = "20260811_0079_source_import_scope_closure"
DOWN_REVISION = "20260811_0078_reprocessing_action_expansion"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair cross-project Source/import references or quarantine the invalid rows"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_import_job
      ADD CONSTRAINT authority_source_import_job_snapshot_fk
        FOREIGN KEY(repository_snapshot_asset_version_id)
        REFERENCES authority_source_repository_snapshot(asset_version_id),
      ADD CONSTRAINT authority_source_import_job_previous_snapshot_fk
        FOREIGN KEY(previous_snapshot_asset_version_id)
        REFERENCES authority_source_repository_snapshot(asset_version_id)
    """,
    """
    CREATE INDEX authority_source_import_job_snapshot_idx
    ON authority_source_import_job(repository_snapshot_asset_version_id)
    WHERE repository_snapshot_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_import_job_previous_snapshot_idx
    ON authority_source_import_job(previous_snapshot_asset_version_id)
    WHERE previous_snapshot_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_import_job_workspace_idx
    ON authority_source_import_job(workspace_id)
    """,
    """
    CREATE INDEX authority_source_import_work_project_idx
    ON authority_source_import_work(project_id)
    """,
    """
    CREATE INDEX authority_source_import_work_target_idx
    ON authority_source_import_work(target_asset_version_id)
    WHERE target_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_repository_file_operation_idx
    ON authority_source_repository_file(processing_operation_id)
    WHERE processing_operation_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_repository_snapshot_workspace_idx
    ON authority_source_repository_snapshot(workspace_id)
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_source_import_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE payload JSONB := to_jsonb(NEW);
    DECLARE expected_project TEXT := payload->>'project_id';
    DECLARE ref_value TEXT;
    DECLARE actual_project TEXT;
    DECLARE transform_source_document_id TEXT;
    BEGIN
        IF payload ? 'workspace_id' THEN
            SELECT project_id INTO actual_project
            FROM authority_workspace WHERE workspace_id = payload->>'workspace_id';
            IF actual_project IS DISTINCT FROM expected_project THEN
                RAISE EXCEPTION 'source import workspace scope mismatch';
            END IF;
        END IF;
        FOREACH ref_value IN ARRAY ARRAY[
            payload->>'discovery_operation_id', payload->>'created_by_operation_id',
            payload->>'operation_id', payload->>'processing_operation_id',
            payload->>'child_operation_id'
        ] LOOP
            IF COALESCE(ref_value, '') <> '' THEN
                SELECT project_id INTO actual_project
                FROM authority_operation WHERE operation_id = ref_value;
                IF actual_project IS DISTINCT FROM expected_project THEN
                    RAISE EXCEPTION 'source import Operation scope mismatch';
                END IF;
            END IF;
        END LOOP;
        FOREACH ref_value IN ARRAY ARRAY[
            payload->>'repository_snapshot_asset_version_id',
            payload->>'previous_snapshot_asset_version_id',
            payload->>'asset_version_id', payload->>'target_asset_version_id'
        ] LOOP
            IF COALESCE(ref_value, '') <> '' THEN
                SELECT asset.project_id INTO actual_project
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                WHERE version.asset_version_id = ref_value;
                IF actual_project IS DISTINCT FROM expected_project THEN
                    RAISE EXCEPTION 'source import AssetVersion scope mismatch';
                END IF;
            END IF;
        END LOOP;
        IF TG_TABLE_NAME <> 'authority_source_import_job'
           AND COALESCE(payload->>'import_job_id', '') <> '' THEN
            SELECT project_id INTO actual_project
            FROM authority_source_import_job
            WHERE import_job_id = payload->>'import_job_id';
            IF actual_project IS DISTINCT FROM expected_project THEN
                RAISE EXCEPTION 'source import job scope mismatch';
            END IF;
        END IF;
        IF COALESCE(payload->>'source_document_id', '') <> '' THEN
            SELECT project_id INTO actual_project
            FROM authority_source_document
            WHERE source_document_id = payload->>'source_document_id';
            IF actual_project IS DISTINCT FROM expected_project THEN
                RAISE EXCEPTION 'source import SourceDocument scope mismatch';
            END IF;
        END IF;
        IF COALESCE(payload->>'source_transform_id', '') <> '' THEN
            SELECT project_id, source_document_id
              INTO actual_project, transform_source_document_id
            FROM authority_source_transform
            WHERE source_transform_id = payload->>'source_transform_id';
            IF actual_project IS DISTINCT FROM expected_project THEN
                RAISE EXCEPTION 'source import SourceTransform scope mismatch';
            END IF;
            IF COALESCE(payload->>'source_document_id', '') <> ''
               AND transform_source_document_id IS DISTINCT FROM
                   payload->>'source_document_id' THEN
                RAISE EXCEPTION 'source import Source lineage mismatch';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
