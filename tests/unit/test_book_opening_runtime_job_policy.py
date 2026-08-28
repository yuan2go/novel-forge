from __future__ import annotations

import pytest

from novel_forge.modules.runtime_job import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    RuntimeJobSpec,
)


def _book_opening_spec(*, max_attempts: int = 1) -> RuntimeJobSpec:
    return RuntimeJobSpec(
        job_kind="BOOK_OPENING_EXECUTE",
        runtime_group="book_opening",
        subject_kind="BOOK_OPENING_RUN",
        subject_id="book-opening:policy-test",
        project_id="project:policy-test",
        dedupe_key="book-opening:policy-test:generation:1",
        input_snapshot={"execution_generation": 1},
        max_attempts=max_attempts,
        lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
    )


def test_book_opening_runtime_job_allows_only_one_attempt() -> None:
    assert _book_opening_spec().max_attempts == 1

    with pytest.raises(ValueError, match="exactly one RuntimeJob attempt"):
        _book_opening_spec(max_attempts=2)
