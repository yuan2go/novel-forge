from __future__ import annotations

MIGRATION_ID = "20260927_0147_runtime_job_dispatch_pause"
DOWN_REVISION = "20260927_0146_edition_prefix_inheritance"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "preserve immutable attempts and append verified control-pause evidence; never reset retry or budget history"

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_runtime_job ADD COLUMN paused_attempt_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE authority_runtime_job DROP CONSTRAINT authority_runtime_job_attempt_bounds_check",
    """ALTER TABLE authority_runtime_job ADD CONSTRAINT authority_runtime_job_attempt_bounds_check CHECK (
        attempt_count>=0 AND max_attempts>0 AND paused_attempt_count>=0
        AND paused_attempt_count<=attempt_count AND attempt_count-paused_attempt_count<=max_attempts
    )""",
    """CREATE FUNCTION authority_runtime_job_pause_count_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE verified_count integer;
    BEGIN
        IF TG_OP='UPDATE' AND NEW.paused_attempt_count<OLD.paused_attempt_count THEN
            RAISE EXCEPTION 'Runtime dispatch pause history is monotonic' USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO verified_count FROM authority_runtime_job_attempt attempt
        WHERE attempt.runtime_job_id=NEW.runtime_job_id AND attempt.status='FAILED'
          AND attempt.error @> '{"dispatch_pause_contract":"runtime-dispatch-control.v1","code":"RUNTIME_DISPATCH_PAUSED","request_sent":false}'::jsonb;
        IF NEW.paused_attempt_count<>verified_count THEN
            RAISE EXCEPTION 'Runtime dispatch pause count requires exact retained attempt evidence' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER authority_runtime_job_pause_count_guard BEFORE INSERT OR UPDATE OF paused_attempt_count
        ON authority_runtime_job FOR EACH ROW EXECUTE FUNCTION authority_runtime_job_pause_count_guard()""",
    """UPDATE authority_runtime_job job SET paused_attempt_count=(
        SELECT count(*) FROM authority_runtime_job_attempt attempt
        WHERE attempt.runtime_job_id=job.runtime_job_id AND attempt.status='FAILED'
          AND attempt.error @> '{"dispatch_pause_contract":"runtime-dispatch-control.v1","code":"RUNTIME_DISPATCH_PAUSED","request_sent":false}'::jsonb
    )""",
]
DOWNGRADE_STATEMENTS: list[str] = []
