from __future__ import annotations

MIGRATION_ID = "20261006_0154_opening_resource_policy_succession"
DOWN_REVISION = "20261006_0153_resource_opening_successor"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append prospective resource admission without changing historical scopes, effects or completed nodes"
UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_book_opening_resource_successor (
        opening_run_id TEXT PRIMARY KEY REFERENCES authority_book_opening_run(opening_run_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL,
        budget_scope_id TEXT NOT NULL UNIQUE REFERENCES authority_provider_budget_scope(budget_scope_id),
        source_policy_hash TEXT NOT NULL CHECK (source_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        resource_policy JSONB NOT NULL,
        execution_template JSONB NOT NULL,
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (resource_policy #>> '{policy_snapshot,resource_control_version}'='billing-channel-resources.v1')
    )""",
    """CREATE TRIGGER authority_book_opening_resource_successor_immutable BEFORE UPDATE OR DELETE
        ON authority_book_opening_resource_successor FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
    """CREATE FUNCTION authority_book_opening_resource_successor_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM authority_book_opening_run opening
                JOIN authority_provider_budget_scope scope ON scope.budget_scope_id=opening.budget_scope_id
                JOIN authority_operation operation ON operation.operation_id=NEW.operation_id
                WHERE opening.opening_run_id=NEW.opening_run_id AND opening.project_id=NEW.project_id AND opening.book_id=NEW.book_id
                  AND scope.budget_scope_id=NEW.budget_scope_id AND scope.policy_hash=NEW.source_policy_hash
                  AND operation.project_id=NEW.project_id AND operation.definition_name='book.opening.adopt_resource_policy'
                  AND operation.actor_id=opening.frozen_request->>'actor_id'
                  AND operation.command_payload->'resource_policy'=NEW.resource_policy
                  AND (operation.command_payload->>'expected_version')::bigint=opening.version
                  AND opening.lifecycle NOT IN ('COMPLETE','ABORTED')) THEN
                RAISE EXCEPTION 'RESOURCE_SUCCESSOR_BINDING_INVALID' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END; $$""",
    """CREATE TRIGGER authority_book_opening_resource_successor_exact BEFORE INSERT
        ON authority_book_opening_resource_successor FOR EACH ROW EXECUTE FUNCTION authority_book_opening_resource_successor_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
