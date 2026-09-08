from __future__ import annotations


MIGRATION_ID = "20260908_0122_source_work_manifest"
DOWN_REVISION = "20260908_0121_account_entitlement_budget"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "retain immutable SourceDocument/SourceTransform history; SourceWork versions "
    "only index governed locator and hash manifests"
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_import_work
      DROP CONSTRAINT authority_source_import_work_work_kind_check,
      ADD CONSTRAINT authority_source_import_work_work_kind_check CHECK (
        work_kind IN (
          'DISCOVERY', 'FILE', 'WORK', 'PROFILING', 'ANALYSIS_PLANNING',
          'DECONSTRUCTION', 'MKAOS_EXTRACTION', 'REPROCESSING',
          'PROJECTION_REBUILD', 'GOVERNANCE_REVIEW'
        )
      )
    """,
    """
    CREATE TABLE authority_source_work (
        source_work_id TEXT PRIMARY KEY REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        work_key TEXT NOT NULL,
        title TEXT NOT NULL,
        collection_kind TEXT NOT NULL,
        repository_identity TEXT NOT NULL,
        repository_url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, work_key),
        CHECK (work_key <> '' AND title <> ''),
        CHECK (status IN ('ACTIVE', 'RETIRED'))
    )
    """,
    """
    CREATE TABLE authority_source_work_version (
        asset_version_id TEXT PRIMARY KEY
            REFERENCES authority_asset_version(asset_version_id),
        source_work_id TEXT NOT NULL
            REFERENCES authority_source_work(source_work_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        repository_snapshot_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_repository_snapshot(asset_version_id),
        source_document_id TEXT NOT NULL
            REFERENCES authority_source_document(source_document_id),
        source_transform_id TEXT NOT NULL
            REFERENCES authority_source_transform(source_transform_id),
        repository_commit_sha TEXT NOT NULL,
        parser_profile TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        registry_id TEXT NOT NULL,
        registry_hash TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        unit_count INTEGER NOT NULL,
        body_unit_count INTEGER NOT NULL,
        character_count BIGINT NOT NULL,
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_work_id, manifest_hash),
        CHECK (repository_commit_sha ~ '^[0-9a-f]{40}$'),
        CHECK (registry_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (unit_count > 0 AND body_unit_count > 0),
        CHECK (body_unit_count <= unit_count AND character_count > 0),
        CHECK (status IN ('ACTIVE', 'SUPERSEDED'))
    )
    """,
    """
    CREATE UNIQUE INDEX authority_source_work_one_active_version_idx
      ON authority_source_work_version(source_work_id)
      WHERE status='ACTIVE'
    """,
    """
    CREATE INDEX authority_source_work_workspace_idx
      ON authority_source_work(workspace_id)
    """,
    """
    CREATE INDEX authority_source_work_operation_idx
      ON authority_source_work(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_source_work_version_project_idx
      ON authority_source_work_version(project_id)
    """,
    """
    CREATE INDEX authority_source_work_version_workspace_idx
      ON authority_source_work_version(workspace_id)
    """,
    """
    CREATE INDEX authority_source_work_version_snapshot_idx
      ON authority_source_work_version(repository_snapshot_asset_version_id)
    """,
    """
    CREATE INDEX authority_source_work_version_transform_idx
      ON authority_source_work_version(source_transform_id)
    """,
    """
    CREATE INDEX authority_source_work_version_document_idx
      ON authority_source_work_version(source_document_id)
    """,
    """
    CREATE TABLE authority_source_unit (
        source_unit_id TEXT PRIMARY KEY,
        source_work_id TEXT NOT NULL
            REFERENCES authority_source_work(source_work_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        unit_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_work_id, unit_key),
        CHECK (source_unit_id <> '' AND unit_key <> '')
    )
    """,
    """
    CREATE TABLE authority_source_unit_version (
        source_unit_version_id TEXT PRIMARY KEY,
        source_work_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_work_version(asset_version_id),
        source_unit_id TEXT NOT NULL
            REFERENCES authority_source_unit(source_unit_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        ordinal INTEGER NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        raw_file_path TEXT NOT NULL,
        raw_file_hash TEXT NOT NULL,
        source_locator JSONB NOT NULL,
        original_content_hash TEXT NOT NULL,
        normalized_content_hash TEXT NOT NULL,
        normalized_byte_start BIGINT NOT NULL,
        normalized_byte_end BIGINT NOT NULL,
        character_count INTEGER NOT NULL,
        line_count INTEGER NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL,
        UNIQUE(source_work_asset_version_id, source_unit_id),
        UNIQUE(source_work_asset_version_id, ordinal),
        CHECK (ordinal > 0),
        CHECK (raw_file_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (original_content_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (normalized_content_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (normalized_byte_start >= 0),
        CHECK (normalized_byte_end >= normalized_byte_start),
        CHECK (character_count >= 0 AND line_count >= 0),
        CHECK (jsonb_typeof(source_locator)='object'),
        CHECK (jsonb_typeof(metadata)='object'),
        CHECK (status IN ('AVAILABLE', 'EMPTY'))
    )
    """,
    """
    CREATE INDEX authority_source_unit_version_locator_idx
      ON authority_source_unit_version(source_work_asset_version_id, raw_file_path)
    """,
    """
    CREATE INDEX authority_source_unit_work_idx
      ON authority_source_unit(source_work_id, project_id)
    """,
    """
    CREATE INDEX authority_source_unit_project_idx
      ON authority_source_unit(project_id)
    """,
    """
    CREATE INDEX authority_source_unit_version_unit_idx
      ON authority_source_unit_version(source_unit_id)
    """,
    """
    CREATE INDEX authority_source_unit_version_project_idx
      ON authority_source_unit_version(project_id)
    """,
    """
    CREATE FUNCTION authority_source_work_scope_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        asset_project TEXT;
        workspace_project TEXT;
        snapshot_project TEXT;
        document_project TEXT;
        transform_project TEXT;
        operation_project TEXT;
    BEGIN
        SELECT project_id INTO asset_project
        FROM authority_asset WHERE asset_id=NEW.source_work_id;
        SELECT project_id INTO workspace_project
        FROM authority_workspace WHERE workspace_id=NEW.workspace_id;
        IF asset_project IS DISTINCT FROM NEW.project_id
           OR workspace_project IS DISTINCT FROM NEW.project_id THEN
            RAISE EXCEPTION 'SOURCE_WORK_SCOPE_MISMATCH:%', NEW.source_work_id
                USING ERRCODE='check_violation';
        END IF;
        SELECT project_id INTO operation_project
        FROM authority_operation WHERE operation_id=NEW.created_by_operation_id;
        IF operation_project IS DISTINCT FROM NEW.project_id THEN
            RAISE EXCEPTION 'SOURCE_WORK_OPERATION_SCOPE_MISMATCH:%',
                NEW.created_by_operation_id USING ERRCODE='check_violation';
        END IF;
        IF TG_TABLE_NAME='authority_source_work_version' THEN
            SELECT project_id INTO snapshot_project
            FROM authority_source_repository_snapshot
            WHERE asset_version_id=NEW.repository_snapshot_asset_version_id;
            SELECT project_id INTO document_project
            FROM authority_source_document
            WHERE source_document_id=NEW.source_document_id;
            SELECT project_id INTO transform_project
            FROM authority_source_transform
            WHERE source_transform_id=NEW.source_transform_id;
            IF snapshot_project IS DISTINCT FROM NEW.project_id
               OR document_project IS DISTINCT FROM NEW.project_id
               OR transform_project IS DISTINCT FROM NEW.project_id THEN
                RAISE EXCEPTION 'SOURCE_WORK_VERSION_SCOPE_MISMATCH:%',
                    NEW.asset_version_id USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_source_work_scope_guard_trigger
    BEFORE INSERT OR UPDATE ON authority_source_work
    FOR EACH ROW EXECUTE FUNCTION authority_source_work_scope_guard()
    """,
    """
    CREATE TRIGGER authority_source_work_version_scope_guard_trigger
    BEFORE INSERT OR UPDATE ON authority_source_work_version
    FOR EACH ROW EXECUTE FUNCTION authority_source_work_scope_guard()
    """,
    """
    CREATE FUNCTION authority_source_unit_scope_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        work_project TEXT;
        version_project TEXT;
        unit_project TEXT;
        version_work TEXT;
        unit_work TEXT;
    BEGIN
        IF TG_TABLE_NAME='authority_source_unit' THEN
            SELECT project_id INTO work_project
            FROM authority_source_work WHERE source_work_id=NEW.source_work_id;
            IF work_project IS DISTINCT FROM NEW.project_id THEN
                RAISE EXCEPTION 'SOURCE_UNIT_SCOPE_MISMATCH:%', NEW.source_unit_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSE
            SELECT project_id, source_work_id INTO version_project, version_work
            FROM authority_source_work_version
            WHERE asset_version_id=NEW.source_work_asset_version_id;
            SELECT project_id, source_work_id INTO unit_project, unit_work
            FROM authority_source_unit WHERE source_unit_id=NEW.source_unit_id;
            IF version_project IS DISTINCT FROM NEW.project_id
               OR unit_project IS DISTINCT FROM NEW.project_id
               OR version_work IS DISTINCT FROM unit_work THEN
                RAISE EXCEPTION 'SOURCE_UNIT_VERSION_SCOPE_MISMATCH:%',
                    NEW.source_unit_version_id USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_source_unit_scope_guard_trigger
    BEFORE INSERT OR UPDATE ON authority_source_unit
    FOR EACH ROW EXECUTE FUNCTION authority_source_unit_scope_guard()
    """,
    """
    CREATE TRIGGER authority_source_unit_version_scope_guard_trigger
    BEFORE INSERT OR UPDATE ON authority_source_unit_version
    FOR EACH ROW EXECUTE FUNCTION authority_source_unit_scope_guard()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
