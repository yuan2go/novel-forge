from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class StoryDesignAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("story-design")
        self.principal = Principal(
            principal_id="story-design-authority",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"story_design.authority.execute"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.authority = PostgresStoryDesignAssetAuthority(
            DATABASE_URL,
            application_build_id="story-design-integration",
            commit_sha="a" * 40,
        )
        self.counter = 0

    def test_generator_cannot_activate_directly(self) -> None:
        candidate = self._seed_candidate("book-plan-candidate-1")
        enrolled = self._transition(
            candidate,
            DesignTransition.ENROLL,
            expected_version=0,
        )
        self.assertEqual(enrolled["lifecycle"], "CANDIDATE")
        with self.assertRaisesRegex(
            KernelError, "STORY_DESIGN_TRANSITION_INVALID"
        ):
            self._transition(
                candidate,
                DesignTransition.ACTIVATE,
                expected_version=0,
            )
        self.assertEqual(
            self.authority.require(
                project_id=self.project_id,
                asset_version_id=candidate["asset_version_id"],
            )["lifecycle"],
            "CANDIDATE",
        )

    def test_candidate_requires_frozen_pep_evidence(self) -> None:
        candidate = self._seed_candidate("book-plan-candidate-no-evidence")
        with self.assertRaisesRegex(
            KernelError, "STORY_DESIGN_PEP_EVIDENCE_REQUIRED"
        ):
            self._transition(
                candidate,
                DesignTransition.ENROLL,
                expected_version=0,
                evidence={"fixture_protocol_only": True},
            )

    def test_activation_supersedes_old_version(self) -> None:
        first = self._seed_candidate("book-plan-candidate-a")
        second = self._seed_candidate("book-plan-candidate-b")
        self._advance_to_active(first)
        self._advance_to_active(second)
        first_state = self.authority.require(
            project_id=self.project_id,
            asset_version_id=first["asset_version_id"],
        )
        second_state = self.authority.require(
            project_id=self.project_id,
            asset_version_id=second["asset_version_id"],
        )
        self.assertEqual(first_state["lifecycle"], "SUPERSEDED")
        self.assertEqual(second_state["lifecycle"], "ACTIVE")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), MAX(asset_version_id)
                FROM authority_story_design_active_version
                WHERE project_id=%s AND logical_key='book-plan:main'
                """,
                [self.project_id],
            )
            count, active = uow.cursor.fetchone()
        self.assertEqual(int(count), 1)
        self.assertEqual(str(active), second["asset_version_id"])

    def test_legacy_import_is_not_automatically_active(self) -> None:
        candidate = self._seed_candidate("legacy-book-plan")
        state = self._transition(
            candidate,
            DesignTransition.ENROLL,
            expected_version=0,
            source_kind="LEGACY_IMPORT",
            evidence={
                "legacy_import_operation_id": "fixture-import-operation",
                "fixture_protocol_only": True,
                "production_verified": False,
            },
        )
        self.assertEqual(state["lifecycle"], "CANDIDATE")
        self.assertEqual(state["approval"], "NOT_REQUESTED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_story_design_active_version
                WHERE project_id=%s
                """,
                [self.project_id],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 0)

    def test_semantic_repair_is_bounded(self) -> None:
        candidate = self._seed_candidate("bounded-repair")
        state = self._transition(
            candidate, DesignTransition.ENROLL, expected_version=0
        )
        state = self._transition(
            candidate,
            DesignTransition.MATERIALIZE,
            expected_version=int(state["version"]),
        )
        state = self._transition(
            candidate,
            DesignTransition.STRUCTURAL_VALIDATE,
            expected_version=int(state["version"]),
            evidence={"passed": True},
        )
        for expected_repair in (1, 2, 3):
            state = self._transition(
                candidate,
                DesignTransition.SEMANTIC_VALIDATE,
                expected_version=int(state["version"]),
                evidence={"passed": False},
            )
            self.assertEqual(
                int(state["semantic_repair_count"]), expected_repair
            )
        self.assertEqual(state["lifecycle"], "REJECTED")
        self.assertEqual(state["qualification"], "FAILED")

    def _advance_to_active(self, candidate: dict[str, str]) -> None:
        state = self._transition(
            candidate, DesignTransition.ENROLL, expected_version=0
        )
        for transition in (
            DesignTransition.MATERIALIZE,
            DesignTransition.STRUCTURAL_VALIDATE,
            DesignTransition.SEMANTIC_VALIDATE,
            DesignTransition.QUALIFY,
            DesignTransition.SUBMIT_APPROVAL,
            DesignTransition.APPROVE,
            DesignTransition.ACTIVATE,
        ):
            state = self._transition(
                candidate,
                transition,
                expected_version=int(state["version"]),
                evidence={"passed": True},
            )
        self.assertEqual(state["lifecycle"], "ACTIVE")

    def _transition(
        self,
        candidate: dict[str, str],
        transition: DesignTransition,
        *,
        expected_version: int,
        source_kind: str = "GENERATED",
        evidence: dict | None = None,
    ) -> dict:
        self.counter += 1
        effective_evidence = (
            {
                "production_execution_gateway_backed": True,
                "operation_id": "fixture-generator-operation",
                "attempt_id": "fixture-attempt",
                "route_snapshot_id": "fixture-route-snapshot",
                "input_manifest_ref": "fixture-input-manifest",
                "validation_manifest_ref": "fixture-validation-manifest",
                "usage_receipt_ref": "fixture-usage-receipt",
                "cost_receipt_ref": "fixture-cost-receipt",
                "fixture_protocol_only": True,
                "real_provider_proven": False,
                "production_verified": False,
            }
            if evidence is None
            else evidence
        )
        return self.authority.transition(
            StoryDesignTransitionCommand(
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                actor_id=self.principal.principal_id,
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                idempotency_key=(
                    f"{self.project_id}:{candidate['asset_version_id']}:"
                    f"{transition.value}:{self.counter}"
                ),
                asset_version_id=candidate["asset_version_id"],
                content_hash=candidate["content_hash"],
                logical_key="book-plan:main",
                generator_operation_name="book_plan.generate",
                transition=transition,
                planning_scope=PlanningScope.BOOK,
                expected_version=expected_version,
                source_kind=source_kind,
                evidence=effective_evidence,
            ),
            principal=self.principal,
        )

    def _seed_candidate(self, label: str) -> dict[str, str]:
        asset_id = f"{self.project_id}:{label}"
        version_id = f"{asset_id}:v1"
        content = {
            "type": "BookPlanCandidate",
            "project_id": self.project_id,
            "candidate_id": label,
        }
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, 'book_plan_candidate')
                """,
                [asset_id, self.project_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number,
                    lifecycle, eligibility, governance, content, content_hash
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s
                )
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.commit()
        return {
            "asset_version_id": version_id,
            "content_hash": content_hash,
        }


if __name__ == "__main__":
    unittest.main()
