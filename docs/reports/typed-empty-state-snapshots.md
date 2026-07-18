# Typed Empty State Snapshots

The selected representation is `typed_empty_state_snapshot`: one independent,
append-only AssetVersion for each logical state kind. It contains project, previous
chapter, `state_kind`, `logical_asset_type`, `declared_empty=true`, reason, evidence,
and contract version.

Supported logical kinds are Canon, Character, Relationship, Timeline, Foreshadow,
Promise Ledger, Reward Ledger, World Rule, and Power State snapshots.

Preparation projects each typed declaration into its logical requirement while
Manifest and Context lineage retain its physical identity. Context, Canon reduction,
Long-form Quality, recap/ending input resolution, and snapshot queries distinguish
explicitly empty from missing. A declaration cannot replace an existing non-empty
snapshot, cross projects, or declare the wrong previous chapter.

Evidence: `production_preparation/typed_empty_state.py`, preparation tests, and
chapter-2 PostgreSQL Context/Canon tests.
