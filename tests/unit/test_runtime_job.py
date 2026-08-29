from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from novel_forge.modules.runtime_job import (
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
    canonical_payload_hash,
    deterministic_runtime_job_id,
)


class _ClaimCursor:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, _parameters: list[str]) -> None:
        self.sql = sql

    @staticmethod
    def fetchone() -> tuple[object, ...]:
        return (
            "RUNNING",
            "attempt:1",
            1,
            1,
            1,
            "worker:1",
            "RUNNING",
            "lease:1",
            1,
            "lease:1",
            "worker:1",
            "HELD",
            1,
            datetime.now(UTC) + timedelta(seconds=30),
            "BOOK_OPENING_EXECUTE",
            "AUTHORITY_CONVERGENCE_REQUIRED",
        )


class RuntimeJobContractTests(unittest.TestCase):
    def test_final_claim_assertion_uses_wall_clock_after_lock_wait(self) -> None:
        cursor = _ClaimCursor()
        authority = RuntimeJobAuthority("postgresql://authority")
        claim = RuntimeJobClaim(
            runtime_job_id="runtime-job:1",
            job_kind="BOOK_OPENING_EXECUTE",
            runtime_group="book_opening",
            subject_kind="BOOK_OPENING_RUN",
            subject_id="opening:1",
            project_id="project:1",
            attempt_id="attempt:1",
            attempt_number=1,
            worker_id="worker:1",
            lease_id="lease:1",
            fencing_token=1,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            input_snapshot={"opening_run_id": "opening:1"},
        )

        authority._lock_and_assert_claim(SimpleNamespace(cursor=cursor), claim)

        self.assertIn("lease.lease_expires_at > clock_timestamp()", cursor.sql)
        self.assertNotIn("lease.lease_expires_at > transaction_timestamp()", cursor.sql)

    def test_job_identity_and_payload_hash_are_deterministic(self) -> None:
        first = deterministic_runtime_job_id(
            project_id="project:7",
            runtime_group="book",
            job_kind="BOOK_COORDINATION_TICK",
            dedupe_key="book-run:7:version:3",
        )
        second = deterministic_runtime_job_id(
            project_id="project:7",
            runtime_group="book",
            job_kind="BOOK_COORDINATION_TICK",
            dedupe_key="book-run:7:version:3",
        )
        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            deterministic_runtime_job_id(
                project_id="project:8",
                runtime_group="book",
                job_kind="BOOK_COORDINATION_TICK",
                dedupe_key="book-run:7:version:3",
            ),
        )
        self.assertTrue(first.startswith("runtime-job:"))
        self.assertEqual(
            canonical_payload_hash({"b": 2, "a": 1}),
            canonical_payload_hash({"a": 1, "b": 2}),
        )

    def test_spec_requires_bounded_execution_identity(self) -> None:
        spec = RuntimeJobSpec(
            job_kind="BOOK_COORDINATION_TICK",
            runtime_group="book",
            subject_kind="BOOK_RUN",
            subject_id="book-run:7",
            project_id="project:7",
            dedupe_key="book-run:7:version:3",
            input_snapshot={"state": "CHAPTER_COMPLETED", "version": 3},
            max_attempts=4,
        )
        self.assertEqual(spec.max_attempts, 4)
        with self.assertRaisesRegex(ValueError, "required"):
            RuntimeJobSpec(
                job_kind="",
                runtime_group="book",
                subject_kind="BOOK_RUN",
                subject_id="book-run:7",
                project_id="project:7",
                dedupe_key="version:3",
                input_snapshot={},
            )
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            RuntimeJobSpec(
                job_kind="BOOK_COORDINATION_TICK",
                runtime_group="book",
                subject_kind="BOOK_RUN",
                subject_id="book-run:7",
                project_id="project:7",
                dedupe_key="version:3",
                input_snapshot={},
                max_attempts=0,
            )
        with self.assertRaisesRegex(ValueError, "operational scheduling envelopes"):
            RuntimeJobSpec(
                job_kind="DRAFT_CHAPTER",
                runtime_group="execution",
                subject_kind="CHAPTER",
                subject_id="chapter:7",
                project_id="project:7",
                dedupe_key="draft:7",
                input_snapshot={},
            )


if __name__ == "__main__":
    unittest.main()
