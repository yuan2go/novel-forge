from __future__ import annotations

import json
import unittest
from typing import Any

from tests.integration.authority_postgres_support import connect, ensure_migrated


class AuthorityQueryPlansPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_bounded_worker_and_migration_queries_have_expected_indexes(self) -> None:
        probes = {
            "operation": (
                "authority_operation_worker_poll_idx",
                """
                SELECT operation_id, project_id
                FROM authority_operation
                WHERE definition_name = ANY(ARRAY['content.draft.generate'])
                  AND status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
                ORDER BY created_at, operation_id
                LIMIT 10
                """,
            ),
            "book": (
                "authority_book_production_worker_poll_idx",
                """
                SELECT book_run_id, project_id
                FROM authority_book_production
                WHERE state = ANY(ARRAY[
                    'CHAPTER_SUBMITTED', 'CHAPTER_RUNNING',
                    'CHAPTER_WAITING_RETRY', 'CHAPTER_COMPLETED',
                    'READER_OUTCOME_PENDING', 'CHECKPOINT_PENDING'
                ])
                ORDER BY updated_at, book_run_id
                LIMIT 10
                """,
            ),
            "external_effect": (
                "authority_external_effect_ready_poll_idx",
                """
                SELECT external_effect_id
                FROM authority_external_effect
                WHERE status IN (
                    'READY', 'FAILED_RETRYABLE', 'RECONCILIATION_REQUIRED'
                )
                ORDER BY created_at, external_effect_id
                LIMIT 10
                """,
            ),
            "outbox": (
                "authority_outbox_worker_claim_idx",
                """
                SELECT outbox_id
                FROM outbox_event
                WHERE LOWER(status) IN ('pending', 'queued', 'failed')
                  AND available_at <= NOW()
                  AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                ORDER BY available_at, created_at, outbox_id
                LIMIT 10
                """,
            ),
            "migration_resume": (
                "authority_legacy_migration_item_phase_resume_idx",
                """
                SELECT migration_item_id
                FROM authority_legacy_migration_item
                WHERE migration_run_id='query-plan-probe'
                  AND phase='VALIDATE'
                  AND status='PENDING'
                ORDER BY updated_at, migration_item_id
                LIMIT 10
                """,
            ),
        }
        with connect() as connection:
            connection.execute("SET enable_seqscan=off")
            for name, (expected_index, query) in probes.items():
                with self.subTest(name=name):
                    plan = connection.execute(
                        f"EXPLAIN (FORMAT JSON, COSTS FALSE) {query}"
                    ).fetchone()[0]
                    indexes = _index_names(plan)
                    self.assertIn(
                        expected_index,
                        indexes,
                        json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    )


def _index_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        names = {
            str(value["Index Name"])
            for key in ("Index Name",)
            if key in value
        }
        for nested in value.values():
            names.update(_index_names(nested))
        return names
    if isinstance(value, list):
        names: set[str] = set()
        for nested in value:
            names.update(_index_names(nested))
        return names
    return set()


if __name__ == "__main__":
    unittest.main()
