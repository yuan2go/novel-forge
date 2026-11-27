from __future__ import annotations


MIGRATION_ID = "20260811_0075_source_deconstruction_intelligence"
DOWN_REVISION = "20260811_0074_longform_native_intelligence"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = (
    "repair invalid Source/Observation/MKAOS lineage through its owning Authority, "
    "then create a new immutable Observation or reprocessing plan version"
)


UPGRADE_STATEMENTS = [
    """
    CREATE TABLE authority_source_evidence_span (
        evidence_span_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        source_document_id TEXT NOT NULL
            REFERENCES authority_source_document(source_document_id),
        source_transform_id TEXT NOT NULL
            REFERENCES authority_source_transform(source_transform_id),
        source_chunk_id TEXT NOT NULL
            REFERENCES authority_source_chunk(source_chunk_id),
        source_chunk_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        chunk_byte_start BIGINT NOT NULL,
        chunk_byte_end BIGINT NOT NULL,
        evidence_hash TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            source_chunk_asset_version_id, chunk_byte_start,
            chunk_byte_end, evidence_hash
        ),
        CHECK (chunk_byte_start >= 0),
        CHECK (chunk_byte_end > chunk_byte_start),
        CHECK (evidence_hash ~ '^sha256:[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE authority_source_deconstruction_observation (
        observation_id TEXT NOT NULL REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT PRIMARY KEY
            REFERENCES authority_asset_version(asset_version_id),
        execution_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        scope JSONB NOT NULL,
        scope_hash TEXT NOT NULL,
        dimension TEXT NOT NULL,
        scale TEXT NOT NULL,
        analyzer_id TEXT NOT NULL,
        analyzer_version TEXT NOT NULL,
        analyzer_contract_hash TEXT NOT NULL,
        prompt_id TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        skill_id TEXT NOT NULL,
        skill_version TEXT NOT NULL,
        capability_id TEXT NOT NULL,
        capability_version TEXT NOT NULL,
        provider_policy_version TEXT NOT NULL,
        aggregation_policy_version TEXT NOT NULL,
        observation_schema_version TEXT NOT NULL,
        observation_hash TEXT NOT NULL,
        confidence NUMERIC(7, 6) NOT NULL,
        evidence_class TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, scope_hash, analyzer_contract_hash, observation_hash),
        CHECK (jsonb_typeof(scope) = 'object'),
        CHECK (scope_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (analyzer_contract_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (observation_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (dimension IN (
            'structure', 'pacing', 'hook', 'reward_payoff', 'reader_promise',
            'conflict', 'character_mechanism', 'relationship_mechanism',
            'emotion_curve', 'foreshadowing', 'information_progression',
            'serialization', 'commercial_logic',
            'originality_copyright_risk'
        )),
        CHECK (scale IN (
            'CHAPTER', 'CHAPTER_WINDOW', 'CHAPTER_GROUP', 'ARC', 'VOLUME',
            'BOOK', 'CROSS_BOOK_PATTERN'
        )),
        CHECK (evidence_class IN (
            'DETERMINISTIC', 'FIXTURE', 'PROVIDER_UNCALIBRATED',
            'PROVIDER_QUALIFIED'
        ))
    )
    """,
    """
    CREATE TABLE authority_source_deconstruction_observation_input (
        observation_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_deconstruction_observation(asset_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        input_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        evidence_span_id TEXT
            REFERENCES authority_source_evidence_span(evidence_span_id),
        role TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(observation_asset_version_id, role, ordinal),
        UNIQUE(observation_asset_version_id, input_asset_version_id, role),
        CHECK (ordinal >= 0),
        CHECK (role IN (
            'SOURCE_CHUNK_EVIDENCE', 'LOWER_SCALE_OBSERVATION',
            'EXECUTION_EVIDENCE'
        )),
        CHECK (
            (role = 'SOURCE_CHUNK_EVIDENCE' AND evidence_span_id IS NOT NULL)
            OR (role <> 'SOURCE_CHUNK_EVIDENCE' AND evidence_span_id IS NULL)
        )
    )
    """,
    """
    CREATE TABLE authority_content_dependency (
        dependency_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        upstream_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        downstream_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        relationship TEXT NOT NULL,
        selector_key TEXT NOT NULL DEFAULT '',
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(
            upstream_asset_version_id, downstream_asset_version_id,
            relationship, selector_key
        ),
        CHECK (upstream_asset_version_id <> downstream_asset_version_id),
        CHECK (relationship IN (
            'EVIDENCES', 'AGGREGATES', 'ABSTRACTS', 'GOVERNS',
            'ACTIVATES', 'SELECTS', 'PROJECTS'
        ))
    )
    """,
    """
    CREATE TABLE authority_content_invalidation (
        invalidation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        target_asset_version_id TEXT NOT NULL
            REFERENCES authority_asset_version(asset_version_id),
        cause_type TEXT NOT NULL,
        cause_ref TEXT NOT NULL,
        dimension TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        resolved_by_operation_id TEXT
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMPTZ,
        UNIQUE(target_asset_version_id, cause_type, cause_ref),
        CHECK (cause_type IN (
            'ANALYZER_UPGRADE', 'SCHEMA_UPGRADE', 'PROMPT_UPGRADE',
            'SKILL_UPGRADE', 'POLICY_UPGRADE', 'UPSTREAM_REPLACED'
        )),
        CHECK (status IN ('OPEN', 'RESOLVED', 'SUPERSEDED')),
        CHECK (cause_ref <> '')
    )
    """,
    """
    CREATE TABLE authority_source_reprocessing_plan (
        reprocessing_plan_id TEXT NOT NULL REFERENCES authority_asset(asset_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        workspace_id TEXT NOT NULL REFERENCES authority_workspace(workspace_id),
        asset_version_id TEXT PRIMARY KEY
            REFERENCES authority_asset_version(asset_version_id),
        source_transform_id TEXT
            REFERENCES authority_source_transform(source_transform_id),
        desired_state_hash TEXT NOT NULL,
        plan_hash TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL UNIQUE
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, desired_state_hash, plan_hash),
        CHECK (desired_state_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (plan_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (item_count > 0),
        CHECK (status IN ('PLANNED', 'APPLIED', 'SUPERSEDED'))
    )
    """,
    """
    CREATE TABLE authority_source_reprocessing_plan_item (
        reprocessing_plan_asset_version_id TEXT NOT NULL
            REFERENCES authority_source_reprocessing_plan(asset_version_id),
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        ordinal INTEGER NOT NULL,
        target_key TEXT NOT NULL,
        dimension TEXT NOT NULL,
        scale TEXT NOT NULL,
        action TEXT NOT NULL,
        current_asset_version_id TEXT
            REFERENCES authority_asset_version(asset_version_id),
        desired_analyzer_contract_hash TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_by_operation_id TEXT NOT NULL
            REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(reprocessing_plan_asset_version_id, ordinal),
        UNIQUE(reprocessing_plan_asset_version_id, target_key, action),
        CHECK (ordinal >= 0),
        CHECK (target_key ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (desired_analyzer_contract_hash ~ '^sha256:[0-9a-f]{64}$'),
        CHECK (action IN (
            'REUSE', 'RECOMPUTE', 'RECOMPUTE_AGGREGATE',
            'REABSTRACT', 'REGOVERN', 'REBUILD_PROJECTION'
        )),
        CHECK (reason <> '')
    )
    """,
    "CREATE INDEX authority_source_evidence_span_project_idx ON authority_source_evidence_span(project_id, source_document_id, created_at DESC)",
    "CREATE INDEX authority_source_evidence_span_chunk_idx ON authority_source_evidence_span(source_chunk_asset_version_id, chunk_byte_start)",
    "CREATE INDEX authority_source_evidence_span_document_fk_idx ON authority_source_evidence_span(source_document_id)",
    "CREATE INDEX authority_source_evidence_span_transform_fk_idx ON authority_source_evidence_span(source_transform_id)",
    "CREATE INDEX authority_source_evidence_span_chunk_id_fk_idx ON authority_source_evidence_span(source_chunk_id)",
    "CREATE INDEX authority_source_evidence_span_operation_fk_idx ON authority_source_evidence_span(created_by_operation_id)",
    "CREATE INDEX authority_source_observation_scope_idx ON authority_source_deconstruction_observation(project_id, dimension, scale, scope_hash, created_at DESC)",
    "CREATE INDEX authority_source_observation_analyzer_idx ON authority_source_deconstruction_observation(project_id, analyzer_id, analyzer_version, created_at DESC)",
    "CREATE INDEX authority_source_observation_asset_fk_idx ON authority_source_deconstruction_observation(observation_id)",
    "CREATE INDEX authority_source_observation_workspace_fk_idx ON authority_source_deconstruction_observation(workspace_id)",
    "CREATE INDEX authority_source_observation_execution_fk_idx ON authority_source_deconstruction_observation(execution_asset_version_id)",
    "CREATE INDEX authority_source_observation_input_idx ON authority_source_deconstruction_observation_input(project_id, input_asset_version_id)",
    "CREATE INDEX authority_source_observation_input_asset_fk_idx ON authority_source_deconstruction_observation_input(input_asset_version_id)",
    "CREATE INDEX authority_source_observation_input_span_fk_idx ON authority_source_deconstruction_observation_input(evidence_span_id)",
    "CREATE INDEX authority_source_observation_input_operation_fk_idx ON authority_source_deconstruction_observation_input(created_by_operation_id)",
    "CREATE INDEX authority_content_dependency_upstream_idx ON authority_content_dependency(project_id, upstream_asset_version_id)",
    "CREATE INDEX authority_content_dependency_downstream_idx ON authority_content_dependency(project_id, downstream_asset_version_id)",
    "CREATE INDEX authority_content_dependency_downstream_fk_idx ON authority_content_dependency(downstream_asset_version_id)",
    "CREATE INDEX authority_content_dependency_operation_fk_idx ON authority_content_dependency(created_by_operation_id)",
    "CREATE INDEX authority_content_invalidation_open_idx ON authority_content_invalidation(project_id, target_asset_version_id) WHERE status='OPEN'",
    "CREATE INDEX authority_content_invalidation_project_fk_idx ON authority_content_invalidation(project_id)",
    "CREATE INDEX authority_content_invalidation_operation_fk_idx ON authority_content_invalidation(created_by_operation_id)",
    "CREATE INDEX authority_content_invalidation_resolution_fk_idx ON authority_content_invalidation(resolved_by_operation_id) WHERE resolved_by_operation_id IS NOT NULL",
    "CREATE INDEX authority_source_reprocessing_plan_project_idx ON authority_source_reprocessing_plan(project_id, created_at DESC)",
    "CREATE INDEX authority_source_reprocessing_plan_asset_fk_idx ON authority_source_reprocessing_plan(reprocessing_plan_id)",
    "CREATE INDEX authority_source_reprocessing_plan_workspace_fk_idx ON authority_source_reprocessing_plan(workspace_id)",
    "CREATE INDEX authority_source_reprocessing_plan_transform_fk_idx ON authority_source_reprocessing_plan(source_transform_id) WHERE source_transform_id IS NOT NULL",
    "CREATE INDEX authority_source_reprocessing_item_project_fk_idx ON authority_source_reprocessing_plan_item(project_id)",
    "CREATE INDEX authority_source_reprocessing_item_current_fk_idx ON authority_source_reprocessing_plan_item(current_asset_version_id) WHERE current_asset_version_id IS NOT NULL",
    "CREATE INDEX authority_source_reprocessing_item_operation_fk_idx ON authority_source_reprocessing_plan_item(created_by_operation_id)",
    """
    CREATE OR REPLACE FUNCTION authority_validate_source_intelligence_scope()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE payload JSONB := to_jsonb(NEW);
    DECLARE field_name TEXT;
    DECLARE asset_fields TEXT[];
    DECLARE workspace_project_id TEXT;
    DECLARE source_project_id TEXT;
    DECLARE transform_project_id TEXT;
    DECLARE evidence_chunk_matches BOOLEAN;
    BEGIN
        asset_fields := CASE TG_TABLE_NAME
            WHEN 'authority_source_evidence_span'
                THEN ARRAY['source_chunk_asset_version_id']
            WHEN 'authority_source_deconstruction_observation'
                THEN ARRAY['asset_version_id', 'execution_asset_version_id']
            WHEN 'authority_source_deconstruction_observation_input'
                THEN ARRAY['observation_asset_version_id', 'input_asset_version_id']
            WHEN 'authority_content_dependency'
                THEN ARRAY['upstream_asset_version_id', 'downstream_asset_version_id']
            WHEN 'authority_content_invalidation'
                THEN ARRAY['target_asset_version_id']
            WHEN 'authority_source_reprocessing_plan'
                THEN ARRAY['asset_version_id']
            WHEN 'authority_source_reprocessing_plan_item'
                THEN ARRAY['reprocessing_plan_asset_version_id', 'current_asset_version_id']
            ELSE ARRAY[]::TEXT[]
        END;
        FOREACH field_name IN ARRAY asset_fields LOOP
            PERFORM authority_require_asset_version_project(
                payload->>'project_id', payload->>field_name
            );
        END LOOP;
        IF payload ? 'created_by_operation_id' THEN
            PERFORM authority_require_operation_project(
                payload->>'project_id', payload->>'created_by_operation_id'
            );
        END IF;
        IF payload ? 'resolved_by_operation_id' THEN
            PERFORM authority_require_operation_project(
                payload->>'project_id', payload->>'resolved_by_operation_id'
            );
        END IF;
        IF payload ? 'workspace_id' THEN
            SELECT project_id INTO workspace_project_id
            FROM authority_workspace WHERE workspace_id=payload->>'workspace_id';
            IF workspace_project_id IS NULL OR workspace_project_id <> payload->>'project_id' THEN
                RAISE EXCEPTION 'Source intelligence Workspace belongs to another Project'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_source_intelligence_workspace_scope_check';
            END IF;
        END IF;
        IF payload ? 'source_document_id' THEN
            SELECT project_id INTO source_project_id
            FROM authority_source_document
            WHERE source_document_id=payload->>'source_document_id';
            IF source_project_id IS NULL OR source_project_id <> payload->>'project_id' THEN
                RAISE EXCEPTION 'SourceDocument belongs to another Project'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_source_intelligence_source_scope_check';
            END IF;
        END IF;
        IF payload ? 'source_transform_id'
           AND COALESCE(payload->>'source_transform_id', '') <> '' THEN
            SELECT project_id INTO transform_project_id
            FROM authority_source_transform
            WHERE source_transform_id=payload->>'source_transform_id';
            IF transform_project_id IS NULL
               OR transform_project_id <> payload->>'project_id' THEN
                RAISE EXCEPTION 'SourceTransform belongs to another Project'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_source_intelligence_transform_scope_check';
            END IF;
        END IF;
        IF TG_TABLE_NAME='authority_source_evidence_span' THEN
            SELECT EXISTS(
                SELECT 1 FROM authority_source_chunk AS chunk
                WHERE chunk.source_chunk_id=payload->>'source_chunk_id'
                  AND chunk.project_id=payload->>'project_id'
                  AND chunk.source_document_id=payload->>'source_document_id'
                  AND chunk.source_transform_id=payload->>'source_transform_id'
                  AND chunk.asset_version_id=
                      payload->>'source_chunk_asset_version_id'
            ) INTO evidence_chunk_matches;
            IF NOT evidence_chunk_matches THEN
                RAISE EXCEPTION 'EvidenceSpan SourceChunk lineage is inconsistent'
                    USING ERRCODE='23514',
                          CONSTRAINT='authority_source_evidence_span_lineage_check';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER {table}_scope_guard
        AFTER INSERT OR UPDATE ON {table}
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION authority_validate_source_intelligence_scope()
        """
        for table in (
            "authority_source_evidence_span",
            "authority_source_deconstruction_observation",
            "authority_source_deconstruction_observation_input",
            "authority_content_dependency",
            "authority_content_invalidation",
            "authority_source_reprocessing_plan",
            "authority_source_reprocessing_plan_item",
        )
    ],
]


DOWNGRADE_STATEMENTS: list[str] = []
