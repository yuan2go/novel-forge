from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.artifact_lineage import (
    ArtifactLineageEdge,
    InvalidationPolicy,
    PostgresArtifactLineageRepository,
    semantic_dimensions_for,
)
from novel_forge.modules.plan_change_authority import (
    PlanChangeProposalCommand,
    PlanChangeSource,
    PostgresPlanChangeAuthority,
)
from novel_forge.modules.story_design_authority import (
    DesignTransition,
    PlanningScope,
    StoryDesignTransitionCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
)


class PlanChangeAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        from tests.integration import (
            test_hierarchical_planning_postgres as planning_tests,
        )

        self.planning_fixture = (
            planning_tests.HierarchicalPlanningPostgresTests(
            methodName=(
                "test_active_plan_unique_and_frozen_replacement_requires_approval"
            )
            )
        )
        self.planning_fixture.setUp()
        self.project_id = self.planning_fixture.project_id
        self.book_id = self.planning_fixture.book_id
        self.principal = Principal(
            principal_id="plan-change-authority",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "story_design.authority.execute",
                    "book.authority.execute",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.planning_fixture.principal = self.principal
        self.story_design = self.planning_fixture.story_design
        self.planning = self.planning_fixture.planning
        self.failure_points: list[str] = []

    def test_plan_change_impact_approval_and_recoverable_activation(
        self,
    ) -> None:
        old = self.planning_fixture._activate_and_bind(
            self._book_type(),
            "book:main",
            execution_scope=self._frozen_scope(),
        )
        proposed_version = self._approved_candidate(
            logical_key="book:main",
            extra={
                "objective": "save the city without surrendering agency",
                "ending_contract": "choose agency and accept public cost",
            },
        )
        source_evidence = self._seed_asset(
            "recap-evidence",
            "longform_recap",
            {"deviations": ["ENDING_REACHABILITY_RISK"]},
        )
        planned = self._dependent_binding(
            old["asset_version_id"],
            logical_key="chapter:future",
            execution_scope="PLANNED",
        )
        executed = self._dependent_binding(
            old["asset_version_id"],
            logical_key="chapter:executed",
            execution_scope="EXECUTED",
        )
        requalification_only = self._dependent_binding(
            old["asset_version_id"],
            logical_key="chapter:requalification-only",
            execution_scope="PLANNED",
            invalidation_policy="REVALIDATE",
        )
        fail_once = {"pending": True}

        def inject(point: str) -> None:
            self.failure_points.append(point)
            if (
                point == "after_plan_activation_before_binding"
                and fail_once["pending"]
            ):
                fail_once["pending"] = False
                raise RuntimeError("injected activation interruption")

        authority = PostgresPlanChangeAuthority(
            DATABASE_URL,
            story_design=self.story_design,
            planning=self.planning,
            application_build_id="plan-change-integration",
            commit_sha="d" * 40,
            failure_injector=inject,
        )
        proposal = authority.propose(
            PlanChangeProposalCommand(
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                book_id=self.book_id,
                actor_id=self.principal.principal_id,
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"book:{self.book_id}",
                stable_idempotency_key=f"{self.project_id}:change:1",
                source_type=PlanChangeSource.LONGFORM_RECAP,
                source_evidence_version_id=source_evidence,
                target_asset_version_id=old["asset_version_id"],
                proposed_asset_version_id=proposed_version,
            ),
            principal=self.principal,
        )
        proposal_replay = authority.propose(
            PlanChangeProposalCommand(
                project_id=self.project_id,
                workspace_id=f"workspace:{self.project_id}",
                book_id=self.book_id,
                actor_id=self.principal.principal_id,
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"book:{self.book_id}",
                stable_idempotency_key=f"{self.project_id}:change:1",
                source_type=PlanChangeSource.LONGFORM_RECAP,
                source_evidence_version_id=source_evidence,
                target_asset_version_id=old["asset_version_id"],
                proposed_asset_version_id=proposed_version,
            ),
            principal=self.principal,
        )
        self.assertEqual(proposal_replay["proposal_id"], proposal["proposal_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_plan_change_proposal
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [self.project_id, f"{self.project_id}:change:1"],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 1)
        self.assertEqual(proposal["status"], "PENDING_APPROVAL")
        self.assertEqual(proposal["risk"], "HIGH")
        self.assertIn(
            "ENDING_CONTRACT_CHANGED",
            {item["change_type"] for item in proposal["semantic_diff"]},
        )
        self.assertEqual(
            self.planning.require_binding(
                project_id=self.project_id,
                asset_version_id=old["asset_version_id"],
            )["freshness"],
            "CURRENT",
        )

        approved = authority.decide(
            proposal["proposal_id"],
            approved=True,
            authority_type="BOOK_DESIGN_AUTHORITY",
            authority_version="stub-v1",
            evidence={
                "human_approved": True,
                "fixture_protocol_only": True,
                "production_verified": False,
            },
            principal=self.principal,
        )
        self.assertEqual(approved["status"], "APPROVED")
        with self.assertRaisesRegex(
            RuntimeError, "injected activation interruption"
        ):
            authority.activate(
                proposal["proposal_id"], principal=self.principal
            )
        interrupted = authority.require(proposal["proposal_id"])
        self.assertEqual(interrupted["status"], "ACTIVATION_PENDING")
        activated = authority.activate(
            proposal["proposal_id"], principal=self.principal
        )
        self.assertEqual(activated["status"], "ACTIVE")
        self.assertIn(
            "after_plan_activation_before_binding", self.failure_points
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT asset_version_id
                FROM active_story_plan_version
                WHERE project_id=%s AND book_id=%s
                  AND logical_key='book:main'
                """,
                [self.project_id, self.book_id],
            )
            active = str(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT asset_version_id, execution_scope, freshness
                FROM story_plan_binding
                WHERE asset_version_id=ANY(%s)
                ORDER BY asset_version_id
                """,
                [[planned, executed, requalification_only]],
            )
            impacted = {
                str(row[0]): (str(row[1]), str(row[2]))
                for row in uow.cursor.fetchall()
            }
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_plan_change_impact
                WHERE proposal_id=%s
                """,
                [proposal["proposal_id"]],
            )
            impact_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT invalidation_id
                FROM authority_artifact_invalidation
                WHERE project_id=%s AND target_asset_version_id=%s
                  AND status='OPEN'
                ORDER BY invalidation_id
                """,
                [self.project_id, planned],
            )
            planned_invalidation_ids = [str(row[0]) for row in uow.cursor.fetchall()]
        self.assertEqual(active, proposed_version)
        self.assertEqual(impacted[planned], ("PLANNED", "STALE"))
        self.assertEqual(impacted[executed], ("EXECUTED", "CURRENT"))
        self.assertEqual(
            impacted[requalification_only], ("PLANNED", "IMPACTED")
        )
        self.assertEqual(impact_count, 3)

        requalification_evidence = self._seed_asset(
            "plan-requalification-evidence",
            "plan_requalification_evidence",
            {
                "target_asset_version_id": planned,
                "resolution_status": "QUALIFIED",
                "invalidation_ids": planned_invalidation_ids,
            },
        )
        revalidated = authority.revalidate(
            project_id=self.project_id,
            asset_version_id=planned,
            evidence_version_id=requalification_evidence,
            principal=self.principal,
        )
        self.assertEqual(revalidated["freshness"], "CURRENT")
        self.assertEqual(
            self.planning.require_binding(
                project_id=self.project_id,
                asset_version_id=planned,
            )["freshness"],
            "CURRENT",
        )

    def _approved_candidate(
        self, *, logical_key: str, extra: dict
    ) -> str:
        content = self.planning_fixture._contract_content(
            self._book_type(),
            logical_key,
            parent_version_id="",
            extra=extra,
        )
        version_id, content_hash = self._seed_asset_with_hash(
            "proposed-book-plan",
            "book_plan_candidate",
            content,
        )
        self.planning_fixture._seed_generation_lineage(
            asset_version_id=version_id,
            content_hash=content_hash,
            contract_type=self._book_type(),
            logical_key=logical_key,
        )
        version = 0
        for transition in (
            DesignTransition.ENROLL,
            DesignTransition.MATERIALIZE,
            DesignTransition.STRUCTURAL_VALIDATE,
            DesignTransition.SEMANTIC_VALIDATE,
            DesignTransition.QUALIFY,
            DesignTransition.SUBMIT_APPROVAL,
            DesignTransition.APPROVE,
        ):
            state = self.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=self.project_id,
                    workspace_id=f"workspace:{self.project_id}",
                    actor_id=self.principal.principal_id,
                    trace_id=f"trace:{self.project_id}",
                    correlation_id=f"book:{self.book_id}",
                    idempotency_key=(
                        f"{self.project_id}:{version_id}:"
                        f"{transition.value}"
                    ),
                    asset_version_id=version_id,
                    content_hash=content_hash,
                    logical_key=logical_key,
                    generator_operation_name="book_plan.generate",
                    transition=transition,
                    planning_scope=PlanningScope.BOOK,
                    expected_version=version,
                    evidence=self.planning_fixture._fixture_pep_evidence(
                        transition
                    ),
                ),
                principal=self.principal,
            )
            version = int(state["version"])
        self.assertEqual(state["approval"], "APPROVED")
        self.assertEqual(state["lifecycle"], "MATERIALIZED")
        return version_id

    def _dependent_binding(
        self,
        source_version: str,
        *,
        logical_key: str,
        execution_scope: str,
        invalidation_policy: str = "MARK_STALE",
    ) -> str:
        version_id = self._seed_asset(
            logical_key.replace(":", "-"),
            "chapter_plan_candidate",
            {
                "logical_key": logical_key,
                "chapter_number": 99,
            },
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT created_by_operation_id
                FROM story_plan_binding
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [self.project_id, source_version],
            )
            operation_id = str(uow.cursor.fetchone()[0])
            binding_id = f"binding:{self.project_id}:{logical_key}"
            uow.cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, 'CHAPTER', %s, %s, %s,
                    %s, 'CURRENT', %s
                )
                """,
                [
                    binding_id,
                    self.project_id,
                    self.book_id,
                    logical_key,
                    version_id,
                    source_version,
                    execution_scope,
                    operation_id,
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO asset_dependency_edge(
                    dependency_edge_id, project_id, book_id,
                    source_asset_version_id, dependent_asset_version_id,
                    dependency_type, invalidation_policy,
                    created_by_operation_id
                ) VALUES (%s, %s, %s, %s, %s, 'PLAN_IMPACT',
                          %s, %s)
                """,
                [
                    f"dependency:{self.project_id}:{logical_key}",
                    self.project_id,
                    self.book_id,
                    source_version,
                    version_id,
                    invalidation_policy,
                    operation_id,
                ],
            )
            policy = (
                InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
                if execution_scope == "EXECUTED"
                else (
                    InvalidationPolicy.REQUALIFY
                    if invalidation_policy == "REVALIDATE"
                    else InvalidationPolicy.PROPAGATE
                )
            )
            PostgresArtifactLineageRepository(uow.cursor).record_edge(
                ArtifactLineageEdge(
                    project_id=self.project_id,
                    book_id=self.book_id,
                    upstream_asset_version_id=source_version,
                    downstream_asset_version_id=version_id,
                    relationship_type="PLAN_IMPACT",
                    semantic_dimensions=semantic_dimensions_for(
                        ("PLAN_IMPACT", "planning")
                    ),
                    invalidation_policy=policy,
                    context_fingerprint="",
                    created_by_operation_id=operation_id,
                )
            )
            uow.commit()
        return version_id

    def _seed_asset(
        self, label: str, asset_type: str, content: dict
    ) -> str:
        return self._seed_asset_with_hash(
            label, asset_type, content
        )[0]

    def _seed_asset_with_hash(
        self, label: str, asset_type: str, content: dict
    ) -> tuple[str, str]:
        asset_id = f"{self.project_id}:{label}:asset"
        version_id = f"{self.project_id}:{label}:v1"
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [asset_id, self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1'
                )
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'plan-change-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return version_id, content_hash

    @staticmethod
    def _book_type():
        from novel_forge.modules.hierarchical_planning import (
            PlanContractType,
        )

        return PlanContractType.BOOK

    @staticmethod
    def _frozen_scope():
        from novel_forge.modules.hierarchical_planning import (
            PlanExecutionScope,
        )

        return PlanExecutionScope.FROZEN


if __name__ == "__main__":
    unittest.main()
