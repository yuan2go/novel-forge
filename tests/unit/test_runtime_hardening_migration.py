from novel_forge.storage.migrations import LATEST_MIGRATION_ID, validate_migration_chain
from novel_forge.storage.migrations.versions import (
    v20260821_0095_post_merge_correctness_repair as previous,
    v20260821_0096_runtime_hardening as migration,
)


def test_0096_is_forward_only_and_expands_arc_terminal_evidence() -> None:
    validate_migration_chain()
    sql = "\n".join(migration.UPGRADE_STATEMENTS)

    assert migration.DOWN_REVISION == previous.MIGRATION_ID
    assert migration.MIGRATION_ID == LATEST_MIGRATION_ID
    assert migration.FORWARD_ONLY is True
    for status in (
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
        "DEAD_LETTER",
        "CANCELLED",
        "RECONCILIATION_REQUIRED",
        "MANUAL_INTERVENTION",
    ):
        assert f"'{status}'" in sql
