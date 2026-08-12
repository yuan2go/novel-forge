from __future__ import annotations


MIGRATION_ID = "20260811_0081_source_intelligence_router"
DOWN_REVISION = "20260811_0080_source_snapshot_governance_identity"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair Source Profile/AnalysisPlan scope or lineage through Source Authority, "
    "then retry the forward migration"
)


_CONTENT_TYPES = """
    'WEB_NOVEL', 'PUBLISHED_FICTION', 'CLASSIC_LITERATURE',
    'WRITING_THEORY', 'PROFESSIONAL_KNOWLEDGE',
    'HISTORY_SOCIAL_SCIENCE', 'BIOGRAPHY_MEMOIR',
    'PHILOSOPHY_ESSAY', 'PLATFORM_RULES', 'UNKNOWN', 'MIXED'
"""


UPGRADE_STATEMENTS = [
    """
    ALTER TABLE authority_source_import_job
      RENAME COLUMN analysis_profile TO legacy_analysis_profile
    """,
    """
    ALTER TABLE authority_source_import_job
      ALTER COLUMN legacy_analysis_profile DROP NOT NULL,
      ADD COLUMN intelligence_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD COLUMN intelligence_policy_hash TEXT,
      ADD COLUMN analysis_override JSONB NOT NULL DEFAULT '{}'::jsonb,
      ADD CONSTRAINT authority_source_import_job_intelligence_json_check CHECK (
        jsonb_typeof(intelligence_policy)='object'
        AND jsonb_typeof(analysis_override)='object'
      )
    """,
    """
    UPDATE authority_source_import_job
    SET intelligence_policy=jsonb_build_object(
          'policy_version', 'legacy-source-intelligence-policy.v0',
          'migration_source', 'authority_source_import_job.analysis_profile',
          'automatic_routing_enabled', false
        )
    WHERE intelligence_policy='{}'::jsonb
    """,
    """
    UPDATE authority_source_import_job
    SET intelligence_policy_hash='sha256:' || encode(
      digest(convert_to(intelligence_policy::text, 'UTF8'), 'sha256'), 'hex'
    )
    WHERE intelligence_policy_hash IS NULL
    """,
    """
    ALTER TABLE authority_source_import_job
      ALTER COLUMN intelligence_policy_hash SET NOT NULL,
      ADD CONSTRAINT authority_source_import_job_intelligence_hash_check CHECK (
        intelligence_policy_hash ~ '^sha256:[0-9a-f]{64}$'
      )
    """,
    f"""
    CREATE TABLE authority_source_content_profile (
        source_content_profile_id TEXT NOT NULL
            REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT PRIMARY KEY
            REFERENCES authority_asset_version(asset_version_id),
        source_document_id TEXT NOT NULL
            REFERENCES authority_source_document(source_document_id),
        source_transform_id TEXT NOT NULL
            REFERENCES authority_source_transform(source_transform_id),
        logical_document_scope JSONB NOT NULL,
        logical_document_scope_hash TEXT NOT NULL,
        boundary_policy_version TEXT NOT NULL,
        classifier_id TEXT NOT NULL,
        classifier_version TEXT NOT NULL,
        classifier_prompt_version TEXT NOT NULL,
        classifier_schema_version TEXT NOT NULL,
        classifier_contract_hash TEXT NOT NULL,
        classification_input_hash TEXT NOT NULL,
        classification_output_hash TEXT NOT NULL,
        intelligence_policy_hash TEXT NOT NULL,
        override_contract_hash TEXT NOT NULL DEFAULT '',
        execution_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        evidence JSONB NOT NULL,
        predicted_content_type TEXT NOT NULL,
        resolved_content_type TEXT NOT NULL,
        confidence NUMERIC(7, 6) NOT NULL,
        margin NUMERIC(7, 6) NOT NULL,
        resolution_mode TEXT NOT NULL,
        resolution_reasons JSONB NOT NULL,
        override_decision_ref TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        manual_review_required BOOLEAN NOT NULL,
        evidence_class TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
          project_id, logical_document_scope_hash, classifier_contract_hash,
          intelligence_policy_hash, override_contract_hash,
          classification_input_hash, classification_output_hash
        ),
        CHECK (jsonb_typeof(logical_document_scope)='object'),
        CHECK (jsonb_typeof(evidence)='object'),
        CHECK (jsonb_typeof(resolution_reasons)='array'),
        CHECK (logical_document_scope_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (classifier_contract_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (classification_input_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (classification_output_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (intelligence_policy_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (
          override_contract_hash='' OR
          override_contract_hash ~ '^sha256:[0-9a-f]{{64}}$'
        ),
        CHECK (predicted_content_type IN ({_CONTENT_TYPES})),
        CHECK (resolved_content_type IN ({_CONTENT_TYPES})),
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (margin >= 0 AND margin <= 1),
        CHECK (resolution_mode IN ('AUTOMATIC', 'GOVERNANCE_OVERRIDE')),
        CHECK (status IN ('ROUTABLE', 'NEEDS_REVIEW', 'FAILED')),
        CHECK (evidence_class IN (
          'FIXTURE', 'PROVIDER_UNCALIBRATED', 'PROVIDER_QUALIFIED'
        )),
        CHECK (
          (status='ROUTABLE' AND manual_review_required=false
           AND resolved_content_type NOT IN ('UNKNOWN', 'MIXED'))
          OR (status<>'ROUTABLE' AND manual_review_required=true)
        ),
        CHECK (
          (resolution_mode='AUTOMATIC' AND override_contract_hash=''
           AND override_decision_ref='')
          OR (resolution_mode='GOVERNANCE_OVERRIDE'
              AND override_contract_hash<>'' AND override_decision_ref<>'')
        )
    )
    """,
    """
    CREATE TABLE authority_source_content_profile_input (
        profile_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_content_profile(asset_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        input_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        role TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        sample_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(profile_asset_version_id, role, ordinal),
        UNIQUE(profile_asset_version_id, input_asset_version_id, role),
        CHECK (role IN ('SOURCE_CHUNK', 'CLASSIFIER_EXECUTION')),
        CHECK (ordinal >= 0),
        CHECK (jsonb_typeof(sample_manifest)='object')
    )
    """,
    f"""
    CREATE TABLE authority_source_analysis_plan (
        source_analysis_plan_id TEXT NOT NULL
            REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT PRIMARY KEY
            REFERENCES authority_asset_version(asset_version_id),
        profile_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_content_profile(asset_version_id),
        logical_document_scope_hash TEXT NOT NULL,
        resolved_content_type TEXT NOT NULL,
        routing_policy_version TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        profile_version TEXT NOT NULL,
        strategy_contract_hash TEXT NOT NULL,
        methodology_contract_hash TEXT NOT NULL,
        methodologies JSONB NOT NULL,
        mkaos_capability TEXT NOT NULL,
        abstraction_policy_version TEXT NOT NULL,
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
          project_id, profile_asset_version_id, strategy_contract_hash,
          methodology_contract_hash
        ),
        CHECK (logical_document_scope_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (resolved_content_type IN ({_CONTENT_TYPES})),
        CHECK (resolved_content_type NOT IN ('UNKNOWN', 'MIXED')),
        CHECK (strategy_contract_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (methodology_contract_hash ~ '^sha256:[0-9a-f]{{64}}$'),
        CHECK (jsonb_typeof(methodologies)='array'),
        CHECK (jsonb_array_length(methodologies)>0),
        CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'BLOCKED'))
    )
    """,
    """
    ALTER TABLE authority_source_repository_file
      ADD COLUMN source_content_profile_asset_version_id TEXT
        REFERENCES authority_source_content_profile(asset_version_id),
      ADD COLUMN source_analysis_plan_asset_version_id TEXT
        REFERENCES authority_source_analysis_plan(asset_version_id)
    """,
    """
    ALTER TABLE authority_source_import_work
      DROP CONSTRAINT authority_source_import_work_work_kind_check,
      ADD CONSTRAINT authority_source_import_work_work_kind_check CHECK (
        work_kind IN (
          'DISCOVERY', 'FILE', 'PROFILING', 'ANALYSIS_PLANNING',
          'DECONSTRUCTION', 'MKAOS_EXTRACTION', 'REPROCESSING',
          'PROJECTION_REBUILD', 'GOVERNANCE_REVIEW'
        )
      )
    """,
    """
    ALTER TABLE authority_source_repository_file
      DROP CONSTRAINT authority_source_repository_file_status_check,
      ADD CONSTRAINT authority_source_repository_file_status_check CHECK (
        status IN (
          'DISCOVERED', 'BLOCKED', 'REUSED', 'QUEUED', 'PROCESSING',
          'TRANSFORMED', 'PROFILING', 'PROFILED',
          'PROFILE_REVIEW_REQUIRED', 'ANALYZING', 'CANDIDATE_READY',
          'FAILED_RETRYABLE', 'FAILED_FINAL', 'REMOVED'
        )
      )
    """,
    """
    ALTER TABLE authority_source_deconstruction_observation
      ADD COLUMN analysis_plan_asset_version_id TEXT
        REFERENCES authority_source_analysis_plan(asset_version_id),
      ADD COLUMN methodology_content_hash TEXT,
      ADD COLUMN analysis_lineage_version TEXT NOT NULL DEFAULT 'legacy.v0',
      ADD CONSTRAINT authority_source_observation_analysis_lineage_check CHECK (
        (analysis_lineage_version='legacy.v0'
         AND analysis_plan_asset_version_id IS NULL
         AND methodology_content_hash IS NULL)
        OR (analysis_lineage_version='source-analysis-lineage.v1'
            AND analysis_plan_asset_version_id IS NOT NULL
            AND methodology_content_hash ~ '^sha256:[0-9a-f]{64}$')
      )
    """,
    """
    ALTER TABLE authority_source_deconstruction_observation
      DROP CONSTRAINT
        authority_source_deconstructi_project_id_scope_hash_analyze_key
    """,
    """
    CREATE UNIQUE INDEX authority_source_observation_analysis_identity_key
      ON authority_source_deconstruction_observation(
        project_id, scope_hash, analyzer_contract_hash,
        COALESCE(analysis_plan_asset_version_id, ''), observation_hash
      )
    """,
    """
    ALTER TABLE authority_source_deconstruction_observation
      DROP CONSTRAINT authority_source_deconstruction_observation_dimension_check,
      ADD CONSTRAINT authority_source_deconstruction_observation_dimension_check CHECK (
        dimension IN (
          'structure', 'pacing', 'hook', 'reward_payoff', 'reader_promise',
          'conflict', 'character_mechanism', 'relationship_mechanism',
          'emotion_curve', 'foreshadowing', 'information_progression',
          'serialization', 'commercial_logic', 'originality_copyright_risk',
          'scene_craft', 'narrative_distance', 'character_arc', 'subtext',
          'transition', 'theme_system', 'social_pressure', 'symbol_function',
          'fate_curve', 'moral_dilemma', 'craft_principle',
          'causal_constraints', 'misuse_risk', 'review_check', 'core_concept',
          'credibility_rule', 'conflict_generator', 'historical_causality',
          'institutional_constraint', 'social_dynamics', 'source_reliability',
          'argument_structure', 'concept_definition', 'assumption',
          'counterargument', 'platform_policy', 'eligibility_rule',
          'retention_constraint', 'release_constraint', 'compliance_risk'
        )
      ),
      DROP CONSTRAINT authority_source_deconstruction_observation_scale_check,
      ADD CONSTRAINT authority_source_deconstruction_observation_scale_check CHECK (
        scale IN (
          'CHAPTER', 'CHAPTER_WINDOW', 'CHAPTER_GROUP', 'ARC', 'VOLUME',
          'BOOK', 'CROSS_BOOK_PATTERN', 'DOCUMENT_SECTION', 'LOGICAL_DOCUMENT'
        )
      )
    """,
    """
    ALTER TABLE authority_source_deconstruction_observation_input
      DROP CONSTRAINT authority_source_deconstruction_observation_input_role_check,
      ADD CONSTRAINT authority_source_deconstruction_observation_input_role_check CHECK (
        role IN (
          'SOURCE_CHUNK_EVIDENCE', 'LOWER_SCALE_OBSERVATION',
          'EXECUTION_EVIDENCE', 'ANALYSIS_PLAN'
        )
      ),
      DROP CONSTRAINT authority_source_deconstruction_observation_input_check,
      ADD CONSTRAINT authority_source_deconstruction_observation_input_check CHECK (
        (role='SOURCE_CHUNK_EVIDENCE' AND evidence_span_id IS NOT NULL)
        OR (role<>'SOURCE_CHUNK_EVIDENCE' AND evidence_span_id IS NULL)
      )
    """,
    """
    ALTER TABLE authority_content_dependency
      DROP CONSTRAINT authority_content_dependency_relationship_check,
      ADD CONSTRAINT authority_content_dependency_relationship_check CHECK (
        relationship IN (
          'EVIDENCES', 'AGGREGATES', 'ABSTRACTS', 'GOVERNS', 'ACTIVATES',
          'SELECTS', 'PROJECTS', 'PROFILES', 'ROUTES', 'PLANS'
        )
      )
    """,
    """
    ALTER TABLE authority_content_invalidation
      DROP CONSTRAINT authority_content_invalidation_cause_type_check,
      ADD CONSTRAINT authority_content_invalidation_cause_type_check CHECK (
        cause_type IN (
          'ANALYZER_UPGRADE', 'SCHEMA_UPGRADE', 'PROMPT_UPGRADE',
          'SKILL_UPGRADE', 'POLICY_UPGRADE', 'UPSTREAM_REPLACED',
          'CLASSIFIER_UPGRADE', 'ROUTING_POLICY_UPGRADE',
          'METHODOLOGY_UPGRADE', 'PROFILE_OVERRIDE'
        )
      )
    """,
    """
    CREATE INDEX authority_source_content_profile_current_idx
      ON authority_source_content_profile(
        project_id, source_transform_id, logical_document_scope_hash,
        created_at DESC
      )
    """,
    """
    CREATE INDEX authority_source_content_profile_classifier_idx
      ON authority_source_content_profile(
        project_id, classifier_id, classifier_version, status, created_at DESC
      )
    """,
    """
    CREATE INDEX authority_source_content_profile_asset_fk_idx
      ON authority_source_content_profile(source_content_profile_id)
    """,
    """
    CREATE INDEX authority_source_content_profile_workspace_fk_idx
      ON authority_source_content_profile(workspace_id)
    """,
    """
    CREATE INDEX authority_source_content_profile_document_fk_idx
      ON authority_source_content_profile(source_document_id)
    """,
    """
    CREATE INDEX authority_source_content_profile_execution_fk_idx
      ON authority_source_content_profile(execution_asset_version_id)
    """,
    """
    CREATE INDEX authority_source_content_profile_input_idx
      ON authority_source_content_profile_input(project_id, input_asset_version_id)
    """,
    """
    CREATE INDEX authority_source_content_profile_input_operation_fk_idx
      ON authority_source_content_profile_input(created_by_operation_id)
    """,
    """
    CREATE INDEX authority_source_analysis_plan_current_idx
      ON authority_source_analysis_plan(
        project_id, logical_document_scope_hash, status, created_at DESC
      )
    """,
    """
    CREATE INDEX authority_source_analysis_plan_profile_idx
      ON authority_source_analysis_plan(profile_asset_version_id)
    """,
    """
    CREATE INDEX authority_source_analysis_plan_asset_fk_idx
      ON authority_source_analysis_plan(source_analysis_plan_id)
    """,
    """
    CREATE INDEX authority_source_analysis_plan_workspace_fk_idx
      ON authority_source_analysis_plan(workspace_id)
    """,
    """
    CREATE INDEX authority_source_repository_file_profile_idx
      ON authority_source_repository_file(source_content_profile_asset_version_id)
      WHERE source_content_profile_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_repository_file_plan_idx
      ON authority_source_repository_file(source_analysis_plan_asset_version_id)
      WHERE source_analysis_plan_asset_version_id IS NOT NULL
    """,
    """
    CREATE INDEX authority_source_observation_plan_idx
      ON authority_source_deconstruction_observation(analysis_plan_asset_version_id)
      WHERE analysis_plan_asset_version_id IS NOT NULL
    """,
    """
    CREATE OR REPLACE FUNCTION authority_validate_source_profile_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE payload JSONB := to_jsonb(NEW);
    DECLARE expected_project TEXT := payload->>'project_id';
    DECLARE actual_project TEXT;
    DECLARE ref_value TEXT;
    BEGIN
      FOREACH ref_value IN ARRAY ARRAY[
        payload->>'asset_version_id', payload->>'profile_asset_version_id',
        payload->>'input_asset_version_id', payload->>'execution_asset_version_id'
      ] LOOP
        IF COALESCE(ref_value, '') <> '' THEN
          PERFORM authority_require_asset_version_project(expected_project, ref_value);
        END IF;
      END LOOP;
      IF COALESCE(payload->>'workspace_id', '') <> '' THEN
        SELECT project_id INTO actual_project
        FROM authority_workspace WHERE workspace_id=payload->>'workspace_id';
        IF actual_project IS DISTINCT FROM expected_project THEN
          RAISE EXCEPTION 'Source Profile Workspace scope mismatch';
        END IF;
      END IF;
      IF COALESCE(payload->>'source_document_id', '') <> '' THEN
        SELECT project_id INTO actual_project FROM authority_source_document
        WHERE source_document_id=payload->>'source_document_id';
        IF actual_project IS DISTINCT FROM expected_project THEN
          RAISE EXCEPTION 'Source Profile SourceDocument scope mismatch';
        END IF;
      END IF;
      IF COALESCE(payload->>'source_transform_id', '') <> '' THEN
        SELECT project_id INTO actual_project FROM authority_source_transform
        WHERE source_transform_id=payload->>'source_transform_id';
        IF actual_project IS DISTINCT FROM expected_project THEN
          RAISE EXCEPTION 'Source Profile SourceTransform scope mismatch';
        END IF;
      END IF;
      IF COALESCE(payload->>'created_by_operation_id', '') <> '' THEN
        PERFORM authority_require_operation_project(
          expected_project, payload->>'created_by_operation_id'
        );
      END IF;
      RETURN NEW;
    END;
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER {table}_source_profile_scope_guard
        AFTER INSERT OR UPDATE ON {table}
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION authority_validate_source_profile_scope()
        """
        for table in (
            "authority_source_content_profile",
            "authority_source_content_profile_input",
            "authority_source_analysis_plan",
        )
    ],
]


DOWNGRADE_STATEMENTS: list[str] = []
