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
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


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
