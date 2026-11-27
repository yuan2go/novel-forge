from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from tests.integration.authority_postgres_support import connect
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    CapabilityPackPostgresHarness,
)


@contextmanager
def _rejected_transaction() -> Iterator[psycopg.Cursor]:
    connection = connect()
    try:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg.IntegrityError):
                yield cursor
                connection.commit()
        connection.rollback()
    finally:
        connection.close()


def test_postgres_rejects_approval_deployment_activation_and_rollout_attacks() -> None:
    harness = CapabilityPackPostgresHarness("pack-integrity", book_count=2)
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1, book_id=harness.book_ids[0])
    harness.activate(baseline)
    version_2 = harness.register_compile_approve("1.1.0", generation=2)
    candidate = harness.deploy(version_2, book_id=harness.book_ids[0])
    other_book_deployment = harness.deploy(
        version_2, book_id=harness.book_ids[1]
    )

    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_capability_pack_approval(
                approval_id, compilation_id, compilation_hash, decision,
                approval_policy_ref, approval_scope, reason, evidence_refs,
                limitations, expires_at, decided_by, decided_by_operation_id,
                approval_scope_v1, structured_limitations
            )
            SELECT %s, compilation_id, %s, decision, approval_policy_ref,
                   approval_scope, 'tampered hash', evidence_refs, limitations,
                   expires_at, decided_by, decided_by_operation_id,
                   approval_scope_v1, structured_limitations
            FROM authority_capability_pack_approval
            WHERE compilation_id=%s
            ORDER BY decided_at DESC LIMIT 1
            """,
            [
                f"attack-approval:{uuid4()}",
                "sha256:" + "f" * 64,
                version_1.compilation_id,
            ],
        )

    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_capability_pack_deployment(
                deployment_id, pack_id, pack_version, compilation_id,
                binding_set_id, target_scope_type, scope_key, project_id,
                workspace_id, book_id, environment, workflow_definition_ref,
                deployment_status, rollout_policy_ref, created_by_operation_id
            )
            SELECT %s, pack_id, pack_version, compilation_id, %s,
                   target_scope_type, scope_key, project_id, workspace_id,
                   book_id, environment, workflow_definition_ref,
                   deployment_status, rollout_policy_ref,
                   created_by_operation_id
            FROM authority_capability_pack_deployment
            WHERE deployment_id=%s
            """,
            [
                f"attack-deployment:{uuid4()}",
                baseline.binding_set_id,
                candidate.deployment_id,
            ],
        )

    activation_key = canonical_hash(
        {
            "scope_key": _deployment_scope_key(other_book_deployment.deployment_id),
            "environment": "development",
            "workflow_definition_ref": "chapter_authority_slice@2.3.1",
            "pack_id": harness.pack_id,
        }
    )
    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_capability_pack_activation(
                activation_key, scope_key, target_scope_type, project_id,
                workspace_id, book_id, environment, workflow_definition_ref,
                pack_id, active_deployment_id, activation_version, reason,
                activated_by, activated_by_operation_id
            )
            SELECT %s, scope_key, target_scope_type, project_id, workspace_id,
                   book_id, environment, workflow_definition_ref, pack_id,
                   %s, 1, 'cross-scope attack', 'sql-attacker',
                   created_by_operation_id
            FROM authority_capability_pack_deployment
            WHERE deployment_id=%s
            """,
            [
                activation_key,
                baseline.deployment_id,
                other_book_deployment.deployment_id,
            ],
        )

    other = CapabilityPackPostgresHarness("other-pack-integrity")
    other_version = other.register_compile_approve("1.0.0", generation=1)
    other_candidate = other.deploy(other_version)
    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_capability_pack_rollout(
                rollout_id, baseline_deployment_id, candidate_deployment_id,
                mode, percentage, assignment_key_policy, status,
                started_by_operation_id
            )
            SELECT %s, %s, %s, 'CANARY', 10, 'BOOK', 'CANARY',
                   created_by_operation_id
            FROM authority_capability_pack_deployment
            WHERE deployment_id=%s
            """,
            [
                f"attack-rollout:{uuid4()}",
                baseline.deployment_id,
                other_candidate.deployment_id,
                baseline.deployment_id,
            ],
        )


def test_postgres_rejects_third_deployment_assignment_and_history_mutation() -> None:
    harness = CapabilityPackPostgresHarness("pack-assignment-integrity")
    version = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version)
    candidate = harness.deploy(version)
    third = harness.deploy(version)
    harness.activate(baseline)
    rollout_id = f"rollout:{harness.pack_id}"
    harness.execute(
        "capability_pack.rollout.start",
        principal=harness.compiler,
        pack_version=version.pack_version,
        rollout_id=rollout_id,
        payload={
            "environment": "development",
            "baseline_deployment_id": baseline.deployment_id,
            "candidate_deployment_id": candidate.deployment_id,
            "mode": "PERCENTAGE",
            "percentage": 50,
            "assignment_key_policy": "BOOK",
        },
    )
    snapshot = CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
        harness.resolution_request()
    )
    subject = harness.book_ids[0]
    attack_subject = f"{subject}:attack"
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT authority_capability_pack_bucket(%s, %s)",
            [rollout_id, attack_subject],
        )
        bucket = int(cursor.fetchone()[0])
    assignment_id = f"attack-assignment:{uuid4()}"
    assignment_hash = canonical_hash(
        {
            "assignment_id": assignment_id,
            "bucket": bucket,
            "rollout_id": rollout_id,
            "selected_deployment_id": third.deployment_id,
            "subject_key": attack_subject,
        }
    )
    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO authority_capability_pack_assignment(
                assignment_id, rollout_id, subject_key, bucket,
                selected_deployment_id, assignment_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                assignment_id,
                rollout_id,
                attack_subject,
                bucket,
                third.deployment_id,
                assignment_hash,
            ],
        )
    with _rejected_transaction() as cursor:
        cursor.execute(
            """
            UPDATE authority_capability_pack_assignment
            SET selected_deployment_id=%s
            WHERE assignment_id=%s
            """,
            [third.deployment_id, snapshot.assignment_ref],
        )


def _deployment_scope_key(deployment_id: str) -> str:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT scope_key FROM authority_capability_pack_deployment
            WHERE deployment_id=%s
            """,
            [deployment_id],
        )
        return str(cursor.fetchone()[0])
