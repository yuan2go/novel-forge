from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_outcome import (
    ChapterOutcomeAuthorityApplication,
    ChapterOutcomeCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class ChapterOutcomeStoryStatePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_story_state_reducer_recovery_after_partial_failure(self) -> None:
        project_id = identifier("story-state-reducer")
        inputs = self._seed_inputs(project_id)
        failure = {"enabled": True}

        def inject(point: str) -> None:
            if failure["enabled"] and point == "mid_reducer":
                raise RuntimeError("injected reducer worker crash")

        application = ChapterOutcomeAuthorityApplication(
            DATABASE_URL,
            application_build_id="story-state-reducer-test",
            commit_sha="f" * 40,
            failure_injector=inject,
        )
        principal = Principal(
            principal_id="story-state-worker",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        admission = application.admit(
            ChapterOutcomeCommand(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id=principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                idempotency_key=f"{project_id}:chapter:1:accept",
                payload={
                    "book_id": f"book:{project_id}",
                    "chapter_number": 1,
                    "parent_group_version_id": "group:v1",
                    "cost_receipt_refs": [],
                },
                input_assets=tuple(inputs),
            ),
            principal=principal,
        )

        with self.assertRaisesRegex(RuntimeError, "reducer worker crash"):
            application.run_or_recover(admission)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_story_state_reducer_application
                WHERE project_id=%s
                """,
                [project_id],
            )
            partial_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT status FROM authority_operation
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            operation_status = str(uow.cursor.fetchone()[0])
        self.assertEqual(partial_count, 7)
        self.assertEqual(operation_status, "SUCCEEDED")

        failure["enabled"] = False
        application.run_or_recover(admission)
        application.run_or_recover(admission)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT reducer_key),
                       COUNT(DISTINCT story_state_asset_version_id)
                FROM authority_story_state_reducer_application
                WHERE project_id=%s
                """,
                [project_id],
            )
            counts = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation_output_asset
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            output_count = int(uow.cursor.fetchone()[0])
        self.assertEqual(counts, (14, 14, 1))
        self.assertEqual(output_count, 2)

    @staticmethod
    def _seed_inputs(project_id: str) -> list[dict[str, str]]:
        payloads = {
            "chapter_plan": {"project_id": project_id, "chapter": 1},
            "draft_version": {"project_id": project_id, "chapter": 1},
            "re_review_report": {
                "decision": "PASSED",
                "blocking_issue_count": 0,
            },
            "canon_patch": {
                "gate": "PASSED",
                "conflicts": [],
                "snapshot_candidates": [
                    {
                        "state_kind": "timeline_snapshot",
                        "changes": [{"event_id": "event-1"}],
                    },
                    {
                        "state_kind": "reader_promise",
                        "changes": [
                            {"promise_id": "promise-1", "status": "OPEN"}
                        ],
                    },
                ],
            },
            "quality_score_report": {"gate": "PASSED"},
            "release_package": {
                "release_status": "READY_FOR_BLOB_VERIFICATION"
            },
            "final_release_gate_report": {
                "gate": "PASSED",
                "release_status": "INTERNAL_RELEASE_FINALIZED",
                "blob_receipt": {"receipt_id": "blob-receipt-1"},
            },
        }
        references: list[dict[str, str]] = []
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for index, (asset_type, content) in enumerate(
                payloads.items(), start=1
            ):
                asset_id = f"{project_id}:{asset_type}"
                version_id = f"{asset_id}:v1"
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(
                        content, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset(asset_id, project_id, asset_type)
                    VALUES (%s, %s, %s)
                    """,
                    [asset_id, project_id, asset_type],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number,
                        lifecycle, eligibility, governance, content,
                        content_hash
                    ) VALUES (
                        %s, %s, %s, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s
                    )
                    """,
                    [
                        version_id,
                        asset_id,
                        index,
                        json.dumps(content),
                        content_hash,
                    ],
                )
                references.append(
                    {
                        "asset_version_id": version_id,
                        "content_hash": content_hash,
                    }
                )
            uow.commit()
        return references


if __name__ == "__main__":
    unittest.main()
