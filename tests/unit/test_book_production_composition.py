from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType


class BookProductionCompositionTests(unittest.TestCase):
    def test_book_opening_recovery_http_surfaces_share_one_application(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from novel_forge.api.models import product_model_map
        from novel_forge.api.routers.book_authority import create_router
        from novel_forge.api.routers.context import ProductRouterContext
        from novel_forge.modules.book_authority import (
            BookOpeningBudgetReconciliationReceipt,
            RecoveryAssessment,
            RecoveryReceipt,
        )
        from novel_forge.modules.command_kernel.budget_runtime import (
            canonical_budget_policy,
        )

        calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        class RecoveryApplication:
            @staticmethod
            def _assessment(kind: str) -> RecoveryAssessment:
                return RecoveryAssessment(
                    recovery_assessment_id=f"assessment:{kind}",
                    assessment_kind=kind,
                    opening_run_id="opening:1",
                    disposition="PROVEN_NO_EFFECT",
                    snapshot_hash="sha256:" + "1" * 64,
                    snapshot={},
                    replayed=False,
                )

            @staticmethod
            def _receipt(kind: str) -> RecoveryReceipt:
                return RecoveryReceipt(
                    recovery_receipt_id=f"receipt:{kind}",
                    receipt_kind=kind,
                    opening_run_id="opening:1",
                    recovery_assessment_id="assessment:1",
                    recovery_intent_id=(
                        "intent:1" if kind == "RECOVERY_ADMISSION" else ""
                    ),
                    result_hash="sha256:" + "2" * 64,
                    result={"provider_invoked": False},
                    replayed=False,
                )

            def reconcile_legacy_execution(self, *args: object, **kwargs: object):
                calls.append(("reconcile_legacy_execution", args, kwargs))
                return self._receipt("CHECKPOINT_RECONCILIATION")

            def assess_execution_loss(self, *args: object, **kwargs: object):
                calls.append(("assess_execution_loss", args, kwargs))
                return self._assessment("EXECUTION_LOSS")

            def converge_execution_loss(self, *args: object, **kwargs: object):
                calls.append(("converge_execution_loss", args, kwargs))
                return self._receipt("EXECUTION_LOSS_CONVERGENCE")

            def assess_recovery(self, *args: object, **kwargs: object):
                calls.append(("assess_recovery", args, kwargs))
                return self._assessment("RECOVERY")

            def recover(self, *args: object, **kwargs: object):
                calls.append(("recover", args, kwargs))
                return self._receipt("RECOVERY_ADMISSION")

            def assess_checkpoint_reconciliation(self, *args: object, **kwargs: object):
                calls.append(("assess_checkpoint_reconciliation", args, kwargs))
                return self._assessment("CHECKPOINT_RECONCILIATION")

            def reconcile_checkpoint(self, *args: object, **kwargs: object):
                calls.append(("reconcile_checkpoint", args, kwargs))
                return self._receipt("CHECKPOINT_RECONCILIATION")

        class OpeningApplication:
            recovery = RecoveryApplication()

            def reconcile_legacy_budget_scope(
                self, *args: object, **kwargs: object
            ) -> BookOpeningBudgetReconciliationReceipt:
                calls.append(("reconcile_legacy_budget_scope", args, kwargs))
                return BookOpeningBudgetReconciliationReceipt(
                    budget_reconciliation_receipt_id="budget-receipt:1",
                    opening_run_id="opening:1",
                    budget_scope_id="budget-scope:1",
                    budget_scope_revision=1,
                    policy_hash="sha256:" + "4" * 64,
                    contract_hash="sha256:" + "5" * 64,
                    result_hash="sha256:" + "6" * 64,
                    replayed=False,
                )

        principal = Principal(
            principal_id="trusted-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({"project:1"}),
            authentication_source="test",
        )
        composition = SimpleNamespace(opening=OpeningApplication())
        app = FastAPI()
        app.include_router(
            create_router(
                ProductRouterContext(
                    app_settings=SimpleNamespace(),
                    models=product_model_map(),
                    services=SimpleNamespace(book_production=composition),
                )
            )
        )
        resolver = SimpleNamespace(resolve_api_principal=lambda **_values: principal)
        prefix = "/product/production/book-authority/opening-runs/opening:1"
        budget_policy = {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 40,
            "token_limit": 1_800_000,
            "cost_limit_usd": "20",
        }
        requests = (
            (
                "reconcile_legacy_budget_scope",
                "reconcile-legacy-budget-scope",
                {
                    "expected_opening_version": 0,
                    "expected_frozen_request_digest": "sha256:" + "a" * 64,
                    "idempotency_key": "legacy-budget",
                    "policy_contract_version": "book-opening-provider-budget.v1",
                    "policy_snapshot": budget_policy,
                    "policy_hash": canonical_budget_policy(budget_policy)[
                        "policy_hash"
                    ],
                    "currency": "USD",
                    "budget_timezone": "UTC",
                    "started_at": "2026-08-29T00:00:00Z",
                    "deadline_at": "2026-08-29T01:00:00Z",
                    "reason": "operator supplied bounded recovery budget",
                },
            ),
            (
                "reconcile_legacy_execution",
                "reconcile-legacy-execution",
                {"idempotency_key": "legacy"},
            ),
            (
                "assess_execution_loss",
                "assess-execution-loss",
                {"idempotency_key": "loss"},
            ),
            (
                "converge_execution_loss",
                "converge-execution-loss",
                {
                    "recovery_assessment_id": "assessment:loss",
                    "idempotency_key": "loss",
                },
            ),
            ("assess_recovery", "assess-recovery", {"idempotency_key": "recovery"}),
            (
                "recover",
                "recover",
                {
                    "recovery_assessment_id": "assessment:recovery",
                    "idempotency_key": "recovery",
                    "reason": "operator authorized recovery",
                },
            ),
            (
                "assess_checkpoint_reconciliation",
                "assess-checkpoint-reconciliation",
                {
                    "idempotency_key": "checkpoint-assessment",
                    "semantic_work_key": "planning-generation:1",
                    "owning_authority": "STORY_PLANNING",
                    "evidence_type": "PLANNING_GENERATION",
                    "evidence_id": "generation:1",
                    "evidence_version": 1,
                    "evidence_hash": "sha256:" + "3" * 64,
                },
            ),
            (
                "reconcile_checkpoint",
                "reconcile-checkpoint",
                {
                    "recovery_assessment_id": "assessment:checkpoint",
                    "idempotency_key": "checkpoint-reconcile",
                },
            ),
        )
        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=resolver,
            ),
            TestClient(app) as client,
        ):
            for expected_call, path, payload in requests:
                response = client.post(
                    f"{prefix}/{path}",
                    json={**payload, "actor_id": "untrusted-caller"},
                )
                self.assertEqual(response.status_code, 202, response.text)
                self.assertEqual(calls[-1][0], expected_call)
                self.assertIs(calls[-1][2]["principal"], principal)

    def test_builder_reuses_one_dependency_graph(self) -> None:
        from novel_forge.api.authority_dependencies import (
            build_book_production_composition,
        )

        principal = Principal(
            principal_id="book-worker",
            principal_type=PrincipalType.WORKER,
            permissions=frozenset({"*"}),
            project_scope=frozenset({"*"}),
            authentication_source="test",
        )
        chapter = SimpleNamespace()
        followup = SimpleNamespace()
        book = SimpleNamespace(
            database_url="postgresql://authority",
            application_build_id="build-1",
            commit_sha="a" * 40,
            followup=followup,
        )
        planning_authority = SimpleNamespace()
        story_design = SimpleNamespace()
        planning = SimpleNamespace(
            planning=planning_authority,
            story_design=story_design,
            database_url="postgresql://authority",
        )
        preparation = SimpleNamespace()
        projection_repair = SimpleNamespace()

        book_design = SimpleNamespace()
        execution = SimpleNamespace(
            cost_accounting_basis="PRICED",
            account_authorization_ref="",
        )
        with (
            patch("novel_forge.api.authority_dependencies.build_book_design_authority_application", return_value=book_design) as build_book_design,
            patch(
                "novel_forge.api.authority_dependencies.build_book_authority_application",
                return_value=book,
            ),
            patch(
                "novel_forge.api.authority_dependencies.build_story_planning_generation_application",
                return_value=planning,
            ),
            patch(
                "novel_forge.api.authority_dependencies.build_production_preparation_service",
                return_value=preparation,
            ),
            patch(
                "novel_forge.api.authority_dependencies.PostgresBookProjectionRepairAuthority",
                return_value=projection_repair,
            ),
        ):
            composition = build_book_production_composition(
                IndustrialSettings(
                    root=Path("."), database_url="postgresql://authority"
                ),
                env={
                    "NOVEL_FORGE_APPLICATION_BUILD_ID": "build-1",
                    "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                },
                principal=principal,
                execution=execution,
                chapter_application=chapter,
            )

        build_book_design.assert_called_once()
        self.assertIs(composition.formation.generation.book_design, book_design)
        self.assertIs(composition.authority, book)
        self.assertIs(composition.planning, planning)
        self.assertIs(composition.production_preparation, preparation)
        self.assertIs(composition.projection_repair, projection_repair)
        self.assertIs(composition.followup, followup)
        self.assertIs(composition.chapter_groups.book, book)
        self.assertIs(composition.plan_change.story_design, story_design)
        self.assertIs(composition.plan_change.planning, planning_authority)
        self.assertIs(composition.replan.book, book)
        self.assertIs(composition.replan.planning, planning)
        self.assertEqual(
            composition.corrective_actions.database_url, "postgresql://authority"
        )
        self.assertIs(composition.supervisor.authority, book)
        self.assertIs(composition.supervisor.query, composition.query)
        self.assertIs(composition.supervisor.scheduler.query, composition.query)
        self.assertIs(composition.supervisor.chapter_groups, composition.chapter_groups)
        self.assertIs(composition.supervisor.production_preparation, preparation)
        self.assertEqual(
            composition.opening.provider_budget_policy,
            {
                "execution_mode": "PROVIDER_ALLOWED",
                "provider_call_limit": 48,
                "token_limit": 4_800_000,
                "cost_limit_usd": "96",
                "per_call_token_limit": 100_000,
                "per_call_cost_limit_usd": "2",
            },
        )

    def test_tick_has_one_canonical_supervisor_path(self) -> None:
        from novel_forge.modules.book_authority.composition import (
            BookProductionComposition,
        )

        calls: list[tuple[str, str]] = []
        supervisor = SimpleNamespace(
            tick=lambda book_run_id: (
                calls.append(("supervisor", book_run_id)) or "supervisor-tick"
            ),
        )
        composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=SimpleNamespace(),
            corrective_actions=SimpleNamespace(),
            supervisor=supervisor,
            principal=Principal(
                principal_id="trusted-operator",
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"book.authority.approve_replan"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert composition.query is not None

        self.assertEqual(composition.tick("book-run:1"), "supervisor-tick")
        self.assertEqual(calls, [("supervisor", "book-run:1")])

    def test_formal_replan_approval_is_scoped_to_the_book_run(self) -> None:
        from novel_forge.modules.book_authority.composition import (
            BookProductionComposition,
        )
        from novel_forge.modules.command_kernel.errors import KernelError

        approvals: list[tuple[str, str, str, dict[str, object]]] = []
        replan = SimpleNamespace(
            require=lambda _replan_id: {
                "book_run_id": "book-run:1",
                "project_id": "project:1",
            },
            approve=lambda replan_id, **values: (
                approvals.append(
                    (
                        replan_id,
                        values["authority_type"],
                        values["authority_version"],
                        values["evidence"],
                    )
                )
                or {"replan_id": replan_id, "status": "ACTIVE"}
            ),
        )
        composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=replan,
            corrective_actions=SimpleNamespace(),
            supervisor=SimpleNamespace(),
            principal=Principal(
                principal_id="trusted-operator",
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"book.authority.approve_replan"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert composition.query is not None

        result = composition.approve_replan(
            book_run_id="book-run:1",
            replan_id="replan:1",
            authority_type="PLAN_CHANGE_AUTHORITY",
            authority_version="operator-approval-v1",
            evidence={"operator_approved": True},
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(len(approvals), 1)
        with self.assertRaises(KernelError) as raised:
            composition.approve_replan(
                book_run_id="book-run:other",
                replan_id="replan:1",
                authority_type="PLAN_CHANGE_AUTHORITY",
                authority_version="operator-approval-v1",
                evidence={"operator_approved": True},
            )
        self.assertEqual(raised.exception.code, "BOOK_REPLAN_SCOPE_MISMATCH")

        worker_composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=replan,
            corrective_actions=SimpleNamespace(),
            supervisor=SimpleNamespace(),
            principal=Principal(
                principal_id="book-worker",
                principal_type=PrincipalType.WORKER,
                permissions=frozenset({"book.authority.execute"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert worker_composition.query is not None
        with self.assertRaises(PermissionError):
            worker_composition.approve_replan(
                book_run_id="book-run:1",
                replan_id="replan:1",
                authority_type="PLAN_CHANGE_AUTHORITY",
                authority_version="worker-forbidden-v1",
                evidence={},
            )

    def test_authority_api_is_the_only_replan_approval_entrypoint(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from novel_forge.api.models import product_model_map
        from novel_forge.api.routers.book_authority import create_router
        from novel_forge.api.routers.context import ProductRouterContext

        approvals: list[dict[str, object]] = []
        composition = SimpleNamespace(
            authority=SimpleNamespace(
                require=lambda _book_run_id: {"project_id": "project:1"}
            ),
            approve_replan=lambda **values: (
                approvals.append(values)
                or {"replan_id": values["replan_id"], "status": "ACTIVE"}
            ),
        )
        principal = Principal(
            principal_id="trusted-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.authority.approve_replan",
                }
            ),
            project_scope=frozenset({"project:1"}),
            authentication_source="test",
        )
        resolver = SimpleNamespace(resolve_api_principal=lambda **_values: principal)
        app = FastAPI()
        app.include_router(
            create_router(
                ProductRouterContext(
                    app_settings=SimpleNamespace(),
                    models=product_model_map(),
                    services=SimpleNamespace(book_production=composition),
                )
            )
        )

        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=resolver,
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/product/production/book-authority/runs/book-run:1/"
                "replans/replan:1/approve",
                json={
                    "authority_type": "PLAN_CHANGE_AUTHORITY",
                    "authority_version": "operator-approval-v1",
                    "evidence": {"operator_approved": True},
                    "actor_id": "untrusted-caller",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ACTIVE")
        self.assertEqual(
            approvals,
            [
                {
                    "book_run_id": "book-run:1",
                    "replan_id": "replan:1",
                    "authority_type": "PLAN_CHANGE_AUTHORITY",
                    "authority_version": "operator-approval-v1",
                    "evidence": {"operator_approved": True},
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
