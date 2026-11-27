from __future__ import annotations

MIGRATION_ID = "20260914_0134_opening_capacity_continuation"
DOWN_REVISION = "20260914_0133_formation_evaluation_recovery"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = "Append an immutable capacity successor only for an unstarted failed Opening; retain both policies and fence its predecessor."

UPGRADE_STATEMENTS = [
    "ALTER TABLE authority_book_opening_run ADD COLUMN capacity_successor_opening_run_id TEXT REFERENCES authority_book_opening_run(opening_run_id) DEFERRABLE INITIALLY DEFERRED",
    "CREATE INDEX authority_bo_capacity_successor_idx ON authority_book_opening_run(capacity_successor_opening_run_id)",
    "DROP INDEX authority_bo_one_active_workflow_per_book_idx",
    "CREATE UNIQUE INDEX authority_bo_one_active_workflow_per_book_idx ON authority_book_opening_run(project_id,book_id) WHERE lifecycle IN ('ADMITTED','RUNNING','FAILED') AND capacity_successor_opening_run_id IS NULL",
    """
    CREATE TABLE authority_book_opening_capacity_continuation (
        source_opening_run_id TEXT PRIMARY KEY REFERENCES authority_book_opening_run(opening_run_id),
        successor_opening_run_id TEXT NOT NULL UNIQUE REFERENCES authority_book_opening_run(opening_run_id),
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        evidence JSONB NOT NULL CHECK(jsonb_typeof(evidence)='object'),
        evidence_hash TEXT NOT NULL CHECK(evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK(source_opening_run_id<>successor_opening_run_id),
        FOREIGN KEY(project_id,workspace_id,book_id) REFERENCES authority_book(project_id,workspace_id,book_id)
    )
    """,
    "CREATE INDEX authority_bo_capacity_continuation_scope_idx ON authority_book_opening_capacity_continuation(project_id,workspace_id,book_id)",
    """
    CREATE FUNCTION authority_bo_capacity_continuation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'BOOK_OPENING_CONTINUATION_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM authority_book_opening_run source
            JOIN authority_book_opening_run successor ON successor.opening_run_id=NEW.successor_opening_run_id
              AND successor.project_id=source.project_id AND successor.workspace_id=source.workspace_id AND successor.book_id=source.book_id
              AND successor.frozen_request-'idempotency_key'=source.frozen_request-'idempotency_key'
              AND successor.root_operation_id=NEW.operation_id AND successor.lifecycle='ADMITTED'
            JOIN authority_operation operation ON operation.operation_id=NEW.operation_id
              AND operation.definition_name='book.opening.continue_unstarted'
              AND operation.causation_operation_id=source.root_operation_id
              AND operation.actor_id=source.frozen_request->>'actor_id'
              AND operation.command_payload->'capacity_continuation'=NEW.evidence->'request'
            JOIN authority_provider_budget_scope old_budget ON old_budget.budget_scope_id=source.budget_scope_id
            JOIN authority_provider_budget_scope new_budget ON new_budget.budget_scope_id=successor.budget_scope_id
              AND new_budget.policy_snapshot-ARRAY['token_limit','per_call_token_limit']=old_budget.policy_snapshot-ARRAY['token_limit','per_call_token_limit']
              AND new_budget.policy_snapshot->>'accounting_basis'='ACCOUNT_ENTITLEMENT'
              AND (new_budget.policy_snapshot->>'per_call_token_limit')::bigint>(old_budget.policy_snapshot->>'per_call_token_limit')::bigint
            WHERE source.opening_run_id=NEW.source_opening_run_id AND source.lifecycle='FAILED'
              AND source.capacity_successor_opening_run_id=NEW.successor_opening_run_id
              AND source.project_id=NEW.project_id AND source.workspace_id=NEW.workspace_id AND source.book_id=NEW.book_id
              AND source.version=(NEW.evidence->'request'->>'expected_version')::bigint
              AND source.frozen_request_digest=NEW.evidence->>'source_frozen_request_digest'
              AND source.failure->>'code' IN ('PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED','PROVIDER_REQUEST_BUDGET_EXCEEDED')
              AND old_budget.policy_hash=NEW.evidence->>'source_policy_hash'
              AND new_budget.policy_hash=NEW.evidence->>'successor_policy_hash'
              AND NOT EXISTS (SELECT 1 FROM authority_book_opening_capacity_continuation previous WHERE previous.successor_opening_run_id=source.opening_run_id)
              AND NOT EXISTS (SELECT 1 FROM authority_book_opening_node_receipt receipt WHERE receipt.opening_run_id=source.opening_run_id)
              AND NOT EXISTS (SELECT 1 FROM authority_budget_reservation reservation WHERE reservation.budget_scope_id=source.budget_scope_id)
              AND NOT EXISTS (SELECT 1 FROM authority_book_opening_budget_operation_binding binding JOIN authority_external_effect effect USING(operation_id) WHERE binding.opening_run_id=source.opening_run_id)
              AND NOT EXISTS (
                  SELECT 1 FROM authority_operation child JOIN authority_external_effect effect USING(operation_id)
                  WHERE child.project_id=source.project_id AND COALESCE(child.command_payload #>> '{payload,opening_execution_binding,opening_run_id}',
                      child.command_payload #>> '{opening_execution_binding,opening_run_id}')=source.opening_run_id
              )
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_CONTINUATION_BINDING_INVALID' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_bo_capacity_continuation_guard BEFORE INSERT OR UPDATE OR DELETE ON authority_book_opening_capacity_continuation FOR EACH ROW EXECUTE FUNCTION authority_bo_capacity_continuation_guard()",
    """
    CREATE FUNCTION authority_bo_capacity_predecessor_fence() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.capacity_successor_opening_run_id IS NOT NULL THEN
            RAISE EXCEPTION 'BOOK_OPENING_CAPACITY_PREDECESSOR_FENCED' USING ERRCODE='check_violation';
        END IF;
        IF TG_OP='UPDATE' AND NEW.capacity_successor_opening_run_id IS NOT NULL
          AND (OLD.lifecycle<>'FAILED' OR to_jsonb(OLD)-'capacity_successor_opening_run_id'<>to_jsonb(NEW)-'capacity_successor_opening_run_id') THEN
            RAISE EXCEPTION 'BOOK_OPENING_CAPACITY_SOURCE_IMMUTABLE' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END; $$
    """,
    "CREATE TRIGGER authority_bo_capacity_predecessor_fence BEFORE UPDATE OR DELETE ON authority_book_opening_run FOR EACH ROW EXECUTE FUNCTION authority_bo_capacity_predecessor_fence()",
    """
    CREATE FUNCTION authority_bo_capacity_pointer_binding() RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.capacity_successor_opening_run_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM authority_book_opening_capacity_continuation
            WHERE source_opening_run_id=NEW.opening_run_id AND successor_opening_run_id=NEW.capacity_successor_opening_run_id
        ) THEN
            RAISE EXCEPTION 'BOOK_OPENING_CAPACITY_POINTER_UNBOUND' USING ERRCODE='check_violation';
        END IF;
        RETURN NULL;
    END; $$
    """,
    "CREATE CONSTRAINT TRIGGER authority_bo_capacity_pointer_binding AFTER INSERT OR UPDATE ON authority_book_opening_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authority_bo_capacity_pointer_binding()",
]
