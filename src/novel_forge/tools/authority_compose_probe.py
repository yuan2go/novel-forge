"""Synthetic fixture probe used only by the Authority Compose smoke runner."""
from __future__ import annotations

import argparse
import json
import time
from uuid import uuid4

from novel_forge.api.authority_dependencies import (
    authority_release_identity,
    build_content_authority_application,
    build_trusted_principal_resolver,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.content_authority import ContentOperationRequest
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    heartbeat_attempt,
    queue_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.database_runtime import close_all_database_runtimes


BRIEF = {
    "target_genre": "engineering_fixture",
    "subgenre": "authority_smoke",
    "target_platform": "fixture",
    "target_audience": "test",
    "reading_promise": "schema-backed deterministic evidence",
    "core_fantasy": "none",
    "core_conflict": "none",
    "protagonist_mechanism": "synthetic",
    "antagonist_mechanism": "synthetic",
    "world_novelty": "synthetic",
    "emotional_engine": "synthetic",
    "pleasure_engine": "synthetic",
    "suspense_engine": "synthetic",
    "theme_question": "Can an authority worker recover a frozen command?",
    "serialization_strategy": "single fixture operation",
    "prohibited_elements": ["real novel claims", "real provider claims"],
    "source_boundaries": ["synthetic_only"],
    "quality_targets": {"engineering_smoke": 1},
}


def submit(settings: IndustrialSettings, suffix: str) -> dict[str, str]:
    build_id, commit_sha = authority_release_identity()
    principal = build_trusted_principal_resolver().resolve_api_principal()
    token = suffix or uuid4().hex[:12]
    project_id = f"compose-smoke-project-{token}"
    workspace_id = f"compose-smoke-workspace-{token}"
    project = ProjectAuthorityApplication(
        settings.database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
    )
    project_result = project.execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            idempotency_key=f"compose-smoke:project:{token}",
            trace_id=f"compose-smoke:trace:{token}",
            correlation_id=f"compose-smoke:correlation:{token}",
            payload={"title": "Authority Compose Fixture", "stage": "DESIGN"},
        ),
        principal=principal,
    )
    content = build_content_authority_application(settings)
    admission = content.admit(
        ContentOperationRequest(
            definition_name="creative.brief.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            trace_id=f"compose-smoke:trace:{token}",
            correlation_id=f"compose-smoke:correlation:{token}",
            idempotency_key=f"compose-smoke:content:{token}",
            payload={"brief": BRIEF},
        ),
        principal=principal,
    )
    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "project_operation_id": str(project_result["operation_id"]),
        "operation_id": admission.operation_id,
        "evidence_level": "COMPOSE_SMOKE_PROVEN",
        "fixture": "true",
    }


def verify(
    settings: IndustrialSettings,
    *,
    project_id: str,
    operation_id: str,
    timeout_seconds: float,
    min_fencing_token: int = 1,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    evidence: dict[str, object] = {}
    while True:
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_operation "
                "WHERE operation_id=%s AND project_id=%s",
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
            status = str(row[0]) if row else "MISSING"
            uow.cursor.execute(
                """
                SELECT COUNT(*), COALESCE(MAX(attempt_number),0)
                FROM authority_attempt WHERE operation_id=%s
                """,
                [operation_id],
            )
            attempt_count, max_attempt = map(int, uow.cursor.fetchone())
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation_output_asset
                WHERE operation_id=%s
                """,
                [operation_id],
            )
            output_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "SELECT COUNT(*) FROM audit_log WHERE operation_id=%s",
                [operation_id],
            )
            audit_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM outbox_event
                WHERE project_id=%s
                  AND payload->>'operation_id'=%s
                  AND published_at IS NOT NULL
                """,
                [project_id, operation_id],
            )
            published_outbox_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*), COALESCE(MAX(lease.fencing_token),0)
                FROM authority_attempt AS attempt
                LEFT JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id=attempt.attempt_id
                WHERE attempt.operation_id=%s
                """,
                [operation_id],
            )
            lease_count, max_fence = map(int, uow.cursor.fetchone())
        evidence = {
            "project_id": project_id,
            "operation_id": operation_id,
            "operation_status": status,
            "attempt_count": attempt_count,
            "max_attempt_number": max_attempt,
            "output_asset_count": output_count,
            "audit_count": audit_count,
            "published_outbox_count": published_outbox_count,
            "lease_count": lease_count,
            "max_fencing_token": max_fence,
            "fixture": True,
            "real_provider_proven": False,
        }
        if (
            status == "SUCCEEDED"
            and attempt_count >= 1
            and output_count >= 1
            and audit_count >= 1
            and published_outbox_count >= 1
            and lease_count >= 1
            and max_fence >= min_fencing_token
        ):
            return {**evidence, "status": "PASS"}
        if time.monotonic() >= deadline:
            raise RuntimeError(f"compose operation did not converge: {evidence}")
        time.sleep(0.25)


def prepare_expiring_lease(
    settings: IndustrialSettings, *, project_id: str, operation_id: str
) -> dict[str, object]:
    trace_id = f"compose-smoke:crash:{operation_id}"
    correlation_id = f"compose-smoke:recovery:{operation_id}"
    attempt = create_attempt(
        settings.database_url,
        operation_id=operation_id,
        project_id=project_id,
        max_attempts=3,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    attempt_id = str(attempt["attempt_id"])
    queue_attempt(
        settings.database_url,
        attempt_id=attempt_id,
        project_id=project_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    lease = acquire_attempt_lease(
        settings.database_url,
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id="compose-crashed-worker",
        lease_seconds=1,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    return {
        "attempt_id": attempt_id,
        "worker_id": "compose-crashed-worker",
        "fencing_token": int(lease["fencing_token"]),
        "lease_expires_at": str(lease["expires_at"]),
        "fixture": True,
    }


def assert_stale_fence_rejected(
    settings: IndustrialSettings,
    *,
    project_id: str,
    operation_id: str,
    attempt_id: str,
    worker_id: str,
    fencing_token: int,
) -> dict[str, object]:
    command = WorkerLeaseCommand(
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        fencing_token=fencing_token,
        trace_id=f"compose-smoke:stale:{operation_id}",
        correlation_id=f"compose-smoke:stale:{operation_id}",
        causation_id=operation_id,
    )
    try:
        heartbeat_attempt(settings.database_url, command, lease_seconds=10)
    except KernelError as exc:
        if exc.code not in {
            "ATTEMPT_FENCING_TOKEN_STALE",
            "ATTEMPT_LEASE_NOT_OWNED",
            "ATTEMPT_LEASE_INACTIVE",
            "ATTEMPT_LEASE_LOST",
        }:
            raise
        return {
            "status": "PASS",
            "rejected_error_code": exc.code,
            "attempt_id": attempt_id,
            "fencing_token": fencing_token,
        }
    raise RuntimeError("stale fencing token was accepted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--suffix", default="")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--project-id", required=True)
    verify_parser.add_argument("--operation-id", required=True)
    verify_parser.add_argument("--timeout-seconds", type=float, default=30)
    verify_parser.add_argument("--min-fencing-token", type=int, default=1)
    lease_parser = subparsers.add_parser("prepare-expiring-lease")
    lease_parser.add_argument("--project-id", required=True)
    lease_parser.add_argument("--operation-id", required=True)
    stale_parser = subparsers.add_parser("assert-stale-fence")
    stale_parser.add_argument("--project-id", required=True)
    stale_parser.add_argument("--operation-id", required=True)
    stale_parser.add_argument("--attempt-id", required=True)
    stale_parser.add_argument("--worker-id", required=True)
    stale_parser.add_argument("--fencing-token", required=True, type=int)
    args = parser.parse_args(argv)
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Compose probe requires PostgreSQL authority")
    try:
        if args.command == "submit":
            result = submit(settings, args.suffix)
        elif args.command == "verify":
            result = verify(
                settings,
                project_id=args.project_id,
                operation_id=args.operation_id,
                timeout_seconds=args.timeout_seconds,
                min_fencing_token=args.min_fencing_token,
            )
        elif args.command == "prepare-expiring-lease":
            result = prepare_expiring_lease(
                settings,
                project_id=args.project_id,
                operation_id=args.operation_id,
            )
        else:
            result = assert_stale_fence_rejected(
                settings,
                project_id=args.project_id,
                operation_id=args.operation_id,
                attempt_id=args.attempt_id,
                worker_id=args.worker_id,
                fencing_token=args.fencing_token,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        close_all_database_runtimes()


if __name__ == "__main__":
    raise SystemExit(main())
