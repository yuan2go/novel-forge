from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import build_chapter_authority_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
    BookFollowupCommand,
)
from novel_forge.modules.book_followup_authority.contracts import (
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.modules.book_followup_authority.query import (
    BookFollowupProjectionQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class BookFollowupAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("book-followup-project")
        self.temp = tempfile.TemporaryDirectory()
        settings = IndustrialSettings(
            root=Path(self.temp.name),
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_COMMIT_SHA": "f" * 40,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                Path(self.temp.name) / "objects"
            ),
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "book-followup-pep",
        }
        chapter = build_chapter_authority_application(settings, env=env)
        self.assertTrue(
            chapter.model_port.adapter.production_execution_gateway_backed
        )
        self.app = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-followup-integration",
            commit_sha="f" * 40,
            model_port=chapter.model_port,
            worker_id="book-followup-worker",
        )
        self.principal = Principal(
            principal_id="book-followup-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.followup:*",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def seed(self, asset_type: str, content: dict, label: str) -> dict[str, str]:
        version_id = f"{self.project_id}:{label}:v1"
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [f"{version_id}:asset", self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                """,
                [
                    version_id,
                    f"{version_id}:asset",
                    json.dumps(content),
                    content_hash,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'book-followup-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return {"asset_version_id": version_id, "content_hash": content_hash}

    def test_reader_outcome_uses_pep_external_effect_and_replays_once(self) -> None:
        draft = self.seed(
            "draft_version",
            {
                "contract_version": "draft-version-v1",
                "text": "A public choice exacts an irreversible cost.",
            },
            "draft",
        )
        canon = self.seed(
            "canon_snapshot",
            {"contract_version": "canon-snapshot-v1", "facts": []},
            "canon",
        )
        command = BookFollowupCommand(
            definition_name=READER_OUTCOME_DEFINITION,
            project_id=self.project_id,
            workspace_id=f"workspace:{self.project_id}",
            actor_id=self.principal.principal_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            idempotency_key=f"{self.project_id}:reader-outcome:chapter:1",
            payload=self.reader_payload(draft, canon),
            input_assets=(draft, canon),
        )

        admission = self.app.admit(command, principal=self.principal)
        result = self.app.run_or_recover(admission)
        replay = self.app.admit(command, principal=self.principal)
        replay_result = self.app.run_or_recover(replay)

        self.assertFalse(admission.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(result.output.asset_version_id, replay_result.output.asset_version_id)
        self.assertEqual(
            {item.asset_type for item in result.output.materialized_outputs},
            {"reader_outcome_report", "reader_state_transition", "reader_issue_set"},
        )
        projection = BookFollowupProjectionQuery(DATABASE_URL)
        # The standalone operation is projected through its output binding. Book
        # linkage is tested separately by the Book Authority slice.
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), MIN(capability), MIN(status)
                FROM authority_external_effect
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            effect = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_attempt
                WHERE operation_id=%s
                """,
                [admission.operation_id],
            )
            attempts = int(uow.cursor.fetchone()[0])
        self.assertEqual(effect, (1, "model.reader_outcome", "SUCCEEDED"))
        self.assertEqual(attempts, 1)
        self.assertTrue(projection)  # query type is production-wired; link view is Book-owned

    def test_longform_recap_materializes_deviation_and_authority_proposals(self) -> None:
        reader = self.seed(
            "reader_state",
            {"contract_version": "reader-state-v1", "confusion": 0.8},
            "reader-state",
        )
        canon = self.seed(
            "canon_snapshot",
            {"contract_version": "canon-snapshot-v1", "conflicts": []},
            "canon-recap",
        )
        payload = {
            "book_id": "book:1",
            "checkpoint_type": "ARC_CHECKPOINT",
            "chapter_range": [1, 10],
            "book_design_version": "book-design:v1",
            "book_plan_version": "book-plan:v1",
            "volume_plan_version": "volume-plan:v1",
            "arc_plan_version": "arc-plan:v1",
            "canon_snapshot_version": canon["asset_version_id"],
            "character_state_version": "character-state:v1",
            "foreshadowing_state_version": "foreshadow:v1",
            "reader_state_version": reader["asset_version_id"],
            "quality_trend_version": "quality-trend:v1",
            "reward_ledger_version": "reward-ledger:v1",
            "promise_ledger_version": "promise-ledger:v1",
            "observations": {
                "reader_state": {"confusion": 0.8},
                "canon": {"conflicts": [{"id": "c1"}]},
                "quality_trend": {"direction": "DECLINING"},
            },
        }
        admission = self.app.admit(
            BookFollowupCommand(
                definition_name=LONGFORM_RECAP_DEFINITION,
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                actor_id=self.principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                idempotency_key=f"{self.project_id}:longform:arc:1",
                payload=payload,
                input_assets=(reader, canon),
            ),
            principal=self.principal,
        )
        result = self.app.run_or_recover(admission)

        self.assertEqual(
            {item.asset_type for item in result.output.materialized_outputs},
            {
                "longform_recap",
                "longform_deviation_report",
                "plan_adjustment_proposal",
                "replan_request",
            },
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s
                  AND binding.output_key='longform.recap.adjustment_proposal'
                """,
                [admission.operation_id],
            )
            proposal = dict(uow.cursor.fetchone()[0])
        self.assertFalse(proposal["mutates_plan"])
        self.assertEqual(proposal["decision_status"], "AUTHORITY_PENDING")

    @staticmethod
    def reader_payload(
        draft: dict[str, str], canon: dict[str, str]
    ) -> dict[str, object]:
        return {
            "book_id": "book:1",
            "chapter_id": "chapter:1",
            "chapter_number": 1,
            "final_draft_asset_version": draft["asset_version_id"],
            "chapter_plan_asset_version": "chapter-plan:v1",
            "book_design_version": "book-design:v1",
            "book_plan_version": "book-plan:v1",
            "parent_plan_versions": {
                "volume_plan_version": "volume-plan:v1",
                "arc_plan_version": "arc-plan:v1",
            },
            "reader_segment_version": "reader-segment:v1",
            "reader_contract_version": "reader-contract:v1",
            "platform_profile_version": "platform-profile:v1",
            "canon_snapshot_version": canon["asset_version_id"],
            "chapter_outcome_version": "chapter-outcome:v1",
            "story_state_version": "story-state:v1",
            "quality_evidence_version": "quality:v1",
            "input_manifest_ref": "input-manifest:v1",
            "previous_reader_state_version": "reader-state:none",
            "evaluation_profile_version": "reader-evaluation:v1",
            "model_strategy_version": "model-strategy:v1",
        }


if __name__ == "__main__":
    unittest.main()
