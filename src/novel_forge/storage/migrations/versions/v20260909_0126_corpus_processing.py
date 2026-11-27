from __future__ import annotations

MIGRATION_ID = '20260909_0126_corpus_processing'
DOWN_REVISION = '20260909_0125_corpus_ingestion_bridge'
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = 'append processing revisions without changing acquired Editions or frozen legacy bridges'

UPGRADE_STATEMENTS = [
    "CREATE OR REPLACE FUNCTION authority_corpus_import_scope() RETURNS trigger LANGUAGE plpgsql AS $$\n    BEGIN\n        IF NEW.mode='FOUNDATION' AND NOT EXISTS (\n            SELECT 1 FROM authority_corpus_snapshot sn JOIN authority_corpus_source s ON s.source_id=sn.source_id\n            JOIN authority_operation o ON o.operation_id=NEW.discovery_operation_id\n            WHERE sn.snapshot_id=NEW.corpus_snapshot_id AND sn.project_id=NEW.project_id\n              AND s.workspace_id=NEW.workspace_id AND o.project_id=NEW.project_id AND o.workspace_id=NEW.workspace_id\n              AND o.definition_name='source.corpus.commit' AND o.command_payload->'payload'->>'snapshot_id'=NEW.corpus_snapshot_id\n        ) THEN RAISE EXCEPTION 'Corpus frozen Source command mismatch' USING ERRCODE='23514'; END IF;\n        IF NEW.source_type='corpus_content' THEN\n            IF NOT EXISTS (SELECT 1 FROM authority_operation o WHERE o.operation_id=NEW.discovery_operation_id\n                AND o.project_id=NEW.project_id AND o.workspace_id=NEW.workspace_id\n                AND (o.definition_name='source.import.corpus.acquire' OR (\n                    o.definition_name='source.import.corpus.work' AND o.command_payload->'payload' ? 'reprocess'\n                    AND o.command_payload->'payload'->>'snapshot_id'=NEW.corpus_snapshot_id\n                    AND EXISTS(SELECT 1 FROM authority_source_work_version w JOIN authority_corpus_edition e ON e.edition_id=w.corpus_edition_id\n                        WHERE w.asset_version_id=o.command_payload->'payload'->'reprocess'->>'parent_work'\n                        AND w.project_id=NEW.project_id AND e.snapshot_id=NEW.corpus_snapshot_id\n                        AND e.edition_id=o.command_payload->'payload'->>'edition_id')))\n                \n                AND o.command_payload->'payload'->'manifest'=NEW.source_locator->'manifest') THEN\n                RAISE EXCEPTION 'Corpus ingestion command mismatch' USING ERRCODE='23514';\n            END IF;\n            IF NEW.corpus_snapshot_id IS NOT NULL AND NOT EXISTS (\n                SELECT 1 FROM authority_corpus_snapshot sn JOIN authority_corpus_source s USING(source_id)\n                WHERE sn.snapshot_id=NEW.corpus_snapshot_id AND sn.project_id=NEW.project_id AND s.workspace_id=NEW.workspace_id\n            ) THEN RAISE EXCEPTION 'Corpus ingestion snapshot scope mismatch' USING ERRCODE='23514'; END IF;\n        END IF;\n        IF TG_OP='UPDATE' AND (\n            (NEW.source_type,NEW.mode,NEW.source_locator,NEW.import_policy,NEW.import_policy_hash,NEW.discovery_operation_id)\n            IS DISTINCT FROM (OLD.source_type,OLD.mode,OLD.source_locator,OLD.import_policy,OLD.import_policy_hash,OLD.discovery_operation_id)\n            OR (NEW.corpus_snapshot_id IS DISTINCT FROM OLD.corpus_snapshot_id AND NOT (\n                OLD.source_type='corpus_content' AND OLD.corpus_snapshot_id IS NULL AND OLD.status IN ('ADMITTED','DISCOVERING','PROCESSING')\n            ))\n        ) THEN RAISE EXCEPTION 'Corpus import frozen identity is immutable' USING ERRCODE='23514'; END IF;\n        RETURN NEW;\n    END $$",
    "ALTER TABLE authority_source_unit_version DROP CONSTRAINT authority_source_unit_version_status_check",
    "ALTER TABLE authority_source_unit_version ADD CONSTRAINT authority_source_unit_version_status_check CHECK(status IN ('AVAILABLE','EMPTY','EXCLUDED'))",
    'DROP INDEX source_work_corpus_edition_idx',
    'CREATE INDEX source_work_corpus_edition_versions_idx ON authority_source_work_version(corpus_edition_id,asset_version_id) WHERE corpus_edition_id IS NOT NULL',
    'ALTER TABLE authority_corpus_bridge DROP CONSTRAINT authority_corpus_bridge_pkey',
    'ALTER TABLE authority_corpus_bridge ADD PRIMARY KEY(edition_id,source_work_asset_version_id)',
    '''CREATE TABLE authority_corpus_processing (
        processing_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        edition_id TEXT NOT NULL REFERENCES authority_corpus_edition(edition_id),
        parent_id TEXT UNIQUE REFERENCES authority_corpus_processing(processing_id),
        source_work_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_source_work_version(asset_version_id),
        source_document_id TEXT NOT NULL UNIQUE REFERENCES authority_source_document(source_document_id),
        parsed_blob_id TEXT NOT NULL REFERENCES authority_blob(blob_id),
        input_hash TEXT NOT NULL, parser_hash TEXT NOT NULL, normalized_hash TEXT NOT NULL,
        profile JSONB NOT NULL, assessment JSONB NOT NULL, fingerprint JSONB NOT NULL,
        buckets TEXT[] NOT NULL, created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(edition_id,input_hash,parser_hash),
        CHECK(input_hash ~ '^sha256:[0-9a-f]{64}$' AND parser_hash ~ '^sha256:[0-9a-f]{64}$' AND normalized_hash ~ '^sha256:[0-9a-f]{64}$'))''',
    'CREATE UNIQUE INDEX corpus_processing_initial_idx ON authority_corpus_processing(edition_id) WHERE parent_id IS NULL',
    'CREATE INDEX corpus_processing_project_page_idx ON authority_corpus_processing(project_id,processing_id)',
    'CREATE INDEX corpus_processing_exact_idx ON authority_corpus_processing(project_id,normalized_hash)',
    'CREATE INDEX corpus_processing_buckets_idx ON authority_corpus_processing USING gin(buckets)',
    'CREATE INDEX corpus_processing_blob_idx ON authority_corpus_processing(parsed_blob_id)',
    'CREATE INDEX corpus_processing_operation_idx ON authority_corpus_processing(created_by_operation_id)',
    '''CREATE TABLE authority_corpus_review (
        review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        processing_id TEXT NOT NULL REFERENCES authority_corpus_processing(processing_id),
        previous_id TEXT UNIQUE REFERENCES authority_corpus_review(review_id),
        decisions JSONB NOT NULL, assessment JSONB NOT NULL, reason TEXT NOT NULL CHECK(length(reason)>0),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''',
    'CREATE UNIQUE INDEX corpus_review_initial_idx ON authority_corpus_review(processing_id) WHERE previous_id IS NULL',
    'CREATE INDEX corpus_review_scope_idx ON authority_corpus_review(project_id,processing_id)',
    'CREATE INDEX corpus_review_operation_idx ON authority_corpus_review(created_by_operation_id)',
    '''CREATE TABLE authority_corpus_equivalence (
        decision_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        left_id TEXT NOT NULL REFERENCES authority_corpus_processing(processing_id),
        right_id TEXT NOT NULL REFERENCES authority_corpus_processing(processing_id),
        previous_id TEXT UNIQUE REFERENCES authority_corpus_equivalence(decision_id),
        canonical_work_id TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REJECT','REVOKE')),
        evidence JSONB NOT NULL, reason TEXT NOT NULL CHECK(length(reason)>0),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK(left_id<right_id))''',
    'CREATE UNIQUE INDEX corpus_equivalence_initial_idx ON authority_corpus_equivalence(left_id,right_id) WHERE previous_id IS NULL',
    'CREATE INDEX corpus_equivalence_left_idx ON authority_corpus_equivalence(project_id,left_id)',
    'CREATE INDEX corpus_equivalence_right_idx ON authority_corpus_equivalence(right_id)',
    'CREATE INDEX corpus_equivalence_canonical_idx ON authority_corpus_equivalence(project_id,canonical_work_id)',
    'CREATE INDEX corpus_equivalence_operation_idx ON authority_corpus_equivalence(created_by_operation_id)',
    '''CREATE FUNCTION authority_corpus_processing_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
      IF NOT EXISTS(SELECT 1 FROM authority_corpus_bridge b JOIN authority_corpus_content c ON c.edition_id=b.edition_id
          AND c.blob_id=NEW.parsed_blob_id AND c.role='PARSED_WORK' AND c.content_hash=NEW.input_hash
          WHERE b.edition_id=NEW.edition_id AND b.project_id=NEW.project_id AND b.source_work_asset_version_id=NEW.source_work_asset_version_id
          AND b.source_document_id=NEW.source_document_id AND b.parser_hash=NEW.parser_hash AND b.normalized_hash=NEW.normalized_hash
          AND b.created_by_operation_id=NEW.created_by_operation_id)
        THEN RAISE EXCEPTION 'processing requires exact verified bridge' USING ERRCODE='23514'; END IF;
      IF NEW.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM authority_corpus_processing p
          WHERE p.processing_id=NEW.parent_id AND p.project_id=NEW.project_id AND p.edition_id=NEW.edition_id)
        THEN RAISE EXCEPTION 'processing parent scope mismatch' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$''',
    'CREATE TRIGGER corpus_processing_scope BEFORE INSERT ON authority_corpus_processing FOR EACH ROW EXECUTE FUNCTION authority_corpus_processing_guard()',
    '''CREATE FUNCTION authority_corpus_quality_decision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
      IF NOT EXISTS(SELECT 1 FROM authority_operation o WHERE o.operation_id=NEW.created_by_operation_id
          AND o.project_id=NEW.project_id AND o.definition_name='source.corpus.commit') THEN
          RAISE EXCEPTION 'quality decision requires Source operation' USING ERRCODE='23514'; END IF;
      IF TG_TABLE_NAME='authority_corpus_review' THEN
        IF NOT EXISTS(SELECT 1 FROM authority_corpus_processing p WHERE p.processing_id=NEW.processing_id AND p.project_id=NEW.project_id)
          OR (NEW.previous_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM authority_corpus_review r WHERE r.review_id=NEW.previous_id
              AND r.processing_id=NEW.processing_id AND r.project_id=NEW.project_id)) THEN
          RAISE EXCEPTION 'review scope mismatch' USING ERRCODE='23514'; END IF;
      ELSE
        IF (SELECT count(*) FROM authority_corpus_processing p WHERE p.processing_id IN (NEW.left_id,NEW.right_id) AND p.project_id=NEW.project_id)<>2
          OR (NEW.previous_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM authority_corpus_equivalence e WHERE e.decision_id=NEW.previous_id
              AND e.left_id=NEW.left_id AND e.right_id=NEW.right_id AND e.project_id=NEW.project_id)) THEN
          RAISE EXCEPTION 'equivalence scope mismatch' USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$''',
]
for table in ('processing','review','equivalence'):
    UPGRADE_STATEMENTS.append(f'CREATE TRIGGER corpus_{table}_immutable BEFORE UPDATE OR DELETE ON authority_corpus_{table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()')
for table in ('review','equivalence'):
    UPGRADE_STATEMENTS.append(f'CREATE TRIGGER corpus_{table}_scope BEFORE INSERT ON authority_corpus_{table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_quality_decision_guard()')
