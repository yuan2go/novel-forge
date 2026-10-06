from __future__ import annotations

MIGRATION_ID = '20261007_0160_planning_result_admission'
DOWN_REVISION = '20261007_0159_planning_dead_letter_result_recovery'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'retain terminal failures and original settled Provider evidence; append result admission receipts'

UPGRADE_STATEMENTS = [
    r"""CREATE TABLE authority_planning_result_admission (
        recovery_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        source_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        recovery_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        source_result_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        candidate_asset_version_id TEXT NOT NULL UNIQUE REFERENCES authority_asset_version(asset_version_id),
        external_effect_id TEXT NOT NULL REFERENCES authority_external_effect(external_effect_id),
        source_generation_version BIGINT NOT NULL CHECK(source_generation_version>=0),
        evidence JSONB NOT NULL CHECK(jsonb_typeof(evidence)='object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK(source_operation_id<>recovery_operation_id)
    )""",
    r"""CREATE INDEX authority_result_admission_project_idx ON authority_planning_result_admission(project_id,book_id)""",
    r"""CREATE INDEX authority_result_admission_book_idx ON authority_planning_result_admission(book_id)""",
    r"""CREATE INDEX authority_result_admission_source_asset_idx ON authority_planning_result_admission(source_result_asset_version_id)""",
    r"""CREATE INDEX authority_result_admission_effect_idx ON authority_planning_result_admission(external_effect_id)""",
    r"""CREATE FUNCTION authority_result_admission_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'PLANNING_RESULT_ADMISSION_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM authority_story_planning_generation g
            JOIN authority_operation source ON source.operation_id=g.operation_id
            JOIN authority_operation recovery ON recovery.operation_id=NEW.recovery_operation_id
            JOIN authority_operation_output_asset raw ON raw.operation_id=source.operation_id
                AND raw.asset_version_id=NEW.source_result_asset_version_id
            JOIN authority_operation_output_asset candidate ON candidate.operation_id=recovery.operation_id
                AND candidate.asset_version_id=NEW.candidate_asset_version_id
            JOIN authority_external_effect effect ON effect.operation_id=source.operation_id
                AND effect.external_effect_id=NEW.external_effect_id AND effect.status='SUCCEEDED'
            WHERE source.operation_id=NEW.source_operation_id AND source.status='FAILED_FINAL'
                AND source.project_id=NEW.project_id AND recovery.project_id=source.project_id
                AND recovery.workspace_id=source.workspace_id AND g.book_id=NEW.book_id
                AND recovery.definition_name='story_planning.result_admission.recover'
                AND recovery.causation_operation_id=source.operation_id
                AND g.version=NEW.source_generation_version AND g.candidate_asset_version_id IS NULL
        ) THEN
            RAISE EXCEPTION 'PLANNING_RESULT_ADMISSION_SCOPE_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$""",
    r"""CREATE TRIGGER authority_result_admission_guard BEFORE INSERT OR UPDATE OR DELETE
        ON authority_planning_result_admission FOR EACH ROW EXECUTE FUNCTION authority_result_admission_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
