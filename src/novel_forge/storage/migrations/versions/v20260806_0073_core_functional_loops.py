from __future__ import annotations


MIGRATION_ID = "20260806_0073_core_functional_loops"
DOWN_REVISION = "20260806_0072_capability_pack_integrity_hardening"
FORWARD_ONLY = True
FORWARD_FIX = (
    "correct invalid rows with a later forward migration; Planning candidates, "
    "Production snapshots, Contributions, and Judge decisions are immutable"
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_story_planning_generation (
        generation_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        generator_operation_name TEXT NOT NULL,
        planning_scope TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        parent_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        input_snapshot JSONB NOT NULL,
        input_snapshot_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        candidate_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        repair_of_candidate_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        repair_reason TEXT,
        repair_number INTEGER NOT NULL DEFAULT 0,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        UNIQUE(project_id, book_id, generator_operation_name, logical_key, operation_id),
        CHECK (generator_operation_name IN (
            'book_plan.generate', 'volume_plan.generate', 'arc_plan.generate',
            'chapter_group_plan.generate', 'chapter_plan.generate'
        )),
        CHECK (planning_scope IN ('BOOK', 'VOLUME', 'ARC', 'CHAPTER_GROUP', 'CHAPTER')),
        CHECK (jsonb_typeof(input_snapshot)='array'),
        CHECK (input_snapshot_hash LIKE 'sha256:%'),
        CHECK (status IN (
            'ADMITTED', 'EXECUTING', 'CANDIDATE_MATERIALIZED',
            'STRUCTURALLY_VALID', 'SEMANTICALLY_VALID', 'QUALIFIED',
            'APPROVAL_PENDING', 'APPROVED', 'ACTIVE',
            'REPAIR_REQUIRED', 'REJECTED'
        )),
        CHECK (repair_number >= 0),
        CHECK (
            (repair_number=0 AND repair_of_candidate_id IS NULL AND repair_reason IS NULL)
            OR (repair_number>0 AND repair_of_candidate_id IS NOT NULL
                AND repair_reason IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE authority_story_planning_candidate (
        candidate_id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_story_planning_generation(generation_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        candidate_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        content_hash TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES authority_attempt(attempt_id),
        repair_of_candidate_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (content_hash LIKE 'sha256:%'),
        CHECK (candidate_asset_version_id IS DISTINCT FROM repair_of_candidate_id)
    )
    """,
    """
    CREATE TABLE authority_story_planning_validation_report (
        validation_report_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        candidate_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        generation_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        validation_kind TEXT NOT NULL,
        status TEXT NOT NULL,
        report JSONB NOT NULL,
        report_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(candidate_asset_version_id, validation_kind, report_hash),
        CHECK (validation_kind IN ('STRUCTURAL', 'SEMANTIC', 'COMBINED')),
        CHECK (status IN ('PASS', 'FAIL')),
        CHECK (jsonb_typeof(report)='object'),
        CHECK (report_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_book_production_input_snapshot (
        snapshot_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        expected_book_version BIGINT NOT NULL,
        book_record_version TEXT NOT NULL,
        book_design_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        book_plan_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        current_volume_plan_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        active_arc_plan_versions JSONB NOT NULL,
        current_chapter_group_plan_version TEXT REFERENCES authority_asset_version(asset_version_id),
        production_profile_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        reader_segment_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        reader_contract_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        platform_profile_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        character_state_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        foreshadowing_state_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        quality_trend_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        reward_ledger_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        promise_ledger_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        capability_pack_deployment_refs JSONB NOT NULL,
        release_sha TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL UNIQUE,
        resolved_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, workspace_id, book_id)
            REFERENCES authority_book(project_id, workspace_id, book_id),
        UNIQUE(project_id, book_id, expected_book_version, snapshot_hash),
        CHECK (expected_book_version > 0),
        CHECK (jsonb_typeof(active_arc_plan_versions)='array'),
        CHECK (jsonb_array_length(active_arc_plan_versions)>0),
        CHECK (jsonb_typeof(capability_pack_deployment_refs)='array'),
        CHECK (release_sha ~ '^[0-9a-f]{40,64}$'),
        CHECK (snapshot_hash LIKE 'sha256:%')
    )
    """,
    "ALTER TABLE authority_book_production ADD COLUMN input_snapshot_id TEXT REFERENCES authority_book_production_input_snapshot(snapshot_id)",
    "ALTER TABLE authority_book_production ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'LEGACY_FIXTURE_INPUT_MODE'",
    "ALTER TABLE authority_book_production ADD CONSTRAINT authority_book_production_input_mode_check CHECK (input_mode IN ('RESOLVED_AUTHORITY_INPUT', 'LEGACY_FIXTURE_INPUT_MODE'))",
    """
    CREATE TABLE authority_book_production_input_binding (
        binding_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        binding_version BIGINT NOT NULL,
        snapshot_id TEXT NOT NULL
            REFERENCES authority_book_production_input_snapshot(snapshot_id),
        reason TEXT NOT NULL,
        bound_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(book_run_id, binding_version),
        UNIQUE(book_run_id, snapshot_id),
        CHECK (binding_version > 0)
    )
    """,
    "ALTER TABLE authority_book_production DROP CONSTRAINT IF EXISTS authority_book_production_state_check",
    """
    ALTER TABLE authority_book_production
    ADD CONSTRAINT authority_book_production_state_check CHECK (state IN (
        'INPUT_RESOLUTION_REQUIRED', 'PLANNING_REQUIRED', 'PLAN_GENERATING',
        'PLAN_APPROVAL_PENDING', 'READY', 'CHAPTER_GROUP_REQUIRED',
        'CHAPTER_PLAN_REQUIRED', 'CHAPTER_SUBMITTED', 'CHAPTER_RUNNING',
        'CHAPTER_WAITING_RETRY', 'CHAPTER_COMPLETED',
        'CHAPTER_ACCEPTANCE_PENDING', 'CHAPTER_FAILED_RETRYABLE',
        'CHAPTER_FAILED_TERMINAL', 'CANON_PENDING', 'CANON_COMMITTED',
        'READER_OUTCOME_PENDING', 'FOLLOWUP_PENDING', 'CHECKPOINT_PENDING',
        'REPLAN_REQUIRED', 'REPLAN_GENERATING', 'REPLAN_APPROVAL_PENDING',
        'PAUSED', 'COMPLETED', 'ABORTED'
    ))
    """,
    """
    CREATE TABLE authority_arc_membership (
        membership_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        arc_plan_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        member_plan_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        member_scope TEXT NOT NULL,
        membership_kind TEXT NOT NULL,
        required_contribution JSONB NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, arc_plan_version_id, member_plan_version_id, membership_kind),
        CHECK (arc_plan_version_id <> member_plan_version_id),
        CHECK (member_scope IN ('VOLUME', 'CHAPTER_GROUP', 'CHAPTER')),
        CHECK (membership_kind IN ('VOLUME_SPAN', 'PRIMARY', 'SECONDARY', 'REQUIRED_CONTRIBUTION', 'CHECKPOINT_EXPECTATION')),
        CHECK (jsonb_typeof(required_contribution)='object')
    )
    """,
    """
    ALTER TABLE authority_book_chapter_acceptance
    ADD CONSTRAINT authority_book_acceptance_contribution_identity_unique
    UNIQUE(
        project_id, chapter_request_id, acceptance_operation_id,
        chapter_outcome_asset_version_id
    )
    """,
    """
    CREATE TABLE authority_arc_contribution (
        contribution_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        arc_plan_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        chapter_plan_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        chapter_request_id TEXT NOT NULL REFERENCES authority_book_chapter_request(chapter_request_id),
        chapter_acceptance_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        contribution_evidence_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        contribution_kind TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        recorded_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(
            project_id, chapter_request_id, chapter_acceptance_operation_id,
            contribution_evidence_version_id
        ) REFERENCES authority_book_chapter_acceptance(
            project_id, chapter_request_id, acceptance_operation_id,
            chapter_outcome_asset_version_id
        ),
        UNIQUE(arc_plan_version_id, chapter_request_id, contribution_kind),
        CHECK (contribution_kind IN ('REQUIRED', 'ACTUAL', 'CLOSURE', 'DEBT')),
        CHECK (evidence_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_book_volume_checkpoint (
        checkpoint_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        volume_plan_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        chapter_range INT4RANGE NOT NULL,
        accepted_through_chapter INTEGER NOT NULL,
        active_chapter_group TEXT,
        volume_goal_status TEXT NOT NULL,
        arc_status_snapshot JSONB NOT NULL,
        promise_settlement_status TEXT NOT NULL,
        ending_reachability TEXT NOT NULL,
        state TEXT NOT NULL,
        version BIGINT NOT NULL,
        updated_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(book_run_id, volume_plan_version, version),
        CHECK (accepted_through_chapter >= 0),
        CHECK (jsonb_typeof(arc_status_snapshot)='object'),
        CHECK (ending_reachability IN ('REACHABLE', 'AT_RISK', 'UNREACHABLE', 'UNKNOWN')),
        CHECK (state IN ('PLANNED', 'ACTIVE', 'CLOSURE_PENDING', 'COMPLETED', 'ABORTED')),
        CHECK (version > 0)
    )
    """,
    """
    CREATE TABLE authority_book_arc_checkpoint (
        checkpoint_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        arc_plan_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        current_stage TEXT NOT NULL,
        arc_status TEXT NOT NULL,
        contribution_count INTEGER NOT NULL,
        required_next_contribution JSONB NOT NULL,
        closure_condition_status TEXT NOT NULL,
        stagnation_risk TEXT NOT NULL,
        cross_volume_status TEXT NOT NULL,
        last_updated_chapter INTEGER NOT NULL,
        arc_debt JSONB NOT NULL,
        version BIGINT NOT NULL,
        updated_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, arc_plan_version, version),
        CHECK (arc_status IN ('PLANNED', 'ACTIVE', 'STALLED', 'AT_RISK', 'CLOSURE_PENDING', 'COMPLETED', 'ABORTED')),
        CHECK (contribution_count >= 0 AND last_updated_chapter >= 0),
        CHECK (jsonb_typeof(required_next_contribution)='object'),
        CHECK (jsonb_typeof(arc_debt)='object'),
        CHECK (version > 0)
    )
    """,
    """
    CREATE TABLE authority_ending_reachability_report (
        report_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        ending_contract_version TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        evaluated_through_chapter INTEGER NOT NULL,
        remaining_chapter_budget INTEGER NOT NULL,
        ending_contract_reachable BOOLEAN NOT NULL,
        critical_arc_closure_path BOOLEAN NOT NULL,
        chapter_budget_sufficient BOOLEAN NOT NULL,
        required_event_windows_open BOOLEAN NOT NULL,
        promise_capacity_sufficient BOOLEAN NOT NULL,
        replan_required BOOLEAN NOT NULL,
        reasons JSONB NOT NULL,
        report_hash TEXT NOT NULL,
        generated_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, book_id, report_hash),
        CHECK (evaluated_through_chapter >= 0 AND remaining_chapter_budget >= 0),
        CHECK (jsonb_typeof(reasons)='array'),
        CHECK (report_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_book_replan (
        replan_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        book_run_id TEXT NOT NULL REFERENCES authority_book_production(book_run_id),
        source_recap_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        replan_request_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        affected_scope TEXT NOT NULL,
        future_only BOOLEAN NOT NULL,
        target_asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id),
        replacement_candidate_asset_version_id TEXT REFERENCES authority_asset_version(asset_version_id),
        generation_operation_id TEXT REFERENCES authority_operation(operation_id),
        plan_change_proposal_id TEXT REFERENCES authority_plan_change_proposal(proposal_id),
        input_snapshot_id TEXT REFERENCES authority_book_production_input_snapshot(snapshot_id),
        status TEXT NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (affected_scope IN ('CHAPTER', 'CHAPTER_GROUP', 'ARC', 'VOLUME', 'BOOK')),
        CHECK (future_only=TRUE),
        CHECK (status IN ('REQUESTED', 'IMPACT_ANALYZED', 'CANDIDATE_GENERATING', 'APPROVAL_PENDING', 'ACTIVE', 'REGENERATING', 'RESUMED', 'REJECTED', 'FAILED'))
    )
    """,
    """
    CREATE TABLE authority_reader_judge (
        judge_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, judge_id)
    )
    """,
    """
    CREATE TABLE authority_reader_judge_version (
        judge_version_id TEXT PRIMARY KEY,
        judge_id TEXT NOT NULL REFERENCES authority_reader_judge(judge_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        definition_version INTEGER NOT NULL,
        model_profile_ref TEXT NOT NULL,
        model_version TEXT NOT NULL,
        capability_pack_ref TEXT NOT NULL,
        prompt_ref TEXT NOT NULL,
        skill_ref TEXT NOT NULL,
        reader_segment_scope TEXT NOT NULL,
        platform_scope TEXT NOT NULL,
        genre_scope TEXT NOT NULL,
        subgenre_scope TEXT NOT NULL,
        chapter_type_scope TEXT NOT NULL,
        evaluation_contract_ref TEXT NOT NULL,
        calibration_policy_ref TEXT NOT NULL,
        decision_policy_ref TEXT NOT NULL,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        maximum_adjustment_chapters INTEGER NOT NULL DEFAULT 0,
        definition JSONB NOT NULL,
        definition_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, judge_id)
            REFERENCES authority_reader_judge(project_id, judge_id),
        UNIQUE(project_id, judge_version_id),
        UNIQUE(judge_id, definition_version),
        UNIQUE(project_id, definition_hash),
        CHECK (definition_version > 0),
        CHECK (mode IN ('SHADOW', 'ADVISORY', 'BOUNDED_PRODUCTION')),
        CHECK (status IN ('UNQUALIFIED', 'SHADOW', 'CALIBRATION_PENDING', 'CALIBRATED', 'QUALIFIED', 'DRIFTED', 'SUSPENDED', 'RETIRED')),
        CHECK (maximum_adjustment_chapters >= 0),
        CHECK (mode <> 'BOUNDED_PRODUCTION' OR maximum_adjustment_chapters > 0),
        CHECK (jsonb_typeof(definition)='object'),
        CHECK (definition_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_reader_judge_qualification_decision (
        decision_id TEXT PRIMARY KEY,
        judge_version_id TEXT NOT NULL REFERENCES authority_reader_judge_version(judge_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        qualification_status TEXT NOT NULL,
        evidence_level TEXT NOT NULL,
        calibration_profile_id TEXT REFERENCES calibration_profile(profile_id),
        evidence JSONB NOT NULL,
        evidence_hash TEXT NOT NULL,
        decided_by TEXT NOT NULL,
        decision_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, judge_version_id)
            REFERENCES authority_reader_judge_version(project_id, judge_version_id),
        UNIQUE(project_id, decision_id),
        UNIQUE(project_id, judge_version_id, decision_id),
        UNIQUE(judge_version_id, decision_operation_id),
        CHECK (qualification_status IN ('UNQUALIFIED', 'SHADOW', 'CALIBRATION_PENDING', 'CALIBRATED', 'QUALIFIED', 'DRIFTED', 'SUSPENDED', 'RETIRED')),
        CHECK (evidence_level IN ('FIXTURE', 'HUMAN_ANCHORED', 'BEHAVIOR_CALIBRATED')),
        CHECK (evidence_level <> 'FIXTURE' OR qualification_status NOT IN ('CALIBRATED', 'QUALIFIED')),
        CHECK (jsonb_typeof(evidence)='object'),
        CHECK (evidence_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_reader_judge_activation (
        activation_id TEXT PRIMARY KEY,
        judge_version_id TEXT NOT NULL REFERENCES authority_reader_judge_version(judge_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT REFERENCES authority_book(book_id),
        activation_version BIGINT NOT NULL,
        expected_previous_activation_version BIGINT NOT NULL,
        qualification_decision_id TEXT NOT NULL REFERENCES authority_reader_judge_qualification_decision(decision_id),
        activation_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, judge_version_id)
            REFERENCES authority_reader_judge_version(project_id, judge_version_id),
        FOREIGN KEY(project_id, qualification_decision_id)
            REFERENCES authority_reader_judge_qualification_decision(project_id, decision_id),
        FOREIGN KEY(project_id, judge_version_id, qualification_decision_id)
            REFERENCES authority_reader_judge_qualification_decision(
                project_id, judge_version_id, decision_id
            ),
        UNIQUE(project_id, activation_id),
        UNIQUE(project_id, book_id, activation_version),
        CHECK (activation_version > 0),
        CHECK (expected_previous_activation_version = activation_version - 1)
    )
    """,
    """
    CREATE TABLE authority_reader_judge_active (
        scope_key TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT REFERENCES authority_book(book_id),
        activation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_reader_judge_activation(activation_id),
        activation_version BIGINT NOT NULL,
        effective_mode TEXT NOT NULL,
        effective_qualification_status TEXT NOT NULL,
        state TEXT NOT NULL,
        updated_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, activation_id)
            REFERENCES authority_reader_judge_activation(project_id, activation_id),
        CHECK (scope_key LIKE 'sha256:%'),
        CHECK (activation_version > 0),
        CHECK (effective_mode IN ('SHADOW', 'ADVISORY', 'BOUNDED_PRODUCTION')),
        CHECK (effective_qualification_status IN (
            'UNQUALIFIED', 'SHADOW', 'CALIBRATION_PENDING', 'CALIBRATED',
            'QUALIFIED', 'DRIFTED', 'SUSPENDED', 'RETIRED'
        )),
        CHECK (state IN ('ACTIVE', 'SUSPENDED', 'RETIRED'))
    )
    """,
    """
    CREATE TABLE authority_reader_judge_suspension (
        suspension_id TEXT PRIMARY KEY,
        activation_id TEXT NOT NULL UNIQUE REFERENCES authority_reader_judge_activation(activation_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        reason TEXT NOT NULL,
        suspension_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, activation_id)
            REFERENCES authority_reader_judge_activation(project_id, activation_id)
    )
    """,
    """
    CREATE TABLE authority_reader_judge_retirement (
        retirement_id TEXT PRIMARY KEY,
        judge_version_id TEXT NOT NULL UNIQUE REFERENCES authority_reader_judge_version(judge_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        reason TEXT NOT NULL,
        retirement_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, judge_version_id)
            REFERENCES authority_reader_judge_version(project_id, judge_version_id)
    )
    """,
    """
    CREATE TABLE authority_reader_judge_drift (
        drift_id TEXT PRIMARY KEY,
        judge_version_id TEXT NOT NULL REFERENCES authority_reader_judge_version(judge_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        severity TEXT NOT NULL,
        drift_type TEXT NOT NULL,
        evidence JSONB NOT NULL,
        evidence_hash TEXT NOT NULL,
        downgrade_mode TEXT NOT NULL,
        detected_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, judge_version_id)
            REFERENCES authority_reader_judge_version(project_id, judge_version_id),
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'SEVERE')),
        CHECK (downgrade_mode IN ('SHADOW', 'ADVISORY')),
        CHECK (jsonb_typeof(evidence)='object'),
        CHECK (evidence_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_reader_calibration_observation_set (
        observation_set_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        exposure_ids JSONB NOT NULL,
        outcome_event_ids JSONB NOT NULL,
        chapter_metric_ids JSONB NOT NULL,
        retention_metric_ids JSONB NOT NULL,
        observation_count INTEGER NOT NULL,
        evidence_level TEXT NOT NULL,
        observation_hash TEXT NOT NULL UNIQUE,
        built_by_operation_id TEXT NOT NULL UNIQUE REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (jsonb_typeof(exposure_ids)='array'),
        CHECK (jsonb_typeof(outcome_event_ids)='array'),
        CHECK (jsonb_typeof(chapter_metric_ids)='array'),
        CHECK (jsonb_typeof(retention_metric_ids)='array'),
        CHECK (observation_count >= 0),
        CHECK (evidence_level IN ('FIXTURE', 'HUMAN_ANCHORED', 'BEHAVIOR_CALIBRATED')),
        CHECK (observation_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE OR REPLACE FUNCTION novel_forge_validate_core_functional_scope()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME = 'authority_story_planning_generation' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_operation AS operation
                WHERE operation.operation_id=NEW.operation_id
                  AND operation.project_id=NEW.project_id
                  AND operation.workspace_id=NEW.workspace_id
                  AND operation.command_payload#>>'{payload,book_id}'=NEW.book_id
            ) OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(NEW.input_snapshot) AS item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=item->>'asset_version_id'
                      AND asset.project_id=NEW.project_id
                      AND COALESCE(version.content->>'book_id', NEW.book_id)=NEW.book_id
                )
            ) OR (
                NEW.parent_version_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM story_plan_binding AS binding
                    WHERE binding.project_id=NEW.project_id
                      AND binding.book_id=NEW.book_id
                      AND binding.asset_version_id=NEW.parent_version_id
                )
            ) OR (
                NEW.candidate_asset_version_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM authority_story_planning_candidate AS candidate
                    WHERE candidate.project_id=NEW.project_id
                      AND candidate.book_id=NEW.book_id
                      AND candidate.generation_id=NEW.generation_id
                      AND candidate.candidate_asset_version_id=NEW.candidate_asset_version_id
                )
            ) OR (
                NEW.repair_of_candidate_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM authority_story_planning_candidate AS prior
                    WHERE prior.project_id=NEW.project_id
                      AND prior.book_id=NEW.book_id
                      AND prior.candidate_asset_version_id=NEW.repair_of_candidate_id
                )
            ) THEN
                RAISE EXCEPTION 'STORY_PLANNING_GENERATION_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_story_planning_candidate' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM authority_story_planning_generation AS generation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=generation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=NEW.candidate_asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE generation.generation_id=NEW.generation_id
                  AND generation.project_id=NEW.project_id
                  AND generation.book_id=NEW.book_id
                  AND attempt.attempt_id=NEW.attempt_id
                  AND asset.project_id=NEW.project_id
            ) OR (
                NEW.repair_of_candidate_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM authority_story_planning_candidate AS prior
                    WHERE prior.project_id=NEW.project_id
                      AND prior.book_id=NEW.book_id
                      AND prior.candidate_asset_version_id=NEW.repair_of_candidate_id
                )
            ) THEN
                RAISE EXCEPTION 'STORY_PLANNING_CANDIDATE_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_story_planning_validation_report' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM authority_story_planning_candidate AS candidate
                JOIN authority_story_planning_generation AS generation
                  ON generation.generation_id=candidate.generation_id
                WHERE candidate.candidate_asset_version_id=NEW.candidate_asset_version_id
                  AND candidate.project_id=NEW.project_id
                  AND generation.operation_id=NEW.generation_operation_id
            ) THEN
                RAISE EXCEPTION 'STORY_PLANNING_VALIDATION_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_book_production_input_snapshot' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_book AS book
                WHERE book.project_id=NEW.project_id
                  AND book.workspace_id=NEW.workspace_id
                  AND book.book_id=NEW.book_id
            ) OR EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    NEW.book_design_version, NEW.book_plan_version,
                    NEW.current_volume_plan_version,
                    NEW.current_chapter_group_plan_version,
                    NEW.production_profile_version, NEW.reader_segment_version,
                    NEW.reader_contract_version, NEW.platform_profile_version,
                    NEW.character_state_version, NEW.foreshadowing_state_version,
                    NEW.quality_trend_version, NEW.reward_ledger_version,
                    NEW.promise_ledger_version
                ]) AS value(asset_version_id)
                WHERE value.asset_version_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=value.asset_version_id
                      AND asset.project_id=NEW.project_id
                  )
            ) OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(NEW.active_arc_plan_versions) AS value(asset_version_id)
                WHERE NOT EXISTS (
                    SELECT 1 FROM story_plan_binding AS binding
                    WHERE binding.project_id=NEW.project_id
                      AND binding.book_id=NEW.book_id
                      AND binding.asset_version_id=value.asset_version_id
                      AND binding.contract_type='ARC'
                      AND binding.freshness='CURRENT'
                )
            ) OR NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.book_plan_version
                  AND binding.contract_type='BOOK'
                  AND binding.freshness='CURRENT'
            ) OR NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.current_volume_plan_version
                  AND binding.contract_type='VOLUME'
                  AND binding.freshness='CURRENT'
            ) OR (
                NEW.current_chapter_group_plan_version IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM story_plan_binding AS binding
                    WHERE binding.project_id=NEW.project_id
                      AND binding.book_id=NEW.book_id
                      AND binding.asset_version_id=NEW.current_chapter_group_plan_version
                      AND binding.contract_type='CHAPTER_GROUP'
                      AND binding.freshness='CURRENT'
                )
            ) THEN
                RAISE EXCEPTION 'BOOK_INPUT_SNAPSHOT_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_book_production_input_binding' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM authority_book_production AS run
                JOIN authority_book_production_input_snapshot AS snapshot
                  ON snapshot.snapshot_id=NEW.snapshot_id
                WHERE run.book_run_id=NEW.book_run_id
                  AND run.project_id=NEW.project_id
                  AND run.book_id=NEW.book_id
                  AND snapshot.project_id=NEW.project_id
                  AND snapshot.book_id=NEW.book_id
            ) THEN
                RAISE EXCEPTION 'BOOK_INPUT_BINDING_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_arc_membership' THEN
            IF NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.arc_plan_version_id
                  AND binding.contract_type='ARC'
            ) OR NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.member_plan_version_id
                  AND binding.contract_type=NEW.member_scope
            ) THEN
                RAISE EXCEPTION 'ARC_MEMBERSHIP_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_arc_contribution' THEN
            IF NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS arc
                WHERE arc.project_id=NEW.project_id
                  AND arc.book_id=NEW.book_id
                  AND arc.asset_version_id=NEW.arc_plan_version_id
                  AND arc.contract_type='ARC'
            ) OR NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS chapter
                WHERE chapter.project_id=NEW.project_id
                  AND chapter.book_id=NEW.book_id
                  AND chapter.asset_version_id=NEW.chapter_plan_version_id
                  AND chapter.contract_type='CHAPTER'
            ) OR NOT EXISTS (
                SELECT 1
                FROM authority_book_chapter_request AS request
                JOIN authority_book_production AS run
                  ON run.book_run_id=request.book_run_id
                WHERE request.chapter_request_id=NEW.chapter_request_id
                  AND request.project_id=NEW.project_id
                  AND run.book_id=NEW.book_id
                  AND request.chapter_plan_version=NEW.chapter_plan_version_id
            ) OR NOT EXISTS (
                SELECT 1
                FROM authority_book_chapter_acceptance AS acceptance
                WHERE acceptance.project_id=NEW.project_id
                  AND acceptance.chapter_request_id=NEW.chapter_request_id
                  AND acceptance.acceptance_operation_id=
                      NEW.chapter_acceptance_operation_id
                  AND acceptance.chapter_outcome_asset_version_id=
                      NEW.contribution_evidence_version_id
                  AND acceptance.status='COMMITTED'
            ) OR NOT EXISTS (
                SELECT 1
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=NEW.contribution_evidence_version_id
                  AND asset.project_id=NEW.project_id
            ) THEN
                RAISE EXCEPTION 'ARC_CONTRIBUTION_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME IN (
            'authority_book_volume_checkpoint',
            'authority_ending_reachability_report'
        ) THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_book_production AS run
                WHERE run.book_run_id=NEW.book_run_id
                  AND run.project_id=NEW.project_id
                  AND run.book_id=NEW.book_id
            ) THEN
                RAISE EXCEPTION 'BOOK_CHECKPOINT_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_book_arc_checkpoint' THEN
            IF NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.arc_plan_version
                  AND binding.contract_type='ARC'
            ) THEN
                RAISE EXCEPTION 'ARC_CHECKPOINT_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_book_replan' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_book_production AS run
                WHERE run.book_run_id=NEW.book_run_id
                  AND run.project_id=NEW.project_id
                  AND run.book_id=NEW.book_id
            ) OR EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    NEW.source_recap_asset_version_id,
                    NEW.replan_request_asset_version_id
                ]) AS value(asset_version_id)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=value.asset_version_id
                      AND asset.project_id=NEW.project_id
                )
            ) OR NOT EXISTS (
                SELECT 1 FROM story_plan_binding AS binding
                WHERE binding.project_id=NEW.project_id
                  AND binding.book_id=NEW.book_id
                  AND binding.asset_version_id=NEW.target_asset_version_id
            ) OR (
                NEW.replacement_candidate_asset_version_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=NEW.replacement_candidate_asset_version_id
                      AND asset.project_id=NEW.project_id
                )
            ) THEN
                RAISE EXCEPTION 'BOOK_REPLAN_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_reader_judge_activation' THEN
            IF NOT EXISTS (
                SELECT 1
                FROM authority_reader_judge_qualification_decision AS decision
                WHERE decision.project_id=NEW.project_id
                  AND decision.judge_version_id=NEW.judge_version_id
                  AND decision.decision_id=NEW.qualification_decision_id
            ) OR (NEW.book_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM authority_book AS book
                WHERE book.project_id=NEW.project_id AND book.book_id=NEW.book_id
            )) THEN
                RAISE EXCEPTION 'READER_JUDGE_ACTIVATION_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        ELSIF TG_TABLE_NAME = 'authority_reader_judge_active' THEN
            IF NOT EXISTS (
                SELECT 1 FROM authority_reader_judge_activation AS activation
                WHERE activation.activation_id=NEW.activation_id
                  AND activation.project_id=NEW.project_id
                  AND activation.book_id IS NOT DISTINCT FROM NEW.book_id
                  AND activation.activation_version=NEW.activation_version
            ) THEN
                RAISE EXCEPTION 'READER_JUDGE_ACTIVE_SCOPE_INVALID'
                    USING ERRCODE='check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    *[
        f"""
        CREATE TRIGGER {table}_scope_guard
        BEFORE INSERT OR UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION novel_forge_validate_core_functional_scope()
        """
        for table in (
            "authority_story_planning_generation",
            "authority_story_planning_candidate",
            "authority_story_planning_validation_report",
            "authority_book_production_input_snapshot",
            "authority_book_production_input_binding",
            "authority_arc_membership",
            "authority_arc_contribution",
            "authority_book_volume_checkpoint",
            "authority_book_arc_checkpoint",
            "authority_ending_reachability_report",
            "authority_book_replan",
            "authority_reader_judge_activation",
            "authority_reader_judge_active",
        )
    ],
    """
    CREATE OR REPLACE FUNCTION novel_forge_story_planning_generation_identity_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF ROW(
            OLD.generation_id, OLD.operation_id, OLD.project_id,
            OLD.workspace_id, OLD.book_id, OLD.generator_operation_name,
            OLD.planning_scope, OLD.logical_key, OLD.parent_version_id,
            OLD.input_snapshot, OLD.input_snapshot_hash,
            OLD.repair_of_candidate_id, OLD.repair_reason, OLD.repair_number,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.generation_id, NEW.operation_id, NEW.project_id,
            NEW.workspace_id, NEW.book_id, NEW.generator_operation_name,
            NEW.planning_scope, NEW.logical_key, NEW.parent_version_id,
            NEW.input_snapshot, NEW.input_snapshot_hash,
            NEW.repair_of_candidate_id, NEW.repair_reason, NEW.repair_number,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'STORY_PLANNING_GENERATION_IDENTITY_IMMUTABLE'
                USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER authority_story_planning_generation_identity_immutable
    BEFORE UPDATE ON authority_story_planning_generation
    FOR EACH ROW
    EXECUTE FUNCTION novel_forge_story_planning_generation_identity_guard()
    """,
    """
    CREATE OR REPLACE FUNCTION novel_forge_reject_immutable_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'IMMUTABLE_AUTHORITY_FACT:%', TG_TABLE_NAME
            USING ERRCODE='check_violation';
    END;
    $$
    """,
    *[
        f"""
        CREATE TRIGGER {table}_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
        """
        for table in (
            "authority_story_planning_candidate",
            "authority_story_planning_validation_report",
            "authority_book_production_input_snapshot",
            "authority_book_production_input_binding",
            "authority_arc_membership",
            "authority_arc_contribution",
            "authority_book_volume_checkpoint",
            "authority_book_arc_checkpoint",
            "authority_ending_reachability_report",
            "authority_reader_judge_version",
            "authority_reader_judge_qualification_decision",
            "authority_reader_judge_activation",
            "authority_reader_judge_suspension",
            "authority_reader_judge_retirement",
            "authority_reader_judge_drift",
            "authority_reader_calibration_observation_set",
        )
    ],
    "CREATE INDEX story_planning_generation_query_idx ON authority_story_planning_generation(project_id, book_id, status, created_at DESC)",
    "CREATE INDEX book_input_snapshot_query_idx ON authority_book_production_input_snapshot(project_id, book_id, created_at DESC)",
    "CREATE INDEX arc_membership_query_idx ON authority_arc_membership(project_id, book_id, arc_plan_version_id)",
    "CREATE INDEX arc_contribution_query_idx ON authority_arc_contribution(project_id, book_id, arc_plan_version_id, created_at)",
    "CREATE INDEX volume_checkpoint_query_idx ON authority_book_volume_checkpoint(project_id, book_id, version DESC)",
    "CREATE INDEX arc_checkpoint_query_idx ON authority_book_arc_checkpoint(project_id, book_id, arc_plan_version, version DESC)",
    "CREATE INDEX book_replan_query_idx ON authority_book_replan(project_id, book_id, status, updated_at DESC)",
    "CREATE INDEX reader_judge_resolution_idx ON authority_reader_judge_version(project_id, platform_scope, genre_scope, subgenre_scope, chapter_type_scope, reader_segment_scope, status)",
    "CREATE INDEX reader_judge_activation_query_idx ON authority_reader_judge_activation(project_id, book_id, activation_version DESC)",
    "CREATE INDEX reader_judge_active_resolution_idx ON authority_reader_judge_active(project_id, book_id, state)",
    """
    DO $$
    DECLARE
        fk RECORD;
        indexed_columns TEXT;
        index_name TEXT;
    BEGIN
        FOR fk IN
            SELECT constraint_row.oid, table_row.relname,
                   constraint_row.conname, constraint_row.conkey
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid=constraint_row.conrelid
            WHERE constraint_row.contype='f'
              AND table_row.relname = ANY(ARRAY[
                'authority_story_planning_generation',
                'authority_story_planning_candidate',
                'authority_story_planning_validation_report',
                'authority_book_production_input_snapshot',
                'authority_book_production_input_binding',
                'authority_book_production',
                'authority_arc_membership',
                'authority_arc_contribution',
                'authority_book_volume_checkpoint',
                'authority_book_arc_checkpoint',
                'authority_ending_reachability_report',
                'authority_book_replan',
                'authority_reader_judge',
                'authority_reader_judge_version',
                'authority_reader_judge_qualification_decision',
                'authority_reader_judge_activation',
                'authority_reader_judge_active',
                'authority_reader_judge_suspension',
                'authority_reader_judge_retirement',
                'authority_reader_judge_drift',
                'authority_reader_calibration_observation_set'
              ])
            ORDER BY cardinality(constraint_row.conkey) DESC,
                     table_row.relname, constraint_row.conname
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM pg_index AS index_row
                WHERE index_row.indrelid=(
                    SELECT constraint_row.conrelid
                    FROM pg_constraint AS constraint_row
                    WHERE constraint_row.oid=fk.oid
                )
                  AND index_row.indisvalid
                  AND fk.conkey::smallint[] <@ index_row.indkey::smallint[]
            ) THEN
                SELECT string_agg(format('%I', attribute_row.attname), ', '
                                  ORDER BY key_row.ordinality)
                INTO indexed_columns
                FROM unnest(fk.conkey) WITH ORDINALITY
                     AS key_row(attnum, ordinality)
                JOIN pg_attribute AS attribute_row
                  ON attribute_row.attrelid=(
                       SELECT constraint_row.conrelid
                       FROM pg_constraint AS constraint_row
                       WHERE constraint_row.oid=fk.oid
                     )
                 AND attribute_row.attnum=key_row.attnum;
                index_name := 'nf0073_fk_' || substr(
                    md5(fk.relname || ':' || fk.conname), 1, 20
                );
                EXECUTE format(
                    'CREATE INDEX %I ON %I (%s)',
                    index_name, fk.relname, indexed_columns
                );
            END IF;
        END LOOP;
    END;
    $$
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
