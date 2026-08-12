from __future__ import annotations

import unittest

from psycopg.errors import ForeignKeyViolation

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
        self.runtime_group = "book"
        self.project_id = identifier("project")
        self.authority = RuntimeJobAuthority(DATABASE_URL)

    def spec(self, *, dedupe_key: str, subject_id: str = "subject:1") -> RuntimeJobSpec:
        return RuntimeJobSpec(
            job_kind="BOOK_COORDINATION_TICK",
            runtime_group=self.runtime_group,
            subject_kind="BOOK_RUN",
            subject_id=subject_id,
            project_id=self.project_id,
            dedupe_key=dedupe_key,
            input_snapshot={"observed_version": 3, "state": "CHAPTER_COMPLETED"},
            max_attempts=2,
        )

    def claim(self, *, subject_id: str, worker_id: str):
        return self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id=worker_id,
            lease_seconds=30,
            project_id=self.project_id,
            subject_kind="BOOK_RUN",
            subject_id=subject_id,
        )

    def test_schedule_claim_checkpoint_and_complete_are_auditable(self) -> None:
        spec = self.spec(dedupe_key="book:1:version:3")
        scheduled = self.authority.schedule(spec)
        replay = self.authority.schedule(spec)
        self.assertEqual(replay["runtime_job_id"], scheduled["runtime_job_id"])
        self.assertTrue(replay["deduplicated"])

        claim = self.claim(subject_id="subject:1", worker_id="book-worker-a")
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

    def test_same_logical_job_is_isolated_between_projects(self) -> None:
        first_spec = self.spec(
            dedupe_key="book:shared:version:3", subject_id="subject:shared"
        )
        first = self.authority.schedule(first_spec)
        first_claim = self.claim(
            subject_id="subject:shared", worker_id="book-worker-project-a"
        )
        assert first_claim is not None
        self.authority.start(first_claim)
        self.authority.complete(first_claim, {"project": "a"})

        second_project_id = identifier("project")
        second_spec = RuntimeJobSpec(
            job_kind=first_spec.job_kind,
            runtime_group=first_spec.runtime_group,
            subject_kind=first_spec.subject_kind,
            subject_id=first_spec.subject_id,
            project_id=second_project_id,
            dedupe_key=first_spec.dedupe_key,
            input_snapshot=first_spec.input_snapshot,
            max_attempts=first_spec.max_attempts,
        )
        second = self.authority.schedule(second_spec)

        self.assertTrue(second["created"])
        self.assertNotEqual(first["runtime_job_id"], second["runtime_job_id"])
        second_claim = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-project-b",
            lease_seconds=30,
            project_id=second_project_id,
            subject_kind="BOOK_RUN",
            subject_id="subject:shared",
        )
        assert second_claim is not None
        self.assertEqual(second_claim.project_id, second_project_id)

    def test_expired_lease_takeover_increments_fence_and_rejects_stale_worker(self) -> None:
        scheduled = self.authority.schedule(
            self.spec(dedupe_key="book:2:version:3", subject_id="subject:2")
        )
        stale = self.claim(
            subject_id="subject:2", worker_id="book-worker-stale"
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

        replacement = self.claim(
            subject_id="subject:2", worker_id="book-worker-replacement"
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
        first = self.claim(subject_id="subject:3", worker_id="book-worker-a")
        assert first is not None
        self.authority.start(first)
        failed = self.authority.fail(first, {"code": "TRANSIENT"})
        self.assertEqual(failed["status"], "RETRY_WAIT")
        second = self.claim(subject_id="subject:3", worker_id="book-worker-b")
        assert second is not None
        self.authority.start(second)
        dead = self.authority.fail(second, {"code": "REPEATED"})
        self.assertEqual(dead["status"], "DEAD_LETTER")

    def test_final_attempt_lease_expiry_dead_letters_instead_of_stranding(self) -> None:
        scheduled = self.authority.schedule(
            self.spec(dedupe_key="book:final-expiry", subject_id="subject:final-expiry")
        )
        first = self.claim(
            subject_id="subject:final-expiry", worker_id="book-worker-a"
        )
        assert first is not None
        self.authority.start(first)
        self.authority.fail(first, {"code": "TRANSIENT"})
        final = self.claim(
            subject_id="subject:final-expiry", worker_id="book-worker-b"
        )
        assert final is not None
        self.authority.start(final)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET lease_expires_at=NOW() - INTERVAL '1 second'
                WHERE lease_id=%s
                """,
                [final.lease_id],
            )
            uow.commit()

        self.assertIsNone(
            self.claim(
                subject_id="subject:final-expiry",
                worker_id="book-worker-recovery",
            )
        )
        job = self.authority.get(scheduled["runtime_job_id"])
        self.assertEqual(job["status"], "DEAD_LETTER")
        self.assertEqual(job["last_error"]["code"], "FINAL_ATTEMPT_LEASE_EXPIRED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT attempt.status, lease.status,
                       COUNT(*) FILTER (
                           WHERE event.event_type='runtime_job.dead_lettered'
                       )
                FROM authority_runtime_job_attempt AS attempt
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                LEFT JOIN authority_runtime_job_event AS event
                  ON event.attempt_id=attempt.attempt_id
                WHERE attempt.attempt_id=%s
                GROUP BY attempt.status, lease.status
                """,
                [final.attempt_id],
            )
            attempt_status, lease_status, dead_letter_events = uow.cursor.fetchone()
        self.assertEqual((attempt_status, lease_status), ("ABANDONED", "EXPIRED"))
        self.assertEqual(int(dead_letter_events), 1)

    def test_database_clock_rejects_expired_heartbeat(self) -> None:
        self.authority.schedule(
            self.spec(dedupe_key="book:expired-heartbeat", subject_id="subject:heartbeat")
        )
        claim = self.claim(
            subject_id="subject:heartbeat", worker_id="book-worker-clock"
        )
        assert claim is not None
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_runtime_job_lease
                SET lease_expires_at=NOW() - INTERVAL '1 second'
                WHERE lease_id=%s
                """,
                [claim.lease_id],
            )
            uow.commit()
        with self.assertRaisesRegex(KernelError, "stale"):
            self.authority.heartbeat(claim, lease_seconds=30)

    def test_database_rejects_cross_job_execution_identity(self) -> None:
        first_job = self.authority.schedule(
            self.spec(dedupe_key="book:identity-a", subject_id="subject:identity-a")
        )
        first_claim = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-identity-a",
            lease_seconds=30,
            project_id=self.project_id,
            subject_kind="BOOK_RUN",
            subject_id="subject:identity-a",
        )
        assert first_claim is not None
        second_job = self.authority.schedule(
            self.spec(dedupe_key="book:identity-b", subject_id="subject:identity-b")
        )
        second_claim = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-identity-b",
            lease_seconds=30,
            project_id=self.project_id,
            subject_kind="BOOK_RUN",
            subject_id="subject:identity-b",
        )
        assert second_claim is not None

        with self.assertRaises(ForeignKeyViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job
                    SET current_attempt_id=%s, current_fencing_token=%s
                    WHERE runtime_job_id=%s
                    """,
                    [
                        second_claim.attempt_id,
                        second_claim.fencing_token,
                        first_job["runtime_job_id"],
                    ],
                )
                uow.commit()
        self.assertNotEqual(first_job["runtime_job_id"], second_job["runtime_job_id"])

    def test_database_rejects_attempt_lease_worker_identity_mismatch(self) -> None:
        self.authority.schedule(
            self.spec(
                dedupe_key="book:lease-identity",
                subject_id="subject:lease-identity",
            )
        )
        claim = self.authority.claim(
            runtime_group=self.runtime_group,
            worker_id="book-worker-authoritative",
            lease_seconds=30,
            project_id=self.project_id,
        )
        assert claim is not None
        with self.assertRaises(ForeignKeyViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job_lease
                    SET worker_id='book-worker-forged'
                    WHERE lease_id=%s
                    """,
                    [claim.lease_id],
                )
                uow.commit()

        with self.assertRaises(ForeignKeyViolation):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "DELETE FROM authority_runtime_job_lease WHERE lease_id=%s",
                    [claim.lease_id],
                )
                uow.commit()


if __name__ == "__main__":
    unittest.main()
