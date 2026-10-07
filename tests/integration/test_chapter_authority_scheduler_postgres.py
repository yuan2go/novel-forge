from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import unittest

from novel_forge.modules.chapter_authority.contracts import (
    QUALITY_GROUP_NODES,
    ChapterNode,
)
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    expire_deferred_canon_approvals,
    list_canon_approvals,
    reopen_canon_approval,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    admit_single_chapter_saga,
)
from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerResultCommand,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.corrective_action import CorrectiveActionQuery
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.production_preparation.policies import (
    CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class QualityCorrectionFixture(DeterministicFixtureChapterProvider):
    supports_quality_evaluation = True

    def __init__(self, *, correction_resolves: bool) -> None:
        self.correction_resolves = correction_resolves
        self.longform_evaluations = 0

    def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
        if stage == "revision" and "quality" in payload:
            draft = payload["draft"]
            return self._result(
                stage,
                self.structured_fixture_output(stage, payload, {
                    "text": (
                        f"{draft['text']} The corrected timeline now matches "
                        "the frozen Canon evidence."
                    )
                }),
            )
        if stage.startswith("quality_"):
            statuses = []
            for dimension in payload["dimensions"]:
                gate = "PASSED"
                if stage == "quality_longform" and dimension == "canon_consistency":
                    self.longform_evaluations += 1
                    if self.longform_evaluations == 1 or not self.correction_resolves:
                        gate = "FAILED"
                statuses.append(
                    {
                        "dimension": dimension,
                        "gate_status": gate,
                        "fixture_protocol_only": True,
                    }
                )
            return self._result(stage, {"dimensions": statuses})
        return super().invoke(request, stage=stage, payload=payload)

    def _result(self, stage: str, output: dict[str, object]) -> ModelProviderResult:
        return ModelProviderResult(
            output=output,
            provider_id=self.provider_id,
            model_id="quality-correction-fixture-v1",
            prompt_version=f"{stage}-fixture-v1",
            skill_version="quality-correction-fixture-v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


class TwoActionQualityCorrectionFixture(QualityCorrectionFixture):
    def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
        result = super().invoke(request, stage=stage, payload=payload)
        if stage == "quality_longform" and self.longform_evaluations == 1:
            dimensions = [dict(item) for item in result.output["dimensions"]]
            for item in dimensions:
                if item["dimension"] == "timeline_consistency":
                    item["gate_status"] = "FAILED"
            return self._result(stage, {"dimensions": dimensions})
        return result


class DownstreamRetryExhaustedFixture(QualityCorrectionFixture):
    def __init__(self) -> None:
        super().__init__(correction_resolves=True)
        self.correction_rereview_calls = 0

    def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
        if stage == "rereview" and "corrected timeline" in str(
            payload.get("revision", {}).get("text") or ""
        ):
            self.correction_rereview_calls += 1
            raise KernelError(
                "MODEL_EFFECT_RETRYABLE_REREVIEW",
                "fixture correction re-review remains retryable",
            )
        return super().invoke(request, stage=stage, payload=payload)


class GroundedHighImpactFixture(DeterministicFixtureChapterProvider):
    supports_semantic_extraction = True
    death = "The protagonist dies from the wound."

    def invoke(self, request, *, stage, payload):
        if stage == "canon_extraction":
            text = payload["revision"]["text"]
            start = text.index(self.death)
            return ModelProviderResult(
                output={"extraction_status": "EXTRACTED", "no_change_reason": "",
                        "character_state_changes": [{"character_id": "protagonist", "status": "dead",
                            "impact_type": "character_death", "confidence": 0.9,
                            "claim_kind": "OBJECTIVE_EVENT", "evidence_quote": self.death,
                            "evidence_start": start, "evidence_end": start + len(self.death)}]},
                provider_id="deterministic_semantic_fixture", model_id="fixture", prompt_version="fixture-v1",
                skill_version="fixture-v1", input_tokens=0, output_tokens=0, cost_amount="0", currency="USD", real_model_call=False,
            )
        result = super().invoke(request, stage=stage, payload=payload)
        if stage == "draft":
            return replace(result, output=self.structured_fixture_output(stage, payload, {"text": result.output["text"] + " " + self.death}))
        return result


class CanonConflictQualityCorrectionFixture(DeterministicFixtureChapterProvider):
    supports_semantic_extraction = True

    def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
        if stage == "draft":
            result = super().invoke(request, stage=stage, payload=payload)
            return replace(result, output=self.structured_fixture_output(stage, payload,
                {"text": result.output["text"] + " The protagonist invoked the governed exception."}))
        if stage == "revision" and "quality" in payload:
            draft = payload["draft"]
            return self._result(
                stage,
                self.structured_fixture_output(stage, payload, {
                    "text": (
                        f"{draft['text']} The governed exception consumes one "
                        "irreplaceable seal as its explicit cost."
                    )
                }),
            )
        if stage == "canon_extraction":
            text = str(payload["revision"].get("text") or "")
            corrected = "explicit cost" in text
            output = {
                field: []
                for field in (
                    "canon_facts",
                    "character_state_changes",
                    "relationship_changes",
                    "timeline_events",
                    "foreshadow_changes",
                    "promise_changes",
                    "reward_changes",
                    "world_rule_usages",
                    "power_state_changes",
                    "plot_thread_changes",
                    "resource_state_changes",
                    "narrative_pattern_fingerprints",
                    "theme_movements",
                    "antagonist_pressure_changes",
                    "character_knowledge_changes",
                    "character_belief_changes",
                    "character_arc_changes",
                    "arc_state_changes",
                    "disclosure_events",
                    "arc_evidence",
                )
            }
            output["world_rule_usages"] = [
                {
                    "rule_id": "rule:governed-exception-cost",
                    "state": "EXERCISED",
                    "exception": True,
                    "cost": "one irreplaceable seal" if corrected else "",
                    "evidence_start": 0,
                    "evidence_end": max(1, len(text)),
                    "confidence": 0.99,
                    "impact_type": "world_rule_use",
                }
            ]
            output.update({"extraction_status": "EXTRACTED", "no_change_reason": ""})
            output["world_rule_usages"][0].update({"claim_kind": "OBJECTIVE_EVENT", "evidence_quote": text})
            return self._result(stage, output)
        return super().invoke(request, stage=stage, payload=payload)

    def _result(self, stage: str, output: dict[str, object]) -> ModelProviderResult:
        return ModelProviderResult(
            output=output,
            provider_id=self.provider_id,
            model_id="canon-conflict-correction-fixture-v1",
            prompt_version=f"{stage}-fixture-v1",
            skill_version="canon-conflict-correction-fixture-v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


class SimulatedQualityCorrectionCrash(BaseException):
    pass


class ChapterAuthoritySchedulerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_deterministic_admission_gate_rechecks_only_after_repair_and_keeps_root(self):
        from unittest.mock import patch

        project_id = identifier("admission-gate")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        request = SingleChapterRequest(
            project_id=project_id, workspace_id=f"workspace:{project_id}", actor_id="trusted-operator",
            chapter=1, title="Scope", premise="A visible cost", trace_id=identifier("trace"),
            correlation_id=identifier("correlation"), application_build_id="admission-gate-test",
            commit_sha="f" * 40, idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True}, context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(DATABASE_URL, request=request, registry=registry,
                                             permissions=frozenset({"chapter.authority.execute"}))
        scheduler = ChapterAuthorityScheduler(DATABASE_URL, registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"), worker_id="gate-worker",
            permissions=frozenset({"chapter.authority.execute"}))
        args = {"project_id": project_id, "root_operation_id": admission.root_operation_id}
        self.assertEqual(scheduler.tick(**args).node, ChapterNode.PLAN.value)
        with patch("novel_forge.modules.chapter_authority.scheduler._admission_implementation_identity", return_value="old-code"):
            with patch.object(scheduler, "_admit_node", side_effect=KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "host source mismatch")) as admit:
                blocked = scheduler.tick(**args)
                self.assertEqual(blocked.recovery_mode, "technical_admission_blocked")
                self.assertNotIn((project_id, admission.root_operation_id), scheduler.pending_roots(limit=1000))
                replay = scheduler.tick(**args)
                self.assertEqual(replay.recovery_mode, "technical_admission_blocked")
                self.assertEqual(admit.call_count, 1)
        with patch("novel_forge.modules.chapter_authority.scheduler._admission_implementation_identity", return_value="repaired-code"):
            self.assertIn((project_id, admission.root_operation_id), scheduler.pending_roots(limit=1000))
            resumed = scheduler.tick(**args)
            self.assertEqual(resumed.node, ChapterNode.EXECUTION_INTENT.value)
            self.assertEqual(resumed.operation_status, "SUCCEEDED")
        root, _, children = scheduler._graph_state(project_id, admission.root_operation_id)
        self.assertEqual(root["command_payload"]["chapter_idempotency_key"], request.idempotency_key)
        self.assertEqual(len(children), 2)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM state_event WHERE aggregate_id=%s AND event_type='authority.operation.status_changed' ORDER BY sequence_number", [admission.root_operation_id])
            events = [row[0] for row in cursor.fetchall()]
        failures = [json.loads(event["reason"]) for event in events if event["reason"].startswith('{"error_code"')]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error_code"], "RETRIEVAL_TASK_SOURCE_BINDING_INVALID")
        with patch("novel_forge.modules.chapter_authority.scheduler._admission_implementation_identity", return_value="repaired-code"):
            with patch.object(scheduler, "_admit_node", side_effect=KernelError("CONTEXT_BINDING_INVALID", "another frozen owner mismatch")):
                self.assertEqual(scheduler.tick(**args).recovery_mode, "technical_admission_blocked")
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            version = uow.repositories.attempt_runtime.operation_state(admission.root_operation_id, project_id)["version"]
        request_cancellation(DATABASE_URL, CancelCommand(
            project_id=project_id, operation_id=admission.root_operation_id, expected_version=int(version),
            idempotency_key=f"{project_id}:cancel", actor_id="trusted-operator", reason="author cancelled", trace_id=request.trace_id,
            correlation_id=request.correlation_id, causation_id="author-cancel",
        ))
        with patch("novel_forge.modules.chapter_authority.scheduler._admission_implementation_identity", return_value="newer-code"):
            scheduler.tick(**args)
        cancelled, _, remaining = scheduler._graph_state(project_id, admission.root_operation_id)
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(len(remaining), 2)

    def test_admission_does_not_execute_and_ticks_rebuild_full_saga(self) -> None:
        project_id = identifier("async-chapter-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Durable Promise",
            premise="A promise creates a visible irreversible cost.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="async-chapter-test",
            commit_sha="f" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )

        self.assertEqual(admission.status, "ACCEPTED")
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        seen = []
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            seen.append(tick.node)
            self.assertEqual(tick.operation_status, "SUCCEEDED")
            if tick.node == ChapterNode.QUALITY_STRUCTURAL.value:
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT definition_name, status
                        FROM authority_operation
                        WHERE root_operation_id = %s
                          AND definition_name LIKE 'chapter.quality.%%.evaluate'
                          AND definition_name <> 'chapter.quality.evaluate'
                        ORDER BY definition_name
                        """,
                        [admission.root_operation_id],
                    )
                    fanout = cursor.fetchall()
                self.assertEqual(len(fanout), 5)
                self.assertEqual(
                    sum(status == "READY" for _, status in fanout),
                    4,
                )

        terminal = scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(seen, [node.value for node in ChapterNode])
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        self.assertEqual(terminal.recovery_mode, "terminal_replay")
        quality, publish_gate = self._quality_and_publish_gate(
            admission.root_operation_id
        )
        self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(publish_gate["gate"], "PASSED")
        self.assertEqual(publish_gate["release_readiness"], "INTERNAL_REVIEW_RELEASE")
        self.assertFalse(publish_gate["external_publish_permitted"])
        self.assertFalse(publish_gate["production_verified"])
        self.assertTrue(publish_gate["fixture_protocol_only"])
        corrective = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id, issue_type="COST_NOT_CONCRETE"
        )
        self.assertEqual(len(corrective), 1)
        self.assertEqual(corrective[0]["status"], "RESOLVED")
        self.assertEqual(corrective[0]["gate_result"], "PASSED")
        self.assertTrue(corrective[0]["execution_operation_id"])
        self.assertTrue(corrective[0]["result_asset_version_ids"])
        self.assertTrue(corrective[0]["evaluation_operation_id"])
        self.assertEqual(corrective[0]["lifecycle"][-1], "RESOLVED")

    def test_failed_rereview_escalates_the_corrective_issue(self) -> None:
        class FailedRereviewFixture(DeterministicFixtureChapterProvider):
            def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
                if stage != "rereview":
                    return super().invoke(request, stage=stage, payload=payload)
                return ModelProviderResult(
                    output={
                        "decision": "NEEDS_REVISION",
                        "score": 70,
                        "issues": [
                            {
                                "code": "COST_NOT_CONCRETE",
                                "severity": "blocking",
                                "message": "The cost remains abstract.",
                            }
                        ],
                        "resolved_issue_codes": [],
                    },
                    provider_id=self.provider_id,
                    model_id="deterministic-fixture-model-v1",
                    prompt_version="chapter-rereview-fixture-v1",
                    skill_version="deterministic-fixture-v1",
                    input_tokens=0,
                    output_tokens=0,
                    cost_amount="0",
                    currency="USD",
                    real_model_call=False,
                )

        project_id = identifier("corrective-escalation-project")
        registry = build_chapter_handler_registry(FailedRereviewFixture())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Unresolved Cost",
                premise="The first repair does not make the consequence concrete.",
                trace_id=identifier("corrective-trace"),
                correlation_id=identifier("corrective-correlation"),
                application_build_id="corrective-escalation-test",
                commit_sha="f" * 40,
                idempotency_key=(
                    f"{project_id}:quality-correction:caller-marker:chapter:1"
                ),
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="corrective-fixture-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            if tick.node == ChapterNode.REREVIEW.value:
                break
        else:
            self.fail("Chapter rereview did not execute")
        self.assertEqual(tick.node, ChapterNode.REREVIEW.value)

        corrective = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id, issue_type="COST_NOT_CONCRETE"
        )
        self.assertEqual(len(corrective), 1)
        self.assertEqual(corrective[0]["status"], "ESCALATED")
        self.assertEqual(corrective[0]["gate_result"], "FAILED")
        self.assertEqual(corrective[0]["resolution"], "ESCALATED")

    def test_quality_issue_executes_bounded_revision_and_resolves_after_reevaluation(
        self,
    ) -> None:
        project_id = identifier("quality-correction-project")
        provider = QualityCorrectionFixture(correction_resolves=True)
        registry = build_chapter_handler_registry(provider)
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="A Corrected Timeline",
                premise="Quality evidence orders a bounded correction.",
                trace_id=identifier("quality-correction-trace"),
                correlation_id=identifier("quality-correction-correlation"),
                application_build_id="quality-correction-test",
                commit_sha="f" * 40,
                idempotency_key=(
                    f"{project_id}:quality-correction:caller-marker:chapter:1"
                ),
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-correction-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        corrective = []
        for _ in range(48):
            scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            corrective = CorrectiveActionQuery(DATABASE_URL).list(
                project_id=project_id, issue_type="canon_consistency"
            )
            if corrective and corrective[0]["status"] == "RESOLVED":
                break
        else:
            self.fail("Quality correction did not reach authoritative re-evaluation")
        self.assertEqual(len(corrective), 1)
        self.assertEqual(corrective[0]["status"], "RESOLVED")
        self.assertEqual(corrective[0]["gate_result"], "PASSED")
        self.assertTrue(corrective[0]["execution_operation_id"])
        self.assertTrue(corrective[0]["execution_attempt_id"])
        self.assertTrue(corrective[0]["result_asset_version_ids"])
        self.assertTrue(corrective[0]["evaluation_operation_id"])
        self.assertEqual(corrective[0]["lifecycle"][-1], "RESOLVED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT definition_name, COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND idempotency_key LIKE '%%:quality-correction:1'
                GROUP BY definition_name
                ORDER BY definition_name
                """,
                [admission.root_operation_id],
            )
            correction_counts = dict(cursor.fetchall())
        self.assertEqual(correction_counts[ChapterNode.REVISION.definition_name], 1)
        self.assertEqual(correction_counts[ChapterNode.REREVIEW.definition_name], 1)
        self.assertEqual(correction_counts[ChapterNode.QUALITY.definition_name], 1)
        expected_correction_nodes = {
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.CANON_EXTRACTION,
            ChapterNode.CANON_PROPOSAL,
            ChapterNode.CANON,
            *QUALITY_GROUP_NODES,
            ChapterNode.QUALITY,
        }
        self.assertEqual(
            set(correction_counts),
            {node.definition_name for node in expected_correction_nodes},
        )
        self.assertTrue(all(count == 1 for count in correction_counts.values()))
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(rereview.input_asset_snapshot) input(value)
                  JOIN authority_operation_output_asset AS revision_output
                    ON revision_output.operation_id=revision.operation_id
                   AND revision_output.role='primary'
                   AND revision_output.asset_version_id=
                       input.value->>'asset_version_id'
                )
                FROM authority_operation AS revision
                JOIN authority_operation AS rereview
                  ON rereview.root_operation_id=revision.root_operation_id
                 AND rereview.definition_name=%s
                 AND rereview.idempotency_key LIKE '%%:quality-correction:1'
                WHERE revision.root_operation_id=%s
                  AND revision.definition_name=%s
                  AND revision.idempotency_key LIKE '%%:quality-correction:1'
                """,
                [
                    ChapterNode.REREVIEW.definition_name,
                    admission.root_operation_id,
                    ChapterNode.REVISION.definition_name,
                ],
            )
            self.assertTrue(cursor.fetchone()[0])

    def test_canon_block_becomes_one_bounded_quality_correction_without_retry(
        self,
    ) -> None:
        project_id = identifier("canon-quality-correction-project")
        registry = build_chapter_handler_registry(
            CanonConflictQualityCorrectionFixture()
        )
        root_key = f"{project_id}:chapter:1"
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="A Cost Bound to Canon",
                premise="A governed exception must expose and pay its exact cost.",
                trace_id=identifier("canon-quality-trace"),
                correlation_id=identifier("canon-quality-correlation"),
                application_build_id="canon-quality-correction-test",
                commit_sha="f" * 40,
                idempotency_key=root_key,
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="canon-quality-correction-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )

        for _ in range(80):
            terminal = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        else:
            self.fail("Canon-blocked quality correction did not complete")

        corrective = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id,
            issue_type="canon_consistency",
        )
        self.assertTrue(corrective)
        self.assertTrue(all(item["status"] == "RESOLVED" for item in corrective))
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, COUNT(attempt.attempt_id),
                       array_agg(attempt.status ORDER BY attempt.attempt_number),
                       version.content
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id=operation.operation_id
                 AND binding.role='primary'
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.idempotency_key=%s
                GROUP BY operation.status, version.content
                """,
                [admission.root_operation_id, f"{root_key}:quality"],
            )
            initial_status, attempt_count, attempt_statuses, initial_quality = (
                cursor.fetchone()
            )
            cursor.execute(
                """
                SELECT version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id=operation.operation_id
                 AND binding.role='primary'
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.idempotency_key=%s
                """,
                [
                    admission.root_operation_id,
                    f"{root_key}:quality:quality-correction:1",
                ],
            )
            corrected_quality = cursor.fetchone()[0]

        self.assertEqual(initial_status, "SUCCEEDED")
        self.assertEqual(attempt_count, 1)
        self.assertEqual(attempt_statuses, ["SUCCEEDED"])
        self.assertEqual(initial_quality["gate"], "FAILED")
        self.assertEqual(
            initial_quality["decision_chain"]["source_gate_failures"]["canon"],
            "BLOCKED",
        )
        self.assertNotEqual(corrected_quality["gate"], "FAILED")

    def test_quality_issue_escalates_when_bounded_reevaluation_still_fails(
        self,
    ) -> None:
        project_id = identifier("quality-correction-escalation-project")
        registry = build_chapter_handler_registry(
            QualityCorrectionFixture(correction_resolves=False)
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Escalated Timeline",
                premise="A bounded correction retains an evidenced contradiction.",
                trace_id=identifier("quality-escalation-trace"),
                correlation_id=identifier("quality-escalation-correlation"),
                application_build_id="quality-escalation-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-escalation-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        corrective = []
        for _ in range(48):
            scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            corrective = CorrectiveActionQuery(DATABASE_URL).list(
                project_id=project_id, issue_type="canon_consistency"
            )
            if corrective and corrective[0]["status"] == "ESCALATED":
                break
        else:
            self.fail("Quality correction did not reach authoritative escalation")
        self.assertEqual(len(corrective), 1)
        self.assertEqual(corrective[0]["gate_result"], "FAILED")
        self.assertTrue(corrective[0]["execution_operation_id"])
        self.assertTrue(corrective[0]["result_asset_version_ids"])
        self.assertTrue(corrective[0]["evaluation_operation_id"])
        self.assertEqual(corrective[0]["lifecycle"][-1], "ESCALATED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT definition_name, COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND idempotency_key LIKE '%%:quality-correction:1'
                GROUP BY definition_name
                """,
                [admission.root_operation_id],
            )
            before_replay = dict(cursor.fetchall())
        scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT definition_name, COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND idempotency_key LIKE '%%:quality-correction:1'
                GROUP BY definition_name
                """,
                [admission.root_operation_id],
            )
            after_replay = dict(cursor.fetchall())
        self.assertEqual(before_replay, after_replay)

    def test_quality_correction_recovers_same_attempt_and_rejects_stale_fence(
        self,
    ) -> None:
        project_id, admission, registry = self._crash_quality_correction(
            "quality-correction-recovery"
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.operation_id, operation.version,
                       attempt.attempt_id, lease.fencing_token
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id=attempt.attempt_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name=%s
                  AND operation.idempotency_key LIKE '%%:quality-correction:1'
                ORDER BY lease.fencing_token DESC
                LIMIT 1
                """,
                [admission.root_operation_id, ChapterNode.REVISION.definition_name],
            )
            operation_id, crashed_version, attempt_id, stale_fence = cursor.fetchone()
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at=NOW()-INTERVAL '2 seconds',
                    heartbeat_at=NOW()-INTERVAL '2 seconds',
                    expires_at=NOW()-INTERVAL '1 second'
                WHERE attempt_id=%s AND released_at IS NULL
                """,
                [attempt_id],
            )
        recovered = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-correction-recovery-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        ).tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(recovered.node, ChapterNode.REVISION.value)
        self.assertEqual(recovered.operation_status, "SUCCEEDED")
        self.assertEqual(recovered.recovery_mode, "quality_correction_lease_takeover")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(DISTINCT operation.operation_id),
                       COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT output.asset_version_id),
                       MAX(lease.fencing_token)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id=attempt.attempt_id
                LEFT JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.role='primary'
                WHERE operation.operation_id=%s
                """,
                [operation_id],
            )
            operation_count, attempt_count, output_count, current_fence = (
                cursor.fetchone()
            )
        self.assertEqual((operation_count, attempt_count, output_count), (1, 1, 1))
        self.assertGreater(current_fence, stale_fence)
        with self.assertRaises(KernelError) as caught:
            submit_attempt_result(
                DATABASE_URL,
                WorkerResultCommand(
                    attempt_id=attempt_id,
                    project_id=project_id,
                    worker_id="quality-correction-crashed-worker",
                    fencing_token=stale_fence,
                    trace_id=identifier("stale-quality-trace"),
                    correlation_id=identifier("stale-quality-correlation"),
                    causation_id=operation_id,
                    expected_operation_version=crashed_version,
                    expected_operation_status="EXECUTING",
                ),
                outcome="success",
                result={"value": "must-not-commit"},
            )
        self.assertEqual(caught.exception.code, "ATTEMPT_FENCING_TOKEN_STALE")

    def test_quality_correction_retry_exhaustion_is_authoritative_failed(self) -> None:
        class RetryExhaustedFixture(QualityCorrectionFixture):
            def __init__(self) -> None:
                super().__init__(correction_resolves=True)
                self.correction_calls = 0

            def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
                if stage == "revision" and "quality" in payload:
                    self.correction_calls += 1
                    raise KernelError(
                        "MODEL_EFFECT_RETRYABLE_CORRECTION",
                        "fixture correction remains retryable",
                    )
                return super().invoke(request, stage=stage, payload=payload)

        project_id = identifier("quality-correction-dead-letter-project")
        provider = RetryExhaustedFixture()
        registry = build_chapter_handler_registry(provider)
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Exhausted Correction",
                premise="Retry exhaustion remains visible in corrective Authority.",
                trace_id=identifier("quality-dead-letter-trace"),
                correlation_id=identifier("quality-dead-letter-correlation"),
                application_build_id="quality-dead-letter-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-dead-letter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        corrective = []
        terminal_tick = None
        for _ in range(48):
            try:
                terminal_tick = scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
            except KernelError:
                pass
            corrective = CorrectiveActionQuery(DATABASE_URL).list(
                project_id=project_id, issue_type="canon_consistency"
            )
            if corrective and corrective[0]["status"] == "FAILED":
                break
        else:
            self.fail("Quality correction retry exhaustion was not authoritative")
        self.assertEqual(corrective[0]["resolution"], "FAILED")
        self.assertTrue(corrective[0]["execution_operation_id"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status,
                       (definition_snapshot->'retry_policy'->>'max_attempts')::int,
                       COUNT(attempt.attempt_id)
                FROM authority_operation AS operation
                LEFT JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                GROUP BY operation.operation_id
                """,
                [corrective[0]["execution_operation_id"]],
            )
            operation_status, max_attempts, attempt_count = cursor.fetchone()
        self.assertEqual(operation_status, "DEAD_LETTER")
        self.assertEqual(provider.correction_calls, max_attempts)
        self.assertEqual(attempt_count, max_attempts)
        self.assertIsNotNone(terminal_tick)
        self.assertEqual(terminal_tick.saga_status, "MANUAL_INTERVENTION")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, operation.version,
                       saga.status, saga.version,
                       (SELECT COUNT(*) FROM state_event
                        WHERE aggregate_id=operation.operation_id)
                FROM authority_operation AS operation
                JOIN authority_saga AS saga
                  ON saga.root_operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [admission.root_operation_id],
            )
            terminal_state = cursor.fetchone()
        self.assertEqual(
            (terminal_state[0], terminal_state[2]),
            ("FAILED_FINAL", "MANUAL_INTERVENTION"),
        )
        self.assertNotIn(
            (project_id, admission.root_operation_id), scheduler.pending_roots()
        )
        replay = scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(replay.saga_status, "MANUAL_INTERVENTION")
        self.assertEqual(replay.recovery_mode, "terminal_replay")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, operation.version,
                       saga.status, saga.version,
                       (SELECT COUNT(*) FROM state_event
                        WHERE aggregate_id=operation.operation_id)
                FROM authority_operation AS operation
                JOIN authority_saga AS saga
                  ON saga.root_operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone(), terminal_state)

    def test_canon_extraction_forward_recovery_exhaustion_dead_letters(self) -> None:
        class CanonExtractionRetryExhaustedFixture(DeterministicFixtureChapterProvider):
            supports_semantic_extraction = True

            def __init__(self) -> None:
                self.canon_extraction_calls = 0

            def invoke(self, request, *, stage, payload):  # type: ignore[no-untyped-def]
                if stage == "canon_extraction":
                    self.canon_extraction_calls += 1
                    raise KernelError(
                        "MODEL_EFFECT_RETRYABLE_CANON_EXTRACTION",
                        "fixture Canon extraction remains retryable",
                    )
                return super().invoke(request, stage=stage, payload=payload)

        project_id = identifier("canon-extraction-dead-letter-project")
        provider = CanonExtractionRetryExhaustedFixture()
        registry = build_chapter_handler_registry(provider)
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Exhausted Canon Extraction",
                premise="Retry exhaustion remains visible in Chapter Authority.",
                trace_id=identifier("canon-dead-letter-trace"),
                correlation_id=identifier("canon-dead-letter-correlation"),
                application_build_id="canon-dead-letter-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(self._release_evidence(project_id)),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="canon-dead-letter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        operation_state = None
        for _ in range(48):
            try:
                scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
            except KernelError:
                pass
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation.status,
                           (operation.definition_snapshot->'retry_policy'->>'max_attempts')::int,
                           COUNT(attempt.attempt_id)
                    FROM authority_operation AS operation
                    LEFT JOIN authority_attempt AS attempt
                      ON attempt.operation_id=operation.operation_id
                    WHERE operation.root_operation_id=%s
                      AND operation.definition_name=%s
                    GROUP BY operation.operation_id
                    """,
                    [
                        admission.root_operation_id,
                        ChapterNode.CANON_EXTRACTION.definition_name,
                    ],
                )
                operation_state = cursor.fetchone()
            if operation_state is not None and operation_state[0] == "DEAD_LETTER":
                break
        else:
            self.fail("Canon extraction retry exhaustion was not authoritative")

        operation_status, max_attempts, attempt_count = operation_state
        self.assertEqual(operation_status, "DEAD_LETTER")
        self.assertEqual(provider.canon_extraction_calls, max_attempts)
        self.assertEqual(attempt_count, max_attempts)

    def test_quality_correction_cancellation_is_authoritative_cancelled(self) -> None:
        project_id, admission, registry = self._crash_quality_correction(
            "quality-correction-cancel"
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.operation_id, operation.version,
                       attempt.attempt_id
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name=%s
                  AND operation.idempotency_key LIKE '%%:quality-correction:1'
                """,
                [admission.root_operation_id, ChapterNode.REVISION.definition_name],
            )
            operation_id, operation_version, attempt_id = cursor.fetchone()
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at=NOW()-INTERVAL '2 seconds',
                    heartbeat_at=NOW()-INTERVAL '2 seconds',
                    expires_at=NOW()-INTERVAL '1 second'
                WHERE attempt_id=%s AND released_at IS NULL
                """,
                [attempt_id],
            )
        request_cancellation(
            DATABASE_URL,
            CancelCommand(
                operation_id=operation_id,
                project_id=project_id,
                actor_id="quality-correction-operator",
                reason="cancel bounded correction",
                expected_version=operation_version,
                idempotency_key=identifier("quality-correction-cancel-command"),
                trace_id=identifier("quality-correction-cancel-trace"),
                correlation_id=identifier("quality-correction-cancel-correlation"),
            ),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-correction-cancel-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        cancelled = scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(cancelled.operation_status, "CANCELLED")
        self.assertEqual(cancelled.saga_status, "CANCELLED")
        corrective = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id, issue_type="canon_consistency"
        )
        self.assertEqual(corrective[0]["status"], "CANCELLED")
        self.assertEqual(corrective[0]["resolution"], "CANCELLED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, saga.status
                FROM authority_operation AS operation
                JOIN authority_saga AS saga
                  ON saga.root_operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone(), ("CANCELLED", "CANCELLED"))
        self.assertNotIn(
            (project_id, admission.root_operation_id), scheduler.pending_roots()
        )

    def test_downstream_rereview_retry_exhaustion_is_authoritative_failed(
        self,
    ) -> None:
        provider = DownstreamRetryExhaustedFixture()
        project_id, admission, _registry, scheduler, _action = (
            self._quality_action_ready(
                "quality-rereview-dead-letter",
                provider=provider,
            )
        )
        corrective = []
        for _ in range(48):
            try:
                scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
            except KernelError:
                pass
            corrective = CorrectiveActionQuery(DATABASE_URL).list(
                project_id=project_id, issue_type="canon_consistency"
            )
            if corrective and corrective[0]["status"] == "FAILED":
                break
        else:
            self.fail("downstream re-review failure was not authoritative")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision.status, rereview.status,
                       (rereview.definition_snapshot->'retry_policy'->>'max_attempts')::int,
                       COUNT(attempt.attempt_id)
                FROM authority_operation AS revision
                JOIN authority_operation AS rereview
                  ON rereview.root_operation_id=revision.root_operation_id
                 AND rereview.definition_name=%s
                 AND rereview.idempotency_key LIKE '%%:quality-correction:1'
                LEFT JOIN authority_attempt AS attempt
                  ON attempt.operation_id=rereview.operation_id
                WHERE revision.operation_id=%s
                GROUP BY revision.status, rereview.operation_id
                """,
                [
                    ChapterNode.REREVIEW.definition_name,
                    corrective[0]["execution_operation_id"],
                ],
            )
            revision_status, rereview_status, max_attempts, attempt_count = (
                cursor.fetchone()
            )
        self.assertEqual(revision_status, "SUCCEEDED")
        self.assertEqual(rereview_status, "DEAD_LETTER")
        self.assertEqual(provider.correction_rereview_calls, max_attempts)
        self.assertEqual(attempt_count, max_attempts)
        self.assertTrue(corrective[0]["evaluation_operation_id"])
        self.assertEqual(corrective[0]["resolution"], "FAILED")

    def test_downstream_rereview_cancellation_is_authoritative_cancelled(
        self,
    ) -> None:
        project_id, admission, registry = self._crash_quality_correction(
            "quality-rereview-cancel", after_revision=True
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.operation_id, operation.version, attempt.attempt_id
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name=%s
                  AND operation.idempotency_key LIKE '%%:quality-correction:1'
                """,
                [admission.root_operation_id, ChapterNode.REREVIEW.definition_name],
            )
            operation_id, operation_version, attempt_id = cursor.fetchone()
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET acquired_at=NOW()-INTERVAL '2 seconds',
                    heartbeat_at=NOW()-INTERVAL '2 seconds',
                    expires_at=NOW()-INTERVAL '1 second'
                WHERE attempt_id=%s AND released_at IS NULL
                """,
                [attempt_id],
            )
        request_cancellation(
            DATABASE_URL,
            CancelCommand(
                operation_id=operation_id,
                project_id=project_id,
                actor_id="quality-rereview-operator",
                reason="cancel bounded correction re-review",
                expected_version=operation_version,
                idempotency_key=identifier("quality-rereview-cancel-command"),
                trace_id=identifier("quality-rereview-cancel-trace"),
                correlation_id=identifier("quality-rereview-cancel-correlation"),
            ),
        )
        cancelled = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-rereview-cancel-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        ).tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        self.assertEqual(cancelled.operation_status, "CANCELLED")
        corrective = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id, issue_type="canon_consistency"
        )
        self.assertEqual(corrective[0]["status"], "CANCELLED")
        self.assertEqual(corrective[0]["resolution"], "CANCELLED")
        self.assertEqual(corrective[0]["evaluation_operation_id"], operation_id)

    def test_superseded_quality_action_is_not_executed(self) -> None:
        project_id, admission, _registry, scheduler, action = (
            self._quality_action_ready("quality-correction-superseded")
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_asset_version
                SET lifecycle='SUPERSEDED'
                WHERE asset_version_id=%s AND lifecycle='ACTIVE'
                """,
                [action["action_asset_version_id"]],
            )
            self.assertEqual(cursor.rowcount, 1)
        projected = CorrectiveActionQuery(DATABASE_URL).list(
            project_id=project_id, issue_type="canon_consistency"
        )
        self.assertEqual(projected[0]["status"], "SUPERSEDED")
        scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND idempotency_key LIKE '%%:quality-correction:1'
                """,
                [admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_active_quality_actions_execute_when_a_sibling_is_superseded(
        self,
    ) -> None:
        project_id, admission, _registry, scheduler, _action = (
            self._quality_action_ready(
                "quality-correction-partial-supersession",
                provider=TwoActionQualityCorrectionFixture(correction_resolves=True),
                excluded_quality_dimensions=frozenset({"timeline_consistency"}),
            )
        )
        actions = [
            item
            for item in CorrectiveActionQuery(DATABASE_URL).list(project_id=project_id)
            if item["issue_type"] in {"canon_consistency", "timeline_consistency"}
        ]
        self.assertEqual(
            {item["issue_type"] for item in actions},
            {"canon_consistency", "timeline_consistency"},
        )
        superseded = next(
            item for item in actions if item["issue_type"] == "canon_consistency"
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_asset_version
                SET lifecycle='SUPERSEDED'
                WHERE asset_version_id=%s AND lifecycle='ACTIVE'
                """,
                [superseded["action_asset_version_id"]],
            )
            self.assertEqual(cursor.rowcount, 1)
        for _ in range(24):
            scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            projected = [
                item
                for item in CorrectiveActionQuery(DATABASE_URL).list(
                    project_id=project_id
                )
                if item["issue_type"] in {"canon_consistency", "timeline_consistency"}
            ]
            if {item["status"] for item in projected} == {
                "RESOLVED",
                "SUPERSEDED",
            }:
                break
        else:
            self.fail("remaining active Quality action was not resolved")
        by_issue = {item["issue_type"]: item for item in projected}
        self.assertEqual(by_issue["canon_consistency"]["status"], "SUPERSEDED")
        self.assertEqual(by_issue["timeline_consistency"]["status"], "RESOLVED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content->'quality_action_observations'
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.role='primary'
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name=%s
                  AND operation.idempotency_key LIKE '%%:quality-correction:1'
                """,
                [admission.root_operation_id, ChapterNode.REVISION.definition_name],
            )
            self.assertEqual(cursor.fetchone()[0], ["timeline_consistency"])

    def _crash_quality_correction(
        self, slug: str, *, after_revision: bool = False
    ) -> tuple[str, object, object]:
        project_id, admission, registry, scheduler, _action = (
            self._quality_action_ready(slug)
        )
        if after_revision:
            revised = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            self.assertEqual(revised.node, ChapterNode.REVISION.value)
            self.assertEqual(revised.operation_status, "SUCCEEDED")

        triggered = False

        def crash(checkpoint: str) -> None:
            nonlocal triggered
            if checkpoint == "after_domain_asset_materialized" and not triggered:
                triggered = True
                raise SimulatedQualityCorrectionCrash(checkpoint)

        crashing = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="quality-correction-crashed-worker",
            permissions=frozenset({"chapter.authority.execute"}),
            fault_injector=crash,
        )
        with self.assertRaises(SimulatedQualityCorrectionCrash):
            crashing.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
        self.assertTrue(triggered)
        return project_id, admission, registry

    def _quality_action_ready(
        self,
        slug: str,
        *,
        provider: QualityCorrectionFixture | None = None,
        excluded_quality_dimensions: frozenset[str] = frozenset(),
    ) -> tuple[str, object, object, ChapterAuthorityScheduler, dict[str, object]]:
        project_id = identifier(f"{slug}-project")
        registry = build_chapter_handler_registry(
            provider or QualityCorrectionFixture(correction_resolves=True)
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="A Recoverable Correction",
                premise="A bounded correction survives its execution boundary.",
                trace_id=identifier(f"{slug}-trace"),
                correlation_id=identifier(f"{slug}-correlation"),
                application_build_id=f"{slug}-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(
                    self._release_evidence(
                        project_id,
                        excluded_dimensions=excluded_quality_dimensions,
                    )
                ),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id=f"{slug}-initial-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in range(24):
            scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            corrective = CorrectiveActionQuery(DATABASE_URL).list(
                project_id=project_id, issue_type="canon_consistency"
            )
            if corrective and corrective[0]["status"] == "ADMITTED":
                break
        else:
            self.fail("initial Quality action was not admitted")
        return project_id, admission, registry, scheduler, corrective[0]

    def test_uncalibrated_fixture_is_a_successful_publish_block(self) -> None:
        project_id = identifier("uncalibrated-publish-block-project")
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id="trusted-operator",
                chapter=1,
                title="An Honest Fixture",
                premise="Fixture evidence cannot become production proof.",
                trace_id=identifier("uncalibrated-trace"),
                correlation_id=identifier("uncalibrated-correlation"),
                application_build_id="uncalibrated-fixture-test",
                commit_sha="f" * 40,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(
                    self._release_evidence(project_id, with_waiver=False)
                ),
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="uncalibrated-fixture-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            if tick.node == ChapterNode.PUBLISH_GATE.value:
                break
        else:
            self.fail("uncalibrated fixture did not reach Publish Gate")

        quality, publish_gate = self._quality_and_publish_gate(
            admission.root_operation_id
        )
        self.assertEqual(quality["gate"], "PASSED_WITH_UNCALIBRATED")
        self.assertEqual(publish_gate["gate"], "PUBLISH_GATE_BLOCKED")
        self.assertEqual(publish_gate["release_readiness"], "BLOCKED")
        self.assertFalse(publish_gate["external_publish_permitted"])
        self.assertFalse(publish_gate["production_verified"])

    def test_preparation_command_runs_through_async_context_and_full_saga(self) -> None:
        project_id = identifier("prepared-async-project")
        self._preparation_assets(project_id)
        prepared = ProductionPreparationService(
            PostgresProductionAssetResolver(DATABASE_URL)
        ).prepare(
            ProductionPreparationRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                chapter=1,
                idempotency_key=f"{project_id}:chapter:1",
            )
        )
        self.assertEqual(prepared.report.decision, "READY")
        self.assertIsNotNone(prepared.command)
        command = prepared.command
        assert command is not None
        self.assertTrue(
            all(item["project_id"] == project_id for item in command.context_candidates)
        )
        registry = build_chapter_handler_registry(DeterministicFixtureChapterProvider())
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=SingleChapterRequest(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                actor_id="trusted-operator",
                chapter=command.chapter,
                title=command.title,
                premise=command.premise,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                application_build_id="prepared-async-test",
                commit_sha="f" * 40,
                idempotency_key=command.idempotency_key,
                preparation_report=command.preparation_report,
                context_candidates=command.context_candidates,
                context_version_refs=command.context_version_refs,
                context_token_budget=command.context_token_budget,
            ),
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-prepared-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in ChapterNode:
            scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
        terminal = scheduler.tick(
            project_id=project_id, root_operation_id=admission.root_operation_id
        )
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS binding
                  ON binding.operation_id = operation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND operation.definition_name = 'chapter.plan.materialize'
                  AND binding.output_key = 'chapter.plan'
                """,
                [admission.root_operation_id],
            )
            authoritative_plan = cursor.fetchone()[0]
        self.assertEqual(
            authoritative_plan["source_chapter_plan_asset_version_id"],
            command.chapter_plan_asset_version_id,
        )
        self.assertEqual(
            authoritative_plan["source_chapter_plan_content_hash"],
            command.chapter_plan_content_hash,
        )

    def test_chapter_two_rejects_missing_accepted_narrative_state(
        self,
    ) -> None:
        project_id = identifier("prepared-missing-state-project")
        self._preparation_assets(project_id, chapter=2)
        prepared = ProductionPreparationService(
            PostgresProductionAssetResolver(DATABASE_URL)
        ).prepare(
            ProductionPreparationRequest(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                book_id=f"book:{project_id}",
                chapter=2,
                idempotency_key=f"{project_id}:chapter:2",
                context_token_budget=6_000,
            )
        )
        self.assertEqual(prepared.report.decision, "BLOCKED")
        self.assertIsNone(prepared.command)
        self.assertEqual(
            set(prepared.report.missing_required_asset_types),
            set(CONTINUING_CHAPTER_REQUIRED_ASSET_TYPES),
        )
        self.assertTrue(prepared.report.repair_actions)

    def test_high_impact_canon_waits_for_approved_decision_asset(self) -> None:

        project_id = identifier("canon-gate-project")
        candidates = self._release_evidence(project_id)
        registry = build_chapter_handler_registry(GroundedHighImpactFixture())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Canon Gate",
            premise="A costly choice changes an identity permanently.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="canon-gate-test",
            commit_sha="d" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(candidates),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        waiting = None
        for _ in ChapterNode:
            tick = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if tick.saga_status == "WAITING_GATE":
                waiting = tick
                break
        self.assertIsNotNone(waiting)
        approvals = list_canon_approvals(DATABASE_URL, project_id=project_id)
        self.assertEqual(len(approvals), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s",
                [admission.root_operation_id, ChapterNode.CANON.definition_name],
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        decision = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"],
            decision="APPROVE",
            reason="fixture proves per-change gate recovery",
            evidence={"fixture": True},
            edited_payload=None,
            idempotency_key="approve-once",
        )
        self.assertTrue(decision["gate_resumed"])
        self.assertTrue(decision["decision_operation_id"])
        replay = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approvals[0]["approval_request_id"],
            expected_version=approvals[0]["version"],
            decision="APPROVE",
            reason="fixture proves per-change gate recovery",
            evidence={"fixture": True},
            edited_payload=None,
            idempotency_key="approve-once",
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            replay["decision_operation_id"], decision["decision_operation_id"]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, attempt.status, decision.decision_operation_id
                FROM authority_operation operation
                JOIN authority_attempt attempt ON attempt.operation_id = operation.operation_id
                JOIN authority_canon_approval_decision decision
                  ON decision.decision_operation_id = operation.operation_id
                WHERE operation.operation_id = %s
                """,
                [decision["decision_operation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("SUCCEEDED", "SUCCEEDED", decision["decision_operation_id"]),
            )
        terminal = None
        for _ in range(30):
            terminal = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT version.content FROM authority_operation_output_asset binding JOIN authority_asset_version version ON version.asset_version_id = binding.asset_version_id JOIN authority_asset asset ON asset.asset_id = version.asset_id WHERE binding.operation_id IN (SELECT operation_id FROM authority_operation WHERE root_operation_id = %s AND definition_name = %s) AND asset.asset_type = 'canon_patch'",
                [admission.root_operation_id, ChapterNode.CANON.definition_name],
            )
            canon_patch = cursor.fetchone()[0]
        character = canon_patch["state_changes"]["character_state"][0]
        self.assertEqual(character["status"], "dead")
        self.assertEqual(
            character["approval_resolution"]["approval_decision_asset_version_id"],
            decision["asset_version_id"],
        )

    def test_deferred_canon_approval_reopens_without_bypassing_gate(self) -> None:
        project_id, request, admission, scheduler = self._high_impact_waiting_fixture(
            "canon-defer"
        )
        approval = list_canon_approvals(DATABASE_URL, project_id=project_id)[0]
        deferred = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"],
            decision="DEFER",
            reason="need a continuity packet",
            evidence={
                "defer_until": "2999-07-18T00:00:00+00:00",
                "required_information": "continuity packet",
                "assigned_operator": "chief-editor",
                "expiry_policy": "REOPEN",
            },
            edited_payload=None,
            idempotency_key="defer-once",
        )
        self.assertFalse(deferred["gate_resumed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id=%s",
                [admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "WAITING_GATE")
        reopened = reopen_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 1,
            reason="continuity packet supplied",
            idempotency_key="reopen-once",
        )
        self.assertEqual(reopened["status"], "PENDING")
        replay = reopen_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 1,
            reason="continuity packet supplied",
            idempotency_key="reopen-once",
        )
        self.assertTrue(replay["replayed"])
        with self.assertRaisesRegex(KernelError, "CANON_APPROVAL_VERSION_CONFLICT"):
            reopen_canon_approval(
                DATABASE_URL,
                CanonApprovalContext(
                    project_id,
                    "local-operator",
                    request.trace_id,
                    request.correlation_id,
                ),
                approval_request_id=approval["approval_request_id"],
                expected_version=approval["version"] + 1,
                reason="stale reopen",
                idempotency_key="reopen-stale",
            )
        deferred_again = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=approval["approval_request_id"],
            expected_version=approval["version"] + 2,
            decision="DEFER",
            reason="wait for automatic expiry",
            evidence={
                "defer_until": "2999-07-19T00:00:00+00:00",
                "required_information": "expiry fixture",
                "assigned_operator": "chief-editor",
                "expiry_policy": "REOPEN",
            },
            edited_payload=None,
            idempotency_key="defer-for-expiry",
        )
        self.assertFalse(deferred_again["gate_resumed"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_canon_approval_request SET defer_until=NOW() - INTERVAL '1 second' WHERE approval_request_id=%s",
                [approval["approval_request_id"]],
            )
        expired = expire_deferred_canon_approvals(
            DATABASE_URL,
            CanonApprovalContext(
                project_id,
                "system-scheduler",
                request.trace_id,
                request.correlation_id,
            ),
        )
        self.assertEqual(expired[0]["status"], "PENDING")

    def test_request_reextraction_supersedes_old_proposal_and_recovers_gate(
        self,
    ) -> None:
        project_id, request, admission, scheduler = self._high_impact_waiting_fixture(
            "canon-reextract"
        )
        old = list_canon_approvals(DATABASE_URL, project_id=project_id)[0]
        decision = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=old["approval_request_id"],
            expected_version=old["version"],
            decision="REQUEST_REEXTRACTION",
            reason="evidence needs a clean semantic pass",
            evidence={"fixture_protocol_only": True},
            edited_payload=None,
            idempotency_key="reextract-once",
        )
        self.assertTrue(decision["reextraction_requested"])
        self.assertFalse(decision["gate_resumed"])
        for _ in range(8):
            scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            approvals = list_canon_approvals(DATABASE_URL, project_id=project_id)
            pending = [item for item in approvals if item["status"] == "PENDING"]
            if pending and pending[0]["proposal_generation"] == 2:
                break
        else:
            self.fail("re-extraction did not produce a generation-2 approval")
        invalidated = [item for item in approvals if item["proposal_generation"] == 1]
        self.assertTrue(invalidated)
        self.assertTrue(all(item["status"] == "INVALIDATED" for item in invalidated))
        new_approval = pending[0]
        self.assertNotEqual(
            new_approval["proposal_asset_version_id"], old["proposal_asset_version_id"]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT step_key FROM authority_saga_step WHERE saga_id=%s AND step_key LIKE 'canon_%%:g2' ORDER BY step_key",
                [admission.saga_id],
            )
            self.assertEqual(
                [row[0] for row in cursor.fetchall()],
                ["canon_extraction:g2", "canon_proposal:g2"],
            )
            cursor.execute(
                "SELECT policy_snapshot->>'policy_version', extraction_digest, proposal_digest, change_set_digest, no_progress_count FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s",
                [project_id, admission.root_operation_id],
            )
            governance = cursor.fetchone()
            self.assertEqual(governance[0], "canon-reextraction-policy-v1")
            self.assertTrue(
                all(str(value).startswith("sha256:") for value in governance[1:4])
            )
            self.assertEqual(governance[4], 1)
        approved = decide_canon_approval(
            DATABASE_URL,
            CanonApprovalContext(
                project_id, "local-operator", request.trace_id, request.correlation_id
            ),
            approval_request_id=new_approval["approval_request_id"],
            expected_version=new_approval["version"],
            decision="APPROVE",
            reason="generation two evidence reviewed",
            evidence={"fixture_protocol_only": True},
            edited_payload=None,
            idempotency_key="approve-generation-two",
        )
        self.assertTrue(approved["gate_resumed"])
        for _ in range(30):
            terminal = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if terminal.saga_status == "SUCCEEDED":
                break
        self.assertEqual(terminal.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM authority_canon_reextraction_generation WHERE project_id=%s AND root_operation_id=%s",
                [project_id, admission.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], "RESOLVED")

    def _high_impact_waiting_fixture(self, prefix: str):

        project_id = identifier(f"{prefix}-project")
        registry = build_chapter_handler_registry(GroundedHighImpactFixture())
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="trusted-operator",
            chapter=1,
            title="A Canon Gate",
            premise="A costly choice changes an identity permanently.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id=f"{prefix}-test",
            commit_sha="e" * 40,
            idempotency_key=f"{project_id}:chapter:1",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(self._release_evidence(project_id)),
        )
        admission = admit_single_chapter_saga(
            DATABASE_URL,
            request=request,
            registry=registry,
            permissions=frozenset({"chapter.authority.execute"}),
        )
        scheduler = ChapterAuthorityScheduler(
            DATABASE_URL,
            registry=registry,
            object_store_adapter=FakeDeterministicProvider("success"),
            worker_id="configured-chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
        )
        for _ in range(20):
            tick = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if tick.saga_status == "WAITING_GATE":
                return project_id, request, admission, scheduler
        self.fail("high-impact fixture did not reach Canon WAITING_GATE")

    @staticmethod
    def _preparation_assets(project_id: str, *, chapter: int = 1) -> None:

        def calibrated(dimensions: tuple[str, ...]) -> dict[str, object]:
            return {
                "safe_summary": "Fixture-only waived quality evidence.",
                "allowed_use": "evidence_only",
                "structured_facts": [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": item,
                                "gate_status": "WAIVED_BY_APPROVAL",
                                "calibration_status": "FIXTURE_UNCALIBRATED",
                                "human_verified": False,
                                "fixture_protocol_only": True,
                            }
                            for item in dimensions
                        ],
                    }
                ],
            }

        assets = {
            "chapter_plan": {
                "chapter": chapter,
                "title": "Prepared Chapter",
                "premise": "A prepared promise creates a visible cost.",
                "chapter_objective": "Force a public choice with a visible cost.",
                "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                "required_arc_contributions": [
                    {
                        "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                        "contribution": "ADVANCE",
                    }
                ],
                "constraint_envelope": {
                    "arc_working_set": {
                        "selected_contributions": [
                            {
                                "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                                "role": "PRIMARY",
                                "action": "ADVANCE",
                            }
                        ]
                    }
                },
                "scene_plan": [
                    {
                        "scene_id": "s1",
                        "goal": "keep the promise",
                        "conflict": "safety requires breaking the promise",
                        "arc_progress": [f"{project_id}:fixture-arc-plan-v1"],
                        "beats": ["pressure", "choice", "visible cost"],
                    }
                ],
                "chapter_hook": "The cost creates a new obligation.",
                "conflict_chain": ["promise collides with institutional safety"],
                "emotional_curve": ["resolve", "fear", "costly resolve"],
                "suspense_curve": ["question", "pressure", "new obligation"],
                "reader_promise_actions": ["test and advance the promise"],
                "protagonist_charm_mechanism": "keeps a costly promise under pressure",
                "information_reveals": ["the safe path requires betraying the promise"],
                "antagonist_pressure": "the institution closes the safe path",
                "next_chapter_bridge": "the obligation requires a new witness",
                "safe_summary": "Prepared chapter plan.",
                "structured_facts": [{"key": "chapter", "value": 1}],
            },
            "style_policy": {
                "safe_summary": "Project style policy.",
                "structured_facts": [],
            },
            "quality_rubric": {
                "safe_summary": "Project quality rubric.",
                "structured_facts": [],
            },
            "platform_profile": {
                "safe_summary": "Internal fixture platform profile.",
                "structured_facts": [{"key": "platform", "value": "fixture"}],
            },
            "operator_checklist": {
                "safe_summary": "Checklist completed.",
                "structured_facts": [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
            },
            "approval_decision": {
                "safe_summary": "Versioned fixture-only waiver approval.",
                "structured_facts": [
                    {"key": "approved", "value": True},
                    {"key": "decision", "value": "APPROVED"},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {
                        "key": "waiver_reason",
                        "value": "Exercise internal fixture release protocol.",
                    },
                    {
                        "key": "waived_dimensions",
                        "value": list(QUALITY_DIMENSIONS),
                    },
                    {
                        "key": "scope",
                        "value": {
                            "project_id": project_id,
                            "scope_type": "PROJECT_FIXTURE",
                            "release_readiness": "INTERNAL_REVIEW_RELEASE",
                        },
                    },
                    {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                    {"key": "fixture_protocol_only", "value": True},
                ],
            },
            "commercial_quality_report": calibrated(
                (
                    "golden_opening",
                    "reader_promise",
                    "reward",
                    "protagonist_charm",
                    "antagonist_pressure",
                    "toxic_point",
                    "chapter_hook",
                    "suspense_progression",
                    "emotional_curve",
                    "serialization_function",
                )
            ),
            "source_originality_quality_report": calibrated(
                (
                    "originality",
                    "anti_ai",
                    "style_drift",
                )
            ),
            "longform_quality_report": calibrated(
                (
                    "character_motivation_drift",
                    "relationship_continuity",
                    "timeline_consistency",
                    "foreshadow_status",
                    "promise_payoff_debt",
                    "world_rule_conflict",
                    "power_state_conflict",
                    "narrative_pattern_repetition",
                    "arc_progress",
                )
            ),
            "platform_quality_report": calibrated(
                (
                    "chapter_length",
                    "format",
                    "sensitive_content",
                    "ai_content_policy",
                    "opening_expectations",
                    "platform_rhythm",
                    "publish_metadata",
                )
            ),
        }
        with transaction() as connection, connection.cursor() as cursor:
            for asset_type, content in assets.items():
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                asset_id = identifier(f"{asset_type}-asset")
                version_id = identifier(asset_type)
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )

    @staticmethod
    def _release_evidence(
        project_id: str,
        *,
        with_waiver: bool = True,
        excluded_dimensions: frozenset[str] = frozenset(),
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        quality = {
            "commercial_quality_report": (
                "golden_opening",
                "reader_promise",
                "reward",
                "protagonist_charm",
                "antagonist_pressure",
                "toxic_point",
                "chapter_hook",
                "suspense_progression",
                "emotional_curve",
                "serialization_function",
            ),
            "source_originality_quality_report": (
                "originality",
                "anti_ai",
                "style_drift",
            ),
            "longform_quality_report": (
                "character_motivation_drift",
                "relationship_continuity",
                "timeline_consistency",
                "foreshadow_status",
                "promise_payoff_debt",
                "world_rule_conflict",
                "power_state_conflict",
                "narrative_pattern_repetition",
                "arc_progress",
            ),
            "platform_quality_report": (
                "chapter_length",
                "format",
                "sensitive_content",
                "ai_content_policy",
                "opening_expectations",
                "platform_rhythm",
                "publish_metadata",
            ),
        }
        evidence = [
            (
                "chapter_plan",
                "Complete authoritative ChapterPlan.",
                [],
                {
                    "project_id": project_id,
                    "chapter": 1,
                    "title": "A Durable Promise",
                    "premise": "A promise creates a visible irreversible cost.",
                    "chapter_objective": "Force a public choice with an irreversible loss.",
                    "scene_sequence": [{"scene_id": "s1", "goal": "keep the promise"}],
                    "required_arc_contributions": [
                        {
                            "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                            "contribution": "ADVANCE",
                        }
                    ],
                    "constraint_envelope": {
                        "arc_working_set": {
                            "selected_contributions": [
                                {
                                    "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                                    "role": "PRIMARY",
                                    "action": "ADVANCE",
                                }
                            ]
                        }
                    },
                    "scene_plan": [
                        {
                            "scene_id": "s1",
                            "goal": "keep the promise",
                            "conflict": "safety requires breaking the promise",
                            "arc_progress": [f"{project_id}:fixture-arc-plan-v1"],
                            "beats": ["pressure", "choice", "visible cost"],
                        }
                    ],
                    "chapter_hook": "The cost creates a new obligation.",
                },
            ),
            (
                "quality_rubric",
                "Versioned quality thresholds.",
                [{"key": "thresholds", "value": {"readability": 70}}],
                None,
            ),
            (
                "platform_profile",
                "Versioned internal platform rules.",
                [
                    {
                        "key": "platform_rules",
                        "value": {
                            "chapter_length": {"minimum": 10, "maximum": 10000},
                            "format": {"paragraph_max": 500},
                            "sensitive_content": [],
                            "ai_content": {"mode": "internal"},
                            "opening": ["visible conflict"],
                            "rhythm": ["payoff"],
                            "publish_metadata": {"title_required": True},
                        },
                    }
                ],
                None,
            ),
            (
                "operator_checklist",
                "Versioned fixture waiver checklist.",
                [
                    {"key": "completed", "value": True},
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-checklist-v1",
                    },
                ],
            ),
            (
                "operator_approval",
                "Versioned fixture-only approval decision.",
                [
                    {"key": "approved", "value": with_waiver},
                    {
                        "key": "decision",
                        "value": "APPROVED" if with_waiver else "NOT_APPROVED",
                    },
                    {
                        "key": "contract_version",
                        "value": "fixture-waiver-approval-v1",
                    },
                    {
                        "key": "waiver_reason",
                        "value": "Exercise internal fixture release protocol.",
                    },
                    {
                        "key": "waived_dimensions",
                        "value": list(QUALITY_DIMENSIONS) if with_waiver else [],
                    },
                    {
                        "key": "scope",
                        "value": {
                            "project_id": project_id,
                            "scope_type": "PROJECT_FIXTURE",
                            "release_readiness": "INTERNAL_REVIEW_RELEASE",
                        },
                    },
                    {"key": "expiry", "value": "2099-01-01T00:00:00Z"},
                    {"key": "fixture_protocol_only", "value": True},
                ],
            ),
        ]
        evidence.extend(
            (
                asset_type,
                "Honest fixture-only quality evidence.",
                [
                    {
                        "key": "dimension_evidence",
                        "value": [
                            {
                                "dimension": dimension,
                                "gate_status": (
                                    "WAIVED_BY_APPROVAL" if with_waiver else "PASSED"
                                ),
                                "calibration_status": "FIXTURE_UNCALIBRATED",
                                "human_verified": False,
                                "fixture_protocol_only": True,
                            }
                            for dimension in dimensions
                            if dimension not in excluded_dimensions
                        ],
                    }
                ],
                None,
            )
            for asset_type, dimensions in quality.items()
        )
        with transaction() as connection, connection.cursor() as cursor:
            normalized_evidence = [
                item if len(item) == 4 else (*item, None) for item in evidence
            ]
            for asset_type, summary, facts, explicit_content in normalized_evidence:
                content = explicit_content or {
                    "safe_summary": summary,
                    "structured_facts": facts,
                }
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                version_id = identifier(asset_type)
                asset_id = identifier(f"{asset_type}-asset")
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, asset_type],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1')
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
                candidates.append(
                    {
                        "asset_version_id": version_id,
                        "asset_type": asset_type,
                        "project_id": project_id,
                        "content_hash": content_hash,
                        "estimated_tokens": 20,
                        "allowed_use": "evidence_only"
                        if asset_type.endswith("quality_report")
                        else "generation",
                        "source_use_mode": "generation",
                        **content,
                        "narrative_function": "release_evidence",
                    }
                )
        return candidates

    @staticmethod
    def _quality_and_publish_gate(
        root_operation_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.definition_name, version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name IN (
                      'chapter.quality.evaluate',
                      'chapter.publishing.prepare_release'
                  )
                  AND output.output_key IN (
                      'chapter.quality', 'chapter.publish_gate'
                  )
                """,
                [root_operation_id],
            )
            values = {str(name): dict(content) for name, content in cursor.fetchall()}
        return (
            values["chapter.quality.evaluate"],
            values["chapter.publishing.prepare_release"],
        )


if __name__ == "__main__":
    unittest.main()
