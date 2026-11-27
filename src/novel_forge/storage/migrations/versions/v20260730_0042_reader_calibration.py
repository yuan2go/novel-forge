from __future__ import annotations

MIGRATION_ID = "20260730_0042_reader_calibration"
DOWN_REVISION = "20260730_0041_plan_change_authority"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE human_preference_task (
        task_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        task_type TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence_level TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (task_type IN ('AB_BLIND', 'BA_REVERSAL')),
        CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
        CHECK (evidence_level IN ('FIXTURE', 'HUMAN_VERIFIED'))
    )
    """,
    """
    CREATE TABLE human_preference_pair (
        pair_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES human_preference_task(task_id),
        project_id TEXT NOT NULL,
        canonical_pair_key TEXT NOT NULL,
        asset_a_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        asset_b_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        left_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        right_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        presentation_order TEXT NOT NULL,
        randomization_hash TEXT NOT NULL,
        blinded BOOLEAN NOT NULL,
        reversal_of_pair_id TEXT REFERENCES human_preference_pair(pair_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(task_id, canonical_pair_key, presentation_order),
        CHECK (asset_a_version_id <> asset_b_version_id),
        CHECK (left_asset_version_id <> right_asset_version_id),
        CHECK (presentation_order IN ('AB', 'BA')),
        CHECK (blinded = TRUE)
    )
    """,
    """
    CREATE TABLE human_preference_decision (
        decision_id TEXT PRIMARY KEY,
        pair_id TEXT NOT NULL REFERENCES human_preference_pair(pair_id),
        project_id TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        reviewer_group TEXT NOT NULL,
        choice TEXT NOT NULL,
        preferred_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        evidence_spans JSONB NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        annotation_reason TEXT NOT NULL,
        position_revealed_after_decision BOOLEAN NOT NULL,
        decision_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(pair_id, reviewer_id),
        CHECK (reviewer_group IN ('EDITOR', 'READER')),
        CHECK (choice IN ('A', 'B', 'TIE', 'REJECT_BOTH')),
        CHECK (confidence BETWEEN 0 AND 1),
        CHECK (jsonb_typeof(evidence_spans) = 'array'),
        CHECK (position_revealed_after_decision = TRUE),
        CHECK (
            (choice IN ('A', 'B') AND preferred_asset_version_id IS NOT NULL)
            OR (choice IN ('TIE', 'REJECT_BOTH')
                AND preferred_asset_version_id IS NULL)
        )
    )
    """,
    """
    CREATE TABLE human_preference_golden_set (
        golden_set_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        version INTEGER NOT NULL,
        status TEXT NOT NULL,
        evidence_level TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, reader_segment, version),
        CHECK (status IN ('CANDIDATE', 'ACTIVE', 'RETIRED')),
        CHECK (evidence_level IN ('FIXTURE', 'HUMAN_VERIFIED'))
    )
    """,
    """
    CREATE TABLE human_judge_agreement_report (
        report_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL UNIQUE
            REFERENCES human_preference_task(task_id),
        project_id TEXT NOT NULL,
        report_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        agreement_rate DOUBLE PRECISION,
        position_bias_detected BOOLEAN NOT NULL,
        reader_editor_disagreement DOUBLE PRECISION,
        sample_coverage JSONB NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (
            agreement_rate IS NULL
            OR agreement_rate BETWEEN 0 AND 1
        ),
        CHECK (
            reader_editor_disagreement IS NULL
            OR reader_editor_disagreement BETWEEN 0 AND 1
        ),
        CHECK (jsonb_typeof(sample_coverage) = 'object')
    )
    """,
    """
    CREATE TABLE reader_session (
        reader_session_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        reader_subject_ref TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        consent_policy_version TEXT NOT NULL,
        pseudonymized BOOLEAN NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        ended_at TIMESTAMPTZ,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        CHECK (pseudonymized = TRUE)
    )
    """,
    """
    CREATE TABLE reader_exposure (
        exposure_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        reader_session_id TEXT NOT NULL
            REFERENCES reader_session(reader_session_id),
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        chapter_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        exposed_at TIMESTAMPTZ NOT NULL,
        denominator_eligible BOOLEAN NOT NULL,
        exposure_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        UNIQUE(project_id, stable_idempotency_key)
    )
    """,
    """
    CREATE TABLE reader_outcome_event (
        outcome_event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        exposure_id TEXT NOT NULL REFERENCES reader_exposure(exposure_id),
        reader_session_id TEXT NOT NULL
            REFERENCES reader_session(reader_session_id),
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_value JSONB NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        event_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        stable_idempotency_key TEXT NOT NULL,
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (event_type IN (
            'CHAPTER_OPEN', 'EFFECTIVE_READ', 'COMPLETION',
            'EXIT_POSITION', 'NEXT_CHAPTER_OPEN', 'RETENTION_3',
            'RETENTION_10', 'RETENTION_30', 'FAVORITE', 'FOLLOW',
            'NEGATIVE_FEEDBACK', 'REFUND', 'COMPLAINT'
        )),
        CHECK (jsonb_typeof(event_value) = 'object')
    )
    """,
    """
    CREATE TABLE chapter_outcome_metric (
        metric_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        chapter_asset_version_id TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        exposure_count INTEGER NOT NULL,
        outcome_count INTEGER NOT NULL,
        metric_type TEXT NOT NULL,
        window_start TIMESTAMPTZ NOT NULL,
        window_end TIMESTAMPTZ NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        CHECK (exposure_count >= 0),
        CHECK (outcome_count >= 0),
        CHECK (outcome_count <= exposure_count),
        CHECK (window_end >= window_start)
    )
    """,
    """
    CREATE TABLE retention_window_metric (
        retention_metric_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        platform TEXT NOT NULL,
        chapter_window INTEGER NOT NULL,
        exposure_count INTEGER NOT NULL,
        retained_count INTEGER NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (chapter_window IN (3, 10, 30)),
        CHECK (exposure_count >= 0 AND retained_count >= 0),
        CHECK (retained_count <= exposure_count)
    )
    """,
    """
    CREATE TABLE calibration_profile (
        profile_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        genre TEXT NOT NULL,
        subgenre TEXT NOT NULL,
        chapter_type TEXT NOT NULL,
        reader_segment TEXT NOT NULL,
        judge_profile TEXT NOT NULL,
        model_version TEXT NOT NULL,
        profile_version INTEGER NOT NULL,
        minimum_sample_size INTEGER NOT NULL,
        sample_size INTEGER NOT NULL,
        status TEXT NOT NULL,
        judge_mode TEXT NOT NULL,
        evidence_level TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            project_id, platform, genre, subgenre, chapter_type,
            reader_segment, judge_profile, model_version, profile_version
        ),
        CHECK (minimum_sample_size > 0),
        CHECK (sample_size >= 0),
        CHECK (status IN (
            'INSUFFICIENT_DATA', 'VALID', 'DRIFTED', 'INVALID'
        )),
        CHECK (judge_mode IN (
            'SHADOW', 'ADVISORY', 'BOUNDED_PRODUCTION'
        )),
        CHECK (evidence_level IN (
            'FIXTURE', 'HUMAN_ANCHORED', 'BEHAVIOR_CALIBRATED'
        )),
        CHECK (
            status <> 'VALID'
            OR sample_size >= minimum_sample_size
        ),
        CHECK (
            evidence_level <> 'FIXTURE'
            OR judge_mode = 'SHADOW'
        )
    )
    """,
    """
    CREATE TABLE calibration_run (
        calibration_run_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL REFERENCES calibration_profile(profile_id),
        project_id TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        input_manifest_ref TEXT NOT NULL,
        sample_size INTEGER NOT NULL,
        status TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        CHECK (sample_size >= 0),
        CHECK (status IN (
            'RUNNING', 'INSUFFICIENT_DATA', 'VALID', 'FAILED'
        ))
    )
    """,
    """
    CREATE TABLE calibration_metric (
        calibration_metric_id TEXT PRIMARY KEY,
        calibration_run_id TEXT NOT NULL
            REFERENCES calibration_run(calibration_run_id),
        metric_name TEXT NOT NULL,
        metric_value DOUBLE PRECISION,
        confidence_lower DOUBLE PRECISION,
        confidence_upper DOUBLE PRECISION,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(calibration_run_id, metric_name),
        CHECK (
            confidence_lower IS NULL OR confidence_upper IS NULL
            OR confidence_lower <= confidence_upper
        )
    )
    """,
    """
    CREATE TABLE calibration_residual (
        residual_id TEXT PRIMARY KEY,
        calibration_run_id TEXT NOT NULL
            REFERENCES calibration_run(calibration_run_id),
        project_id TEXT NOT NULL,
        segment_key TEXT NOT NULL,
        predicted_value DOUBLE PRECISION NOT NULL,
        observed_value DOUBLE PRECISION NOT NULL,
        residual DOUBLE PRECISION NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE calibration_validity (
        validity_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL REFERENCES calibration_profile(profile_id),
        project_id TEXT NOT NULL,
        drift_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence JSONB NOT NULL,
        detected_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (drift_type IN (
            'MODEL', 'PROMPT', 'PLATFORM', 'GENRE', 'SEGMENT',
            'BEHAVIOR', 'CALIBRATION_RESIDUAL'
        )),
        CHECK (severity IN ('INFO', 'WARNING', 'SEVERE')),
        CHECK (status IN ('CURRENT', 'SUPERSEDED')),
        CHECK (jsonb_typeof(evidence) = 'object')
    )
    """,
    """
    CREATE INDEX human_preference_task_query_idx
    ON human_preference_task(
        project_id, book_id, reader_segment, status, created_at DESC
    )
    """,
    """
    CREATE INDEX reader_exposure_scope_idx
    ON reader_exposure(
        project_id, book_id, reader_segment, platform, exposed_at
    )
    """,
    """
    CREATE INDEX reader_outcome_scope_idx
    ON reader_outcome_event(
        project_id, book_id, reader_segment, platform, event_type, occurred_at
    )
    """,
    """
    CREATE INDEX calibration_profile_resolution_idx
    ON calibration_profile(
        project_id, platform, genre, subgenre, chapter_type,
        reader_segment, judge_profile, model_version, status
    )
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []
