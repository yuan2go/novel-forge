from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace

from psycopg.types.json import Jsonb
from psycopg.errors import UniqueViolation

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_authority import (
    CommitDeconstructionObservationCommand,
    CommitSourceTransformCommand,
    ObservationEvidenceSpan,
    ObservationScope,
    PlanSourceReprocessingCommand,
    RegisterSourceDocumentCommand,
    ReprocessingTarget,
    SourceAuthorityApplication,
    SourceAuthorityQuery,
    SourceAuthorityScheduler,
    SourceChunkCandidate,
    default_analyzer_contracts,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class SourceDeconstructionAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("deconstruction-project")
        self.workspace_id = identifier("deconstruction-workspace")
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="deconstruction-integration",
            commit_sha="d" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id="project-operator",
                idempotency_key=f"project:{self.project_id}",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload={"title": "Deconstruction Integration"},
            )
        )
        self.application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="deconstruction-integration",
            commit_sha="d" * 40,
            allow_fixture_observations=True,
        )
        self.principal = Principal(
            principal_id="deconstruction-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"source.authority.execute"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )
        self.source, self.transform, self.chunk = self._source_chain()
        self.execution_asset_version_id = self._execution_evidence()

    def test_replay_and_analyzer_upgrade_recompute_only_affected_dimension(self) -> None:
        contracts = default_analyzer_contracts()
        hook_v1 = self._command("hook", contracts["hook"])
        structure_v1 = self._command("structure", contracts["structure"])

        hook = self.application.execute_observation(
            hook_v1, principal=self.principal
        )
        structure = self.application.execute_observation(
            structure_v1, principal=self.principal
        )
        replay = self.application.execute_observation(
            hook_v1, principal=self.principal
        )
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["asset_version_id"], hook["asset_version_id"])

        hook_v2 = replace(
            contracts["hook"],
            analyzer_version="2.0.0",
            prompt_version="2.0.0",
        )
        admitted = self.application.admit_reprocessing_plan(
            PlanSourceReprocessingCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                targets=(
                    ReprocessingTarget(scope=hook_v1.scope, analyzer=hook_v2),
                    ReprocessingTarget(
                        scope=structure_v1.scope, analyzer=contracts["structure"]
                    ),
                ),
                cause_type="ANALYZER_UPGRADE",
                source_transform_id=self.transform["source_transform_id"],
                actor_id="payload-actor",
                idempotency_key="plan:hook-v2",
                trace_id="trace:plan:hook-v2",
                correlation_id="correlation:plan:hook-v2",
            ),
            principal=self.principal,
        )
        result = SourceAuthorityScheduler(
            SourceAuthorityApplication(
                DATABASE_URL,
                application_build_id="deconstruction-integration",
                commit_sha="d" * 40,
                worker_id="deconstruction-restarted-worker",
                allow_fixture_observations=True,
            ),
            worker_id="deconstruction-restarted-worker",
        ).run_or_recover(
            operation_id=admitted["operation_id"], project_id=self.project_id
        )

        actions = {
            (item["dimension"], item["action"])
            for item in result["items"]
            if item["action"] != "REBUILD_PROJECTION"
        }
        self.assertEqual(
            actions, {("hook", "RECOMPUTE"), ("structure", "REUSE")}
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT target_asset_version_id, dimension
                FROM authority_content_invalidation
                WHERE project_id=%s ORDER BY target_asset_version_id
                """,
                [self.project_id],
            )
            self.assertEqual(cursor.fetchall(), [(hook["asset_version_id"], "hook")])
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_source_deconstruction_observation
                WHERE project_id=%s
                """,
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 2)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation,
                     jsonb_array_elements(input_asset_snapshot) AS input
                WHERE operation_id=%s
                  AND input->>'asset_version_id'=%s
                """,
                [admitted["operation_id"], self.transform["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

        upgraded = self.application.execute_observation(
            self._command("hook", hook_v2), principal=self.principal
        )
        self.assertNotEqual(upgraded["asset_version_id"], hook["asset_version_id"])
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT lifecycle FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [hook["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], "SUPERSEDED")
            cursor.execute(
                """
                SELECT lifecycle FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [structure["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], "ACTIVE")
            cursor.execute(
                """
                SELECT status, resolved_by_operation_id
                FROM authority_content_invalidation
                WHERE target_asset_version_id=%s
                """,
                [hook["asset_version_id"]],
            )
            self.assertEqual(
                cursor.fetchone(), ("RESOLVED", upgraded["operation_id"])
            )

    def test_observation_is_source_isolated_and_commit_consumes_no_tokens(self) -> None:
        command = self._command("hook", default_analyzer_contracts()["hook"])
        result = self.application.execute_observation(
            command, principal=self.principal
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT version.eligibility, version.content,
                       observation.evidence_class
                FROM authority_source_deconstruction_observation AS observation
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=observation.asset_version_id
                WHERE observation.asset_version_id=%s
                """,
                [result["asset_version_id"]],
            )
            eligibility, content, evidence_class = cursor.fetchone()
            self.assertEqual((eligibility, evidence_class), ("INELIGIBLE", "FIXTURE"))
            self.assertFalse(content["source_policy"]["generation_context_allowed"])
            self.assertNotIn("raw_text", json.dumps(content))
            cursor.execute(
                """
                SELECT payload->>'provider_tokens_consumed_by_commit'
                FROM outbox_event
                WHERE payload->>'operation_id'=%s
                  AND topic='authority.source.deconstruction.observation.committed'
                """,
                [result["operation_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], "0")
        admission = SourceAuthorityQuery(DATABASE_URL).data_import_admission(
            project_id=self.project_id
        )
        checks = {item["name"]: item["passed"] for item in admission["checks"]}
        self.assertFalse(admission["data_import_ready"])
        self.assertTrue(checks["source_deduplication"])
        self.assertTrue(checks["source_integrity"])
        self.assertTrue(checks["stable_evidence_addressing"])
        self.assertTrue(checks["source_isolation"])
        self.assertTrue(checks["cross_project_isolation"])
        self.assertFalse(checks["token_cost_traceability"])
        self.assertFalse(checks["mkaos_lineage"])

    def test_multiple_spans_from_one_chunk_preserve_complete_lineage_and_replay(
        self,
    ) -> None:
        from novel_forge.storage.source_intelligence_repositories import (
            SourceIntelligenceRepository,
        )

        command = self._command("hook", default_analyzer_contracts()["hook"])
        second = ObservationEvidenceSpan(
            source_chunk_asset_version_id=self.chunk["asset_version_id"],
            chunk_byte_start=10,
            chunk_byte_end=20,
            evidence_hash="sha256:" + hashlib.sha256(b"span:10:20").hexdigest(),
        )
        observation = dict(command.observation)
        observation["findings"] = [
            {
                **observation["findings"][0],
                "evidence_span_ids": [
                    command.evidence_spans[0].evidence_span_id,
                    second.evidence_span_id,
                ],
            }
        ]
        command = replace(
            command,
            observation=observation,
            evidence_spans=(*command.evidence_spans, second),
        )
        committed = self.application.execute_observation(
            command, principal=self.principal
        )
        replay = self.application.execute_observation(command, principal=self.principal)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["asset_version_id"], committed["asset_version_id"])
        with transaction() as connection, connection.cursor() as cursor:
            repository = SourceIntelligenceRepository(cursor)
            spans = repository.observation_evidence_spans(
                project_id=self.project_id,
                asset_version_id=committed["asset_version_id"],
            )
            self.assertEqual(
                [(item[1], item[2]) for item in spans], [(0, 10), (10, 20)]
            )
            cursor.execute(
                """SELECT count(*) FROM authority_source_deconstruction_observation_input
                WHERE observation_asset_version_id=%s AND role='SOURCE_CHUNK_EVIDENCE'""",
                [committed["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 2)
            with self.assertRaises(UniqueViolation):
                cursor.execute(
                    """INSERT INTO authority_source_deconstruction_observation_input
                    SELECT observation_asset_version_id,project_id,input_asset_version_id,evidence_span_id,
                           role,ordinal+100,created_by_operation_id,created_at
                    FROM authority_source_deconstruction_observation_input
                    WHERE observation_asset_version_id=%s AND role='SOURCE_CHUNK_EVIDENCE' LIMIT 1""",
                    [committed["asset_version_id"]],
                )
            connection.rollback()

    def _command(self, dimension: str, analyzer: object) -> CommitDeconstructionObservationCommand:
        span = ObservationEvidenceSpan(
            source_chunk_asset_version_id=self.chunk["asset_version_id"],
            chunk_byte_start=0,
            chunk_byte_end=10,
            evidence_hash="sha256:" + hashlib.sha256(b"span:0:10").hexdigest(),
        )
        scope = ObservationScope(
            scale="CHAPTER" if dimension == "hook" else "CHAPTER_GROUP",
            range_start=1,
            range_end=1 if dimension == "hook" else 10,
            source_document_ids=(self.source["source_document_id"],),
            label="chapters-1" if dimension == "hook" else "chapters-1-10",
        )
        return CommitDeconstructionObservationCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            execution_asset_version_id=self.execution_asset_version_id,
            scope=scope,
            analyzer=analyzer,
            observation={
                "findings": [
                    {
                        "finding_code": f"{dimension}.fixture.1",
                        "statement": "An abstract mechanism is observed at the addressed scale.",
                        "evidence_span_ids": [span.evidence_span_id],
                    }
                ],
                "confidence": 0.8,
                "originality_risk": "LOW_AFTER_ABSTRACTION",
                "knowledge_status": "NOT_ABSTRACTED",
            },
            evidence_spans=(span,),
            input_observation_asset_version_ids=(),
            evidence_class="FIXTURE",
            actor_id="payload-actor",
            idempotency_key=f"observation:{dimension}:{analyzer.fingerprint}",
            trace_id=f"trace:observation:{dimension}",
            correlation_id=f"correlation:observation:{dimension}",
        )

    def _source_chain(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        source_bytes = b"S" * 200
        blob_id = self._blob(source_bytes)
        source = self.application.execute(
            RegisterSourceDocumentCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                blob_id=blob_id,
                title="Licensed web novel fixture",
                source_kind="licensed_web_novel",
                source_uri="urn:test:deconstruction",
                rights_authorization="owned",
                license_name="owner-rights",
                copyright_boundary="analysis and abstraction only",
                actor_id="payload-actor",
                idempotency_key=f"source:{blob_id}",
                trace_id=f"trace:{blob_id}",
                correlation_id=f"correlation:{blob_id}",
            ),
            principal=self.principal,
        )
        chunk_bytes = b"normalized governed evidence chunk"
        chunk_blob = self._blob(chunk_bytes)
        transform = self.application.execute_transform(
            CommitSourceTransformCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                source_document_id=str(source["source_document_id"]),
                normalization_version="normalize:v1",
                chunking_version="chapter-aware:v1",
                chunking_policy_hash="sha256:" + hashlib.sha256(b"policy").hexdigest(),
                chunks=(
                    SourceChunkCandidate(
                        chunk_index=0,
                        blob_id=chunk_blob,
                        content_hash="sha256:" + hashlib.sha256(chunk_bytes).hexdigest(),
                        byte_size=len(chunk_bytes),
                        character_count=len(chunk_bytes),
                        token_count=6,
                        source_byte_start=0,
                        source_byte_end=200,
                    ),
                ),
                actor_id="payload-actor",
                idempotency_key="transform:v1",
                trace_id="trace:transform:v1",
                correlation_id="correlation:transform:v1",
            ),
            principal=self.principal,
        )
        chunk = SourceAuthorityQuery(DATABASE_URL).list_chunks(
            project_id=self.project_id,
            source_transform_id=str(transform["source_transform_id"]),
        )[0]
        return source, transform, chunk

    def _execution_evidence(self) -> str:
        asset_id = identifier("deconstruction-model-call")
        asset_version_id = f"{asset_id}:v1"
        content = {
            "gateway": "ProductionExecutionGateway",
            "fixture_protocol_only": True,
            "real_provider_proven": False,
            "production_verified": False,
            "provider": "fixture",
            "model": "fixture",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            "cost": {"amount_usd": "0"},
        }
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s, %s, 'model_call_log')",
                [asset_id, self.project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s,
                          'model-call-log.v1')
                """,
                [asset_version_id, asset_id, Jsonb(content), content_hash],
            )
        return asset_version_id

    def _blob(self, content: bytes) -> str:
        blob_id = identifier("deconstruction-blob")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        object_key = f"sources/{self.project_id}/{blob_id}"
        with transaction() as connection:
            connection.cursor().execute(
                """
                INSERT INTO authority_blob(
                    blob_id, project_id, provider, object_key, expected_hash,
                    expected_size, media_type, actual_object_key, actual_hash,
                    actual_size, receipt_provider, status
                ) VALUES (%s, %s, 'fixture_object_store', %s, %s, %s,
                          'text/plain', %s, %s, %s,
                          'fixture_object_store', 'AVAILABLE')
                """,
                [
                    blob_id,
                    self.project_id,
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
