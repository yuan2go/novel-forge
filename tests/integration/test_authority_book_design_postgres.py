from __future__ import annotations

import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
)
from novel_forge.modules.story_design_authority import scripted_qualification
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class BookDesignAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("book-design-project")
        self.workspace_id = identifier("book-design-workspace")
        self.book_id = identifier("book")
        self.principal = Principal(
            principal_id="book-design-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "project.authority.execute",
                    "book_design.authority.execute",
                    "book_design.authority.query",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.project_application = ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-design-integration",
            commit_sha="b" * 40,
        )
        self.application = BookDesignAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-design-integration",
            commit_sha="b" * 40,
        )
        self.query = BookDesignAuthorityQuery(DATABASE_URL)
        self._create_project()

    def test_full_chain_replay_projection_and_supersession(self) -> None:
        created = self._book_command(
            "book.create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "The Glass Harbor",
                "production_profile": {
                    "environment": "production",
                    "platform": "fixture",
                },
                "runtime_policy": {"execution_fallback": "FAIL_CLOSED"},
                "release_identity": "book-design-integration@" + "b" * 40,
            },
            idempotency_key=f"book:create:{self.book_id}",
        )
        replay = self._book_command(
            "book.create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "The Glass Harbor",
                "production_profile": {
                    "environment": "production",
                    "platform": "fixture",
                },
                "runtime_policy": {"execution_fallback": "FAIL_CLOSED"},
                "release_identity": "book-design-integration@" + "b" * 40,
            },
            idempotency_key=f"book:create:{self.book_id}",
        )
        self.assertEqual(replay["operation_id"], created["operation_id"])
        self.assertTrue(replay["replayed"])

        book = self.query.require_book(project_id=self.project_id, book_id=self.book_id)
        first = self._book_command(
            "book_design.propose",
            payload=self._design("collective truth"),
            idempotency_key=f"design:propose:1:{self.book_id}",
            expected_book_version=book["version"],
            expected_design=book["active_book_design_version_id"],
        )
        decided = self._book_command(
            "book_design.decide",
            payload={
                "decision": "APPROVE",
                "reason": "typed contract and reader promise verified",
            },
            idempotency_key=f"design:approve:1:{self.book_id}",
            expected_book_version=book["version"],
            expected_design="",
            target_asset_version_id=first["asset_version_id"],
        )
        activated = self._book_command(
            "book_design.activate",
            payload={"reason": "first accepted design"},
            idempotency_key=f"design:activate:1:{self.book_id}",
            expected_book_version=book["version"],
            expected_design="",
            target_asset_version_id=first["asset_version_id"],
        )
        self.assertTrue(decided["decision_id"])
        self.assertTrue(activated["activation_id"])

        book = self.query.require_book(project_id=self.project_id, book_id=self.book_id)
        self.assertEqual(
            book["active_book_design_version_id"], first["asset_version_id"]
        )
        self.assertEqual(book["version"], 2)
        second = self._book_command(
            "book_design.propose",
            payload=self._design("accountable collective truth"),
            idempotency_key=f"design:propose:2:{self.book_id}",
            expected_book_version=book["version"],
            expected_design=first["asset_version_id"],
        )
        self._book_command(
            "book_design.decide",
            payload={
                "decision": "APPROVE",
                "reason": "revision closes the stated thematic gap",
            },
            idempotency_key=f"design:approve:2:{self.book_id}",
            expected_book_version=book["version"],
            expected_design=first["asset_version_id"],
            target_asset_version_id=second["asset_version_id"],
        )
        superseded = self._book_command(
            "book_design.activate",
            payload={"reason": "approved design supersession"},
            idempotency_key=f"design:activate:2:{self.book_id}",
            expected_book_version=book["version"],
            expected_design=first["asset_version_id"],
            target_asset_version_id=second["asset_version_id"],
        )

        self.assertEqual(
            superseded["previous_asset_version_id"], first["asset_version_id"]
        )
        versions = self.query.list_design_versions(
            project_id=self.project_id, book_id=self.book_id
        )
        self.assertEqual([item["version_number"] for item in versions], [1, 2])
        self.assertEqual(versions[0]["status"], "SUPERSEDED")
        self.assertEqual(versions[0]["lifecycle"], "SUPERSEDED")
        self.assertEqual(versions[1]["status"], "ACTIVE")
        self.assertEqual(versions[1]["lifecycle"], "ACTIVE")
        self.assertEqual(
            versions[1]["payload_schema_version"], BOOK_DESIGN_SCHEMA_VERSION
        )
        self.assertEqual(
            versions[1]["book_dependency_version_id"], created["asset_version_id"]
        )

        outbox = self.query.outbox_projection(
            project_id=self.project_id, book_id=self.book_id
        )
        topics = {item["topic"] for item in outbox}
        self.assertEqual(
            topics,
            {
                "authority.book.create.committed",
                "authority.book_design.propose.committed",
                "authority.book_design.decide.committed",
                "authority.book_design.activate.committed",
            },
        )
        self.assertTrue(all(item["delivery_status"] == "PENDING" for item in outbox))

    def test_invalid_candidate_and_stale_book_version_roll_back_business_writes(
        self,
    ) -> None:
        self._book_command(
            "book.create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "Rollback Book",
                "production_profile": {},
                "runtime_policy": {"legacy_write": False, "silent_fallback": False},
                "release_identity": "book-design-integration@" + "b" * 40,
            },
            idempotency_key=f"book:create:{self.book_id}",
        )
        with self.assertRaisesRegex(KernelError, "BOOK_DESIGN_INVALID"):
            self._book_command(
                "book_design.propose",
                payload={
                    "schema_version": BOOK_DESIGN_SCHEMA_VERSION,
                    "title": "arbitrary JSON",
                },
                idempotency_key=f"design:invalid:{self.book_id}",
                expected_book_version=1,
            )
        with self.assertRaisesRegex(KernelError, "BOOK_VERSION_CONFLICT"):
            self._book_command(
                "book_design.propose",
                payload=self._design("stale"),
                idempotency_key=f"design:stale:{self.book_id}",
                expected_book_version=99,
            )

        self.assertEqual(
            self.query.list_design_versions(
                project_id=self.project_id, book_id=self.book_id
            ),
            [],
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_book_design_candidate WHERE book_id = %s",
                [self.book_id],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 0)

    def test_semantically_failed_design_is_persisted_as_rejected_lineage(self) -> None:
        self._book_command(
            "book.create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "Rejected Design Book",
                "production_profile": {},
                "runtime_policy": {"legacy_write": False, "silent_fallback": False},
                "release_identity": "book-design-integration@" + "b" * 40,
            },
            idempotency_key=f"book:create:{self.book_id}",
        )
        design = self._design("unqualified premise")
        criterion = design["narrative_qualification"]["evaluations"][0][
            "criteria"
        ][0]
        criterion.update(
            verdict="FAIL",
            repair_directive="rebuild the premise around one reachable ending",
        )

        rejected = self._book_command(
            "book_design.propose",
            payload=design,
            idempotency_key=f"design:rejected:{self.book_id}",
            expected_book_version=1,
        )

        self.assertEqual(rejected["status"], "REJECTED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.status, version.eligibility,
                       qualification.qualification_status
                FROM authority_book_design_candidate AS candidate
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=candidate.asset_version_id
                JOIN authority_narrative_design_qualification AS qualification
                  ON qualification.asset_version_id=candidate.asset_version_id
                 AND qualification.design_layer='STORY_INTENT'
                WHERE candidate.asset_version_id=%s
                """,
                [rejected["asset_version_id"]],
            )
            self.assertEqual(
                uow.cursor.fetchone(),
                ("REJECTED", "INELIGIBLE", "FAIL"),
            )

    def test_crash_after_business_commit_cannot_leave_partial_command(self) -> None:
        def fail_before_completion(checkpoint: str) -> None:
            if checkpoint == "before_operation_completion":
                raise RuntimeError("fault: before operation completion")

        application = BookDesignAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-design-integration",
            commit_sha="b" * 40,
            fault_injector=fail_before_completion,
        )
        command = BookDesignAuthorityCommand(
            definition_name="book.create",
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
            actor_id=self.principal.principal_id,
            service_identity="authority-api",
            idempotency_key=f"book:crash:{self.book_id}",
            trace_id=f"trace:{self.project_id}",
            correlation_id=f"correlation:{self.project_id}",
            payload={
                "schema_version": "book-authority.v1",
                "title": "Crash Window",
                "production_profile": {},
                "runtime_policy": {"legacy_write": False, "silent_fallback": False},
                "release_identity": "book-design-integration@" + "b" * 40,
            },
        )
        with self.assertRaisesRegex(RuntimeError, "before operation completion"):
            application.execute(command, principal=self.principal)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_book WHERE book_id = %s",
                [self.book_id],
            )
            book_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE idempotency_scope = 'book:design' AND idempotency_key = %s",
                [command.idempotency_key],
            )
            operation_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_attempt WHERE operation_id IN (SELECT operation_id FROM authority_operation WHERE idempotency_key = %s)",
                [command.idempotency_key],
            )
            attempt_count = int(uow.cursor.fetchone()[0])
        self.assertEqual((book_count, operation_count, attempt_count), (0, 0, 0))

    def _create_project(self) -> None:
        self.project_application.execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.principal.principal_id,
                idempotency_key=f"project:create:{self.project_id}",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload={"title": "BookDesign Integration Project", "stage": "DESIGN"},
            ),
            principal=self.principal,
        )

    def _book_command(
        self,
        definition_name: str,
        *,
        payload: dict,
        idempotency_key: str,
        expected_book_version: int = 0,
        expected_design: str = "",
        target_asset_version_id: str = "",
    ) -> dict:
        return self.application.execute(
            BookDesignAuthorityCommand(
                definition_name=definition_name,
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.principal.principal_id,
                service_identity="authority-api",
                idempotency_key=idempotency_key,
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload=payload,
                expected_book_version=expected_book_version,
                expected_current_design_asset_version_id=expected_design,
                target_asset_version_id=target_asset_version_id,
            ),
            principal=self.principal,
        )

    @staticmethod
    def _design(theme: str) -> dict:
        return {
            "schema_version": BOOK_DESIGN_SCHEMA_VERSION,
            "title": "The Glass Harbor",
            "genre": "speculative mystery",
            "premise": "A cartographer proves that the city edits its own maps.",
            "theme": theme,
            "core_conflict": "A public witness network challenges a self-editing archive.",
            "reader_promise": "Each map anomaly reveals a deeper institutional bargain.",
            "ending": "The missing district returns and the archive becomes auditable.",
            "protagonist": {
                "name": "Mara",
                "external_goal": "Restore the missing district.",
                "internal_need": "Trust collaborators with incomplete evidence.",
                "flaw": "Treats uncertainty as personal failure.",
                "arc": "From solitary certainty to accountable collective truth.",
            },
            "world_rules": [
                "Maps change only after a signed archival decision.",
                "A witnessed place cannot be erased for seven days.",
            ],
            "target_chapters": 90,
            "core_characters": [
                {
                    "character_id": "mara",
                    "role": "protagonist",
                    "long_term_goal": "Restore the missing district.",
                    "causal_arc": "Isolation becomes accountable collaboration.",
                    "conflict_function": "Certainty delays collective action.",
                }
            ],
            "opposition_forces": [
                {
                    "force_id": "civic-archive",
                    "goal": "Control public memory.",
                    "leverage": "Rewrite official maps.",
                    "escalation_pattern": "Denial becomes erasure.",
                    "limit": "Witnessed places resist immediate erasure.",
                }
            ],
            "narrative_dna": {
                "core_question": "Who owns collectively witnessed truth?",
                "recurring_choice": "Certainty or disclosure.",
                "cost_logic": "Every fact exposes a witness.",
                "distinctive_mechanism": "Maps change physical access.",
                "emotional_contract": "Discovery brings hope and public cost.",
            },
            "narrative_qualification": scripted_qualification(
                "book_design.propose"
            ),
        }


if __name__ == "__main__":
    unittest.main()
