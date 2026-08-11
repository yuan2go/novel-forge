from __future__ import annotations


MIGRATION_ID = "20260811_0076_source_import_runtime"
DOWN_REVISION = "20260811_0075_source_deconstruction_intelligence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair project/workspace/operation scope or quarantine invalid import rows before retry"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_transform
      ADD COLUMN normalized_blob_id TEXT REFERENCES authority_blob(blob_id),
      ADD COLUMN normalized_content_hash TEXT,
      ADD COLUMN normalized_byte_size BIGINT,
      ADD CONSTRAINT authority_source_transform_normalized_identity_check CHECK (
        (normalized_blob_id IS NULL AND normalized_content_hash IS NULL
         AND normalized_byte_size IS NULL)
        OR
        (normalized_blob_id IS NOT NULL
         AND normalized_content_hash ~ '^sha256:[0-9a-f]{64}$'
         AND normalized_byte_size > 0)
      )
    """,
    """
    CREATE INDEX authority_source_transform_normalized_blob_idx
    ON authority_source_transform(normalized_blob_id)
    WHERE normalized_blob_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_source_import_job (
        import_job_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        source_type TEXT NOT NULL,
        source_locator JSONB NOT NULL,
        requested_ref TEXT NOT NULL DEFAULT '',
        import_policy JSONB NOT NULL,
        import_policy_hash TEXT NOT NULL,
        analysis_profile TEXT NOT NULL,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        discovery_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        repository_snapshot_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        previous_snapshot_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        counters JSONB NOT NULL DEFAULT '{}'::jsonb,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (source_type IN (
            'github_repository', 'local_file', 'local_directory', 'https_resource'
        )),
        CHECK (mode IN ('PREVIEW', 'IMPORT')),
        CHECK (status IN (
            'ADMITTED', 'DISCOVERING', 'PREVIEWED', 'PROCESSING',
            'AWAITING_GOVERNANCE', 'IMPORTED', 'PARTIALLY_COMPLETED',
            'FAILED_RETRYABLE', 'FAILED_FINAL', 'BLOCKED', 'CANCELLED'
        )),
        CHECK (import_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (jsonb_typeof(source_locator) = 'object'),
        CHECK (jsonb_typeof(import_policy) = 'object'),
        CHECK (jsonb_typeof(counters) = 'object'),
        CHECK (jsonb_typeof(failure) = 'object')
    )
    """,
    """
    CREATE INDEX authority_source_import_job_project_idx
    ON authority_source_import_job(project_id, created_at DESC, import_job_id)
    """,
    """
    CREATE INDEX authority_source_import_job_status_idx
    ON authority_source_import_job(status, updated_at)
    WHERE status IN ('ADMITTED', 'DISCOVERING', 'PROCESSING', 'FAILED_RETRYABLE')
    """,
    """
    CREATE TABLE authority_source_repository_snapshot (
        repository_snapshot_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        repository_identity TEXT NOT NULL,
        repository_url TEXT NOT NULL,
        requested_ref TEXT NOT NULL,
        resolved_commit_sha TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        import_policy_hash TEXT NOT NULL,
        file_count INTEGER NOT NULL,
        repository_bytes BIGINT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, repository_identity, resolved_commit_sha, import_policy_hash),
        CHECK (resolved_commit_sha ~ '^[0-9a-f]{40}$'),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (import_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (file_count >= 0),
        CHECK (repository_bytes >= 0)
    )
    """,
    """
    CREATE INDEX authority_source_repository_snapshot_project_idx
    ON authority_source_repository_snapshot(
        project_id, repository_identity, created_at DESC
    )
    """,
    """
    CREATE TABLE authority_source_repository_file (
        repository_snapshot_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_repository_snapshot(asset_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        path TEXT NOT NULL,
        file_identity_hash TEXT NOT NULL,
        diff_state TEXT NOT NULL,
        previous_path TEXT NOT NULL DEFAULT '',
        previous_object_id TEXT NOT NULL DEFAULT '',
        object_mode TEXT NOT NULL DEFAULT '',
        object_type TEXT NOT NULL DEFAULT '',
        object_id TEXT NOT NULL DEFAULT '',
        size_bytes BIGINT NOT NULL,
        eligibility TEXT NOT NULL,
        block_reason TEXT NOT NULL DEFAULT '',
        content_hash TEXT,
        source_document_id TEXT REFERENCES authority_source_document(source_document_id),
        source_transform_id TEXT REFERENCES authority_source_transform(source_transform_id),
        processing_operation_id TEXT REFERENCES authority_operation(operation_id),
        status TEXT NOT NULL,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(repository_snapshot_asset_version_id, path),
        CHECK (file_identity_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (diff_state IN (
            'UNCHANGED', 'ADDED', 'MODIFIED', 'REMOVED',
            'RENAMED_SAME_CONTENT', 'BLOCKED'
        )),
        CHECK (size_bytes >= -1),
        CHECK (eligibility IN ('ELIGIBLE', 'BLOCKED')),
        CHECK (
            (eligibility = 'ELIGIBLE' AND block_reason = '')
            OR (eligibility = 'BLOCKED' AND block_reason <> '')
        ),
        CHECK (content_hash IS NULL OR content_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (status IN (
            'DISCOVERED', 'BLOCKED', 'REUSED', 'QUEUED', 'PROCESSING',
            'TRANSFORMED', 'ANALYZING', 'CANDIDATE_READY', 'FAILED_RETRYABLE',
            'FAILED_FINAL', 'REMOVED'
        )),
        CHECK (jsonb_typeof(failure) = 'object')
    )
    """,
    """
    CREATE INDEX authority_source_repository_file_project_idx
    ON authority_source_repository_file(project_id, status, updated_at)
    """,
    """
    CREATE INDEX authority_source_repository_file_content_idx
    ON authority_source_repository_file(project_id, content_hash)
    WHERE content_hash IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_repository_file_source_idx
    ON authority_source_repository_file(source_document_id)
    WHERE source_document_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_repository_file_transform_idx
    ON authority_source_repository_file(source_transform_id)
    WHERE source_transform_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_source_import_work (
        work_id TEXT PRIMARY KEY,
        import_job_id TEXT NOT NULL REFERENCES authority_source_import_job(import_job_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        work_kind TEXT NOT NULL,
        stable_key TEXT NOT NULL,
        source_path TEXT NOT NULL DEFAULT '',
        target_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        status TEXT NOT NULL,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        failure JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(import_job_id, work_kind, stable_key),
        CHECK (work_kind IN (
            'DISCOVERY', 'FILE', 'DECONSTRUCTION', 'MKAOS_EXTRACTION',
            'REPROCESSING', 'PROJECTION_REBUILD', 'GOVERNANCE_REVIEW'
        )),
        CHECK (status IN (
            'PLANNED', 'RUNNING', 'SUCCEEDED', 'REUSED', 'FAILED_RETRYABLE',
            'FAILED_FINAL', 'BLOCKED', 'CANCELLED'
        )),
        CHECK (jsonb_typeof(result) = 'object'),
        CHECK (jsonb_typeof(failure) = 'object')
    )
    """,
    """
    CREATE INDEX authority_source_import_work_job_idx
    ON authority_source_import_work(import_job_id, work_kind, status, created_at)
    """,
    """
    ALTER TABLE authority_source_reprocessing_plan
      DROP CONSTRAINT authority_source_reprocessing_plan_status_check,
      ADD CONSTRAINT authority_source_reprocessing_plan_status_check CHECK (
        status IN (
            'PLANNED', 'RUNNING', 'PARTIALLY_APPLIED', 'APPLIED',
            'FAILED', 'BLOCKED', 'SUPERSEDED'
        )
      )
    """,
    """
    ALTER TABLE authority_source_reprocessing_plan_item
      ADD COLUMN execution_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING',
      ADD COLUMN child_operation_id TEXT REFERENCES authority_operation(operation_id),
      ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN last_error JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      ADD CONSTRAINT authority_source_reprocessing_item_status_check CHECK (
        status IN ('PENDING', 'RUNNING', 'REUSED', 'APPLIED', 'FAILED', 'BLOCKED')
      ),
      ADD CONSTRAINT authority_source_reprocessing_item_attempt_check CHECK (
        attempt_count >= 0
      ),
      ADD CONSTRAINT authority_source_reprocessing_item_json_check CHECK (
        jsonb_typeof(execution_spec) = 'object'
        AND jsonb_typeof(last_error) = 'object'
      )
    """,
    """
    CREATE INDEX authority_source_reprocessing_item_status_idx
    ON authority_source_reprocessing_plan_item(
        reprocessing_plan_asset_version_id, status, ordinal
    )
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
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_source_import_job_scope_guard
    BEFORE INSERT OR UPDATE ON authority_source_import_job
    FOR EACH ROW EXECUTE FUNCTION authority_validate_source_import_scope()
    """,
    """
    CREATE TRIGGER authority_source_repository_snapshot_scope_guard
    BEFORE INSERT OR UPDATE ON authority_source_repository_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_validate_source_import_scope()
    """,
    """
    CREATE TRIGGER authority_source_repository_file_scope_guard
    BEFORE INSERT OR UPDATE ON authority_source_repository_file
    FOR EACH ROW EXECUTE FUNCTION authority_validate_source_import_scope()
    """,
    """
    CREATE TRIGGER authority_source_import_work_scope_guard
    BEFORE INSERT OR UPDATE ON authority_source_import_work
    FOR EACH ROW EXECUTE FUNCTION authority_validate_source_import_scope()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
