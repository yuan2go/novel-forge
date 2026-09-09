from __future__ import annotations

MIGRATION_ID = "20260909_0127_corpus_curation"
DOWN_REVISION = "20260909_0126_corpus_processing"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_corpus_equivalence ADD COLUMN relation TEXT CHECK(relation IN ('SAME_WORK','SAME_EDITION_COPY','REVISION','ABRIDGED','EXPANDED','EXCERPT','SIMILAR_ONLY','DIFFERENT_WORK','UNCERTAIN'))",
    "CREATE INDEX corpus_processing_catalog_watermark_idx ON authority_corpus_processing(project_id,created_at DESC)",
    "CREATE INDEX corpus_review_catalog_watermark_idx ON authority_corpus_review(project_id,created_at DESC)",
    "ALTER TABLE authority_corpus_processing ADD UNIQUE(processing_id,project_id,edition_id)",
    """CREATE TABLE authority_corpus_work_revision (
 revision_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES authority_project(project_id), workspace_id TEXT NOT NULL,
 previous_id TEXT UNIQUE REFERENCES authority_corpus_work_revision(revision_id), manifest JSONB NOT NULL,
 created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(revision_id,project_id))""",
    "CREATE UNIQUE INDEX corpus_work_initial_idx ON authority_corpus_work_revision(project_id,work_id) WHERE previous_id IS NULL",
    "CREATE INDEX corpus_work_scope_idx ON authority_corpus_work_revision(project_id,work_id,revision_id)",
    "CREATE INDEX corpus_work_operation_idx ON authority_corpus_work_revision(created_by_operation_id)",
    """CREATE TABLE authority_corpus_work_member (
 revision_id TEXT NOT NULL, project_id TEXT NOT NULL, processing_id TEXT NOT NULL, edition_id TEXT NOT NULL,
 evidence JSONB NOT NULL,
 PRIMARY KEY(revision_id,edition_id),
 FOREIGN KEY(revision_id,project_id) REFERENCES authority_corpus_work_revision(revision_id,project_id),
 FOREIGN KEY(processing_id,project_id,edition_id) REFERENCES authority_corpus_processing(processing_id,project_id,edition_id))""",
    "CREATE INDEX corpus_work_member_processing_idx ON authority_corpus_work_member(processing_id)",
    "CREATE INDEX corpus_work_member_edition_idx ON authority_corpus_work_member(project_id,edition_id)",
    "CREATE TRIGGER corpus_work_revision_immutable BEFORE UPDATE OR DELETE ON authority_corpus_work_revision FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
    "CREATE TRIGGER corpus_work_member_immutable BEFORE UPDATE OR DELETE ON authority_corpus_work_member FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
    """CREATE TABLE authority_corpus_curated_revision (
 revision_id TEXT PRIMARY KEY, corpus_id TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES authority_project(project_id), workspace_id TEXT NOT NULL,
 previous_id TEXT UNIQUE REFERENCES authority_corpus_curated_revision(revision_id), manifest JSONB NOT NULL,
 created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(revision_id,project_id))""",
    "CREATE UNIQUE INDEX corpus_curated_initial_idx ON authority_corpus_curated_revision(project_id,corpus_id) WHERE previous_id IS NULL",
    "CREATE INDEX corpus_curated_scope_idx ON authority_corpus_curated_revision(project_id,corpus_id,revision_id)",
    "CREATE INDEX corpus_curated_operation_idx ON authority_corpus_curated_revision(created_by_operation_id)",
    """CREATE TABLE authority_corpus_curated_member (
 revision_id TEXT NOT NULL, project_id TEXT NOT NULL, processing_id TEXT NOT NULL, edition_id TEXT NOT NULL,
 evidence JSONB NOT NULL,
 PRIMARY KEY(revision_id,edition_id),
 FOREIGN KEY(revision_id,project_id) REFERENCES authority_corpus_curated_revision(revision_id,project_id),
 FOREIGN KEY(processing_id,project_id,edition_id) REFERENCES authority_corpus_processing(processing_id,project_id,edition_id))""",
    "CREATE INDEX corpus_curated_member_processing_idx ON authority_corpus_curated_member(processing_id)",
    "CREATE INDEX corpus_curated_member_edition_idx ON authority_corpus_curated_member(project_id,edition_id)",
    "CREATE TRIGGER corpus_curated_revision_immutable BEFORE UPDATE OR DELETE ON authority_corpus_curated_revision FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
    "CREATE TRIGGER corpus_curated_member_immutable BEFORE UPDATE OR DELETE ON authority_corpus_curated_member FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
    """CREATE FUNCTION authority_corpus_catalog_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_parent text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
 IF NOT EXISTS(SELECT 1 FROM authority_operation o WHERE o.operation_id=NEW.created_by_operation_id AND o.project_id=NEW.project_id AND o.workspace_id=NEW.workspace_id AND o.definition_name='source.corpus.commit') THEN
 RAISE EXCEPTION 'catalog revision requires scoped Source command' USING ERRCODE='23514'; END IF;
 IF NEW.previous_id IS NOT NULL THEN
 IF TG_TABLE_NAME='authority_corpus_work_revision' THEN
 SELECT revision_id INTO expected_parent FROM authority_corpus_work_revision p WHERE p.revision_id=NEW.previous_id AND p.project_id=NEW.project_id AND p.workspace_id=NEW.workspace_id AND p.work_id=NEW.work_id;
 ELSE
 SELECT revision_id INTO expected_parent FROM authority_corpus_curated_revision p WHERE p.revision_id=NEW.previous_id AND p.project_id=NEW.project_id AND p.workspace_id=NEW.workspace_id AND p.corpus_id=NEW.corpus_id;
 END IF;
 IF expected_parent IS NULL THEN RAISE EXCEPTION 'catalog parent mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$""",
    "CREATE TRIGGER corpus_work_revision_scope BEFORE INSERT ON authority_corpus_work_revision FOR EACH ROW EXECUTE FUNCTION authority_corpus_catalog_revision_guard()",
    "CREATE TRIGGER corpus_curated_revision_scope BEFORE INSERT ON authority_corpus_curated_revision FOR EACH ROW EXECUTE FUNCTION authority_corpus_catalog_revision_guard()",
    """CREATE FUNCTION authority_corpus_curated_member_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM authority_corpus_membership m JOIN authority_corpus_edition e ON e.edition_id=m.edition_id JOIN authority_corpus_snapshot s ON s.snapshot_id=e.snapshot_id
 WHERE m.membership_id=NEW.evidence->>'membership_id' AND m.project_id=NEW.project_id AND m.edition_id=NEW.edition_id AND m.purpose=NEW.evidence->>'purpose' AND s.rights_id=NEW.evidence->>'rights_id') THEN
 RAISE EXCEPTION 'curated member must retain exact purpose membership and rights' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$""",
    "CREATE TRIGGER corpus_curated_member_scope BEFORE INSERT ON authority_corpus_curated_member FOR EACH ROW EXECUTE FUNCTION authority_corpus_curated_member_guard()",
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
                AND (o.definition_name='source.import.corpus.acquire' OR (o.definition_name='source.import.corpus.analysis' AND EXISTS(SELECT 1 FROM authority_corpus_curated_revision r WHERE r.revision_id=o.command_payload->'payload'->>'curated_revision_id' AND r.project_id=NEW.project_id AND r.workspace_id=NEW.workspace_id AND r.manifest->>'state'='FROZEN')) OR (
                    o.definition_name='source.import.corpus.work' AND o.command_payload->'payload' ? 'reprocess'
                    AND o.command_payload->'payload'->>'snapshot_id'=NEW.corpus_snapshot_id
                    AND EXISTS(SELECT 1 FROM authority_source_work_version w JOIN authority_corpus_edition e ON e.edition_id=w.corpus_edition_id
                        WHERE w.asset_version_id=o.command_payload->'payload'->'reprocess'->>'parent_work'
                        AND w.project_id=NEW.project_id AND e.snapshot_id=NEW.corpus_snapshot_id
                        AND e.edition_id=o.command_payload->'payload'->>'edition_id')))
                
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
]
