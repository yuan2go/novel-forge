from __future__ import annotations

import hashlib
import json
import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PlanExecutionScope,
    PostgresHierarchicalPlanningAuthority,
)
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
    seed_authority_project_book,
)


_GENERATOR = {
    PlanContractType.BOOK: "book_plan.generate",
    PlanContractType.VOLUME: "volume_plan.generate",
    PlanContractType.ARC: "arc_plan.generate",
    PlanContractType.CHAPTER_GROUP: "chapter_group_plan.generate",
    PlanContractType.CHAPTER: "chapter_plan.generate",
}


class HierarchicalPlanningPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("hierarchical-plan")
        self.book_id = identifier("book")
        seed_authority_project_book(project_id=self.project_id, book_id=self.book_id)
        self.principal = Principal(
            principal_id="planning-authority",
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
        self.story_design = PostgresStoryDesignAssetAuthority(
            DATABASE_URL,
            application_build_id="hierarchical-planning-integration",
            commit_sha="b" * 40,
        )
        self.planning = PostgresHierarchicalPlanningAuthority(
            DATABASE_URL,
            application_build_id="hierarchical-planning-integration",
            commit_sha="b" * 40,
        )
        self.counter = 0

    def test_book_volume_group_hierarchy_and_parent_versions(self) -> None:
        book = self._activate_and_bind(
            PlanContractType.BOOK,
            "book:main",
        )
        volume = self._activate_and_bind(
            PlanContractType.VOLUME,
            "volume:1",
            parent=book,
        )
        group = self._activate_and_bind(
            PlanContractType.CHAPTER_GROUP,
            "group:1",
            parent=volume,
        )
        chapter = self._activate_and_bind(
            PlanContractType.CHAPTER,
            "chapter:1",
            parent=group,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT relation_type
                FROM story_plan_hierarchy
                WHERE project_id=%s
                ORDER BY relation_type
                """,
                [self.project_id],
            )
            relations = [str(row[0]) for row in uow.cursor.fetchall()]
        self.assertEqual(
            relations,
            [
                "BOOK_CONTAINS_VOLUME",
                "CHAPTER_GROUP_CONTAINS_CHAPTER",
                "VOLUME_CONTAINS_CHAPTER_GROUP",
            ],
        )
        self.assertEqual(
            chapter["parent_version_id"],
            group["asset_version_id"],
        )

        other_book = self._activate_and_bind(
            PlanContractType.BOOK,
            "book:other",
        )
        with self.assertRaisesRegex(KernelError, "PLANNING_PARENT_BINDING_INVALID"):
            self._activate_and_bind(
                PlanContractType.CHAPTER,
                "chapter:bad-parent",
                parent=other_book,
            )

    def test_arc_crosses_volumes_and_chapter_contributes_to_multiple_arcs(
        self,
    ) -> None:
        book = self._activate_and_bind(
            PlanContractType.BOOK,
            "book:main",
        )
        volume1 = self._activate_and_bind(
            PlanContractType.VOLUME,
            "volume:1",
            parent=book,
        )
        volume2 = self._activate_and_bind(
            PlanContractType.VOLUME,
            "volume:2",
            parent=book,
        )
        arc1 = self._activate_and_bind(
            PlanContractType.ARC,
            "arc:main",
            extra={
                "cross_volume_scope": [
                    volume1["asset_version_id"],
                    volume2["asset_version_id"],
                ]
            },
        )
        arc2 = self._activate_and_bind(
            PlanContractType.ARC,
            "arc:relationship",
            extra={"cross_volume_scope": [volume1["asset_version_id"]]},
        )
        group = self._activate_and_bind(
            PlanContractType.CHAPTER_GROUP,
            "group:1",
            parent=volume1,
        )
        chapter = self._activate_and_bind(
            PlanContractType.CHAPTER,
            "chapter:1",
            parent=group,
            extra={
                "required_arc_contributions": [
                    {"arc_plan_version_id": arc1["asset_version_id"]},
                    {"arc_plan_version_id": arc2["asset_version_id"]},
                ]
            },
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT source_asset_version_id, dependent_asset_version_id
                FROM asset_dependency_edge
                WHERE project_id=%s AND dependency_type='ARC_CONTRIBUTION'
                """,
                [self.project_id],
            )
            edges = {(str(row[0]), str(row[1])) for row in uow.cursor.fetchall()}
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM story_plan_hierarchy AS hierarchy
                JOIN story_plan_binding AS child
                  ON child.binding_id=hierarchy.child_binding_id
                WHERE hierarchy.project_id=%s
                  AND child.contract_type='ARC'
                """,
                [self.project_id],
            )
            arc_containment_count = int(uow.cursor.fetchone()[0])
        self.assertIn(
            (volume1["asset_version_id"], arc1["asset_version_id"]),
            edges,
        )
        self.assertIn(
            (volume2["asset_version_id"], arc1["asset_version_id"]),
            edges,
        )
        self.assertIn(
            (arc1["asset_version_id"], chapter["asset_version_id"]),
            edges,
        )
        self.assertIn(
            (arc2["asset_version_id"], chapter["asset_version_id"]),
            edges,
        )
        self.assertEqual(arc_containment_count, 0)

    def test_canonical_segment_arc_and_chapter_execution_views_compose(self) -> None:
        book = self._activate_and_bind(PlanContractType.BOOK, "book:canonical")
        volume = self._activate_and_bind(
            PlanContractType.VOLUME,
            "volume:canonical",
            parent=book,
            extra={
                "narrative_architecture_version": "canonical-narrative-v1",
                "narrative_segments": [
                    {
                        "segment_id": "segment:commitment",
                        "objective": "force public commitment",
                        "chapter_range": [1, 3],
                        "entry_state_ref": "story-state:v0",
                        "exit_state_spec": {"summary": "commitment is public"},
                        "arc_checkpoint_refs": ["arc:accountability"],
                    }
                ],
            },
        )
        arc = self._activate_and_bind(
            PlanContractType.ARC,
            "arc:canonical",
            extra={
                "narrative_architecture_version": "canonical-narrative-v1",
                "thread_id": "thread:accountability",
                "cross_volume_scope": [volume["asset_version_id"]],
                "arc_segments": [
                    {
                        "segment_id": "arc-segment:choice",
                        "volume_plan_version_id": volume["asset_version_id"],
                        "narrative_segment_id": "segment:commitment",
                        "objective": "denial becomes action",
                        "entry_state_ref": "arc-state:denial",
                        "exit_state_spec": {"summary": "action has cost"},
                        "status": "PLANNED",
                    }
                ],
                "arc_relations": [],
            },
        )
        group = self._activate_and_bind(
            PlanContractType.CHAPTER_GROUP,
            "group:canonical",
            parent=volume,
            extra={
                "narrative_architecture_version": "canonical-narrative-v1",
                "narrative_segment_ref": {
                    "volume_plan_version_id": volume["asset_version_id"],
                    "segment_id": "segment:commitment",
                },
            },
        )
        chapter = self._activate_and_bind(
            PlanContractType.CHAPTER,
            "chapter:canonical",
            parent=group,
            extra={
                "narrative_architecture_version": "canonical-narrative-v1",
                "narrative_segment_ref": {
                    "volume_plan_version_id": volume["asset_version_id"],
                    "segment_id": "segment:commitment",
                },
                "chapter_intent": "make the choice visible",
                "arc_schedule": [
                    {
                        "arc_plan_version_id": arc["asset_version_id"],
                        "role": "PRIMARY",
                        "segment_id": "arc-segment:choice",
                        "expected_movement": "denial to action",
                    }
                ],
                "required_arc_contributions": [
                    {
                        "arc_plan_version_id": arc["asset_version_id"],
                        "contribution": "denial becomes visible action",
                    }
                ],
                "setups": [],
                "payoffs": [],
                "character_participation": [{"character_id": "character:lin"}],
                "knowledge_boundaries": [{"fact_id": "fact:ledger"}],
                "disclosures": [{"disclosure_id": "disclosure:ledger"}],
                "required_state_transitions": [{"entity_key": "character:lin"}],
                "reader_experience": {"target_emotion": "costly relief"},
                "scene_plan": [{"scene_id": "scene:1"}],
                "expected_exit_state": {"summary": "the choice is public"},
            },
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT narrative_segment_id FROM authority_narrative_segment_projection "
                "WHERE project_id=%s AND volume_plan_version_id=%s",
                [self.project_id, volume["asset_version_id"]],
            )
            self.assertEqual(uow.cursor.fetchone()[0], "segment:commitment")
            uow.cursor.execute(
                "SELECT thread_id FROM authority_narrative_arc_graph_projection "
                "WHERE project_id=%s AND arc_plan_version_id=%s",
                [self.project_id, arc["asset_version_id"]],
            )
            self.assertEqual(uow.cursor.fetchone()[0], "thread:accountability")
            uow.cursor.execute(
                "SELECT chapter_intent FROM authority_chapter_execution_plan_projection "
                "WHERE project_id=%s AND chapter_plan_version_id=%s",
                [self.project_id, chapter["asset_version_id"]],
            )
            self.assertEqual(uow.cursor.fetchone()[0], "make the choice visible")

    def test_active_plan_unique_and_frozen_replacement_requires_approval(
        self,
    ) -> None:
        first = self._activate_and_bind(
            PlanContractType.BOOK,
            "book:main",
            execution_scope=PlanExecutionScope.FROZEN,
        )
        replacement_version = self._activate_design(
            PlanContractType.BOOK,
            "book:main",
            label="replacement",
        )
        with self.assertRaisesRegex(KernelError, "FROZEN_PLAN_APPROVAL_REQUIRED"):
            self.planning.bind_active_contract(
                project_id=self.project_id,
                book_id=self.book_id,
                asset_version_id=replacement_version,
                contract_type=PlanContractType.BOOK,
                expected_active_asset_version_id=first["asset_version_id"],
                **self._binding_command(replacement_version, "rejected"),
            )
        replacement = self.planning.bind_active_contract(
            project_id=self.project_id,
            book_id=self.book_id,
            asset_version_id=replacement_version,
            contract_type=PlanContractType.BOOK,
            replacement_approved=True,
            expected_active_asset_version_id=first["asset_version_id"],
            decision_evidence={"decision_id": "fixture-approval"},
            **self._binding_command(replacement_version, "approved"),
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), MAX(asset_version_id)
                FROM active_story_plan_version
                WHERE project_id=%s AND book_id=%s AND logical_key='book:main'
                """,
                [self.project_id, self.book_id],
            )
            count, active = uow.cursor.fetchone()
            uow.cursor.execute(
                "SELECT freshness FROM story_plan_binding WHERE binding_id=%s",
                [first["binding_id"]],
            )
            old_freshness = str(uow.cursor.fetchone()[0])
        self.assertEqual(int(count), 1)
        self.assertEqual(str(active), replacement["asset_version_id"])
        self.assertEqual(old_freshness, "STALE")

    def test_executed_plan_is_not_overwritten(self) -> None:
        executed = self._activate_and_bind(
            PlanContractType.BOOK,
            "book:main",
            execution_scope=PlanExecutionScope.EXECUTED,
        )
        replacement = self._activate_design(
            PlanContractType.BOOK,
            "book:main",
            label="replacement",
        )
        with self.assertRaisesRegex(KernelError, "EXECUTED_PLAN_IMMUTABLE"):
            self.planning.bind_active_contract(
                project_id=self.project_id,
                book_id=self.book_id,
                asset_version_id=replacement,
                contract_type=PlanContractType.BOOK,
                replacement_approved=True,
                expected_active_asset_version_id=executed["asset_version_id"],
                decision_evidence={"decision_id": "fixture-approval"},
                **self._binding_command(replacement, "executed-replacement"),
            )

    def test_binding_has_own_atomic_operation_and_idempotent_replay(self) -> None:
        asset_version_id = self._activate_design(
            PlanContractType.BOOK, "book:formal-binding"
        )
        metadata = {
            "workspace_id": f"workspace:{self.project_id}",
            "actor_id": self.principal.principal_id,
            "idempotency_key": f"formal-binding:{asset_version_id}",
            "trace_id": f"trace:formal-binding:{self.project_id}",
            "correlation_id": f"book:{self.book_id}",
            "principal": self.principal,
        }
        first = self.planning.bind_active_contract(
            project_id=self.project_id,
            book_id=self.book_id,
            asset_version_id=asset_version_id,
            contract_type=PlanContractType.BOOK,
            **metadata,
        )
        replay = self.planning.bind_active_contract(
            project_id=self.project_id,
            book_id=self.book_id,
            asset_version_id=asset_version_id,
            contract_type=PlanContractType.BOOK,
            **metadata,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.definition_name,
                       COUNT(attempt.attempt_id)
                FROM authority_operation AS operation
                LEFT JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                GROUP BY operation.status, operation.definition_name
                """,
                [first["operation_id"]],
            )
            operation = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM outbox_event
                WHERE project_id=%s AND topic='story_plan.bound'
                  AND payload->>'operation_id'=%s
                """,
                [self.project_id, first["operation_id"]],
            )
            outbox_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT updated_by_operation_id
                FROM authority_story_design_version_state
                WHERE asset_version_id=%s
                """,
                [asset_version_id],
            )
            story_design_operation_id = str(uow.cursor.fetchone()[0])
        self.assertEqual(first["operation_id"], replay["operation_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            tuple(operation), ("SUCCEEDED", "planning.binding.activate", 0)
        )
        self.assertEqual(outbox_count, 1)
        self.assertNotEqual(first["operation_id"], story_design_operation_id)
        self.assertEqual(first["created_by_operation_id"], first["operation_id"])

    def test_binding_rolls_back_business_outbox_and_operation_on_fault(self) -> None:
        asset_version_id = self._activate_design(PlanContractType.BOOK, "book:rollback")

        def inject(point: str) -> None:
            if point == "after_outbox_insert":
                raise RuntimeError("injected planning binding failure")

        authority = PostgresHierarchicalPlanningAuthority(
            DATABASE_URL,
            application_build_id="hierarchical-planning-fault-test",
            commit_sha="c" * 40,
            fault_injector=inject,
        )
        idempotency_key = f"formal-binding-fault:{asset_version_id}"
        with self.assertRaisesRegex(RuntimeError, "injected planning"):
            authority.bind_active_contract(
                project_id=self.project_id,
                book_id=self.book_id,
                asset_version_id=asset_version_id,
                contract_type=PlanContractType.BOOK,
                workspace_id=f"workspace:{self.project_id}",
                actor_id=self.principal.principal_id,
                idempotency_key=idempotency_key,
                trace_id=f"trace:formal-binding:{self.project_id}",
                correlation_id=f"book:{self.book_id}",
                principal=self.principal,
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM story_plan_binding WHERE asset_version_id=%s",
                [asset_version_id],
            )
            binding_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE idempotency_key=%s",
                [idempotency_key],
            )
            operation_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM outbox_event
                WHERE project_id=%s AND topic='story_plan.bound'
                  AND payload->>'asset_version_id'=%s
                """,
                [self.project_id, asset_version_id],
            )
            outbox_count = int(uow.cursor.fetchone()[0])
        self.assertEqual((binding_count, operation_count, outbox_count), (0, 0, 0))

    def _activate_and_bind(
        self,
        contract_type: PlanContractType,
        logical_key: str,
        *,
        parent: dict | None = None,
        execution_scope: PlanExecutionScope = PlanExecutionScope.PLANNED,
        extra: dict | None = None,
    ) -> dict:
        version_id = self._activate_design(
            contract_type,
            logical_key,
            parent_version_id=(
                "" if parent is None else str(parent["asset_version_id"])
            ),
            extra=extra,
        )
        return self.planning.bind_active_contract(
            project_id=self.project_id,
            book_id=self.book_id,
            asset_version_id=version_id,
            contract_type=contract_type,
            parent_version_id=(
                "" if parent is None else str(parent["asset_version_id"])
            ),
            execution_scope=execution_scope,
            **self._binding_command(version_id, "initial"),
        )

    def _binding_command(self, asset_version_id: str, label: str) -> dict:
        self.counter += 1
        return {
            "workspace_id": f"workspace:{self.project_id}",
            "actor_id": self.principal.principal_id,
            "idempotency_key": (
                f"planning-bind:{self.project_id}:{asset_version_id}:"
                f"{label}:{self.counter}"
            ),
            "trace_id": f"trace:planning-bind:{self.project_id}",
            "correlation_id": f"book:{self.book_id}",
            "principal": self.principal,
        }

    def _activate_design(
        self,
        contract_type: PlanContractType,
        logical_key: str,
        *,
        parent_version_id: str = "",
        extra: dict | None = None,
        label: str = "",
    ) -> str:
        self.counter += 1
        content = self._contract_content(
            contract_type,
            logical_key,
            parent_version_id=parent_version_id,
            extra=extra,
        )
        suffix = label or str(self.counter)
        asset_id = (
            f"{self.project_id}:{contract_type.value.lower()}:{logical_key}:{suffix}"
        )
        version_id = f"{asset_id}:v1"
        content_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [
                    asset_id,
                    self.project_id,
                    f"{contract_type.value.lower()}_plan_candidate",
                ],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number,
                    lifecycle, eligibility, governance, content, content_hash, schema_version
                ) VALUES (
                    %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1'
                )
                """,
                [version_id, asset_id, json.dumps(content), content_hash],
            )
            uow.commit()
        state_version = 0
        transitions = (
            DesignTransition.ENROLL,
            DesignTransition.MATERIALIZE,
            DesignTransition.STRUCTURAL_VALIDATE,
            DesignTransition.SEMANTIC_VALIDATE,
            DesignTransition.QUALIFY,
            DesignTransition.SUBMIT_APPROVAL,
            DesignTransition.APPROVE,
            DesignTransition.ACTIVATE,
        )
        for transition in transitions:
            self.counter += 1
            state = self.story_design.transition(
                StoryDesignTransitionCommand(
                    project_id=self.project_id,
                    workspace_id=f"workspace:{self.project_id}",
                    actor_id=self.principal.principal_id,
                    trace_id=f"trace:{self.project_id}",
                    correlation_id=f"book:{self.book_id}",
                    idempotency_key=(
                        f"{self.project_id}:{version_id}:"
                        f"{transition.value}:{self.counter}"
                    ),
                    asset_version_id=version_id,
                    content_hash=content_hash,
                    logical_key=logical_key,
                    generator_operation_name=_GENERATOR[contract_type],
                    transition=transition,
                    planning_scope=PlanningScope(contract_type.value),
                    expected_version=state_version,
                    evidence=self._fixture_pep_evidence(transition),
                ),
                principal=self.principal,
            )
            state_version = int(state["version"])
        return version_id

    def _contract_content(
        self,
        contract_type: PlanContractType,
        logical_key: str,
        *,
        parent_version_id: str,
        extra: dict | None,
    ) -> dict:
        values = {
            "contract_id": f"contract:{self.project_id}:{logical_key}",
            "project_id": self.project_id,
            "book_id": self.book_id,
            "logical_key": logical_key,
            "parent_version_id": parent_version_id,
            "objective": f"objective for {logical_key}",
            "entry_state_ref": "story-state:entry",
            "exit_state_spec": {"pressure": "advanced"},
            "hard_constraints": ["preserve accepted history"],
            "soft_constraints": ["vary rhythm"],
            "required_events": ["meaningful escalation"],
            "forbidden_events": ["premature ending"],
            "required_payoffs": ["local consequence"],
            "forbidden_payoffs": ["final mystery closure"],
            "character_deltas": [{"character": "protagonist"}],
            "world_deltas": [{"rule": "pressure rises"}],
            "relationship_deltas": [{"pair": "protagonist:rival"}],
            "arc_contributions": ["mainline advances"],
            "canon_dependencies": [],
            "quality_targets": {"minimum": "qualified"},
            "budget_policy_ref": "budget:planning:v1",
            "context_profile_ref": "context:planning:v1",
        }
        if contract_type is PlanContractType.BOOK:
            values.update(
                {
                    "reader_promise": "progress with meaningful cost",
                    "central_conflict_engine": "agency versus control",
                    "protagonist_transformation": "reactive to responsible",
                    "antagonist_escalation": "adapts to every public win",
                    "world_evolution": "institutions polarize",
                    "relationship_evolution": "trust becomes negotiated",
                    "theme_evolution": "power tests responsibility",
                    "ending_contract": "costly self-authored choice",
                    "volume_skeleton": ["volume one", "volume two"],
                    "major_turns": ["first reversal"],
                    "climax_distribution": ["volume climax"],
                    "long_promise_payoff": ["identity truth"],
                    "length_strategy": {"target_chapters": 100},
                    "risk_register": ["power inflation"],
                }
            )
        elif contract_type is PlanContractType.VOLUME:
            values.update(
                {
                    "volume_function": "establish and overturn local order",
                    "stage_conflict": "institutional capture",
                    "stage_antagonist": "regional operator",
                    "irreversible_change": "public commitment",
                    "midpoint": "ally defects",
                    "climax": "costly local victory",
                    "settlement": "new obligation",
                    "next_volume_bridge": "central power responds",
                    "chapter_range": [1, 20],
                }
            )
        elif contract_type is PlanContractType.ARC:
            values.update(
                {
                    "arc_type": "mainline",
                    "resistance": "adaptive antagonist",
                    "escalation": "cost moves from private to public",
                    "turn": "apparent ally reveals leverage",
                    "choice": "protect status or reveal truth",
                    "cost": "loss of safe identity",
                    "result": "temporary strategic access",
                    "consequence": "antagonist changes tactics",
                    "dependencies": ["book reader promise"],
                    "closure_conditions": ["choice paid for"],
                    "cross_volume_scope": [],
                }
            )
        elif contract_type is PlanContractType.CHAPTER_GROUP:
            values.update(
                {
                    "local_objective": "force a public commitment",
                    "trigger": "resource is seized",
                    "resistance_escalation": "each move reveals a deeper cost",
                    "turn": "trusted route is compromised",
                    "local_climax": "commitment under surveillance",
                    "information_release": ["antagonist knows the mechanism"],
                    "emotion_curve": ["uncertainty", "resolve", "cost"],
                    "antagonist_actions": ["observe", "contain", "counter"],
                    "chapter_function_matrix": [
                        self._chapter_matrix_row(1, "DISCOVERY", "new threat"),
                        self._chapter_matrix_row(2, "ESCALATION", "cost revealed"),
                        self._chapter_matrix_row(3, "REVERSAL", "choice demanded"),
                    ],
                    "chapter_range": [1, 3],
                    "cost_range": [100, 300],
                }
            )
        else:
            values.update(self._chapter_matrix_row(1, "DISCOVERY", "new threat"))
            values["required_arc_contributions"] = []
        values.update(extra or {})
        return values

    @staticmethod
    def _chapter_matrix_row(
        chapter: int, primary_function: str, ending_hook: str
    ) -> dict:
        return {
            "chapter_number": chapter,
            "primary_function": primary_function,
            "secondary_functions": ["continuity"],
            "required_state_delta": {"pressure": chapter},
            "required_arc_contributions": ["mainline"],
            "promise_action": "advance",
            "foreshadow_action": "plant",
            "reward_action": "partial",
            "ending_hook": ending_hook,
            "prohibited_outcomes": ["premature closure"],
        }

    @staticmethod
    def _fixture_pep_evidence(
        transition: DesignTransition,
    ) -> dict:
        return {
            "production_execution_gateway_backed": True,
            "operation_id": f"fixture-generator:{transition.value}",
            "attempt_id": f"fixture-attempt:{transition.value}",
            "route_snapshot_id": f"fixture-route:{transition.value}",
            "input_manifest_ref": f"fixture-input:{transition.value}",
            "validation_manifest_ref": f"fixture-validation:{transition.value}",
            "usage_receipt_ref": f"fixture-usage:{transition.value}",
            "cost_receipt_ref": f"fixture-cost:{transition.value}",
            "passed": True,
            "fixture_protocol_only": True,
            "real_provider_proven": False,
            "production_verified": False,
        }


if __name__ == "__main__":
    unittest.main()
