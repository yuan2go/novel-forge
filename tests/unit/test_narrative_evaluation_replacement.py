from __future__ import annotations

import pytest

from novel_forge.modules.story_design_authority import (
    NarrativeEvaluationExternalEffectDisposition,
    NarrativeSemanticEvaluationReplacementCommand,
    classify_narrative_evaluation_external_effects,
)


def _effect_row(
    *,
    effect_status: str,
    dispatch_status: str | None = None,
    receipt_status: str | None = None,
) -> dict[str, object]:
    return {
        "external_effect_id": "effect-1",
        "effect_status": effect_status,
        "dispatch_id": "dispatch-1" if dispatch_status else None,
        "dispatch_status": dispatch_status,
        "receipt_status": receipt_status,
    }


def test_external_effect_classification_requires_conclusive_durable_evidence() -> None:
    assert (
        classify_narrative_evaluation_external_effects(())
        is NarrativeEvaluationExternalEffectDisposition.PROVEN_NO_EFFECT
    )
    assert (
        classify_narrative_evaluation_external_effects(
            (
                _effect_row(
                    effect_status="SUCCEEDED",
                    dispatch_status="SUCCEEDED",
                    receipt_status="VERIFIED",
                ),
            )
        )
        is NarrativeEvaluationExternalEffectDisposition.PROVEN_SUCCESS
    )
    assert (
        classify_narrative_evaluation_external_effects(
            (
                _effect_row(
                    effect_status="FAILED_FINAL",
                    dispatch_status="FAILED_FINAL",
                    receipt_status="VERIFIED",
                ),
            )
        )
        is NarrativeEvaluationExternalEffectDisposition.PROVEN_TERMINAL_FAILURE
    )


@pytest.mark.parametrize(
    "row",
    (
        _effect_row(effect_status="RECONCILIATION_REQUIRED", dispatch_status="UNKNOWN"),
        _effect_row(effect_status="SUCCEEDED", dispatch_status="SUCCEEDED"),
        _effect_row(effect_status="READY"),
        _effect_row(effect_status="DISPATCHED", dispatch_status="ACKNOWLEDGED"),
    ),
)
def test_external_effect_classification_fails_closed_for_ambiguous_evidence(
    row: dict[str, object],
) -> None:
    assert (
        classify_narrative_evaluation_external_effects((row,))
        is NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    )


def test_external_effect_classification_rejects_multiple_receipts_per_dispatch() -> (
    None
):
    successful = _effect_row(
        effect_status="SUCCEEDED",
        dispatch_status="SUCCEEDED",
        receipt_status="VERIFIED",
    )
    conflicting_receipt = {**successful, "receipt_status": "REJECTED"}

    assert (
        classify_narrative_evaluation_external_effects(
            (successful, conflicting_receipt)
        )
        is NarrativeEvaluationExternalEffectDisposition.UNKNOWN_AMBIGUOUS
    )


def test_replacement_command_requires_exact_head_and_recovery_lineage() -> None:
    command = NarrativeSemanticEvaluationReplacementCommand(
        predecessor_operation_id="operation-1",
        expected_head_generation=1,
        expected_head_version=0,
        recovery_intent_id="recovery-intent-1",
        actor_id="evaluator-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
    )

    assert command.successor_generation == 2
    with pytest.raises(ValueError, match="generation"):
        NarrativeSemanticEvaluationReplacementCommand(
            predecessor_operation_id="operation-1",
            expected_head_generation=0,
            expected_head_version=0,
            recovery_intent_id="recovery-intent-1",
            actor_id="evaluator-1",
            trace_id="trace-1",
            correlation_id="correlation-1",
        )
