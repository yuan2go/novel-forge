from __future__ import annotations

MIGRATION_ID = '20260910_0128_corpus_operations'
DOWN_REVISION = '20260909_0127_corpus_curation'
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = 'index job-scoped execution and enforce final canonical relation consistency without rewriting historical decisions'

UPGRADE_STATEMENTS = [
    'CREATE INDEX source_import_work_job_operation_idx ON authority_source_import_work(project_id,import_job_id,operation_id)',
    'CREATE INDEX corpus_equivalence_right_scope_idx ON authority_corpus_equivalence(project_id,right_id)',
    'CREATE INDEX corpus_equivalence_left_scope_idx ON authority_corpus_equivalence(project_id,left_id)',
    '''CREATE FUNCTION authority_corpus_relation_consistency() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE editions TEXT[];
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('source-corpus-authorization:'||NEW.project_id,0));
      IF TG_TABLE_NAME='authority_corpus_equivalence' THEN
        SELECT array_agg(edition_id) INTO editions FROM authority_corpus_processing WHERE processing_id IN (NEW.left_id,NEW.right_id);
      ELSE editions:=ARRAY[NEW.edition_id]; END IF;
      IF EXISTS (
        SELECT 1 FROM authority_corpus_work_member a
        JOIN authority_corpus_work_revision r USING(revision_id,project_id)
        JOIN authority_corpus_work_member b ON b.revision_id=a.revision_id AND b.project_id=a.project_id AND b.edition_id<>a.edition_id
        JOIN authority_corpus_processing x ON x.project_id=a.project_id AND x.edition_id=a.edition_id
        JOIN authority_corpus_processing y ON y.project_id=b.project_id AND y.edition_id=b.edition_id
        JOIN authority_corpus_equivalence e ON e.project_id=a.project_id AND e.left_id=LEAST(x.processing_id,y.processing_id) AND e.right_id=GREATEST(x.processing_id,y.processing_id)
        WHERE a.project_id=NEW.project_id AND a.edition_id=ANY(editions) AND r.manifest->>'state'='ACTIVE'
          AND NOT EXISTS(SELECT 1 FROM authority_corpus_work_revision n WHERE n.previous_id=r.revision_id)
          AND NOT EXISTS(SELECT 1 FROM authority_corpus_equivalence n WHERE n.previous_id=e.decision_id)
          AND (e.relation='DIFFERENT_WORK' OR (e.relation IS NULL AND e.decision='REJECT'))
      ) THEN RAISE EXCEPTION 'canonical members contradict current negative relation' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$''',
    'CREATE CONSTRAINT TRIGGER corpus_relation_consistency AFTER INSERT ON authority_corpus_equivalence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authority_corpus_relation_consistency()',
    'CREATE CONSTRAINT TRIGGER corpus_membership_relation_consistency AFTER INSERT ON authority_corpus_work_member DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authority_corpus_relation_consistency()',
]
