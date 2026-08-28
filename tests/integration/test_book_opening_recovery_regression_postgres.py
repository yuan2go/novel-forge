from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_recovery_postgres_support import (
    create_legacy_book_opening_orphan,
)


def test_legacy_book_opening_process_loss_strands_cross_layer_execution() -> None:
    """Reproduce the exact pre-closure bug before its invariants are inverted."""

    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()

    assert orphan.cross_layer_state() == (
        "RUNNING",
        "CHECKPOINTED",
        "CHECKPOINTED",
        "HELD",
        True,
        "CANCELLED",
        "LEASE_LOST",
        "EXPIRED",
        0,
    )

    with pytest.raises(KernelError, match="BOOK_OPENING_RESUME_CONFLICT"):
        orphan.opening.resume(
            orphan.opening_run_id,
            expected_version=0,
            principal=orphan.principal,
        )

    for command in (
        orphan.evaluation_command,
        replace(
            orphan.evaluation_command,
            idempotency_key=f"{orphan.evaluation_command.idempotency_key}:replacement",
        ),
    ):
        with pytest.raises(KernelError, match="CONTENT_RECOVERY_TERMINAL"):
            orphan.planning.evaluate_candidate(
                command,
                principal=orphan.evaluator,
                transition_principal=orphan.principal,
            )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_operation
            WHERE project_id=%s
              AND definition_name='story_design.semantic_evaluate'
              AND concurrency_key=(
                  SELECT concurrency_key FROM authority_operation
                  WHERE operation_id=%s
              )
            """,
            [orphan.project_id, orphan.evaluation_operation_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 1

    takeover = RuntimeJobAuthority(DATABASE_URL).claim(
        runtime_group="book_opening",
        worker_id="legacy-silent-takeover-worker",
        lease_seconds=30,
        job_kinds=("BOOK_OPENING_EXECUTE",),
        project_id=orphan.project_id,
    )
    assert takeover is not None
    assert takeover.runtime_job_id == orphan.runtime_job_id
    assert takeover.attempt_id != orphan.outer_claim.attempt_id
    assert takeover.attempt_number == 2
    assert takeover.fencing_token > orphan.outer_claim.fencing_token

