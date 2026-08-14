from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_forge.api.authority_dependencies import (
    build_narrative_semantic_evaluation_execution_port,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
    BookDesignSemanticEvaluationCommand,
)
from novel_forge.modules.story_design_authority import (
    required_qualification_profiles,
    scripted_qualification,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.maintenance import scan_expired_attempt_leases
from novel_forge.modules.provider_control import (
    OpenAIProviderAdapterV2,
    ProviderAdapterRegistry,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    build_narrative_evaluation_pack_profile,
)
from novel_forge.modules.story_design_authority import (
    NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
    narrative_semantic_evaluation_definition,
)
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
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)


class _MeasuredSemanticEvaluationTransport:
    def __init__(self) -> None:
        self.calls = 0
        self.idempotency_keys: set[str] = set()

    def execute(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.idempotency_keys.add(request.stable_idempotency_key)
        if request.stage != "narrative_semantic_evaluation":
            raise AssertionError("proof transport accepts only semantic evaluation")
        return {
            "outcome": "success",
            "request_sent": True,
            "provider_request_id": f"provider-request:{request.stable_idempotency_key}",
            "completion_mode": "synchronous",
            "evidence": {
                "result": scripted_qualification("book_design.propose"),
                "usage": {"input_tokens": 200, "output_tokens": 80},
                "cost": {"amount": "0.01", "currency": "USD"},
                "request_hash": request.request_hash,
            },
        }

    def query(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("synchronous proof must not query")

    def cancel(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("completed proof must not cancel")

    def verify_callback(self, body, headers, *, secret):  # type: ignore[no-untyped-def]
        raise AssertionError("synchronous proof has no callback")


class _SemanticEvaluatorProcessCrash(BaseException):
    """Test-only process boundary that bypasses in-process failure handling."""


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
                    "narrative_design.evaluate",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.evaluator_principal = Principal(
            principal_id="book-design-independent-evaluator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"narrative_design.evaluate"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test-evaluator-configuration",
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
            allow_scripted_evaluation_fixture=True,
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
        self.assertEqual(first["status"], "EVALUATION_PENDING")
        first_evaluation = self._evaluate(first)
        self.assertEqual(first_evaluation["status"], "VALIDATED")
        self.assertNotEqual(
            first_evaluation["generation_operation_id"],
            first_evaluation["evaluation_operation_id"],
        )
        self.assertTrue(first_evaluation["evaluation_attempt_id"])
        contradictory = scripted_qualification("book_design.propose")
        contradictory["evaluations"][0]["criteria"][0].update(
            {
                "verdict": "FAIL",
                "rationale": "Independent review found a contradictory premise.",
                "repair_directive": "Repair the premise before reevaluation.",
            }
        )
        with self.assertRaisesRegex(
            KernelError, "NARRATIVE_EVALUATION_CANDIDATE_NOT_PENDING"
        ):
            self._evaluate(
                first,
                evaluation=contradictory,
                idempotency_suffix="contradictory",
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
        self._evaluate(second)
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
        evaluation = scripted_qualification("book_design.propose")
        criterion = evaluation["evaluations"][0]["criteria"][0]
        criterion.update(
            verdict="FAIL",
            repair_directive="rebuild the premise around one reachable ending",
        )

        candidate = self._book_command(
            "book_design.propose",
            payload=design,
            idempotency_key=f"design:rejected:{self.book_id}",
            expected_book_version=1,
        )
        rejected = self._evaluate(candidate, evaluation=evaluation)

        self.assertEqual(rejected["status"], "REJECTED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.status, version.eligibility,
                       qualification.qualification_status,
                       qualification.trust_boundary,
                       qualification.generation_operation_id,
                       qualification.evaluation_operation_id,
                       qualification.evaluation_attempt_id
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
                (
                    "REJECTED",
                    "INELIGIBLE",
                    "FAIL",
                    "INDEPENDENT",
                    candidate["operation_id"],
                    rejected["evaluation_operation_id"],
                    rejected["evaluation_attempt_id"],
                ),
            )

    def test_real_provider_evaluator_records_independent_receipt_and_replays_once(
        self,
    ) -> None:
        self._book_command(
            "book.create",
            payload={
                "schema_version": "book-authority.v1",
                "title": "Provider Evaluation Proof",
                "production_profile": {},
                "runtime_policy": {"execution_fallback": "FAIL_CLOSED"},
                "release_identity": "book-design-provider-proof@" + "b" * 40,
            },
            idempotency_key=f"book:create:{self.book_id}",
        )
        candidate = self._book_command(
            "book_design.propose",
            payload=self._design("independent provider evaluation"),
            idempotency_key=f"design:provider:{self.book_id}",
            expected_book_version=1,
        )
        transport = _MeasuredSemanticEvaluationTransport()
        registry = ProviderAdapterRegistry()
        registry.register(
            OpenAIProviderAdapterV2(
                transport,
                supports_query=False,
                supports_cancel=False,
                supports_callback=False,
                supports_cost_receipt=True,
                provider_idempotency_supported=True,
            )
        )
        harness = CapabilityPackPostgresHarness(
            "semantic-provider-proof",
            application_build_id=NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
            release_sha="b" * 40,
        )
        harness.project_id = self.project_id
        harness.workspace_id = self.workspace_id
        harness.book_ids = (self.book_id,)
        harness.compiler = harness.principal("compiler", *harness.compiler.permissions)
        harness.approver = harness.principal("approver", *harness.approver.permissions)
        harness.agent_admin = harness.principal(
            "agent-admin", *harness.agent_admin.permissions
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            registered = uow.repositories.definitions.register(
                narrative_semantic_evaluation_definition(
                    application_build_id=NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
                    commit_sha="b" * 40,
                )
            )
            uow.commit()
        profile = build_narrative_evaluation_pack_profile(
            Path(__file__).resolve().parents[2],
            operation_definition_hash=str(registered["definition_hash"]),
            pack_id=harness.pack_id,
        )
        harness._base_manifest = profile.manifest
        harness._base_catalog = profile.artifact_catalog
        harness.workflow_definition_ref = profile.workflow_ref
        pack = harness.register_compile_approve(
            "1.0.0",
            generation=1,
            approval_scope=harness.approval_scope(
                project_ids=(self.project_id,),
                workspace_ids=(self.workspace_id,),
                book_ids=(self.book_id,),
            ),
            proof_skill_ref=profile.agent_skill_ref,
            release_sha="b" * 40,
        )
        deployment = harness.deploy(
            pack,
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
        )
        harness.activate(deployment)
        injected = {"done": False}

        def fail_once(checkpoint: str) -> None:
            if checkpoint == "after_provider_success" and not injected["done"]:
                injected["done"] = True
                raise _SemanticEvaluatorProcessCrash(checkpoint)

        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(__file__).resolve().parents[2],
                database_url=DATABASE_URL,
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "development",
                "NOVEL_FORGE_MODEL_PROVIDER": "openai",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "openai",
                "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "gpt-proof",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                    Path(directory) / "objects"
                ),
                "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "1.00",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "semantic-provider-proof",
                "NOVEL_FORGE_COMMIT_SHA": "b" * 40,
                "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID": (
                    harness.pack_id
                ),
            }
            execution = build_production_execution_composition(
                settings, provider_registry=registry, env=env
            )
            semantic_port = build_narrative_semantic_evaluation_execution_port(
                settings,
                execution=execution,
                env=env,
                post_provider_fault_injector=fail_once,
            )
            provider_application = BookDesignAuthorityApplication(
                DATABASE_URL,
                application_build_id="book-design-provider-proof",
                commit_sha="b" * 40,
                semantic_evaluation_execution_port=semantic_port,
                narrative_evaluator_principal=self.evaluator_principal,
            )
            command = BookDesignSemanticEvaluationCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.evaluator_principal.principal_id,
                candidate_asset_version_id=candidate["asset_version_id"],
                generation_operation_id=candidate["operation_id"],
                generator_operation_name="book_design.propose",
                candidate_content_hash=candidate["content_hash"],
                evaluator_execution_class="MODEL_PROVIDER",
                idempotency_key=f"semantic-provider:{candidate['asset_version_id']}",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
            )
            wrong_actor = BookDesignSemanticEvaluationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=self.principal.principal_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                generator_operation_name=command.generator_operation_name,
                candidate_content_hash=command.candidate_content_hash,
                evaluator_execution_class="MODEL_PROVIDER",
                idempotency_key=command.idempotency_key + ":wrong-actor",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            with self.assertRaisesRegex(
                KernelError, "NARRATIVE_EVALUATION_ACTOR_NOT_INDEPENDENT"
            ):
                provider_application.evaluate_semantics(
                    wrong_actor, principal=self.principal
                )
            with self.assertRaises(_SemanticEvaluatorProcessCrash):
                provider_application.evaluate_semantics(
                    command, principal=self.evaluator_principal
                )
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT operation.operation_id, attempt.attempt_id
                    FROM authority_operation AS operation
                    JOIN authority_attempt AS attempt
                      ON attempt.operation_id=operation.operation_id
                    WHERE operation.project_id=%s
                      AND operation.idempotency_key=%s
                    """,
                    [self.project_id, command.idempotency_key],
                )
                crashed_operation_id, crashed_attempt_id = uow.cursor.fetchone()
                uow.cursor.execute(
                    """
                    UPDATE authority_lease_acquisition
                    SET expires_at=acquired_at + INTERVAL '1 microsecond'
                    WHERE attempt_id=%s AND status='HELD'
                    """,
                    [crashed_attempt_id],
                )
                uow.commit()
            expired = scan_expired_attempt_leases(
                DATABASE_URL, actor_id="semantic-evaluation-recovery-test"
            )
            self.assertTrue(
                any(item["attempt_id"] == crashed_attempt_id for item in expired)
            )
            competing_claim = BookDesignSemanticEvaluationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=command.actor_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                generator_operation_name=command.generator_operation_name,
                candidate_content_hash=command.candidate_content_hash,
                evaluator_execution_class="MODEL_PROVIDER",
                idempotency_key=command.idempotency_key + ":competing-claim",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            first = provider_application.evaluate_semantics(
                competing_claim, principal=self.evaluator_principal
            )
            replay = provider_application.evaluate_semantics(
                command, principal=self.evaluator_principal
            )
            stale = BookDesignSemanticEvaluationCommand(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                actor_id=command.actor_id,
                candidate_asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                generator_operation_name=command.generator_operation_name,
                candidate_content_hash=command.candidate_content_hash,
                evaluator_execution_class="MODEL_PROVIDER",
                idempotency_key=command.idempotency_key + ":stale",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            with self.assertRaisesRegex(
                KernelError, "NARRATIVE_EVALUATION_CANDIDATE_NOT_PENDING"
            ):
                provider_application.evaluate_semantics(
                    stale, principal=self.evaluator_principal
                )

        self.assertEqual(
            first["evaluation_operation_id"], replay["evaluation_operation_id"]
        )
        self.assertEqual(transport.calls, 1)
        self.assertEqual(len(transport.idempotency_keys), 1)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_attempt WHERE operation_id=%s",
                [crashed_operation_id],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 1)
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name='story_design.semantic_evaluate'
                  AND concurrency_key=%s
                """,
                [
                    self.project_id,
                    f"book:{self.book_id}:evaluation:{candidate['asset_version_id']}",
                ],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 1)
            uow.cursor.execute(
                """
                SELECT qualification.provider_model_call_asset_version_id,
                       qualification.provider_model_call_content_hash,
                       qualification.provider_evidence_hash,
                       qualification.provider_result_hash,
                       qualification.provider_route_snapshot_id,
                       generation.actor_id, evaluation.actor_id,
                       qualification.evaluation_operation_id,
                       qualification.evaluation_attempt_id
                FROM authority_narrative_design_qualification AS qualification
                JOIN authority_operation AS generation
                  ON generation.operation_id=qualification.generation_operation_id
                JOIN authority_operation AS evaluation
                  ON evaluation.operation_id=qualification.evaluation_operation_id
                WHERE qualification.project_id=%s
                  AND qualification.asset_version_id=%s
                  AND qualification.evaluator_execution_class='MODEL_PROVIDER'
                """,
                [self.project_id, candidate["asset_version_id"]],
            )
            rows = uow.cursor.fetchall()
            qualification_id = str(
                uow.cursor.execute(
                    """
                    SELECT qualification_id
                    FROM authority_narrative_design_qualification
                    WHERE project_id=%s AND asset_version_id=%s
                      AND evaluator_execution_class='MODEL_PROVIDER'
                    ORDER BY qualification_id
                    LIMIT 1
                    """,
                    [self.project_id, candidate["asset_version_id"]],
                ).fetchone()[0]
            )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(str(row[0]) for row in rows))
        self.assertTrue(all(str(row[1]).startswith("sha256:") for row in rows))
        self.assertTrue(all(str(row[2]).startswith("sha256:") for row in rows))
        self.assertTrue(all(str(row[3]).startswith("sha256:") for row in rows))
        self.assertTrue(all(str(row[4]) for row in rows))
        self.assertTrue(all(row[5] != row[6] for row in rows))
        self.assertTrue(
            all(str(row[7]) == first["evaluation_operation_id"] for row in rows)
        )
        self.assertTrue(
            all(str(row[8]) == first["evaluation_attempt_id"] for row in rows)
        )
        provider_application._require_model_provider_qualification(
            project_id=self.project_id,
            book_id=self.book_id,
            asset_version_id=candidate["asset_version_id"],
        )
        profiles = required_qualification_profiles("book_design.propose")
        with (
            patch(
                "novel_forge.modules.book_design_authority.application.required_qualification_profiles",
                return_value=(
                    replace(profiles[0], profile_version="stale-profile-version"),
                    *profiles[1:],
                ),
            ),
            self.assertRaisesRegex(
                KernelError, "NARRATIVE_EVALUATION_QUALIFICATION_STALE"
            ),
        ):
            provider_application._require_model_provider_qualification(
                project_id=self.project_id,
                book_id=self.book_id,
                asset_version_id=candidate["asset_version_id"],
            )
        with self.assertRaisesRegex(
            Exception,
            "Provider lineage does not match exact ModelCallLog",
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as forged_uow:
                forged_uow.cursor.execute(
                    """
                    INSERT INTO authority_narrative_design_qualification(
                        qualification_id, project_id, book_id,
                        asset_version_id, source_operation_id,
                        candidate_content_hash, design_layer, profile_id,
                        profile_version, profile_hash, capability_id, skill_ref,
                        evaluator_execution_class, qualification_status,
                        evaluation, evaluation_hash, qualification_hash,
                        generation_operation_id, evaluation_operation_id,
                        evaluation_attempt_id, evaluation_asset_version_id,
                        evaluation_evidence_hash, trust_boundary,
                        provider_model_call_asset_version_id,
                        provider_model_call_content_hash,
                        provider_evidence_hash, provider_result_hash,
                        provider_route_snapshot_id
                    )
                    SELECT qualification_id || ':forged', project_id, book_id,
                           asset_version_id, source_operation_id,
                           candidate_content_hash, design_layer, profile_id,
                           profile_version, profile_hash, capability_id, skill_ref,
                           evaluator_execution_class, qualification_status,
                           evaluation, 'sha256:' || repeat('f', 64),
                           'sha256:' || repeat('e', 64),
                           generation_operation_id, evaluation_operation_id,
                           evaluation_attempt_id, evaluation_asset_version_id,
                           evaluation_evidence_hash, trust_boundary,
                           provider_model_call_asset_version_id,
                           'sha256:' || repeat('d', 64),
                           provider_evidence_hash, provider_result_hash,
                           provider_route_snapshot_id
                    FROM authority_narrative_design_qualification
                    WHERE qualification_id=%s
                    """,
                    [qualification_id],
                )
        with self.assertRaisesRegex(
            Exception,
            "Provider lineage does not match exact ModelCallLog",
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as forged_uow:
                forged_uow.cursor.execute(
                    """
                    INSERT INTO authority_narrative_design_qualification(
                        qualification_id, project_id, book_id,
                        asset_version_id, source_operation_id,
                        candidate_content_hash, design_layer, profile_id,
                        profile_version, profile_hash, capability_id, skill_ref,
                        evaluator_execution_class, qualification_status,
                        evaluation, evaluation_hash, qualification_hash,
                        generation_operation_id, evaluation_operation_id,
                        evaluation_attempt_id, evaluation_asset_version_id,
                        evaluation_evidence_hash, trust_boundary,
                        provider_model_call_asset_version_id,
                        provider_model_call_content_hash,
                        provider_evidence_hash, provider_result_hash,
                        provider_route_snapshot_id
                    )
                    SELECT qualification_id || ':forged-verdict',
                           project_id, book_id, asset_version_id,
                           source_operation_id, candidate_content_hash,
                           design_layer, profile_id, profile_version,
                           profile_hash, capability_id, skill_ref,
                           evaluator_execution_class, 'PASS',
                           jsonb_set(
                               evaluation,
                               '{criteria,0,verdict}',
                               '"FAIL"'::jsonb
                           ),
                           authority_sha256_jsonb(
                               jsonb_set(
                                   evaluation,
                                   '{criteria,0,verdict}',
                                   '"FAIL"'::jsonb
                               )
                           ),
                           qualification_hash, generation_operation_id,
                           evaluation_operation_id, evaluation_attempt_id,
                           evaluation_asset_version_id,
                           evaluation_evidence_hash, trust_boundary,
                           provider_model_call_asset_version_id,
                           provider_model_call_content_hash,
                           provider_evidence_hash, provider_result_hash,
                           provider_route_snapshot_id
                    FROM authority_narrative_design_qualification
                    WHERE qualification_id=%s
                    """,
                    [qualification_id],
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
            allow_scripted_evaluation_fixture=True,
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

    def _evaluate(
        self,
        candidate: dict,
        *,
        evaluation: dict | None = None,
        idempotency_suffix: str = "primary",
    ) -> dict:
        return self.application.evaluate_semantics(
            BookDesignSemanticEvaluationCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.evaluator_principal.principal_id,
                candidate_asset_version_id=candidate["asset_version_id"],
                generation_operation_id=candidate["operation_id"],
                generator_operation_name="book_design.propose",
                candidate_content_hash=candidate["content_hash"],
                evaluator_execution_class="SCRIPTED_FIXTURE",
                evaluation=evaluation or scripted_qualification("book_design.propose"),
                idempotency_key=(
                    f"design:evaluate:{candidate['asset_version_id']}:{idempotency_suffix}"
                ),
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
            ),
            principal=self.evaluator_principal,
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
        }


if __name__ == "__main__":
    unittest.main()
