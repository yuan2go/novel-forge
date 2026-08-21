from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from psycopg.types.json import Jsonb

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.context_builder.embedding_projection import (
    RetrievalEmbeddingProjectionRuntime,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


class _RecoverableEmbeddingAdapter:
    provider = "recoverable_embedding_fixture"
    reconciliation_mode = "query"
    capability_profile = {
        "provider": provider,
        "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": True,
        "supports_cancel": True,
        "supports_callback": False,
        "supports_usage_receipt": False,
        "supports_cost_receipt": False,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(
        self,
        *,
        execute_outcomes: tuple[str, ...],
        query_outcomes: tuple[str, ...] = (),
    ) -> None:
        self.execute_outcomes = list(execute_outcomes)
        self.query_outcomes = list(query_outcomes)
        self.execute_calls = 0
        self.query_calls = 0
        self.recovery_authorizations = 0

    def provider_id_for_stage(self, _stage: str) -> str:
        return self.provider

    def model_id_for_stage(self, _stage: str) -> str:
        return "fixture-embedding-recovery-v1"

    def for_recovery(self, **_kwargs: object) -> "_RecoverableEmbeddingAdapter":
        self.recovery_authorizations += 1
        return self

    def record_authorization(self) -> None:
        return None

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, object],
    ) -> ProviderResult:
        del capability, request_payload
        self.execute_calls += 1
        outcome = self.execute_outcomes.pop(0)
        if outcome == "success":
            evidence = self._success_evidence()
        else:
            evidence = {
                "failure_code": "AMBIGUOUS_PROVIDER_RESULT",
                "failure_message": "provider result could not be observed",
            }
        return ProviderResult(
            outcome,
            f"fixture-execute:{stable_idempotency_key}",
            evidence,
            provider_request_id=f"provider-request:{stable_idempotency_key}",
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, object],
    ) -> ProviderResult:
        del capability, request_payload
        self.query_calls += 1
        outcome = self.query_outcomes.pop(0)
        evidence = (
            self._success_evidence()
            if outcome == "success"
            else {"provider_query_outcome": outcome}
        )
        return ProviderResult(
            outcome,
            f"fixture-query:{stable_idempotency_key}",
            evidence,
            provider_request_id=f"provider-request:{stable_idempotency_key}",
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, object],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        return ProviderResult(
            "cancelled",
            provider_request_id or f"fixture-cancel:{stable_idempotency_key}",
            {"cancelled": True},
        )

    @staticmethod
    def _success_evidence() -> dict[str, object]:
        return {
            "result": {
                "vectors": [[0.1, 0.2, 0.3]],
                "embedding_dimensions": 3,
                "embedding_model": "fixture-embedding-recovery-v1",
            },
            "provider_id": "recoverable_embedding_fixture",
            "model_id": "fixture-embedding-recovery-v1",
            "prompt_version": "embedding-fixture-prompt-v1",
            "skill_version": "embedding-fixture-skill-v1",
            "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4},
            "cost": {"amount": "0", "currency": "USD"},
            "real_model_call": False,
            "production_execution": {
                "route_snapshot": {
                    "route_snapshot_id": "route-snapshot:embedding-recovery-fixture"
                }
            },
        }


class RetrievalEmbeddingProjectionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_document_embedding_uses_operation_external_effect_and_receipt(
        self,
    ) -> None:
        class SimulatedWorkerCrash(BaseException):
            pass

        crash = {"armed": True}

        def fault(checkpoint: str) -> None:
            if checkpoint == "after_provider_success" and crash["armed"]:
                crash["armed"] = False
                raise SimulatedWorkerCrash

        project_id = identifier("embedding-project")
        book_id = f"book:{project_id}"
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(
            project_id=project_id,
            book_id=book_id,
            workspace_id=workspace_id,
        )
        definition_name = identifier("embedding-source-definition")
        operation_id = identifier("embedding-source-operation")
        source_version_id = identifier("embedding-source-version")
        source_content = {
            "chapter": 1,
            "text": "The accepted red key promise changes Mei and Ren's trust.",
        }
        source_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    source_content, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        document_id = identifier("retrieval-document")
        document = {
            "retrieval_document_id": document_id,
            "project_id": project_id,
            "book_id": book_id,
            "source_asset_version_id": source_version_id,
            "source_artifact_type": "best_draft_candidate",
            "accepted_from_chapter": 1,
            "memory_layer": "L0",
            "content_text": source_content["text"],
            "metadata": {"projection_kind": "recent_accepted_prose"},
        }
        projection_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="SUCCEEDED",
            )
            cursor.execute(
                "UPDATE authority_operation SET workspace_id=%s WHERE operation_id=%s",
                [workspace_id, operation_id],
            )
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [f"asset:{source_version_id}", project_id, "best_draft_candidate"],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'draft.v1')
                """,
                [
                    source_version_id,
                    f"asset:{source_version_id}",
                    Jsonb(source_content),
                    source_hash,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_narrative_retrieval_document(
                    retrieval_document_id,project_id,book_id,
                    source_asset_version_id,source_artifact_type,
                    accepted_from_chapter,memory_layer,content_text,
                    metadata,projection_hash,created_by_operation_id
                ) VALUES (%s,%s,%s,%s,'best_draft_candidate',1,'L0',%s,%s,%s,%s)
                """,
                [
                    document_id,
                    project_id,
                    book_id,
                    source_version_id,
                    source_content["text"],
                    Jsonb(document["metadata"]),
                    projection_hash,
                    operation_id,
                ],
            )
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory),
                environment="test",
                storage_authority="postgresql",
                database_url=DATABASE_URL,
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_EMBEDDING_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_EMBEDDING_MODEL": "scripted-embedding-v1",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                    Path(directory) / "objects"
                ),
            }
            execution = build_production_execution_composition(settings, env=env)
            application = build_chapter_authority_application(
                settings,
                execution=execution,
                env=env,
                runtime_fault_injector=fault,
            )
            runtime = application.embedding_projection_runtime
            self.assertIsNotNone(runtime)
            assert runtime is not None
            runtime.schedule_pending(limit=1000)
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation_id FROM authority_operation
                    WHERE project_id=%s
                      AND definition_name='narrative.retrieval.embedding.project'
                      AND command_payload->'payload'->>'retrieval_document_id'=%s
                    """,
                    [project_id, document_id],
                )
                target = str(cursor.fetchone()[0])
            with self.assertRaises(SimulatedWorkerCrash):
                runtime.tick(project_id=project_id, operation_id=target)
            # A real replacement worker can only take over after the old
            # process lease expires. Move the test clock boundary without
            # changing the Attempt or its ExternalEffect identity.
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_lease_acquisition
                    SET acquired_at=NOW()-INTERVAL '2 seconds',
                        heartbeat_at=NOW()-INTERVAL '2 seconds',
                        expires_at=NOW()-INTERVAL '1 second'
                    WHERE attempt_id=(
                        SELECT attempt_id FROM authority_attempt
                        WHERE operation_id=%s
                        ORDER BY attempt_number DESC LIMIT 1
                    ) AND status='HELD'
                    """,
                    [target],
                )
                self.assertEqual(cursor.rowcount, 1)
            tick = runtime.tick(project_id=project_id, operation_id=target)
            self.assertEqual(tick.status, "SUCCEEDED")
            replay = runtime.tick(project_id=project_id, operation_id=target)
            self.assertTrue(replay.replayed)
            self.assertEqual(runtime.schedule_pending(project_id=project_id), ())
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT projection.status,projection.embedding_model,
                       projection.embedding_dimensions,
                       projection.external_effect_id,projection.receipt_id,
                       operation.status,effect.status,effect.capability
                FROM authority_retrieval_embedding_projection AS projection
                JOIN authority_operation AS operation
                  ON operation.operation_id=projection.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.external_effect_id=projection.external_effect_id
                WHERE projection.retrieval_document_id=%s
                """,
                [document_id],
            )
            row = cursor.fetchone()
            cursor.execute(
                """
                SELECT saga.status, COUNT(effect.external_effect_id)
                FROM authority_saga AS saga
                JOIN authority_operation AS operation
                  ON operation.root_operation_id=saga.root_operation_id
                LEFT JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                 AND effect.capability='model.retrieval'
                WHERE operation.operation_id=%s
                GROUP BY saga.status
                """,
                [target],
            )
            saga = cursor.fetchone()
        self.assertEqual(row[0], "READY")
        self.assertEqual(row[1], "deterministic-fixture-embedding-v1")
        self.assertEqual(row[2], 8)
        self.assertTrue(row[3])
        self.assertTrue(row[4])
        self.assertEqual(row[5:8], ("SUCCEEDED", "SUCCEEDED", "model.retrieval"))
        self.assertEqual(saga, ("SUCCEEDED", 1))

    def test_unknown_effect_reconciles_without_blind_redispatch(self) -> None:
        cases = (
            (
                "receipt_found",
                ("unknown",),
                ("success",),
                ("SUCCEEDED", "READY", 1, 1, 1),
            ),
            (
                "confirmed_not_executed",
                ("unknown", "success"),
                ("not_found",),
                ("SUCCEEDED", "READY", 2, 1, 2),
            ),
            (
                "unresolved",
                ("unknown",),
                ("ambiguous", "ambiguous"),
                ("RECONCILIATION_REQUIRED", "RECONCILIATION_REQUIRED", 1, 2, 1),
            ),
        )
        for (
            label,
            execute_outcomes,
            query_outcomes,
            expected,
        ) in cases:
            with self.subTest(label=label):
                project_id, document_id = self._seed_document(label)
                adapter = _RecoverableEmbeddingAdapter(
                    execute_outcomes=execute_outcomes,
                    query_outcomes=query_outcomes,
                )
                runtime = self._runtime(adapter, worker_id=f"worker:{label}")
                scheduled = runtime.schedule_pending(project_id=project_id)
                self.assertEqual(len(scheduled), 1)
                operation_id = scheduled[0]
                with self.assertRaises(KernelError) as unknown:
                    runtime.tick(project_id=project_id, operation_id=operation_id)
                self.assertEqual(unknown.exception.code, "MODEL_EFFECT_OUTCOME_UNKNOWN")

                recovery = runtime.tick(
                    project_id=project_id,
                    operation_id=operation_id,
                )
                if label == "confirmed_not_executed":
                    self.assertEqual(recovery.status, "FAILED_RETRYABLE")
                    recovery = runtime.tick(
                        project_id=project_id,
                        operation_id=operation_id,
                    )
                elif label == "unresolved":
                    self.assertEqual(recovery.status, "RECONCILIATION_REQUIRED")
                    recovery = runtime.tick(
                        project_id=project_id,
                        operation_id=operation_id,
                    )
                self.assertEqual(recovery.status, expected[0])
                self.assertEqual(adapter.execute_calls, expected[2])
                self.assertEqual(adapter.query_calls, expected[3])
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT operation.status, projection.status,
                               COUNT(DISTINCT attempt.attempt_id),
                               COUNT(DISTINCT effect.external_effect_id),
                               COUNT(DISTINCT dispatch.dispatch_id)
                        FROM authority_operation AS operation
                        JOIN authority_retrieval_embedding_projection AS projection
                          ON projection.operation_id=operation.operation_id
                        LEFT JOIN authority_attempt AS attempt
                          ON attempt.operation_id=operation.operation_id
                        LEFT JOIN authority_external_effect AS effect
                          ON effect.operation_id=operation.operation_id
                        LEFT JOIN authority_external_effect_dispatch AS dispatch
                          ON dispatch.external_effect_id=effect.external_effect_id
                        WHERE operation.operation_id=%s
                        GROUP BY operation.status, projection.status
                        """,
                        [operation_id],
                    )
                    row = cursor.fetchone()
                self.assertEqual(row[0], expected[0])
                self.assertEqual(row[1], expected[1])
                self.assertEqual(row[2], expected[4])
                self.assertEqual(row[3], expected[4])
                self.assertEqual(row[4], expected[4])
                if label == "unresolved":
                    self.assertGreaterEqual(adapter.recovery_authorizations, 2)
                    self.assertEqual(runtime.schedule_pending(project_id=project_id), ())
                self.assertTrue(document_id)

    def test_retry_exhaustion_dead_letters_without_reusing_an_unknown_effect(
        self,
    ) -> None:
        project_id, _document_id = self._seed_document("retry-exhaustion")
        adapter = _RecoverableEmbeddingAdapter(
            execute_outcomes=(
                "retryable_failure",
                "retryable_failure",
                "retryable_failure",
            )
        )
        runtime = self._runtime(adapter, worker_id="worker:retry-exhaustion")
        operation_id = runtime.schedule_pending(project_id=project_id)[0]
        for _attempt_number in range(3):
            with self.assertRaises(KernelError) as failure:
                runtime.tick(project_id=project_id, operation_id=operation_id)
            self.assertTrue(failure.exception.code.startswith("MODEL_EFFECT_RETRYABLE_"))
        exhausted = runtime.tick(project_id=project_id, operation_id=operation_id)
        self.assertEqual(exhausted.status, "DEAD_LETTER")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, projection.status,
                       COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT effect.external_effect_id)
                FROM authority_operation AS operation
                JOIN authority_retrieval_embedding_projection AS projection
                  ON projection.operation_id=operation.operation_id
                LEFT JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                LEFT JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                GROUP BY operation.status, projection.status
                """,
                [operation_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("DEAD_LETTER", "DEAD_LETTER", 3, 3),
            )
        self.assertEqual(adapter.execute_calls, 3)

    def test_definitive_provider_failure_is_final_not_unknown(self) -> None:
        project_id, _document_id = self._seed_document("final-failure")
        adapter = _RecoverableEmbeddingAdapter(
            execute_outcomes=("final_failure",),
        )
        runtime = self._runtime(adapter, worker_id="worker:final-failure")
        operation_id = runtime.schedule_pending(project_id=project_id)[0]
        with self.assertRaises(KernelError) as failure:
            runtime.tick(project_id=project_id, operation_id=operation_id)
        self.assertTrue(failure.exception.code.startswith("MODEL_EFFECT_FINAL_"))
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, attempt.status, effect.status,
                       projection.status
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                JOIN authority_retrieval_embedding_projection AS projection
                  ON projection.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [operation_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("FAILED_FINAL", "FAILED_FINAL", "FAILED_FINAL", "FAILED_FINAL"),
            )
        self.assertEqual(adapter.execute_calls, 1)
        self.assertEqual(adapter.query_calls, 0)

    def test_cancellation_reconciles_the_existing_effect_before_terminalizing(
        self,
    ) -> None:
        project_id, _document_id = self._seed_document("cancelled")
        adapter = _RecoverableEmbeddingAdapter(
            execute_outcomes=("unknown",),
            query_outcomes=("cancelled",),
        )
        runtime = self._runtime(adapter, worker_id="worker:cancelled")
        operation_id = runtime.schedule_pending(project_id=project_id)[0]
        with self.assertRaises(KernelError):
            runtime.tick(project_id=project_id, operation_id=operation_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status,version,trace_id,correlation_id FROM authority_operation WHERE operation_id=%s",
                [operation_id],
            )
            status, version, trace_id, correlation_id = cursor.fetchone()
        transition_operation(
            DATABASE_URL,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=project_id,
                expected_version=int(version),
                expected_status=str(status),
                target_status="CANCELLATION_REQUESTED",
                actor_id="operator:test",
                reason="operator cancels unknown embedding projection",
                trace_id=str(trace_id),
                correlation_id=str(correlation_id),
                causation_id=operation_id,
            ),
        )
        cancelled = runtime.tick(project_id=project_id, operation_id=operation_id)
        self.assertEqual(cancelled.status, "CANCELLED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, attempt.status, effect.status,
                       projection.status, COUNT(dispatch.dispatch_id)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                JOIN authority_retrieval_embedding_projection AS projection
                  ON projection.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                GROUP BY operation.status, attempt.status, effect.status,
                         projection.status
                """,
                [operation_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("CANCELLED", "CANCELLED", "CANCELLED", "CANCELLED", 1),
            )
        self.assertEqual(adapter.execute_calls, 1)
        self.assertEqual(adapter.query_calls, 1)

    def test_stale_embedding_worker_cannot_rewrite_projection_state(self) -> None:
        project_id, _document_id = self._seed_document("stale-worker")
        adapter = _RecoverableEmbeddingAdapter(
            execute_outcomes=("unknown",),
            query_outcomes=("ambiguous",),
        )
        runtime = self._runtime(adapter, worker_id="worker:stale")
        operation_id = runtime.schedule_pending(project_id=project_id)[0]
        with self.assertRaises(KernelError):
            runtime.tick(project_id=project_id, operation_id=operation_id)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.attempt_id, lease.fencing_token,
                       operation.trace_id, operation.correlation_id
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id=attempt.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id=attempt.attempt_id
                WHERE attempt.operation_id=%s
                ORDER BY lease.fencing_token
                LIMIT 1
                """,
                [operation_id],
            )
            attempt_id, old_fence, trace_id, correlation_id = cursor.fetchone()
        runtime.tick(project_id=project_id, operation_id=operation_id)
        stale = WorkerLeaseCommand(
            attempt_id=str(attempt_id),
            project_id=project_id,
            worker_id="worker:stale",
            fencing_token=int(old_fence),
            trace_id=str(trace_id),
            correlation_id=str(correlation_id),
            causation_id=operation_id,
        )
        with self.assertRaises(KernelError) as rejected:
            runtime._persist_projection_status(
                project_id=project_id,
                operation_id=operation_id,
                status="FAILED_FINAL",
                evidence={"illegitimate_stale_write": True},
                worker=stale,
            )
        self.assertEqual(rejected.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, evidence ? 'illegitimate_stale_write'
                FROM authority_retrieval_embedding_projection
                WHERE operation_id=%s
                """,
                [operation_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("RECONCILIATION_REQUIRED", False),
            )

    @staticmethod
    def _runtime(
        adapter: _RecoverableEmbeddingAdapter,
        *,
        worker_id: str,
    ) -> RetrievalEmbeddingProjectionRuntime:
        provider = ExternalEffectChapterModelPort(
            DATABASE_URL,
            adapter=adapter,
            worker_id=worker_id,
            execution_binding_domain="retrieval_projection",
        )
        return RetrievalEmbeddingProjectionRuntime(
            DATABASE_URL,
            provider=provider,
            worker_id=worker_id,
            application_build_id="embedding-recovery-test",
            commit_sha="f" * 40,
        )

    @staticmethod
    def _seed_document(label: str) -> tuple[str, str]:
        project_id = identifier(f"embedding-recovery-{label}")
        book_id = f"book:{project_id}"
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(
            project_id=project_id,
            book_id=book_id,
            workspace_id=workspace_id,
        )
        definition_name = identifier("embedding-recovery-source-definition")
        operation_id = identifier("embedding-recovery-source-operation")
        source_version_id = identifier("embedding-recovery-source-version")
        content_text = f"Accepted semantic source for {label}."
        source_content = {"chapter": 1, "text": content_text}
        source_hash = "sha256:" + hashlib.sha256(
            json.dumps(source_content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        document_id = identifier("embedding-recovery-document")
        document = {
            "retrieval_document_id": document_id,
            "project_id": project_id,
            "book_id": book_id,
            "source_asset_version_id": source_version_id,
            "source_artifact_type": "best_draft_candidate",
            "accepted_from_chapter": 1,
            "memory_layer": "L0",
            "content_text": content_text,
            "metadata": {"projection_kind": "recent_accepted_prose"},
        }
        projection_hash = "sha256:" + hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="SUCCEEDED",
            )
            cursor.execute(
                "UPDATE authority_operation SET workspace_id=%s WHERE operation_id=%s",
                [workspace_id, operation_id],
            )
            cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)",
                [f"asset:{source_version_id}", project_id, "best_draft_candidate"],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'draft.v1')
                """,
                [
                    source_version_id,
                    f"asset:{source_version_id}",
                    Jsonb(source_content),
                    source_hash,
                ],
            )
            cursor.execute(
                """
                INSERT INTO authority_narrative_retrieval_document(
                    retrieval_document_id,project_id,book_id,
                    source_asset_version_id,source_artifact_type,
                    accepted_from_chapter,memory_layer,content_text,
                    metadata,projection_hash,created_by_operation_id
                ) VALUES (%s,%s,%s,%s,'best_draft_candidate',1,'L0',%s,%s,%s,%s)
                """,
                [
                    document_id,
                    project_id,
                    book_id,
                    source_version_id,
                    content_text,
                    Jsonb(document["metadata"]),
                    projection_hash,
                    operation_id,
                ],
            )
        return project_id, document_id
