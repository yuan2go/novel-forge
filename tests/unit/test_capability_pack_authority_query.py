import inspect

from novel_forge.modules.capability_pack_authority.domain import DriftClassification
from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
    classify_deployment_drift,
)


def test_drift_classifier_blocks_new_admission_without_invalidating_history() -> None:
    result = classify_deployment_drift(
        deployment_status="ACTIVE",
        approval_current=True,
        retired=False,
        definition_drift=True,
        agent_drift=False,
    )
    assert result is DriftClassification.NEW_ADMISSION_BLOCKED


def test_revoked_or_rollback_required_have_stronger_drift_classes() -> None:
    assert (
        classify_deployment_drift(
            deployment_status="ACTIVE",
            approval_current=True,
            retired=True,
            definition_drift=False,
            agent_drift=False,
        )
        is DriftClassification.REVOKED
    )
    assert (
        classify_deployment_drift(
            deployment_status="ROLLBACK_REQUIRED",
            approval_current=True,
            retired=False,
            definition_drift=False,
            agent_drift=False,
        )
        is DriftClassification.ROLLBACK_RECOMMENDED
    )
    assert (
        classify_deployment_drift(
            deployment_status="ROLLBACK_REQUIRED",
            approval_current=False,
            retired=False,
            definition_drift=False,
            agent_drift=False,
            approval_revoked=True,
        )
        is DriftClassification.REVOKED
    )


def test_usage_rates_project_gate_assets_not_operation_success() -> None:
    source = inspect.getsource(CapabilityPackAuthorityQuery.usage_metrics)

    assert "asset_type='quality_score_report'" in source
    assert "asset_type='publish_gate_report'" in source
    assert "content->>'gate'" in source
    assert "real_provider_validation_eligible" in source
    assert "authority_external_receipt" in source
