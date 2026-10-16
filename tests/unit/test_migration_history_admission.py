from unittest.mock import MagicMock, patch

import pytest

from novel_forge.storage.migrations import MIGRATIONS, pending_migrations, run_migrations


@pytest.mark.parametrize(
    "applied",
    [
        {"20261006_0157_planning_result_admission"},
        {MIGRATIONS[1].migration_id},
        {MIGRATIONS[0].migration_id, MIGRATIONS[2].migration_id},
    ],
)
def test_foreign_or_discontinuous_history_is_rejected_before_pending_ddl(applied):
    with pytest.raises(ValueError, match="MIGRATION_HISTORY"):
        pending_migrations(applied)


def test_run_migrations_never_applies_business_ddl_to_foreign_history():
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("20261006_0157_planning_result_admission", "2026-10-06T00:00:00Z")
    ]
    with patch("novel_forge.storage.migrations.runner._connect", return_value=connection):
        with pytest.raises(ValueError, match="MIGRATION_HISTORY"):
            run_migrations("unused-test-connection")
    statements = [call.args[0].strip() for call in cursor.execute.call_args_list]
    assert len(statements) == 3
    assert statements[0].startswith("SELECT pg_try_advisory_xact_lock")
    assert statements[1].startswith("CREATE TABLE IF NOT EXISTS nf_schema_migrations")
    assert statements[2].startswith("SELECT migration_id, applied_at")


def test_every_registered_history_prefix_can_continue_without_identity_rewrite():
    for prefix_length in range(len(MIGRATIONS) + 1):
        applied = {migration.migration_id for migration in MIGRATIONS[:prefix_length]}
        assert pending_migrations(applied) == list(MIGRATIONS[prefix_length:])
