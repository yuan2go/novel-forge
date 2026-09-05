from __future__ import annotations

import unittest

from novel_forge.schemas.narrative_qualification import EvidenceDimension
from novel_forge.tools.narrative_qualification import (
    CAPABILITIES,
    build_narrative_report,
    collect_accepted_snapshot,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as book_fixture,
)


class NarrativeQualificationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_scripted_accepted_chapter_collects_replayable_read_only_blind_evidence(
        self,
    ) -> None:
        fixture_case = book_fixture.BookToChapterAuthorityVerticalPostgresTests(
            "test_book_cursor_advances_once"
        )
        self.addCleanup(fixture_case.doCleanups)
        fixture = fixture_case._new_book_fixture(target_chapter_count=1)
        authority = fixture["authority"]
        delegated = authority.submit_chapter(
            fixture_case._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        fixture_case._run_child(fixture, delegated["chapter_root_operation_id"])
        authority.reconcile_chapter(delegated["chapter_request_id"])
        authority.accept_chapter(
            delegated["chapter_request_id"], principal=fixture["principal"]
        )
        before = authority.require(fixture["book"].book_run_id)

        first = collect_accepted_snapshot(
            DATABASE_URL, book_run_id=fixture["book"].book_run_id
        )
        replay = collect_accepted_snapshot(
            DATABASE_URL, book_run_id=fixture["book"].book_run_id
        )
        self.assertEqual(first, replay)
        self.assertEqual(before, authority.require(fixture["book"].book_run_id))
        self.assertEqual(len(first["accepted"]), 1)
        self.assertTrue(first["effects"])
        self.assertTrue(first["observations"])
        report, blind, private = build_narrative_report(
            first,
            implementation={
                "commit_sha": "f" * 40,
                "implementation_tree_sha": "sha256:" + "e" * 64,
            },
            capabilities=CAPABILITIES,
            engineering=EvidenceDimension(
                "NOT_PROVEN", "NO_CURRENT_P0", (), ("fixture execution only",)
            ),
        )
        self.assertTrue(report.source["fixture_backed"])
        self.assertEqual(report.real_chapter_production["status"], "NOT_PROVEN")
        self.assertEqual(
            report.dimensions["human_editorial"].status, "WAITING_EVIDENCE"
        )
        self.assertEqual(
            report.dimensions["longitudinal_stability"].status,
            "EVIDENCE_NOT_YET_SUFFICIENT",
        )
        self.assertEqual(len(blind.samples), 1)
        self.assertEqual(
            private["samples"][0]["acceptance_id"],
            first["accepted"][0]["acceptance_id"],
        )
        self.assertTrue(
            all(
                item["model_call_log_ids"] and item["cost_ledger_ids"]
                for item in report.accepted_chapters[0]["provider_effects"]
            )
        )
        with self.assertRaisesRegex(ValueError, "does not exist"):
            collect_accepted_snapshot(DATABASE_URL, book_run_id="book-run:absent")
