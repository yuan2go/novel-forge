from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ProviderResult,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ExternalEffectChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.story_design_authority import scripted_qualification
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
)
from novel_forge.modules.story_design_authority.evaluation_execution import (
    GatewayNarrativeSemanticEvaluationExecutionPort,
)
from novel_forge.modules.runtime_job import (
    BOOK_OPENING_LEGACY_JOB_KIND,
    BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    RuntimeJobAuthority,
)
import novel_forge.modules.content_authority.scheduler as content_scheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_legacy_book_opening_claim
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_recovery_postgres_support import (
    LegacyBookOpeningOrphan,
    SimulatedBookOpeningProcessLoss,
    create_legacy_book_opening_orphan,
)


class _SyntheticSemanticProvider:
    """Complete governed-result fixture with no network or real Provider."""

    provider = "synthetic_semantic_durable_replay"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True
    capability_profile = {
        "provider": provider,
        "control_level": "FIXTURE_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": True,
        "supports_cancel": True,
        "supports_callback": False,
        "supports_usage_receipt": True,
        "supports_cost_receipt": True,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(self) -> None:
        self.invocations = 0
        self.recovery_authorizations = 0

    def for_recovery(self, **_kwargs: Any) -> "_SyntheticSemanticProvider":
        self.recovery_authorizations += 1
        return self

    def record_authorization(self) -> None:
        return None

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        self.invocations += 1
        assert capability == "model.narrative_semantic_evaluation"
        metadata = dict(request_payload.get("_production_execution") or {})
        generator_operation_name = str(
            metadata.get("generator_operation_name") or "book_plan.generate"
        )
        result = ModelProviderResult(
            output=scripted_qualification(generator_operation_name),
            provider_id=self.provider,
            model_id="synthetic-semantic-v1",
            prompt_version="synthetic-semantic-prompt-v1",
            skill_version="quality-review@synthetic-v1",
            input_tokens=17,
            output_tokens=11,
            cost_amount="0",
            currency="USD",
            real_model_call=True,
            execution_evidence={
                "execution_request": {
                    "external_effect_id": str(
                        request_payload.get("external_effect_id") or ""
                    )
                },
                "route_snapshot": {
                    "route_snapshot_id": "route:synthetic-semantic-durable-replay"
                },
                "execution_handle": {"transport": "REMOTE_PROVIDER_API"},
            },
        )
        return ProviderResult(
            "success",
            f"synthetic:{stable_idempotency_key}",
            result.to_evidence(),
            provider_request_id=f"synthetic-request:{stable_idempotency_key}",
        )

    def query(self, **_kwargs: Any) -> ProviderResult:
        raise AssertionError("synchronous synthetic success must not query")

    def cancel(self, **_kwargs: Any) -> ProviderResult:
        raise AssertionError("synchronous synthetic success must not cancel")


def _semantic_port(
    adapter: _SyntheticSemanticProvider,
    *,
    fault_injector: Any | None = None,
) -> GatewayNarrativeSemanticEvaluationExecutionPort:
    model_port = ExternalEffectChapterModelPort(
        DATABASE_URL,
        adapter=adapter,
        worker_id="synthetic-semantic-provider-worker",
        lease_seconds=30,
        max_cost_per_call="0",
        fault_injector=fault_injector,
        execution_binding_domain="narrative_evaluation",
    )
    return GatewayNarrativeSemanticEvaluationExecutionPort(
        DATABASE_URL,
        model_port=model_port,
    )


def _converge_outer_loss(orphan: LegacyBookOpeningOrphan) -> None:
    key = f"durable-success-loss:{orphan.opening_run_id}:generation-1"
    assessment = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=key,
        principal=orphan.principal,
    )
    receipt = orphan.opening.recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert receipt.result["opening_lifecycle"] == "FAILED"


def _counts(orphan: LegacyBookOpeningOrphan) -> tuple[int, int, int, int, int]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM authority_external_effect
               WHERE operation_id=%s),
              (SELECT COUNT(*)
               FROM authority_external_effect_dispatch AS dispatch
               JOIN authority_external_effect AS effect
                 ON effect.external_effect_id=dispatch.external_effect_id
               WHERE effect.operation_id=%s),
              (SELECT COUNT(*)
               FROM authority_external_receipt AS receipt
               JOIN authority_external_effect_dispatch AS dispatch
                 ON dispatch.dispatch_id=receipt.dispatch_id
               JOIN authority_external_effect AS effect
                 ON effect.external_effect_id=dispatch.external_effect_id
               WHERE effect.operation_id=%s),
              (SELECT COUNT(*) FROM authority_book_opening_recovery_intent
               WHERE opening_run_id=%s),
              (SELECT COUNT(*) FROM authority_book_opening_execution
               WHERE opening_run_id=%s AND generation > 1)
            """,
            [
                orphan.evaluation_operation_id,
                orphan.evaluation_operation_id,
                orphan.evaluation_operation_id,
                orphan.opening_run_id,
                orphan.opening_run_id,
            ],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(int(value) for value in row)  # type: ignore[return-value]


def _semantic_runtime_state(orphan: LegacyBookOpeningOrphan) -> tuple[Any, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status,attempt.status,evaluation.lifecycle,
                   COUNT(DISTINCT attempt.attempt_id),
                   COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   COUNT(DISTINCT receipt.external_receipt_id),
                   COUNT(DISTINCT model.asset_version_id),
                   COUNT(DISTINCT cost.asset_version_id),
                   COUNT(DISTINCT output.asset_version_id)
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            LEFT JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            LEFT JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            LEFT JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            LEFT JOIN authority_operation_output_asset AS model
              ON model.operation_id=operation.operation_id
             AND model.role='model_evidence'
            LEFT JOIN authority_operation_output_asset AS cost
              ON cost.operation_id=operation.operation_id
             AND cost.role='cost_evidence'
            LEFT JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
             AND output.output_key='story_design.semantic_evaluation'
             AND output.role='qualification_evidence'
            WHERE operation.operation_id=%s
            GROUP BY operation.status,attempt.status,evaluation.lifecycle
            """,
            [orphan.evaluation_operation_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(row)


def _complete_durable_success_orphan() -> tuple[
    LegacyBookOpeningOrphan, _SyntheticSemanticProvider
]:
    """Crash after gen-1 terminal/output commit but before qualification projection."""

    adapter = _SyntheticSemanticProvider()
    original = NarrativeSemanticEvaluationApplication._record_qualifications
    armed = {"value": True}

    def lose_response_after_output(
        application: NarrativeSemanticEvaluationApplication,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if armed["value"] and adapter.invocations == 1:
            armed["value"] = False
            raise SimulatedBookOpeningProcessLoss(
                "process disappeared after terminal semantic output and before qualification projection"
            )
        original(application, *args, **kwargs)

    with patch.object(
        NarrativeSemanticEvaluationApplication,
        "_record_qualifications",
        new=lose_response_after_output,
    ):
        orphan = create_legacy_book_opening_orphan(
            semantic_evaluation_execution_port=_semantic_port(adapter),
            terminalize_evaluation=False,
        )
    return orphan, adapter


def _semantic_command(
    orphan: LegacyBookOpeningOrphan,
) -> NarrativeSemanticEvaluationCommand:
    command = orphan.evaluation_command
    return NarrativeSemanticEvaluationCommand(
        project_id=command.project_id,
        workspace_id=command.workspace_id,
        book_id=command.book_id,
        actor_id=command.actor_id,
        candidate_asset_version_id=command.candidate_asset_version_id,
        generation_operation_id=command.generation_operation_id,
        generator_operation_name=command.generator_operation_name,
        candidate_content_hash=command.candidate_content_hash,
        evaluator_execution_class=command.evaluator_execution_class,
        evaluation=None if command.evaluation is None else dict(command.evaluation),
        evidence_asset_version_ids=command.evidence_asset_version_ids,
        idempotency_key=command.idempotency_key,
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )


@pytest.fixture(scope="module", autouse=True)
def _migration() -> None:
    ensure_migrated()


def test_verified_receipt_before_output_recovers_same_generation_without_replay() -> (
    None
):
    """Outer recovery re-enters the governed receipt replay, never Provider."""

    adapter = _SyntheticSemanticProvider()
    armed = {"value": True}

    def crash_after_receipt(checkpoint: str) -> None:
        if checkpoint == "after_provider_success" and armed["value"]:
            armed["value"] = False
            raise SimulatedBookOpeningProcessLoss(
                "process disappeared after receipt and before durable model output"
            )

    orphan = create_legacy_book_opening_orphan(
        semantic_evaluation_execution_port=_semantic_port(
            adapter, fault_injector=crash_after_receipt
        ),
        terminalize_evaluation=False,
    )

    assert adapter.invocations == 1
    assert _counts(orphan) == (1, 1, 1, 0, 0)
    assert _semantic_runtime_state(orphan) == (
        "EXECUTING",
        "RUNNING",
        "RUNNING",
        1,
        1,
        1,
        1,
        0,
        0,
        0,
    )
    _converge_outer_loss(orphan)
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"durable-success-assessment:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    assert assessment.disposition == "PROVEN_SUCCESS"
    receipt = orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"durable-success-recovery:{orphan.opening_run_id}",
        reason="resume the governed semantic receipt replay in the successor Opening",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert receipt.result["replacement_evaluation_operation_id"] == ""
    assert _counts(orphan) == (1, 1, 1, 1, 1)
    assert adapter.invocations == 1

    claim = orphan.opening.claim_next_legacy_execution(
        worker_id="durable-receipt-successor-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == receipt.result["runtime_job_id"]
    assert (claim.job_kind, claim.runtime_group) == (
        BOOK_OPENING_LEGACY_JOB_KIND,
        BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    )
    original_checkpoint = orphan.opening._checkpoint_search
    checkpoint_committed = {"value": False}

    def crash_after_book_checkpoint(*args: Any, **kwargs: Any) -> None:
        original_checkpoint(*args, **kwargs)
        if not checkpoint_committed["value"]:
            checkpoint_committed["value"] = True
            raise SimulatedBookOpeningProcessLoss(
                "successor disappeared after projecting the recovered Book search"
            )

    with (
        patch.object(
            orphan.opening,
            "_checkpoint_search",
            side_effect=crash_after_book_checkpoint,
        ),
        pytest.raises(SimulatedBookOpeningProcessLoss),
    ):
        execute_legacy_book_opening_claim(
            RuntimeJobAuthority(DATABASE_URL),
            orphan.opening,
            orphan.principal,
            claim,
            lease_seconds=60,
        )

    assert _semantic_runtime_state(orphan) == (
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=%s
              AND semantic_work_key='book_plan.generate:book:main'
            """,
            [orphan.opening_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 1
        uow.cursor.execute(
            """
            SELECT COUNT(DISTINCT evaluation.evaluation_execution_id),
                   COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   COUNT(DISTINCT receipt.external_receipt_id)
            FROM authority_narrative_evaluation_execution AS evaluation
            LEFT JOIN authority_external_effect AS effect
              ON effect.operation_id=evaluation.operation_id
            LEFT JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            LEFT JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            WHERE evaluation.project_id=%s
              AND evaluation.candidate_asset_version_id=%s
            """,
            [
                orphan.project_id,
                orphan.evaluation_command.candidate_asset_version_id,
            ],
        )
        all_semantic_effects = tuple(int(value) for value in uow.cursor.fetchone())
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [claim.lease_id],
        )
        uow.commit()
    assert all_semantic_effects == (1, 1, 1, 1)
    # Three unique Book-search candidates executed, but the interrupted first
    # candidate retained exactly one Effect/Dispatch/Receipt and one Attempt.
    assert adapter.invocations == 3

    loss_key = f"durable-success-loss:{orphan.opening_run_id}:generation-2"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    reassessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"durable-success-reassess:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    replay = orphan.opening.recovery.recover(
        reassessment.recovery_assessment_id,
        idempotency_key=f"durable-success-readmit:{orphan.opening_run_id}",
        reason="prove checkpointed receipt replay remains formally recoverable",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert replay.result["replacement_evaluation_operation_id"] == ""
    current = orphan.opening.require(orphan.opening_run_id)
    aborted = orphan.opening.abort(
        orphan.opening_run_id,
        expected_version=int(current["version"]),
        principal=orphan.principal,
    )
    assert aborted["lifecycle"] == "ABORTED"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_runtime_job
            WHERE subject_kind='BOOK_OPENING_RUN' AND subject_id=%s
              AND status IN ('READY','CLAIMED','RUNNING','CHECKPOINTED','RETRY_WAIT')
            """,
            [orphan.opening_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0
    assert adapter.invocations == 3


def test_complete_success_bundle_recovers_by_projection_with_zero_provider_replay() -> (
    None
):
    orphan, adapter = _complete_durable_success_orphan()
    assert adapter.invocations == 1
    assert _semantic_runtime_state(orphan) == (
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status,operation.version,attempt.status,
                   lease.status,evaluation.lifecycle,evaluation.version,
                   effect.status,effect.request_hash,dispatch.status,
                   dispatch.payload_hash,receipt.status,receipt.payload_hash,
                   output.asset_version_id,output.content_hash
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
             AND output.output_key='story_design.semantic_evaluation'
             AND output.role='qualification_evidence'
            WHERE operation.operation_id=%s
            """,
            [orphan.evaluation_operation_id],
        )
        predecessor_before = tuple(uow.cursor.fetchone())
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_narrative_design_qualification
            WHERE evaluation_operation_id=%s
            """,
            [orphan.evaluation_operation_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0

    _converge_outer_loss(orphan)
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"complete-success-assessment:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    assert assessment.disposition == "PROVEN_SUCCESS"
    admitted = orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"complete-success-recovery:{orphan.opening_run_id}",
        reason="project the complete durable semantic result without Provider replay",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    replacement_operation_id = str(
        admitted.result["replacement_evaluation_operation_id"]
    )
    assert replacement_operation_id
    assert admitted.result["provider_invoked"] is False
    assert adapter.invocations == 1
    assert _counts(orphan) == (1, 1, 1, 1, 1)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status,operation.version,attempt.status,
                   lease.status,evaluation.lifecycle,evaluation.version,
                   effect.status,effect.request_hash,dispatch.status,
                   dispatch.payload_hash,receipt.status,receipt.payload_hash,
                   output.asset_version_id,output.content_hash
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            JOIN authority_external_receipt AS receipt
              ON receipt.dispatch_id=dispatch.dispatch_id
            JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
             AND output.output_key='story_design.semantic_evaluation'
             AND output.role='qualification_evidence'
            WHERE operation.operation_id=%s
            """,
            [orphan.evaluation_operation_id],
        )
        assert tuple(uow.cursor.fetchone()) == predecessor_before
        uow.cursor.execute(
            """
            SELECT operation.status,evaluation.lifecycle,
                   operation.command_payload#>>'{payload,durable_success_replay,source_operation_id}',
                   operation.command_payload#>>'{payload,durable_success_replay,source_attempt_id}',
                   (SELECT COUNT(*) FROM authority_attempt
                    WHERE operation_id=operation.operation_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=operation.operation_id)
            FROM authority_operation AS operation
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            WHERE operation.operation_id=%s
            """,
            [replacement_operation_id],
        )
        assert tuple(uow.cursor.fetchone()) == (
            "ADMITTED",
            "ADMITTED",
            orphan.evaluation_operation_id,
            orphan.evaluation_attempt_id,
            0,
            0,
        )

    claim = orphan.opening.claim_next_legacy_execution(
        worker_id="durable-complete-successor-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == admitted.result["runtime_job_id"]
    opening = orphan.opening.require(orphan.opening_run_id)
    orphan.opening._bind_running_execution(  # noqa: SLF001
        orphan.opening_run_id,
        expected_version=int(opening["version"]),
        runtime_claim=claim,
    )

    semantic_command = _semantic_command(orphan)
    evaluated = orphan.planning.semantic_evaluation.execute(
        semantic_command,
        principal=orphan.evaluator,
        caller_permission="story_planning.authority.execute",
    )
    assert adapter.invocations == 1
    assert evaluated.lineage.evaluation_operation_id == orphan.evaluation_operation_id
    assert evaluated.lineage.evaluation_attempt_id == orphan.evaluation_attempt_id
    assert (
        evaluated.evaluation_content["durable_success_replay"][
            "replacement_operation_id"
        ]
        == replacement_operation_id
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status,evaluation.lifecycle,attempt.status,lease.status,
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=operation.operation_id)
            FROM authority_operation AS operation
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE operation.operation_id=%s
            """,
            [replacement_operation_id],
        )
        assert tuple(uow.cursor.fetchone()) == (
            "SUCCEEDED",
            "SUCCEEDED",
            "SUCCEEDED",
            "RELEASED",
            0,
        )
        uow.cursor.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT evaluation_operation_id),
                   MIN(evaluation_operation_id),
                   COUNT(DISTINCT evaluation_attempt_id),
                   MIN(evaluation_attempt_id),
                   COUNT(DISTINCT provider_model_call_asset_version_id),
                   COUNT(DISTINCT evaluation_asset_version_id)
            FROM authority_narrative_design_qualification
            WHERE asset_version_id=%s
            """,
            [orphan.evaluation_command.candidate_asset_version_id],
        )
        qualification_lineage = tuple(uow.cursor.fetchone())
    assert qualification_lineage[:5] == (
        3,
        1,
        orphan.evaluation_operation_id,
        1,
        orphan.evaluation_attempt_id,
    )
    assert qualification_lineage[5:] == (1, 1)

    with patch.object(
        orphan.planning.semantic_evaluation.registry.item.handler,
        "execute",
        side_effect=AssertionError(
            "committed replacement output replay must skip handler and Provider"
        ),
    ):
        replayed = orphan.planning.semantic_evaluation.execute(
            semantic_command,
            principal=orphan.evaluator,
            caller_permission="story_planning.authority.execute",
        )
    assert replayed.lineage == evaluated.lineage
    assert replayed.qualification == evaluated.qualification
    assert replayed.evaluation_content == evaluated.evaluation_content
    assert adapter.invocations == 1
    assert _counts(orphan) == (1, 1, 1, 1, 1)


def test_multiple_receipts_for_one_successful_dispatch_fail_closed() -> None:
    orphan, adapter = _complete_durable_success_orphan()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            INSERT INTO authority_external_receipt(
                provider,receipt_id,dispatch_id,payload_hash,
                received_at,payload,status
            )
            SELECT receipt.provider,
                   receipt.receipt_id || ':conflicting-duplicate',
                   receipt.dispatch_id,receipt.payload_hash,
                   receipt.received_at + INTERVAL '1 microsecond',
                   receipt.payload,'VERIFIED'
            FROM authority_external_receipt AS receipt
            JOIN authority_external_effect_dispatch AS dispatch
              USING(dispatch_id)
            JOIN authority_external_effect AS effect
              USING(external_effect_id)
            WHERE effect.operation_id=%s
            """,
            [orphan.evaluation_operation_id],
        )
        assert uow.cursor.rowcount == 1
        uow.commit()

    _converge_outer_loss(orphan)
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"multiple-receipt-assessment:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    assert assessment.disposition == "UNKNOWN_AMBIGUOUS"
    with pytest.raises(KernelError) as blocked:
        orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=f"multiple-receipt-recovery:{orphan.opening_run_id}",
            reason="multiple receipts must never be collapsed into proven success",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    assert blocked.value.code == "BOOK_OPENING_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED"
    assert adapter.invocations == 1
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_opening_recovery_intent
            WHERE opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0


def test_verified_receipt_before_output_replays_same_attempt_without_provider() -> None:
    adapter = _SyntheticSemanticProvider()
    armed = {"value": True}

    def crash_after_receipt(checkpoint: str) -> None:
        if checkpoint == "after_provider_success" and armed["value"]:
            armed["value"] = False
            raise SimulatedBookOpeningProcessLoss(
                "process disappeared after receipt and before durable model output"
            )

    orphan = create_legacy_book_opening_orphan(
        semantic_evaluation_execution_port=_semantic_port(
            adapter, fault_injector=crash_after_receipt
        ),
        terminalize_evaluation=False,
    )

    assert adapter.invocations == 1
    assert _semantic_runtime_state(orphan) == (
        "EXECUTING",
        "RUNNING",
        "RUNNING",
        1,
        1,
        1,
        1,
        0,
        0,
        0,
    )

    orphan.planning.evaluate_candidate(
        orphan.evaluation_command,
        principal=orphan.evaluator,
        transition_principal=orphan.principal,
    )

    assert adapter.invocations == 1
    assert _semantic_runtime_state(orphan) == (
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )


def test_materialized_output_before_terminal_replays_without_handler_or_provider() -> (
    None
):
    adapter = _SyntheticSemanticProvider()
    original_execute = content_scheduler.execute_content_handler
    armed = {"value": True}

    def crash_after_materialization(*args: Any, **kwargs: Any) -> object:
        result = original_execute(*args, **kwargs)
        if armed["value"] and adapter.invocations == 1:
            armed["value"] = False
            raise SimulatedBookOpeningProcessLoss(
                "process disappeared after semantic output materialization"
            )
        return result

    with patch.object(
        content_scheduler,
        "execute_content_handler",
        new=crash_after_materialization,
    ):
        orphan = create_legacy_book_opening_orphan(
            semantic_evaluation_execution_port=_semantic_port(adapter),
            terminalize_evaluation=False,
        )

    assert adapter.invocations == 1
    assert _semantic_runtime_state(orphan) == (
        "EXECUTING",
        "RUNNING",
        "RUNNING",
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )

    with patch.object(
        orphan.planning.semantic_evaluation.registry.item.handler,
        "execute",
        side_effect=AssertionError("materialized output replay must skip handler"),
    ):
        orphan.planning.evaluate_candidate(
            orphan.evaluation_command,
            principal=orphan.evaluator,
            transition_principal=orphan.principal,
        )

    assert adapter.invocations == 1
    assert _semantic_runtime_state(orphan) == (
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )
