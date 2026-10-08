from __future__ import annotations

MIGRATION_ID = "20261008_0182_source_market_observations"
DOWN_REVISION = "20261008_0181_author_manuscript_delivery"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Append Source rank definitions/attempts; preserve previous snapshots and Corpus identities."

UPGRADE_STATEMENTS = [
    """CREATE TABLE authority_source_market_site (
        host TEXT PRIMARY KEY CHECK(host='www.qidian.com'),
        next_request_at TIMESTAMPTZ NOT NULL,
        stopped_reason TEXT NOT NULL DEFAULT '',
        stopped_at TIMESTAMPTZ,
        blocked_until TIMESTAMPTZ
    )""",
    """CREATE TABLE authority_source_market_platform (
        project_id TEXT NOT NULL REFERENCES authority_project(project_id),
        platform TEXT NOT NULL CHECK(platform='qidian'),
        source_id TEXT NOT NULL,
        PRIMARY KEY(project_id,platform),
        UNIQUE(project_id,source_id),
        FOREIGN KEY(project_id,source_id) REFERENCES authority_corpus_source(project_id,source_id)
    )""",
    """CREATE TABLE authority_source_market_definition (
        definition_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        rank_key TEXT NOT NULL,
        previous_definition_id TEXT,
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id) DEFERRABLE INITIALLY DEFERRED,
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id,definition_id),
        FOREIGN KEY(project_id,source_id) REFERENCES authority_source_market_platform(project_id,source_id),
        FOREIGN KEY(project_id,previous_definition_id) REFERENCES authority_source_market_definition(project_id,definition_id)
    )""",
    "CREATE UNIQUE INDEX source_market_definition_chain_idx ON authority_source_market_definition(project_id,rank_key,COALESCE(previous_definition_id,''))",
    "CREATE INDEX source_market_definition_source_idx ON authority_source_market_definition(project_id,source_id,definition_id)",
    "CREATE INDEX source_market_definition_parent_idx ON authority_source_market_definition(previous_definition_id) WHERE previous_definition_id IS NOT NULL",
    "CREATE INDEX source_market_definition_asset_idx ON authority_source_market_definition(asset_version_id)",
    "CREATE INDEX source_market_definition_operation_idx ON authority_source_market_definition(created_by_operation_id)",
    """CREATE TABLE authority_source_market_attempt (
        attempt_record_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        definition_id TEXT NOT NULL,
        asset_version_id TEXT NOT NULL REFERENCES authority_asset_version(asset_version_id) DEFERRABLE INITIALLY DEFERRED,
        status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','NOT_MODIFIED','ACCESS_DENIED','RATE_LIMITED','CHALLENGE','LOGIN_REQUIRED','PARSE_DRIFT','TIMEOUT','UNSUPPORTED','REVOKED','REMOVED','TRANSPORT_FAILURE')),
        observed_at TIMESTAMPTZ NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id,definition_id) REFERENCES authority_source_market_definition(project_id,definition_id),
        UNIQUE(project_id,attempt_record_id)
    )""",
    "CREATE INDEX source_market_attempt_query_idx ON authority_source_market_attempt(project_id,definition_id,observed_at DESC,attempt_record_id)",
    "CREATE INDEX source_market_attempt_valid_idx ON authority_source_market_attempt(project_id,definition_id,observed_at DESC,attempt_record_id) WHERE status='COMPLETE'",
    "CREATE INDEX source_market_attempt_asset_idx ON authority_source_market_attempt(asset_version_id)",
    "CREATE INDEX source_market_attempt_operation_idx ON authority_source_market_attempt(created_by_operation_id)",
    """CREATE TABLE authority_source_market_metadata (
        metadata_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        book_source_id TEXT NOT NULL,
        content_hash TEXT NOT NULL CHECK(content_hash ~ '^sha256:[0-9a-f]{64}$'),
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(project_id,source_id,book_source_id) REFERENCES authority_corpus_book_identity(project_id,source_id,book_source_id),
        UNIQUE(book_source_id,content_hash)
    )""",
    "CREATE INDEX source_market_metadata_book_idx ON authority_source_market_metadata(project_id,book_source_id,metadata_id)",
    "CREATE INDEX source_market_metadata_source_idx ON authority_source_market_metadata(source_id)",
    "CREATE INDEX source_market_metadata_operation_idx ON authority_source_market_metadata(created_by_operation_id)",
    """CREATE TABLE authority_source_market_edition_link (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        book_source_id TEXT NOT NULL,
        edition_id TEXT NOT NULL,
        evidence_ref TEXT NOT NULL CHECK(length(evidence_ref)>0),
        created_by_operation_id TEXT NOT NULL REFERENCES authority_operation(operation_id),
        PRIMARY KEY(book_source_id,edition_id),
        FOREIGN KEY(project_id,source_id,book_source_id) REFERENCES authority_corpus_book_identity(project_id,source_id,book_source_id),
        FOREIGN KEY(project_id,edition_id) REFERENCES authority_corpus_edition(project_id,edition_id)
    )""",
    "CREATE INDEX source_market_link_edition_idx ON authority_source_market_edition_link(project_id,edition_id)",
    "CREATE INDEX source_market_link_source_idx ON authority_source_market_edition_link(source_id)",
    "CREATE INDEX source_market_link_operation_idx ON authority_source_market_edition_link(created_by_operation_id)",
]

for _table in ("definition", "attempt", "metadata", "edition_link"):
    UPGRADE_STATEMENTS.extend(
        [
            f"CREATE TRIGGER source_market_{_table}_scope BEFORE INSERT ON authority_source_market_{_table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_scope()",
            f"CREATE TRIGGER source_market_{_table}_immutable BEFORE UPDATE OR DELETE ON authority_source_market_{_table} FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()",
        ]
    )
UPGRADE_STATEMENTS.append(
    "CREATE TRIGGER source_market_platform_immutable BEFORE UPDATE OR DELETE ON authority_source_market_platform FOR EACH ROW EXECUTE FUNCTION authority_corpus_immutable()"
)

DOWNGRADE_STATEMENTS = []
