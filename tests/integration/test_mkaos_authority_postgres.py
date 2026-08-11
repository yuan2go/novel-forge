from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import asdict, replace
from decimal import Decimal

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    BuildKnowledgePackCommand,
    CommitKnowledgeCandidateCommand,
    KnowledgeEvidenceSpan,
    KnowledgePackSelection,
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
    MkaosAuthorityScheduler,
)
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
    SourceChunkCandidate,
    default_analyzer_contracts,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class MkaosAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("mkaos-authority-project")
        self.workspace_id = identifier("mkaos-authority-workspace")
        self._create_project(self.project_id, self.workspace_id)
        self.application = MkaosAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
            allow_fixture_activation=True,
        )
        self.query = MkaosAuthorityQuery(DATABASE_URL)
        self.principal = Principal(
            principal_id="mkaos-governance-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "mkaos.authority.execute",
                    "mkaos.authority.approve",
                    "mkaos.authority.query",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def test_candidate_decision_card_and_deterministic_pack_are_separate(self) -> None:
        chunk_version_id = self._source_chunk_version()
        execution_version_id = self._insert_asset_version(
            self.project_id,
            "model_call_log",
            {
                "execution_id": identifier("mkaos-execution"),
                "gateway": "ProductionExecutionGateway",
                "fixture_protocol_only": True,
                "real_provider_proven": False,
            },
        )
        target_version_id = self._insert_asset_version(
            self.project_id,
            "chapter_plan",
            {"chapter": 1, "status": "PLANNED"},
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT source_document_id, source_transform_id
                FROM authority_source_chunk
                WHERE asset_version_id=%s
                """,
                [chunk_version_id],
            )
            source_document_id, source_transform_id = map(str, cursor.fetchone())
        observation_span = ObservationEvidenceSpan(
            source_chunk_asset_version_id=chunk_version_id,
            chunk_byte_start=0,
            chunk_byte_end=10,
            evidence_hash="sha256:" + hashlib.sha256(b"span-0-10").hexdigest(),
        )
        observation_scope = ObservationScope(
            scale="CHAPTER",
            range_start=1,
            range_end=1,
            source_document_ids=(source_document_id,),
            label="chapter-1",
        )
        hook_analyzer = default_analyzer_contracts()["hook"]
        source_application = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
            allow_fixture_observations=True,
        )
        observation = source_application.execute_observation(
            CommitDeconstructionObservationCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                execution_asset_version_id=execution_version_id,
                scope=observation_scope,
                analyzer=hook_analyzer,
                observation={
                    "findings": [
                        {
                            "finding_code": "hook.1",
                            "statement": "A bounded abstract hook mechanism was observed.",
                            "evidence_span_ids": [observation_span.evidence_span_id],
                        }
                    ],
                    "confidence": 0.8,
                    "originality_risk": "LOW_AFTER_ABSTRACTION",
                    "knowledge_status": "NOT_ABSTRACTED",
                },
                evidence_spans=(observation_span,),
                input_observation_asset_version_ids=(),
                evidence_class="FIXTURE",
                actor_id="fixture-observer",
                idempotency_key=f"observation:{chunk_version_id}",
                trace_id=f"trace:observation:{chunk_version_id}",
                correlation_id=f"correlation:observation:{chunk_version_id}",
            )
        )
        candidate_command = self._candidate_command(
            chunk_version_id=chunk_version_id,
            execution_version_id=execution_version_id,
            observation_asset_version_id=observation["asset_version_id"],
        )
        unrelated_chunk_version_id = self._source_chunk_version(
            source_bytes=b"T" * 100,
            chunk_bytes=b"unrelated governed evidence for a second source",
        )
        with self.assertRaises(KernelError) as mismatched_lineage:
            self.application.admit_candidate(
                self._candidate_command(
                    chunk_version_id=unrelated_chunk_version_id,
                    execution_version_id=execution_version_id,
                    observation_asset_version_id=observation["asset_version_id"],
                ),
                principal=self.principal,
            )
        self.assertEqual(
            mismatched_lineage.exception.code,
            "MKAOS_OBSERVATION_EVIDENCE_CONFLICT",
        )

        admitted = self.application.admit_candidate(
            candidate_command, principal=self.principal
        )
        self.assertEqual(admitted["status"], "READY")
        restarted = MkaosAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
            worker_id="mkaos-worker-after-api",
            allow_fixture_activation=True,
        )
        candidate = MkaosAuthorityScheduler(
            restarted,
            worker_id="mkaos-worker-after-api",
            lease_seconds=30,
        ).run_or_recover(
            operation_id=admitted["operation_id"], project_id=self.project_id
        )
        replay = self.application.admit_candidate(
            candidate_command, principal=self.principal
        )

        self.assertEqual(candidate["status"], "SUCCEEDED")
        self.assertTrue(replay["duplicate"])
        candidates = self.query.list_candidates(project_id=self.project_id)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            (
                candidates[0]["candidate_status"],
                candidates[0]["lifecycle"],
                candidates[0]["eligibility"],
                candidates[0]["governance"],
            ),
            ("NEEDS_REVIEW", "CANDIDATE", "PENDING_EVALUATION", "CLEAR"),
        )
        self.assertEqual(self.query.list_cards(project_id=self.project_id), [])

        approval = self.application.execute_approval(
            ApproveKnowledgeCandidateCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                candidate_asset_version_id=candidate["asset_version_id"],
                policy_version="mkaos-governance:v1",
                rationale="The candidate is abstract, traceable and contains no source prose.",
                actor_id="request-actor-is-not-trusted",
                idempotency_key=f"approve:{candidate['asset_version_id']}",
                trace_id=f"trace:approve:{candidate['asset_version_id']}",
                correlation_id=f"correlation:approve:{candidate['asset_version_id']}",
            ),
            principal=self.principal,
        )
        card = self.query.list_cards(project_id=self.project_id)[0]
        self.assertEqual(approval["status"], "SUCCEEDED")
        self.assertEqual(
            (card["lifecycle"], card["eligibility"], card["governance"]),
            ("ACTIVE", "ELIGIBLE", "CLEAR"),
        )
        self.assertEqual(
            card["content"]["lineage"]["candidate_asset_version_id"],
            candidate["asset_version_id"],
        )

        pack_command = BuildKnowledgePackCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            target_asset_version_id=target_version_id,
            selector_policy_version="mkaos-explicit-selector:v1",
            selector_policy_hash="sha256:" + hashlib.sha256(b"selector-v1").hexdigest(),
            selections=(
                KnowledgePackSelection(
                    knowledge_card_asset_version_id=approval["asset_version_id"],
                    usage_role="constraint",
                    frozen_weight=Decimal("2.5"),
                ),
            ),
            actor_id="request-actor-is-not-trusted",
            idempotency_key=f"pack:{target_version_id}",
            trace_id=f"trace:pack:{target_version_id}",
            correlation_id=f"correlation:pack:{target_version_id}",
        )
        pack = self.application.execute_pack(pack_command, principal=self.principal)
        pack_replay = self.application.execute_pack(
            pack_command, principal=self.principal
        )
        stored_pack = self.query.require_pack(
            project_id=self.project_id,
            knowledge_pack_id=pack["knowledge_pack_id"],
        )

        self.assertEqual(pack["status"], "SUCCEEDED")
        self.assertTrue(pack_replay["duplicate"])
        self.assertEqual(stored_pack["target_asset_version_id"], target_version_id)
        self.assertEqual(stored_pack["item_count"], 1)
        self.assertFalse(
            stored_pack["content"]["source_policy"]["directory_selection_used"]
        )
        encoded = json.dumps(stored_pack["content"], ensure_ascii=False)
        self.assertNotIn("raw_text", encoded)
        self.assertNotIn("clean_text", encoded)

        conflicting_pack = BuildKnowledgePackCommand(
            **{
                **asdict(pack_command),
                "selections": (
                    KnowledgePackSelection(
                        knowledge_card_asset_version_id=approval[
                            "asset_version_id"
                        ],
                        usage_role="check",
                        frozen_weight=Decimal("2.5"),
                    ),
                ),
            }
        )
        with self.assertRaises(KernelError) as conflict:
            self.application.admit_pack(conflicting_pack, principal=self.principal)
        self.assertEqual(conflict.exception.code, "MKAOS_PACK_ACTIVE_CONFLICT")

        replacement = self.application.execute_pack(
            replace(
                conflicting_pack,
                idempotency_key=f"pack-rebuild:{target_version_id}",
                supersedes_pack_asset_version_id=pack["asset_version_id"],
            ),
            principal=self.principal,
        )
        self.assertNotEqual(replacement["asset_version_id"], pack["asset_version_id"])
        pack_diff = self.query.diff_packs(
            project_id=self.project_id,
            knowledge_pack_id=replacement["knowledge_pack_id"],
            against_knowledge_pack_id=pack["knowledge_pack_id"],
        )
        self.assertTrue(pack_diff["directly_supersedes_baseline"])
        self.assertEqual(pack_diff["added"], [])
        self.assertEqual(pack_diff["removed"], [])
        self.assertEqual(len(pack_diff["changed"]), 1)
        self.assertEqual(
            pack_diff["changed"][0]["before"]["usage_role"], "CONSTRAINT"
        )
        self.assertEqual(pack_diff["changed"][0]["after"]["usage_role"], "CHECK")

        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT candidate.status, COUNT(DISTINCT decision.asset_version_id),
                       COUNT(DISTINCT card.asset_version_id),
                       COUNT(DISTINCT item.knowledge_card_asset_version_id)
                FROM authority_mkaos_knowledge_candidate AS candidate
                JOIN authority_mkaos_governance_decision AS decision
                  ON decision.candidate_asset_version_id = candidate.asset_version_id
                JOIN authority_mkaos_knowledge_card AS card
                  ON card.candidate_asset_version_id = candidate.asset_version_id
                JOIN authority_mkaos_knowledge_pack_item AS item
                  ON item.knowledge_card_asset_version_id = card.asset_version_id
                WHERE candidate.asset_version_id = %s
                GROUP BY candidate.status
                """,
                [candidate["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("APPROVED", 1, 1, 1))
            cursor.execute(
                """
                SELECT status, version.lifecycle
                FROM authority_mkaos_knowledge_pack AS pack
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=pack.asset_version_id
                WHERE pack.asset_version_id=%s
                """,
                [pack["asset_version_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("SUPERSEDED", "SUPERSEDED"))
            cursor.execute(
                """
                SELECT DISTINCT relationship FROM authority_content_dependency
                WHERE project_id=%s AND relationship IN (
                    'ABSTRACTS', 'GOVERNS', 'ACTIVATES', 'SELECTS', 'PROJECTS'
                ) ORDER BY relationship
                """,
                [self.project_id],
            )
            self.assertEqual(
                [row[0] for row in cursor.fetchall()],
                ["ABSTRACTS", "ACTIVATES", "GOVERNS", "PROJECTS", "SELECTS"],
            )

        plan = source_application.execute_reprocessing_plan(
            PlanSourceReprocessingCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                targets=(
                    ReprocessingTarget(
                        scope=observation_scope,
                        analyzer=replace(
                            hook_analyzer,
                            analyzer_version="2.0.0",
                            prompt_version="2.0.0",
                        ),
                    ),
                ),
                cause_type="ANALYZER_UPGRADE",
                source_transform_id=source_transform_id,
                actor_id="source-reprocessing-operator",
                idempotency_key=f"reprocess:{observation['asset_version_id']}",
                trace_id=f"trace:reprocess:{observation['asset_version_id']}",
                correlation_id=(
                    f"correlation:reprocess:{observation['asset_version_id']}"
                ),
            )
        )
        self.assertEqual(
            {item["action"] for item in plan["items"]},
            {"RECOMPUTE", "REABSTRACT", "REGOVERN", "REBUILD_PROJECTION"},
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT asset.asset_type, invalidation.target_asset_version_id
                FROM authority_content_invalidation AS invalidation
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=invalidation.target_asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE invalidation.project_id=%s AND invalidation.status='OPEN'
                ORDER BY asset.asset_type, invalidation.target_asset_version_id
                """,
                [self.project_id],
            )
            invalidated = cursor.fetchall()
        self.assertIn(
            ("source_deconstruction_observation", observation["asset_version_id"]),
            invalidated,
        )
        self.assertIn(
            ("knowledge_card_candidate", candidate["asset_version_id"]),
            invalidated,
        )
        self.assertIn(("knowledge_card", approval["asset_version_id"]), invalidated)
        self.assertIn(("knowledge_pack", replacement["asset_version_id"]), invalidated)
        self.assertNotIn(("knowledge_pack", pack["asset_version_id"]), invalidated)

    def test_raw_source_field_and_cross_project_lineage_fail_closed(self) -> None:
        chunk_version_id = self._source_chunk_version()
        execution_version_id = self._insert_asset_version(
            self.project_id,
            "execution_commit_manifest",
            {"gateway": "ProductionExecutionGateway", "status": "verified-fixture"},
        )
        command = self._candidate_command(
            chunk_version_id=chunk_version_id,
            execution_version_id=execution_version_id,
        )
        with self.assertRaises(KernelError) as leaked:
            self.application.admit_candidate(
                CommitKnowledgeCandidateCommand(
                    **{
                        **asdict(command),
                        "candidate": {**command.candidate, "raw_text": "blocked"},
                        "evidence_spans": command.evidence_spans,
                    }
                ),
                principal=self.principal,
            )
        self.assertEqual(leaked.exception.code, "MKAOS_SOURCE_LEAKAGE_BLOCKED")

        other_project = identifier("mkaos-other-project")
        other_workspace = identifier("mkaos-other-workspace")
        self._create_project(other_project, other_workspace)
        other_chunk = self._source_chunk_version(
            project_id=other_project, workspace_id=other_workspace
        )
        with self.assertRaises(KernelError) as crossed:
            self.application.admit_candidate(
                self._candidate_command(
                    chunk_version_id=other_chunk,
                    execution_version_id=execution_version_id,
                ),
                principal=self.principal,
            )
        self.assertEqual(crossed.exception.code, "MKAOS_SOURCE_CHUNK_NOT_FOUND")
        with self.assertRaises(KernelError) as unbound:
            self.application.admit_candidate(command, principal=self.principal)
        self.assertEqual(unbound.exception.code, "MKAOS_EXECUTION_OUTPUT_UNBOUND")

    def test_fixture_candidate_cannot_activate_with_production_defaults(self) -> None:
        chunk_version_id = self._source_chunk_version()
        execution_version_id = self._insert_asset_version(
            self.project_id,
            "model_call_log",
            {
                "gateway": "ProductionExecutionGateway",
                "fixture_protocol_only": True,
                "real_provider_proven": False,
                "production_verified": False,
            },
        )
        candidate = self.application.execute_candidate(
            self._candidate_command(
                chunk_version_id=chunk_version_id,
                execution_version_id=execution_version_id,
            ),
            principal=self.principal,
        )
        strict_application = MkaosAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
        )
        with self.assertRaises(KernelError) as blocked:
            strict_application.admit_approval(
                ApproveKnowledgeCandidateCommand(
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    candidate_asset_version_id=candidate["asset_version_id"],
                    policy_version="mkaos-governance:v1",
                    rationale="Fixture evidence is intentionally not production evidence.",
                    actor_id="request-actor-is-not-trusted",
                    idempotency_key=f"approve:{candidate['asset_version_id']}",
                    trace_id=f"trace:approve:{candidate['asset_version_id']}",
                    correlation_id=(
                        f"correlation:approve:{candidate['asset_version_id']}"
                    ),
                ),
                principal=self.principal,
            )
        self.assertEqual(
            blocked.exception.code, "MKAOS_FIXTURE_CANDIDATE_NOT_ACTIVATABLE"
        )

    def _candidate_command(
        self,
        *,
        chunk_version_id: str,
        execution_version_id: str,
        observation_asset_version_id: str = "",
    ) -> CommitKnowledgeCandidateCommand:
        candidate = {
            "concept_name": "Escalating obligation",
            "discipline": "organizational behavior",
            "abstract_principle": (
                "A favor creates conflict when repayment criteria can change after consent."
            ),
            "constraints": [
                "Every escalation must expose who changed the repayment criterion."
            ],
            "conflict_generators": [
                "The beneficiary and patron disagree about whether the debt is settled."
            ],
            "review_checks": [
                "Reject any proper noun, distinctive scene or source-specific expression."
            ],
            "copyright_boundaries": [
                "Retain only the abstract obligation mechanism and evidence identity."
            ],
        }
        return CommitKnowledgeCandidateCommand(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            execution_asset_version_id=execution_version_id,
            candidate=candidate,
            evidence_spans=(
                KnowledgeEvidenceSpan(
                    source_chunk_asset_version_id=chunk_version_id,
                    chunk_byte_start=0,
                    chunk_byte_end=10,
                    evidence_hash="sha256:" + hashlib.sha256(b"span-0-10").hexdigest(),
                ),
            ),
            abstraction_policy_version="anti-copy-abstraction:v1",
            actor_id="request-actor-is-not-trusted",
            idempotency_key=f"candidate:{chunk_version_id}:{execution_version_id}",
            trace_id=f"trace:candidate:{chunk_version_id}",
            correlation_id=f"correlation:candidate:{chunk_version_id}",
            observation_asset_version_ids=(
                (observation_asset_version_id,)
                if observation_asset_version_id
                else ()
            ),
        )

    def _source_chunk_version(
        self,
        *,
        project_id: str = "",
        workspace_id: str = "",
        source_bytes: bytes = b"S" * 100,
        chunk_bytes: bytes = b"normalized evidence bytes for abstract analysis",
    ) -> str:
        project_id = project_id or self.project_id
        workspace_id = workspace_id or self.workspace_id
        source_app = SourceAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
        )
        source_blob = self._insert_available_blob(project_id, source_bytes)
        source = source_app.execute(
            RegisterSourceDocumentCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                blob_id=source_blob,
                title="MKAOS governed source",
                source_kind="licensed_research",
                source_uri="urn:test:mkaos-source",
                rights_authorization="owned",
                license_name="owner-rights",
                copyright_boundary="abstract mechanisms only",
                actor_id="source-operator",
                idempotency_key=f"source:{source_blob}",
                trace_id=f"trace:{source_blob}",
                correlation_id=f"correlation:{source_blob}",
            )
        )
        chunk_blob = self._insert_available_blob(project_id, chunk_bytes)
        transformed = source_app.execute_transform(
            CommitSourceTransformCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                source_document_id=source["source_document_id"],
                normalization_version="normalize:v1",
                chunking_version="evidence:v1",
                chunking_policy_hash="sha256:" + hashlib.sha256(b"mkaos-chunk-v1").hexdigest(),
                chunks=(
                    SourceChunkCandidate(
                        chunk_index=0,
                        blob_id=chunk_blob,
                        content_hash="sha256:" + hashlib.sha256(chunk_bytes).hexdigest(),
                        byte_size=len(chunk_bytes),
                        character_count=len(chunk_bytes.decode()),
                        token_count=6,
                        source_byte_start=0,
                        source_byte_end=100,
                    ),
                ),
                actor_id="source-operator",
                idempotency_key=f"transform:{source['asset_version_id']}",
                trace_id=f"trace:transform:{source_blob}",
                correlation_id=f"correlation:transform:{source_blob}",
            )
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT asset_version_id FROM authority_source_chunk
                WHERE source_transform_id = %s AND chunk_index = 0
                """,
                [transformed["source_transform_id"]],
            )
            return str(cursor.fetchone()[0])

    @staticmethod
    def _create_project(project_id: str, workspace_id: str) -> None:
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="mkaos-authority-integration",
            commit_sha="f" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="mkaos-project-operator",
                idempotency_key=f"mkaos-project:{project_id}",
                trace_id=f"trace:{project_id}",
                correlation_id=f"correlation:{project_id}",
                payload={"title": "MKAOS Authority Project"},
            )
        )

    @staticmethod
    def _insert_available_blob(project_id: str, content: bytes) -> str:
        blob_id = identifier("mkaos-blob")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        object_key = f"mkaos/{project_id}/{blob_id}"
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

    @staticmethod
    def _insert_asset_version(
        project_id: str, asset_type: str, content: dict[str, object]
    ) -> str:
        asset_id = identifier(f"mkaos-{asset_type}")
        asset_version_id = f"{asset_id}:v1"
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number,
                    lifecycle, eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                """,
                [asset_version_id, asset_id, Jsonb(content), content_hash],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_qualification(
                    qualification_id, asset_version_id,
                    policy_version, decision, evidence
                ) VALUES (%s, %s, 'integration-fixture-v1',
                          'ELIGIBLE', %s)
                """,
                [
                    f"{asset_version_id}:qualification:v1",
                    asset_version_id,
                    Jsonb({
                        "fixture_protocol_only": True,
                        "production_verified": False,
                    }),
                ],
            )
        return asset_version_id


if __name__ == "__main__":
    unittest.main()
