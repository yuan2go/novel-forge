from __future__ import annotations


MIGRATION_ID = "20260805_0070_agent_runtime_recovery_protocol"
DOWN_REVISION = "20260805_0069_agent_runtime_domain_commit_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Preserve immutable recovery and supersession facts, repair only missing "
    "audit/outbox projections, and resume through the current Authority "
    "Attempt lease. Never rewrite the frozen ExecutionRequest or Candidate."
)


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_agent_collaboration_session
    ADD COLUMN attempt_id TEXT REFERENCES authority_attempt(attempt_id)
    """,
    """
    UPDATE authority_agent_collaboration_session AS session
    SET attempt_id = turn.attempt_id
    FROM (
        SELECT DISTINCT ON (session_id) session_id, attempt_id
        FROM authority_agent_collaboration_turn
        ORDER BY session_id, turn_number
    ) AS turn
    WHERE turn.session_id = session.session_id
    """,
    """
    ALTER TABLE authority_agent_collaboration_session
    DROP CONSTRAINT authority_agent_collaboration_session_created_operation_id_key
    """,
    """
    ALTER TABLE authority_agent_collaboration_session
    DROP CONSTRAINT authority_agent_collaboration_session_saga_id_key
    """,
    """
    CREATE UNIQUE INDEX authority_agent_session_attempt_unique
    ON authority_agent_collaboration_session(attempt_id)
    WHERE attempt_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_agent_session_operation_attempt_idx
    ON authority_agent_collaboration_session(
        created_operation_id, attempt_id, created_at
    )
    """,
    """
    ALTER TABLE authority_agent_collaboration_turn
    DROP CONSTRAINT authority_agent_collaboration_turn_operation_id_key
    """,
    """
    CREATE INDEX authority_agent_collaboration_turn_operation_attempt_idx
    ON authority_agent_collaboration_turn(operation_id, attempt_id, created_at)
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_session_attempt_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        attempt_operation TEXT;
        operation_project TEXT;
    BEGIN
        IF TG_OP = 'UPDATE'
           AND OLD.attempt_id IS NOT NULL
           AND NEW.attempt_id IS DISTINCT FROM OLD.attempt_id THEN
            RAISE EXCEPTION 'collaboration Session Attempt binding is immutable'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_session_attempt_immutable';
        END IF;
        IF NEW.attempt_id IS NULL THEN
            RETURN NEW;
        END IF;
        SELECT attempt.operation_id, operation.project_id
        INTO attempt_operation, operation_project
        FROM authority_attempt AS attempt
        JOIN authority_operation AS operation
          ON operation.operation_id=attempt.operation_id
        WHERE attempt.attempt_id=NEW.attempt_id;
        IF attempt_operation IS DISTINCT FROM NEW.created_operation_id
           OR operation_project IS DISTINCT FROM NEW.project_id THEN
            RAISE EXCEPTION 'collaboration Session Attempt scope is invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_session_attempt_scope';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_agent_session_attempt_fact_guard
    BEFORE INSERT OR UPDATE OF attempt_id
    ON authority_agent_collaboration_session
    FOR EACH ROW EXECUTE FUNCTION authority_agent_session_attempt_guard()
    """,
    """
    CREATE TABLE authority_execution_recovery_authorization (
        authorization_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        external_effect_id TEXT NOT NULL
            REFERENCES authority_external_effect(external_effect_id),
        execution_id TEXT NOT NULL,
        execution_fencing_token BIGINT NOT NULL,
        recovery_fencing_token BIGINT NOT NULL,
        recovery_worker_id TEXT NOT NULL,
        action TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(execution_id, recovery_fencing_token, action),
        FOREIGN KEY(attempt_id, execution_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        FOREIGN KEY(attempt_id, recovery_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        CHECK (execution_id <> '' AND recovery_worker_id <> ''),
        CHECK (execution_fencing_token > 0),
        CHECK (recovery_fencing_token >= execution_fencing_token),
        CHECK (action IN (
            'DISPATCH_PLANNED', 'QUERY', 'CANCEL',
            'CONSUME_RESULT', 'FINALIZE'
        ))
    )
    """,
    """
    CREATE INDEX authority_execution_recovery_project_query_idx
    ON authority_execution_recovery_authorization(
        project_id, operation_id, attempt_id, created_at
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_execution_recovery_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        operation_project TEXT;
        attempt_operation TEXT;
        effect_operation TEXT;
        effect_project TEXT;
        frozen_attempt TEXT;
        frozen_fence BIGINT;
        current_owner TEXT;
    BEGIN
        SELECT project_id INTO operation_project
        FROM authority_operation WHERE operation_id=NEW.operation_id;
        SELECT operation_id INTO attempt_operation
        FROM authority_attempt WHERE attempt_id=NEW.attempt_id;
        SELECT operation_id, project_id,
               request_payload->'_production_execution'->>'attempt_id',
               NULLIF(
                   request_payload->'_production_execution'->>'fencing_token',
                   ''
               )::BIGINT
        INTO effect_operation, effect_project, frozen_attempt, frozen_fence
        FROM authority_external_effect
        WHERE external_effect_id=NEW.external_effect_id;
        SELECT owner INTO current_owner
        FROM authority_lease_acquisition
        WHERE attempt_id=NEW.attempt_id
          AND fencing_token=NEW.recovery_fencing_token
          AND status='HELD' AND expires_at > NOW();
        IF operation_project IS DISTINCT FROM NEW.project_id
           OR attempt_operation IS DISTINCT FROM NEW.operation_id
           OR effect_operation IS DISTINCT FROM NEW.operation_id
           OR effect_project IS DISTINCT FROM NEW.project_id
           OR frozen_attempt IS DISTINCT FROM NEW.attempt_id
           OR frozen_fence IS DISTINCT FROM NEW.execution_fencing_token
           OR current_owner IS DISTINCT FROM NEW.recovery_worker_id THEN
            RAISE EXCEPTION 'Execution Recovery Authorization facts are invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_execution_recovery_fact_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_execution_recovery_fact_guard
    AFTER INSERT ON authority_execution_recovery_authorization
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_execution_recovery_guard()
    """,
    """
    CREATE TRIGGER authority_execution_recovery_immutable
    BEFORE UPDATE OR DELETE ON authority_execution_recovery_authorization
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TABLE authority_agent_candidate_supersession (
        supersession_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        superseded_attempt_id TEXT NOT NULL
            REFERENCES authority_attempt(attempt_id),
        superseding_attempt_id TEXT NOT NULL
            REFERENCES authority_attempt(attempt_id),
        superseded_candidate_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        superseding_candidate_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        recovery_fencing_token BIGINT NOT NULL,
        created_by_worker TEXT NOT NULL,
        failure_reason JSONB NOT NULL,
        retry_policy_ref TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(superseding_attempt_id, recovery_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        CHECK (superseded_attempt_id <> superseding_attempt_id),
        CHECK (
            superseded_candidate_version_id
            <> superseding_candidate_version_id
        ),
        CHECK (recovery_fencing_token > 0),
        CHECK (created_by_worker <> '' AND retry_policy_ref <> '')
    )
    """,
    """
    CREATE INDEX authority_agent_candidate_supersession_query_idx
    ON authority_agent_candidate_supersession(
        project_id, operation_id, superseding_attempt_id, created_at
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_candidate_supersession_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        old_operation TEXT;
        new_operation TEXT;
        old_project TEXT;
        new_project TEXT;
        old_number INTEGER;
        new_number INTEGER;
        current_owner TEXT;
    BEGIN
        SELECT turn.operation_id, session.project_id, attempt.attempt_number
        INTO old_operation, old_project, old_number
        FROM authority_agent_candidate_version AS candidate
        JOIN authority_agent_collaboration_turn AS turn
          ON turn.turn_id=candidate.originating_turn_id
        JOIN authority_agent_collaboration_session AS session
          ON session.session_id=candidate.session_id
        JOIN authority_attempt AS attempt
          ON attempt.attempt_id=turn.attempt_id
        WHERE candidate.candidate_version_id=
              NEW.superseded_candidate_version_id
          AND turn.attempt_id=NEW.superseded_attempt_id;
        SELECT turn.operation_id, session.project_id, attempt.attempt_number
        INTO new_operation, new_project, new_number
        FROM authority_agent_candidate_version AS candidate
        JOIN authority_agent_collaboration_turn AS turn
          ON turn.turn_id=candidate.originating_turn_id
        JOIN authority_agent_collaboration_session AS session
          ON session.session_id=candidate.session_id
        JOIN authority_attempt AS attempt
          ON attempt.attempt_id=turn.attempt_id
        WHERE candidate.candidate_version_id=
              NEW.superseding_candidate_version_id
          AND turn.attempt_id=NEW.superseding_attempt_id;
        SELECT owner INTO current_owner
        FROM authority_lease_acquisition
        WHERE attempt_id=NEW.superseding_attempt_id
          AND fencing_token=NEW.recovery_fencing_token
          AND status='HELD' AND expires_at > NOW();
        IF old_operation IS DISTINCT FROM NEW.operation_id
           OR new_operation IS DISTINCT FROM NEW.operation_id
           OR old_project IS DISTINCT FROM NEW.project_id
           OR new_project IS DISTINCT FROM NEW.project_id
           OR old_number >= new_number
           OR current_owner IS DISTINCT FROM NEW.created_by_worker
           OR EXISTS(
               SELECT 1 FROM authority_agent_collaboration_commit
               WHERE candidate_version_id=
                     NEW.superseded_candidate_version_id
           ) THEN
            RAISE EXCEPTION 'Agent Candidate Supersession facts are invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_candidate_supersession_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_agent_candidate_supersession_fact_guard
    AFTER INSERT ON authority_agent_candidate_supersession
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_agent_candidate_supersession_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_superseded_commit_guard()
    RETURNS TRIGGER AS $$
    BEGIN
        IF EXISTS(
            SELECT 1 FROM authority_agent_candidate_supersession
            WHERE superseded_candidate_version_id=NEW.candidate_version_id
        ) THEN
            RAISE EXCEPTION 'superseded Agent Candidate cannot be committed'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_superseded_commit_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_agent_superseded_commit_fact_guard
    AFTER INSERT ON authority_agent_collaboration_commit
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_agent_superseded_commit_guard()
    """,
    """
    CREATE TRIGGER authority_agent_candidate_supersession_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_candidate_supersession
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_runtime_binding_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        attempt_operation_id TEXT;
        operation_project_id TEXT;
        operation_definition_name_value TEXT;
        operation_definition_version_value TEXT;
        work_order_attempt_id TEXT;
        work_order_fencing_token BIGINT;
        work_order_agent_id TEXT;
        work_order_agent_version INTEGER;
        work_order_capability_id TEXT;
        work_order_capability_version INTEGER;
        work_order_execution_capability_id TEXT;
        execution_lease_exists BOOLEAN;
        recovery_authorization_exists BOOLEAN;
    BEGIN
        SELECT attempt.operation_id
        INTO attempt_operation_id
        FROM authority_attempt AS attempt
        WHERE attempt.attempt_id=NEW.attempt_id;
        SELECT operation.project_id, operation.definition_name,
               operation.definition_version
        INTO operation_project_id, operation_definition_name_value,
             operation_definition_version_value
        FROM authority_operation AS operation
        WHERE operation.operation_id=NEW.operation_id;
        SELECT work_order.attempt_id, work_order.fencing_token,
               work_order.agent_id, work_order.agent_definition_version,
               work_order.capability_id, work_order.capability_version,
               work_order.execution_capability_id
        INTO work_order_attempt_id, work_order_fencing_token,
             work_order_agent_id, work_order_agent_version,
             work_order_capability_id, work_order_capability_version,
             work_order_execution_capability_id
        FROM authority_agent_work_order AS work_order
        WHERE work_order.work_order_id=NEW.work_order_id
          AND work_order.operation_id=NEW.operation_id;
        SELECT EXISTS(
            SELECT 1 FROM authority_lease_acquisition AS lease
            WHERE lease.attempt_id=NEW.attempt_id
              AND lease.fencing_token=NEW.fencing_token
        ) INTO execution_lease_exists;
        SELECT EXISTS(
            SELECT 1
            FROM authority_execution_recovery_authorization AS recovery
            WHERE recovery.operation_id=NEW.operation_id
              AND recovery.attempt_id=NEW.attempt_id
              AND recovery.execution_fencing_token=NEW.fencing_token
              AND recovery.recovery_fencing_token=work_order_fencing_token
              AND recovery.action='DISPATCH_PLANNED'
        ) INTO recovery_authorization_exists;
        IF attempt_operation_id IS DISTINCT FROM NEW.operation_id
           OR operation_project_id IS DISTINCT FROM NEW.project_id
           OR operation_definition_name_value
                IS DISTINCT FROM NEW.operation_definition_name
           OR operation_definition_version_value
                IS DISTINCT FROM NEW.operation_definition_version
           OR work_order_attempt_id IS DISTINCT FROM NEW.attempt_id
           OR (
               work_order_fencing_token IS DISTINCT FROM NEW.fencing_token
               AND NOT recovery_authorization_exists
           )
           OR work_order_agent_id IS DISTINCT FROM NEW.agent_id
           OR work_order_agent_version
                IS DISTINCT FROM NEW.agent_definition_version
           OR work_order_capability_id IS DISTINCT FROM NEW.capability_id
           OR work_order_capability_version
                IS DISTINCT FROM NEW.capability_version
           OR work_order_execution_capability_id
                IS DISTINCT FROM NEW.execution_capability_id
           OR NOT execution_lease_exists THEN
            RAISE EXCEPTION 'Agent Runtime binding differs from Authority facts'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_runtime_binding_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
