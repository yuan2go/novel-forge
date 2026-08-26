from __future__ import annotations


MIGRATION_ID = "20260826_0101_quality_qualification"
DOWN_REVISION = "20260825_0100_hierarchy_closure"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "preserve historical Quality and human-preference rows; supersede only "
    "future qualification protocols through a later forward migration"
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_quality_qualification_campaign (
        campaign_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        manifest_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        manifest_hash TEXT NOT NULL,
        exact_release_sha TEXT NOT NULL,
        migration_head TEXT NOT NULL,
        protocol_version TEXT NOT NULL,
        evaluation_profile_version TEXT NOT NULL,
        quality_profile_version TEXT NOT NULL,
        reader_outcome_profile_version TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        qualification_status TEXT,
        human_evidence_status TEXT NOT NULL,
        required_evaluator_count INTEGER NOT NULL,
        chapter_start INTEGER NOT NULL,
        chapter_end INTEGER NOT NULL,
        chapter_group_ranges JSONB NOT NULL,
        provider_route_manifest JSONB NOT NULL,
        capability_pack_manifest JSONB NOT NULL,
        foundation_lineage JSONB NOT NULL,
        planning_lineage JSONB NOT NULL,
        realization_lineage JSONB NOT NULL,
        context_policy JSONB NOT NULL,
        budget_policy JSONB NOT NULL,
        stable_idempotency_key TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        frozen_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        version BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(project_id, stable_idempotency_key),
        CHECK (manifest_hash LIKE 'sha256:%'),
        CHECK (exact_release_sha ~ '^[0-9a-f]{40}$'),
        CHECK (migration_head <> ''),
        CHECK (lifecycle IN (
            'DRAFT','FROZEN','RUNNING','WAITING_HUMAN_EVIDENCE',
            'EVALUATING','COMPLETE','FAILED','ABORTED'
        )),
        CHECK (
            qualification_status IS NULL
            OR qualification_status IN (
                'PASS','PASS_WITH_LIMITATIONS','FAIL','NOT_PROVEN'
            )
        ),
        CHECK (human_evidence_status IN (
            'NOT_STARTED','WAITING_HUMAN_EVIDENCE','HUMAN_EVIDENCE_LIMITED',
            'BOUNDED_HUMAN_EVIDENCE'
        )),
        CHECK (required_evaluator_count >= 2),
        CHECK (chapter_start = 1 AND chapter_end = 8),
        CHECK (jsonb_typeof(chapter_group_ranges)='array'),
        CHECK (jsonb_array_length(chapter_group_ranges)=2),
        CHECK (jsonb_typeof(provider_route_manifest)='object'),
        CHECK (jsonb_typeof(capability_pack_manifest)='object'),
        CHECK (jsonb_typeof(foundation_lineage)='object'),
        CHECK (jsonb_typeof(planning_lineage)='object'),
        CHECK (jsonb_typeof(realization_lineage)='object'),
        CHECK (jsonb_typeof(context_policy)='object'),
        CHECK (jsonb_typeof(budget_policy)='object'),
        CHECK (
            lifecycle <> 'WAITING_HUMAN_EVIDENCE'
            OR qualification_status='NOT_PROVEN'
        ),
        CHECK (
            lifecycle NOT IN ('FROZEN','RUNNING','WAITING_HUMAN_EVIDENCE',
                              'EVALUATING','COMPLETE')
            OR frozen_at IS NOT NULL
        )
    )
    """,
    """
    CREATE TABLE authority_quality_qualification_subject (
        subject_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_campaign(campaign_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        scope_type TEXT NOT NULL,
        scope_key TEXT NOT NULL,
        chapter_start INTEGER NOT NULL,
        chapter_end INTEGER NOT NULL,
        arc_plan_version_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        canonical_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        canonical_content_hash TEXT NOT NULL,
        baseline_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        baseline_content_hash TEXT NOT NULL,
        chapter_plan_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        narrative_realization_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(campaign_id, scope_type, scope_key),
        CHECK (scope_type IN ('CHAPTER','ARC')),
        CHECK (chapter_start > 0 AND chapter_end >= chapter_start),
        CHECK (scope_type <> 'CHAPTER' OR chapter_start=chapter_end),
        CHECK (jsonb_typeof(arc_plan_version_ids)='array'),
        CHECK (canonical_asset_version_id <> baseline_asset_version_id),
        CHECK (canonical_content_hash LIKE 'sha256:%'),
        CHECK (baseline_content_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE TABLE authority_quality_qualification_evidence (
        evidence_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_campaign(campaign_id),
        subject_id TEXT
            REFERENCES authority_quality_qualification_subject(subject_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        evidence_layer TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        evidence_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        evidence_content_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        severity TEXT NOT NULL,
        source_asset_version_ids JSONB NOT NULL,
        evaluator_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
        provider_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(campaign_id, evidence_asset_version_id),
        CHECK (evidence_layer IN (
            'L1_HARD_CORRECTNESS',
            'L2_EDITORIAL_QUALITY',
            'L3_READER_LONGITUDINAL'
        )),
        CHECK (status IN (
            'PASS','PASS_WITH_LIMITATIONS','WARNING','FAIL','NOT_PROVEN',
            'NOT_OBSERVED','WAITING_HUMAN_EVIDENCE'
        )),
        CHECK (severity IN ('INFO','WARNING','MAJOR','SEVERE','BLOCKING')),
        CHECK (evidence_content_hash LIKE 'sha256:%'),
        CHECK (jsonb_typeof(source_asset_version_ids)='array'),
        CHECK (jsonb_typeof(evaluator_lineage)='object'),
        CHECK (jsonb_typeof(provider_lineage)='object')
    )
    """,
    """
    CREATE TABLE authority_quality_qualification_decision (
        decision_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_campaign(campaign_id),
        decision_version BIGINT NOT NULL,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        decision_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        decision_content_hash TEXT NOT NULL,
        qualification_status TEXT NOT NULL,
        campaign_lifecycle TEXT NOT NULL,
        human_evidence_status TEXT NOT NULL,
        hard_correctness_status TEXT NOT NULL,
        editorial_quality_status TEXT NOT NULL,
        reader_longitudinal_status TEXT NOT NULL,
        limitations JSONB NOT NULL,
        evidence_asset_version_ids JSONB NOT NULL,
        decided_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(campaign_id, decision_version),
        CHECK (decision_version > 0),
        CHECK (decision_content_hash LIKE 'sha256:%'),
        CHECK (qualification_status IN (
            'PASS','PASS_WITH_LIMITATIONS','FAIL','NOT_PROVEN'
        )),
        CHECK (campaign_lifecycle IN (
            'WAITING_HUMAN_EVIDENCE','COMPLETE','FAILED'
        )),
        CHECK (human_evidence_status IN (
            'WAITING_HUMAN_EVIDENCE','HUMAN_EVIDENCE_LIMITED',
            'BOUNDED_HUMAN_EVIDENCE'
        )),
        CHECK (hard_correctness_status IN (
            'PASS','PASS_WITH_LIMITATIONS','FAIL','NOT_PROVEN'
        )),
        CHECK (editorial_quality_status IN (
            'PASS','PASS_WITH_LIMITATIONS','FAIL','NOT_PROVEN'
        )),
        CHECK (reader_longitudinal_status IN (
            'PASS','PASS_WITH_LIMITATIONS','FAIL','NOT_PROVEN'
        )),
        CHECK (jsonb_typeof(limitations)='array'),
        CHECK (jsonb_typeof(evidence_asset_version_ids)='array'),
        CHECK (
            campaign_lifecycle <> 'WAITING_HUMAN_EVIDENCE'
            OR qualification_status='NOT_PROVEN'
        ),
        CHECK (
            hard_correctness_status <> 'FAIL'
            OR qualification_status='FAIL'
        )
    )
    """,
    """
    CREATE VIEW authority_current_quality_qualification_decision AS
    SELECT DISTINCT ON (campaign_id)
           decision_id, campaign_id, decision_version, project_id,
           decision_asset_version_id, decision_content_hash,
           qualification_status, campaign_lifecycle,
           human_evidence_status, hard_correctness_status,
           editorial_quality_status, reader_longitudinal_status,
           limitations, evidence_asset_version_ids,
           decided_by_operation_id, created_at
    FROM authority_quality_qualification_decision
    ORDER BY campaign_id, decision_version DESC, created_at DESC, decision_id DESC
    """,
    """
    ALTER TABLE human_preference_task
    ADD COLUMN campaign_id TEXT
        REFERENCES authority_quality_qualification_campaign(campaign_id),
    ADD COLUMN protocol_version TEXT,
    ADD COLUMN evaluation_profile_version TEXT,
    ADD COLUMN required_evaluator_count INTEGER,
    ADD COLUMN evaluator_identity_classes JSONB,
    ADD COLUMN scope_manifest JSONB,
    ADD COLUMN blind_pack_status TEXT,
    ADD CONSTRAINT human_preference_task_quality_protocol_check CHECK (
        protocol_version IS NULL OR (
            campaign_id IS NOT NULL
            AND evaluation_profile_version IS NOT NULL
            AND required_evaluator_count >= 2
            AND jsonb_typeof(evaluator_identity_classes)='array'
            AND jsonb_typeof(scope_manifest)='object'
            AND blind_pack_status IN ('PENDING','EXPORTED','PARTIAL','COMPLETE')
        )
    )
    """,
    """
    CREATE TABLE human_preference_evaluation_pack (
        pack_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES human_preference_task(task_id),
        campaign_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_campaign(campaign_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        reviewer_id TEXT NOT NULL,
        evaluator_identity_class TEXT NOT NULL,
        protocol_version TEXT NOT NULL,
        evaluation_profile_version TEXT NOT NULL,
        pack_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        pack_content_hash TEXT NOT NULL,
        private_mapping_hash TEXT NOT NULL,
        pair_count INTEGER NOT NULL,
        chapter_pair_count INTEGER NOT NULL,
        arc_pair_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        exported_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(task_id, reviewer_id),
        CHECK (pack_content_hash LIKE 'sha256:%'),
        CHECK (private_mapping_hash LIKE 'sha256:%'),
        CHECK (pair_count > 0),
        CHECK (chapter_pair_count = 8),
        CHECK (arc_pair_count >= 1),
        CHECK (pair_count=chapter_pair_count+arc_pair_count),
        CHECK (status IN ('EXPORTED','IN_PROGRESS','COMPLETED','INVALIDATED'))
    )
    """,
    """
    ALTER TABLE human_preference_pair
    ADD COLUMN subject_id TEXT
        REFERENCES authority_quality_qualification_subject(subject_id),
    ADD COLUMN pack_id TEXT
        REFERENCES human_preference_evaluation_pack(pack_id),
    ADD COLUMN protocol_version TEXT,
    ADD COLUMN scope_type TEXT,
    ADD COLUMN chapter_start INTEGER,
    ADD COLUMN chapter_end INTEGER,
    ADD COLUMN arc_plan_version_ids JSONB,
    ADD COLUMN pair_ordinal INTEGER,
    ADD COLUMN assigned_reviewer_id TEXT,
    ADD COLUMN blind_pair_token TEXT UNIQUE,
    ADD COLUMN private_mapping_hash TEXT,
    ADD CONSTRAINT human_preference_pair_quality_protocol_check CHECK (
        protocol_version IS NULL OR (
            subject_id IS NOT NULL
            AND pack_id IS NOT NULL
            AND scope_type IN ('CHAPTER','ARC')
            AND chapter_start > 0
            AND chapter_end >= chapter_start
            AND (scope_type <> 'CHAPTER' OR chapter_start=chapter_end)
            AND jsonb_typeof(arc_plan_version_ids)='array'
            AND pair_ordinal > 0
            AND assigned_reviewer_id IS NOT NULL
            AND blind_pair_token IS NOT NULL
            AND private_mapping_hash LIKE 'sha256:%'
        )
    )
    """,
    """
    ALTER TABLE human_preference_decision
    DROP CONSTRAINT human_preference_decision_choice_check,
    DROP CONSTRAINT human_preference_decision_check,
    DROP CONSTRAINT human_preference_decision_position_revealed_after_decisio_check
    """,
    """
    ALTER TABLE human_preference_decision
    ADD COLUMN pack_id TEXT
        REFERENCES human_preference_evaluation_pack(pack_id),
    ADD COLUMN protocol_version TEXT,
    ADD COLUMN evaluation_version TEXT,
    ADD COLUMN evaluator_identity_class TEXT,
    ADD COLUMN scope_type TEXT,
    ADD COLUMN dimension_scores JSONB,
    ADD COLUMN adjudication_status TEXT,
    ADD COLUMN submitted_at TIMESTAMPTZ,
    ADD CONSTRAINT human_preference_decision_choice_check CHECK (
        choice IN ('A','B','TIE','REJECT_BOTH','CANNOT_JUDGE')
    ),
    ADD CONSTRAINT human_preference_decision_preference_check CHECK (
        (choice IN ('A','B') AND preferred_asset_version_id IS NOT NULL)
        OR (
            choice IN ('TIE','REJECT_BOTH','CANNOT_JUDGE')
            AND preferred_asset_version_id IS NULL
        )
    ),
    ADD CONSTRAINT human_preference_decision_quality_protocol_check CHECK (
        protocol_version IS NULL OR (
            pack_id IS NOT NULL
            AND evaluation_version IS NOT NULL
            AND evaluator_identity_class IS NOT NULL
            AND scope_type IN ('CHAPTER','ARC')
            AND jsonb_typeof(dimension_scores)='object'
            AND adjudication_status IN (
                'UNREVIEWED','AGREED','DISAGREED','ADJUDICATED'
            )
            AND submitted_at IS NOT NULL
            AND choice <> 'REJECT_BOTH'
            AND position_revealed_after_decision=FALSE
        )
    )
    """,
    """
    CREATE TABLE human_preference_adjudication (
        adjudication_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_campaign(campaign_id),
        task_id TEXT NOT NULL REFERENCES human_preference_task(task_id),
        subject_id TEXT NOT NULL
            REFERENCES authority_quality_qualification_subject(subject_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        protocol_version TEXT NOT NULL,
        evaluation_version TEXT NOT NULL,
        status TEXT NOT NULL,
        resolved_choice TEXT,
        dimension_scores JSONB NOT NULL,
        source_decision_ids JSONB NOT NULL,
        adjudicator_id TEXT NOT NULL,
        evaluator_identity_class TEXT NOT NULL,
        rationale TEXT NOT NULL,
        adjudication_asset_version_id TEXT NOT NULL UNIQUE
            REFERENCES authority_asset_version(asset_version_id),
        adjudication_content_hash TEXT NOT NULL,
        adjudication_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(task_id, subject_id),
        CHECK (status IN (
            'AGREED','DISAGREED','ADJUDICATED','CANNOT_ADJUDICATE'
        )),
        CHECK (
            resolved_choice IS NULL
            OR resolved_choice IN ('A','B','TIE','CANNOT_JUDGE')
        ),
        CHECK (jsonb_typeof(dimension_scores)='object'),
        CHECK (jsonb_typeof(source_decision_ids)='array'),
        CHECK (jsonb_array_length(source_decision_ids)>=2),
        CHECK (adjudication_content_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE INDEX authority_quality_campaign_lifecycle_idx
    ON authority_quality_qualification_campaign(
        lifecycle, updated_at, campaign_id
    )
    WHERE lifecycle IN (
        'DRAFT','FROZEN','RUNNING','WAITING_HUMAN_EVIDENCE','EVALUATING'
    )
    """,
    """
    CREATE INDEX authority_quality_subject_campaign_idx
    ON authority_quality_qualification_subject(
        campaign_id, scope_type, chapter_start, chapter_end
    )
    """,
    """
    CREATE INDEX authority_quality_evidence_campaign_layer_idx
    ON authority_quality_qualification_evidence(
        campaign_id, evidence_layer, status
    )
    """,
    """
    CREATE INDEX human_preference_pack_campaign_idx
    ON human_preference_evaluation_pack(campaign_id, status, reviewer_id)
    """,
    """
    CREATE INDEX human_preference_pair_pack_idx
    ON human_preference_pair(pack_id, pair_ordinal)
    WHERE pack_id IS NOT NULL
    """,
]

DOWNGRADE_STATEMENTS: list[str] = []


def upgrade(connection) -> None:
    with connection.cursor() as cursor:
        for statement in UPGRADE_STATEMENTS:
            cursor.execute(statement)


__all__ = [
    "BACKUP_REQUIRED",
    "DOWN_REVISION",
    "DOWNGRADE_STATEMENTS",
    "FORWARD_FIX",
    "FORWARD_ONLY",
    "MIGRATION_ID",
    "UPGRADE_STATEMENTS",
    "upgrade",
]
