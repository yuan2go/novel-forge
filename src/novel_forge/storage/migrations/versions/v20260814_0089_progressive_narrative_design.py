from __future__ import annotations


MIGRATION_ID = "20260814_0089_progressive_narrative_design"
DOWN_REVISION = "20260814_0088_canonical_narrative_architecture"
FORWARD_ONLY = True
BACKUP_REQUIRED = False
FORWARD_FIX = (
    "Record immutable, layer-specific Narrative Qualification and bind one "
    "fail-closed long-form design admission into Book Production input snapshots"
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_narrative_design_qualification (
        qualification_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        book_id TEXT NOT NULL REFERENCES authority_book(book_id),
        asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        source_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        candidate_content_hash TEXT NOT NULL,
        design_layer TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        profile_version TEXT NOT NULL,
        profile_hash TEXT NOT NULL,
        capability_id TEXT NOT NULL,
        skill_ref TEXT NOT NULL,
        evaluator_execution_class TEXT NOT NULL,
        qualification_status TEXT NOT NULL,
        evaluation JSONB NOT NULL,
        evaluation_hash TEXT NOT NULL,
        qualification_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id, book_id)
            REFERENCES authority_book(project_id, book_id),
        UNIQUE(asset_version_id, design_layer, profile_version, evaluation_hash),
        CHECK (candidate_content_hash LIKE 'sha256:%'),
        CHECK (design_layer IN (
            'STORY_INTENT', 'STORY_FOUNDATION', 'BOOK_ARCHITECTURE',
            'VOLUME_ARCHITECTURE', 'NARRATIVE_ARC_GRAPH',
            'CHARACTER_DEVELOPMENT', 'DISCLOSURE_OBLIGATION',
            'NARRATIVE_SCHEDULING', 'CHAPTER_EXECUTION_PLAN',
            'SCENE_ARCHITECTURE'
        )),
        CHECK (profile_version ~ '^[1-9][0-9]*\\.[0-9]+\\.[0-9]+$'),
        CHECK (profile_hash LIKE 'sha256:%'),
        CHECK (evaluator_execution_class IN (
            'MODEL_PROVIDER', 'SCRIPTED_FIXTURE', 'OPERATOR_REVIEW'
        )),
        CHECK (qualification_status IN ('PASS', 'FAIL', 'INSUFFICIENT')),
        CHECK (jsonb_typeof(evaluation)='object'),
        CHECK (evaluation_hash LIKE 'sha256:%'),
        CHECK (qualification_hash LIKE 'sha256:%')
    )
    """,
    """
    CREATE INDEX authority_narrative_design_qualification_asset_idx
    ON authority_narrative_design_qualification(asset_version_id, design_layer)
    """,
    """
    CREATE INDEX authority_narrative_design_qualification_operation_idx
    ON authority_narrative_design_qualification(source_operation_id)
    """,
    """
    CREATE TRIGGER authority_narrative_design_qualification_immutable
    BEFORE UPDATE OR DELETE ON authority_narrative_design_qualification
    FOR EACH ROW EXECUTE FUNCTION novel_forge_reject_immutable_mutation()
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD COLUMN design_admission_status TEXT NOT NULL DEFAULT 'LEGACY_UNQUALIFIED',
    ADD COLUMN design_qualification JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN design_qualification_hash TEXT NOT NULL
        DEFAULT 'sha256:legacy-unqualified'
    """,
    """
    ALTER TABLE authority_book_production_input_snapshot
    ADD CONSTRAINT authority_book_production_design_admission_check
    CHECK (design_admission_status IN (
        'LEGACY_UNQUALIFIED', 'LONGFORM_DESIGN_QUALIFIED'
    )),
    ADD CONSTRAINT authority_book_production_design_qualification_shape_check
    CHECK (jsonb_typeof(design_qualification)='object'),
    ADD CONSTRAINT authority_book_production_design_qualification_hash_check
    CHECK (design_qualification_hash LIKE 'sha256:%')
    """,
    """
    CREATE INDEX authority_book_production_design_admission_idx
    ON authority_book_production_input_snapshot(
        project_id, book_id, design_admission_status, created_at DESC
    )
    """,
    """
    CREATE VIEW authority_current_narrative_design_qualification AS
    SELECT qualification.qualification_id,
           qualification.project_id,
           qualification.book_id,
           qualification.asset_version_id,
           qualification.source_operation_id,
           qualification.design_layer,
           qualification.profile_id,
           qualification.profile_version,
           qualification.profile_hash,
           qualification.capability_id,
           qualification.skill_ref,
           qualification.evaluator_execution_class,
           qualification.qualification_status,
           qualification.evaluation,
           qualification.evaluation_hash,
           qualification.qualification_hash,
           CASE
             WHEN book.current_book_design_asset_version_id=
                  qualification.asset_version_id THEN 'CURRENT'
             WHEN active.binding_id IS NOT NULL AND binding.freshness='CURRENT'
                  THEN 'CURRENT'
             ELSE 'HISTORICAL'
           END AS freshness
    FROM authority_narrative_design_qualification AS qualification
    LEFT JOIN authority_book AS book
      ON book.project_id=qualification.project_id
     AND book.book_id=qualification.book_id
    LEFT JOIN story_plan_binding AS binding
      ON binding.project_id=qualification.project_id
     AND binding.book_id=qualification.book_id
     AND binding.asset_version_id=qualification.asset_version_id
    LEFT JOIN active_story_plan_version AS active
      ON active.binding_id=binding.binding_id
    WHERE qualification.qualification_status='PASS'
    """,
    """
    CREATE VIEW authority_longform_design_admission_projection AS
    SELECT snapshot.snapshot_id,
           snapshot.project_id,
           snapshot.workspace_id,
           snapshot.book_id,
           snapshot.expected_book_version,
           snapshot.design_admission_status,
           snapshot.design_qualification,
           snapshot.design_qualification_hash,
           snapshot.resolved_by_operation_id,
           snapshot.created_at
    FROM authority_book_production_input_snapshot AS snapshot
    WHERE snapshot.design_admission_status='LONGFORM_DESIGN_QUALIFIED'
    """,
]


DOWNGRADE_STATEMENTS: list[str] = []
