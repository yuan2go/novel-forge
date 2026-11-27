from __future__ import annotations


MIGRATION_ID = "20260806_0072_capability_pack_integrity_hardening"
DOWN_REVISION = "20260805_0071_capability_pack_authority"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Preserve immutable Pack, Assignment, Attempt Snapshot, and Runtime Binding "
    "facts. Register corrected successor versions or approvals, and move only "
    "the CAS activation pointer through a new Command Kernel operation."
)


UPGRADE_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "DROP TRIGGER authority_capability_pack_immutable ON authority_capability_pack",
    "DROP TRIGGER authority_capability_pack_approval_immutable ON authority_capability_pack_approval",
    """
    ALTER TABLE authority_capability_pack
    ADD COLUMN owner_scope_type TEXT,
    ADD COLUMN owner_project_id TEXT REFERENCES authority_project(project_id)
    """,
    """
    UPDATE authority_capability_pack AS pack
    SET owner_scope_type='PROJECT', owner_project_id=owner.project_id
    FROM (
        SELECT DISTINCT version.pack_id, asset.project_id
        FROM authority_capability_pack_version AS version
        JOIN authority_asset_version AS asset_version
          ON asset_version.asset_version_id=version.manifest_asset_version_id
        JOIN authority_asset AS asset ON asset.asset_id=asset_version.asset_id
    ) AS owner
    WHERE owner.pack_id=pack.pack_id
    """,
    """
    ALTER TABLE authority_capability_pack
    ALTER COLUMN owner_scope_type SET NOT NULL,
    ADD CONSTRAINT authority_capability_pack_owner_scope_check CHECK (
        (owner_scope_type='SYSTEM' AND owner_project_id IS NULL)
        OR (owner_scope_type='PROJECT' AND owner_project_id IS NOT NULL)
    )
    """,
    """
    CREATE INDEX authority_capability_pack_owner_idx
    ON authority_capability_pack(owner_scope_type, owner_project_id, pack_id)
    """,
    """
    ALTER TABLE authority_capability_pack_approval
    ADD COLUMN approval_scope_v1 JSONB,
    ADD COLUMN structured_limitations JSONB
    """,
    """
    UPDATE authority_capability_pack_approval AS approval
    SET approval_scope_v1=jsonb_build_object(
            'schema_version', 'CapabilityPackApprovalScope.v1',
            'allowed_environments',
                CASE
                    WHEN jsonb_typeof(approval.approval_scope->'allowed_environments')='array'
                    THEN approval.approval_scope->'allowed_environments'
                    WHEN COALESCE(approval.approval_scope->>'environment', '')<>''
                    THEN jsonb_build_array(approval.approval_scope->>'environment')
                    ELSE jsonb_build_array(compilation.runtime_profile)
                END,
            'allowed_runtime_profiles', jsonb_build_array(compilation.runtime_profile),
            'allowed_release_channels', jsonb_build_array(compilation.release_channel),
            'allowed_scope_types', jsonb_build_array(
                'SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK'
            ),
            'allowed_project_ids', jsonb_build_array(owner.project_id),
            'allowed_workspace_ids', '[]'::jsonb,
            'allowed_book_ids', '[]'::jsonb,
            'allowed_workflow_definition_refs', jsonb_build_array(
                CONCAT(
                    manifest.content->'workflow_template'->>'workflow_id',
                    '@',
                    manifest.content->'workflow_template'->>'workflow_version'
                )
            ),
            'allow_canary', TRUE,
            'allow_percentage_rollout', TRUE,
            'allow_full_rollout', TRUE,
            'maximum_rollout_percentage', 100
        ),
        structured_limitations='[]'::jsonb
    FROM authority_capability_pack_compilation AS compilation
    JOIN authority_capability_pack_version AS pack_version
      ON pack_version.pack_id=compilation.pack_id
     AND pack_version.pack_version=compilation.pack_version
    JOIN authority_asset_version AS manifest
      ON manifest.asset_version_id=pack_version.manifest_asset_version_id
    JOIN authority_asset_version AS compiled_asset
      ON compiled_asset.asset_version_id=compilation.compiled_asset_version_id
    JOIN authority_asset AS owner ON owner.asset_id=compiled_asset.asset_id
    WHERE compilation.compilation_id=approval.compilation_id
    """,
    """
    ALTER TABLE authority_capability_pack_approval
    ALTER COLUMN approval_scope_v1 SET NOT NULL,
    ALTER COLUMN structured_limitations SET NOT NULL
    """,
    """
    ALTER TABLE authority_capability_pack_compilation
    ADD CONSTRAINT authority_capability_pack_compilation_exact_unique
        UNIQUE(compilation_id, compilation_hash),
    ADD CONSTRAINT authority_capability_pack_compilation_pack_unique
        UNIQUE(compilation_id, pack_id, pack_version)
    """,
    """
    ALTER TABLE authority_capability_pack_approval
    ADD CONSTRAINT authority_capability_pack_approval_exact_compilation_fk
        FOREIGN KEY(compilation_id, compilation_hash)
        REFERENCES authority_capability_pack_compilation(
            compilation_id, compilation_hash
        )
    """,
    """
    ALTER TABLE authority_capability_pack_binding_set
    ADD CONSTRAINT authority_capability_pack_binding_exact_unique
        UNIQUE(binding_set_id, binding_set_hash),
    ADD CONSTRAINT authority_capability_pack_binding_compilation_unique
        UNIQUE(binding_set_id, compilation_id, workflow_definition_ref)
    """,
    """
    ALTER TABLE authority_capability_pack_deployment
    ADD CONSTRAINT authority_capability_pack_deployment_compilation_chain_fk
        FOREIGN KEY(compilation_id, pack_id, pack_version)
        REFERENCES authority_capability_pack_compilation(
            compilation_id, pack_id, pack_version
        ),
    ADD CONSTRAINT authority_capability_pack_deployment_binding_chain_fk
        FOREIGN KEY(binding_set_id, compilation_id, workflow_definition_ref)
        REFERENCES authority_capability_pack_binding_set(
            binding_set_id, compilation_id, workflow_definition_ref
        )
    """,
    """
    ALTER TABLE authority_capability_pack_assignment
    ADD CONSTRAINT authority_capability_pack_assignment_rollout_unique
        UNIQUE(rollout_id, assignment_id)
    """,
    """
    CREATE UNIQUE INDEX authority_capability_pack_one_open_rollout
    ON authority_capability_pack_rollout(baseline_deployment_id)
    WHERE status IN ('OFF', 'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED')
    """,
    """
    CREATE TABLE authority_capability_pack_dependency (
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        dependency_pack_id TEXT NOT NULL,
        dependency_pack_version TEXT NOT NULL,
        dependency_manifest_hash TEXT NOT NULL,
        dependency_type TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(pack_id, pack_version, dependency_pack_id),
        FOREIGN KEY(pack_id, pack_version)
            REFERENCES authority_capability_pack_version(pack_id, pack_version),
        FOREIGN KEY(
            dependency_pack_id, dependency_pack_version,
            dependency_manifest_hash
        ) REFERENCES authority_capability_pack_version(
            pack_id, pack_version, manifest_hash
        ),
        CHECK (pack_id<>dependency_pack_id),
        CHECK (dependency_type IN ('REQUIRED', 'OPTIONAL')),
        CHECK (dependency_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (
            dependency_pack_version !~* '(latest|snapshot|[*xX^~<>])'
        )
    )
    """,
    """
    CREATE INDEX authority_capability_pack_dependency_reverse_idx
    ON authority_capability_pack_dependency(
        dependency_pack_id, dependency_pack_version, pack_id, pack_version
    )
    """,
    """
    CREATE TABLE authority_attempt_capability_pack_snapshot (
        snapshot_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL UNIQUE REFERENCES authority_attempt(attempt_id),
        execution_fencing_token BIGINT NOT NULL,
        snapshot_creation_fencing_token BIGINT NOT NULL,
        deployment_id TEXT NOT NULL
            REFERENCES authority_capability_pack_deployment(deployment_id),
        activation_version BIGINT NOT NULL,
        pack_id TEXT NOT NULL,
        pack_version TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        compilation_id TEXT NOT NULL,
        compilation_hash TEXT NOT NULL,
        catalog_snapshot_hash TEXT NOT NULL,
        binding_set_id TEXT NOT NULL,
        binding_set_hash TEXT NOT NULL,
        selected_scope_type TEXT NOT NULL,
        rollout_id TEXT REFERENCES authority_capability_pack_rollout(rollout_id),
        assignment_id TEXT,
        assignment_ref TEXT NOT NULL,
        workflow_node_id TEXT NOT NULL,
        operation_definition_ref TEXT NOT NULL,
        agent_definition_ref TEXT NOT NULL,
        release_sha TEXT NOT NULL,
        snapshot_payload JSONB NOT NULL,
        snapshot_hash TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        span_id TEXT NOT NULL,
        resolution_count SMALLINT NOT NULL DEFAULT 1,
        created_by_worker_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(snapshot_id, snapshot_hash),
        FOREIGN KEY(attempt_id, execution_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        FOREIGN KEY(attempt_id, snapshot_creation_fencing_token)
            REFERENCES authority_lease_acquisition(attempt_id, fencing_token),
        FOREIGN KEY(compilation_id, compilation_hash)
            REFERENCES authority_capability_pack_compilation(
                compilation_id, compilation_hash
            ),
        FOREIGN KEY(binding_set_id, binding_set_hash)
            REFERENCES authority_capability_pack_binding_set(
                binding_set_id, binding_set_hash
            ),
        FOREIGN KEY(rollout_id, assignment_id)
            REFERENCES authority_capability_pack_assignment(
                rollout_id, assignment_id
            ),
        CHECK (
            execution_fencing_token>0
            AND snapshot_creation_fencing_token>0
            AND activation_version>0
        ),
        CHECK (selected_scope_type IN ('SYSTEM', 'PROJECT', 'WORKSPACE', 'BOOK')),
        CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (compilation_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (catalog_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (binding_set_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (resolution_count=1),
        CHECK (release_sha ~ '^[0-9a-f]{40,64}$'),
        CHECK (assignment_ref<>'' AND workflow_node_id<>''),
        CHECK (operation_definition_ref<>'' AND agent_definition_ref<>''),
        CHECK (created_by_worker_id<>'' AND trace_id<>'' AND span_id<>'')
    )
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_deployment_idx
    ON authority_attempt_capability_pack_snapshot(
        deployment_id, pack_id, pack_version, created_at
    )
    """,
    """
    CREATE INDEX authority_pack_deployment_compilation_chain_idx
    ON authority_capability_pack_deployment(
        compilation_id, pack_id, pack_version
    )
    """,
    """
    CREATE INDEX authority_pack_deployment_binding_chain_idx
    ON authority_capability_pack_deployment(
        binding_set_id, compilation_id, workflow_definition_ref
    )
    """,
    """
    CREATE INDEX authority_pack_dependency_target_idx
    ON authority_capability_pack_dependency(
        dependency_pack_id, dependency_pack_version, dependency_manifest_hash
    )
    """,
    """
    CREATE INDEX authority_pack_dependency_operation_idx
    ON authority_capability_pack_dependency(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_operation_idx
    ON authority_attempt_capability_pack_snapshot(operation_id)
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_fence_idx
    ON authority_attempt_capability_pack_snapshot(
        attempt_id, execution_fencing_token
    )
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_creation_fence_idx
    ON authority_attempt_capability_pack_snapshot(
        attempt_id, snapshot_creation_fencing_token
    )
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_compilation_idx
    ON authority_attempt_capability_pack_snapshot(
        compilation_id, compilation_hash
    )
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_binding_idx
    ON authority_attempt_capability_pack_snapshot(binding_set_id, binding_set_hash)
    """,
    """
    CREATE INDEX authority_attempt_pack_snapshot_assignment_idx
    ON authority_attempt_capability_pack_snapshot(rollout_id, assignment_id)
    """,
    """
    ALTER TABLE authority_agent_runtime_binding
    ADD COLUMN capability_pack_attempt_snapshot_id TEXT,
    ADD COLUMN capability_pack_attempt_snapshot_hash TEXT,
    ADD CONSTRAINT authority_agent_runtime_pack_attempt_snapshot_fk
        FOREIGN KEY(
            capability_pack_attempt_snapshot_id,
            capability_pack_attempt_snapshot_hash
        ) REFERENCES authority_attempt_capability_pack_snapshot(
            snapshot_id, snapshot_hash
        )
    """,
    """
    CREATE INDEX authority_agent_runtime_pack_attempt_snapshot_idx
    ON authority_agent_runtime_binding(
        capability_pack_attempt_snapshot_id,
        capability_pack_attempt_snapshot_hash
    )
    """,
    """
    CREATE OR REPLACE FUNCTION authority_canonical_jsonb(value JSONB)
    RETURNS TEXT AS $$
    DECLARE result TEXT;
    BEGIN
        CASE jsonb_typeof(value)
        WHEN 'object' THEN
            SELECT '{' || COALESCE(string_agg(
                to_jsonb(entry.key)::TEXT || ':' ||
                authority_canonical_jsonb(entry.value),
                ',' ORDER BY entry.key
            ), '') || '}'
            INTO result FROM jsonb_each(value) AS entry;
        WHEN 'array' THEN
            SELECT '[' || COALESCE(string_agg(
                authority_canonical_jsonb(entry.value),
                ',' ORDER BY entry.ordinality
            ), '') || ']'
            INTO result
            FROM jsonb_array_elements(value) WITH ORDINALITY AS entry(value, ordinality);
        ELSE
            result := value::TEXT;
        END CASE;
        RETURN result;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE STRICT
    """,
    """
    CREATE OR REPLACE FUNCTION authority_sha256_jsonb(value JSONB)
    RETURNS TEXT AS $$
        SELECT 'sha256:' || encode(
            digest(convert_to(authority_canonical_jsonb(value), 'UTF8'), 'sha256'),
            'hex'
        )
    $$ LANGUAGE sql IMMUTABLE STRICT
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_bucket(
        p_rollout_id TEXT, p_subject_key TEXT
    ) RETURNS INTEGER AS $$
        SELECT MOD(SUM(
            get_byte(digest(convert_to(p_rollout_id || chr(31) || p_subject_key, 'UTF8'), 'sha256'), index)
            * power(256::NUMERIC, 7-index)
        ), 10000)::INTEGER
        FROM generate_series(0, 7) AS index
    $$ LANGUAGE sql IMMUTABLE STRICT
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_approval_policy_guard()
    RETURNS TRIGGER AS $$
    DECLARE key_name TEXT; item JSONB;
    BEGIN
        IF jsonb_typeof(NEW.approval_scope_v1)<>'object'
           OR NEW.approval_scope_v1->>'schema_version'
                <>'CapabilityPackApprovalScope.v1'
           OR NOT (NEW.approval_scope_v1 ?& ARRAY[
                'schema_version', 'allowed_environments',
                'allowed_runtime_profiles', 'allowed_release_channels',
                'allowed_scope_types', 'allowed_project_ids',
                'allowed_workspace_ids', 'allowed_book_ids',
                'allowed_workflow_definition_refs', 'allow_canary',
                'allow_percentage_rollout', 'allow_full_rollout',
                'maximum_rollout_percentage'
           ]) THEN
            RAISE EXCEPTION 'Approval Scope v1 is incomplete'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_approval_scope_v1';
        END IF;
        FOR key_name IN SELECT jsonb_object_keys(NEW.approval_scope_v1) LOOP
            IF key_name <> ALL(ARRAY[
                'schema_version', 'allowed_environments',
                'allowed_runtime_profiles', 'allowed_release_channels',
                'allowed_scope_types', 'allowed_project_ids',
                'allowed_workspace_ids', 'allowed_book_ids',
                'allowed_workflow_definition_refs', 'allow_canary',
                'allow_percentage_rollout', 'allow_full_rollout',
                'maximum_rollout_percentage'
            ]) THEN
                RAISE EXCEPTION 'Approval Scope v1 contains unknown key %', key_name
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_capability_pack_approval_scope_v1';
            END IF;
        END LOOP;
        FOREACH key_name IN ARRAY ARRAY[
            'allowed_environments', 'allowed_runtime_profiles',
            'allowed_release_channels', 'allowed_scope_types',
            'allowed_project_ids', 'allowed_workspace_ids',
            'allowed_book_ids', 'allowed_workflow_definition_refs'
        ] LOOP
            IF jsonb_typeof(NEW.approval_scope_v1->key_name)<>'array' THEN
                RAISE EXCEPTION 'Approval Scope % must be an array', key_name
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_capability_pack_approval_scope_v1';
            END IF;
        END LOOP;
        IF jsonb_typeof(NEW.approval_scope_v1->'allow_canary')<>'boolean'
           OR jsonb_typeof(NEW.approval_scope_v1->'allow_percentage_rollout')<>'boolean'
           OR jsonb_typeof(NEW.approval_scope_v1->'allow_full_rollout')<>'boolean'
           OR jsonb_typeof(NEW.approval_scope_v1->'maximum_rollout_percentage')<>'number'
           OR (NEW.approval_scope_v1->>'maximum_rollout_percentage')::NUMERIC NOT BETWEEN 0 AND 100
           OR jsonb_typeof(NEW.structured_limitations)<>'array' THEN
            RAISE EXCEPTION 'Approval policy v1 value types are invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_approval_scope_v1';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(NEW.structured_limitations) LOOP
            IF jsonb_typeof(item)<>'object'
               OR NOT (item ?& ARRAY['limitation_type', 'code', 'value', 'message'])
               OR (SELECT COUNT(*) FROM jsonb_object_keys(item))<>4
               OR item->>'limitation_type' NOT IN (
                    'INFORMATIONAL', 'ADMISSION_CONSTRAINT',
                    'ROLLOUT_CONSTRAINT', 'EXPIRY_CONSTRAINT'
               )
               OR COALESCE(item->>'code', '')=''
               OR COALESCE(item->>'message', '')='' THEN
                RAISE EXCEPTION 'structured limitation v1 is invalid'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_capability_pack_limitation_v1';
            END IF;
        END LOOP;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_approval_policy_fact_guard
    AFTER INSERT ON authority_capability_pack_approval
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_approval_policy_guard()
    """,
    """
    CREATE TRIGGER authority_capability_pack_immutable
    BEFORE UPDATE OR DELETE ON authority_capability_pack
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()
    """,
    """
    CREATE TRIGGER authority_capability_pack_approval_immutable
    BEFORE UPDATE OR DELETE ON authority_capability_pack_approval
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_binding_hash_guard()
    RETURNS TRIGGER AS $$
    DECLARE compilation RECORD; expected_hash TEXT;
    BEGIN
        SELECT pack_id, pack_version, compilation_hash INTO compilation
        FROM authority_capability_pack_compilation
        WHERE compilation_id=NEW.compilation_id;
        expected_hash := authority_sha256_jsonb(jsonb_build_object(
            'schema_version', 'novelos.capability_pack.binding_set.v1',
            'pack_id', compilation.pack_id,
            'pack_version', compilation.pack_version,
            'compilation_hash', compilation.compilation_hash,
            'workflow_definition_ref', NEW.workflow_definition_ref,
            'node_bindings', NEW.node_bindings,
            'artifact_bindings', NEW.artifact_bindings,
            'policy_bindings', NEW.policy_bindings
        ));
        IF NEW.binding_set_hash IS DISTINCT FROM expected_hash THEN
            RAISE EXCEPTION 'Binding Set hash differs from exact content'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_binding_set_hash';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_binding_hash_fact_guard
    AFTER INSERT ON authority_capability_pack_binding_set
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_binding_hash_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_deployment_guard()
    RETURNS TRIGGER AS $$
    DECLARE compilation RECORD; binding RECORD; owner RECORD;
    BEGIN
        SELECT pack_id, pack_version INTO compilation
        FROM authority_capability_pack_compilation
        WHERE compilation_id=NEW.compilation_id;
        SELECT compilation_id, workflow_definition_ref INTO binding
        FROM authority_capability_pack_binding_set
        WHERE binding_set_id=NEW.binding_set_id;
        SELECT owner_scope_type, owner_project_id INTO owner
        FROM authority_capability_pack WHERE pack_id=NEW.pack_id;
        IF compilation.pack_id IS DISTINCT FROM NEW.pack_id
           OR compilation.pack_version IS DISTINCT FROM NEW.pack_version
           OR binding.compilation_id IS DISTINCT FROM NEW.compilation_id
           OR binding.workflow_definition_ref IS DISTINCT FROM NEW.workflow_definition_ref
           OR (NEW.target_scope_type='SYSTEM' AND owner.owner_scope_type<>'SYSTEM')
           OR (owner.owner_scope_type='PROJECT' AND (
                NEW.project_id IS DISTINCT FROM owner.owner_project_id
                OR NEW.target_scope_type='SYSTEM'
           )) THEN
            RAISE EXCEPTION 'Deployment does not belong to one authoritative Pack chain'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_deployment_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_deployment_fact_guard
    AFTER INSERT OR UPDATE ON authority_capability_pack_deployment
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_deployment_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_activation_guard()
    RETURNS TRIGGER AS $$
    DECLARE deployment RECORD; expected_scope_key TEXT; expected_activation_key TEXT;
    BEGIN
        SELECT * INTO deployment FROM authority_capability_pack_deployment
        WHERE deployment_id=NEW.active_deployment_id;
        expected_scope_key := authority_sha256_jsonb(jsonb_build_object(
            'scope_type', NEW.target_scope_type,
            'project_id', COALESCE(NEW.project_id, ''),
            'workspace_id', COALESCE(NEW.workspace_id, ''),
            'book_id', COALESCE(NEW.book_id, '')
        ));
        expected_activation_key := authority_sha256_jsonb(jsonb_build_object(
            'scope_key', NEW.scope_key,
            'environment', NEW.environment,
            'workflow_definition_ref', NEW.workflow_definition_ref,
            'pack_id', NEW.pack_id
        ));
        IF deployment.deployment_id IS NULL
           OR NEW.scope_key IS DISTINCT FROM expected_scope_key
           OR NEW.activation_key IS DISTINCT FROM expected_activation_key
           OR deployment.scope_key IS DISTINCT FROM NEW.scope_key
           OR deployment.target_scope_type IS DISTINCT FROM NEW.target_scope_type
           OR deployment.project_id IS DISTINCT FROM NEW.project_id
           OR deployment.workspace_id IS DISTINCT FROM NEW.workspace_id
           OR deployment.book_id IS DISTINCT FROM NEW.book_id
           OR deployment.environment IS DISTINCT FROM NEW.environment
           OR deployment.workflow_definition_ref IS DISTINCT FROM NEW.workflow_definition_ref
           OR deployment.pack_id IS DISTINCT FROM NEW.pack_id
           OR deployment.deployment_status IN ('DISABLED', 'RETIRED', 'ROLLBACK_REQUIRED')
           OR EXISTS (
                SELECT 1 FROM authority_capability_pack_rollout AS rollout
                WHERE rollout.baseline_deployment_id<>
                        NEW.active_deployment_id
                  AND rollout.baseline_deployment_id IN (
                        SELECT sibling.deployment_id
                        FROM authority_capability_pack_deployment AS sibling
                        WHERE sibling.scope_key=NEW.scope_key
                          AND sibling.environment=NEW.environment
                          AND sibling.workflow_definition_ref=
                                NEW.workflow_definition_ref
                          AND sibling.pack_id=NEW.pack_id
                  )
                  AND rollout.status IN (
                        'OFF', 'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED'
                  )
           ) THEN
            RAISE EXCEPTION 'Activation pointer differs from Deployment identity'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_activation_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_activation_fact_guard
    AFTER INSERT OR UPDATE ON authority_capability_pack_activation
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_activation_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_rollout_guard()
    RETURNS TRIGGER AS $$
    DECLARE baseline RECORD; candidate RECORD; active_deployment TEXT;
    BEGIN
        SELECT * INTO baseline FROM authority_capability_pack_deployment
        WHERE deployment_id=NEW.baseline_deployment_id;
        SELECT * INTO candidate FROM authority_capability_pack_deployment
        WHERE deployment_id=NEW.candidate_deployment_id;
        SELECT activation.active_deployment_id INTO active_deployment
        FROM authority_capability_pack_activation AS activation
        WHERE activation.scope_key=baseline.scope_key
          AND activation.environment=baseline.environment
          AND activation.workflow_definition_ref=baseline.workflow_definition_ref
          AND activation.pack_id=baseline.pack_id;
        IF baseline.scope_key IS DISTINCT FROM candidate.scope_key
           OR baseline.target_scope_type IS DISTINCT FROM candidate.target_scope_type
           OR baseline.project_id IS DISTINCT FROM candidate.project_id
           OR baseline.workspace_id IS DISTINCT FROM candidate.workspace_id
           OR baseline.book_id IS DISTINCT FROM candidate.book_id
           OR baseline.environment IS DISTINCT FROM candidate.environment
           OR baseline.workflow_definition_ref IS DISTINCT FROM candidate.workflow_definition_ref
           OR baseline.pack_id IS DISTINCT FROM candidate.pack_id
           OR (NEW.status IN ('OFF', 'CANARY', 'PERCENTAGE', 'FULL', 'PAUSED')
               AND active_deployment IS DISTINCT FROM NEW.baseline_deployment_id)
           OR (NEW.status='COMPLETED'
               AND active_deployment IS DISTINCT FROM NEW.candidate_deployment_id)
           OR (NEW.status='ROLLED_BACK'
               AND active_deployment IS DISTINCT FROM NEW.baseline_deployment_id) THEN
            RAISE EXCEPTION 'Rollout Deployment or Activation identity is invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_rollout_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_rollout_fact_guard
    AFTER INSERT OR UPDATE ON authority_capability_pack_rollout
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_rollout_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_assignment_guard()
    RETURNS TRIGGER AS $$
    DECLARE rollout RECORD; expected_hash TEXT; expected_bucket INTEGER;
    BEGIN
        SELECT * INTO rollout FROM authority_capability_pack_rollout
        WHERE rollout_id=NEW.rollout_id;
        expected_bucket := authority_capability_pack_bucket(
            NEW.rollout_id, NEW.subject_key
        );
        expected_hash := authority_sha256_jsonb(jsonb_build_object(
            'assignment_id', NEW.assignment_id,
            'bucket', NEW.bucket,
            'rollout_id', NEW.rollout_id,
            'selected_deployment_id', NEW.selected_deployment_id,
            'subject_key', NEW.subject_key
        ));
        IF NEW.selected_deployment_id NOT IN (
                rollout.baseline_deployment_id,
                rollout.candidate_deployment_id
           )
           OR NEW.bucket IS DISTINCT FROM expected_bucket
           OR NEW.assignment_hash IS DISTINCT FROM expected_hash THEN
            RAISE EXCEPTION 'Canary Assignment immutable facts are invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_assignment_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_assignment_fact_guard
    AFTER INSERT ON authority_capability_pack_assignment
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_assignment_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_capability_pack_dependency_guard()
    RETURNS TRIGGER AS $$
    DECLARE owner RECORD; dependency_owner RECORD;
    BEGIN
        SELECT owner_scope_type, owner_project_id INTO owner
        FROM authority_capability_pack WHERE pack_id=NEW.pack_id;
        SELECT owner_scope_type, owner_project_id INTO dependency_owner
        FROM authority_capability_pack WHERE pack_id=NEW.dependency_pack_id;
        IF (owner.owner_scope_type='SYSTEM'
            AND dependency_owner.owner_scope_type<>'SYSTEM')
           OR (owner.owner_scope_type='PROJECT'
               AND dependency_owner.owner_scope_type='PROJECT'
               AND dependency_owner.owner_project_id
                    IS DISTINCT FROM owner.owner_project_id)
           OR EXISTS (
                WITH RECURSIVE graph(pack_id, pack_version) AS (
                    SELECT NEW.dependency_pack_id, NEW.dependency_pack_version
                    UNION
                    SELECT dependency.dependency_pack_id,
                           dependency.dependency_pack_version
                    FROM authority_capability_pack_dependency AS dependency
                    JOIN graph ON graph.pack_id=dependency.pack_id
                              AND graph.pack_version=dependency.pack_version
                )
                SELECT 1 FROM graph
                WHERE pack_id=NEW.pack_id AND pack_version=NEW.pack_version
           ) THEN
            RAISE EXCEPTION 'Pack Dependency namespace or graph is invalid'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_capability_pack_dependency_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_capability_pack_dependency_fact_guard
    AFTER INSERT ON authority_capability_pack_dependency
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_dependency_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_attempt_capability_pack_snapshot_guard()
    RETURNS TRIGGER AS $$
    DECLARE attempt_operation TEXT; attempt_trace TEXT; attempt_span TEXT;
            current_fence BIGINT; deployment_fact RECORD;
            assignment_identity TEXT; assignment_deployment TEXT;
            expected_hash TEXT;
    BEGIN
        SELECT attempt.operation_id, operation.trace_id, operation.span_id
        INTO attempt_operation, attempt_trace, attempt_span
        FROM authority_attempt AS attempt
        JOIN authority_operation AS operation
          ON operation.operation_id=attempt.operation_id
        WHERE attempt.attempt_id=NEW.attempt_id;
        SELECT fencing_token INTO current_fence
        FROM authority_lease_acquisition
        WHERE attempt_id=NEW.attempt_id
          AND fencing_token=NEW.snapshot_creation_fencing_token
          AND status='HELD' AND expires_at>NOW();
        SELECT deployment.*, compilation.compilation_hash,
               compilation.manifest_hash, compilation.catalog_snapshot_hash,
               binding_set.binding_set_hash
        INTO deployment_fact
        FROM authority_capability_pack_deployment AS deployment
        JOIN authority_capability_pack_compilation AS compilation
          ON compilation.compilation_id=deployment.compilation_id
        JOIN authority_capability_pack_binding_set AS binding_set
          ON binding_set.binding_set_id=deployment.binding_set_id
        WHERE deployment.deployment_id=NEW.deployment_id;
        IF NEW.assignment_id IS NOT NULL THEN
            SELECT assignment_id, selected_deployment_id
            INTO assignment_identity, assignment_deployment
            FROM authority_capability_pack_assignment
            WHERE rollout_id=NEW.rollout_id AND assignment_id=NEW.assignment_id;
        END IF;
        expected_hash := authority_sha256_jsonb(NEW.snapshot_payload);
        IF attempt_operation IS DISTINCT FROM NEW.operation_id
           OR attempt_trace IS DISTINCT FROM NEW.trace_id
           OR attempt_span IS DISTINCT FROM NEW.span_id
           OR current_fence IS DISTINCT FROM NEW.snapshot_creation_fencing_token
           OR NEW.snapshot_hash IS DISTINCT FROM expected_hash
           OR deployment_fact.pack_id IS DISTINCT FROM NEW.pack_id
           OR deployment_fact.pack_version IS DISTINCT FROM NEW.pack_version
           OR deployment_fact.manifest_hash IS DISTINCT FROM NEW.manifest_hash
           OR deployment_fact.compilation_id IS DISTINCT FROM NEW.compilation_id
           OR deployment_fact.compilation_hash IS DISTINCT FROM NEW.compilation_hash
           OR deployment_fact.catalog_snapshot_hash IS DISTINCT FROM NEW.catalog_snapshot_hash
           OR deployment_fact.binding_set_id IS DISTINCT FROM NEW.binding_set_id
           OR deployment_fact.binding_set_hash IS DISTINCT FROM NEW.binding_set_hash
           OR NEW.snapshot_payload->>'deployment_id' IS DISTINCT FROM NEW.deployment_id
           OR (NEW.snapshot_payload->>'activation_version')::BIGINT
                IS DISTINCT FROM NEW.activation_version
           OR NEW.snapshot_payload->>'pack_id' IS DISTINCT FROM NEW.pack_id
           OR NEW.snapshot_payload->>'pack_version' IS DISTINCT FROM NEW.pack_version
           OR NEW.snapshot_payload->>'manifest_hash' IS DISTINCT FROM NEW.manifest_hash
           OR NEW.snapshot_payload->>'compilation_id' IS DISTINCT FROM NEW.compilation_id
           OR NEW.snapshot_payload->>'compilation_hash' IS DISTINCT FROM NEW.compilation_hash
           OR NEW.snapshot_payload->>'catalog_snapshot_hash'
                IS DISTINCT FROM NEW.catalog_snapshot_hash
           OR NEW.snapshot_payload->>'binding_set_id' IS DISTINCT FROM NEW.binding_set_id
           OR NEW.snapshot_payload->>'binding_set_hash' IS DISTINCT FROM NEW.binding_set_hash
           OR NEW.snapshot_payload->>'selected_scope_type'
                IS DISTINCT FROM NEW.selected_scope_type
           OR NEW.snapshot_payload->>'rollout_id' IS DISTINCT FROM COALESCE(NEW.rollout_id, '')
           OR NEW.snapshot_payload->>'assignment_ref' IS DISTINCT FROM NEW.assignment_ref
           OR NEW.snapshot_payload->>'workflow_node_id' IS DISTINCT FROM NEW.workflow_node_id
           OR NEW.snapshot_payload->>'operation_definition_ref'
                IS DISTINCT FROM NEW.operation_definition_ref
           OR NEW.snapshot_payload->>'agent_definition_ref'
                IS DISTINCT FROM NEW.agent_definition_ref
           OR NEW.snapshot_payload->>'release_sha' IS DISTINCT FROM NEW.release_sha
           OR (NEW.assignment_id IS NOT NULL AND (
                assignment_identity IS NULL
                OR NEW.assignment_ref IS DISTINCT FROM NEW.assignment_id
                OR assignment_deployment IS DISTINCT FROM NEW.deployment_id
           )) THEN
            RAISE EXCEPTION 'Attempt Pack Snapshot differs from Authority facts'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_attempt_capability_pack_snapshot_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_attempt_capability_pack_snapshot_fact_guard
    AFTER INSERT ON authority_attempt_capability_pack_snapshot
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_attempt_capability_pack_snapshot_guard()
    """,
    """
    CREATE TRIGGER authority_attempt_capability_pack_snapshot_immutable
    BEFORE UPDATE OR DELETE ON authority_attempt_capability_pack_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()
    """,
    """
    CREATE TRIGGER authority_capability_pack_dependency_immutable
    BEFORE UPDATE OR DELETE ON authority_capability_pack_dependency
    FOR EACH ROW EXECUTE FUNCTION authority_capability_pack_immutable_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_runtime_pack_integrity_guard()
    RETURNS TRIGGER AS $$
    DECLARE snapshot RECORD;
    BEGIN
        IF NEW.capability_pack_deployment_id IS NULL THEN
            RETURN NEW;
        END IF;
        SELECT * INTO snapshot FROM authority_attempt_capability_pack_snapshot
        WHERE snapshot_id=NEW.capability_pack_attempt_snapshot_id;
        IF snapshot.snapshot_id IS NULL
           OR snapshot.attempt_id IS DISTINCT FROM NEW.attempt_id
           OR snapshot.operation_id IS DISTINCT FROM NEW.operation_id
           OR snapshot.execution_fencing_token IS DISTINCT FROM NEW.fencing_token
           OR snapshot.snapshot_hash IS DISTINCT FROM NEW.capability_pack_attempt_snapshot_hash
           OR snapshot.deployment_id IS DISTINCT FROM NEW.capability_pack_deployment_id
           OR snapshot.activation_version IS DISTINCT FROM NEW.capability_pack_activation_version
           OR snapshot.binding_set_id IS DISTINCT FROM NEW.capability_pack_binding_set_id
           OR snapshot.binding_set_hash IS DISTINCT FROM NEW.capability_pack_binding_set_hash
           OR snapshot.selected_scope_type IS DISTINCT FROM NEW.capability_pack_scope_type
           OR snapshot.assignment_ref IS DISTINCT FROM NEW.capability_pack_assignment_ref
           OR CONCAT(snapshot.pack_id, '@', snapshot.pack_version)
                IS DISTINCT FROM NEW.capability_pack_ref
           OR snapshot.compilation_hash
                IS DISTINCT FROM NEW.capability_pack_compilation_hash
           OR snapshot.workflow_node_id IS DISTINCT FROM NEW.workflow_node_id
           OR snapshot.operation_definition_ref IS DISTINCT FROM
                CONCAT(NEW.operation_definition_name, '@', NEW.operation_definition_version)
           OR snapshot.agent_definition_ref IS DISTINCT FROM
                CONCAT(NEW.agent_id, '@', NEW.agent_definition_version)
           OR snapshot.release_sha IS DISTINCT FROM NEW.release_sha THEN
            RAISE EXCEPTION 'Runtime Binding differs from frozen Attempt Pack Snapshot'
                USING ERRCODE='23514',
                      CONSTRAINT='authority_agent_runtime_pack_snapshot_chain';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE CONSTRAINT TRIGGER authority_agent_runtime_pack_integrity_fact_guard
    AFTER INSERT ON authority_agent_runtime_binding
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION authority_agent_runtime_pack_integrity_guard()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
