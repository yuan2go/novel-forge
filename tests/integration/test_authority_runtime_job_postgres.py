from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class AuthorityRuntimeJobPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.runtime_group = identifier("runtime-group")
        self.authority = RuntimeJobAuthority(DATABASE_URL)

    def spec(self, *, dedupe_key: str, subject_id: str = "subject:1") -> RuntimeJobSpec:
        return RuntimeJobSpec(
            job_kind="BOOK_COORDINATION_TICK",
            runtime_group=self.runtime_group,
            subject_kind="BOOK_RUN",
            subject_id=subject_id,
            project_id=identifier("project"),
            dedupe_key=dedupe_key,
            input_snapshot={"observed_version": 3, "state": "CHAPTER_COMPLETED"},
            max_attempts=2,
        )

    def test_schedule_claim_checkpoint_and_complete_are_auditable(self) -> None:
        spec = self.spec(dedupe_key="book:1:version:3")
        scheduled = self.authority.schedule(spec)
        replay = self.authority.schedule(spec)
        self.assertEqual(replay["runtime_job_id"], scheduled["runtime_job_id"])
        self.assertTrue(replay["deduplicated"])

        claim = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-a",
            lease_seconds=30,
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.authority.start(claim)
        checkpoint = self.authority.checkpoint(
            claim,
            {"step": "CHAPTER_ACCEPTED", "book_run_id": "subject:1"},
        )
        self.assertEqual(checkpoint["checkpoint_sequence"], 1)
        completed = self.authority.complete(
            claim,
            {"action": "ACCEPT_CHAPTER", "state": "READY"},
        )
        self.assertEqual(completed["status"], "SUCCEEDED")

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT job.status, attempt.status, lease.status,
                       checkpoint.checkpoint_sequence,
                       result.result_hash,
                       (SELECT COUNT(*) FROM authority_runtime_job_event
                        WHERE runtime_job_id=job.runtime_job_id)
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                JOIN authority_runtime_job_checkpoint AS checkpoint
                  ON checkpoint.attempt_id=attempt.attempt_id
                JOIN authority_runtime_job_result AS result
                  ON result.attempt_id=attempt.attempt_id
                WHERE job.runtime_job_id=%s
                """,
                [scheduled["runtime_job_id"]],
            )
            evidence = uow.cursor.fetchone()
        self.assertEqual(tuple(evidence[:4]), ("SUCCEEDED", "SUCCEEDED", "RELEASED", 1))
        self.assertTrue(str(evidence[4]).startswith("sha256:"))
        self.assertGreaterEqual(int(evidence[5]), 5)

    def test_expired_lease_takeover_increments_fence_and_rejects_stale_worker(self) -> None:
        scheduled = self.authority.schedule(
            self.spec(dedupe_key="book:2:version:3", subject_id="subject:2")
        )
        stale = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-stale",
            lease_seconds=30,
        )
        assert stale is not None
        self.authority.start(stale)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET lease_expires_at=NOW() - INTERVAL '1 second'
                WHERE lease_id=%s
                """,
                [stale.lease_id],
            )
            uow.commit()

        replacement = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-replacement",
            lease_seconds=30,
        )
        assert replacement is not None
        self.assertEqual(replacement.runtime_job_id, scheduled["runtime_job_id"])
        self.assertGreater(replacement.fencing_token, stale.fencing_token)
        self.assertNotEqual(replacement.attempt_id, stale.attempt_id)
        with self.assertRaisesRegex(KernelError, "stale"):
            self.authority.checkpoint(stale, {"invalid": "stale result"})
        self.authority.start(replacement)
        self.authority.complete(replacement, {"recovered": True})

    def test_retry_becomes_dead_letter_at_max_attempts(self) -> None:
        self.authority.schedule(
            self.spec(dedupe_key="book:3:version:3", subject_id="subject:3")
        )
        first = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-a",
            lease_seconds=30,
        )
        assert first is not None
        self.authority.start(first)
        failed = self.authority.fail(first, {"code": "TRANSIENT"})
        self.assertEqual(failed["status"], "RETRY_WAIT")
        second = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-b",
            lease_seconds=30,
        )
        assert second is not None
        self.authority.start(second)
        dead = self.authority.fail(second, {"code": "REPEATED"})
        self.assertEqual(dead["status"], "DEAD_LETTER")


if __name__ == "__main__":
    unittest.main()
