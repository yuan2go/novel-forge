from __future__ import annotations

MIGRATION_ID = "20260728_0033_agent_collaboration_v1"
DOWN_REVISION = "20260718_0032_provider_callback_dispatch_index"

MESSAGE_TYPES = """
    'PROPOSAL', 'CHALLENGE', 'COUNTER_PROPOSAL', 'REVISION', 'EVIDENCE',
    'IMPACT_ASSESSMENT', 'SUPPORT', 'OBJECTION', 'EVALUATION',
    'SCOPE_EXPANSION_REQUEST', 'ESCALATION_REQUEST',
    'DECISION_RECOMMENDATION', 'AUTHORITY_DECISION'
"""

SESSION_STATUSES = """
    'CREATED', 'SCOPE_FROZEN', 'PARTICIPANTS_ASSIGNED',
    'INITIAL_PROPOSAL_PENDING', 'DELIBERATING', 'REVISION_PENDING',
    'EVALUATING', 'CONSENSUS_REACHED', 'AUTHORITY_DECISION_PENDING',
    'ACCEPTED', 'COMMITTED', 'SCOPE_VIOLATION', 'CONFLICT_UNRESOLVED',
    'BUDGET_EXHAUSTED', 'MAX_ROUNDS_REACHED', 'HUMAN_DECISION_REQUIRED',
    'ESCALATED', 'REJECTED', 'CANCELLED', 'FAILED'
"""

DECISIONS = """
    'ACCEPTED', 'REJECTED', 'REPAIR_REQUIRED', 'DEFERRED',
    'REPLAN_REQUIRED', 'HUMAN_DECISION_REQUIRED',
    'SCOPE_EXPANSION_APPROVED', 'SCOPE_EXPANSION_REJECTED'
"""

UPGRADE_STATEMENTS = [
    f"""
    CREATE TABLE authority_agent_capability (
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        domain TEXT NOT NULL,
        input_schema_ref TEXT NOT NULL,
        output_schema_ref TEXT NOT NULL,
        supported_message_types TEXT[] NOT NULL,
        supported_scope_types TEXT[] NOT NULL,
        risk_class TEXT NOT NULL,
        execution_requirements JSONB NOT NULL,
        qualification_status TEXT NOT NULL,
        capability_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(capability_id, capability_version),
        CHECK (capability_version > 0),
        CHECK (risk_class IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
        CHECK (qualification_status IN (
            'UNQUALIFIED', 'QUALIFIED_FIXTURE', 'QUALIFIED_INTEGRATION',
            'QUALIFIED_REAL_RUNTIME', 'RETIRED'
        )),
        CHECK (cardinality(supported_message_types) > 0),
        CHECK (cardinality(supported_scope_types) > 0),
        CHECK (supported_message_types <@ ARRAY[{MESSAGE_TYPES}]::TEXT[])
    )
    """,
    """
    CREATE TABLE authority_agent_definition (
        agent_id TEXT NOT NULL,
        definition_version INTEGER NOT NULL,
        agent_type TEXT NOT NULL,
        domain TEXT NOT NULL,
        role TEXT NOT NULL,
        input_contract_ref TEXT NOT NULL,
        output_contract_ref TEXT NOT NULL,
        authority_scope_ref TEXT NOT NULL,
        default_scope_policy_ref TEXT NOT NULL,
        allowed_tools TEXT[] NOT NULL,
        allowed_context_types TEXT[] NOT NULL,
        execution_policy_ref TEXT NOT NULL,
        approval_policy_ref TEXT NOT NULL,
        quality_policy_ref TEXT NOT NULL,
        status TEXT NOT NULL,
        definition_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(agent_id, definition_version),
        CHECK (definition_version > 0),
        CHECK (status IN ('CANDIDATE', 'ACTIVE', 'RETIRED')),
        CHECK (cardinality(allowed_tools) > 0),
        CHECK (cardinality(allowed_context_types) > 0)
    )
    """,
    """
    CREATE TABLE authority_agent_definition_capability (
        agent_id TEXT NOT NULL,
        definition_version INTEGER NOT NULL,
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        PRIMARY KEY(
            agent_id, definition_version, capability_id, capability_version
        ),
        FOREIGN KEY(agent_id, definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        FOREIGN KEY(capability_id, capability_version)
            REFERENCES authority_agent_capability(capability_id, capability_version)
    )
    """,
    """
    CREATE TABLE authority_agent_scope_snapshot (
        scope_snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        scope_contract_id TEXT NOT NULL,
        scope_contract_version INTEGER NOT NULL,
        owner_authority TEXT NOT NULL,
        narrative_scope_type TEXT NOT NULL,
        book_id TEXT NOT NULL,
        volume_id TEXT NOT NULL DEFAULT '',
        arc_id TEXT NOT NULL DEFAULT '',
        chapter_group_id TEXT NOT NULL DEFAULT '',
        chapter_id TEXT NOT NULL DEFAULT '',
        scene_id TEXT NOT NULL DEFAULT '',
        past_locked_through INTEGER NOT NULL,
        active_range_start INTEGER NOT NULL,
        active_range_end INTEGER NOT NULL,
        forecast_horizon INTEGER NOT NULL,
        published_boundary INTEGER NOT NULL,
        authority_type TEXT NOT NULL,
        contract JSONB NOT NULL,
        scope_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, scope_snapshot_id),
        CHECK (scope_contract_version > 0),
        CHECK (narrative_scope_type IN (
            'BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER', 'SCENE'
        )),
        CHECK (past_locked_through >= 0),
        CHECK (published_boundary >= 0),
        CHECK (active_range_start > GREATEST(
            past_locked_through, published_boundary
        )),
        CHECK (active_range_end >= active_range_start),
        CHECK (forecast_horizon >= active_range_end)
    )
    """,
    """
    CREATE INDEX authority_agent_scope_project_book_idx
    ON authority_agent_scope_snapshot(
        project_id, book_id, narrative_scope_type, created_at DESC
    )
    """,
    """
    CREATE INDEX authority_agent_scope_contract_hash_idx
    ON authority_agent_scope_snapshot(
        project_id, scope_contract_id, scope_contract_version, scope_hash
    )
    """,
    """
    CREATE TABLE authority_agent_participant_snapshot (
        participant_snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        participant_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX authority_agent_participant_snapshot_hash_idx
    ON authority_agent_participant_snapshot(project_id, participant_hash)
    """,
    """
    CREATE TABLE authority_agent_participant (
        participant_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_participant_snapshot(participant_snapshot_id),
        ordinal INTEGER NOT NULL,
        agent_id TEXT NOT NULL,
        agent_definition_version INTEGER NOT NULL,
        participant_role TEXT NOT NULL,
        PRIMARY KEY(participant_snapshot_id, agent_id),
        UNIQUE(participant_snapshot_id, ordinal),
        FOREIGN KEY(agent_id, agent_definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        CHECK (ordinal > 0)
    )
    """,
    f"""
    CREATE TABLE authority_agent_collaboration_session (
        session_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        owner_authority TEXT NOT NULL,
        business_goal TEXT NOT NULL,
        issue_type TEXT NOT NULL,
        scope_snapshot_id TEXT
            REFERENCES authority_agent_scope_snapshot(scope_snapshot_id),
        participant_snapshot_id TEXT
            REFERENCES authority_agent_participant_snapshot(participant_snapshot_id),
        current_candidate_version_id TEXT,
        status TEXT NOT NULL,
        round_number INTEGER NOT NULL DEFAULT 0,
        turn_number INTEGER NOT NULL DEFAULT 0,
        execution_count INTEGER NOT NULL DEFAULT 0,
        spent_budget NUMERIC(20, 8) NOT NULL DEFAULT 0,
        budget_ref TEXT NOT NULL,
        termination_policy_ref TEXT NOT NULL,
        created_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        saga_id TEXT NOT NULL REFERENCES authority_saga(saga_id),
        authority_decision_id TEXT,
        last_turn_id TEXT,
        version BIGINT NOT NULL DEFAULT 0,
        cancelled_at TIMESTAMPTZ,
        invalidated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, session_id),
        UNIQUE(created_operation_id),
        UNIQUE(saga_id),
        CHECK (status IN ({SESSION_STATUSES})),
        CHECK (round_number >= 0 AND turn_number >= 0 AND execution_count >= 0),
        CHECK (spent_budget >= 0)
    )
    """,
    """
    CREATE INDEX authority_agent_collaboration_session_query_idx
    ON authority_agent_collaboration_session(
        project_id, status, updated_at DESC
    )
    """,
    f"""
    CREATE TABLE authority_agent_collaboration_turn (
        turn_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        turn_number INTEGER NOT NULL,
        round_number INTEGER NOT NULL,
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        fencing_token BIGINT NOT NULL,
        agent_id TEXT NOT NULL,
        agent_definition_version INTEGER NOT NULL,
        message_type TEXT NOT NULL,
        status TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        domain_acceptance TEXT,
        processing_result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        UNIQUE(session_id, turn_number),
        UNIQUE(session_id, stable_idempotency_key),
        UNIQUE(operation_id),
        UNIQUE(attempt_id),
        FOREIGN KEY(agent_id, agent_definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        CHECK (turn_number > 0 AND round_number > 0 AND fencing_token > 0),
        CHECK (message_type IN ({MESSAGE_TYPES})),
        CHECK (status IN (
            'SCHEDULED', 'EXECUTING', 'OUTPUT_RECEIVED', 'REPAIR_REQUIRED',
            'REJECTED', 'ACCEPTED', 'FAILED', 'CANCELLED'
        )),
        CHECK (
            domain_acceptance IS NULL OR domain_acceptance IN (
                'ACCEPTED', 'REJECTED', 'REPAIR_REQUIRED', 'DEFERRED',
                'REPLAN_REQUIRED', 'HUMAN_DECISION_REQUIRED'
            )
        )
    )
    """,
    """
    CREATE INDEX authority_agent_collaboration_turn_session_idx
    ON authority_agent_collaboration_turn(session_id, turn_number)
    """,
    f"""
    CREATE TABLE authority_agent_work_order (
        work_order_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        turn_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_turn(turn_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        fencing_token BIGINT NOT NULL,
        agent_id TEXT NOT NULL,
        agent_definition_version INTEGER NOT NULL,
        capability_id TEXT NOT NULL,
        capability_version INTEGER NOT NULL,
        execution_capability_id TEXT NOT NULL,
        message_type TEXT NOT NULL,
        business_goal TEXT NOT NULL,
        current_issue TEXT NOT NULL,
        scope_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_scope_snapshot(scope_snapshot_id),
        participant_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_participant_snapshot(participant_snapshot_id),
        input_asset_versions TEXT[] NOT NULL,
        candidate_version_id TEXT,
        context_bundle_ref TEXT NOT NULL,
        evidence_refs TEXT[] NOT NULL,
        must_preserve TEXT[] NOT NULL,
        must_change TEXT[] NOT NULL,
        forbidden_changes TEXT[] NOT NULL,
        acceptance_criteria TEXT[] NOT NULL,
        risk_level TEXT NOT NULL,
        budget_policy_ref TEXT NOT NULL,
        timeout_policy_ref TEXT NOT NULL,
        approval_policy_ref TEXT NOT NULL,
        failure_policy TEXT NOT NULL,
        continuation_policy TEXT NOT NULL,
        project_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        route_snapshot_ref TEXT NOT NULL,
        input_manifest_ref TEXT NOT NULL,
        work_order_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(turn_id),
        UNIQUE(operation_id, attempt_id),
        FOREIGN KEY(project_id, session_id)
            REFERENCES authority_agent_collaboration_session(
                project_id, session_id
            ),
        FOREIGN KEY(agent_id, agent_definition_version)
            REFERENCES authority_agent_definition(agent_id, definition_version),
        FOREIGN KEY(
            agent_id, agent_definition_version,
            capability_id, capability_version
        ) REFERENCES authority_agent_definition_capability(
            agent_id, definition_version,
            capability_id, capability_version
        ),
        CHECK (fencing_token > 0),
        CHECK (capability_version > 0),
        CHECK (message_type IN ({MESSAGE_TYPES})),
        CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
    )
    """,
    f"""
    CREATE TABLE authority_agent_output_envelope (
        output_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        turn_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_turn(turn_id),
        agent_id TEXT NOT NULL,
        message_type TEXT NOT NULL,
        structured_payload JSONB NOT NULL,
        natural_language_explanation TEXT NOT NULL,
        source_asset_versions TEXT[] NOT NULL,
        evidence_refs TEXT[] NOT NULL,
        assumptions TEXT[] NOT NULL,
        confidence NUMERIC(5, 4) NOT NULL,
        affected_assets TEXT[] NOT NULL,
        proposed_changes JSONB NOT NULL,
        preserved_constraints TEXT[] NOT NULL,
        accessed_knowledge TEXT[] NOT NULL,
        unresolved_questions TEXT[] NOT NULL,
        risk_level TEXT NOT NULL,
        requested_next_action TEXT NOT NULL,
        execution_evidence_ref TEXT NOT NULL,
        output_hash TEXT NOT NULL,
        schema_validation_status TEXT NOT NULL,
        scope_validation_status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(turn_id),
        CHECK (message_type IN ({MESSAGE_TYPES})),
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (schema_validation_status IN ('PASSED', 'FAILED', 'REPAIRED')),
        CHECK (scope_validation_status IN ('PASSED', 'FAILED'))
    )
    """,
    f"""
    CREATE TABLE authority_agent_conversation_message (
        message_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        turn_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_turn(turn_id),
        output_id TEXT NOT NULL
            REFERENCES authority_agent_output_envelope(output_id),
        message_type TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        recipient_ids TEXT[] NOT NULL,
        target_proposal_id TEXT,
        target_candidate_version_id TEXT,
        scope_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_scope_snapshot(scope_snapshot_id),
        evidence_refs TEXT[] NOT NULL,
        parent_message_id TEXT
            REFERENCES authority_agent_conversation_message(message_id),
        structured_payload JSONB NOT NULL,
        natural_language TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(turn_id),
        UNIQUE(output_id),
        CHECK (message_type IN ({MESSAGE_TYPES}))
    )
    """,
    """
    CREATE INDEX authority_agent_message_replay_idx
    ON authority_agent_conversation_message(session_id, created_at, message_id)
    """,
    """
    CREATE TABLE authority_agent_candidate_version (
        candidate_version_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        candidate_type TEXT NOT NULL,
        originating_message_id TEXT NOT NULL
            REFERENCES authority_agent_conversation_message(message_id),
        originating_turn_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_turn(turn_id),
        created_by_agent TEXT NOT NULL,
        scope_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_scope_snapshot(scope_snapshot_id),
        content_ref TEXT NOT NULL,
        structured_diff JSONB NOT NULL,
        change_reason_refs TEXT[] NOT NULL,
        preserved_constraints TEXT[] NOT NULL,
        resolved_conflicts TEXT[] NOT NULL,
        unresolved_conflicts TEXT[] NOT NULL,
        validation_status TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        invalidated_at TIMESTAMPTZ,
        UNIQUE(originating_message_id),
        CHECK (validation_status IN (
            'PENDING', 'VALID', 'INVALID', 'SCOPE_VIOLATION'
        ))
    )
    """,
    """
    CREATE INDEX authority_agent_candidate_session_idx
    ON authority_agent_candidate_version(session_id, created_at, candidate_version_id)
    """,
    """
    CREATE TABLE authority_agent_candidate_parent (
        child_candidate_version_id TEXT NOT NULL
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        parent_candidate_version_id TEXT NOT NULL
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        parent_ordinal INTEGER NOT NULL,
        PRIMARY KEY(child_candidate_version_id, parent_candidate_version_id),
        UNIQUE(child_candidate_version_id, parent_ordinal),
        CHECK (parent_ordinal > 0),
        CHECK (child_candidate_version_id <> parent_candidate_version_id)
    )
    """,
    """
    CREATE INDEX authority_agent_candidate_parent_parent_idx
    ON authority_agent_candidate_parent(
        parent_candidate_version_id, child_candidate_version_id
    )
    """,
    """
    CREATE TABLE authority_agent_conflict_record (
        conflict_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        conflict_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        raised_by TEXT NOT NULL,
        target_candidate_version_id TEXT NOT NULL
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        conflicting_asset_versions TEXT[] NOT NULL,
        claim TEXT NOT NULL,
        evidence_refs TEXT[] NOT NULL,
        affected_scopes TEXT[] NOT NULL,
        affected_assets TEXT[] NOT NULL,
        reader_outcome_impact TEXT NOT NULL,
        continuity_impact TEXT NOT NULL,
        ending_reachability_impact TEXT NOT NULL,
        requested_resolution TEXT NOT NULL,
        status TEXT NOT NULL,
        resolution_ref TEXT,
        authority_decision_id TEXT,
        raised_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMPTZ,
        CHECK (severity IN ('MINOR', 'MAJOR', 'BLOCKING')),
        CHECK (status IN (
            'OPEN', 'RESOLVED', 'ACCEPTED_NON_BLOCKING', 'DEFERRED', 'REJECTED'
        ))
    )
    """,
    """
    CREATE INDEX authority_agent_conflict_open_idx
    ON authority_agent_conflict_record(
        session_id, severity, raised_at
    ) WHERE status = 'OPEN'
    """,
    """
    CREATE TABLE authority_agent_scope_expansion_request (
        request_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        current_scope_snapshot_id TEXT NOT NULL
            REFERENCES authority_agent_scope_snapshot(scope_snapshot_id),
        requested_scope_type TEXT NOT NULL,
        requested_scope JSONB NOT NULL,
        reason TEXT NOT NULL,
        affected_assets TEXT[] NOT NULL,
        risk_level TEXT NOT NULL,
        requesting_agent TEXT NOT NULL,
        required_authority TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT 'PENDING',
        decision_ref TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        decided_at TIMESTAMPTZ,
        CHECK (requested_scope_type IN (
            'BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER', 'SCENE'
        )),
        CHECK (decision IN (
            'PENDING', 'SCOPE_EXPANSION_APPROVED', 'SCOPE_EXPANSION_REJECTED'
        )),
        CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
    )
    """,
    f"""
    CREATE TABLE authority_agent_collaboration_decision (
        decision_id TEXT PRIMARY KEY,
        decision_type TEXT NOT NULL,
        authority_type TEXT NOT NULL,
        authority_version INTEGER NOT NULL,
        session_id TEXT NOT NULL
            REFERENCES authority_agent_collaboration_session(session_id),
        candidate_version_id TEXT
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        accepted_changes TEXT[] NOT NULL,
        rejected_changes TEXT[] NOT NULL,
        deferred_changes TEXT[] NOT NULL,
        accepted_with_objections TEXT[] NOT NULL,
        unresolved_objections TEXT[] NOT NULL,
        required_followup TEXT[] NOT NULL,
        affected_asset_versions TEXT[] NOT NULL,
        commit_policy_ref TEXT NOT NULL,
        decision_evidence TEXT[] NOT NULL,
        decision_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(session_id, decision_id),
        CHECK (authority_version > 0),
        CHECK (decision_type IN ({DECISIONS})),
        CHECK (
            (
                decision_type IN (
                    'SCOPE_EXPANSION_APPROVED',
                    'SCOPE_EXPANSION_REJECTED'
                )
                AND candidate_version_id IS NULL
            )
            OR (
                decision_type NOT IN (
                    'SCOPE_EXPANSION_APPROVED',
                    'SCOPE_EXPANSION_REJECTED'
                )
                AND candidate_version_id IS NOT NULL
            )
        )
    )
    """,
    """
    CREATE INDEX authority_agent_decision_session_idx
    ON authority_agent_collaboration_decision(session_id, created_at DESC)
    """,
    """
    CREATE TABLE authority_agent_collaboration_commit (
        commit_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE
            REFERENCES authority_agent_collaboration_session(session_id),
        decision_id TEXT NOT NULL UNIQUE
            REFERENCES authority_agent_collaboration_decision(decision_id),
        candidate_version_id TEXT NOT NULL
            REFERENCES authority_agent_candidate_version(candidate_version_id),
        operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        stable_idempotency_key TEXT NOT NULL UNIQUE,
        source_lineage JSONB NOT NULL,
        receipt_ref TEXT,
        committed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE authority_agent_collaboration_session
    ADD CONSTRAINT authority_agent_session_current_candidate_fk
    FOREIGN KEY(current_candidate_version_id)
    REFERENCES authority_agent_candidate_version(candidate_version_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_agent_collaboration_session
    ADD CONSTRAINT authority_agent_session_decision_fk
    FOREIGN KEY(authority_decision_id)
    REFERENCES authority_agent_collaboration_decision(decision_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_agent_work_order
    ADD CONSTRAINT authority_agent_work_order_candidate_fk
    FOREIGN KEY(candidate_version_id)
    REFERENCES authority_agent_candidate_version(candidate_version_id)
    """,
    """
    ALTER TABLE authority_agent_conversation_message
    ADD CONSTRAINT authority_agent_message_target_candidate_fk
    FOREIGN KEY(target_candidate_version_id)
    REFERENCES authority_agent_candidate_version(candidate_version_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_agent_conflict_record
    ADD CONSTRAINT authority_agent_conflict_decision_fk
    FOREIGN KEY(authority_decision_id)
    REFERENCES authority_agent_collaboration_decision(decision_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE authority_agent_scope_expansion_request
    ADD CONSTRAINT authority_agent_expansion_decision_fk
    FOREIGN KEY(decision_ref)
    REFERENCES authority_agent_collaboration_decision(decision_id)
    DEFERRABLE INITIALLY DEFERRED
    """,
    """
    CREATE INDEX authority_agent_participant_definition_fk_idx
    ON authority_agent_participant(agent_id, agent_definition_version)
    """,
    """
    CREATE INDEX authority_agent_session_scope_fk_idx
    ON authority_agent_collaboration_session(scope_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_session_participants_fk_idx
    ON authority_agent_collaboration_session(participant_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_session_candidate_fk_idx
    ON authority_agent_collaboration_session(current_candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_session_decision_fk_idx
    ON authority_agent_collaboration_session(authority_decision_id)
    """,
    """
    CREATE INDEX authority_agent_turn_definition_fk_idx
    ON authority_agent_collaboration_turn(agent_id, agent_definition_version)
    """,
    """
    CREATE INDEX authority_agent_work_order_session_fk_idx
    ON authority_agent_work_order(session_id)
    """,
    """
    CREATE INDEX authority_agent_work_order_definition_fk_idx
    ON authority_agent_work_order(agent_id, agent_definition_version)
    """,
    """
    CREATE INDEX authority_agent_work_order_capability_fk_idx
    ON authority_agent_work_order(
        agent_id, agent_definition_version,
        capability_id, capability_version
    )
    """,
    """
    CREATE INDEX authority_agent_work_order_project_session_fk_idx
    ON authority_agent_work_order(project_id, session_id)
    """,
    """
    CREATE INDEX authority_agent_work_order_scope_fk_idx
    ON authority_agent_work_order(scope_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_work_order_participants_fk_idx
    ON authority_agent_work_order(participant_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_work_order_candidate_fk_idx
    ON authority_agent_work_order(candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_output_session_fk_idx
    ON authority_agent_output_envelope(session_id)
    """,
    """
    CREATE INDEX authority_agent_message_scope_fk_idx
    ON authority_agent_conversation_message(scope_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_message_parent_fk_idx
    ON authority_agent_conversation_message(parent_message_id)
    """,
    """
    CREATE INDEX authority_agent_message_candidate_fk_idx
    ON authority_agent_conversation_message(target_candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_candidate_turn_fk_idx
    ON authority_agent_candidate_version(originating_turn_id)
    """,
    """
    CREATE INDEX authority_agent_candidate_scope_fk_idx
    ON authority_agent_candidate_version(scope_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_conflict_candidate_fk_idx
    ON authority_agent_conflict_record(target_candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_conflict_decision_fk_idx
    ON authority_agent_conflict_record(authority_decision_id)
    """,
    """
    CREATE INDEX authority_agent_expansion_session_fk_idx
    ON authority_agent_scope_expansion_request(session_id)
    """,
    """
    CREATE INDEX authority_agent_expansion_scope_fk_idx
    ON authority_agent_scope_expansion_request(current_scope_snapshot_id)
    """,
    """
    CREATE INDEX authority_agent_expansion_decision_fk_idx
    ON authority_agent_scope_expansion_request(decision_ref)
    """,
    """
    CREATE INDEX authority_agent_decision_candidate_fk_idx
    ON authority_agent_collaboration_decision(candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_commit_candidate_fk_idx
    ON authority_agent_collaboration_commit(candidate_version_id)
    """,
    """
    CREATE INDEX authority_agent_commit_operation_fk_idx
    ON authority_agent_collaboration_commit(operation_id)
    """,
    """
    CREATE OR REPLACE FUNCTION authority_agent_collaboration_immutable()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER authority_agent_scope_snapshot_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_scope_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_participant_snapshot_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_participant_snapshot
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_participant_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_participant
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_candidate_version_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_candidate_version
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_candidate_parent_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_candidate_parent
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_work_order_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_work_order
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_output_envelope_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_output_envelope
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
    """
    CREATE TRIGGER authority_agent_conversation_message_immutable
    BEFORE UPDATE OR DELETE ON authority_agent_conversation_message
    FOR EACH ROW EXECUTE FUNCTION authority_agent_collaboration_immutable()
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
