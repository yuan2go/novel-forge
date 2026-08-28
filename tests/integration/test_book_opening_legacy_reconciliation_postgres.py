from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.book_authority.recovery import (
    PostgresBookOpeningRecoveryApplication,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_planning_runtime import (
    PostgresNarrativeSearchApplication,
)
from novel_forge.storage.migrations import MIGRATIONS, run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL


MIGRATION_ID = "20260828_0102_book_opening_recovery_closure"
RELEASE_SHA = "f" * 40


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _database_url(database_name: str) -> str:
    parameters = conninfo_to_dict(DATABASE_URL)
    parameters["dbname"] = database_name
    return make_conninfo(**parameters)


def _seed_scope(cursor: psycopg.Cursor, *, suffix: str) -> dict[str, str]:
    project_id = f"project:legacy-opening:{suffix}"
    workspace_id = f"workspace:legacy-opening:{suffix}"
    book_id = f"book:legacy-opening:{suffix}"
    operation_id = f"operation:legacy-opening:{suffix}"
    definition_name = f"fixture.legacy_opening.{suffix}"
    cursor.execute(
        """
        INSERT INTO authority_operation_definition(
            name,definition_version,family,enabled,command_schema,
            result_schema,policy,completion_contract
        ) VALUES (%s,'1.0.0','legacy-opening-fixture',TRUE,
                  '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb)
        """,
        [definition_name],
    )
    cursor.execute(
        """
        INSERT INTO authority_operation(
            operation_id,definition_name,definition_version,project_id,
            workspace_id,actor_id,status,root_operation_id,
            idempotency_scope,idempotency_key,request_digest,
            definition_snapshot,completion_contract_snapshot,
            policy_snapshot,concurrency_key,command_payload
        ) VALUES (%s,%s,'1.0.0',%s,%s,'legacy-opening-operator',
                  'ADMITTED',%s,%s,%s,%s,'{}'::jsonb,'{}'::jsonb,
                  '{}'::jsonb,%s,'{}'::jsonb)
        """,
        [
            operation_id,
            definition_name,
            project_id,
            workspace_id,
            operation_id,
            f"project:{project_id}",
            operation_id,
            "sha256:" + "1" * 64,
            f"fixture:{operation_id}",
        ],
    )
    assets = (
        (f"asset:legacy-opening:{suffix}:project", "project_record", "2"),
        (f"asset:legacy-opening:{suffix}:workspace", "workspace_record", "3"),
        (f"asset:legacy-opening:{suffix}:book", "book_record", "4"),
    )
    for asset_id, asset_type, digest in assets:
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) "
            "VALUES (%s,%s,%s)",
            [asset_id, project_id, asset_type],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR','{}'::jsonb,%s,
                      'legacy-opening-fixture.v1')
            """,
            [f"{asset_id}:v1", asset_id, "sha256:" + digest * 64],
        )
    cursor.execute(
        """
        INSERT INTO authority_project(
            project_id,primary_workspace_id,title,status,stage,health,
            current_asset_version_id,created_by_operation_id,last_operation_id
        ) VALUES (%s,%s,%s,'ACTIVE','PLANNING','HEALTHY',%s,%s,%s)
        """,
        [
            project_id,
            workspace_id,
            f"Legacy Opening {suffix}",
            f"{assets[0][0]}:v1",
            operation_id,
            operation_id,
        ],
    )
    cursor.execute(
        """
        INSERT INTO authority_workspace(
            workspace_id,project_id,book_id,status,current_asset_version_id,
            created_by_operation_id,last_operation_id
        ) VALUES (%s,%s,%s,'ACTIVE',%s,%s,%s)
        """,
        [
            workspace_id,
            project_id,
            book_id,
            f"{assets[1][0]}:v1",
            operation_id,
            operation_id,
        ],
    )
    cursor.execute(
        """
        INSERT INTO authority_book(
            book_id,project_id,workspace_id,principal_id,service_identity,
            book_scope,production_profile,runtime_policy,release_identity,
            status,current_book_asset_version_id,created_by_operation_id,
            last_operation_id
        ) VALUES (%s,%s,%s,'legacy-opening-operator','legacy-opening-fixture',
                  '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,'previous-main',
                  'DESIGN_PENDING',%s,%s,%s)
        """,
        [
            book_id,
            project_id,
            workspace_id,
            f"{assets[2][0]}:v1",
            operation_id,
            operation_id,
        ],
    )
    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_id": book_id,
        "operation_id": operation_id,
    }


def _seed_opening(
    cursor: psycopg.Cursor,
    *,
    suffix: str,
    with_runtime: str,
) -> dict[str, str]:
    scope = _seed_scope(cursor, suffix=suffix)
    opening_run_id = f"book-opening:legacy:{suffix}"
    runtime_job_id = f"runtime-job:legacy:{suffix}"
    attempt_id = f"runtime-attempt:legacy:{suffix}"
    lease_id = f"runtime-lease:legacy:{suffix}"
    frozen_request = {
        "project_id": scope["project_id"],
        "workspace_id": scope["workspace_id"],
        "book_id": scope["book_id"],
        "actor_id": "legacy-opening-operator",
        "expected_book_version": 1,
        "production_profile": "legacy-opening-fixture",
        "planning_input_versions": {},
        "idempotency_key": f"legacy:{suffix}:open-book",
        "arc_logical_keys": ["arc:central"],
        "trace_id": f"trace:legacy-opening:{suffix}",
        "correlation_id": f"correlation:legacy-opening:{suffix}",
        "initial_story_state_version": (f"asset:legacy-opening:{suffix}:project:v1"),
        "initial_canon_snapshot_version": (
            f"asset:legacy-opening:{suffix}:workspace:v1"
        ),
    }
    cursor.execute(
        """
        INSERT INTO authority_book_opening_run(
            opening_run_id,project_id,workspace_id,book_id,
            root_operation_id,stable_idempotency_key,lifecycle,
            frozen_request,frozen_request_digest
        ) VALUES (%s,%s,%s,%s,%s,%s,'RUNNING',%s,%s)
        """,
        [
            opening_run_id,
            scope["project_id"],
            scope["workspace_id"],
            scope["book_id"],
            scope["operation_id"],
            frozen_request["idempotency_key"],
            Jsonb(frozen_request),
            _canonical_hash(frozen_request),
        ],
    )
    if with_runtime == "missing":
        return {
            **scope,
            "opening_run_id": opening_run_id,
            "runtime_job_id": "",
            "attempt_id": "",
            "lease_id": "",
        }

    terminal = with_runtime == "terminal"
    job_status = "FAILED" if terminal else "CHECKPOINTED"
    attempt_status = "FAILED" if terminal else "CHECKPOINTED"
    lease_status = "RELEASED" if terminal else "HELD"
    result_hash = "sha256:" + "9" * 64 if terminal else ""
    cursor.execute(
        """
        INSERT INTO authority_runtime_job(
            runtime_job_id,job_kind,runtime_group,subject_kind,
            subject_id,project_id,dedupe_key,input_snapshot,input_hash,
            status,attempt_count,max_attempts,claimed_by,
            current_attempt_id,current_fencing_token,result_hash,last_error,
            created_at,updated_at,completed_at
        ) VALUES (%s,'BOOK_OPENING_EXECUTE','book_opening','BOOK_OPENING_RUN',
                  %s,%s,%s,%s,%s,%s,1,5,%s,%s,1,%s,%s,
                  '2026-08-01T00:00:00Z','2026-08-01T00:01:00Z',
                  CASE WHEN %s THEN '2026-08-01T00:01:00Z'::timestamptz END)
        """,
        [
            runtime_job_id,
            opening_run_id,
            scope["project_id"],
            f"legacy:{suffix}:generation:1",
            Jsonb({"opening_run_id": opening_run_id}),
            "sha256:" + "5" * 64,
            job_status,
            "" if terminal else "legacy-worker",
            attempt_id,
            result_hash,
            Jsonb({"code": "LEGACY_TERMINAL"}) if terminal else Jsonb({}),
            terminal,
        ],
    )
    cursor.execute(
        """
        INSERT INTO authority_runtime_job_attempt(
            attempt_id,runtime_job_id,attempt_number,worker_id,status,
            lease_id,fencing_token,lease_expires_at,heartbeat_at,
            result_hash,error,started_at,completed_at
        ) VALUES (%s,%s,1,'legacy-worker',%s,%s,1,
                  '2026-08-01T00:00:30Z','2026-08-01T00:00:20Z',%s,%s,
                  '2026-08-01T00:00:00Z',
                  CASE WHEN %s THEN '2026-08-01T00:01:00Z'::timestamptz END)
        """,
        [
            attempt_id,
            runtime_job_id,
            attempt_status,
            lease_id,
            result_hash,
            Jsonb({"code": "LEGACY_TERMINAL"}) if terminal else Jsonb({}),
            terminal,
        ],
    )
    cursor.execute(
        """
        INSERT INTO authority_runtime_job_lease(
            lease_id,runtime_job_id,attempt_id,worker_id,fencing_token,
            lease_expires_at,heartbeat_at,status,released_at,release_reason,
            created_at
        ) VALUES (%s,%s,%s,'legacy-worker',1,'2026-08-01T00:00:30Z',
                  '2026-08-01T00:00:20Z',%s,
                  CASE WHEN %s THEN '2026-08-01T00:01:00Z'::timestamptz END,
                  CASE WHEN %s THEN 'legacy_failed' ELSE '' END,
                  '2026-08-01T00:00:00Z')
        """,
        [lease_id, runtime_job_id, attempt_id, lease_status, terminal, terminal],
    )
    if terminal:
        cursor.execute(
            """
            INSERT INTO authority_runtime_job_result(
                result_id,runtime_job_id,attempt_id,fencing_token,status,
                result,result_hash,created_at
            ) VALUES (%s,%s,%s,1,'FAILED',%s,%s,'2026-08-01T00:01:00Z')
            """,
            [
                f"runtime-result:legacy:{suffix}",
                runtime_job_id,
                attempt_id,
                Jsonb({"code": "LEGACY_TERMINAL"}),
                result_hash,
            ],
        )
    return {
        **scope,
        "opening_run_id": opening_run_id,
        "runtime_job_id": runtime_job_id,
        "attempt_id": attempt_id,
        "lease_id": lease_id,
    }


@pytest.fixture(scope="module")
def legacy_reconciliation_database() -> Iterator[tuple[str, dict[str, dict[str, str]]]]:
    database_name = f"nf_opening_legacy_reconcile_{uuid4().hex}"[:63]
    admin_url = _database_url("postgres")
    test_url = _database_url(database_name)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    try:
        with psycopg.connect(test_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE nf_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for migration in MIGRATIONS:
                if migration.migration_id == MIGRATION_ID:
                    break
                for statement in migration.upgrade_statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO nf_schema_migrations(migration_id) VALUES (%s)",
                    [migration.migration_id],
                )
            scenario_kinds = {
                "active": "active",
                "missing": "missing",
                "terminal": "terminal",
                "abort": "active",
                "missing-abort": "missing",
                "sweeper-release-drift": "active",
            }
            scenarios = {
                name: _seed_opening(cursor, suffix=name, with_runtime=kind)
                for name, kind in scenario_kinds.items()
            }
        status = run_migrations(test_url)
        assert status["ok"] is True
        yield test_url, scenarios
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname=%s AND pid<>pg_backend_pid()
                """,
                [database_name],
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


def _principal(project_id: str) -> Principal:
    return Principal(
        principal_id=f"legacy-recovery-operator:{project_id}",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"book.authority.execute"}),
        project_scope=frozenset({project_id}),
        authentication_source="legacy-opening-reconciliation-postgres",
    )


def _recovery(database_url: str) -> PostgresBookOpeningRecoveryApplication:
    return PostgresBookOpeningRecoveryApplication(
        database_url,
        application_build_id="legacy-opening-reconciliation-postgres",
        commit_sha=RELEASE_SHA,
    )


def _opening(database_url: str) -> PostgresBookOpeningApplication:
    return PostgresBookOpeningApplication(
        database_url,
        narrative_search=cast(PostgresNarrativeSearchApplication, object()),
        input_resolver=cast(BookProductionInputResolver, object()),
        application_build_id="legacy-opening-reconciliation-postgres",
        commit_sha=RELEASE_SHA,
    )


class _CrashAfterLossAssessmentCommit(BaseException):
    """Model process loss between automatic assessment and convergence."""


def _recover(
    recovery: PostgresBookOpeningRecoveryApplication,
    fixture: dict[str, str],
    principal: Principal,
) -> object:
    assessment = recovery.assess_recovery(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-recovery-assess:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert assessment.disposition == "PROVEN_NO_EFFECT"
    return recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"legacy-recovery-admit:{fixture['opening_run_id']}",
        reason="recover reconciled previous-main execution lineage",
        principal=principal,
        expected_opening_run_id=fixture["opening_run_id"],
    )


def test_previous_main_expired_active_job_formally_binds_loses_and_recovers(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["active"]
    principal = _principal(fixture["project_id"])
    recovery = _recovery(database_url)
    runtime_jobs = RuntimeJobAuthority(database_url)

    with psycopg.connect(database_url) as connection:
        migrated = connection.execute(
            """
            SELECT status,max_attempts,lease_loss_policy,attempt_count
            FROM authority_runtime_job WHERE runtime_job_id=%s
            """,
            [fixture["runtime_job_id"]],
        ).fetchone()
    assert migrated == (
        "CHECKPOINTED",
        5,
        "AUTHORITY_CONVERGENCE_REQUIRED",
        1,
    )
    assert (
        runtime_jobs.claim(
            runtime_group="book_opening",
            worker_id="forbidden-generic-takeover",
            lease_seconds=30,
            job_kinds=("BOOK_OPENING_EXECUTE",),
            project_id=fixture["project_id"],
        )
        is None
    )

    bound = recovery.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert bound.result["execution_lifecycle"] == "RUNNING"
    assert bound.result["opening_lifecycle"] == "RUNNING"
    loss_key = f"legacy-loss:{fixture['opening_run_id']}"
    loss = recovery.assess_execution_loss(
        fixture["opening_run_id"],
        idempotency_key=loss_key,
        principal=principal,
    )
    converged = recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=principal,
        expected_opening_run_id=fixture["opening_run_id"],
    )
    assert converged.result["opening_lifecycle"] == "FAILED"
    admitted = _recover(recovery, fixture, principal)
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["provider_invoked"] is False

    with psycopg.connect(database_url) as connection:
        state = connection.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   prior.lifecycle,successor.lifecycle,
                   prior_job.status,prior_job.max_attempts,
                   prior_attempt.status,prior_lease.status,
                   successor_job.status,successor_job.max_attempts,
                   successor_job.lease_loss_policy,
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE runtime_job_id=prior_job.runtime_job_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS prior
              ON prior.opening_run_id=opening.opening_run_id
             AND prior.generation=1
            JOIN authority_book_opening_execution AS successor
              ON successor.opening_execution_id=opening.current_execution_id
             AND successor.generation=2
            JOIN authority_runtime_job AS prior_job
              ON prior_job.runtime_job_id=prior.runtime_job_id
            JOIN authority_runtime_job_attempt AS prior_attempt
              ON prior_attempt.attempt_id=prior_job.current_attempt_id
            JOIN authority_runtime_job_lease AS prior_lease
              ON prior_lease.lease_id=prior_attempt.lease_id
            JOIN authority_runtime_job AS successor_job
              ON successor_job.runtime_job_id=successor.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert state == (
        "ADMITTED",
        2,
        "LOST",
        "SCHEDULED",
        "FAILED",
        5,
        "ABANDONED",
        "EXPIRED",
        "READY",
        1,
        "AUTHORITY_CONVERGENCE_REQUIRED",
        1,
        0,
    )


def test_expired_active_legacy_execution_rejects_abort_until_formal_loss(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["abort"]
    principal = _principal(fixture["project_id"])
    recovery = _recovery(database_url)
    opening = _opening(database_url)

    bound = recovery.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert bound.result["execution_lifecycle"] == "RUNNING"
    before = opening.require(fixture["opening_run_id"])

    with pytest.raises(KernelError) as conflict:
        opening.abort(
            fixture["opening_run_id"],
            expected_version=int(before["version"]),
            principal=principal,
        )
    assert conflict.value.code == "BOOK_OPENING_ABORT_CONFLICT"

    with psycopg.connect(database_url) as connection:
        unchanged = connection.execute(
            """
            SELECT opening.lifecycle,opening.version,execution.lifecycle,
                   job.status,attempt.status,lease.status,
                   lease.lease_expires_at <= transaction_timestamp()
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert unchanged == (
        "RUNNING",
        int(before["version"]),
        "RUNNING",
        "CHECKPOINTED",
        "CHECKPOINTED",
        "HELD",
        True,
    )

    loss_key = f"legacy-loss-after-abort-rejection:{fixture['opening_run_id']}"
    assessment = recovery.assess_execution_loss(
        fixture["opening_run_id"],
        idempotency_key=loss_key,
        principal=principal,
    )
    receipt = recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=principal,
        expected_opening_run_id=fixture["opening_run_id"],
    )
    assert receipt.result["opening_lifecycle"] == "FAILED"
    assert receipt.result["execution_lifecycle"] == "LOST"
    with psycopg.connect(database_url) as connection:
        converged = connection.execute(
            """
            SELECT opening.lifecycle,execution.lifecycle,job.status,
                   attempt.status,lease.status,
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert converged == ("FAILED", "LOST", "FAILED", "ABANDONED", "EXPIRED", 0)


def test_missing_runtime_job_gets_formal_loss_marker_then_recovers(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["missing"]
    principal = _principal(fixture["project_id"])
    recovery = _recovery(database_url)

    reconciled = recovery.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert reconciled.result["execution_lifecycle"] == "ABORTED"
    assert reconciled.result["opening_lifecycle"] == "FAILED"
    with psycopg.connect(database_url) as connection:
        marker = connection.execute(
            """
            SELECT job.status,job.current_attempt_id,execution.lifecycle,
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE runtime_job_id=job.runtime_job_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert marker == ("CANCELLED", None, "ABORTED", 0)

    admitted = _recover(recovery, fixture, principal)
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["provider_invoked"] is False
    with psycopg.connect(database_url) as connection:
        lineage = connection.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   predecessor.lifecycle,marker.status,marker.current_attempt_id,
                   successor.lifecycle,successor_job.status,
                   successor_job.max_attempts,
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE runtime_job_id=marker.runtime_job_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS predecessor
              ON predecessor.opening_run_id=opening.opening_run_id
             AND predecessor.generation=1
            JOIN authority_runtime_job AS marker
              ON marker.runtime_job_id=predecessor.runtime_job_id
            JOIN authority_book_opening_execution AS successor
              ON successor.opening_execution_id=opening.current_execution_id
             AND successor.generation=2
            JOIN authority_runtime_job AS successor_job
              ON successor_job.runtime_job_id=successor.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert lineage == (
        "ADMITTED",
        2,
        "ABORTED",
        "CANCELLED",
        None,
        "SCHEDULED",
        "READY",
        1,
        0,
        0,
    )


def test_missing_runtime_loss_marker_can_be_formally_aborted_without_rewrite(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["missing-abort"]
    principal = _principal(fixture["project_id"])
    recovery = _recovery(database_url)
    opening = _opening(database_url)

    reconciled = recovery.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert reconciled.result["execution_lifecycle"] == "ABORTED"
    failed = opening.require(fixture["opening_run_id"])
    assert failed["lifecycle"] == "FAILED"

    aborted = opening.abort(
        fixture["opening_run_id"],
        expected_version=int(failed["version"]),
        principal=principal,
    )
    assert aborted["lifecycle"] == "ABORTED"
    with psycopg.connect(database_url) as connection:
        state = connection.execute(
            """
            SELECT opening.lifecycle,execution.lifecycle,job.status,
                   job.current_attempt_id,job.current_fencing_token,
                   (SELECT COUNT(*) FROM authority_runtime_job_attempt
                    WHERE runtime_job_id=job.runtime_job_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert state == ("ABORTED", "ABORTED", "CANCELLED", None, 0, 0, 0)


def test_terminal_runtime_history_is_bound_immutably_then_recovered(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["terminal"]
    principal = _principal(fixture["project_id"])
    recovery = _recovery(database_url)
    with psycopg.connect(database_url) as connection:
        before = connection.execute(
            """
            SELECT job.status,job.max_attempts,job.result_hash,job.last_error,
                   attempt.status,attempt.result_hash,attempt.error,
                   lease.status,lease.release_reason
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
            WHERE job.runtime_job_id=%s
            """,
            [fixture["runtime_job_id"]],
        ).fetchone()

    reconciled = recovery.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )
    assert reconciled.result["execution_lifecycle"] == "FAILED"
    assert reconciled.result["opening_lifecycle"] == "FAILED"
    admitted = _recover(recovery, fixture, principal)
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["provider_invoked"] is False

    with psycopg.connect(database_url) as connection:
        after = connection.execute(
            """
            SELECT job.status,job.max_attempts,job.result_hash,job.last_error,
                   attempt.status,attempt.result_hash,attempt.error,
                   lease.status,lease.release_reason
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
            WHERE job.runtime_job_id=%s
            """,
            [fixture["runtime_job_id"]],
        ).fetchone()
        lineage = connection.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   predecessor.lifecycle,successor.lifecycle,
                   successor_job.status,successor_job.max_attempts,
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS predecessor
              ON predecessor.opening_run_id=opening.opening_run_id
             AND predecessor.generation=1
            JOIN authority_book_opening_execution AS successor
              ON successor.opening_execution_id=opening.current_execution_id
             AND successor.generation=2
            JOIN authority_runtime_job AS successor_job
              ON successor_job.runtime_job_id=successor.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert after == before
    assert lineage == ("ADMITTED", 2, "FAILED", "SCHEDULED", "READY", 1, 0)


def test_loss_sweeper_reassesses_after_release_drift_and_converges(
    legacy_reconciliation_database: tuple[str, dict[str, dict[str, str]]],
) -> None:
    database_url, scenarios = legacy_reconciliation_database
    fixture = scenarios["sweeper-release-drift"]
    principal = _principal(fixture["project_id"])
    release_a = _recovery(database_url)
    release_a.reconcile_legacy_execution(
        fixture["opening_run_id"],
        idempotency_key=f"legacy-bind:{fixture['opening_run_id']}",
        principal=principal,
    )

    with (
        patch.object(
            release_a,
            "converge_execution_loss",
            side_effect=_CrashAfterLossAssessmentCommit(
                "process disappeared after loss assessment commit"
            ),
        ),
        pytest.raises(_CrashAfterLossAssessmentCommit),
    ):
        release_a.scan_expired_executions(principal=principal, limit=10)

    with psycopg.connect(database_url) as connection:
        first = connection.execute(
            """
            SELECT recovery_assessment_id,idempotency_key,snapshot_hash,
                   authority_version_digest,snapshot
            FROM authority_book_opening_recovery_assessment
            WHERE opening_run_id=%s AND assessment_kind='EXECUTION_LOSS'
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
        receipt_count_before = connection.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_opening_recovery_receipt
            WHERE opening_run_id=%s
              AND receipt_kind='EXECUTION_LOSS_CONVERGENCE'
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert first is not None
    assert receipt_count_before == (0,)

    release_b = PostgresBookOpeningRecoveryApplication(
        database_url,
        application_build_id="legacy-opening-loss-sweeper-release-b",
        commit_sha="b" * 40,
    )
    swept = release_b.scan_expired_executions(principal=principal, limit=10)
    assert len(swept) == 1
    assert swept[0]["opening_run_id"] == fixture["opening_run_id"]
    assert swept[0]["opening_lifecycle"] == "FAILED"
    assert swept[0]["execution_lifecycle"] == "LOST"

    with psycopg.connect(database_url) as connection:
        assessments = connection.execute(
            """
            SELECT recovery_assessment_id,idempotency_key,snapshot_hash,
                   authority_version_digest,snapshot
            FROM authority_book_opening_recovery_assessment
            WHERE opening_run_id=%s AND assessment_kind='EXECUTION_LOSS'
            ORDER BY created_at,recovery_assessment_id
            """,
            [fixture["opening_run_id"]],
        ).fetchall()
        final = connection.execute(
            """
            SELECT opening.lifecycle,execution.lifecycle,job.status,
                   attempt.status,lease.status,
                   (SELECT COUNT(*)
                    FROM authority_book_opening_recovery_receipt
                    WHERE opening_run_id=opening.opening_run_id
                      AND receipt_kind='EXECUTION_LOSS_CONVERGENCE'),
                   (SELECT COUNT(*)
                    FROM authority_book_opening_recovery_intent
                    WHERE opening_run_id=opening.opening_run_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            WHERE opening.opening_run_id=%s
            """,
            [fixture["opening_run_id"]],
        ).fetchone()
    assert len(assessments) == 2
    by_id = {str(row[0]): row for row in assessments}
    assert by_id[str(first[0])] == first
    assert len({str(row[1]) for row in assessments}) == 2
    assert len({str(row[2]) for row in assessments}) == 2
    assert len({str(row[3]) for row in assessments}) == 2
    assert all(
        str(row[3]) == str(row[4]["authority_version_digest"]) for row in assessments
    )
    assert final == ("FAILED", "LOST", "FAILED", "ABANDONED", "EXPIRED", 1, 0, 0)
