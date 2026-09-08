from __future__ import annotations

from decimal import Decimal

import psycopg

from novel_forge.storage.migrations import run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
)


BASELINE = "20260907_0120_foundation_generation"


def test_account_entitlement_migration_preserves_settled_priced_history() -> None:
    with disposable_database_at_migration(
        DATABASE_URL,
        prefix="account_entitlement_upgrade",
        target_migration_id=BASELINE,
    ) as url:
        with psycopg.connect(url) as connection:
            connection.execute(
                """
                INSERT INTO authority_operation_definition(
                    name,definition_version,family,enabled,command_schema,
                    result_schema,policy,completion_contract
                ) VALUES (
                    'fixture.account_entitlement.upgrade','1.0.0','fixture',TRUE,
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb
                )
                """
            )
            connection.execute(
                """
                INSERT INTO authority_operation(
                    operation_id,definition_name,definition_version,project_id,
                    workspace_id,actor_id,status,root_operation_id,
                    idempotency_scope,idempotency_key,request_digest,
                    definition_snapshot,completion_contract_snapshot,
                    policy_snapshot,concurrency_key,command_payload
                ) VALUES (
                    'operation:account-entitlement-upgrade',
                    'fixture.account_entitlement.upgrade','1.0.0',
                    'project:account-entitlement-upgrade',
                    'workspace:account-entitlement-upgrade','fixture','SUCCEEDED',
                    'operation:account-entitlement-upgrade',
                    'project:account-entitlement-upgrade','upgrade-fixture',
                    'sha256:0000000000000000000000000000000000000000000000000000000000000000',
                    '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
                    'fixture:account-entitlement-upgrade','{}'::jsonb
                )
                """
            )
            connection.execute(
                """
                INSERT INTO authority_budget_reservation(
                    reservation_id,operation_id,project_id,
                    stable_idempotency_key,provider,currency,
                    estimated_amount,reserved_amount,settled_amount,
                    estimated_tokens,actual_tokens,status,settled_at
                ) VALUES (
                    'reservation:priced-settled-upgrade',
                    'operation:account-entitlement-upgrade',
                    'project:account-entitlement-upgrade','priced-settled-upgrade',
                    'openai','USD',1.25,1.25,0.75,1000,800,'SETTLED',NOW()
                )
                """
            )
            connection.commit()

        status = run_migrations(url)
        assert status["ok"]

        with psycopg.connect(url) as connection:
            row = connection.execute(
                """
                SELECT accounting_basis,estimated_cost_status,
                       settled_cost_status,estimated_amount,reserved_amount,
                       settled_amount,status
                FROM authority_budget_reservation
                WHERE reservation_id='reservation:priced-settled-upgrade'
                """
            ).fetchone()
        assert row == (
            "PRICED",
            "KNOWN",
            "KNOWN",
            Decimal("1.25"),
            Decimal("1.25"),
            Decimal("0.75"),
            "SETTLED",
        )
