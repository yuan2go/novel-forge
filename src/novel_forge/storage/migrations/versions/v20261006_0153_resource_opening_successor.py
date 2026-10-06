from __future__ import annotations

MIGRATION_ID = "20261006_0153_resource_opening_successor"
DOWN_REVISION = "20261006_0152_validation_realization_admission"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "append native resource policy only for a zero-work historical Opening; preserve all prior snapshots"
UPGRADE_STATEMENTS = [
    r"""
    CREATE OR REPLACE FUNCTION authority_bo_capacity_continuation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
              AND ((NEW.evidence->>'contract_version'='book-opening-capacity-continuation.v1'
                AND new_budget.policy_snapshot-ARRAY['token_limit','per_call_token_limit']=old_budget.policy_snapshot-ARRAY['token_limit','per_call_token_limit']
                AND new_budget.policy_snapshot->>'accounting_basis'='ACCOUNT_ENTITLEMENT'
                AND (new_budget.policy_snapshot->>'per_call_token_limit')::bigint>(old_budget.policy_snapshot->>'per_call_token_limit')::bigint)
              OR (NEW.evidence->>'contract_version'='book-opening-capacity-continuation.v2'
                AND new_budget.policy_snapshot->>'resource_control_version'='billing-channel-resources.v1'
                AND EXISTS (SELECT 1 FROM authority_runtime_policy_version policy
                  JOIN authority_operation configured ON configured.operation_id=policy.created_by_operation_id
                  WHERE policy.owner='PROVIDER_ROUTING' AND policy.project_id=source.project_id
                    AND configured.status='SUCCEEDED'
                    AND policy.content=NEW.evidence #> '{execution_template,policy_snapshot,policy}'
                    AND policy.content_hash=NEW.evidence #>> '{execution_template,policy_snapshot,policy_hash}'
                    AND policy.created_by_operation_id=NEW.evidence #>> '{execution_template,policy_snapshot,operation_id}'
                    AND EXISTS (SELECT 1 FROM jsonb_array_elements(policy.content->'execution_templates') selected
                      WHERE selected->>'book_id'=source.book_id AND selected->>'mode'='CREATIVE_VALIDATION'
                        AND selected->>'member_authorization_ref'=new_budget.policy_snapshot->>'authorization_ref'
                        AND selected->>'require_literary_qualification'='false'))))
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
]
DOWNGRADE_STATEMENTS: list[str] = []
