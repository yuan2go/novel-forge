from __future__ import annotations


MIGRATION_ID = "20260909_0125_corpus_ingestion_bridge"
DOWN_REVISION = "20260909_0124_corpus_fk_indexes"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append corrected acquisition/rights revisions; retain existing Source and Corpus history"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_corpus_rights DROP CONSTRAINT authority_corpus_rights_declaration_check5",
    """ALTER TABLE authority_corpus_rights ADD CONSTRAINT corpus_rights_scope_v2 CHECK (
        declaration->>'scope' IN ('ALL_WORKS_IN_SNAPSHOT','SELECTED_WORKS') AND
        (declaration->>'scope'<>'SELECTED_WORKS' OR (jsonb_typeof(declaration->'work_grants')='object' AND declaration->'work_grants'<>'{}'::jsonb))
    )""",
    """CREATE OR REPLACE FUNCTION authority_corpus_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_purpose TEXT; frozen_rights TEXT; rights JSONB; source_key TEXT; work_key TEXT; effective JSONB;
    BEGIN
        PERFORM pg_advisory_xact_lock_shared(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
        SELECT s.purpose,sn.rights_id,r.declaration,s.source_id,b.external_work_id
          INTO source_purpose,frozen_rights,rights,source_key,work_key
          FROM authority_corpus_edition e
          JOIN authority_corpus_snapshot sn ON sn.snapshot_id=e.snapshot_id
          JOIN authority_corpus_source s ON s.source_id=e.source_id
          JOIN authority_corpus_rights r ON r.rights_id=sn.rights_id
          JOIN authority_corpus_book_identity b ON b.book_source_id=e.book_source_id
          WHERE e.edition_id=NEW.edition_id AND e.project_id=NEW.project_id;
        IF NOT FOUND OR NEW.rights_id IS DISTINCT FROM frozen_rights THEN
            RAISE EXCEPTION 'Corpus decision must bind exact frozen rights' USING ERRCODE='23514';
        END IF;
        effective := CASE WHEN rights->>'scope'='SELECTED_WORKS' THEN rights->'work_grants'->work_key ELSE rights END;
        IF NEW.decision='ALLOW' AND (
            (NEW.purpose=source_purpose AND rights->'allowed_purposes' ? NEW.purpose AND
             effective->'allowed_purposes' ? NEW.purpose AND NOT (rights->'denied_purposes' ? NEW.purpose) AND
             NOT (effective->'denied_purposes' ? NEW.purpose)) IS NOT TRUE OR
            EXISTS (SELECT 1 FROM authority_corpus_retirement WHERE source_id=source_key) OR
            EXISTS (SELECT 1 FROM authority_corpus_rights WHERE previous_rights_id=frozen_rights) OR
            (NEW.purpose='PRODUCTION_REFERENCE' AND (
                (effective->>'underlying_rights' IN ('OWNED','LICENSED','PUBLIC_DOMAIN','PERMISSION_GRANTED') AND
                 jsonb_array_length(effective->'restrictions')=0 AND jsonb_array_length(rights->'restrictions')=0 AND
                 (effective->>'underlying_rights'<>'LICENSED' OR length(effective->>'underlying_license')>0) AND
                 jsonb_array_length(effective->'evidence_refs')>0) IS NOT TRUE
            ))
        ) THEN RAISE EXCEPTION 'Corpus purpose or underlying rights deny admission' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""",
    """CREATE FUNCTION authority_corpus_authorization_lock() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
        RETURN NEW;
    END $$""",
    "ALTER TABLE authority_source_import_job DROP CONSTRAINT authority_source_import_job_status_check",
    "ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_job_status_check CHECK(status IN ('ADMITTED','DISCOVERING','PREVIEWED','PROCESSING','PARTIALLY_COMPLETED','AWAITING_GOVERNANCE','IMPORTED','BLOCKED','FAILED_RETRYABLE','FAILED_FINAL','CANCELLED','PAUSED'))",
    "ALTER TABLE authority_source_import_job DROP CONSTRAINT authority_source_import_job_source_type_check",
    "ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_job_source_type_check CHECK (source_type IN ('github_repository','local_file','local_directory','https_resource','corpus_manifest','corpus_content'))",
    "ALTER TABLE authority_source_import_job DROP CONSTRAINT authority_source_import_corpus_binding",
    """ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_corpus_binding CHECK (
        (mode='FOUNDATION' AND source_type='corpus_manifest' AND corpus_snapshot_id IS NOT NULL) OR
        (mode IN ('IMPORT','PREVIEW') AND source_type='corpus_content') OR
        (mode<>'FOUNDATION' AND source_type NOT IN ('corpus_manifest','corpus_content') AND corpus_snapshot_id IS NULL)
    )""",
    """CREATE OR REPLACE FUNCTION authority_corpus_import_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.mode='FOUNDATION' AND NOT EXISTS (
            SELECT 1 FROM authority_corpus_snapshot sn JOIN authority_corpus_source s ON s.source_id=sn.source_id
            JOIN authority_operation o ON o.operation_id=NEW.discovery_operation_id
            WHERE sn.snapshot_id=NEW.corpus_snapshot_id AND sn.project_id=NEW.project_id
              AND s.workspace_id=NEW.workspace_id AND o.project_id=NEW.project_id AND o.workspace_id=NEW.workspace_id
              AND o.definition_name='source.corpus.commit' AND o.command_payload->'payload'->>'snapshot_id'=NEW.corpus_snapshot_id
        ) THEN RAISE EXCEPTION 'Corpus frozen Source command mismatch' USING ERRCODE='23514'; END IF;
        IF NEW.source_type='corpus_content' THEN
            IF NOT EXISTS (SELECT 1 FROM authority_operation o WHERE o.operation_id=NEW.discovery_operation_id
                AND o.project_id=NEW.project_id AND o.workspace_id=NEW.workspace_id
                AND o.definition_name='source.import.corpus.acquire'
                AND o.command_payload->'payload'->'manifest'=NEW.source_locator->'manifest') THEN
                RAISE EXCEPTION 'Corpus ingestion command mismatch' USING ERRCODE='23514';
            END IF;
            IF NEW.corpus_snapshot_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_corpus_snapshot sn JOIN authority_corpus_source s USING(source_id)
                WHERE sn.snapshot_id=NEW.corpus_snapshot_id AND sn.project_id=NEW.project_id AND s.workspace_id=NEW.workspace_id
            ) THEN RAISE EXCEPTION 'Corpus ingestion snapshot scope mismatch' USING ERRCODE='23514'; END IF;
        END IF;
        IF TG_OP='UPDATE' AND (
            (NEW.source_type,NEW.mode,NEW.source_locator,NEW.import_policy,NEW.import_policy_hash,NEW.discovery_operation_id)
            IS DISTINCT FROM (OLD.source_type,OLD.mode,OLD.source_locator,OLD.import_policy,OLD.import_policy_hash,OLD.discovery_operation_id)
            OR (NEW.corpus_snapshot_id IS DISTINCT FROM OLD.corpus_snapshot_id AND NOT (
                OLD.source_type='corpus_content' AND OLD.corpus_snapshot_id IS NULL AND OLD.status IN ('ADMITTED','DISCOVERING','PROCESSING')
            ))
        ) THEN RAISE EXCEPTION 'Corpus import frozen identity is immutable' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""",
    "ALTER TABLE authority_source_document ADD COLUMN corpus_edition_id TEXT REFERENCES authority_corpus_edition(edition_id)",
    "CREATE INDEX source_document_corpus_edition_idx ON authority_source_document(corpus_edition_id) WHERE corpus_edition_id IS NOT NULL",
    "ALTER TABLE authority_source_work_version ALTER COLUMN repository_snapshot_asset_version_id DROP NOT NULL, ALTER COLUMN repository_commit_sha DROP NOT NULL, ADD COLUMN corpus_edition_id TEXT REFERENCES authority_corpus_edition(edition_id)",
    "ALTER TABLE authority_source_work_version ADD CONSTRAINT source_work_acquisition_exclusive CHECK ((repository_snapshot_asset_version_id IS NOT NULL AND repository_commit_sha IS NOT NULL AND corpus_edition_id IS NULL) OR (repository_snapshot_asset_version_id IS NULL AND corpus_edition_id IS NOT NULL))",
    "CREATE UNIQUE INDEX source_work_corpus_edition_idx ON authority_source_work_version(corpus_edition_id) WHERE corpus_edition_id IS NOT NULL",
    """CREATE TABLE authority_corpus_content (
        content_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        snapshot_id TEXT NOT NULL REFERENCES authority_corpus_snapshot(snapshot_id),
        edition_id TEXT REFERENCES authority_corpus_edition(edition_id),
        blob_id TEXT NOT NULL REFERENCES authority_blob(blob_id),
        role TEXT NOT NULL CHECK(role IN ('ACQUISITION','PARSED_WORK','RAW_BUNDLE','NORMALIZED','CHUNK')),
        path TEXT NOT NULL, content_hash TEXT NOT NULL CHECK(content_hash ~ '^sha256:[0-9a-f]{64}$'),
        byte_size BIGINT NOT NULL CHECK(byte_size>0), locator JSONB NOT NULL,
        acquisition_effect_id TEXT NOT NULL REFERENCES authority_external_effect(external_effect_id),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(snapshot_id,role,path,blob_id)
    )""",
    "CREATE INDEX corpus_content_blob_idx ON authority_corpus_content(blob_id,project_id)",
    "CREATE INDEX corpus_content_hash_idx ON authority_corpus_content(project_id,content_hash)",
    "CREATE INDEX corpus_content_edition_idx ON authority_corpus_content(edition_id,role)",
    "CREATE INDEX corpus_content_effect_idx ON authority_corpus_content(acquisition_effect_id)",
    "CREATE INDEX corpus_content_operation_idx ON authority_corpus_content(created_by_operation_id)",
    "CREATE INDEX corpus_content_project_snapshot_page_idx ON authority_corpus_content(project_id,snapshot_id,content_id)",
    """CREATE TABLE authority_corpus_bridge (
        edition_id TEXT PRIMARY KEY REFERENCES authority_corpus_edition(edition_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        source_document_id TEXT NOT NULL UNIQUE REFERENCES authority_source_document(source_document_id),
        source_transform_id TEXT NOT NULL UNIQUE REFERENCES authority_source_transform(source_transform_id),
        source_work_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_source_work_version(asset_version_id),
        rights_id TEXT NOT NULL REFERENCES authority_corpus_rights(rights_id),
        parser_hash TEXT NOT NULL CHECK(parser_hash ~ '^sha256:[0-9a-f]{64}$'),
        normalized_hash TEXT NOT NULL CHECK(normalized_hash ~ '^sha256:[0-9a-f]{64}$'),
        policy_version TEXT NOT NULL CHECK(policy_version='corpus-use-policy.v1'),
        evidence JSONB NOT NULL, created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX corpus_bridge_project_idx ON authority_corpus_bridge(project_id,edition_id)",
    "CREATE INDEX corpus_bridge_rights_idx ON authority_corpus_bridge(rights_id)",
    "CREATE INDEX corpus_bridge_operation_idx ON authority_corpus_bridge(created_by_operation_id)",
    """CREATE FUNCTION authority_corpus_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM authority_corpus_snapshot s JOIN authority_blob b ON b.blob_id=NEW.blob_id
            JOIN authority_external_effect e ON e.external_effect_id=NEW.acquisition_effect_id
            JOIN authority_operation o ON o.operation_id=NEW.created_by_operation_id
            WHERE s.snapshot_id=NEW.snapshot_id AND s.project_id=NEW.project_id AND b.project_id=NEW.project_id
              AND b.status='AVAILABLE' AND b.actual_hash=NEW.content_hash AND b.actual_size=NEW.byte_size
              AND e.project_id=NEW.project_id AND e.status='SUCCEEDED' AND e.capability='source.remote.fetch'
              AND s.acquisition->>'receipt_ref'=e.external_effect_id AND o.project_id=NEW.project_id
              AND o.definition_name IN ('source.import.corpus.acquire','source.import.corpus.work')
        ) OR (NEW.edition_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM authority_corpus_edition e WHERE e.edition_id=NEW.edition_id AND e.snapshot_id=NEW.snapshot_id AND e.project_id=NEW.project_id))
        THEN RAISE EXCEPTION 'Corpus verified content lineage mismatch' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""",
    "CREATE TRIGGER corpus_content_scope BEFORE INSERT ON authority_corpus_content FOR EACH ROW EXECUTE FUNCTION authority_corpus_content_guard()",
    """CREATE FUNCTION authority_corpus_bridge_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM pg_advisory_xact_lock_shared(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
        IF NOT EXISTS (
            SELECT 1 FROM authority_corpus_edition e JOIN authority_corpus_snapshot s USING(snapshot_id)
            JOIN authority_source_document d ON d.source_document_id=NEW.source_document_id AND d.corpus_edition_id=e.edition_id
            JOIN authority_source_transform t ON t.source_transform_id=NEW.source_transform_id AND t.source_document_id=d.source_document_id
            JOIN authority_source_work_version w ON w.asset_version_id=NEW.source_work_asset_version_id
                AND w.source_document_id=d.source_document_id AND w.source_transform_id=t.source_transform_id AND w.corpus_edition_id=e.edition_id
            JOIN authority_operation o ON o.operation_id=NEW.created_by_operation_id
            WHERE e.edition_id=NEW.edition_id AND e.project_id=NEW.project_id AND s.rights_id=NEW.rights_id
              AND d.project_id=NEW.project_id AND t.project_id=NEW.project_id AND w.project_id=NEW.project_id
              AND t.normalized_content_hash=NEW.normalized_hash AND o.project_id=NEW.project_id
              AND o.definition_name='source.import.corpus.work'
              AND EXISTS (SELECT 1 FROM authority_corpus_content c WHERE c.edition_id=e.edition_id AND c.blob_id=d.blob_id AND c.role='RAW_BUNDLE')
        ) THEN RAISE EXCEPTION 'Corpus bridge requires exact content/Edition/Source lineage' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""",
    "CREATE TRIGGER corpus_bridge_scope BEFORE INSERT ON authority_corpus_bridge FOR EACH ROW EXECUTE FUNCTION authority_corpus_bridge_guard()",
]

UPGRADE_STATEMENTS.append("""
    CREATE OR REPLACE FUNCTION authority_source_work_scope_guard()
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
            IF NEW.corpus_edition_id IS NOT NULL THEN
                SELECT e.project_id INTO snapshot_project FROM authority_corpus_edition e
                JOIN authority_source_document d ON d.corpus_edition_id=e.edition_id
                WHERE e.edition_id=NEW.corpus_edition_id AND d.source_document_id=NEW.source_document_id;
            ELSE
                SELECT project_id INTO snapshot_project FROM authority_source_repository_snapshot
                WHERE asset_version_id=NEW.repository_snapshot_asset_version_id;
            END IF;
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
""")

for table in ("source", "rights", "snapshot", "retirement"):
    UPGRADE_STATEMENTS.append(f"CREATE TRIGGER corpus_{table}_authorization_serial BEFORE INSERT ON authority_corpus_{table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_authorization_lock()")
for table in ("content", "bridge"):
    UPGRADE_STATEMENTS.append(f"CREATE TRIGGER corpus_{table}_immutable BEFORE UPDATE OR DELETE ON authority_corpus_{table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()")

DOWNGRADE_STATEMENTS: list[str] = []
