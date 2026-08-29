from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from novel_forge.modules.runtime_job import RuntimeJobClaim
from tests.integration.authority_postgres_support import ensure_migrated
from tests.integration.book_opening_workflow_postgres_support import (
    as_mapping,
    build_workflow_fixture,
    claim_node_kind,
)


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


def test_two_workers_can_create_only_one_attempt_for_the_same_node() -> None:
    fixture = build_workflow_fixture()
    admission = fixture.admit()
    barrier = Barrier(2)

    def claim(worker_id: str) -> RuntimeJobClaim | None:
        barrier.wait(timeout=10)
        return fixture.claim(worker_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim, "book-opening-double-claim:a")
        second = executor.submit(claim, "book-opening-double-claim:b")
        outcomes = (first.result(timeout=20), second.result(timeout=20))

    claims = [item for item in outcomes if item is not None]
    assert len(claims) == 1
    winner = claims[0]
    assert claim_node_kind(winner) == "BOOK_PLAN"
    job = fixture.runtime_jobs.get(winner.runtime_job_id)
    assert job["attempt_count"] == 1
    assert job["current_attempt_id"] == winner.attempt_id
    assert job["current_fencing_token"] == winner.fencing_token

    progress = fixture.progress(admission.opening_run_id)
    assert as_mapping(progress["current_layer"])["node_kind"] == "BOOK_PLAN"
    assert as_mapping(progress["current_layer"])["lifecycle"] == "RUNNING"
