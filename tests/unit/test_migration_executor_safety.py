from unittest.mock import MagicMock, patch
import json

import pytest

from novel_forge.storage.migrations import runner
from novel_forge.storage.migrations.backup import create_migration_backup


def test_status_keeps_legacy_target_field_without_claiming_schema_qualification():
    rows = [{"migration_id": item.migration_id, "applied_at": "same-transaction-time"} for item in runner.MIGRATIONS[:3]]
    status = runner._status_from_rows(rows)
    assert status["current"] == status["target_head"] == runner.LATEST_MIGRATION_ID
    assert status["applied_head"] == runner.MIGRATIONS[2].migration_id
    assert status["history_valid"] and not status["ok"]
    assert status["schema_qualification"] == "NOT_CHECKED"
    assert not runner._status_from_rows(rows[1:])["history_valid"]


def test_competing_executor_stops_before_ledger_ddl():
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (False,)
    with patch.object(runner, "_connect", return_value=connection), pytest.raises(RuntimeError, match="EXECUTOR_BUSY"):
        runner.run_migrations("unused")
    assert cursor.execute.call_count == 1


@pytest.mark.parametrize("directory", [None, "relative/path"])
def test_required_backup_cannot_be_an_acknowledgement_or_missing_path(directory):
    cursor = MagicMock()
    with pytest.raises(RuntimeError, match="BACKUP_REQUIRED"):
        create_migration_backup("unused", cursor, applied=[], directory=directory)
    cursor.execute.assert_not_called()


def test_commit_disconnect_is_unknown_and_never_automatically_retried():
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (True,)
    cursor.fetchall.return_value = [(item.migration_id, "time") for item in runner.MIGRATIONS]
    connection.__exit__.side_effect = OSError("lost commit response")
    with patch.object(runner, "_connect", return_value=connection) as connect:
        with pytest.raises(RuntimeError, match="COMMIT_OUTCOME_UNKNOWN"):
            runner.run_migrations("unused")
    connect.assert_called_once()


def test_backup_uses_exact_private_connection_and_retains_consistent_snapshot(tmp_path):
    cursor = MagicMock()
    cursor.fetchone.return_value = ("owned", "16.15", "snapshot-id")
    from novel_forge.storage.migrations import backup

    def execute(arguments, **kwargs):
        assert "credential" not in " ".join(arguments)
        assert kwargs["env"]["PGHOST"] == "/exclusive/socket"
        assert kwargs["env"]["PGPORT"] == "55741"
        assert kwargs["env"]["PGDATABASE"] == "owned"
        assert kwargs["env"]["PGPASSWORD"] == "credential"
        for argument in arguments:
            if argument.startswith("--file="):
                from pathlib import Path
                Path(argument[7:]).write_bytes(b"private-archive")

    with patch.object(backup.shutil, "which", side_effect=lambda command: "/bin/" + command), patch.object(backup.subprocess, "run", side_effect=execute):
        evidence = create_migration_backup("host=/exclusive/socket port=55741 dbname=owned password=credential", cursor,
                                           applied=[{"migration_id": "original", "applied_at": "frozen"}], directory=str(tmp_path))
    assert evidence["archive_readable"] and evidence["restore_qualification"] == "NOT_RUN"
    metadata = next(tmp_path.glob("*.json"))
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert json.loads(metadata.read_text())["snapshot"] == "snapshot-id"


def test_backup_preserves_explicit_libpq_configuration_home(tmp_path, monkeypatch):
    from novel_forge.storage.migrations import backup

    context = {"HOME": str(tmp_path / "private-home"), "PGSERVICEFILE": str(tmp_path / "services.conf"),
               "PGSYSCONFDIR": str(tmp_path / "system-config")}
    for key, value in context.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-forwarded")
    cursor = MagicMock()
    cursor.fetchone.return_value = ("owned", "16.15", "snapshot-id")

    def execute(arguments, **kwargs):
        assert {key: kwargs["env"].get(key) for key in context} == context
        assert "UNRELATED_SECRET" not in kwargs["env"]
        assert kwargs["env"]["PGSERVICE"] == "owned"
        for argument in arguments:
            if argument.startswith("--file="):
                from pathlib import Path
                Path(argument[7:]).write_bytes(b"private-archive")

    with patch.object(backup.shutil, "which", side_effect=lambda name: "/bin/" + name), patch.object(backup.subprocess, "run", side_effect=execute):
        create_migration_backup("service=owned", cursor, applied=[], directory=str(tmp_path))
