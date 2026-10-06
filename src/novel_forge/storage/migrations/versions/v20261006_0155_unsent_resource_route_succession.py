from __future__ import annotations

MIGRATION_ID = "20261006_0155_unsent_resource_route_succession"
DOWN_REVISION = "20261006_0154_opening_resource_policy_succession"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "retain cancelled unsent route evidence; only a new frozen intent can use an alternative authorized channel"
UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_effect_resource_denial (
        external_effect_id TEXT PRIMARY KEY REFERENCES authority_external_effect(external_effect_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        reason TEXT NOT NULL CHECK (reason='PAID_WORK_BUDGET_EXHAUSTED'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TRIGGER authority_effect_resource_denial_immutable BEFORE UPDATE OR DELETE
        ON authority_effect_resource_denial FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
    """CREATE FUNCTION authority_effect_resource_denial_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.external_effect_id=NEW.external_effect_id
                AND effect.project_id=NEW.project_id AND effect.operation_id=NEW.operation_id AND effect.status='CANCELLED')
                OR EXISTS(SELECT 1 FROM authority_external_effect_dispatch WHERE external_effect_id=NEW.external_effect_id)
                OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE external_effect_id=NEW.external_effect_id) THEN
                RAISE EXCEPTION 'RESOURCE_ROUTE_UNSENT_PROOF_REQUIRED' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END; $$""",
    """CREATE TRIGGER authority_effect_resource_denial_exact BEFORE INSERT
        ON authority_effect_resource_denial FOR EACH ROW EXECUTE FUNCTION authority_effect_resource_denial_guard()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
