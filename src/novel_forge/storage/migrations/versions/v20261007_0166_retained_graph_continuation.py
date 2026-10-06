from __future__ import annotations

from .v20261007_0165_derived_step_revalidation import UPGRADE_STATEMENTS as PREVIOUS_GUARDS

MIGRATION_ID = '20261007_0166_retained_graph_continuation'
DOWN_REVISION = '20261007_0165_derived_step_revalidation'
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = 'append terminal graph continuations referencing completed operations without rewriting their lifecycle or accounting'
UPGRADE_STATEMENTS = [
    PREVIOUS_GUARDS[0].replace("'creative-execution-template.v6')", "'creative-execution-template.v6','creative-execution-template.v7')"),
    '''CREATE TABLE authority_graph_continuation (
        continuation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_root_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        successor_root_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        source_saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        successor_saga_id TEXT NOT NULL UNIQUE REFERENCES authority_saga(saga_id),
        actor_id TEXT NOT NULL,
        contract_version TEXT NOT NULL CHECK (contract_version='kernel-retained-graph-continuation.v1'),
        request_digest TEXT NOT NULL,
        source_snapshot JSONB NOT NULL,
        policy_evidence JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (source_root_operation_id<>successor_root_operation_id),
        CHECK (source_saga_id<>successor_saga_id)
    )''',
    '''CREATE TABLE authority_saga_retained_step (
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        continuation_id TEXT NOT NULL REFERENCES authority_graph_continuation(continuation_id),
        step_key TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal>0),
        source_step_snapshot JSONB NOT NULL,
        source_output_snapshot JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(saga_id,step_key),
        UNIQUE(saga_id,operation_id),
        UNIQUE(saga_id,ordinal)
    )''',
    """CREATE TRIGGER authority_graph_continuation_immutable BEFORE UPDATE OR DELETE ON authority_graph_continuation
        FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
    """CREATE TRIGGER authority_saga_retained_step_immutable BEFORE UPDATE OR DELETE ON authority_saga_retained_step
        FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()""",
]
DOWNGRADE_STATEMENTS: list[str] = []
