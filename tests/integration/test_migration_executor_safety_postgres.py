from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from novel_forge.storage.migrations import runner
from tests.integration.authority_postgres_support import DATABASE_URL


@contextmanager
def _isolated_chain(monkeypatch):
    schema = "migration_safety_" + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    url = make_conninfo(DATABASE_URL, options="-c search_path=" + schema)
    chain = [runner.Migration("first", None, ("CREATE TABLE preserved(value TEXT)",), ())]
    pending = runner.pending_migrations
    monkeypatch.setattr(runner, "pending_migrations", lambda applied: pending(applied, tuple(chain)))
    monkeypatch.setattr(runner, "MIGRATIONS", chain)
    monkeypatch.setattr(runner, "LATEST_MIGRATION_ID", "first")
    try:
        yield url, chain
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_two_postgres_executors_contend_before_any_schema_write(monkeypatch):
    with _isolated_chain(monkeypatch) as (url, chain):
        with psycopg.connect(url) as owner:
            runner._lock_executor(owner.cursor())
            with pytest.raises(RuntimeError, match="MIGRATION_EXECUTOR_BUSY"):
                runner.run_migrations(url)
            assert owner.execute("SELECT to_regclass('nf_schema_migrations')").fetchone() == (None,)
        assert runner.run_migrations(url)["ok"]


def test_mid_sql_failure_rolls_back_all_pending_ddl_and_original_ledger(monkeypatch):
    with _isolated_chain(monkeypatch) as (url, chain):
        runner.run_migrations(url)
        chain.append(runner.Migration("second", "first", ("INSERT INTO preserved VALUES('must-rollback')", "SELECT no_such_column FROM preserved"), ()))
        before = runner.get_migration_status(url)["applied"]
        with pytest.raises(psycopg.errors.UndefinedColumn):
            runner.run_migrations(url)
        assert runner.get_migration_status(url)["applied"] == before
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT * FROM preserved").fetchall() == []


def test_same_name_drift_is_retained_and_cannot_be_passed_off_as_an_applied_migration(monkeypatch):
    with _isolated_chain(monkeypatch) as (url, chain):
        with psycopg.connect(url) as connection:
            connection.execute("CREATE TABLE preserved(wrong_identity INTEGER)")
        with pytest.raises(psycopg.errors.DuplicateTable):
            runner.run_migrations(url)
        status = runner.get_migration_status(url)
        assert not status["ok"] and status["applied_head"] is None
        assert status["schema_qualification"] == "NOT_CHECKED"
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT wrong_identity FROM preserved").fetchall() == []


def test_commit_response_loss_reconciles_committed_state_without_replaying_sql(monkeypatch):
    with _isolated_chain(monkeypatch) as (url, chain):
        connect = runner._connect
        class LostAcknowledgement:
            def __enter__(self):
                self.connection = connect(url)
                return self.connection.__enter__()
            def __exit__(self, *arguments):
                self.connection.__exit__(*arguments)
                raise psycopg.OperationalError("simulated lost acknowledgement after actual commit")
        with monkeypatch.context() as lost:
            lost.setattr(runner, "_connect", lambda unused: LostAcknowledgement())
            with pytest.raises(RuntimeError, match="MIGRATION_COMMIT_OUTCOME_UNKNOWN"):
                runner.run_migrations(url)
        status = runner.get_migration_status(url)
        assert status["ok"] and status["applied_head"] == "first"
        assert runner.run_migrations(url) == status


def test_existing_ledger_requires_actual_backup_before_declared_upgrade(monkeypatch):
    with _isolated_chain(monkeypatch) as (url, chain):
        runner.run_migrations(url)
        chain.append(runner.Migration("second", "first", ("INSERT INTO preserved VALUES('upgrade')",), (), backup_required=True))
        monkeypatch.delenv("NOVEL_FORGE_MIGRATION_BACKUP_DIR", raising=False)
        with pytest.raises(RuntimeError, match="MIGRATION_BACKUP_REQUIRED"):
            runner.run_migrations(url)
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT * FROM preserved").fetchall() == []
