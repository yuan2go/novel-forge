#!/usr/bin/env python3
"""Run one isolated, destructive-to-its-own-project Worker Compose proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
from typing import Any, Callable
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
COMPOSE = tuple(
    shlex.split(os.environ.get("NOVEL_FORGE_DOCKER_COMPOSE_BIN") or "docker compose")
)
COMPOSE_FILES = ("compose.yml", "compose.worker-e2e.yml")
WORKER_SERVICES = {
    "chapter": "chapter-authority-worker",
    "content": "content-authority-worker",
    "source": "source-authority-worker",
    "mkaos": "mkaos-authority-worker",
    "book": "book-authority-worker",
    "outbox": "outbox-worker",
    "maintenance": "maintenance-worker",
}
WORKER_IDENTITIES = {
    "chapter": ("chapter-execution-effect-dispatch", "chapter-authority-worker-1"),
    "content": ("content-authority", "content-authority-worker-1"),
    "source": ("source-authority", "source-authority-worker-1"),
    "mkaos": ("mkaos-authority", "mkaos-authority-worker-1"),
    "book": ("book-authority", "book-authority-worker-1"),
    "outbox": ("outbox-dispatch", "outbox-worker-1"),
    "maintenance": ("maintenance-recovery", "maintenance-worker-1"),
}
ALL_SERVICES = tuple(WORKER_SERVICES.values())


def _run(
    command: list[str], *, env: dict[str, str], timeout: float = 600, check: bool = True
) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _compose(project: str, *arguments: str) -> list[str]:
    command = [*COMPOSE, "-p", project]
    for compose_file in COMPOSE_FILES:
        command.extend(("-f", compose_file))
    return [*command, *arguments]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _connect(database_url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(database_url, connect_timeout=5)


def _poll(
    label: str,
    read: Callable[[], Any],
    accepted: Callable[[Any], bool],
    *,
    timeout: float = 120,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = read()
        if accepted(last):
            return last
        time.sleep(0.25)
    raise RuntimeError(f"{label} did not converge: {last!r}")


def _operation_status(database_url: str, operation_id: str) -> str:
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id=%s",
            [operation_id],
        )
        row = cursor.fetchone()
    return str(row[0]) if row else "MISSING"


def _wait_operation(database_url: str, operation_id: str) -> str:
    return str(
        _poll(
            f"operation {operation_id}",
            lambda: _operation_status(database_url, operation_id),
            lambda status: status == "SUCCEEDED",
        )
    )


def _operation_execution_evidence(
    database_url: str, operation_id: str
) -> dict[str, Any]:
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT attempt.attempt_id, attempt.worker_id, attempt.status,
                   attempt.checkpoint, lease.lease_id, lease.fencing_token
            FROM authority_attempt AS attempt
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE attempt.operation_id=%s
            ORDER BY lease.fencing_token DESC, attempt.attempt_number DESC
            LIMIT 1
            """,
            [operation_id],
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"operation {operation_id} has no lease evidence")
        cursor.execute(
            "SELECT COUNT(*) FROM audit_log WHERE operation_id=%s", [operation_id]
        )
        audit_count = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COUNT(*) FROM outbox_event WHERE payload->>'operation_id'=%s",
            [operation_id],
        )
        outbox_count = int(cursor.fetchone()[0])
    checkpoint = dict(row[3] or {})
    return {
        "attempt_id": str(row[0]),
        "claimed_by": str(row[1]),
        "attempt_status": str(row[2]),
        "checkpoint": checkpoint or {"terminal_status": str(row[2])},
        "lease_id": str(row[4]),
        "fencing_token": int(row[5]),
        "audit_count": audit_count,
        "outbox_count": outbox_count,
    }


def _expire_attempt_lease(database_url: str, attempt_id: str) -> None:
    def expired() -> bool:
        with _connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status='EXPIRED' OR (status='HELD' AND expires_at<=NOW()) "
                "FROM authority_lease_acquisition WHERE attempt_id=%s",
                [attempt_id],
            )
            row = cursor.fetchone()
        return bool(row and row[0])

    _poll("fixture attempt lease expiry", expired, bool, timeout=5)


def _project(database_url: str, suffix: str) -> tuple[str, str, str]:
    from novel_forge.modules.project_authority import (
        ProjectAuthorityApplication,
        ProjectAuthorityCommand,
    )

    project_id = f"worker-e2e-{suffix}-{uuid4().hex[:12]}"
    workspace_id = f"workspace:{project_id}"
    result = ProjectAuthorityApplication(
        database_url,
        application_build_id="worker-fleet-compose-e2e",
        commit_sha=os.environ["NOVEL_FORGE_COMMIT_SHA"],
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id="worker-fleet-operator",
            idempotency_key=f"worker-fleet:project:{project_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={"title": f"{suffix} worker fixture", "stage": "DESIGN"},
        )
    )
    return project_id, workspace_id, str(result["operation_id"])


def _fixture_principal(project_id: str, permissions: set[str]):
    from novel_forge.modules.authority_security import Principal, PrincipalType

    return Principal(
        principal_id="worker-fleet-operator",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset(permissions),
        project_scope=frozenset({project_id}),
        authentication_source="compose-worker-e2e-fixture",
    )


def _real_minio_blob(
    settings: Any, project_id: str, content: bytes, label: str
) -> dict[str, Any]:
    from io import BytesIO

    from novel_forge.modules.command_kernel.asset_runtime import (
        AssetCommandContext,
        accept_blob_upload_receipt,
        begin_blob_upload_dispatch,
        request_blob_upload,
        reserve_blob,
        verify_blob,
    )
    from novel_forge.storage.object_store import MinioObjectStore

    operation_id = f"fixture-blob-operation:{uuid4()}"
    definition_name = f"fixture.blob.receipt.{uuid4()}"
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_operation_definition(
                name, definition_version, family, enabled, command_schema,
                result_schema, policy, completion_contract
            ) VALUES (%s,'1.0.0','fixture',TRUE,'{}','{}','{}','{}')
            """,
            [definition_name],
        )
        cursor.execute(
            """
            INSERT INTO authority_operation(
                operation_id, definition_name, definition_version, project_id,
                status, root_operation_id, idempotency_scope, idempotency_key,
                request_digest, definition_snapshot, completion_contract_snapshot,
                policy_snapshot
            ) VALUES (%s,%s,'1.0.0',%s,'EXECUTING',%s,%s,%s,%s,'{}','{}','{}')
            """,
            [
                operation_id,
                definition_name,
                project_id,
                operation_id,
                f"project:{project_id}",
                operation_id,
                f"digest:{operation_id}",
            ],
        )
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    object_name = f"worker-e2e/{project_id}/{label}-{uuid4().hex}.bin"
    store = MinioObjectStore(settings)
    store.ensure_buckets()
    stored = store.client.put_object(
        settings.minio_raw_bucket,
        object_name,
        BytesIO(content),
        length=len(content),
        content_type="text/plain",
        metadata={"content-hash": digest, "fixture-protocol-only": "true"},
    )
    stat = store.client.stat_object(settings.minio_raw_bucket, object_name)
    object_key = f"{settings.minio_raw_bucket}/{object_name}"
    context = AssetCommandContext(
        operation_id=operation_id,
        project_id=project_id,
        actor_id="worker-fleet-blob-receipt",
        trace_id=f"trace:{operation_id}",
        correlation_id=f"correlation:{operation_id}",
    )
    blob_id = reserve_blob(
        settings.database_url,
        context,
        provider="minio",
        object_key=object_key,
        expected_hash=digest,
        expected_size=len(content),
        media_type="text/plain",
    )
    effect = request_blob_upload(settings.database_url, context, blob_id=blob_id)
    dispatch = begin_blob_upload_dispatch(
        settings.database_url,
        context,
        external_effect_id=str(effect["external_effect_id"]),
        provider="minio",
    )
    receipt_id = str(getattr(stored, "etag", "") or uuid4())
    accept_blob_upload_receipt(
        settings.database_url,
        context,
        dispatch_id=str(dispatch["dispatch_id"]),
        provider="minio",
        receipt_id=receipt_id,
        object_key=object_key,
        actual_hash=digest,
        actual_size=int(stat.size),
        payload_hash="sha256:"
        + hashlib.sha256(
            f"{object_key}:{digest}:{stat.size}:{receipt_id}".encode()
        ).hexdigest(),
        evidence={
            "bucket": settings.minio_raw_bucket,
            "etag": str(getattr(stat, "etag", "") or ""),
            "fixture_protocol_only": True,
            "real_object_store_receipt": True,
        },
    )
    verified = verify_blob(settings.database_url, context, blob_id=blob_id)
    return {
        "blob_id": blob_id,
        "object_key": object_key,
        "content_hash": digest,
        "size": len(content),
        "receipt_id": receipt_id,
        "status": verified["status"],
        "real_minio_object": True,
    }


def _prepare_operation_recovery(
    settings: Any, project_id: str, operation_id: str
) -> tuple[dict[str, Any], Callable[[], dict[str, Any]]]:
    from novel_forge.tools.authority_compose_probe import (
        assert_stale_fence_rejected,
        prepare_expiring_lease,
    )

    stale = prepare_expiring_lease(
        settings, project_id=project_id, operation_id=operation_id
    )
    _expire_attempt_lease(settings.database_url, str(stale["attempt_id"]))

    def assert_stale() -> dict[str, Any]:
        return assert_stale_fence_rejected(
            settings,
            project_id=project_id,
            operation_id=operation_id,
            attempt_id=str(stale["attempt_id"]),
            worker_id=str(stale["worker_id"]),
            fencing_token=int(stale["fencing_token"]),
        )

    return stale, assert_stale


def _chapter_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import (
        build_chapter_authority_application,
        build_production_execution_composition,
    )
    from novel_forge.modules.chapter_authority import SingleChapterRequest
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    project_id = f"worker-e2e-chapter-{uuid4().hex[:12]}"
    candidates = PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    principal = _fixture_principal(
        project_id, {"chapter.authority.execute", "external_effect.execute"}
    )
    execution = build_production_execution_composition(settings, env=os.environ)
    application = build_chapter_authority_application(
        settings, execution=execution, env=os.environ
    )
    control.stop_target()
    admission = application.admit(
        SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id=principal.principal_id,
            chapter=1,
            title="Recovered Fixture Chapter",
            premise="A bounded recovery proves the execution plane.",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            application_build_id="worker-fleet-compose-e2e",
            commit_sha=os.environ["NOVEL_FORGE_COMMIT_SHA"],
            context_candidates=tuple(candidates),
        ),
        principal=principal,
    )
    stale, assert_stale = _prepare_operation_recovery(
        settings, project_id, admission.first_operation_id
    )
    control.start_target()

    def chapter_state() -> tuple[str, str, int]:
        with (
            _connect(settings.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [admission.root_operation_id],
            )
            root = str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT status FROM authority_saga WHERE saga_id=%s",
                [admission.saga_id],
            )
            saga = str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM authority_operation "
                "WHERE root_operation_id=%s AND definition_name LIKE 'chapter.%%' "
                "AND definition_name<>'chapter.slice.run' AND status='SUCCEEDED'",
                [admission.root_operation_id],
            )
            nodes = int(cursor.fetchone()[0])
        return root, saga, nodes

    terminal = _poll(
        "Chapter Saga",
        chapter_state,
        lambda value: (
            value[0] == "SUCCEEDED" and value[1] == "SUCCEEDED" and value[2] == 18
        ),
        timeout=180,
    )
    execution = _operation_execution_evidence(
        settings.database_url, admission.first_operation_id
    )
    stale_result = assert_stale()
    return {
        "scenario": "Fixture Chapter root, 18 nodes, quality/canon/export and crash recovery",
        "work_id": admission.root_operation_id,
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": {
            "root_status": terminal[0],
            "saga_status": terminal[1],
            "succeeded_node_count": terminal[2],
            "fixture_provider": True,
            "quality_claim": False,
        },
        "expired_claim": stale,
        "stale_error_code": stale_result["rejected_error_code"],
    }


def _content_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from novel_forge.tools.authority_compose_probe import submit, verify

    control.stop_target()
    admitted = submit(settings, f"content-{uuid4().hex[:10]}")
    stale, assert_stale = _prepare_operation_recovery(
        settings, admitted["project_id"], admitted["operation_id"]
    )
    control.start_target()
    terminal = verify(
        settings,
        project_id=admitted["project_id"],
        operation_id=admitted["operation_id"],
        timeout_seconds=120,
        min_fencing_token=2,
    )
    execution = _operation_execution_evidence(
        settings.database_url, admitted["operation_id"]
    )
    stale_result = assert_stale()
    return {
        "scenario": "Creative Brief admission, materialization and crash recovery",
        "work_id": admitted["operation_id"],
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": terminal,
        "expired_claim": stale,
        "stale_error_code": stale_result["rejected_error_code"],
    }


def _source_pipeline(
    settings: Any,
    *,
    project_id: str,
    workspace_id: str,
    recover_registration: bool,
    control: "ComposeControl | None" = None,
) -> dict[str, Any]:
    from novel_forge.modules.source_authority import (
        CommitSourceTransformCommand,
        RegisterSourceDocumentCommand,
        SourceAuthorityApplication,
        SourceAuthorityQuery,
        SourceChunkCandidate,
    )

    application = SourceAuthorityApplication(
        settings.database_url,
        application_build_id="worker-fleet-compose-e2e",
        commit_sha=os.environ["NOVEL_FORGE_COMMIT_SHA"],
    )
    principal = _fixture_principal(
        project_id, {"source.authority.execute", "source.authority.query"}
    )
    source_bytes = b"licensed fixture source bytes for abstract structural evidence"
    source_blob = _real_minio_blob(settings, project_id, source_bytes, "source")
    admission = application.admit(
        RegisterSourceDocumentCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            blob_id=source_blob["blob_id"],
            title="Governed MinIO Fixture Source",
            source_kind="licensed_research",
            source_uri="urn:fixture:worker-e2e-source",
            rights_authorization="owned",
            license_name="fixture-owner-rights",
            copyright_boundary="abstract mechanisms only; no source prose in drafts",
            actor_id=principal.principal_id,
            idempotency_key=f"source:{source_blob['blob_id']}",
            trace_id=f"trace:{source_blob['blob_id']}",
            correlation_id=f"correlation:{source_blob['blob_id']}",
        ),
        principal=principal,
    )
    stale: dict[str, Any] = {}
    stale_result: dict[str, Any] = {}
    if recover_registration:
        if control is None:
            raise ValueError("recovered Source registration requires Compose control")
        stale, assert_stale = _prepare_operation_recovery(
            settings, project_id, str(admission["operation_id"])
        )
        control.start_target()
    _wait_operation(settings.database_url, str(admission["operation_id"]))
    if recover_registration:
        stale_result = assert_stale()
    source = application.result(
        str(admission["operation_id"]), project_id, replayed=False
    )
    chunk_bytes = b"normalized evidence bytes for an abstract obligation mechanism"
    chunk_blob = _real_minio_blob(settings, project_id, chunk_bytes, "chunk")
    transform_admission = application.admit_transform(
        CommitSourceTransformCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            source_document_id=str(source["source_document_id"]),
            normalization_version="normalize:v1",
            chunking_version="evidence:v1",
            chunking_policy_hash="sha256:"
            + hashlib.sha256(b"worker-e2e-chunk-v1").hexdigest(),
            chunks=(
                SourceChunkCandidate(
                    chunk_index=0,
                    blob_id=str(chunk_blob["blob_id"]),
                    content_hash="sha256:" + hashlib.sha256(chunk_bytes).hexdigest(),
                    byte_size=len(chunk_bytes),
                    character_count=len(chunk_bytes.decode()),
                    token_count=8,
                    source_byte_start=0,
                    source_byte_end=len(source_bytes),
                ),
            ),
            actor_id=principal.principal_id,
            idempotency_key=f"transform:{source['asset_version_id']}",
            trace_id=f"trace:transform:{source_blob['blob_id']}",
            correlation_id=f"correlation:transform:{source_blob['blob_id']}",
        ),
        principal=principal,
    )
    _wait_operation(settings.database_url, str(transform_admission["operation_id"]))
    transformed = application.result(
        str(transform_admission["operation_id"]), project_id, replayed=False
    )
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT asset_version_id FROM authority_source_chunk "
            "WHERE source_transform_id=%s AND chunk_index=0",
            [transformed["source_transform_id"]],
        )
        chunk_version_id = str(cursor.fetchone()[0])
    document = SourceAuthorityQuery(settings.database_url).require_document(
        project_id=project_id, source_document_id=str(source["source_document_id"])
    )
    return {
        "registration_operation_id": str(admission["operation_id"]),
        "transform_operation_id": str(transform_admission["operation_id"]),
        "source_document_id": str(source["source_document_id"]),
        "source_asset_version_id": str(source["asset_version_id"]),
        "source_chunk_asset_version_id": chunk_version_id,
        "source_blob": source_blob,
        "chunk_blob": chunk_blob,
        "lifecycle": document["lifecycle"],
        "governance": document["governance"],
        "stale": stale,
        "stale_result": stale_result,
    }


def _source_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    project_id, workspace_id, _ = _project(settings.database_url, "source")
    control.stop_target()
    pipeline = _source_pipeline(
        settings,
        project_id=project_id,
        workspace_id=workspace_id,
        recover_registration=True,
        control=control,
    )
    execution = _operation_execution_evidence(
        settings.database_url, pipeline["registration_operation_id"]
    )
    if pipeline["lifecycle"] != "ACTIVE" or pipeline["governance"] != "CLEAR":
        raise RuntimeError("Source pipeline did not remain fail-closed and eligible")
    return {
        "scenario": "Real MinIO Put/Receipt, Source register/transform/projection and recovery",
        "work_id": pipeline["registration_operation_id"],
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": pipeline,
        "expired_claim": pipeline["stale"],
        "stale_error_code": pipeline["stale_result"]["rejected_error_code"],
    }


def _insert_asset_version(
    database_url: str, project_id: str, asset_type: str, content: dict[str, Any]
) -> str:
    asset_id = f"worker-e2e:{asset_type}:{uuid4()}"
    version_id = f"{asset_id}:v1"
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
            [asset_id, project_id, asset_type],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,eligibility,
                governance,content,content_hash,schema_version
            ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'worker-e2e-fixture.v1')
            """,
            [version_id, asset_id, Jsonb(content), digest],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_qualification(
                qualification_id,asset_version_id,policy_version,decision,evidence
            ) VALUES (%s,%s,'worker-e2e-fixture-v1','ELIGIBLE',%s)
            """,
            [
                f"{version_id}:qualification",
                version_id,
                Jsonb({"fixture_protocol_only": True}),
            ],
        )
    return version_id


def _mkaos_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from decimal import Decimal

    from novel_forge.modules.mkaos_authority import (
        ApproveKnowledgeCandidateCommand,
        BuildKnowledgePackCommand,
        CommitKnowledgeCandidateCommand,
        KnowledgeEvidenceSpan,
        KnowledgePackSelection,
        MkaosAuthorityApplication,
        MkaosAuthorityQuery,
    )

    project_id, workspace_id, _ = _project(settings.database_url, "mkaos")
    source = _source_pipeline(
        settings,
        project_id=project_id,
        workspace_id=workspace_id,
        recover_registration=False,
    )
    execution_version = _insert_asset_version(
        settings.database_url,
        project_id,
        "model_call_log",
        {
            "execution_id": f"fixture-execution:{uuid4()}",
            "gateway": "ProductionExecutionGateway",
            "fixture_protocol_only": True,
            "real_provider_proven": False,
        },
    )
    target_version = _insert_asset_version(
        settings.database_url,
        project_id,
        "chapter_plan",
        {"chapter": 1, "status": "PLANNED"},
    )
    principal = _fixture_principal(
        project_id,
        {"mkaos.authority.execute", "mkaos.authority.approve", "mkaos.authority.query"},
    )
    application = MkaosAuthorityApplication(
        settings.database_url,
        application_build_id="worker-fleet-compose-e2e",
        commit_sha=os.environ["NOVEL_FORGE_COMMIT_SHA"],
        allow_fixture_activation=True,
    )
    candidate_command = CommitKnowledgeCandidateCommand(
        project_id=project_id,
        workspace_id=workspace_id,
        execution_asset_version_id=execution_version,
        candidate={
            "concept_name": "Escalating obligation",
            "discipline": "organizational behavior",
            "abstract_principle": "A favor creates conflict when repayment criteria change after consent.",
            "constraints": ["Expose who changed the repayment criterion."],
            "conflict_generators": [
                "The parties disagree whether the debt is settled."
            ],
            "review_checks": ["Reject proper nouns and source-specific expression."],
            "copyright_boundaries": [
                "Retain only the abstract mechanism and evidence identity."
            ],
        },
        evidence_spans=(
            KnowledgeEvidenceSpan(
                source_chunk_asset_version_id=source["source_chunk_asset_version_id"],
                chunk_byte_start=0,
                chunk_byte_end=10,
                evidence_hash="sha256:" + hashlib.sha256(b"span-0-10").hexdigest(),
            ),
        ),
        abstraction_policy_version="anti-copy-abstraction:v1",
        actor_id=principal.principal_id,
        idempotency_key=f"candidate:{execution_version}",
        trace_id=f"trace:candidate:{execution_version}",
        correlation_id=f"correlation:candidate:{execution_version}",
    )
    control.stop_target()
    candidate_admission = application.admit_candidate(
        candidate_command, principal=principal
    )
    stale, assert_stale = _prepare_operation_recovery(
        settings, project_id, str(candidate_admission["operation_id"])
    )
    control.start_target()
    _wait_operation(settings.database_url, str(candidate_admission["operation_id"]))
    candidate = application.result(
        str(candidate_admission["operation_id"]), project_id, replayed=False
    )
    stale_result = assert_stale()
    approval_admission = application.admit_approval(
        ApproveKnowledgeCandidateCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            candidate_asset_version_id=str(candidate["asset_version_id"]),
            policy_version="mkaos-governance:v1",
            rationale="Abstract, traceable fixture evidence with no source prose.",
            actor_id=principal.principal_id,
            idempotency_key=f"approve:{candidate['asset_version_id']}",
            trace_id=f"trace:approve:{candidate['asset_version_id']}",
            correlation_id=f"correlation:approve:{candidate['asset_version_id']}",
        ),
        principal=principal,
    )
    _wait_operation(settings.database_url, str(approval_admission["operation_id"]))
    approval = application.result(
        str(approval_admission["operation_id"]), project_id, replayed=False
    )
    selector_hash = "sha256:" + hashlib.sha256(b"worker-e2e-selector-v1").hexdigest()
    pack_admission = application.admit_pack(
        BuildKnowledgePackCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            target_asset_version_id=target_version,
            selector_policy_version="mkaos-explicit-selector:v1",
            selector_policy_hash=selector_hash,
            selections=(
                KnowledgePackSelection(
                    knowledge_card_asset_version_id=str(approval["asset_version_id"]),
                    usage_role="constraint",
                    frozen_weight=Decimal("2.5"),
                ),
            ),
            actor_id=principal.principal_id,
            idempotency_key=f"pack:{target_version}",
            trace_id=f"trace:pack:{target_version}",
            correlation_id=f"correlation:pack:{target_version}",
        ),
        principal=principal,
    )
    _wait_operation(settings.database_url, str(pack_admission["operation_id"]))
    pack = application.result(
        str(pack_admission["operation_id"]), project_id, replayed=False
    )
    query = MkaosAuthorityQuery(settings.database_url)
    stored = query.require_pack(
        project_id=project_id, knowledge_pack_id=str(pack["knowledge_pack_id"])
    )
    execution = _operation_execution_evidence(
        settings.database_url, str(candidate_admission["operation_id"])
    )
    return {
        "scenario": "Candidate, independent approval, Knowledge Card/Pack and crash recovery",
        "work_id": str(candidate_admission["operation_id"]),
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": {
            "source_chunk_asset_version_id": source["source_chunk_asset_version_id"],
            "candidate_asset_version_id": candidate["asset_version_id"],
            "approval_operation_id": approval_admission["operation_id"],
            "knowledge_card_asset_version_id": approval["asset_version_id"],
            "pack_operation_id": pack_admission["operation_id"],
            "knowledge_pack_id": pack["knowledge_pack_id"],
            "pack_item_count": stored["item_count"],
            "fixture_evidence": True,
        },
        "expired_claim": stale,
        "stale_error_code": stale_result["rejected_error_code"],
    }


def _expire_runtime_job_claim(database_url: str, attempt_id: str) -> None:
    def expired() -> bool:
        with _connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status='HELD' AND lease_expires_at<=NOW() "
                "FROM authority_runtime_job_lease WHERE attempt_id=%s",
                [attempt_id],
            )
            row = cursor.fetchone()
        return bool(row and row[0])

    _poll("fixture Runtime Job lease expiry", expired, bool, timeout=5)


def _assert_stale_runtime_job(runtime_jobs: Any, claim: Any) -> str:
    from novel_forge.modules.command_kernel.errors import KernelError

    try:
        runtime_jobs.checkpoint(claim, {"stage": "STALE_WORKER_MUST_NOT_COMMIT"})
    except KernelError as error:
        return error.code
    raise RuntimeError("stale Runtime Job worker was accepted")


def _runtime_job_evidence(database_url: str, runtime_job_id: str) -> dict[str, Any]:
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT job.status, attempt.attempt_id, attempt.worker_id,
                   attempt.fencing_token, lease.lease_id,
                   COALESCE((SELECT checkpoint FROM authority_runtime_job_checkpoint
                     WHERE attempt_id=attempt.attempt_id
                     ORDER BY checkpoint_sequence DESC LIMIT 1),'{}'::jsonb),
                   result.result
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
            LEFT JOIN authority_runtime_job_result AS result
              ON result.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
            """,
            [runtime_job_id],
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Runtime Job evidence disappeared")
    return {
        "status": str(row[0]),
        "attempt_id": str(row[1]),
        "claimed_by": str(row[2]),
        "fencing_token": int(row[3]),
        "lease_id": str(row[4]),
        "checkpoint": dict(row[5] or {}),
        "result": dict(row[6] or {}),
    }


def _book_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import (
        build_book_authority_application,
        build_chapter_authority_application,
        build_production_execution_composition,
    )
    from novel_forge.modules.book_authority import (
        PostgresBookProductionQuery,
        StartBookProductionCommand,
        SubmitBookChapterCommand,
    )
    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    from novel_forge.workers.book_authority import schedule_book_coordination_jobs
    from tests.integration.test_book_to_chapter_authority_vertical_postgres import (
        BookToChapterAuthorityVerticalPostgresTests,
    )
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    project_id = f"worker-e2e-book-{uuid4().hex[:12]}"
    principal = BookToChapterAuthorityVerticalPostgresTests._principal(project_id)
    candidates = PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    versions = BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(project_id)
    execution = build_production_execution_composition(settings, env=os.environ)
    chapter = build_chapter_authority_application(
        settings, execution=execution, env=os.environ
    )
    application = build_book_authority_application(
        settings,
        execution=execution,
        chapter_application=chapter,
        env=os.environ,
    )
    control.stop_target()
    book = application.start(
        StartBookProductionCommand(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            book_id=f"book:{project_id}",
            actor_id=principal.principal_id,
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            stable_idempotency_key=f"{project_id}:book:v1",
            book_design_version=versions.pop("book_design_version"),
            book_plan_version=versions.pop("book_plan_version"),
            production_profile_version="production-profile:v1",
            longform_context_versions=versions,
            target_chapter_count=1,
            input_mode="LEGACY_FIXTURE_INPUT_MODE",
            light_recap_cadence=1,
            formal_recap_cadence=1,
        ),
        principal=principal,
    )
    plan = next(item for item in candidates if item["asset_type"] == "chapter_plan")
    chapter = application.submit_chapter(
        SubmitBookChapterCommand(
            book_run_id=book.book_run_id,
            chapter_number=1,
            title="Recovered Book Chapter",
            premise="A worker replacement must advance the same Book exactly once.",
            chapter_plan_asset_version_id=str(plan["asset_version_id"]),
            chapter_plan_content_hash=str(plan["content_hash"]),
            context_candidates=tuple(candidates),
        ),
        principal=principal,
    )
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    scheduled = schedule_book_coordination_jobs(
        PostgresBookProductionQuery(settings.database_url),
        runtime_jobs,
        limit=1,
        book_run_id=book.book_run_id,
    )
    if len(scheduled) != 1:
        raise RuntimeError("Book Runtime Job was not scheduled")
    stale_claim = runtime_jobs.claim(
        runtime_group="book",
        worker_id="book-crashed-worker",
        lease_seconds=1,
        job_kinds=("BOOK_COORDINATION_TICK",),
        subject_kind="BOOK_RUN",
        subject_id=book.book_run_id,
    )
    if stale_claim is None:
        raise RuntimeError("Book Runtime Job could not be claimed")
    _expire_runtime_job_claim(settings.database_url, stale_claim.attempt_id)
    control.start_target()

    def book_state() -> dict[str, Any]:
        return application.require(book.book_run_id)

    final = _poll(
        "Book worker chain",
        book_state,
        lambda state: (
            state["state"] == "COMPLETED"
            and int(state["accepted_through_chapter"]) == 1
        ),
        timeout=240,
    )
    execution = _poll(
        "recovered Book Runtime Job",
        lambda: _runtime_job_evidence(
            settings.database_url, stale_claim.runtime_job_id
        ),
        lambda item: item["status"] == "SUCCEEDED" and item["fencing_token"] >= 2,
    )
    stale_error = _assert_stale_runtime_job(runtime_jobs, stale_claim)
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s",
            [book.book_run_id],
        )
        acceptance_count = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COUNT(*) FROM authority_runtime_job "
            "WHERE runtime_group='book' AND subject_id=%s AND status='SUCCEEDED'",
            [book.book_run_id],
        )
        completed_ticks = int(cursor.fetchone()[0])
    return {
        "scenario": "Book Runtime Job tick, real Chapter child acceptance/follow-up and recovery",
        "work_id": book.book_run_id,
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": {
            "chapter_request_id": chapter["chapter_request_id"],
            "chapter_root_operation_id": chapter["chapter_root_operation_id"],
            "book_state": final["state"],
            "accepted_through_chapter": final["accepted_through_chapter"],
            "acceptance_count": acceptance_count,
            "completed_runtime_ticks": completed_ticks,
            "autonomous_book_loop_proven": False,
        },
        "expired_claim": {
            "attempt_id": stale_claim.attempt_id,
            "lease_id": stale_claim.lease_id,
            "fencing_token": stale_claim.fencing_token,
        },
        "stale_error_code": stale_error,
    }


def _insert_outbox_event(
    database_url: str, project_id: str, *, poison: bool = False
) -> tuple[str, str]:
    event_id = f"worker-e2e-event:{uuid4()}"
    outbox_id = f"worker-e2e-outbox:{uuid4()}"
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO state_event(
                event_id,aggregate_type,aggregate_id,project_id,event_type,
                event_version,sequence_number,payload
            ) VALUES (%s,'worker_e2e',%s,%s,'worker.e2e',1,1,%s)
            """,
            [event_id, outbox_id, project_id, Jsonb({"fixture": True})],
        )
        cursor.execute(
            """
            INSERT INTO outbox_event(
                outbox_id,event_id,project_id,topic,status,payload,attempt_count
            ) VALUES (%s,%s,%s,'worker.e2e','PENDING',%s,%s)
            """,
            [
                outbox_id,
                event_id,
                project_id,
                Jsonb({"fixture": True}),
                4 if poison else 0,
            ],
        )
    return outbox_id, event_id


def _outbox_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from novel_forge.workers.outbox_authority import PostgresOutboxDispatcher

    project_id = f"worker-e2e-outbox-{uuid4().hex[:12]}"
    control.stop_target()
    outbox_id, event_id = _insert_outbox_event(settings.database_url, project_id)
    stale_dispatcher = PostgresOutboxDispatcher(
        settings.database_url, worker_id="outbox-crashed-worker", lease_seconds=30
    )
    stale = stale_dispatcher.claim(limit=1, project_id=project_id)[0]
    stale_dispatcher.checkpoint(stale, {"stage": "INTERNAL_DELIVERY_STARTED"})
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE outbox_event SET lease_expires_at=NOW()-INTERVAL '1 second' WHERE outbox_id=%s",
            [outbox_id],
        )
    control.start_target()

    def outbox_state() -> tuple[Any, ...]:
        with (
            _connect(settings.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT status,claimed_by,lease_id,fencing_token,published_at IS NOT NULL,"
                "acked_at IS NOT NULL FROM outbox_event WHERE outbox_id=%s",
                [outbox_id],
            )
            return tuple(cursor.fetchone())

    terminal = _poll(
        "Outbox delivery",
        outbox_state,
        lambda row: (
            str(row[0]).lower() == "acked" and int(row[3]) >= 2 and row[4] and row[5]
        ),
    )
    replay_delivered = stale_dispatcher.deliver(stale)
    if replay_delivered:
        raise RuntimeError("acked Outbox delivery was not idempotent on replay")
    try:
        stale_dispatcher.checkpoint(stale, {"stage": "STALE_WORKER_COMMIT"})
    except RuntimeError as error:
        stale_error = type(error).__name__ + ":" + str(error)
    else:
        raise RuntimeError("stale Outbox claim was accepted")
    poison_id, _ = _insert_outbox_event(settings.database_url, project_id, poison=True)
    poison_dispatcher = PostgresOutboxDispatcher(
        settings.database_url, worker_id="outbox-poison-fixture", lease_seconds=30
    )
    poison_claim = poison_dispatcher.claim(limit=1, project_id=project_id)[0]
    poison = poison_dispatcher.fail(poison_claim, {"code": "FIXTURE_POISON_DELIVERY"})
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT outbox_delivery_execution_id,checkpoint,lease_id,fencing_token,worker_id "
            "FROM authority_outbox_delivery_execution "
            "WHERE outbox_id=%s AND fencing_token=%s",
            [outbox_id, int(terminal[3])],
        )
        execution = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) FROM outbox_consumer_delivery WHERE event_id=%s",
            [event_id],
        )
        receipt_count = int(cursor.fetchone()[0])
    return {
        "scenario": "Internal Outbox claim/checkpoint/ack/replay, poison and lease recovery",
        "work_id": outbox_id,
        "attempt_or_job_id": str(execution[0]),
        "lease_id": str(execution[2]),
        "fencing_token": int(execution[3]),
        "checkpoint": json.dumps(dict(execution[1] or {}), sort_keys=True),
        "claimed_by": str(execution[4]),
        "domain_evidence": {
            "event_id": event_id,
            "delivery_status": terminal[0],
            "receipt_count": receipt_count,
            "duplicate_replay_delivered": replay_delivered,
            "internal_delivery_only": True,
            "external_broker_proven": False,
            "poison_outbox_id": poison_id,
            "poison_status": poison["status"],
        },
        "expired_claim": {
            "lease_id": stale.lease_id,
            "fencing_token": stale.fencing_token,
            "worker_id": "outbox-crashed-worker",
        },
        "stale_error_code": stale_error,
    }


def _maintenance_fixtures(database_url: str) -> dict[str, str]:
    ids = {
        name: f"worker-e2e-{name}:{uuid4()}"
        for name in (
            "project",
            "definition",
            "operation",
            "attempt",
            "lease",
            "event",
            "outbox",
            "effect",
        )
    }
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO authority_operation_definition(name,definition_version,family,enabled,"
            "command_schema,result_schema,policy,completion_contract) "
            "VALUES (%s,'1.0.0','maintenance',TRUE,'{}','{}','{}','{}')",
            [ids["definition"]],
        )
        cursor.execute(
            """
            INSERT INTO authority_operation(
                operation_id,definition_name,definition_version,project_id,status,
                root_operation_id,idempotency_scope,idempotency_key,request_digest,
                definition_snapshot,completion_contract_snapshot,policy_snapshot,
                business_deadline_at
            ) VALUES (%s,%s,'1.0.0',%s,'READY',%s,%s,%s,%s,'{}','{}','{}',
                      NOW()-INTERVAL '1 second')
            """,
            [
                ids["operation"],
                ids["definition"],
                ids["project"],
                ids["operation"],
                f"project:{ids['project']}",
                ids["operation"],
                f"digest:{ids['operation']}",
            ],
        )
        cursor.execute(
            "INSERT INTO authority_attempt(attempt_id,operation_id,attempt_number,status,worker_id,started_at) "
            "VALUES (%s,%s,1,'RUNNING','crashed-maintenance-worker',NOW()-INTERVAL '2 minutes')",
            [ids["attempt"], ids["operation"]],
        )
        cursor.execute(
            "INSERT INTO authority_lease_acquisition(lease_id,attempt_id,owner,fencing_token,"
            "acquired_at,expires_at,status) VALUES (%s,%s,'crashed-maintenance-worker',1,"
            "NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute','HELD')",
            [ids["lease"], ids["attempt"]],
        )
        cursor.execute(
            "INSERT INTO state_event(event_id,aggregate_type,aggregate_id,project_id,event_type,"
            "event_version,sequence_number,payload) VALUES (%s,'maintenance',%s,%s,"
            "'maintenance.fixture',1,1,'{}')",
            [ids["event"], ids["outbox"], ids["project"]],
        )
        cursor.execute(
            """
            INSERT INTO outbox_event(
                outbox_id,event_id,project_id,topic,status,claimed_by,claimed_at,
                lease_expires_at,payload,attempt_count,lease_id,fencing_token,runtime_group
            ) VALUES (%s,%s,%s,'maintenance.fixture','claimed','crashed-outbox',
                NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute','{}',1,%s,1,'outbox')
            """,
            [ids["outbox"], ids["event"], ids["project"], f"{ids['outbox']}:1"],
        )
        cursor.execute(
            """
            INSERT INTO authority_external_effect(
                external_effect_id,operation_id,project_id,effect_type,
                stable_idempotency_key,status,request_hash,request_payload,
                provider,capability,reconciliation_mode,provider_query_mode
            ) VALUES (%s,%s,%s,'fixture.unknown',%s,'UNKNOWN',%s,'{}',
                      'unavailable-fixture-provider','fixture.query','unsupported','unsupported')
            """,
            [
                ids["effect"],
                ids["operation"],
                ids["project"],
                ids["effect"],
                f"sha256:{uuid4().hex}",
            ],
        )
    return ids


def _maintenance_scenario(settings: Any, control: "ComposeControl") -> dict[str, Any]:
    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    from novel_forge.workers.runtime_groups import (
        MAINTENANCE_RUNTIME_JOB_KINDS,
        schedule_maintenance_runtime_jobs,
    )

    control.stop_target()
    ids = _maintenance_fixtures(settings.database_url)
    runtime_jobs = RuntimeJobAuthority(settings.database_url)
    scheduled = schedule_maintenance_runtime_jobs(
        runtime_jobs, batch_limit=10_000, schedule_bucket=time.time_ns()
    )
    stale_claim = runtime_jobs.claim(
        runtime_group="maintenance",
        worker_id="maintenance-crashed-worker",
        lease_seconds=1,
        job_kinds=("OPERATION_DEADLINE_SCAN",),
    )
    if stale_claim is None:
        raise RuntimeError("Maintenance Runtime Job could not be claimed")
    _expire_runtime_job_claim(settings.database_url, stale_claim.attempt_id)
    control.start_target()

    scheduled_ids = [str(item["runtime_job_id"]) for item in scheduled]

    def maintenance_state() -> dict[str, Any]:
        with (
            _connect(settings.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT COUNT(*) FROM authority_runtime_job WHERE runtime_job_id=ANY(%s) AND status='SUCCEEDED'",
                [scheduled_ids],
            )
            succeeded = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [ids["operation"]],
            )
            operation = str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT status FROM authority_lease_acquisition WHERE lease_id=%s",
                [ids["lease"]],
            )
            attempt_lease = str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT status FROM authority_external_effect WHERE external_effect_id=%s",
                [ids["effect"]],
            )
            effect = str(cursor.fetchone()[0])
            cursor.execute(
                "SELECT status FROM outbox_event WHERE outbox_id=%s",
                [ids["outbox"]],
            )
            outbox = str(cursor.fetchone()[0]).lower()
        return {
            "succeeded_jobs": succeeded,
            "operation_status": operation,
            "attempt_lease_status": attempt_lease,
            "external_effect_status": effect,
            "outbox_status": outbox,
        }

    terminal = _poll(
        "Maintenance Runtime Job fleet",
        maintenance_state,
        lambda state: (
            state["succeeded_jobs"] == len(MAINTENANCE_RUNTIME_JOB_KINDS)
            and state["operation_status"] in {"CANCELLATION_REQUESTED", "CANCELLED"}
            and state["attempt_lease_status"] == "EXPIRED"
            and state["outbox_status"] in {"failed", "dead_letter", "acked"}
        ),
    )
    execution = _runtime_job_evidence(settings.database_url, stale_claim.runtime_job_id)
    if execution["status"] != "SUCCEEDED" or execution["fencing_token"] < 2:
        raise RuntimeError(
            "Maintenance Runtime Job was not taken over by a higher fence"
        )
    stale_error = _assert_stale_runtime_job(runtime_jobs, stale_claim)
    with _connect(settings.database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT result FROM authority_runtime_job_result AS result "
            "JOIN authority_runtime_job_attempt AS attempt ON attempt.attempt_id=result.attempt_id "
            "JOIN authority_runtime_job AS job ON job.current_attempt_id=attempt.attempt_id "
            "WHERE job.runtime_job_id=ANY(%s) AND job.job_kind='EXTERNAL_EFFECT_RECONCILIATION_SCAN'",
            [scheduled_ids],
        )
        reconciliation = dict(cursor.fetchone()[0])
        cursor.execute(
            "SELECT result FROM authority_runtime_job_result AS result "
            "JOIN authority_runtime_job_attempt AS attempt ON attempt.attempt_id=result.attempt_id "
            "JOIN authority_runtime_job AS job ON job.current_attempt_id=attempt.attempt_id "
            "WHERE job.runtime_job_id=ANY(%s) AND job.job_kind='OUTBOX_RECOVERY_SCAN'",
            [scheduled_ids],
        )
        outbox_recovery = dict(cursor.fetchone()[0])
    matching_effects = [
        item
        for item in reconciliation["reconciliation_required"]
        if item.get("external_effect_id") == ids["effect"]
    ]
    if len(matching_effects) != 1 or matching_effects[0].get("action") != (
        "QUERY_OR_MANUAL_RECONCILIATION_REQUIRED"
    ):
        raise RuntimeError(
            "Maintenance E2E did not retain the seeded unknown effect as query/manual required"
        )
    matching_outbox = [
        item
        for item in outbox_recovery["recovered_outbox"]
        if item.get("outbox_id") == ids["outbox"]
    ]
    if len(matching_outbox) != 1 or matching_outbox[0].get("status") not in {
        "failed",
        "dead_letter",
    }:
        raise RuntimeError(
            "Maintenance E2E did not record recovery of the seeded expired Outbox claim"
        )
    return {
        "scenario": "Deadline/lease/outbox/effect scans through fenced Runtime Jobs and recovery",
        "work_id": stale_claim.runtime_job_id,
        "attempt_or_job_id": execution["attempt_id"],
        "lease_id": execution["lease_id"],
        "fencing_token": execution["fencing_token"],
        "checkpoint": json.dumps(execution["checkpoint"], sort_keys=True),
        "claimed_by": execution["claimed_by"],
        "domain_evidence": {
            **terminal,
            "runtime_job_ids": scheduled_ids,
            "unknown_effect_action": reconciliation["reconciliation_required"],
            "seeded_unknown_effect": matching_effects[0],
            "seeded_outbox_recovery": matching_outbox[0],
            "provider_query_proven": reconciliation["provider_query_proven"],
        },
        "expired_claim": {
            "attempt_id": stale_claim.attempt_id,
            "lease_id": stale_claim.lease_id,
            "fencing_token": stale_claim.fencing_token,
        },
        "stale_error_code": stale_error,
    }


SCENARIOS: dict[str, Callable[[Any, "ComposeControl"], dict[str, Any]]] = {
    "chapter": _chapter_scenario,
    "content": _content_scenario,
    "source": _source_scenario,
    "mkaos": _mkaos_scenario,
    "book": _book_scenario,
    "outbox": _outbox_scenario,
    "maintenance": _maintenance_scenario,
}


class ComposeControl:
    def __init__(self, project: str, env: dict[str, str], worker: str) -> None:
        self.project = project
        self.env = env
        self.worker = worker
        self.service = WORKER_SERVICES[worker]
        self.restart_performed = False

    def stop_target(self) -> None:
        _run(
            _compose(self.project, "stop", "-t", "45", self.service),
            env=self.env,
            timeout=90,
        )

    def start_target(self) -> None:
        _run(
            _compose(
                self.project,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                self.service,
            ),
            env=self.env,
            timeout=180,
        )
        self.restart_performed = True

    def drain(self, database_url: str) -> dict[str, Any]:
        _run(
            _compose(self.project, "stop", "-t", "45", *ALL_SERVICES),
            env=self.env,
            timeout=240,
        )

        def governance() -> dict[str, int]:
            with _connect(database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE state='idle in transaction'),
                           COUNT(*) FILTER (WHERE xact_start IS NOT NULL),
                           COUNT(*) FILTER (WHERE application_name=ANY(%s))
                    FROM pg_stat_activity WHERE pid<>pg_backend_pid()
                    """,
                    [list(ALL_SERVICES)],
                )
                row = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM authority_worker_health_projection "
                    "WHERE status='STOPPED' AND drain_status='DRAINED'"
                )
                drained = int(cursor.fetchone()[0])
            return {
                "idle_in_transaction": int(row[0]),
                "active_transactions": int(row[1]),
                "worker_connections": int(row[2]),
                "drained_worker_count": drained,
            }

        result = _poll(
            "worker drain",
            governance,
            lambda item: (
                item["idle_in_transaction"] == 0
                and item["active_transactions"] == 0
                and item["worker_connections"] == 0
                and item["drained_worker_count"] >= 7
            ),
            timeout=90,
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=tuple(SCENARIOS), required=True)
    parser.add_argument("--project-name", default="")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    commit_sha = _run(["git", "rev-parse", "HEAD"], env=dict(os.environ), timeout=10)
    project = args.project_name or f"novel-forge-{args.worker}-e2e-{os.getpid()}"
    postgres_port = _free_port()
    minio_port = _free_port()
    api_port = _free_port()
    env = {
        **os.environ,
        "NOVEL_FORGE_COMMIT_SHA": commit_sha,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": f"worker-e2e-{commit_sha[:12]}",
        "NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
        "NOVEL_FORGE_POSTGRES_PASSWORD": "novel_forge_dev_only",
        "NOVEL_FORGE_MINIO_ACCESS_KEY": "novel_forge",
        "NOVEL_FORGE_MINIO_SECRET_KEY": "novel_forge_dev_only",
        "NOVEL_FORGE_MKAOS_ALLOW_FIXTURE_ACTIVATION": "true",
        "NOVEL_FORGE_WORKER_E2E_POSTGRES_PORT": str(postgres_port),
        "NOVEL_FORGE_WORKER_E2E_MINIO_PORT": str(minio_port),
        "NOVEL_FORGE_AUTHORITY_API_PORT": str(api_port),
    }
    database_url = f"postgresql://novel_forge:novel_forge_dev_only@127.0.0.1:{postgres_port}/novel_forge"
    host_env = {
        **env,
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
        "NOVEL_FORGE_DATABASE_URL": database_url,
        "NOVEL_FORGE_MINIO_ENDPOINT": f"127.0.0.1:{minio_port}",
        "NOVEL_FORGE_MINIO_ACCESS_KEY": "novel_forge",
        "NOVEL_FORGE_MINIO_SECRET_KEY": "novel_forge_dev_only",
        "NOVEL_FORGE_MINIO_SECURE": "false",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": (
            f"/tmp/novel-forge-worker-e2e-{os.getpid()}"
        ),
    }
    os.environ.update(host_env)
    started = time.monotonic()
    control = ComposeControl(project, env, args.worker)
    up = ["up", "-d"]
    if not args.no_build:
        up.append("--build")
    up.extend(("--wait", "--wait-timeout", "300"))
    try:
        _run(
            _compose(project, "down", "--volumes", "--remove-orphans"),
            env=env,
            timeout=120,
        )
        _run(_compose(project, *up), env=env, timeout=900)
        from novel_forge.infrastructure.settings import IndustrialSettings
        from novel_forge.storage.database_runtime import close_all_database_runtimes
        from novel_forge.tools.worker_fleet_evidence import validate_worker_evidence

        settings = IndustrialSettings.from_env()
        scenario = SCENARIOS[args.worker](settings, control)
        drain = control.drain(database_url)
        runtime_group, worker_id = WORKER_IDENTITIES[args.worker]
        evidence = validate_worker_evidence(
            {
                "type": "AuthorityWorkerComposeEvidence",
                "schema_version": "authority-worker-fleet-evidence.v1",
                "worker": args.worker,
                "scenario": scenario.pop("scenario"),
                "commit_sha": commit_sha,
                "runtime_group": runtime_group,
                "worker_id": worker_id,
                **scenario,
                "restart": control.restart_performed,
                "recovery": True,
                "stale_rejection": True,
                "graceful_drain": drain["drained_worker_count"] >= 7,
                "zero_leaked_connections": drain["worker_connections"] == 0,
                "shutdown_database_governance": drain,
                "fixture": True,
                "real_provider_proven": False,
                "longform_proven": False,
                "production_verified": False,
                "duration_seconds": round(time.monotonic() - started, 3),
                "result": "PASS",
            },
            expected_worker=args.worker,
            expected_sha=commit_sha,
        )
        close_all_database_runtimes()
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0
    except Exception:
        logs = _run(
            _compose(project, "logs", "--no-color", "--tail", "200"),
            env=env,
            timeout=120,
            check=False,
        )
        if logs:
            print(logs, file=os.sys.stderr)
        raise
    finally:
        if not args.keep:
            _run(
                _compose(project, "down", "--volumes", "--remove-orphans"),
                env=env,
                timeout=180,
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
