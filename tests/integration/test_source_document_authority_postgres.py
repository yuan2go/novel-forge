from __future__ import annotations

import hashlib
import unittest
from dataclasses import asdict

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_authority import (
    CommitSourceTransformCommand,
    RegisterSourceDocumentCommand,
    SourceChunkCandidate,
    SourceAuthorityApplication,
    SourceAuthorityQuery,
    SourceAuthorityScheduler,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class SourceDocumentAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("source-authority-project")
        self.workspace_id = identifier("source-authority-workspace")
        self._create_project(self.project_id, self.workspace_id)
        self.application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-authority-integration",
            commit_sha="e" * 40,
        )
        self.query = SourceAuthorityQuery(DATABASE_URL)
        self.principal = Principal(
            principal_id="source-governance-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {"source.authority.execute", "source.authority.query"}
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def test_verified_blob_registers_one_replayable_source_without_raw_text(self) -> None:
        blob_id = self._insert_available_blob(
            self.project_id, "licensed source bytes".encode()
        )
        command = self._command(
            blob_id=blob_id,
            authorization="licensed",
            license_name="license-2026-01",
            copyright_boundary="analysis and abstraction only; no raw prose context",
        )

        result = self.application.execute(command, principal=self.principal)
        replay = self.application.execute(command, principal=self.principal)
        source = self.query.require_document(
            project_id=self.project_id,
            source_document_id=result["source_document_id"],
        )

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertFalse(result["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(
            (source["lifecycle"], source["eligibility"], source["governance"]),
            ("ACTIVE", "ELIGIBLE", "CLEAR"),
        )
        self.assertEqual(source["rights_authorization"], "licensed")
        self.assertFalse(
            source["content"]["source_policy"]["raw_source_text_in_postgresql"]
        )
        self.assertFalse(
            source["content"]["source_policy"][
                "raw_source_text_in_generation_context"
            ]
        )
        self.assertNotIn("text", source["content"])
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT reference.blob_id, reference.role, blob.status
                FROM authority_asset_version_blob_reference AS reference
                JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
                WHERE reference.asset_version_id = %s
                """,
                [result["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone(), (blob_id, "raw_source", "AVAILABLE"))
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_source_document
                WHERE project_id = %s AND source_content_hash = %s
                """,
                [self.project_id, source["source_content_hash"]],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_unknown_rights_quarantine_and_cross_project_blob_fail_closed(self) -> None:
        blob_id = self._insert_available_blob(
            self.project_id, "unknown rights bytes".encode()
        )
        result = self.application.execute(
            self._command(blob_id=blob_id, authorization="unknown"),
            principal=self.principal,
        )
        source = self.query.require_document(
            project_id=self.project_id,
            source_document_id=result["source_document_id"],
        )

        self.assertEqual(source["governance_status"], "NEEDS_REVIEW")
        self.assertEqual(
            (source["lifecycle"], source["eligibility"], source["governance"]),
            ("CANDIDATE", "PENDING_EVALUATION", "QUARANTINED"),
        )
        other_project = identifier("source-other-project")
        other_workspace = identifier("source-other-workspace")
        self._create_project(other_project, other_workspace)
        other_principal = Principal(
            principal_id="other-source-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"source.authority.execute"}),
            project_scope=frozenset({other_project}),
            authentication_source="integration-test",
        )
        with self.assertRaisesRegex(KernelError, "another project"):
            self.application.execute(
                RegisterSourceDocumentCommand(
                    **{
                        **asdict(
                            self._command(blob_id=blob_id, authorization="owned")
                        ),
                        "project_id": other_project,
                        "workspace_id": other_workspace,
                        "idempotency_key": f"source:{other_project}:{blob_id}",
                    }
                ),
                principal=other_principal,
            )

    def test_api_admission_is_worker_driven_and_database_recoverable(self) -> None:
        blob_id = self._insert_available_blob(
            self.project_id, "authority worker source".encode()
        )
        admitted = self.application.admit(
            self._command(blob_id=blob_id, authorization="owned"),
            principal=self.principal,
        )

        self.assertEqual(admitted["status"], "READY")
        self.assertEqual(
            self.query.list_documents(project_id=self.project_id), []
        )
        restarted_application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-authority-integration",
            commit_sha="e" * 40,
            worker_id="source-worker-after-api",
        )
        scheduler = SourceAuthorityScheduler(
            restarted_application,
            worker_id="source-worker-after-api",
            lease_seconds=30,
        )
        self.assertIn(
            (admitted["operation_id"], self.project_id),
            scheduler.pending_operations(),
        )

        result = scheduler.run_or_recover(
            operation_id=admitted["operation_id"],
            project_id=self.project_id,
        )

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["recovery_mode"], "fresh_attempt")
        self.assertEqual(
            len(self.query.list_documents(project_id=self.project_id)), 1
        )

    def test_expired_lease_replays_committed_output_without_duplicate_source(self) -> None:
        blob_id = self._insert_available_blob(
            self.project_id, "source output before worker crash".encode()
        )
        admitted = self.application.admit(
            self._command(blob_id=blob_id, authorization="owned"),
            principal=self.principal,
        )
        operation_id = str(admitted["operation_id"])
        attempt = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=self.project_id,
            max_attempts=2,
            trace_id=f"trace:{blob_id}",
            correlation_id=f"correlation:{blob_id}",
        )
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=self.project_id,
            trace_id=f"trace:{blob_id}",
            correlation_id=f"correlation:{blob_id}",
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=self.project_id,
            worker_id="crashed-source-worker",
            lease_seconds=30,
            trace_id=f"trace:{blob_id}",
            correlation_id=f"correlation:{blob_id}",
        )
        crashed_worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=self.project_id,
            worker_id="crashed-source-worker",
            fencing_token=int(lease["fencing_token"]),
            trace_id=f"trace:{blob_id}",
            correlation_id=f"correlation:{blob_id}",
            causation_id=operation_id,
        )
        start_attempt(DATABASE_URL, crashed_worker)
        self.application.execute_fenced(crashed_worker)
        with transaction() as connection:
            connection.cursor().execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at = NOW() - INTERVAL '2 seconds',
                    expires_at = NOW() - INTERVAL '1 second'
                WHERE attempt_id = %s AND status = 'HELD'
                """,
                [attempt_id],
            )

        restarted_application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-authority-integration",
            commit_sha="e" * 40,
            worker_id="restarted-source-worker",
        )
        result = SourceAuthorityScheduler(
            restarted_application,
            worker_id="restarted-source-worker",
            lease_seconds=30,
        ).run_or_recover(operation_id=operation_id, project_id=self.project_id)

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["recovery_mode"], "output_replay_takeover")
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_document WHERE project_id = %s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                """
                SELECT COUNT(*), MAX(fencing_token)
                FROM authority_lease_acquisition
                WHERE attempt_id = %s
                """,
                [attempt_id],
            )
            self.assertEqual(cursor.fetchone(), (2, 2))

    def test_transform_commits_verified_chunk_blobs_as_evidence_only_assets(self) -> None:
        source_blob_id = self._insert_available_blob(self.project_id, b"S" * 200)
        source = self.application.execute(
            self._command(blob_id=source_blob_id, authorization="owned"),
            principal=self.principal,
        )
        chunk_bytes = (b"normalized chunk zero", b"normalized chunk one")
        chunk_blob_ids = tuple(
            self._insert_available_blob(self.project_id, content)
            for content in chunk_bytes
        )
        chunks = tuple(
            SourceChunkCandidate(
                chunk_index=index,
                blob_id=chunk_blob_ids[index],
                content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                character_count=len(content.decode()),
                token_count=4,
                source_byte_start=index * 100,
                source_byte_end=(index + 1) * 100,
            )
            for index, content in enumerate(chunk_bytes)
        )
        command = CommitSourceTransformCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            source_document_id=source["source_document_id"],
            normalization_version="normalize-text:v1",
            chunking_version="fixed-evidence-spans:v1",
            chunking_policy_hash="sha256:" + hashlib.sha256(b"policy-v1").hexdigest(),
            chunks=chunks,
            actor_id="request-payload-actor",
            idempotency_key=f"transform:{source['asset_version_id']}",
            trace_id=f"trace:transform:{source_blob_id}",
            correlation_id=f"correlation:transform:{source_blob_id}",
        )

        admitted = self.application.admit_transform(
            command, principal=self.principal
        )
        result = SourceAuthorityScheduler(
            self.application,
            worker_id="source-transform-worker",
            lease_seconds=30,
        ).run_or_recover(
            operation_id=admitted["operation_id"], project_id=self.project_id
        )
        replay = self.application.admit_transform(command, principal=self.principal)
        transforms = self.query.list_transforms(
            project_id=self.project_id,
            source_document_id=source["source_document_id"],
        )
        stored_chunks = self.query.list_chunks(
            project_id=self.project_id,
            source_transform_id=result["source_transform_id"],
        )

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue(replay["duplicate"])
        self.assertEqual(len(transforms), 1)
        self.assertEqual(len(stored_chunks), 2)
        self.assertEqual(
            [
                (row["lifecycle"], row["eligibility"], row["governance"])
                for row in stored_chunks
            ],
            [("ACTIVE", "INELIGIBLE", "CLEAR")] * 2,
        )
        for row in stored_chunks:
            encoded = str(row["content"])
            self.assertNotIn("raw_text", encoded)
            self.assertNotIn("clean_text", encoded)
            self.assertFalse(
                row["content"]["source_policy"]["generation_context_allowed"]
            )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_source_chunk AS chunk
                JOIN authority_asset_version_blob_reference AS reference
                  ON reference.asset_version_id = chunk.asset_version_id
                JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
                WHERE chunk.source_transform_id = %s
                  AND reference.role = 'clean_source_chunk'
                  AND blob.status = 'AVAILABLE'
                """,
                [result["source_transform_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_transform_rejects_quarantined_source_and_cross_project_chunk(self) -> None:
        unknown_blob = self._insert_available_blob(self.project_id, b"U" * 100)
        unknown = self.application.execute(
            self._command(blob_id=unknown_blob, authorization="unknown"),
            principal=self.principal,
        )
        chunk_content = b"candidate chunk"
        chunk_blob = self._insert_available_blob(self.project_id, chunk_content)
        candidate = SourceChunkCandidate(
            chunk_index=0,
            blob_id=chunk_blob,
            content_hash="sha256:" + hashlib.sha256(chunk_content).hexdigest(),
            byte_size=len(chunk_content),
            character_count=len(chunk_content.decode()),
            token_count=2,
            source_byte_start=0,
            source_byte_end=100,
        )
        command = CommitSourceTransformCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            source_document_id=unknown["source_document_id"],
            normalization_version="normalize:v1",
            chunking_version="chunk:v1",
            chunking_policy_hash="sha256:" + "c" * 64,
            chunks=(candidate,),
            actor_id="operator",
            idempotency_key="quarantined-transform",
            trace_id="trace:quarantined-transform",
            correlation_id="correlation:quarantined-transform",
        )
        with self.assertRaises(KernelError) as quarantined:
            self.application.admit_transform(command, principal=self.principal)
        self.assertEqual(
            quarantined.exception.code, "SOURCE_TRANSFORM_GOVERNANCE_BLOCKED"
        )

        eligible_source_blob = self._insert_available_blob(self.project_id, b"E" * 100)
        eligible = self.application.execute(
            self._command(blob_id=eligible_source_blob, authorization="owned"),
            principal=self.principal,
        )
        other_project = identifier("source-transform-other-project")
        other_workspace = identifier("source-transform-other-workspace")
        self._create_project(other_project, other_workspace)
        other_blob = self._insert_available_blob(other_project, chunk_content)
        cross_project = CommitSourceTransformCommand(
            **{
                **asdict(command),
                "source_document_id": eligible["source_document_id"],
                "chunks": (
                    SourceChunkCandidate(
                        **{**asdict(candidate), "blob_id": other_blob}
                    ),
                ),
                "idempotency_key": "cross-project-transform",
            }
        )
        with self.assertRaises(KernelError) as crossed:
            self.application.admit_transform(
                cross_project, principal=self.principal
            )
        self.assertEqual(crossed.exception.code, "CROSS_PROJECT_REFERENCE")

    def _command(
        self,
        *,
        blob_id: str,
        authorization: str,
        license_name: str = "",
        copyright_boundary: str = "",
    ) -> RegisterSourceDocumentCommand:
        return RegisterSourceDocumentCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            blob_id=blob_id,
            title="Governed Source",
            source_kind="professional_book",
            source_uri="urn:test:governed-source",
            rights_authorization=authorization,
            license_name=license_name,
            copyright_boundary=copyright_boundary,
            actor_id="request-payload-actor",
            idempotency_key=f"source:{self.project_id}:{blob_id}",
            trace_id=f"trace:{blob_id}",
            correlation_id=f"correlation:{blob_id}",
        )

    @staticmethod
    def _create_project(project_id: str, workspace_id: str) -> None:
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-authority-integration",
            commit_sha="e" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="source-project-operator",
                idempotency_key=f"source-project:{project_id}",
                trace_id=f"trace:{project_id}",
                correlation_id=f"correlation:{project_id}",
                payload={"title": "Source Authority Project"},
            )
        )

    @staticmethod
    def _insert_available_blob(project_id: str, content: bytes) -> str:
        blob_id = identifier("source-blob")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        object_key = f"sources/{project_id}/{blob_id}"
        with transaction() as connection:
            connection.cursor().execute(
                """
                INSERT INTO authority_blob (
                    blob_id, project_id, provider, object_key, expected_hash,
                    expected_size, media_type, actual_object_key, actual_hash,
                    actual_size, receipt_provider, status
                ) VALUES (%s, %s, 'fixture_object_store', %s, %s, %s,
                          'text/plain', %s, %s, %s,
                          'fixture_object_store', 'AVAILABLE')
                """,
                [
                    blob_id,
                    project_id,
                    object_key,
                    digest,
                    len(content),
                    object_key,
                    digest,
                    len(content),
                ],
            )
        return blob_id


if __name__ == "__main__":
    unittest.main()
