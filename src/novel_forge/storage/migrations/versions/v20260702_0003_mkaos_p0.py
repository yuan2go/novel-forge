from __future__ import annotations

MIGRATION_ID = "20260702_0003_mkaos_p0"
DOWN_REVISION: str | None = "20260628_0002_query_and_release_indexes"

UPGRADE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS source_documents (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        source_kind TEXT NOT NULL DEFAULT '',
        source_uri TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        clean_status TEXT NOT NULL DEFAULT 'pending',
        rights JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_chunks (
        id TEXT PRIMARY KEY,
        source_document_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
        source_asset_id TEXT NOT NULL DEFAULT '',
        chunk_index INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        raw_text TEXT NOT NULL DEFAULT '',
        clean_text TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (source_document_id, content_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_cards (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        concept_name TEXT NOT NULL,
        discipline TEXT NOT NULL DEFAULT '',
        sub_discipline TEXT NOT NULL DEFAULT '',
        knowledge_type TEXT NOT NULL DEFAULT '',
        source_chunk_ids TEXT[] NOT NULL DEFAULT '{}',
        confidence NUMERIC NOT NULL DEFAULT 0,
        source_reliability NUMERIC NOT NULL DEFAULT 0,
        risk_level TEXT NOT NULL DEFAULT 'low',
        status TEXT NOT NULL DEFAULT 'active',
        quality_score NUMERIC NOT NULL DEFAULT 0,
        weight NUMERIC NOT NULL DEFAULT 1,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_usage_bindings (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        knowledge_id TEXT NOT NULL,
        flow TEXT NOT NULL,
        usage_type TEXT NOT NULL DEFAULT '',
        usage_granularity TEXT NOT NULL DEFAULT '',
        input_role TEXT NOT NULL DEFAULT '',
        output_form TEXT NOT NULL DEFAULT '',
        review_rule_id TEXT NOT NULL DEFAULT '',
        template_id TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL DEFAULT 100,
        risk_level TEXT NOT NULL DEFAULT 'low',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_cards (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        rule_name TEXT NOT NULL,
        rule_type TEXT NOT NULL DEFAULT '',
        severity TEXT NOT NULL DEFAULT 'medium',
        blocking BOOLEAN NOT NULL DEFAULT FALSE,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        applicable_flows TEXT[] NOT NULL DEFAULT '{}',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS template_cards (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        template_name TEXT NOT NULL,
        template_type TEXT NOT NULL DEFAULT '',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        applicable_flows TEXT[] NOT NULL DEFAULT '{}',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_packs (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        task_id TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL DEFAULT '',
        workspace_path TEXT NOT NULL DEFAULT '',
        flow TEXT NOT NULL,
        chapter_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'built',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_pack_items (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        knowledge_pack_id TEXT NOT NULL,
        knowledge_id TEXT NOT NULL DEFAULT '',
        item_role TEXT NOT NULL,
        flow TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 100,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_usage_events (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        knowledge_id TEXT NOT NULL DEFAULT '',
        knowledge_pack_id TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL DEFAULT '',
        flow TEXT NOT NULL,
        target_artifact_id TEXT NOT NULL DEFAULT '',
        chapter_id TEXT NOT NULL DEFAULT '',
        agent_name TEXT NOT NULL DEFAULT '',
        used_as TEXT NOT NULL DEFAULT '',
        effect_score NUMERIC,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_quality_scores (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL UNIQUE,
        knowledge_id TEXT NOT NULL,
        flow TEXT NOT NULL DEFAULT '',
        delta NUMERIC NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mkaos_source_documents_project ON source_documents(project_id, workspace_path)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_source_chunks_source ON source_chunks(source_document_id, chunk_index)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_source_chunks_hash ON source_chunks(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_knowledge_cards_status ON knowledge_cards(status, risk_level)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_knowledge_cards_project ON knowledge_cards(project_id, workspace_path)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_bindings_flow ON knowledge_usage_bindings(flow, enabled)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_bindings_knowledge ON knowledge_usage_bindings(knowledge_id)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_rule_cards_flow ON rule_cards USING GIN(applicable_flows)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_template_cards_flow ON template_cards USING GIN(applicable_flows)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_packs_lookup ON knowledge_packs(project_id, flow, chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_pack_items_pack ON knowledge_pack_items(knowledge_pack_id, item_role)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_usage_events_lookup ON knowledge_usage_events(project_id, flow, chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_usage_events_knowledge ON knowledge_usage_events(knowledge_id)",
    "CREATE INDEX IF NOT EXISTS idx_mkaos_quality_scores_knowledge ON knowledge_quality_scores(knowledge_id, flow)",
]

DOWNGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_mkaos_quality_scores_knowledge",
    "DROP INDEX IF EXISTS idx_mkaos_usage_events_knowledge",
    "DROP INDEX IF EXISTS idx_mkaos_usage_events_lookup",
    "DROP INDEX IF EXISTS idx_mkaos_pack_items_pack",
    "DROP INDEX IF EXISTS idx_mkaos_packs_lookup",
    "DROP INDEX IF EXISTS idx_mkaos_template_cards_flow",
    "DROP INDEX IF EXISTS idx_mkaos_rule_cards_flow",
    "DROP INDEX IF EXISTS idx_mkaos_bindings_knowledge",
    "DROP INDEX IF EXISTS idx_mkaos_bindings_flow",
    "DROP INDEX IF EXISTS idx_mkaos_knowledge_cards_project",
    "DROP INDEX IF EXISTS idx_mkaos_knowledge_cards_status",
    "DROP INDEX IF EXISTS idx_mkaos_source_chunks_hash",
    "DROP INDEX IF EXISTS idx_mkaos_source_chunks_source",
    "DROP INDEX IF EXISTS idx_mkaos_source_documents_project",
]
