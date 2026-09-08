from __future__ import annotations

MIGRATION_ID = "20260908_0121_corpus_foundation"
DOWN_REVISION = "20260908_0121_account_entitlement_budget"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "append a corrected Source rights declaration and snapshot; never rewrite frozen Corpus lineage"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_corpus_source (
        source_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        source_kind TEXT NOT NULL CHECK (length(source_kind)>0),
        external_identity TEXT NOT NULL CHECK (length(external_identity)>0),
        purpose TEXT NOT NULL CHECK (purpose IN ('RESEARCH','BENCHMARK','MARKET_INTELLIGENCE','PRODUCTION_REFERENCE')),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, source_kind, external_identity),
        UNIQUE(project_id, source_id)
    )
    """,
    """
    CREATE TABLE authority_corpus_rights (
        rights_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        previous_rights_id TEXT,
        revision_number INTEGER NOT NULL CHECK (revision_number>0),
        declaration JSONB NOT NULL CHECK (jsonb_typeof(declaration)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, source_id, rights_id),
        FOREIGN KEY(project_id,source_id) REFERENCES authority_corpus_source(project_id,source_id),
        FOREIGN KEY(project_id,source_id,previous_rights_id) REFERENCES authority_corpus_rights(project_id,source_id,rights_id),
        CHECK (declaration->>'underlying_rights' IN ('OWNED','LICENSED','PUBLIC_DOMAIN','PERMISSION_GRANTED','UNKNOWN','CONFLICTING','RESTRICTED')),
        CHECK (declaration ?& ARRAY['dataset_license','underlying_rights','allowed_purposes','denied_purposes','restrictions','evidence_refs','scope','copyright_boundary']),
        CHECK (jsonb_typeof(declaration->'evidence_refs')='array' AND jsonb_array_length(declaration->'evidence_refs')>0),
        CHECK (jsonb_typeof(declaration->'allowed_purposes')='array' AND jsonb_typeof(declaration->'denied_purposes')='array' AND jsonb_typeof(declaration->'restrictions')='array'),
        CHECK (declaration->>'scope'='ALL_WORKS_IN_SNAPSHOT'),
        CHECK ((declaration->>'underlying_rights'<>'LICENSED' OR length(declaration->>'underlying_license')>0) IS TRUE),
        CHECK ((jsonb_typeof(declaration->'dataset_license')='string' AND length(declaration->>'dataset_license')>0
            AND jsonb_typeof(declaration->'underlying_rights')='string'
            AND jsonb_typeof(declaration->'scope')='string'
            AND jsonb_typeof(declaration->'copyright_boundary')='string'
            AND length(declaration->>'copyright_boundary')>0) IS TRUE)
    )
    """,
    "CREATE UNIQUE INDEX authority_corpus_rights_chain_idx ON authority_corpus_rights(source_id, COALESCE(previous_rights_id,''))",
    "CREATE UNIQUE INDEX authority_corpus_rights_latest_idx ON authority_corpus_rights(project_id,source_id,revision_number DESC)",
    "CREATE INDEX authority_corpus_rights_parent_idx ON authority_corpus_rights(previous_rights_id) WHERE previous_rights_id IS NOT NULL",
    """
    CREATE TABLE authority_corpus_snapshot (
        snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        rights_id TEXT NOT NULL,
        previous_snapshot_id TEXT,
        revision_number INTEGER NOT NULL CHECK (revision_number>0),
        manifest JSONB NOT NULL CHECK (jsonb_typeof(manifest)='object'),
        acquisition JSONB NOT NULL CHECK (jsonb_typeof(acquisition)='object'),
        repository_snapshot_asset_version_id TEXT REFERENCES authority_source_repository_snapshot(asset_version_id),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id,source_id,snapshot_id),
        FOREIGN KEY(project_id,source_id,rights_id) REFERENCES authority_corpus_rights(project_id,source_id,rights_id),
        FOREIGN KEY(project_id,source_id,previous_snapshot_id) REFERENCES authority_corpus_snapshot(project_id,source_id,snapshot_id),
        CHECK (manifest ?& ARRAY['schema_version','origin_uri','external_version','format','checksum','adapter_profile','adapter_contract_version']),
        CHECK (manifest->>'schema_version'='corpus-dataset-manifest.v1'),
        CHECK (manifest->>'checksum' ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (acquisition ?& ARRAY['locator','receipt_ref','acquired_at','checksum']),
        CHECK ((manifest->>'checksum'=acquisition->>'checksum' AND manifest->>'checksum' ~ '^sha256:[0-9a-f]{64}$'
            AND length(manifest->>'external_version')>0 AND length(acquisition->>'receipt_ref')>0) IS TRUE)
    )
    """,
    "CREATE UNIQUE INDEX authority_corpus_snapshot_chain_idx ON authority_corpus_snapshot(source_id, COALESCE(previous_snapshot_id,''))",
    "CREATE UNIQUE INDEX authority_corpus_snapshot_latest_idx ON authority_corpus_snapshot(project_id,source_id,revision_number DESC)",
    "CREATE INDEX authority_corpus_snapshot_parent_idx ON authority_corpus_snapshot(previous_snapshot_id) WHERE previous_snapshot_id IS NOT NULL",
    "CREATE INDEX authority_corpus_snapshot_rights_idx ON authority_corpus_snapshot(rights_id)",
    "CREATE INDEX authority_corpus_snapshot_repository_idx ON authority_corpus_snapshot(repository_snapshot_asset_version_id) WHERE repository_snapshot_asset_version_id IS NOT NULL",
    """
    CREATE TABLE authority_corpus_book_identity (
        book_source_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        external_work_id TEXT NOT NULL CHECK (length(external_work_id)>0),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(source_id,external_work_id),
        UNIQUE(project_id,source_id,book_source_id),
        FOREIGN KEY(project_id,source_id) REFERENCES authority_corpus_source(project_id,source_id)
    )
    """,
    """
    CREATE TABLE authority_corpus_edition (
        edition_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        book_source_id TEXT NOT NULL,
        external_edition_id TEXT NOT NULL CHECK (length(external_edition_id)>0),
        checksum TEXT NOT NULL CHECK (checksum ~ '^sha256:[0-9a-f]{64}$'),
        title TEXT NOT NULL CHECK (length(title)>0),
        locator TEXT NOT NULL CHECK (length(locator)>0),
        metadata JSONB NOT NULL CHECK (jsonb_typeof(metadata)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(snapshot_id,book_source_id,external_edition_id),
        UNIQUE(project_id,edition_id),
        FOREIGN KEY(project_id,source_id,snapshot_id) REFERENCES authority_corpus_snapshot(project_id,source_id,snapshot_id),
        FOREIGN KEY(project_id,source_id,book_source_id) REFERENCES authority_corpus_book_identity(project_id,source_id,book_source_id)
    )
    """,
    "CREATE INDEX authority_corpus_edition_page_idx ON authority_corpus_edition(project_id,snapshot_id,edition_id)",
    "CREATE INDEX authority_corpus_edition_book_idx ON authority_corpus_edition(book_source_id,edition_id)",
    """
    CREATE TABLE authority_corpus_admission (
        decision_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        edition_id TEXT NOT NULL,
        rights_id TEXT NOT NULL REFERENCES authority_corpus_rights(rights_id),
        purpose TEXT NOT NULL CHECK (purpose IN ('RESEARCH','BENCHMARK','MARKET_INTELLIGENCE','PRODUCTION_REFERENCE')),
        decision TEXT NOT NULL CHECK (decision IN ('ALLOW','DENY')),
        evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id,edition_id,purpose,decision_id,decision),
        FOREIGN KEY(project_id,edition_id) REFERENCES authority_corpus_edition(project_id,edition_id)
    )
    """,
    "CREATE INDEX authority_corpus_admission_edition_idx ON authority_corpus_admission(project_id,edition_id,created_at DESC,decision_id)",
    "CREATE INDEX authority_corpus_admission_page_idx ON authority_corpus_admission(project_id,edition_id,decision_id)",
    "CREATE INDEX authority_corpus_admission_rights_idx ON authority_corpus_admission(rights_id)",
    """
    CREATE TABLE authority_corpus_membership (
        membership_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        edition_id TEXT NOT NULL,
        purpose TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT 'ALLOW' CHECK (decision='ALLOW'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(edition_id,purpose),
        FOREIGN KEY(project_id,edition_id,purpose,decision_id,decision)
          REFERENCES authority_corpus_admission(project_id,edition_id,purpose,decision_id,decision)
    )
    """,
    "CREATE INDEX authority_corpus_membership_project_idx ON authority_corpus_membership(project_id,purpose,edition_id)",
    "CREATE INDEX authority_corpus_membership_decision_idx ON authority_corpus_membership(decision_id)",
    """
    CREATE TABLE authority_corpus_retirement (
        source_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(reason)>0),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id,source_id) REFERENCES authority_corpus_source(project_id,source_id)
    )
    """,
    """
    CREATE FUNCTION authority_corpus_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Corpus lineage is immutable; append a revision or retirement' USING ERRCODE='23514';
    END $$
    """,
    """
    CREATE FUNCTION authority_corpus_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM authority_operation o WHERE o.operation_id=NEW.created_by_operation_id AND o.project_id=NEW.project_id AND o.definition_name='source.corpus.commit') THEN
            RAISE EXCEPTION 'Corpus operation project mismatch' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='authority_corpus_source' THEN
            IF NOT EXISTS (SELECT 1 FROM authority_workspace w JOIN authority_operation o ON o.workspace_id=w.workspace_id
                WHERE w.workspace_id=NEW.workspace_id AND w.project_id=NEW.project_id AND o.operation_id=NEW.created_by_operation_id) THEN
                RAISE EXCEPTION 'Corpus workspace mismatch' USING ERRCODE='23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME='authority_corpus_snapshot' THEN
            IF NEW.previous_snapshot_id IS NULL THEN NEW.revision_number := 1;
            ELSE SELECT revision_number+1 INTO NEW.revision_number FROM authority_corpus_snapshot WHERE snapshot_id=NEW.previous_snapshot_id; END IF;
            IF NEW.repository_snapshot_asset_version_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_source_repository_snapshot r JOIN authority_corpus_source s ON s.source_id=NEW.source_id
                WHERE r.asset_version_id=NEW.repository_snapshot_asset_version_id AND r.project_id=NEW.project_id
                    AND r.workspace_id=s.workspace_id AND r.resolved_commit_sha=NEW.manifest->>'external_version'
            ) THEN
                RAISE EXCEPTION 'Corpus acquisition repository binding mismatch' USING ERRCODE='23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME='authority_corpus_rights' THEN
            IF NEW.previous_rights_id IS NULL THEN NEW.revision_number := 1;
            ELSE SELECT revision_number+1 INTO NEW.revision_number FROM authority_corpus_rights WHERE rights_id=NEW.previous_rights_id; END IF;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE FUNCTION authority_corpus_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_purpose TEXT; frozen_rights TEXT; rights JSONB; source_key TEXT;
    BEGIN
        SELECT s.purpose, sn.rights_id, r.declaration, s.source_id
        INTO source_purpose,frozen_rights,rights,source_key
        FROM authority_corpus_edition e
        JOIN authority_corpus_snapshot sn ON sn.snapshot_id=e.snapshot_id
        JOIN authority_corpus_source s ON s.source_id=e.source_id
        JOIN authority_corpus_rights r ON r.rights_id=sn.rights_id
        WHERE e.edition_id=NEW.edition_id AND e.project_id=NEW.project_id;
        IF NOT FOUND OR NEW.rights_id IS DISTINCT FROM frozen_rights THEN
            RAISE EXCEPTION 'Corpus decision must bind exact frozen rights' USING ERRCODE='23514';
        END IF;
        IF NEW.decision='ALLOW' AND (
            NEW.purpose<>source_purpose OR
            NOT (rights->'allowed_purposes' ? NEW.purpose) OR
            rights->'denied_purposes' ? NEW.purpose OR
            EXISTS (SELECT 1 FROM authority_corpus_retirement WHERE source_id=source_key) OR
            EXISTS (SELECT 1 FROM authority_corpus_rights WHERE previous_rights_id=frozen_rights) OR
            (NEW.purpose='PRODUCTION_REFERENCE' AND (
                rights->>'underlying_rights' NOT IN ('OWNED','LICENSED','PUBLIC_DOMAIN','PERMISSION_GRANTED') OR
                jsonb_array_length(rights->'restrictions')>0
            ))
        ) THEN
            RAISE EXCEPTION 'Corpus purpose or underlying rights deny admission' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_corpus_admission_guard BEFORE INSERT ON authority_corpus_admission FOR EACH ROW EXECUTE FUNCTION authority_corpus_admission_guard()",
    "ALTER TABLE authority_source_import_job DROP CONSTRAINT authority_source_import_job_source_type_check",
    "ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_job_source_type_check CHECK (source_type IN ('github_repository','local_file','local_directory','https_resource','corpus_manifest'))",
    "ALTER TABLE authority_source_import_job DROP CONSTRAINT authority_source_import_job_mode_check",
    "ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_job_mode_check CHECK (mode IN ('PREVIEW','IMPORT','FOUNDATION'))",
    "ALTER TABLE authority_source_import_job ADD COLUMN corpus_snapshot_id TEXT REFERENCES authority_corpus_snapshot(snapshot_id)",
    "ALTER TABLE authority_source_import_job ADD CONSTRAINT authority_source_import_corpus_binding CHECK ((mode='FOUNDATION' AND source_type='corpus_manifest' AND corpus_snapshot_id IS NOT NULL) OR (mode<>'FOUNDATION' AND source_type<>'corpus_manifest' AND corpus_snapshot_id IS NULL))",
    "CREATE INDEX authority_source_import_corpus_snapshot_idx ON authority_source_import_job(corpus_snapshot_id) WHERE corpus_snapshot_id IS NOT NULL",
    """
    CREATE FUNCTION authority_corpus_import_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.mode='FOUNDATION' AND NOT EXISTS (
            SELECT 1 FROM authority_corpus_snapshot sn JOIN authority_corpus_source s ON s.source_id=sn.source_id
            JOIN authority_operation o ON o.operation_id=NEW.discovery_operation_id
            WHERE sn.snapshot_id=NEW.corpus_snapshot_id AND sn.project_id=NEW.project_id
              AND s.workspace_id=NEW.workspace_id AND o.project_id=NEW.project_id
              AND o.workspace_id=NEW.workspace_id AND o.definition_name='source.corpus.commit'
              AND o.command_payload->'payload'->>'snapshot_id'=NEW.corpus_snapshot_id
              AND o.command_payload->'payload'->>'action'='import_batch'
        ) THEN
            RAISE EXCEPTION 'Corpus import must bind its frozen Source command and snapshot' USING ERRCODE='23514';
        END IF;
        IF TG_OP='UPDATE' AND OLD.mode='FOUNDATION' AND
            (NEW.source_type,NEW.mode,NEW.corpus_snapshot_id,NEW.source_locator,NEW.import_policy,NEW.import_policy_hash,NEW.discovery_operation_id)
            IS DISTINCT FROM (OLD.source_type,OLD.mode,OLD.corpus_snapshot_id,OLD.source_locator,OLD.import_policy,OLD.import_policy_hash,OLD.discovery_operation_id) THEN
            RAISE EXCEPTION 'Corpus import input is immutable' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER authority_corpus_import_scope BEFORE INSERT OR UPDATE ON authority_source_import_job FOR EACH ROW EXECUTE FUNCTION authority_corpus_import_scope()",
]

for _table in (
    "source",
    "rights",
    "snapshot",
    "book_identity",
    "edition",
    "admission",
    "membership",
    "retirement",
):
    UPGRADE_STATEMENTS.extend(
        [
            f"CREATE TRIGGER authority_corpus_{_table}_immutable BEFORE UPDATE OR DELETE ON authority_corpus_{_table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
            f"CREATE TRIGGER authority_corpus_{_table}_scope BEFORE INSERT ON authority_corpus_{_table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_scope()",
            f"CREATE INDEX authority_corpus_{_table}_operation_idx ON authority_corpus_{_table}(created_by_operation_id)",
        ]
    )

DOWNGRADE_STATEMENTS: list[str] = []
