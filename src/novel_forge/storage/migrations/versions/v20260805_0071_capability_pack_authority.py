from __future__ import annotations


MIGRATION_ID = "20260805_0071_capability_pack_authority"
DOWN_REVISION = "20260805_0070_agent_runtime_recovery_protocol"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Preserve every immutable Pack Version, Compilation, Approval, Binding Set, "
    "Deployment, Assignment, and Runtime Binding. Register corrected successor "
    "facts and switch only the CAS activation pointer."
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_capability_pack (
        pack_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        capability_type TEXT NOT NULL,
        owner TEXT NOT NULL,
        description TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (pack_id <> '' AND name <> '' AND domain <> ''),
        CHECK (capability_type <> '' AND owner <> '')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_created_operation_idx
    ON authority_capability_pack(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_version (
        pack_id TEXT NOT NULL REFERENCES authority_capability_pack(pack_id),
        pack_version TEXT NOT NULL,
        manifest_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        artifact_catalog_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        manifest_hash TEXT NOT NULL,
        artifact_catalog_hash TEXT NOT NULL,
        protocol_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'REGISTERED',
        lifecycle TEXT NOT NULL,
        release_channel TEXT NOT NULL,
        registered_by TEXT NOT NULL,
        registered_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(pack_id, pack_version),
        UNIQUE(pack_id, pack_version, manifest_hash),
        CHECK (pack_version <> '' AND protocol_version <> ''),
        CHECK (status = 'REGISTERED'),
        CHECK (lifecycle IN ('DEVELOPMENT', 'VALIDATION', 'PRODUCTION')),
        CHECK (release_channel <> '' AND registered_by <> ''),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (artifact_catalog_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_version_manifest_fk_idx
    ON authority_capability_pack_version(manifest_asset_version_id)
    """,
    """
    CREATE INDEX authority_capability_pack_version_catalog_fk_idx
    ON authority_capability_pack_version(artifact_catalog_asset_version_id)
    """,
    """
    CREATE INDEX authority_capability_pack_version_operation_idx
    ON authority_capability_pack_version(registered_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_validation (
        validation_id TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        validator_version TEXT NOT NULL,
        decision TEXT NOT NULL,
        report JSONB NOT NULL,
        report_hash TEXT NOT NULL,
        validated_by TEXT NOT NULL,
        validated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(pack_id, pack_version, manifest_hash)
            REFERENCES authority_capability_pack_version(
                pack_id, pack_version, manifest_hash
            ),
        UNIQUE(pack_id, pack_version, manifest_hash, report_hash),
        CHECK (decision IN ('VALID', 'INVALID')),
        CHECK (validator_version <> '' AND validated_by <> ''),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (report_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_validation_version_idx
    ON authority_capability_pack_validation(pack_id, pack_version, validated_at DESC)
    """,
    """
    CREATE INDEX authority_capability_pack_validation_operation_idx
    ON authority_capability_pack_validation(validated_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_compilation (
        compilation_id TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        compiled_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        compilation_hash TEXT NOT NULL UNIQUE,
        catalog_snapshot_hash TEXT NOT NULL,
        compiler_version TEXT NOT NULL,
        release_sha TEXT NOT NULL,
        novel_forge_version TEXT NOT NULL,
        runtime_profile TEXT NOT NULL,
        release_channel TEXT NOT NULL,
        compilation_status TEXT NOT NULL DEFAULT 'TRUSTED',
        compiled_by TEXT NOT NULL,
        compiled_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(pack_id, pack_version, manifest_hash)
            REFERENCES authority_capability_pack_version(
                pack_id, pack_version, manifest_hash
            ),
        UNIQUE(pack_id, pack_version, compilation_hash),
        CHECK (compilation_status = 'TRUSTED'),
        CHECK (compiler_version <> '' AND novel_forge_version <> ''),
        CHECK (runtime_profile <> '' AND release_channel <> ''),
        CHECK (compiled_by <> ''),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (compilation_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (catalog_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (release_sha ~ '^[0-9a-f]{40,64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_compilation_version_idx
    ON authority_capability_pack_compilation(pack_id, pack_version, created_at DESC)
    """,
    """
    CREATE INDEX authority_capability_pack_compilation_manifest_fk_idx
    ON authority_capability_pack_compilation(pack_id, pack_version, manifest_hash)
    """,
    """
    CREATE INDEX authority_capability_pack_compilation_operation_idx
    ON authority_capability_pack_compilation(compiled_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_approval (
        approval_id TEXT PRIMARY KEY,
        compilation_id TEXT NOT NULL
            REFERENCES authority_capability_pack_compilation(compilation_id),
        compilation_hash TEXT NOT NULL,
        decision TEXT NOT NULL,
        approval_policy_ref TEXT NOT NULL,
        approval_scope JSONB NOT NULL,
        reason TEXT NOT NULL,
        evidence_refs JSONB NOT NULL,
        limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
        expires_at TIMESTAMPTZ,
        decided_by TEXT NOT NULL,
        decided_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(approval_id, compilation_id, compilation_hash),
        CHECK (decision IN ('APPROVED', 'REJECTED', 'REVOKED')),
        CHECK (approval_policy_ref <> '' AND reason <> '' AND decided_by <> ''),
        CHECK (compilation_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_approval_current_idx
    ON authority_capability_pack_approval(compilation_id, decided_at DESC, approval_id DESC)
    """,
    """
    CREATE INDEX authority_capability_pack_approval_operation_idx
    ON authority_capability_pack_approval(decided_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_binding_set (
        binding_set_id TEXT PRIMARY KEY,
        compilation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_capability_pack_compilation(compilation_id),
        binding_set_hash TEXT NOT NULL UNIQUE,
        workflow_definition_ref TEXT NOT NULL,
        node_bindings JSONB NOT NULL,
        artifact_bindings JSONB NOT NULL,
        policy_bindings JSONB NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (workflow_definition_ref <> ''),
        CHECK (binding_set_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_binding_set_operation_idx
    ON authority_capability_pack_binding_set(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_deployment (
        deployment_id TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        compilation_id TEXT NOT NULL
            REFERENCES authority_capability_pack_compilation(compilation_id),
        binding_set_id TEXT NOT NULL
            REFERENCES authority_capability_pack_binding_set(binding_set_id),
        target_scope_type TEXT NOT NULL,
        scope_key TEXT NOT NULL,
        project_id TEXT REFERENCES authority_project(project_id),
        workspace_id TEXT,
        book_id TEXT,
        environment TEXT NOT NULL,
        workflow_definition_ref TEXT NOT NULL,
        deployment_status TEXT NOT NULL DEFAULT 'CANDIDATE',
        rollout_policy_ref TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(pack_id, pack_version)
            REFERENCES authority_capability_pack_version(pack_id, pack_version),
        FOREIGN KEY(project_id, workspace_id)
            REFERENCES authority_workspace(project_id, workspace_id),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        UNIQUE(scope_key, environment, workflow_definition_ref, deployment_id),
        CHECK (target_scope_type IN ('SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK')),
        CHECK (
            (target_scope_type = 'SYSTEM' AND project_id IS NULL
                AND workspace_id IS NULL AND book_id IS NULL)
            OR (target_scope_type = 'PROJECT' AND project_id IS NOT NULL
                AND workspace_id IS NULL AND book_id IS NULL)
            OR (target_scope_type = 'WORKSPACE' AND project_id IS NOT NULL
                AND workspace_id IS NOT NULL AND book_id IS NULL)
            OR (target_scope_type = 'BOOK' AND project_id IS NOT NULL
                AND workspace_id IS NOT NULL AND book_id IS NOT NULL)
        ),
        CHECK (environment <> '' AND workflow_definition_ref <> ''),
        CHECK (deployment_status IN (
            'CANDIDATE', 'ACTIVE', 'DISABLED', 'DEPRECATED', 'RETIRED',
            'ROLLBACK_REQUIRED'
        )),
        CHECK (rollout_policy_ref <> ''),
        CHECK (scope_key ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_deployment_scope_idx
    ON authority_capability_pack_deployment(
        scope_key, environment, workflow_definition_ref, deployment_status
    )
    """,
    """
    CREATE INDEX authority_capability_pack_deployment_compilation_idx
    ON authority_capability_pack_deployment(compilation_id, binding_set_id)
    """,
    """
    CREATE INDEX authority_capability_pack_deployment_version_fk_idx
    ON authority_capability_pack_deployment(pack_id, pack_version)
    """,
    """
    CREATE INDEX authority_capability_pack_deployment_project_idx
    ON authority_capability_pack_deployment(project_id, workspace_id, book_id)
    WHERE project_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_capability_pack_deployment_operation_idx
    ON authority_capability_pack_deployment(created_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_activation (
        activation_key TEXT PRIMARY KEY,
        scope_key TEXT NOT NULL,
        target_scope_type TEXT NOT NULL,
        project_id TEXT REFERENCES authority_project(project_id),
        workspace_id TEXT,
        book_id TEXT,
        environment TEXT NOT NULL,
        workflow_definition_ref TEXT NOT NULL,
        pack_id TEXT NOT NULL REFERENCES authority_capability_pack(pack_id),
        active_deployment_id TEXT NOT NULL
            REFERENCES authority_capability_pack_deployment(deployment_id),
        activation_version BIGINT NOT NULL,
        reason TEXT NOT NULL,
        activated_by TEXT NOT NULL,
        activated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id)
            REFERENCES authority_workspace(project_id, workspace_id),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        UNIQUE(scope_key, environment, workflow_definition_ref, pack_id),
        CHECK (target_scope_type IN ('SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK')),
        CHECK (activation_version > 0),
        CHECK (reason <> '' AND activated_by <> ''),
        CHECK (scope_key ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_activation_deployment_idx
    ON authority_capability_pack_activation(active_deployment_id)
    """,
    """
    CREATE INDEX authority_capability_pack_activation_operation_idx
    ON authority_capability_pack_activation(activated_by_operation_id)
    """,
    """
    CREATE INDEX authority_capability_pack_activation_scope_fk_idx
    ON authority_capability_pack_activation(project_id, workspace_id, book_id)
    WHERE project_id IS NOT NULL
    """,
    """
    CREATE TABLE authority_capability_pack_rollout (
        rollout_id TEXT PRIMARY KEY,
        baseline_deployment_id TEXT NOT NULL
            REFERENCES authority_capability_pack_deployment(deployment_id),
        candidate_deployment_id TEXT NOT NULL
            REFERENCES authority_capability_pack_deployment(deployment_id),
        mode TEXT NOT NULL,
        percentage NUMERIC(5,2) NOT NULL,
        assignment_key_policy TEXT NOT NULL,
        status TEXT NOT NULL,
        started_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        paused_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (baseline_deployment_id <> candidate_deployment_id),
        CHECK (mode IN ('OFF', 'CANARY', 'PERCENTAGE', 'FULL')),
        CHECK (status IN (
            'OFF', 'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED', 'COMPLETED',
            'ROLLED_BACK'
        )),
        CHECK (percentage >= 0 AND percentage <= 100),
        CHECK (assignment_key_policy IN ('BOOK', 'PROJECT_WORKSPACE'))
    )
    """,
    """
    CREATE INDEX authority_capability_pack_rollout_deployments_idx
    ON authority_capability_pack_rollout(
        baseline_deployment_id, candidate_deployment_id, status
    )
    """,
    """
    CREATE INDEX authority_capability_pack_rollout_operation_idx
    ON authority_capability_pack_rollout(started_by_operation_id)
    """,
    """
    CREATE TABLE authority_capability_pack_assignment (
        assignment_id TEXT PRIMARY KEY,
        rollout_id TEXT NOT NULL
            REFERENCES authority_capability_pack_rollout(rollout_id),
        subject_key TEXT NOT NULL,
        bucket INTEGER NOT NULL,
        selected_deployment_id TEXT NOT NULL
            REFERENCES authority_capability_pack_deployment(deployment_id),
        assignment_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(rollout_id, subject_key),
        CHECK (subject_key <> ''),
        CHECK (bucket >= 0 AND bucket < 10000),
        CHECK (assignment_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_assignment_selected_idx
    ON authority_capability_pack_assignment(selected_deployment_id, created_at)
    """,
    """
    CREATE TABLE authority_capability_pack_deprecation (
        deprecation_id TEXT PRIMARY KEY,
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        replacement_pack_ref TEXT,
        deprecation_reason TEXT NOT NULL,
        retirement_deadline TIMESTAMPTZ,
        migration_required BOOLEAN NOT NULL DEFAULT FALSE,
        migration_policy_ref TEXT,
        retired BOOLEAN NOT NULL DEFAULT FALSE,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(pack_id, pack_version)
            REFERENCES authority_capability_pack_version(pack_id, pack_version),
        UNIQUE(pack_id, pack_version, deprecation_id),
        CHECK (deprecation_reason <> '')
    )
    """,
    """
    CREATE INDEX authority_capability_pack_deprecation_version_idx
    ON authority_capability_pack_deprecation(pack_id, pack_version, created_at DESC)
    """,
    """
    CREATE INDEX authority_capability_pack_deprecation_operation_idx
    ON authority_capability_pack_deprecation(created_by_operation_id)
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_deployment_id TEXT
        REFERENCES authority_capability_pack_deployment(deployment_id)
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_activation_version BIGINT
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_binding_set_id TEXT
        REFERENCES authority_capability_pack_binding_set(binding_set_id)
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_binding_set_hash TEXT
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_scope_type TEXT
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_assignment_ref TEXT
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ALTER COLUMN chapter_node_binding_id DROP NOT NULL,
    ALTER COLUMN chapter_node_binding_version DROP NOT NULL
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD CONSTRAINT authority_agent_runtime_pack_snapshot_check CHECK (
        (capability_pack_deployment_id IS NULL
         AND capability_pack_activation_version IS NULL
         AND capability_pack_binding_set_id IS NULL
         AND capability_pack_binding_set_hash IS NULL
         AND capability_pack_scope_type IS NULL
         AND capability_pack_assignment_ref IS NULL)
        OR
        (capability_pack_deployment_id IS NOT NULL
         AND capability_pack_activation_version > 0
         AND capability_pack_binding_set_id IS NOT NULL
         AND capability_pack_binding_set_hash ~ '^sha256:[0-9a-f]{64}$'
         AND capability_pack_scope_type IN ('SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK')
         AND capability_pack_assignment_ref IS NOT NULL)
    )
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD CONSTRAINT authority_agent_runtime_binding_source_check CHECK (
        (capability_pack_deployment_id IS NULL
         AND chapter_node_binding_id IS NOT NULL
         AND chapter_node_binding_version IS NOT NULL)
        OR
        (capability_pack_deployment_id IS NOT NULL
         AND chapter_node_binding_id IS NULL
         AND chapter_node_binding_version IS NULL)
    )
    """,
    """
    CREATE INDEX authority_agent_runtime_pack_deployment_idx
    ON authority_agent_runtime_binding(
        capability_pack_deployment_id, created_at DESC
    ) WHERE capability_pack_deployment_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_agent_runtime_pack_binding_set_idx
    ON authority_agent_runtime_binding(capability_pack_binding_set_id)
    WHERE capability_pack_binding_set_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_agent_runtime_chapter_binding_full_fk_idx
    ON authority_agent_runtime_binding(
        workflow_definition_ref, workflow_node_id,
        chapter_node_binding_id, chapter_node_binding_version
    ) WHERE chapter_node_binding_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_chapter_agent_binding_definition_fk_idx
    ON authority_chapter_node_agent_binding(
        agent_id, agent_definition_version, capability_id, capability_version
    )
    """,
    """
    CREATE INDEX authority_chapter_agent_activation_binding_full_fk_idx
    ON authority_chapter_node_agent_binding_activation(
        workflow_definition_ref, workflow_node_id,
        binding_id, binding_version
    )
    """,
    """
    CREATE INDEX authority_agent_collaboration_session_saga_fk_idx
    ON authority_agent_collaboration_session(saga_id)
    """,
    """
    CREATE INDEX authority_execution_recovery_external_effect_fk_idx
    ON authority_execution_recovery_authorization(external_effect_id)
    """,
    """
    CREATE INDEX authority_execution_recovery_execution_fence_fk_idx
    ON authority_execution_recovery_authorization(
        attempt_id, execution_fencing_token
    )
    """,
    """
    CREATE INDEX authority_execution_recovery_recovery_fence_fk_idx
    ON authority_execution_recovery_authorization(
        attempt_id, recovery_fencing_token
    )
    """,
    """
    CREATE INDEX authority_agent_candidate_superseded_attempt_fk_idx
    ON authority_agent_candidate_supersession(superseded_attempt_id)
    """,
    """
    CREATE INDEX authority_agent_candidate_superseding_fence_fk_idx
    ON authority_agent_candidate_supersession(
        superseding_attempt_id, recovery_fencing_token
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_immutable_guard()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Capability Pack historical fact is immutable'
            USING ERRCODE='23514',
                  CONSTRAINT='authority_capability_pack_immutable';
    END;
    $$ LANGUAGE plpgsql
    """,
    *[
        f"""
        CREATE TRIGGER {table}_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()
        """
        for table in (
            "authority_capability_pack",
            "authority_capability_pack_version",
            "authority_capability_pack_validation",
            "authority_capability_pack_compilation",
            "authority_capability_pack_approval",
            "authority_capability_pack_binding_set",
            "authority_capability_pack_assignment",
            "authority_capability_pack_deprecation",
        )
    ],
]


DOWNGRADE_STATEMENTS: list[str] = []
