"""SECURITY: offline native-shaped fixture cannot stand in for a verified Provider receipt."""

from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.chapter_quality_authority.model_reference import require_native_model_call
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash
from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
from tests.integration.authority_postgres_support import (
    DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, transaction,
)


def test_offline_model_log_without_verified_effect_receipt_is_rejected():
    ensure_migrated()
    project, operation, attempt, effect = (identifier("model-reference-project"),
        identifier("model-reference-operation"), identifier("model-reference-attempt"),
        identifier("model-reference-effect"))
    definition = "quality.model_reference.evaluate"
    subject = {"asset_version_id": "subject:offline", "content_hash": "sha256:" + "a" * 64}
    baseline = {"asset_version_id": "baseline:offline", "content_hash": "sha256:" + "b" * 64}
    frozen = {"subject": subject, "author_baseline": baseline, "role": "BLIND_EVALUATION"}
    request = {"input": {"model_reference": frozen}}
    evidence = {"real_model_call": True, "provider_id": "codex-cli", "model_id": "gpt-6.1-sol",
        "result": {"status": "PASSED", "score_range": [80, 90]},
        "production_execution": {"execution_request": {"project_id": project,
            "operation_id": operation, "attempt_id": attempt, "external_effect_id": effect}}}
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM authority_operation_definition WHERE name=%s AND definition_version='1.0.0'", [definition])
        if cursor.fetchone() is None:
            insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition,
            project_id=project, status="EXECUTING")
        cursor.execute("INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status) VALUES(%s,%s,1,'SUCCEEDED')",
            [attempt, operation])
        cursor.execute("""INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,
            stable_idempotency_key,status,request_hash,request_payload,model_id,capability)
            VALUES(%s,%s,%s,'model.invoke',%s,'SUCCEEDED',%s,%s,%s,%s)""",
            [effect, operation, project, effect, authorization_hash(request), Jsonb(request),
             "gpt-6.1-sol", "model.model_reference_evaluate"])
    log = AuthorityAssetWriter(DATABASE_URL).materialize_output(AuthorityAssetWriteCommand(
        operation, project, identifier("model-reference-log"), "model_call_log", "model-call-log.v1",
        "offline/model-reference-log", "fixture", "model_call_log", "model_evidence",
        {"stage": "model_reference_evaluate", "attempt_id": attempt, "provider_evidence": evidence},
        "fixture-only-v1", "trace:offline", "correlation:offline"))
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_operation SET status='SUCCEEDED' WHERE operation_id=%s", [operation])
    with transaction() as connection, connection.cursor() as cursor, pytest.raises(KernelError, match="MODEL_REFERENCE_PROVENANCE_INVALID"):
        require_native_model_call(cursor, project_id=project,
            binding={"asset_version_id": log.asset_version_id, "content_hash": log.content_hash},
            expected={key: frozen[key] for key in ("subject", "author_baseline")}, role="BLIND_EVALUATION")
