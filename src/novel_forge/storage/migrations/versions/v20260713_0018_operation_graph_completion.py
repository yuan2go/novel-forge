from __future__ import annotations

MIGRATION_ID = "20260713_0018_operation_graph_completion"
DOWN_REVISION = "20260713_0017_external_effect_runtime"

UPGRADE_STATEMENTS = [
    "UPDATE authority_operation_dependency SET dependency_condition = 'ON_SUCCESS' WHERE dependency_condition = 'SUCCEEDED'",
    """
    ALTER TABLE authority_operation_dependency
    ADD CONSTRAINT authority_operation_dependency_condition_check
    CHECK (dependency_condition IN (
        'ON_SUCCESS', 'ON_COMPLETION', 'ON_FAILURE',
        'ON_COMPENSATED', 'MANUAL_GATE'
    ))
    """,
    """
    CREATE TABLE authority_completion_approval (
        approval_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        approval_key TEXT NOT NULL,
        status TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        evidence JSONB NOT NULL,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(operation_id, approval_key),
        CHECK (status IN ('APPROVED', 'REJECTED', 'REVOKED'))
    )
    """,
    "CREATE INDEX authority_completion_approval_operation_idx ON authority_completion_approval(operation_id)",
    """
    CREATE TABLE authority_completion_gate (
        gate_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        gate_key TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence JSONB NOT NULL,
        evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(operation_id, gate_key),
        CHECK (status IN ('PASSED', 'FAILED', 'PENDING'))
    )
    """,
    "CREATE INDEX authority_completion_gate_operation_idx ON authority_completion_gate(operation_id)",
    """
    CREATE TABLE authority_completion_aggregate_state (
        aggregate_state_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        state TEXT NOT NULL,
        version BIGINT NOT NULL,
        evidence JSONB NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(operation_id, aggregate_type, aggregate_id)
    )
    """,
    "CREATE INDEX authority_completion_aggregate_operation_idx ON authority_completion_aggregate_state(operation_id)",
    """
    CREATE TABLE authority_operation_cost_evidence (
        cost_evidence_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        amount NUMERIC(20, 8) NOT NULL,
        currency TEXT NOT NULL,
        evidence JSONB NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (amount >= 0)
    )
    """,
    "CREATE INDEX authority_operation_cost_operation_idx ON authority_operation_cost_evidence(operation_id)",
    """
    CREATE TABLE authority_saga (
        saga_id TEXT PRIMARY KEY,
        root_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL,
        status TEXT NOT NULL,
        version BIGINT NOT NULL DEFAULT 0,
        trace_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (status IN (
            'RUNNING', 'FORWARD_RECOVERY', 'COMPENSATING',
            'SUCCEEDED', 'COMPENSATED', 'COMPENSATION_FAILED',
            'MANUAL_INTERVENTION', 'CANCELLED'
        ))
    )
    """,
    "CREATE INDEX authority_saga_project_idx ON authority_saga(project_id, status)",
    """
    CREATE TABLE authority_saga_step (
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        step_key TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        compensation_definition TEXT NOT NULL DEFAULT '',
        compensation_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(saga_id, step_key),
        UNIQUE(saga_id, ordinal),
        CHECK (ordinal > 0),
        CHECK (compensation_status IN (
            'NOT_REQUIRED', 'REQUIRED', 'COMPENSATING',
            'COMPENSATED', 'COMPENSATION_FAILED'
        ))
    )
    """,
    "CREATE INDEX authority_saga_step_saga_idx ON authority_saga_step(saga_id, ordinal)",
]

DOWNGRADE_STATEMENTS: list[str] = []
