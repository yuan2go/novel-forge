from __future__ import annotations

from .v20260829_0103_book_opening_semantic_runtime_hardening import (
    UPGRADE_STATEMENTS as _SEMANTIC_RUNTIME_UPGRADE_STATEMENTS,
)


def _versioned_narrative_replacement_gate_statement() -> str:
    source = next(
        statement
        for statement in _SEMANTIC_RUNTIME_UPGRADE_STATEMENTS
        if "CREATE OR REPLACE FUNCTION authority_narrative_replacement_gate_is_open"
        in statement
    )
    recovery_legacy_identity = """AND job.job_kind='BOOK_OPENING_EXECUTE'
              AND job.runtime_group='book_opening'"""
    opening_legacy_identity = """AND job.job_kind='BOOK_OPENING_EXECUTE'
             AND job.runtime_group='book_opening'"""
    legacy_execution_contract = """AND opening.execution_contract_version=
                  'book-opening-execution-v2'"""
    if (
        source.count(recovery_legacy_identity) != 1
        or source.count(opening_legacy_identity) != 2
        or source.count(legacy_execution_contract) != 2
    ):
        raise RuntimeError("0103 narrative replacement gate source shape drifted")
    recovery_identity = """AND (
                  (
                      job.job_kind='BOOK_OPENING_EXECUTE'
                      AND job.runtime_group='book_opening'
                  ) OR (
                      job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                      AND job.runtime_group='book_opening_workflow_v1'
                  )
              )"""
    exact_opening_identity = """AND (
                  (
                      opening.workflow_contract_version=
                          'legacy-monolithic-v2'
                      AND opening.execution_contract_version=
                          'book-opening-execution-v2'
                      AND job.job_kind='BOOK_OPENING_EXECUTE'
                      AND job.runtime_group='book_opening'
                  ) OR (
                      opening.workflow_contract_version=
                          'book-opening-workflow-v1'
                      AND opening.execution_contract_version=
                          'book-opening-execution-v3'
                      AND job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                      AND job.runtime_group='book_opening_workflow_v1'
                  )
              )"""
    versioned = source.replace(recovery_legacy_identity, recovery_identity)
    versioned = versioned.replace(opening_legacy_identity, exact_opening_identity)
    return versioned.replace(legacy_execution_contract, "")


_VERSIONED_NARRATIVE_REPLACEMENT_GATE = (
    _versioned_narrative_replacement_gate_statement()
)


MIGRATION_ID = "20260829_0104_book_opening_workflow_nodes"
DOWN_REVISION = "20260829_0103_book_opening_semantic_runtime_hardening"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "preserve legacy-monolithic-v2 Book Opening history unchanged; admit only "
    "new book-opening-workflow-v1 runs through the owning Book Opening and "
    "RuntimeJob Authority transaction paths"
)


PREFLIGHT_STATEMENTS = [
    """
    SELECT 'multiple_active_or_recoverable_openings_per_book',COUNT(*)
    FROM (
        SELECT project_id,book_id
        FROM authority_book_opening_run
        WHERE lifecycle IN ('ADMITTED','RUNNING','FAILED')
        GROUP BY project_id,book_id
        HAVING COUNT(*)>1
    ) AS duplicate
    """,
    """
    SELECT 'unsupported_book_opening_execution_contract',COUNT(*)
    FROM authority_book_opening_run
    WHERE execution_contract_version NOT IN (
        'legacy-unbound','book-opening-execution-v2'
    )
    """,
]


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_book_opening_run
    ADD COLUMN workflow_contract_version TEXT NOT NULL
        DEFAULT 'legacy-monolithic-v2',
    ADD COLUMN current_workflow_node_id TEXT,
    ADD COLUMN workflow_graph_revision BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN workflow_graph_hash TEXT NOT NULL DEFAULT '',
    ADD CONSTRAINT authority_bo_run_workflow_contract_shape_check CHECK (
        (
            workflow_contract_version='legacy-monolithic-v2'
            AND current_workflow_node_id IS NULL
            AND workflow_graph_revision=0
            AND workflow_graph_hash=''
        ) OR (
            workflow_contract_version='book-opening-workflow-v1'
            AND current_workflow_node_id IS NOT NULL
            AND workflow_graph_revision=1
            AND workflow_graph_hash ~ '^sha256:[0-9a-f]{64}$'
        )
    )
    """,
    """
    -- Existing rows were backfilled by the preceding ADD COLUMN defaults.
    -- Remove those defaults at cutover so a pre-0104 writer cannot silently
    -- admit a new legacy-monolithic run after the node workflow is canonical.
    ALTER TABLE authority_book_opening_run
        ALTER COLUMN workflow_contract_version DROP DEFAULT,
        ALTER COLUMN workflow_graph_revision DROP DEFAULT,
        ALTER COLUMN workflow_graph_hash DROP DEFAULT
    """,
    """
    ALTER TABLE authority_book_opening_run
    ADD CONSTRAINT authority_bo_run_execution_contract_pair_check CHECK (
        (
            workflow_contract_version='legacy-monolithic-v2'
            AND execution_contract_version IN (
                'legacy-unbound','book-opening-execution-v2'
            )
        ) OR (
            workflow_contract_version='book-opening-workflow-v1'
            AND execution_contract_version='book-opening-execution-v3'
        )
    )
    """,
    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_book_opening_runtime_identity_pair_check CHECK (
        NOT (
            job_kind IN (
                'BOOK_OPENING_EXECUTE',
                'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
            )
            OR runtime_group IN (
                'book_opening','book_opening_workflow_v1'
            )
        ) OR (
            subject_kind='BOOK_OPENING_RUN'
            AND (
                (
                    job_kind='BOOK_OPENING_EXECUTE'
                    AND runtime_group='book_opening'
                ) OR (
                    job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                    AND runtime_group='book_opening_workflow_v1'
                )
            )
        )
    ) NOT VALID,
    ADD CONSTRAINT authority_book_opening_workflow_runtime_policy_check CHECK (
        NOT (
            job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
            AND runtime_group='book_opening_workflow_v1'
            AND subject_kind='BOOK_OPENING_RUN'
        ) OR (
            lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
            AND max_attempts=1
        )
    ) NOT VALID
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_runtime_policy_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        legacy_identity BOOLEAN;
        workflow_identity BOOLEAN;
        opening_identity_token BOOLEAN;
    BEGIN
        legacy_identity = (
            NEW.job_kind='BOOK_OPENING_EXECUTE'
            AND NEW.runtime_group='book_opening'
            AND NEW.subject_kind='BOOK_OPENING_RUN'
        );
        workflow_identity = (
            NEW.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
            AND NEW.runtime_group='book_opening_workflow_v1'
            AND NEW.subject_kind='BOOK_OPENING_RUN'
        );
        opening_identity_token = (
            NEW.job_kind IN (
                'BOOK_OPENING_EXECUTE',
                'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
            )
            OR NEW.runtime_group IN (
                'book_opening','book_opening_workflow_v1'
            )
        );
        IF opening_identity_token AND NOT (legacy_identity OR workflow_identity) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_IDENTITY_INVALID:%',
                NEW.runtime_job_id
                USING ERRCODE='check_violation';
        END IF;
        IF legacy_identity OR workflow_identity THEN
            IF TG_OP='INSERT' THEN
                NEW.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED';
                NEW.max_attempts=1;
            ELSIF (
                NEW.lease_loss_policy IS DISTINCT FROM
                    'AUTHORITY_CONVERGENCE_REQUIRED'
                OR NEW.max_attempts IS DISTINCT FROM 1
            ) AND NOT (
                legacy_identity
                AND OLD.job_kind='BOOK_OPENING_EXECUTE'
                AND OLD.runtime_group='book_opening'
                AND OLD.subject_kind='BOOK_OPENING_RUN'
                AND OLD.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
                AND OLD.max_attempts<>1
                AND NEW.lease_loss_policy IS NOT DISTINCT FROM
                    OLD.lease_loss_policy
                AND NEW.max_attempts IS NOT DISTINCT FROM OLD.max_attempts
            ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_POLICY_INVALID:%',
                    NEW.runtime_job_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    ALTER TABLE authority_runtime_job
    ADD CONSTRAINT authority_book_opening_workflow_semantic_binding_shape_check
    CHECK (
        NOT (
            job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
            AND runtime_group='book_opening_workflow_v1'
            AND subject_kind='BOOK_OPENING_RUN'
        ) OR (
            input_snapshot ? 'semantic_evaluation_operation_id'
            AND input_snapshot ? 'semantic_evaluation_execution_id'
            AND input_snapshot ? 'semantic_evaluation_generation'
            AND input_snapshot ? 'semantic_execution_mode'
            AND input_snapshot->>'semantic_execution_mode' IN (
                'NONE','NEW_REPLACEMENT','RESUME_CURRENT'
            )
            AND (
                (
                    input_snapshot->>'semantic_execution_mode'='NONE'
                    AND input_snapshot->>'semantic_evaluation_operation_id'=''
                    AND input_snapshot->>'semantic_evaluation_execution_id'=''
                    AND input_snapshot->>'semantic_evaluation_generation'='0'
                ) OR (
                    input_snapshot->>'semantic_execution_mode' IN (
                        'NEW_REPLACEMENT','RESUME_CURRENT'
                    )
                    AND NULLIF(
                        input_snapshot->>'semantic_evaluation_operation_id',''
                    ) IS NOT NULL
                    AND NULLIF(
                        input_snapshot->>'semantic_evaluation_execution_id',''
                    ) IS NOT NULL
                    AND input_snapshot->>'semantic_evaluation_generation'
                        ~ '^[1-9][0-9]*$'
                )
            )
        )
    ) NOT VALID
    """,
    """
    CREATE INDEX authority_runtime_job_workflow_semantic_evaluation_binding_idx
    ON authority_runtime_job(
        project_id,
        (input_snapshot->>'semantic_evaluation_operation_id'),
        (input_snapshot->>'semantic_evaluation_execution_id'),
        (input_snapshot->>'semantic_evaluation_generation'),
        (input_snapshot->>'semantic_execution_mode')
    ) WHERE job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
      AND runtime_group='book_opening_workflow_v1'
      AND subject_kind='BOOK_OPENING_RUN'
      AND input_snapshot ? 'semantic_execution_mode'
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_execution_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        opening_project_id TEXT;
        opening_workflow_contract TEXT;
        opening_execution_contract TEXT;
        runtime_project_id TEXT;
        runtime_job_kind TEXT;
        runtime_group_name TEXT;
        runtime_subject_kind TEXT;
        runtime_subject_id TEXT;
        runtime_lease_loss_policy TEXT;
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_HISTORY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE' AND ROW(
            OLD.opening_execution_id,
            OLD.opening_run_id,
            OLD.generation,
            OLD.predecessor_execution_id,
            OLD.predecessor_generation,
            OLD.runtime_job_id,
            OLD.frozen_request_digest,
            OLD.input_snapshot_hash,
            OLD.policy_snapshot_hash,
            OLD.authority_contract_hash,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.opening_execution_id,
            NEW.opening_run_id,
            NEW.generation,
            NEW.predecessor_execution_id,
            NEW.predecessor_generation,
            NEW.runtime_job_id,
            NEW.frozen_request_digest,
            NEW.input_snapshot_hash,
            NEW.policy_snapshot_hash,
            NEW.authority_contract_hash,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE'
           AND OLD.lifecycle IN ('SUCCEEDED','FAILED','LOST','ABORTED')
           AND ROW(OLD.*) IS DISTINCT FROM ROW(NEW.*) THEN
            RAISE EXCEPTION 'BOOK_OPENING_EXECUTION_TERMINAL_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;

        SELECT project_id,workflow_contract_version,execution_contract_version
        INTO opening_project_id,opening_workflow_contract,
             opening_execution_contract
        FROM authority_book_opening_run
        WHERE opening_run_id=NEW.opening_run_id;
        IF NEW.runtime_job_id IS NULL THEN
            IF opening_project_id IS NULL
               OR opening_workflow_contract<>'legacy-monolithic-v2'
               OR opening_execution_contract NOT IN (
                   'legacy-unbound','book-opening-execution-v2'
               )
               OR NEW.generation IS DISTINCT FROM 1
               OR NEW.lifecycle NOT IN ('FAILED','ABORTED')
               OR NEW.current_attempt_id IS NOT NULL
               OR NEW.current_lease_id IS NOT NULL
               OR NEW.current_worker_id IS NOT NULL
               OR NEW.current_fencing_token IS NOT NULL THEN
                RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_BINDING_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END IF;
        SELECT project_id,job_kind,runtime_group,subject_kind,subject_id,
               lease_loss_policy
        INTO runtime_project_id,runtime_job_kind,runtime_group_name,
             runtime_subject_kind,runtime_subject_id,runtime_lease_loss_policy
        FROM authority_runtime_job
        WHERE runtime_job_id=NEW.runtime_job_id;
        IF opening_project_id IS NULL
           OR runtime_project_id IS DISTINCT FROM opening_project_id
           OR NOT (
               (
                   opening_workflow_contract='legacy-monolithic-v2'
                   AND opening_execution_contract=
                       'book-opening-execution-v2'
                   AND runtime_job_kind='BOOK_OPENING_EXECUTE'
                   AND runtime_group_name='book_opening'
               ) OR (
                   opening_workflow_contract='book-opening-workflow-v1'
                   AND opening_execution_contract=
                       'book-opening-execution-v3'
                   AND runtime_job_kind=
                       'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                   AND runtime_group_name='book_opening_workflow_v1'
               )
           )
           OR runtime_subject_kind IS DISTINCT FROM 'BOOK_OPENING_RUN'
           OR runtime_subject_id IS DISTINCT FROM NEW.opening_run_id
           OR runtime_lease_loss_policy IS DISTINCT FROM
              'AUTHORITY_CONVERGENCE_REQUIRED' THEN
            RAISE EXCEPTION 'BOOK_OPENING_RUNTIME_BINDING_INVALID'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_current_execution(
        target_opening_run_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        opening RECORD;
    BEGIN
        SELECT
            run.execution_contract_version,
            run.workflow_contract_version,
            run.lifecycle AS opening_lifecycle,
            run.recovery_state,
            run.current_execution_id,
            run.current_execution_generation,
            execution.lifecycle AS execution_lifecycle
        INTO opening
        FROM authority_book_opening_run AS run
        LEFT JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=run.opening_run_id
         AND execution.opening_execution_id=run.current_execution_id
         AND execution.generation=run.current_execution_generation
        WHERE run.opening_run_id=target_opening_run_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF NOT (
            (
                opening.workflow_contract_version='legacy-monolithic-v2'
                AND opening.execution_contract_version=
                    'book-opening-execution-v2'
            ) OR (
                opening.workflow_contract_version='book-opening-workflow-v1'
                AND opening.execution_contract_version=
                    'book-opening-execution-v3'
            )
        ) THEN
            IF opening.execution_contract_version='legacy-unbound'
               AND opening.workflow_contract_version='legacy-monolithic-v2' THEN
                RETURN;
            END IF;
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        IF opening.current_execution_id IS NULL
           OR opening.execution_lifecycle IS NULL
           OR opening.recovery_state='LEGACY_RECONCILIATION_REQUIRED'
           OR (
               opening.opening_lifecycle='ADMITTED'
               AND opening.execution_lifecycle NOT IN ('SCHEDULED','BOUND')
           )
           OR (
               opening.opening_lifecycle='RUNNING'
               AND opening.execution_lifecycle<>'RUNNING'
           )
           OR (
               opening.opening_lifecycle='COMPLETE'
               AND opening.execution_lifecycle<>'SUCCEEDED'
           )
           OR (
               opening.opening_lifecycle='FAILED'
               AND opening.execution_lifecycle NOT IN (
                   'FAILED','LOST','ABORTED'
               )
           )
           OR (
               opening.opening_lifecycle='ABORTED'
               AND opening.execution_lifecycle NOT IN (
                   'ABORTED','FAILED','LOST'
               )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        PERFORM authority_assert_book_opening_execution_binding(
            opening.current_execution_id
        );
    END;
    $$
    """,
    """
    CREATE UNIQUE INDEX authority_bo_one_active_workflow_per_book_idx
    ON authority_book_opening_run(project_id,book_id)
    WHERE lifecycle IN ('ADMITTED','RUNNING','FAILED')
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD CONSTRAINT authority_bo_legacy_snapshot_exact_identity_unique
    UNIQUE(snapshot_id,project_id,workspace_id,book_id,snapshot_hash)
    """,
    """
    CREATE TABLE authority_book_opening_legacy_snapshot_entitlement (
        snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL UNIQUE,
        source_migration_id TEXT NOT NULL,
        entitled_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
        FOREIGN KEY(
            snapshot_id,project_id,workspace_id,book_id,snapshot_hash
        ) REFERENCES authority_book_production_input_snapshot(
            snapshot_id,project_id,workspace_id,book_id,snapshot_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (
            source_migration_id=
                '20260829_0104_book_opening_workflow_nodes'
        ),
        CHECK (snapshot_hash LIKE 'sha256:%')
    )
    """,
    """
    INSERT INTO authority_book_opening_legacy_snapshot_entitlement(
        snapshot_id,project_id,workspace_id,book_id,snapshot_hash,
        source_migration_id
    )
    SELECT
        snapshot.snapshot_id,
        snapshot.project_id,
        snapshot.workspace_id,
        snapshot.book_id,
        snapshot.snapshot_hash,
        '20260829_0104_book_opening_workflow_nodes'
    FROM authority_book_production_input_snapshot AS snapshot
    """,
    """
    CREATE OR REPLACE FUNCTION
        authority_book_opening_legacy_snapshot_entitlement_sealed()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION
            'BOOK_OPENING_LEGACY_SNAPSHOT_ENTITLEMENT_SEALED:%',
            CASE
                WHEN TG_OP='DELETE' THEN OLD.snapshot_id
                ELSE NEW.snapshot_id
            END
            USING ERRCODE='check_violation';
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_bo_legacy_snapshot_entitlement_sealed
    BEFORE INSERT OR UPDATE OR DELETE
    ON authority_book_opening_legacy_snapshot_entitlement
    FOR EACH ROW
    EXECUTE FUNCTION
        authority_book_opening_legacy_snapshot_entitlement_sealed()
    """,
    """
    CREATE TABLE authority_book_opening_workflow_node (
        workflow_node_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        node_key TEXT NOT NULL,
        node_kind TEXT NOT NULL,
        ordinal SMALLINT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        input_contract JSONB NOT NULL,
        input_hash TEXT NOT NULL,
        graph_revision BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id,node_key),
        UNIQUE(opening_run_id,ordinal),
        UNIQUE(opening_run_id,stable_idempotency_key),
        UNIQUE(opening_run_id,workflow_node_id),
        CHECK (
            (node_key='book-plan'
             AND node_kind='BOOK_PLAN'
             AND ordinal=1)
            OR
            (node_key='volume-portfolio'
             AND node_kind='VOLUME_PORTFOLIO'
             AND ordinal=2)
            OR
            (node_key='current-volume'
             AND node_kind='CURRENT_VOLUME'
             AND ordinal=3)
            OR
            (node_key='initial-arc-scope'
             AND node_kind='INITIAL_ARC_SCOPE'
             AND ordinal=4)
            OR
            (node_key='input-snapshot'
             AND node_kind='INPUT_SNAPSHOT'
             AND ordinal=5)
        ),
        CHECK (NULLIF(stable_idempotency_key,'') IS NOT NULL),
        CHECK (jsonb_typeof(input_contract)='object'),
        CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (graph_revision=1)
    )
    """,
    """
    CREATE INDEX authority_bo_node_opening_fk_idx
    ON authority_book_opening_workflow_node(opening_run_id)
    """,
    """
    CREATE TABLE authority_book_opening_workflow_edge (
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        predecessor_workflow_node_id TEXT NOT NULL,
        successor_workflow_node_id TEXT NOT NULL,
        edge_kind TEXT NOT NULL DEFAULT 'REQUIRES',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(
            opening_run_id,
            predecessor_workflow_node_id,
            successor_workflow_node_id
        ),
        FOREIGN KEY(opening_run_id,predecessor_workflow_node_id)
            REFERENCES authority_book_opening_workflow_node(
                opening_run_id,workflow_node_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(opening_run_id,successor_workflow_node_id)
            REFERENCES authority_book_opening_workflow_node(
                opening_run_id,workflow_node_id
            ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (edge_kind='REQUIRES'),
        CHECK (predecessor_workflow_node_id<>successor_workflow_node_id)
    )
    """,
    """
    CREATE INDEX authority_bo_edge_successor_fk_idx
    ON authority_book_opening_workflow_edge(
        opening_run_id,successor_workflow_node_id
    )
    """,
    """
    ALTER TABLE authority_book_opening_run
    ADD CONSTRAINT authority_bo_run_current_node_fk
    FOREIGN KEY(opening_run_id,current_workflow_node_id)
    REFERENCES authority_book_opening_workflow_node(
        opening_run_id,workflow_node_id
    ) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_bo_run_current_node_fk_idx
    ON authority_book_opening_run(opening_run_id,current_workflow_node_id)
    WHERE current_workflow_node_id IS NOT NULL
    """,
    """
    ALTER TABLE authority_book_opening_execution
    ADD COLUMN workflow_node_id TEXT,
    ADD COLUMN workflow_transition_kind TEXT NOT NULL
        DEFAULT 'LEGACY_MONOLITHIC',
    ADD COLUMN source_checkpoint_id TEXT,
    ADD COLUMN source_checkpoint_sequence BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN source_checkpoint_hash TEXT NOT NULL DEFAULT ''
    """,
    """
    DO $$
    DECLARE
        lineage_constraints TEXT[];
    BEGIN
        SELECT ARRAY_AGG(constraint_row.conname ORDER BY constraint_row.conname)
        INTO lineage_constraints
        FROM (
            SELECT constraint_def.conname
            FROM pg_constraint AS constraint_def
            WHERE constraint_def.conrelid=
                    'authority_book_opening_execution'::regclass
              AND constraint_def.contype='c'
              AND pg_get_constraintdef(constraint_def.oid)
                    ~ 'generation[[:space:]]*=[[:space:]]*1'
              AND pg_get_constraintdef(constraint_def.oid)
                    LIKE '%predecessor_execution_id%'
              AND pg_get_constraintdef(constraint_def.oid)
                    LIKE '%recovery_intent_id%'
        ) AS constraint_row;
        IF COALESCE(CARDINALITY(lineage_constraints),0)<>1 THEN
            RAISE EXCEPTION
                'BOOK_OPENING_EXECUTION_LINEAGE_CONSTRAINT_AMBIGUOUS:%',
                COALESCE(CARDINALITY(lineage_constraints),0)
                USING ERRCODE='check_violation';
        END IF;
        EXECUTE FORMAT(
            'ALTER TABLE authority_book_opening_execution DROP CONSTRAINT %I',
            lineage_constraints[1]
        );
    END;
    $$
    """,
    """
    ALTER TABLE authority_book_opening_execution
    ADD CONSTRAINT authority_bo_execution_workflow_shape_check CHECK (
        workflow_transition_kind IN (
            'LEGACY_MONOLITHIC','ADMISSION','CONTINUATION','RECOVERY'
        )
        AND (
            (
                workflow_transition_kind='LEGACY_MONOLITHIC'
                AND workflow_node_id IS NULL
                AND (
                    (source_checkpoint_id IS NULL
                     AND source_checkpoint_sequence=0
                     AND source_checkpoint_hash='')
                    OR
                    (source_checkpoint_id IS NOT NULL
                     AND source_checkpoint_sequence>0
                     AND source_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
                )
            ) OR (
                workflow_transition_kind='ADMISSION'
                AND workflow_node_id IS NOT NULL
                AND source_checkpoint_id IS NULL
                AND source_checkpoint_sequence=0
                AND source_checkpoint_hash=''
            ) OR (
                workflow_transition_kind='CONTINUATION'
                AND workflow_node_id IS NOT NULL
                AND source_checkpoint_id IS NOT NULL
                AND source_checkpoint_sequence>0
                AND source_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'
            ) OR (
                workflow_transition_kind='RECOVERY'
                AND workflow_node_id IS NOT NULL
                AND (
                    (source_checkpoint_id IS NULL
                     AND source_checkpoint_sequence=0
                     AND source_checkpoint_hash='')
                    OR
                    (source_checkpoint_id IS NOT NULL
                     AND source_checkpoint_sequence>0
                     AND source_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$')
                )
            )
        )
    ),
    ADD CONSTRAINT authority_bo_execution_generation_lineage_check CHECK (
        (
            workflow_transition_kind='LEGACY_MONOLITHIC'
            AND (
                (generation=1
                 AND predecessor_execution_id IS NULL
                 AND predecessor_generation IS NULL
                 AND recovery_intent_id IS NULL)
                OR
                (generation>1
                 AND predecessor_execution_id IS NOT NULL
                 AND predecessor_generation=generation-1
                 AND recovery_intent_id IS NOT NULL)
            )
        ) OR (
            workflow_transition_kind='ADMISSION'
            AND generation=1
            AND predecessor_execution_id IS NULL
            AND predecessor_generation IS NULL
            AND recovery_intent_id IS NULL
        ) OR (
            workflow_transition_kind='CONTINUATION'
            AND generation>1
            AND predecessor_execution_id IS NOT NULL
            AND predecessor_generation=generation-1
            AND recovery_intent_id IS NULL
        ) OR (
            workflow_transition_kind='RECOVERY'
            AND generation>1
            AND predecessor_execution_id IS NOT NULL
            AND predecessor_generation=generation-1
            AND recovery_intent_id IS NOT NULL
        )
    ),
    ADD CONSTRAINT authority_bo_execution_node_fk
    FOREIGN KEY(opening_run_id,workflow_node_id)
    REFERENCES authority_book_opening_workflow_node(
        opening_run_id,workflow_node_id
    ) DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT authority_bo_execution_source_checkpoint_fk
    FOREIGN KEY(
        opening_run_id,source_checkpoint_id,
        source_checkpoint_sequence,source_checkpoint_hash
    ) REFERENCES authority_book_opening_semantic_checkpoint(
        opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
    ) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_bo_execution_node_fk_idx
    ON authority_book_opening_execution(opening_run_id,workflow_node_id)
    WHERE workflow_node_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_bo_execution_source_checkpoint_fk_idx
    ON authority_book_opening_execution(
        opening_run_id,source_checkpoint_id,
        source_checkpoint_sequence,source_checkpoint_hash
    ) WHERE source_checkpoint_id IS NOT NULL
    """,
    """
    ALTER TABLE authority_book_opening_semantic_checkpoint
    ADD COLUMN workflow_node_id TEXT,
    ADD CONSTRAINT authority_bo_checkpoint_node_fk
    FOREIGN KEY(opening_run_id,workflow_node_id)
    REFERENCES authority_book_opening_workflow_node(
        opening_run_id,workflow_node_id
    ) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_bo_checkpoint_node_fk_idx
    ON authority_book_opening_semantic_checkpoint(
        opening_run_id,workflow_node_id
    ) WHERE workflow_node_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX authority_bo_checkpoint_node_unique_idx
    ON authority_book_opening_semantic_checkpoint(
        opening_run_id,workflow_node_id
    ) WHERE workflow_node_id IS NOT NULL
      AND evidence_type='BOOK_OPENING_NODE_RECEIPT'
    """,
    """
    CREATE TABLE authority_book_opening_node_receipt (
        node_receipt_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        workflow_node_id TEXT NOT NULL,
        opening_execution_id TEXT NOT NULL,
        execution_generation BIGINT NOT NULL,
        result JSONB NOT NULL,
        result_hash TEXT NOT NULL,
        authoritative_evidence_hash TEXT NOT NULL,
        reviewable_artifact_kind TEXT NOT NULL,
        reviewable_asset_version_ids TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
        checkpoint_id TEXT NOT NULL,
        checkpoint_sequence BIGINT NOT NULL,
        checkpoint_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id,node_receipt_id),
        UNIQUE(workflow_node_id),
        UNIQUE(opening_run_id,workflow_node_id),
        UNIQUE(
            opening_run_id,opening_execution_id,execution_generation
        ),
        UNIQUE(checkpoint_id),
        FOREIGN KEY(opening_run_id,workflow_node_id)
            REFERENCES authority_book_opening_workflow_node(
                opening_run_id,workflow_node_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,opening_execution_id,execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,checkpoint_id,
            checkpoint_sequence,checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint(
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (execution_generation>0),
        CHECK (checkpoint_sequence>0),
        CHECK (jsonb_typeof(result)='object'),
        CHECK (result_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (authoritative_evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (reviewable_artifact_kind IN (
            'BOOK_PLAN',
            'VOLUME_PORTFOLIO',
            'CURRENT_VOLUME_PLAN',
            'INITIAL_ARC_SCOPE',
            'BOOK_PRODUCTION_INPUT_SNAPSHOT'
        ))
    )
    """,
    """
    CREATE INDEX authority_bo_node_receipt_execution_fk_idx
    ON authority_book_opening_node_receipt(
        opening_run_id,opening_execution_id,execution_generation
    )
    """,
    """
    CREATE TABLE authority_book_opening_workflow_transition_receipt (
        workflow_transition_receipt_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL
            REFERENCES authority_book_opening_run(opening_run_id),
        source_node_receipt_id TEXT NOT NULL UNIQUE,
        predecessor_opening_execution_id TEXT NOT NULL,
        predecessor_execution_generation BIGINT NOT NULL,
        successor_opening_execution_id TEXT NOT NULL,
        successor_execution_generation BIGINT NOT NULL,
        successor_workflow_node_id TEXT NOT NULL,
        source_checkpoint_id TEXT NOT NULL,
        source_checkpoint_sequence BIGINT NOT NULL,
        source_checkpoint_hash TEXT NOT NULL,
        transition_kind TEXT NOT NULL,
        transition_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT authority_bo_transition_successor_key UNIQUE(
            opening_run_id,
            successor_opening_execution_id,
            successor_execution_generation
        ),
        FOREIGN KEY(opening_run_id,source_node_receipt_id)
            REFERENCES authority_book_opening_node_receipt(
                opening_run_id,node_receipt_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,predecessor_opening_execution_id,
            predecessor_execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,successor_opening_execution_id,
            successor_execution_generation
        ) REFERENCES authority_book_opening_execution(
            opening_run_id,opening_execution_id,generation
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(opening_run_id,successor_workflow_node_id)
            REFERENCES authority_book_opening_workflow_node(
                opening_run_id,workflow_node_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,source_checkpoint_id,
            source_checkpoint_sequence,source_checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint(
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (predecessor_execution_generation>0),
        CHECK (
            successor_execution_generation=
                predecessor_execution_generation+1
        ),
        CHECK (transition_kind='CONTINUATION'),
        CHECK (source_checkpoint_sequence>0),
        CHECK (source_checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (transition_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_bo_transition_predecessor_fk_idx
    ON authority_book_opening_workflow_transition_receipt(
        opening_run_id,predecessor_opening_execution_id,
        predecessor_execution_generation
    )
    """,
    """
    CREATE INDEX authority_bo_transition_successor_fk_idx
    ON authority_book_opening_workflow_transition_receipt(
        opening_run_id,successor_opening_execution_id,
        successor_execution_generation
    )
    """,
    """
    CREATE INDEX authority_bo_transition_node_fk_idx
    ON authority_book_opening_workflow_transition_receipt(
        opening_run_id,successor_workflow_node_id
    )
    """,
    """
    CREATE INDEX authority_bo_transition_checkpoint_fk_idx
    ON authority_book_opening_workflow_transition_receipt(
        opening_run_id,source_checkpoint_id,
        source_checkpoint_sequence,source_checkpoint_hash
    )
    """,
    """
    CREATE TABLE authority_book_opening_input_snapshot_binding (
        input_snapshot_binding_id TEXT PRIMARY KEY,
        opening_run_id TEXT NOT NULL,
        workflow_node_id TEXT NOT NULL,
        node_receipt_id TEXT NOT NULL UNIQUE,
        checkpoint_id TEXT NOT NULL,
        checkpoint_sequence BIGINT NOT NULL,
        checkpoint_hash TEXT NOT NULL,
        snapshot_id TEXT NOT NULL UNIQUE
            REFERENCES authority_book_production_input_snapshot(snapshot_id),
        snapshot_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(opening_run_id,workflow_node_id),
        FOREIGN KEY(opening_run_id,workflow_node_id)
            REFERENCES authority_book_opening_workflow_node(
                opening_run_id,workflow_node_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(opening_run_id,node_receipt_id)
            REFERENCES authority_book_opening_node_receipt(
                opening_run_id,node_receipt_id
            ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(
            opening_run_id,checkpoint_id,
            checkpoint_sequence,checkpoint_hash
        ) REFERENCES authority_book_opening_semantic_checkpoint(
            opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
        ) DEFERRABLE INITIALLY DEFERRED,
        CHECK (checkpoint_sequence>0),
        CHECK (checkpoint_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_bo_snapshot_binding_checkpoint_fk_idx
    ON authority_book_opening_input_snapshot_binding(
        opening_run_id,checkpoint_id,checkpoint_sequence,checkpoint_hash
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_book_opening_workflow_fact_immutable()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_FACT_IMMUTABLE:%',TG_TABLE_NAME
            USING ERRCODE='check_violation';
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_workflow_node_immutable
    BEFORE UPDATE OR DELETE ON authority_book_opening_workflow_node
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_workflow_fact_immutable()
    """,
    """
    CREATE TRIGGER authority_book_opening_workflow_edge_immutable
    BEFORE UPDATE OR DELETE ON authority_book_opening_workflow_edge
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_workflow_fact_immutable()
    """,
    """
    CREATE TRIGGER authority_book_opening_node_receipt_immutable
    BEFORE UPDATE OR DELETE ON authority_book_opening_node_receipt
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_workflow_fact_immutable()
    """,
    """
    CREATE TRIGGER authority_bo_workflow_transition_receipt_immutable
    BEFORE UPDATE OR DELETE
    ON authority_book_opening_workflow_transition_receipt
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_workflow_fact_immutable()
    """,
    """
    CREATE TRIGGER authority_bo_input_snapshot_binding_immutable
    BEFORE UPDATE OR DELETE ON authority_book_opening_input_snapshot_binding
    FOR EACH ROW
    EXECUTE FUNCTION authority_book_opening_workflow_fact_immutable()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_snapshot_binding(
        target_binding_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        binding RECORD;
    BEGIN
        SELECT
            link.opening_run_id,link.workflow_node_id,link.node_receipt_id,
            link.checkpoint_id,link.checkpoint_sequence,link.checkpoint_hash,
            link.snapshot_id,link.snapshot_hash,node.node_kind,node.ordinal,
            receipt.result,receipt.reviewable_artifact_kind,
            receipt.reviewable_asset_version_ids,
            receipt.checkpoint_id AS receipt_checkpoint_id,
            receipt.checkpoint_sequence AS receipt_checkpoint_sequence,
            receipt.checkpoint_hash AS receipt_checkpoint_hash,
            checkpoint.evidence_type,checkpoint.evidence_id,
            checkpoint.evidence_hash,snapshot.snapshot_hash AS actual_snapshot_hash,
            opening.project_id AS opening_project_id,
            opening.workspace_id AS opening_workspace_id,
            opening.book_id AS opening_book_id,
            snapshot.project_id AS snapshot_project_id,
            snapshot.workspace_id AS snapshot_workspace_id,
            snapshot.book_id AS snapshot_book_id
        INTO binding
        FROM authority_book_opening_input_snapshot_binding AS link
        JOIN authority_book_opening_workflow_node AS node
          ON node.opening_run_id=link.opening_run_id
         AND node.workflow_node_id=link.workflow_node_id
        JOIN authority_book_opening_run AS opening
          ON opening.opening_run_id=link.opening_run_id
        JOIN authority_book_opening_node_receipt AS receipt
          ON receipt.opening_run_id=link.opening_run_id
         AND receipt.node_receipt_id=link.node_receipt_id
         AND receipt.workflow_node_id=link.workflow_node_id
        JOIN authority_book_opening_semantic_checkpoint AS checkpoint
          ON checkpoint.opening_run_id=link.opening_run_id
         AND checkpoint.checkpoint_id=link.checkpoint_id
         AND checkpoint.checkpoint_sequence=link.checkpoint_sequence
         AND checkpoint.checkpoint_hash=link.checkpoint_hash
         AND checkpoint.workflow_node_id=link.workflow_node_id
        JOIN authority_book_production_input_snapshot AS snapshot
          ON snapshot.snapshot_id=link.snapshot_id
        WHERE link.input_snapshot_binding_id=target_binding_id;
        IF NOT FOUND
           OR binding.node_kind<>'INPUT_SNAPSHOT'
           OR binding.ordinal<>5
           OR binding.reviewable_artifact_kind<>
                'BOOK_PRODUCTION_INPUT_SNAPSHOT'
           OR CARDINALITY(binding.reviewable_asset_version_ids)<>0
           OR binding.receipt_checkpoint_id<>binding.checkpoint_id
           OR binding.receipt_checkpoint_sequence<>binding.checkpoint_sequence
           OR binding.receipt_checkpoint_hash<>binding.checkpoint_hash
           OR binding.evidence_type<>'BOOK_OPENING_NODE_RECEIPT'
           OR binding.evidence_id<>binding.node_receipt_id
           OR binding.snapshot_hash<>binding.actual_snapshot_hash
           OR binding.snapshot_project_id<>binding.opening_project_id
           OR binding.snapshot_workspace_id<>binding.opening_workspace_id
           OR binding.snapshot_book_id<>binding.opening_book_id
           OR binding.result->>'snapshot_id'<>binding.snapshot_id
           OR binding.result->>'snapshot_hash'<>binding.snapshot_hash THEN
            RAISE EXCEPTION 'BOOK_OPENING_INPUT_SNAPSHOT_BINDING_INVALID:%',
                target_binding_id
                USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_run_workflow_identity_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.workflow_contract_version='legacy-monolithic-v2' THEN
            IF NEW.workflow_contract_version='legacy-monolithic-v2'
               AND ROW(
                   OLD.current_workflow_node_id,
                   OLD.workflow_graph_revision,
                   OLD.workflow_graph_hash
               ) IS DISTINCT FROM ROW(
                   NEW.current_workflow_node_id,
                   NEW.workflow_graph_revision,
                   NEW.workflow_graph_hash
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_IDENTITY_INVALID:%',
                    NEW.opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.workflow_contract_version<>'book-opening-workflow-v1'
           OR NEW.workflow_contract_version<>'book-opening-workflow-v1'
           OR OLD.workflow_graph_revision IS DISTINCT FROM
                NEW.workflow_graph_revision
           OR OLD.workflow_graph_hash IS DISTINCT FROM NEW.workflow_graph_hash
           OR (
               OLD.current_workflow_node_id IS DISTINCT FROM
                    NEW.current_workflow_node_id
               AND NOT EXISTS (
                   SELECT 1
                   FROM authority_book_opening_workflow_edge AS edge
                   WHERE edge.opening_run_id=NEW.opening_run_id
                     AND edge.predecessor_workflow_node_id=
                         OLD.current_workflow_node_id
                     AND edge.successor_workflow_node_id=
                         NEW.current_workflow_node_id
                     AND edge.edge_kind='REQUIRES'
               )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_IDENTITY_INVALID:%',
                NEW.opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_bo_run_workflow_identity_guard
    BEFORE UPDATE ON authority_book_opening_run
    FOR EACH ROW
    EXECUTE FUNCTION authority_bo_run_workflow_identity_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_run_terminal_immutable_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            IF OLD.lifecycle IN ('COMPLETE','ABORTED') THEN
                RAISE EXCEPTION 'BOOK_OPENING_RUN_TERMINAL_IMMUTABLE:%',
                    OLD.opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
            RETURN OLD;
        END IF;
        -- COMPLETE and ABORTED are final Book Opening history.  Leave only the
        -- audit timestamp mutable; every Authority-owned fact (including any
        -- column added by a future migration) is frozen after terminal entry.
        IF OLD.lifecycle IN ('COMPLETE','ABORTED')
           AND (to_jsonb(OLD) - 'updated_at') IS DISTINCT FROM
               (to_jsonb(NEW) - 'updated_at') THEN
            RAISE EXCEPTION 'BOOK_OPENING_RUN_TERMINAL_IMMUTABLE:%',
                OLD.opening_run_id
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_book_opening_run_terminal_immutable
    BEFORE UPDATE OR DELETE ON authority_book_opening_run
    FOR EACH ROW
    EXECUTE FUNCTION authority_bo_run_terminal_immutable_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_execution_workflow_identity_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        run_contract_version TEXT;
    BEGIN
        IF TG_OP='UPDATE' AND ROW(
            OLD.workflow_node_id,
            OLD.workflow_transition_kind,
            OLD.source_checkpoint_id,
            OLD.source_checkpoint_sequence,
            OLD.source_checkpoint_hash,
            OLD.recovery_intent_id
        ) IS DISTINCT FROM ROW(
            NEW.workflow_node_id,
            NEW.workflow_transition_kind,
            NEW.source_checkpoint_id,
            NEW.source_checkpoint_sequence,
            NEW.source_checkpoint_hash,
            NEW.recovery_intent_id
        ) THEN
            RAISE EXCEPTION
                'BOOK_OPENING_WORKFLOW_EXECUTION_IDENTITY_IMMUTABLE:%',
                NEW.opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        SELECT workflow_contract_version INTO run_contract_version
        FROM authority_book_opening_run
        WHERE opening_run_id=NEW.opening_run_id;
        IF NOT FOUND
           OR (
               NEW.workflow_transition_kind='LEGACY_MONOLITHIC'
               AND run_contract_version<>'legacy-monolithic-v2'
           )
           OR (
               NEW.workflow_transition_kind<>'LEGACY_MONOLITHIC'
               AND run_contract_version<>'book-opening-workflow-v1'
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_INVALID:%',
                NEW.opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_bo_execution_workflow_identity_guard
    BEFORE INSERT OR UPDATE ON authority_book_opening_execution
    FOR EACH ROW
    EXECUTE FUNCTION authority_bo_execution_workflow_identity_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_node_receipt(
        target_node_receipt_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        receipt RECORD;
        asset_count BIGINT;
        distinct_asset_count BIGINT;
        bound_asset_count BIGINT;
        authoritative_asset_count BIGINT;
    BEGIN
        SELECT
            node_receipt.*,
            opening.project_id,opening.book_id AS opening_book_id,
            node.node_kind,
            execution.lifecycle AS execution_lifecycle,
            execution.workflow_node_id AS execution_workflow_node_id,
            checkpoint.opening_execution_id AS checkpoint_execution_id,
            checkpoint.execution_generation AS checkpoint_generation,
            checkpoint.workflow_node_id AS checkpoint_workflow_node_id,
            checkpoint.semantic_work_key AS checkpoint_semantic_work_key,
            checkpoint.owning_authority AS checkpoint_owning_authority,
            checkpoint.evidence_type AS checkpoint_evidence_type,
            checkpoint.evidence_id AS checkpoint_evidence_id,
            checkpoint.evidence_version AS checkpoint_evidence_version,
            checkpoint.evidence_hash AS checkpoint_evidence_hash
        INTO receipt
        FROM authority_book_opening_node_receipt AS node_receipt
        JOIN authority_book_opening_run AS opening
          ON opening.opening_run_id=node_receipt.opening_run_id
        JOIN authority_book_opening_workflow_node AS node
          ON node.opening_run_id=node_receipt.opening_run_id
         AND node.workflow_node_id=node_receipt.workflow_node_id
        JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=node_receipt.opening_run_id
         AND execution.opening_execution_id=
             node_receipt.opening_execution_id
         AND execution.generation=node_receipt.execution_generation
        JOIN authority_book_opening_semantic_checkpoint AS checkpoint
          ON checkpoint.opening_run_id=node_receipt.opening_run_id
         AND checkpoint.checkpoint_id=node_receipt.checkpoint_id
         AND checkpoint.checkpoint_sequence=
             node_receipt.checkpoint_sequence
         AND checkpoint.checkpoint_hash=node_receipt.checkpoint_hash
        WHERE node_receipt.node_receipt_id=target_node_receipt_id;
        IF NOT FOUND
           OR receipt.execution_lifecycle IS DISTINCT FROM 'SUCCEEDED'
           OR receipt.execution_workflow_node_id IS DISTINCT FROM
                receipt.workflow_node_id
           OR receipt.checkpoint_execution_id IS DISTINCT FROM
                receipt.opening_execution_id
           OR receipt.checkpoint_generation IS DISTINCT FROM
                receipt.execution_generation
           OR receipt.checkpoint_workflow_node_id IS DISTINCT FROM
                receipt.workflow_node_id
           OR receipt.checkpoint_semantic_work_key IS DISTINCT FROM
                'book-opening-node:' || receipt.node_kind || ':' ||
                receipt.workflow_node_id
           OR receipt.checkpoint_owning_authority IS DISTINCT FROM
                'BOOK_AUTHORITY'
           OR receipt.checkpoint_evidence_type IS DISTINCT FROM
                'BOOK_OPENING_NODE_RECEIPT'
           OR receipt.checkpoint_evidence_id IS DISTINCT FROM
                receipt.node_receipt_id
           OR receipt.checkpoint_evidence_version IS DISTINCT FROM 1
           OR receipt.authoritative_evidence_hash IS DISTINCT FROM
                receipt.checkpoint_evidence_hash
           OR (
               receipt.node_kind='BOOK_PLAN'
               AND (
                   receipt.reviewable_artifact_kind<>'BOOK_PLAN'
                   OR CARDINALITY(receipt.reviewable_asset_version_ids)<>1
               )
           )
           OR (
               receipt.node_kind='VOLUME_PORTFOLIO'
               AND (
                   receipt.reviewable_artifact_kind<>'VOLUME_PORTFOLIO'
                   OR CARDINALITY(receipt.reviewable_asset_version_ids)<1
               )
           )
           OR (
               receipt.node_kind='CURRENT_VOLUME'
               AND (
                   receipt.reviewable_artifact_kind<>'CURRENT_VOLUME_PLAN'
                   OR CARDINALITY(receipt.reviewable_asset_version_ids)<>1
               )
           )
           OR (
               receipt.node_kind='INITIAL_ARC_SCOPE'
               AND (
                   receipt.reviewable_artifact_kind<>'INITIAL_ARC_SCOPE'
                   OR CARDINALITY(receipt.reviewable_asset_version_ids)<1
               )
           )
           OR (
               receipt.node_kind='INPUT_SNAPSHOT'
               AND (
                   receipt.reviewable_artifact_kind<>
                       'BOOK_PRODUCTION_INPUT_SNAPSHOT'
                   OR CARDINALITY(receipt.reviewable_asset_version_ids)<>0
               )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                target_node_receipt_id
                USING ERRCODE='check_violation';
        END IF;

        SELECT
            COUNT(*),
            COUNT(DISTINCT asset_id.asset_version_id),
            COUNT(version.asset_version_id) FILTER (
                WHERE asset.project_id=receipt.project_id
            )
        INTO asset_count,distinct_asset_count,bound_asset_count
        FROM UNNEST(receipt.reviewable_asset_version_ids)
             AS asset_id(asset_version_id)
        LEFT JOIN authority_asset_version AS version
          ON version.asset_version_id=asset_id.asset_version_id
        LEFT JOIN authority_asset AS asset ON asset.asset_id=version.asset_id;
        IF asset_count<>distinct_asset_count
           OR asset_count<>bound_asset_count THEN
            RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                target_node_receipt_id
                USING ERRCODE='check_violation';
        END IF;

        IF receipt.node_kind='BOOK_PLAN' THEN
            SELECT COUNT(*) INTO authoritative_asset_count
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN story_plan_binding AS binding
              ON binding.asset_version_id=version.asset_version_id
             AND binding.binding_id=receipt.result->>'binding_id'
             AND binding.project_id=receipt.project_id
             AND binding.book_id=receipt.opening_book_id
             AND binding.contract_type='BOOK'
             AND binding.logical_key='book:main'
             AND binding.freshness='CURRENT'
            JOIN active_story_plan_version AS active
              ON active.project_id=binding.project_id
             AND active.book_id=binding.book_id
             AND active.logical_key=binding.logical_key
             AND active.binding_id=binding.binding_id
             AND active.asset_version_id=binding.asset_version_id
            JOIN authority_story_narrative_search AS search
              ON search.search_id=receipt.result->>'search_id'
             AND search.project_id=binding.project_id
             AND search.book_id=binding.book_id
             AND search.status='ACTIVATED'
             AND search.selected_candidate_asset_version_id=
                 binding.asset_version_id
            WHERE version.asset_version_id=
                    receipt.result->>'asset_version_id'
              AND receipt.reviewable_asset_version_ids[1]=
                    version.asset_version_id
              AND version.content_hash=receipt.result->>'content_hash'
              AND asset.project_id=receipt.project_id
              AND version.lifecycle='ACTIVE'
              AND version.eligibility='ELIGIBLE'
              AND version.governance='CLEAR';
            IF authoritative_asset_count<>1 THEN
                RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                    target_node_receipt_id USING ERRCODE='check_violation';
            END IF;
        ELSIF receipt.node_kind IN ('VOLUME_PORTFOLIO','INITIAL_ARC_SCOPE') THEN
            WITH members AS (
                SELECT value AS member
                FROM jsonb_array_elements(
                    CASE receipt.node_kind
                    WHEN 'VOLUME_PORTFOLIO' THEN
                        COALESCE(receipt.result->'volume_plan_versions','[]'::jsonb)
                    ELSE COALESCE(receipt.result->'arc_plan_versions','[]'::jsonb)
                    END
                )
            )
            SELECT COUNT(*) INTO authoritative_asset_count
            FROM members
            JOIN authority_asset_version AS version
              ON version.asset_version_id=members.member->>'asset_version_id'
             AND version.content_hash=members.member->>'content_hash'
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN story_plan_binding AS binding
              ON binding.asset_version_id=version.asset_version_id
             AND binding.binding_id=members.member->>'binding_id'
             AND binding.project_id=receipt.project_id
             AND binding.book_id=receipt.opening_book_id
             AND binding.contract_type=CASE receipt.node_kind
                 WHEN 'VOLUME_PORTFOLIO' THEN 'VOLUME' ELSE 'ARC' END
             AND binding.logical_key=members.member->>'logical_key'
             AND binding.freshness='CURRENT'
            JOIN active_story_plan_version AS active
              ON active.project_id=binding.project_id
             AND active.book_id=binding.book_id
             AND active.logical_key=binding.logical_key
             AND active.binding_id=binding.binding_id
             AND active.asset_version_id=binding.asset_version_id
            JOIN authority_story_narrative_search AS search
              ON search.search_id=members.member->>'search_id'
             AND search.project_id=binding.project_id
             AND search.book_id=binding.book_id
             AND search.status='ACTIVATED'
             AND search.selected_candidate_asset_version_id=
                 binding.asset_version_id
            WHERE asset.project_id=receipt.project_id
              AND version.lifecycle='ACTIVE'
              AND version.eligibility='ELIGIBLE'
              AND version.governance='CLEAR'
              AND version.asset_version_id=
                  ANY(receipt.reviewable_asset_version_ids);
            IF authoritative_asset_count<>
                 CARDINALITY(receipt.reviewable_asset_version_ids)
               OR authoritative_asset_count<>(
                  CASE
                  WHEN receipt.node_kind='VOLUME_PORTFOLIO' THEN
                    jsonb_array_length(receipt.result->'volume_plan_versions')
                  ELSE jsonb_array_length(receipt.result->'arc_plan_versions')
                  END
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                    target_node_receipt_id USING ERRCODE='check_violation';
            END IF;
        ELSIF receipt.node_kind='CURRENT_VOLUME' THEN
            SELECT COUNT(*) INTO authoritative_asset_count
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            JOIN story_plan_binding AS binding
              ON binding.asset_version_id=version.asset_version_id
             AND binding.project_id=receipt.project_id
             AND binding.book_id=receipt.opening_book_id
             AND binding.contract_type='VOLUME'
             AND binding.freshness='CURRENT'
            JOIN active_story_plan_version AS active
              ON active.project_id=binding.project_id
             AND active.book_id=binding.book_id
             AND active.logical_key=binding.logical_key
             AND active.binding_id=binding.binding_id
             AND active.asset_version_id=binding.asset_version_id
            WHERE version.asset_version_id=
                    receipt.result->>'current_volume_plan_version_id'
              AND receipt.reviewable_asset_version_ids[1]=
                    version.asset_version_id
              AND version.content_hash=
                    receipt.result->>'current_volume_content_hash'
              AND asset.project_id=receipt.project_id
              AND version.lifecycle='ACTIVE'
              AND version.eligibility='ELIGIBLE'
              AND version.governance='CLEAR';
            IF authoritative_asset_count<>1 THEN
                RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                    target_node_receipt_id USING ERRCODE='check_violation';
            END IF;
        ELSIF receipt.node_kind='INPUT_SNAPSHOT' AND NOT EXISTS (
            SELECT 1
            FROM authority_book_opening_input_snapshot_binding AS link
            WHERE link.opening_run_id=receipt.opening_run_id
              AND link.workflow_node_id=receipt.workflow_node_id
              AND link.node_receipt_id=receipt.node_receipt_id
              AND link.checkpoint_id=receipt.checkpoint_id
              AND link.checkpoint_sequence=receipt.checkpoint_sequence
              AND link.checkpoint_hash=receipt.checkpoint_hash
              AND link.snapshot_id=receipt.result->>'snapshot_id'
              AND link.snapshot_hash=receipt.result->>'snapshot_hash'
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_NODE_RECEIPT_INVALID:%',
                target_node_receipt_id USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_node_receipt_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM authority_assert_book_opening_node_receipt(
            CASE WHEN TG_OP='DELETE'
                 THEN OLD.node_receipt_id ELSE NEW.node_receipt_id END
        );
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_node_receipt_relationship_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_node_receipt
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_node_receipt_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_workflow_transition(
        target_transition_receipt_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        transition_binding RECORD;
    BEGIN
        SELECT
            transition_receipt.*,
            source_receipt.workflow_node_id AS source_workflow_node_id,
            source_receipt.opening_execution_id AS receipt_execution_id,
            source_receipt.execution_generation AS receipt_generation,
            source_receipt.checkpoint_id AS receipt_checkpoint_id,
            source_receipt.checkpoint_sequence AS receipt_checkpoint_sequence,
            source_receipt.checkpoint_hash AS receipt_checkpoint_hash,
            predecessor.lifecycle AS predecessor_lifecycle,
            predecessor.workflow_node_id AS predecessor_workflow_node_id,
            predecessor.frozen_request_digest AS predecessor_request_digest,
            successor.predecessor_execution_id AS successor_predecessor_id,
            successor.predecessor_generation AS successor_predecessor_generation,
            successor.recovery_intent_id AS successor_recovery_intent_id,
            successor.workflow_node_id AS bound_successor_workflow_node_id,
            successor.workflow_transition_kind AS successor_transition_kind,
            successor.source_checkpoint_id AS successor_checkpoint_id,
            successor.source_checkpoint_sequence AS successor_checkpoint_sequence,
            successor.source_checkpoint_hash AS successor_checkpoint_hash,
            successor.frozen_request_digest AS successor_request_digest,
            predecessor_node.ordinal AS predecessor_ordinal,
            successor_node.ordinal AS successor_ordinal,
            edge.edge_kind
        INTO transition_binding
        FROM authority_book_opening_workflow_transition_receipt
             AS transition_receipt
        JOIN authority_book_opening_node_receipt AS source_receipt
          ON source_receipt.opening_run_id=transition_receipt.opening_run_id
         AND source_receipt.node_receipt_id=
             transition_receipt.source_node_receipt_id
        JOIN authority_book_opening_execution AS predecessor
          ON predecessor.opening_run_id=transition_receipt.opening_run_id
         AND predecessor.opening_execution_id=
             transition_receipt.predecessor_opening_execution_id
         AND predecessor.generation=
             transition_receipt.predecessor_execution_generation
        JOIN authority_book_opening_execution AS successor
          ON successor.opening_run_id=transition_receipt.opening_run_id
         AND successor.opening_execution_id=
             transition_receipt.successor_opening_execution_id
         AND successor.generation=
             transition_receipt.successor_execution_generation
        JOIN authority_book_opening_workflow_node AS predecessor_node
          ON predecessor_node.opening_run_id=transition_receipt.opening_run_id
         AND predecessor_node.workflow_node_id=source_receipt.workflow_node_id
        JOIN authority_book_opening_workflow_node AS successor_node
          ON successor_node.opening_run_id=transition_receipt.opening_run_id
         AND successor_node.workflow_node_id=
             transition_receipt.successor_workflow_node_id
        LEFT JOIN authority_book_opening_workflow_edge AS edge
          ON edge.opening_run_id=transition_receipt.opening_run_id
         AND edge.predecessor_workflow_node_id=
             predecessor_node.workflow_node_id
         AND edge.successor_workflow_node_id=successor_node.workflow_node_id
        WHERE transition_receipt.workflow_transition_receipt_id=
              target_transition_receipt_id;
        IF NOT FOUND
           OR transition_binding.predecessor_lifecycle IS DISTINCT FROM 'SUCCEEDED'
           OR transition_binding.receipt_execution_id IS DISTINCT FROM
                transition_binding.predecessor_opening_execution_id
           OR transition_binding.receipt_generation IS DISTINCT FROM
                transition_binding.predecessor_execution_generation
           OR transition_binding.predecessor_workflow_node_id IS DISTINCT FROM
                transition_binding.source_workflow_node_id
           OR transition_binding.receipt_checkpoint_id IS DISTINCT FROM
                transition_binding.source_checkpoint_id
           OR transition_binding.receipt_checkpoint_sequence IS DISTINCT FROM
                transition_binding.source_checkpoint_sequence
           OR transition_binding.receipt_checkpoint_hash IS DISTINCT FROM
                transition_binding.source_checkpoint_hash
           OR transition_binding.successor_predecessor_id IS DISTINCT FROM
                transition_binding.predecessor_opening_execution_id
           OR transition_binding.successor_predecessor_generation IS DISTINCT
                FROM transition_binding.predecessor_execution_generation
           OR transition_binding.successor_recovery_intent_id IS NOT NULL
           OR transition_binding.bound_successor_workflow_node_id IS DISTINCT
                FROM transition_binding.successor_workflow_node_id
           OR transition_binding.successor_transition_kind IS DISTINCT FROM
                'CONTINUATION'
           OR transition_binding.successor_checkpoint_id IS DISTINCT FROM
                transition_binding.source_checkpoint_id
           OR transition_binding.successor_checkpoint_sequence IS DISTINCT
                FROM transition_binding.source_checkpoint_sequence
           OR transition_binding.successor_checkpoint_hash IS DISTINCT FROM
                transition_binding.source_checkpoint_hash
           OR transition_binding.successor_request_digest IS DISTINCT FROM
                transition_binding.predecessor_request_digest
           OR transition_binding.successor_ordinal IS DISTINCT FROM
                transition_binding.predecessor_ordinal+1
           OR transition_binding.edge_kind IS DISTINCT FROM 'REQUIRES' THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_TRANSITION_INVALID:%',
                target_transition_receipt_id
                USING ERRCODE='check_violation';
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_workflow_transition_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM authority_assert_book_opening_workflow_transition(
            CASE WHEN TG_OP='DELETE'
                 THEN OLD.workflow_transition_receipt_id
                 ELSE NEW.workflow_transition_receipt_id END
        );
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_workflow_transition_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_workflow_transition_receipt
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_transition_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_workflow_graph(
        target_opening_run_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        opening RECORD;
        graph RECORD;
        current_binding RECORD;
        receipt_count BIGINT;
        checkpoint_count BIGINT;
        snapshot_binding_count BIGINT;
        head_checkpoint RECORD;
        fact RECORD;
    BEGIN
        SELECT * INTO opening
        FROM authority_book_opening_run
        WHERE opening_run_id=target_opening_run_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;

        IF opening.workflow_contract_version='legacy-monolithic-v2' THEN
            IF opening.current_workflow_node_id IS NOT NULL
               OR opening.workflow_graph_revision<>0
               OR opening.workflow_graph_hash<>''
               OR EXISTS (
                   SELECT 1 FROM authority_book_opening_workflow_node
                   WHERE opening_run_id=target_opening_run_id
               )
               OR EXISTS (
                   SELECT 1 FROM authority_book_opening_workflow_edge
                   WHERE opening_run_id=target_opening_run_id
               )
               OR EXISTS (
                   SELECT 1 FROM authority_book_opening_execution
                   WHERE opening_run_id=target_opening_run_id
                     AND (
                         workflow_node_id IS NOT NULL
                         OR workflow_transition_kind<>'LEGACY_MONOLITHIC'
                     )
               )
               OR EXISTS (
                   SELECT 1
                   FROM authority_book_opening_semantic_checkpoint
                   WHERE opening_run_id=target_opening_run_id
                     AND workflow_node_id IS NOT NULL
               )
               OR EXISTS (
                   SELECT 1 FROM authority_book_opening_node_receipt
                   WHERE opening_run_id=target_opening_run_id
               )
               OR EXISTS (
                   SELECT 1
                   FROM authority_book_opening_workflow_transition_receipt
                   WHERE opening_run_id=target_opening_run_id
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                    target_opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
            RETURN;
        END IF;

        IF opening.workflow_contract_version<>'book-opening-workflow-v1'
           OR opening.workflow_graph_revision<>1
           OR opening.workflow_graph_hash !~ '^sha256:[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        SELECT
            COUNT(*) AS node_count,
            COUNT(*) FILTER (WHERE node_kind='BOOK_PLAN') AS book_plan_count,
            COUNT(*) FILTER (
                WHERE node_kind='VOLUME_PORTFOLIO'
            ) AS volume_portfolio_count,
            COUNT(*) FILTER (
                WHERE node_kind='CURRENT_VOLUME'
            ) AS current_volume_count,
            COUNT(*) FILTER (
                WHERE node_kind='INITIAL_ARC_SCOPE'
            ) AS initial_arc_scope_count,
            COUNT(*) FILTER (
                WHERE node_kind='INPUT_SNAPSHOT'
            ) AS input_snapshot_count,
            COUNT(*) FILTER (
                WHERE graph_revision=opening.workflow_graph_revision
            ) AS revision_count
        INTO graph
        FROM authority_book_opening_workflow_node
        WHERE opening_run_id=target_opening_run_id;
        IF graph.node_count<>5
           OR graph.book_plan_count<>1
           OR graph.volume_portfolio_count<>1
           OR graph.current_volume_count<>1
           OR graph.initial_arc_scope_count<>1
           OR graph.input_snapshot_count<>1
           OR graph.revision_count<>5 THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        SELECT
            COUNT(*) AS edge_count,
            COUNT(*) FILTER (
                WHERE predecessor.ordinal=1 AND successor.ordinal=2
            ) AS edge_1_2,
            COUNT(*) FILTER (
                WHERE predecessor.ordinal=2 AND successor.ordinal=3
            ) AS edge_2_3,
            COUNT(*) FILTER (
                WHERE predecessor.ordinal=3 AND successor.ordinal=4
            ) AS edge_3_4,
            COUNT(*) FILTER (
                WHERE predecessor.ordinal=4 AND successor.ordinal=5
            ) AS edge_4_5
        INTO graph
        FROM authority_book_opening_workflow_edge AS edge
        JOIN authority_book_opening_workflow_node AS predecessor
          ON predecessor.opening_run_id=edge.opening_run_id
         AND predecessor.workflow_node_id=
             edge.predecessor_workflow_node_id
        JOIN authority_book_opening_workflow_node AS successor
          ON successor.opening_run_id=edge.opening_run_id
         AND successor.workflow_node_id=edge.successor_workflow_node_id
        WHERE edge.opening_run_id=target_opening_run_id;
        IF graph.edge_count<>4
           OR graph.edge_1_2<>1
           OR graph.edge_2_3<>1
           OR graph.edge_3_4<>1
           OR graph.edge_4_5<>1 THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        SELECT
            node.ordinal,
            node.node_kind,
            execution.opening_execution_id,
            execution.generation,
            execution.lifecycle AS execution_lifecycle,
            execution.workflow_node_id AS execution_workflow_node_id,
            execution.workflow_transition_kind
        INTO current_binding
        FROM authority_book_opening_workflow_node AS node
        JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=node.opening_run_id
         AND execution.opening_execution_id=opening.current_execution_id
         AND execution.generation=opening.current_execution_generation
        WHERE node.opening_run_id=target_opening_run_id
          AND node.workflow_node_id=opening.current_workflow_node_id;
        IF NOT FOUND
           OR current_binding.execution_workflow_node_id IS DISTINCT FROM
                opening.current_workflow_node_id
           OR current_binding.workflow_transition_kind='LEGACY_MONOLITHIC' THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        SELECT COUNT(*) INTO receipt_count
        FROM authority_book_opening_node_receipt
        WHERE opening_run_id=target_opening_run_id;
        SELECT COUNT(*) INTO checkpoint_count
        FROM authority_book_opening_semantic_checkpoint
        WHERE opening_run_id=target_opening_run_id;
        IF checkpoint_count<receipt_count
           OR receipt_count<0
           OR receipt_count>5
           OR EXISTS (
               SELECT 1
               FROM authority_book_opening_workflow_node AS node
               WHERE node.opening_run_id=target_opening_run_id
                 AND (
                     (node.ordinal<=receipt_count AND NOT EXISTS (
                         SELECT 1
                         FROM authority_book_opening_node_receipt AS receipt
                         WHERE receipt.opening_run_id=node.opening_run_id
                           AND receipt.workflow_node_id=node.workflow_node_id
                     ))
                     OR
                     (node.ordinal>receipt_count AND EXISTS (
                         SELECT 1
                         FROM authority_book_opening_node_receipt AS receipt
                         WHERE receipt.opening_run_id=node.opening_run_id
                           AND receipt.workflow_node_id=node.workflow_node_id
                     ))
                 )
           )
           OR EXISTS (
               SELECT 1
               FROM authority_book_opening_semantic_checkpoint AS checkpoint
               LEFT JOIN authority_book_opening_execution AS execution
                 ON execution.opening_run_id=checkpoint.opening_run_id
                AND execution.opening_execution_id=
                    checkpoint.opening_execution_id
                AND execution.generation=checkpoint.execution_generation
               LEFT JOIN authority_book_opening_workflow_node AS node
                 ON node.opening_run_id=checkpoint.opening_run_id
                AND node.workflow_node_id=checkpoint.workflow_node_id
               LEFT JOIN authority_book_opening_node_receipt AS receipt
                 ON receipt.opening_run_id=checkpoint.opening_run_id
                AND receipt.workflow_node_id=checkpoint.workflow_node_id
               WHERE checkpoint.opening_run_id=target_opening_run_id
                 AND (
                     checkpoint.workflow_node_id IS NULL
                     OR execution.opening_execution_id IS NULL
                     OR execution.workflow_node_id IS DISTINCT FROM
                        checkpoint.workflow_node_id
                     OR node.workflow_node_id IS NULL
                     OR node.ordinal>receipt_count+1
                     OR (
                         receipt.node_receipt_id IS NOT NULL
                         AND checkpoint.checkpoint_sequence>
                             receipt.checkpoint_sequence
                     )
                     OR (
                         node.ordinal<=receipt_count
                         AND receipt.node_receipt_id IS NULL
                     )
                 )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        FOR fact IN
            SELECT node_receipt_id
            FROM authority_book_opening_node_receipt
            WHERE opening_run_id=target_opening_run_id
        LOOP
            PERFORM authority_assert_book_opening_node_receipt(
                fact.node_receipt_id
            );
        END LOOP;
        FOR fact IN
            SELECT workflow_transition_receipt_id
            FROM authority_book_opening_workflow_transition_receipt
            WHERE opening_run_id=target_opening_run_id
        LOOP
            PERFORM authority_assert_book_opening_workflow_transition(
                fact.workflow_transition_receipt_id
            );
        END LOOP;
        FOR fact IN
            SELECT input_snapshot_binding_id
            FROM authority_book_opening_input_snapshot_binding
            WHERE opening_run_id=target_opening_run_id
        LOOP
            PERFORM authority_assert_book_opening_snapshot_binding(
                fact.input_snapshot_binding_id
            );
        END LOOP;

        IF EXISTS (
            SELECT 1
            FROM authority_book_opening_execution AS execution
            LEFT JOIN authority_book_opening_node_receipt AS receipt
              ON receipt.opening_run_id=execution.opening_run_id
             AND receipt.opening_execution_id=execution.opening_execution_id
             AND receipt.execution_generation=execution.generation
            WHERE execution.opening_run_id=target_opening_run_id
              AND (
                  execution.workflow_node_id IS NULL
                  OR execution.workflow_transition_kind='LEGACY_MONOLITHIC'
                  OR (
                      execution.lifecycle='SUCCEEDED'
                      AND receipt.node_receipt_id IS NULL
                  )
                  OR (
                      execution.lifecycle<>'SUCCEEDED'
                      AND receipt.node_receipt_id IS NOT NULL
                  )
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_book_opening_execution AS execution
            LEFT JOIN authority_book_opening_workflow_transition_receipt
                      AS transition_receipt
              ON transition_receipt.opening_run_id=execution.opening_run_id
             AND transition_receipt.successor_opening_execution_id=
                 execution.opening_execution_id
             AND transition_receipt.successor_execution_generation=
                 execution.generation
            WHERE execution.opening_run_id=target_opening_run_id
              AND (
                  (execution.workflow_transition_kind='CONTINUATION'
                   AND transition_receipt.workflow_transition_receipt_id IS NULL)
                  OR
                  (execution.workflow_transition_kind<>'CONTINUATION'
                   AND transition_receipt.workflow_transition_receipt_id
                       IS NOT NULL)
              )
        ) OR EXISTS (
            SELECT 1
            FROM authority_book_opening_node_receipt AS receipt
            JOIN authority_book_opening_workflow_node AS node
              ON node.opening_run_id=receipt.opening_run_id
             AND node.workflow_node_id=receipt.workflow_node_id
            LEFT JOIN authority_book_opening_workflow_transition_receipt
                      AS transition_receipt
              ON transition_receipt.opening_run_id=receipt.opening_run_id
             AND transition_receipt.source_node_receipt_id=
                 receipt.node_receipt_id
            WHERE receipt.opening_run_id=target_opening_run_id
              AND (
                  (node.ordinal<5
                   AND transition_receipt.workflow_transition_receipt_id IS NULL)
                  OR
                  (node.ordinal=5
                   AND transition_receipt.workflow_transition_receipt_id
                       IS NOT NULL)
              )
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                target_opening_run_id
                USING ERRCODE='check_violation';
        END IF;

        IF receipt_count<5 THEN
            IF current_binding.ordinal IS DISTINCT FROM receipt_count+1
               OR current_binding.execution_lifecycle='SUCCEEDED'
               OR opening.lifecycle='COMPLETE' THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                    target_opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSE
            SELECT COUNT(*) INTO snapshot_binding_count
            FROM authority_book_opening_input_snapshot_binding AS link
            JOIN authority_book_opening_node_receipt AS receipt
              ON receipt.opening_run_id=link.opening_run_id
             AND receipt.node_receipt_id=link.node_receipt_id
            WHERE link.opening_run_id=target_opening_run_id
              AND link.workflow_node_id=current_binding.execution_workflow_node_id
              AND opening.result->>'input_snapshot_id'=link.snapshot_id;
            IF current_binding.ordinal<>5
               OR current_binding.execution_lifecycle<>'SUCCEEDED'
               OR opening.lifecycle<>'COMPLETE'
               OR snapshot_binding_count<>1 THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                    target_opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;

        IF checkpoint_count=0 THEN
            IF opening.current_checkpoint_id IS NOT NULL
               OR opening.current_checkpoint_sequence<>0
               OR opening.current_checkpoint_hash<>'' THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                    target_opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSE
            SELECT checkpoint.* INTO head_checkpoint
            FROM authority_book_opening_semantic_checkpoint AS checkpoint
            WHERE checkpoint.opening_run_id=target_opening_run_id
            ORDER BY checkpoint.checkpoint_sequence DESC
            LIMIT 1;
            IF head_checkpoint.checkpoint_id IS DISTINCT FROM
                    opening.current_checkpoint_id
               OR head_checkpoint.checkpoint_sequence IS DISTINCT FROM
                    opening.current_checkpoint_sequence
               OR head_checkpoint.checkpoint_hash IS DISTINCT FROM
                    opening.current_checkpoint_hash THEN
                RAISE EXCEPTION 'BOOK_OPENING_WORKFLOW_GRAPH_INVALID:%',
                    target_opening_run_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION authority_bo_workflow_graph_guard()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE
        target_opening_run_id TEXT;
    BEGIN
        IF TG_OP='DELETE' THEN
            target_opening_run_id=OLD.opening_run_id;
        ELSE
            target_opening_run_id=NEW.opening_run_id;
        END IF;
        PERFORM authority_assert_book_opening_workflow_graph(
            target_opening_run_id
        );
        RETURN NULL;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_run_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE ON authority_book_opening_run
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_node_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE ON authority_book_opening_workflow_node
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_edge_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE ON authority_book_opening_workflow_edge
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_execution_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE ON authority_book_opening_execution
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_checkpoint_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_semantic_checkpoint
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_receipt_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE ON authority_book_opening_node_receipt
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_transition_workflow_graph_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_workflow_transition_receipt
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_bo_snapshot_binding_graph_guard
    AFTER INSERT OR UPDATE OR DELETE
    ON authority_book_opening_input_snapshot_binding
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authority_bo_workflow_graph_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_assert_book_opening_execution_binding(
        target_opening_execution_id TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$
    DECLARE
        binding RECORD;
        exact_claim BOOLEAN;
    BEGIN
        SELECT
            execution.opening_execution_id,
            execution.opening_run_id,
            execution.generation AS execution_generation,
            execution.lifecycle AS execution_lifecycle,
            execution.recovery_intent_id,
            execution.workflow_transition_kind,
            execution.source_checkpoint_id,
            execution.source_checkpoint_sequence,
            execution.source_checkpoint_hash,
            execution.frozen_request_digest AS execution_request_digest,
            execution.input_snapshot_hash,
            execution.runtime_job_id,
            execution.current_attempt_id AS execution_attempt_id,
            execution.current_lease_id AS execution_lease_id,
            execution.current_worker_id AS execution_worker_id,
            execution.current_fencing_token AS execution_fencing_token,
            predecessor.lifecycle AS predecessor_lifecycle,
            opening.project_id AS opening_project_id,
            opening.workflow_contract_version AS
                opening_workflow_contract_version,
            opening.execution_contract_version AS
                opening_execution_contract_version,
            opening.frozen_request_digest AS opening_request_digest,
            opening.current_execution_id AS opening_current_execution_id,
            opening.current_execution_generation AS opening_current_generation,
            EXISTS (
                SELECT 1
                FROM authority_book_opening_recovery_receipt AS receipt
                WHERE receipt.receipt_kind='RECOVERY_ADMISSION'
                  AND receipt.opening_run_id=execution.opening_run_id
                  AND receipt.recovery_intent_id=execution.recovery_intent_id
                  AND receipt.successor_execution_id=
                      execution.opening_execution_id
                  AND receipt.successor_generation=execution.generation
            ) AS exact_recovery_admission,
            EXISTS (
                SELECT 1
                FROM authority_book_opening_workflow_transition_receipt
                     AS transition_receipt
                WHERE transition_receipt.opening_run_id=
                      execution.opening_run_id
                  AND transition_receipt.predecessor_opening_execution_id=
                      execution.predecessor_execution_id
                  AND transition_receipt.predecessor_execution_generation=
                      execution.predecessor_generation
                  AND transition_receipt.successor_opening_execution_id=
                      execution.opening_execution_id
                  AND transition_receipt.successor_execution_generation=
                      execution.generation
                  AND transition_receipt.successor_workflow_node_id=
                      execution.workflow_node_id
                  AND transition_receipt.source_checkpoint_id=
                      execution.source_checkpoint_id
                  AND transition_receipt.source_checkpoint_sequence=
                      execution.source_checkpoint_sequence
                  AND transition_receipt.source_checkpoint_hash=
                      execution.source_checkpoint_hash
                  AND transition_receipt.transition_kind='CONTINUATION'
            ) AS exact_workflow_continuation,
            job.project_id AS job_project_id,
            job.job_kind,
            job.runtime_group,
            job.subject_kind,
            job.subject_id,
            job.input_hash AS job_input_hash,
            job.lease_loss_policy,
            job.status AS job_status,
            job.claimed_by AS job_claimed_by,
            job.current_attempt_id AS job_attempt_id,
            job.current_fencing_token AS job_fencing_token,
            attempt.attempt_id AS exact_attempt_id,
            attempt.status AS attempt_status,
            lease.lease_id AS exact_lease_id,
            lease.status AS lease_status
        INTO binding
        FROM authority_book_opening_execution AS execution
        JOIN authority_book_opening_run AS opening
          ON opening.opening_run_id=execution.opening_run_id
        LEFT JOIN authority_book_opening_execution AS predecessor
          ON predecessor.opening_run_id=execution.opening_run_id
         AND predecessor.opening_execution_id=
             execution.predecessor_execution_id
         AND predecessor.generation=execution.predecessor_generation
        LEFT JOIN authority_runtime_job AS job
          ON job.runtime_job_id=execution.runtime_job_id
        LEFT JOIN authority_runtime_job_attempt AS attempt
          ON attempt.runtime_job_id=execution.runtime_job_id
         AND attempt.attempt_id=execution.current_attempt_id
         AND attempt.lease_id=execution.current_lease_id
         AND attempt.worker_id=execution.current_worker_id
         AND attempt.fencing_token=execution.current_fencing_token
        LEFT JOIN authority_runtime_job_lease AS lease
          ON lease.runtime_job_id=execution.runtime_job_id
         AND lease.attempt_id=execution.current_attempt_id
         AND lease.lease_id=execution.current_lease_id
         AND lease.worker_id=execution.current_worker_id
         AND lease.fencing_token=execution.current_fencing_token
        WHERE execution.opening_execution_id=target_opening_execution_id;
        IF NOT FOUND THEN
            RETURN;
        END IF;
        IF binding.execution_request_digest IS DISTINCT FROM
           binding.opening_request_digest THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.execution_generation>1
           AND (
               (
                   binding.workflow_transition_kind IN (
                       'LEGACY_MONOLITHIC','RECOVERY'
                   )
                   AND (
                       binding.recovery_intent_id IS NULL
                       OR NOT binding.exact_recovery_admission
                   )
               )
               OR (
                   binding.workflow_transition_kind='CONTINUATION'
                   AND (
                       binding.recovery_intent_id IS NOT NULL
                       OR NOT binding.exact_workflow_continuation
                       OR binding.predecessor_lifecycle IS DISTINCT FROM
                          'SUCCEEDED'
                   )
               )
               OR binding.workflow_transition_kind NOT IN (
                   'LEGACY_MONOLITHIC','CONTINUATION','RECOVERY'
               )
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.execution_lifecycle IN ('SCHEDULED','BOUND','RUNNING')
           AND (
               binding.opening_current_execution_id IS DISTINCT FROM
                  binding.opening_execution_id
               OR binding.opening_current_generation IS DISTINCT FROM
                  binding.execution_generation
           ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;
        IF binding.runtime_job_id IS NULL THEN
            IF binding.execution_generation IS DISTINCT FROM 1
               OR binding.execution_lifecycle NOT IN ('FAILED','ABORTED')
               OR binding.execution_attempt_id IS NOT NULL
               OR binding.execution_lease_id IS NOT NULL
               OR binding.execution_worker_id IS NOT NULL
               OR binding.execution_fencing_token IS NOT NULL THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
            RETURN;
        END IF;
        IF binding.job_project_id IS DISTINCT FROM binding.opening_project_id
           OR NOT (
               (
                   binding.opening_workflow_contract_version=
                       'legacy-monolithic-v2'
                   AND binding.opening_execution_contract_version=
                       'book-opening-execution-v2'
                   AND binding.job_kind='BOOK_OPENING_EXECUTE'
                   AND binding.runtime_group='book_opening'
               ) OR (
                   binding.opening_workflow_contract_version=
                       'book-opening-workflow-v1'
                   AND binding.opening_execution_contract_version=
                       'book-opening-execution-v3'
                   AND binding.job_kind=
                       'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                   AND binding.runtime_group='book_opening_workflow_v1'
               )
           )
           OR binding.subject_kind IS DISTINCT FROM 'BOOK_OPENING_RUN'
           OR binding.subject_id IS DISTINCT FROM binding.opening_run_id
           OR binding.job_input_hash IS DISTINCT FROM binding.input_snapshot_hash
           OR binding.lease_loss_policy IS DISTINCT FROM
              'AUTHORITY_CONVERGENCE_REQUIRED' THEN
            RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                target_opening_execution_id
                USING ERRCODE='check_violation';
        END IF;

        PERFORM authority_assert_runtime_job_current_claim(
            binding.runtime_job_id
        );
        exact_claim = (
            binding.execution_attempt_id IS NOT NULL
            AND binding.exact_attempt_id IS NOT NULL
            AND binding.exact_lease_id IS NOT NULL
            AND binding.job_attempt_id IS NOT DISTINCT FROM
                binding.execution_attempt_id
            AND binding.job_fencing_token IS NOT DISTINCT FROM
                binding.execution_fencing_token
        );

        IF binding.execution_lifecycle='SCHEDULED' THEN
            IF binding.execution_attempt_id IS NOT NULL
               OR binding.job_status IS DISTINCT FROM 'READY'
               OR binding.job_attempt_id IS NOT NULL
               OR binding.job_fencing_token<>0
               OR binding.job_claimed_by<>'' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle IN ('BOUND','RUNNING') THEN
            IF NOT exact_claim
               OR binding.job_status NOT IN ('CLAIMED','RUNNING','CHECKPOINTED')
               OR binding.job_claimed_by IS DISTINCT FROM
                  binding.execution_worker_id
               OR binding.attempt_status IS DISTINCT FROM binding.job_status
               OR binding.lease_status IS DISTINCT FROM 'HELD' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='SUCCEEDED' THEN
            IF NOT exact_claim
               OR binding.job_status IS DISTINCT FROM 'SUCCEEDED'
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'SUCCEEDED'
               OR binding.lease_status IS DISTINCT FROM 'RELEASED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='FAILED' THEN
            IF NOT exact_claim
               OR binding.job_status NOT IN ('FAILED','DEAD_LETTER')
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'FAILED'
               OR binding.lease_status IS DISTINCT FROM 'RELEASED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='LOST' THEN
            IF NOT exact_claim
               OR binding.job_status IS DISTINCT FROM 'FAILED'
               OR binding.job_claimed_by<>''
               OR binding.attempt_status IS DISTINCT FROM 'ABANDONED'
               OR binding.lease_status IS DISTINCT FROM 'EXPIRED' THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF binding.execution_lifecycle='ABORTED' THEN
            IF binding.job_status IS DISTINCT FROM 'CANCELLED'
               OR binding.job_claimed_by<>''
               OR (
                   binding.execution_attempt_id IS NULL
                   AND (
                       binding.job_attempt_id IS NOT NULL
                       OR binding.job_fencing_token<>0
                   )
               )
               OR (
                   binding.execution_attempt_id IS NOT NULL
                   AND (
                       NOT exact_claim
                       OR binding.attempt_status IS DISTINCT FROM 'ABANDONED'
                       OR binding.lease_status IS DISTINCT FROM 'RELEASED'
                   )
               ) THEN
                RAISE EXCEPTION 'BOOK_OPENING_RELATIONAL_CLOSURE_INVALID:%',
                    target_opening_execution_id
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
    END;
    $$
    """,
    _VERSIONED_NARRATIVE_REPLACEMENT_GATE,
]


DOWNGRADE_STATEMENTS: list[str] = []
