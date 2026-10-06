from __future__ import annotations

from .v20261006_0164_execution_contract_continuation import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = '20261007_0165_derived_step_revalidation'
DOWN_REVISION = '20261006_0164_execution_contract_continuation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'append unaccepted derived-step revalidation without rewriting completed outputs, calls or acceptance'
UPGRADE_STATEMENTS = [
    PREVIOUS_GUARDS[0].replace("'creative-execution-template.v5')", "'creative-execution-template.v5','creative-execution-template.v6')"),
    '''CREATE TABLE authority_saga_step_revalidation (
        revalidation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        predecessor_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        successor_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        actor_id TEXT NOT NULL,
        contract_version TEXT NOT NULL CHECK (contract_version='kernel-derived-step-successor.v1'),
        request_digest TEXT NOT NULL,
        source_step_snapshot JSONB NOT NULL,
        source_execution_snapshot JSONB NOT NULL,
        policy_evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (predecessor_operation_id<>successor_operation_id)
    )''',
]
DOWNGRADE_STATEMENTS: list[str] = []
