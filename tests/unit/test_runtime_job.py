from __future__ import annotations

import unittest

from novel_forge.modules.runtime_job import (
    RuntimeJobSpec,
    canonical_payload_hash,
    deterministic_runtime_job_id,
)


class RuntimeJobContractTests(unittest.TestCase):
    def test_job_identity_and_payload_hash_are_deterministic(self) -> None:
        first = deterministic_runtime_job_id(
            runtime_group="book",
            job_kind="BOOK_COORDINATION_TICK",
            dedupe_key="book-run:7:version:3",
        )
        second = deterministic_runtime_job_id(
            runtime_group="book",
            job_kind="BOOK_COORDINATION_TICK",
            dedupe_key="book-run:7:version:3",
        )
        self.assertEqual(first, second)
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


if __name__ == "__main__":
    unittest.main()
