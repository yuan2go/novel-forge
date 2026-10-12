from datetime import datetime, timezone

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.attempt_runtime import create_attempt
from novel_forge.modules.command_kernel.deadline_runtime import probe_operation_execution
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, transaction


def seed(capabilities):
    ensure_migrated()
    definition, operation, project = (identifier(value) for value in ("definition", "operation", "project"))
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition)
        cursor.execute("""INSERT INTO authority_operation(operation_id,definition_name,definition_version,
            project_id,status,root_operation_id,idempotency_scope,idempotency_key,request_digest,
            command_payload,definition_snapshot,completion_contract_snapshot,policy_snapshot,business_deadline_at)
            VALUES(%s,%s,'1.0.0',%s,'READY',%s,%s,%s,%s,'{}',%s,'{}','{}',%s)""",
            [operation, definition, project, operation, project, operation, operation,
             Jsonb({"external_capabilities": capabilities}), datetime(2000, 1, 1, tzinfo=timezone.utc)])
        for number in (1, 2):
            cursor.execute("""INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,max_attempts,status)
                VALUES(%s,%s,%s,1,'FAILED_FINAL')""", [identifier("attempt"), operation, number])
    return operation, project


def test_old_model_deadline_and_attempt_ceiling_are_observations():
    operation, project = seed(["model.draft"])
    assert probe_operation_execution(DATABASE_URL, operation_id=operation, project_id=project)["status"] == "READY"
    result = create_attempt(DATABASE_URL, operation_id=operation, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")
    assert result["attempt_number"] == 3
    assert not result["dead_letter"]
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT attempt_number,max_attempts,status FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number', [operation])
        assert cursor.fetchall() == [(1, 1, "FAILED_FINAL"), (2, 1, "FAILED_FINAL"), (3, 1, "CREATED")]
        cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s', [operation])
        assert cursor.fetchone()[0].year == 2000


def test_non_generation_deadline_and_cumulative_limit_are_preserved():
    operation, project = seed(["external.publish"])
    with pytest.raises(KernelError, match="OPERATION_BUSINESS_TIMEOUT"):
        probe_operation_execution(DATABASE_URL, operation_id=operation, project_id=project)
    result = create_attempt(DATABASE_URL, operation_id=operation, project_id=project,
        max_attempts=1, trace_id="trace", correlation_id="correlation")
    assert result["dead_letter"]
