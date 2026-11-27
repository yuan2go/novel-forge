from __future__ import annotations

MIGRATION_ID = "20260804_0053_d0_provider_qualification_authority"
DOWN_REVISION = "20260804_0052_asset_schema_and_scope_integrity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "Correct invalid D0 run/scenario evidence with a new qualification run; "
    "never rewrite Provider receipts or usage evidence in place."
)

PREFLIGHT_STATEMENTS: list[str] = []

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_provider_price (
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        effective_from TIMESTAMPTZ NOT NULL,
        input_token_price NUMERIC(20, 10) NOT NULL,
        output_token_price NUMERIC(20, 10) NOT NULL,
        currency TEXT NOT NULL,
        price_source TEXT NOT NULL,
        price_version TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(provider, model, price_version),
        CHECK (input_token_price >= 0 AND output_token_price >= 0),
        CHECK (currency <> '' AND price_source <> '' AND price_version <> '')
    )
    """,
    """
    CREATE TABLE authority_d0_qualification_run (
        qualification_run_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        provider TEXT NOT NULL,
        backend_id TEXT NOT NULL,
        model TEXT NOT NULL,
        model_version TEXT NOT NULL,
        sdk_version TEXT NOT NULL,
        api_mode TEXT NOT NULL,
        sdk_max_retries INTEGER NOT NULL,
        timeout_seconds INTEGER NOT NULL,
        auth_secret_ref TEXT NOT NULL,
        route_snapshot JSONB NOT NULL,
        fixture_protocol_only BOOLEAN NOT NULL,
        status TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT 'PENDING',
        report_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        blocker TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (auth_secret_ref LIKE 'env://%'),
        CHECK (sdk_max_retries = 0),
        CHECK (timeout_seconds > 0),
        CHECK (status IN ('READY', 'RUNNING', 'WAITING_RECONCILIATION', 'COMPLETED', 'BLOCKED', 'FAILED')),
        CHECK (decision IN ('PENDING', 'QUALIFIED', 'NOT_QUALIFIED', 'BLOCKED')),
        CHECK (jsonb_typeof(route_snapshot) = 'object')
    )
    """,
    """
    CREATE TABLE authority_d0_scenario_evidence (
        qualification_run_id TEXT NOT NULL
            REFERENCES authority_d0_qualification_run(qualification_run_id),
        scenario TEXT NOT NULL,
        external_effect_id TEXT REFERENCES authority_external_effect(external_effect_id),
        provider_request_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        request_object_ref TEXT NOT NULL,
        response_object_ref TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response_hash TEXT NOT NULL,
        receipt JSONB NOT NULL,
        raw_usage JSONB NOT NULL,
        normalized_usage JSONB NOT NULL,
        provider_cost JSONB NOT NULL,
        calculated_cost JSONB NOT NULL,
        evidence JSONB NOT NULL,
        late_result BOOLEAN NOT NULL DEFAULT FALSE,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(qualification_run_id, scenario),
        CHECK (scenario IN ('D0-A', 'D0-B', 'D0-C', 'D0-D', 'D0-E', 'D0-F')),
        CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED', 'UNKNOWN', 'CANCELLED', 'LATE_RESULT')),
        CHECK (request_hash LIKE 'sha256:%'),
        CHECK (response_hash LIKE 'sha256:%')
    )
    """,
    "CREATE INDEX authority_d0_run_query_idx ON authority_d0_qualification_run(project_id, created_at DESC)",
    "CREATE INDEX authority_d0_scenario_effect_idx ON authority_d0_scenario_evidence(external_effect_id) WHERE external_effect_id IS NOT NULL",
    """
    CREATE OR REPLACE FUNCTION authority_validate_d0_scope()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    DECLARE operation_project TEXT;
    DECLARE workspace_project TEXT;
    BEGIN
        SELECT project_id INTO operation_project
        FROM authority_operation WHERE operation_id = NEW.operation_id;
        SELECT project_id INTO workspace_project
        FROM authority_workspace WHERE workspace_id = NEW.workspace_id;
        IF operation_project IS NULL OR operation_project <> NEW.project_id
           OR workspace_project IS NULL OR workspace_project <> NEW.project_id THEN
            RAISE EXCEPTION 'D0 Operation/Workspace does not belong to Project'
                USING ERRCODE='23514', CONSTRAINT='authority_d0_project_scope_check';
        END IF;
        PERFORM authority_require_asset_version_project(
            NEW.project_id, NEW.report_asset_version_id
        );
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_d0_scope_guard
    AFTER INSERT OR UPDATE ON authority_d0_qualification_run
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_validate_d0_scope()
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
