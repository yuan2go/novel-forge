from __future__ import annotations


MIGRATION_ID = "20260805_0068_unified_agent_runtime"
DOWN_REVISION = "20260804_0067_activated_migration_archival_binding"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Disable the affected Agent Definition or Chapter binding activation, "
    "register a corrected immutable successor version, and resume through "
    "the existing Authority retry or recovery command."
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_agent_capability_execution_mapping (
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        execution_capability_id TEXT NOT NULL,
        execution_capability_hash TEXT NOT NULL,
        mapping_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(capability_id, capability_version),
        FOREIGN KEY(capability_id, capability_version)
            REFERENCES authority_agent_capability(
                capability_id, capability_version
            ),
        CHECK (execution_capability_id <> ''),
        CHECK (execution_capability_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (mapping_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_agent_capability_mapping_created_operation_idx
    ON authority_agent_capability_execution_mapping(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_agent_definition_runtime_contract (
        agent_id TEXT NOT NULL,
        definition_version INTEGER NOT NULL,
        capability_pack_ref TEXT NOT NULL,
        prompt_bundle_ref TEXT NOT NULL,
        prompt_bundle_hash TEXT NOT NULL,
        skill_bundle_ref TEXT NOT NULL,
        skill_bundle_hash TEXT NOT NULL,
        tool_policy_ref TEXT NOT NULL,
        tool_policy_hash TEXT NOT NULL,
        context_policy_ref TEXT NOT NULL,
        context_policy_hash TEXT NOT NULL,
        runtime_contract_hash TEXT NOT NULL,
        definition_source TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(agent_id, definition_version),
        FOREIGN KEY(agent_id, definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        CHECK (capability_pack_ref <> ''),
        CHECK (prompt_bundle_ref <> '' AND skill_bundle_ref <> ''),
        CHECK (tool_policy_ref <> '' AND context_policy_ref <> ''),
        CHECK (prompt_bundle_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (skill_bundle_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (tool_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (context_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (runtime_contract_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (definition_source IN (
            'POSTGRES_AUTHORITY', 'BOOTSTRAP_ADAPTER', 'LEGACY_MIGRATION'
        ))
    )
    """,
    """
    CREATE INDEX authority_agent_runtime_contract_created_operation_idx
    ON authority_agent_definition_runtime_contract(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_agent_definition_activation (
        agent_id TEXT PRIMARY KEY,
        definition_version INTEGER NOT NULL,
        activation_status TEXT NOT NULL,
        activation_version BIGINT NOT NULL DEFAULT 1,
        reason TEXT NOT NULL,
        activated_by TEXT NOT NULL,
        activated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(agent_id, definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        FOREIGN KEY(agent_id, definition_version)
            REFERENCES authority_agent_definition_runtime_contract(
                agent_id, definition_version
            ),
        CHECK (activation_status IN ('ACTIVE', 'DISABLED', 'RETIRED')),
        CHECK (activation_version > 0),
        CHECK (reason <> '' AND activated_by <> '')
    )
    """,
    """
    CREATE INDEX authority_agent_definition_activation_query_idx
    ON authority_agent_definition_activation(
        activation_status, updated_at DESC, agent_id
    )
    """,
    """
    CREATE INDEX authority_agent_definition_activation_version_idx
    ON authority_agent_definition_activation(agent_id, definition_version)
    """,
    """
    CREATE INDEX authority_agent_definition_activation_operation_idx
    ON authority_agent_definition_activation(activated_by_operation_id)
    """,
    """
    CREATE TABLE authority_chapter_node_agent_binding (
        binding_id TEXT NOT NULL,
        binding_version INTEGER NOT NULL,
        workflow_definition_ref TEXT NOT NULL,
        workflow_node_id TEXT NOT NULL,
        operation_definition_name TEXT NOT NULL,
        operation_definition_version TEXT NOT NULL,
        operation_definition_hash TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        agent_definition_version INTEGER NOT NULL,
        agent_definition_hash TEXT NOT NULL,
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        capability_hash TEXT NOT NULL,
        execution_capability_id TEXT NOT NULL,
        capability_pack_ref TEXT NOT NULL,
        capability_pack_compilation_hash TEXT NOT NULL,
        input_contract_ref TEXT NOT NULL,
        output_contract_ref TEXT NOT NULL,
        domain_acceptance_policy_ref TEXT NOT NULL,
        commit_authority TEXT NOT NULL,
        binding_status TEXT NOT NULL,
        release_sha TEXT NOT NULL,
        binding_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(binding_id, binding_version),
        UNIQUE(workflow_definition_ref, workflow_node_id, binding_version),
        UNIQUE(
            workflow_definition_ref, workflow_node_id,
            binding_id, binding_version
        ),
        FOREIGN KEY(operation_definition_name, operation_definition_version)
            REFERENCES authority_operation_definition(name, definition_version),
        FOREIGN KEY(agent_id, agent_definition_version)
            REFERENCES authority_agent_definition_runtime_contract(
                agent_id, definition_version
            ),
        FOREIGN KEY(capability_id, capability_version)
            REFERENCES authority_agent_capability_execution_mapping(
                capability_id, capability_version
            ),
        FOREIGN KEY(
            agent_id, agent_definition_version,
            capability_id, capability_version
        ) REFERENCES authority_agent_definition_capability(
            agent_id, definition_version,
            capability_id, capability_version
        ),
        CHECK (binding_version > 0),
        CHECK (binding_status IN ('CANDIDATE', 'ACTIVE', 'RETIRED')),
        CHECK (commit_authority ~ '^[A-Z0-9_]+_AUTHORITY$'),
        CHECK (operation_definition_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (agent_definition_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (capability_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (capability_pack_compilation_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (binding_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (release_sha ~ '^[0-9a-f]{40,64}$')
    )
    """,
    """
    CREATE TABLE authority_chapter_node_agent_binding_activation (
        workflow_definition_ref TEXT NOT NULL,
        workflow_node_id TEXT NOT NULL,
        binding_id TEXT NOT NULL,
        binding_version INTEGER NOT NULL,
        activation_status TEXT NOT NULL,
        activation_version BIGINT NOT NULL DEFAULT 1,
        reason TEXT NOT NULL,
        activated_by TEXT NOT NULL,
        activated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(workflow_definition_ref, workflow_node_id),
        FOREIGN KEY(
            workflow_definition_ref, workflow_node_id,
            binding_id, binding_version
        )
            REFERENCES authority_chapter_node_agent_binding(
                workflow_definition_ref, workflow_node_id,
                binding_id, binding_version
            ),
        CHECK (activation_status IN ('ACTIVE', 'DISABLED', 'RETIRED')),
        CHECK (activation_version > 0),
        CHECK (reason <> '' AND activated_by <> '')
    )
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_definition_idx
    ON authority_chapter_node_agent_binding(agent_id, agent_definition_version)
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_operation_definition_idx
    ON authority_chapter_node_agent_binding(
        operation_definition_name, operation_definition_version
    )
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_capability_idx
    ON authority_chapter_node_agent_binding(capability_id, capability_version)
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_created_operation_idx
    ON authority_chapter_node_agent_binding(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_activation_binding_idx
    ON authority_chapter_node_agent_binding_activation(
        binding_id, binding_version
    )
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_activation_operation_idx
    ON authority_chapter_node_agent_binding_activation(
        activated_by_operation_id
    )
    """,
    """
    CREATE TABLE authority_agent_runtime_binding (
        binding_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL,
        book_id TEXT,
        workflow_definition_ref TEXT NOT NULL,
        workflow_node_id TEXT NOT NULL,
        operation_definition_name TEXT NOT NULL,
        operation_definition_version TEXT NOT NULL,
        operation_definition_hash TEXT NOT NULL,
        operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL UNIQUE
            REFERENCES authority_attempt(attempt_id),
        fencing_token BIGINT NOT NULL,
        work_order_id TEXT NOT NULL UNIQUE
            REFERENCES authority_agent_work_order(work_order_id),
        agent_id TEXT NOT NULL,
        agent_definition_version INTEGER NOT NULL,
        agent_definition_hash TEXT NOT NULL,
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        capability_hash TEXT NOT NULL,
        execution_capability_id TEXT NOT NULL,
        chapter_node_binding_id TEXT NOT NULL,
        chapter_node_binding_version INTEGER NOT NULL,
        capability_pack_ref TEXT NOT NULL,
        capability_pack_compilation_hash TEXT NOT NULL,
        context_bundle_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        context_bundle_hash TEXT NOT NULL,
        prompt_bundle_ref TEXT NOT NULL,
        prompt_bundle_hash TEXT NOT NULL,
        skill_bundle_ref TEXT NOT NULL,
        skill_bundle_hash TEXT NOT NULL,
        tool_policy_ref TEXT NOT NULL,
        tool_policy_hash TEXT NOT NULL,
        tool_permission_snapshot_ref TEXT NOT NULL,
        tool_permission_snapshot_hash TEXT NOT NULL,
        context_policy_ref TEXT NOT NULL,
        context_policy_hash TEXT NOT NULL,
        route_snapshot_ref TEXT NOT NULL,
        route_snapshot_hash TEXT NOT NULL,
        input_manifest_ref TEXT NOT NULL,
        input_manifest_hash TEXT NOT NULL,
        budget_policy_ref TEXT NOT NULL,
        timeout_policy_ref TEXT NOT NULL,
        approval_policy_ref TEXT NOT NULL,
        validation_policy_ref TEXT NOT NULL,
        commit_policy_ref TEXT NOT NULL,
        commit_authority TEXT NOT NULL,
        release_sha TEXT NOT NULL,
        binding_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id)
            REFERENCES authority_workspace(project_id, workspace_id),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        FOREIGN KEY(operation_definition_name, operation_definition_version)
            REFERENCES authority_operation_definition(name, definition_version),
        FOREIGN KEY(agent_id, agent_definition_version)
            REFERENCES authority_agent_definition_runtime_contract(
                agent_id, definition_version
            ),
        FOREIGN KEY(capability_id, capability_version)
            REFERENCES authority_agent_capability_execution_mapping(
                capability_id, capability_version
            ),
        FOREIGN KEY(
            workflow_definition_ref, workflow_node_id,
            chapter_node_binding_id, chapter_node_binding_version
        )
            REFERENCES authority_chapter_node_agent_binding(
                workflow_definition_ref, workflow_node_id,
                binding_id, binding_version
            ),
        CHECK (fencing_token > 0),
        CHECK (commit_authority ~ '^[A-Z0-9_]+_AUTHORITY$'),
        CHECK (operation_definition_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (agent_definition_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (capability_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (capability_pack_compilation_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (context_bundle_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (prompt_bundle_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (skill_bundle_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (tool_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (tool_permission_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (context_policy_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (route_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (input_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (binding_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (release_sha ~ '^[0-9a-f]{40,64}$')
    )
    """,
    """
    CREATE INDEX authority_agent_runtime_project_query_idx
    ON authority_agent_runtime_binding(
        project_id, book_id, agent_id, created_at DESC
    )
    """,
    """
    CREATE INDEX authority_agent_runtime_operation_idx
    ON authority_agent_runtime_binding(operation_id, created_at DESC)
    """,
    """
    CREATE INDEX authority_agent_runtime_workspace_idx
    ON authority_agent_runtime_binding(project_id, workspace_id)
    """,
    """
    CREATE INDEX authority_agent_runtime_book_idx
    ON authority_agent_runtime_binding(project_id, workspace_id, book_id)
    """,
    """
    CREATE INDEX authority_agent_runtime_operation_definition_idx
    ON authority_agent_runtime_binding(
        operation_definition_name, operation_definition_version
    )
    """,
    """
    CREATE INDEX authority_agent_runtime_definition_idx
    ON authority_agent_runtime_binding(agent_id, agent_definition_version)
    """,
    """
    CREATE INDEX authority_agent_runtime_capability_idx
    ON authority_agent_runtime_binding(capability_id, capability_version)
    """,
    """
    CREATE INDEX authority_agent_runtime_context_idx
    ON authority_agent_runtime_binding(context_bundle_asset_version_id)
    """,
    """
    CREATE INDEX authority_agent_runtime_chapter_binding_idx
    ON authority_agent_runtime_binding(
        chapter_node_binding_id, chapter_node_binding_version
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_runtime_binding_guard()
    RETURNS TRIGGER AS $$
    DECLARE
        attempt_operation_id TEXT;
        operation_project_id TEXT;
        operation_definition_name_value TEXT;
        operation_definition_version_value TEXT;
        work_order_attempt_id TEXT;
        work_order_fencing_token BIGINT;
        work_order_agent_id TEXT;
        work_order_agent_version INTEGER;
        work_order_capability_id TEXT;
        work_order_capability_version INTEGER;
        work_order_execution_capability_id TEXT;
        lease_exists BOOLEAN;
    BEGIN
        SELECT attempt.operation_id
        INTO attempt_operation_id
        FROM authority_attempt AS attempt
        WHERE attempt.attempt_id=NEW.attempt_id;

        SELECT operation.project_id, operation.definition_name,
               operation.definition_version
        INTO operation_project_id, operation_definition_name_value,
             operation_definition_version_value
        FROM authority_operation AS operation
        WHERE operation.operation_id=NEW.operation_id;

        SELECT work_order.attempt_id, work_order.fencing_token,
               work_order.agent_id, work_order.agent_definition_version,
               work_order.capability_id, work_order.capability_version,
               work_order.execution_capability_id
        INTO work_order_attempt_id, work_order_fencing_token,
             work_order_agent_id, work_order_agent_version,
             work_order_capability_id, work_order_capability_version,
             work_order_execution_capability_id
        FROM authority_agent_work_order AS work_order
        WHERE work_order.work_order_id=NEW.work_order_id
          AND work_order.operation_id=NEW.operation_id;

        SELECT EXISTS(
            SELECT 1
            FROM authority_lease_acquisition AS lease
            WHERE lease.attempt_id=NEW.attempt_id
              AND lease.fencing_token=NEW.fencing_token
        ) INTO lease_exists;

        IF attempt_operation_id IS DISTINCT FROM NEW.operation_id
           OR operation_project_id IS DISTINCT FROM NEW.project_id
           OR operation_definition_name_value
                IS DISTINCT FROM NEW.operation_definition_name
           OR operation_definition_version_value
                IS DISTINCT FROM NEW.operation_definition_version
           OR work_order_attempt_id IS DISTINCT FROM NEW.attempt_id
           OR work_order_fencing_token IS DISTINCT FROM NEW.fencing_token
           OR work_order_agent_id IS DISTINCT FROM NEW.agent_id
           OR work_order_agent_version
                IS DISTINCT FROM NEW.agent_definition_version
           OR work_order_capability_id IS DISTINCT FROM NEW.capability_id
           OR work_order_capability_version
                IS DISTINCT FROM NEW.capability_version
           OR work_order_execution_capability_id
                IS DISTINCT FROM NEW.execution_capability_id
           OR NOT lease_exists THEN
            RAISE EXCEPTION 'Agent Runtime binding differs from Authority facts'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_runtime_binding_guard';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_agent_runtime_binding_fact_guard
    AFTER INSERT ON authority_agent_runtime_binding
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_agent_runtime_binding_guard()
    """,
    """
    CREATE TRIGGER authority_agent_capability_execution_mapping_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_capability_execution_mapping
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_definition_runtime_contract_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_definition_runtime_contract
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_definition_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_definition
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_capability_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_capability
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_chapter_node_agent_binding_immutable
    BEFORE UPDATE OR DELETE ON authority_chapter_node_agent_binding
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_runtime_binding_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_runtime_binding
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
