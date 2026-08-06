from __future__ import annotations

import pytest

from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    CapabilityPackPostgresHarness,
)


def test_approval_scope_is_closed_and_enforced_at_deploy_rollout_and_runtime() -> None:
    harness = CapabilityPackPostgresHarness("pack-policy", book_count=2)
    scope = harness.approval_scope(
        scope_types=("BOOK",),
        book_ids=(harness.book_ids[0],),
        allow_full_rollout=False,
        maximum_rollout_percentage=10,
    )
    version = harness.register_compile_approve(
        "1.0.0",
        generation=1,
        approval_scope=scope,
        limitations=(
            {
                "limitation_type": "ROLLOUT_CONSTRAINT",
                "code": "MAXIMUM_PERCENTAGE",
                "value": 10,
                "message": "Qualification is capped at ten percent.",
            },
            "Legacy text is informational only.",
        ),
    )
    baseline = harness.deploy(version, book_id=harness.book_ids[0])
    candidate = harness.deploy(version, book_id=harness.book_ids[0])
    harness.activate(baseline)

    with pytest.raises(KernelError) as wrong_book:
        harness.deploy(version, book_id=harness.book_ids[1])
    assert wrong_book.value.code == "CAPABILITY_PACK_APPROVAL_SCOPE_DENIED"
    with pytest.raises(KernelError) as wrong_environment:
        harness.deploy(
            version,
            book_id=harness.book_ids[0],
            environment="production",
        )
    assert wrong_environment.value.code == "CAPABILITY_PACK_APPROVAL_SCOPE_DENIED"
    with pytest.raises(KernelError) as percentage:
        harness.execute(
            "capability_pack.rollout.start",
            principal=harness.compiler,
            pack_version=version.pack_version,
            rollout_id="policy-percentage-rollout",
            payload={
                "environment": "development",
                "baseline_deployment_id": baseline.deployment_id,
                "candidate_deployment_id": candidate.deployment_id,
                "mode": "PERCENTAGE",
                "percentage": 50,
                "assignment_key_policy": "BOOK",
            },
        )
    assert percentage.value.code == "CAPABILITY_PACK_APPROVAL_ROLLOUT_DENIED"
    with pytest.raises(KernelError) as full:
        harness.execute(
            "capability_pack.rollout.start",
            principal=harness.compiler,
            pack_version=version.pack_version,
            rollout_id="policy-full-rollout",
            payload={
                "environment": "development",
                "baseline_deployment_id": baseline.deployment_id,
                "candidate_deployment_id": candidate.deployment_id,
                "mode": "FULL",
                "percentage": 100,
                "assignment_key_policy": "BOOK",
            },
        )
    assert full.value.code == "CAPABILITY_PACK_APPROVAL_ROLLOUT_DENIED"

    # A later immutable approval decision narrows runtime admission without
    # rewriting the Deployment or its historical binding set.
    harness.execute(
        "capability_pack.approval.decide",
        principal=harness.approver,
        pack_version=version.pack_version,
        compilation_id=version.compilation_id,
        payload={
            "compilation_hash": version.compilation_hash,
            "decision": "APPROVED",
            "approval_policy_ref": "capability-pack-approval-scope:v1",
            "scope": harness.approval_scope(
                scope_types=("BOOK",),
                book_ids=(harness.book_ids[1],),
            ),
            "reason": "Narrow admission to the second fixture Book.",
            "enforce_duties_separation": True,
        },
    )
    with pytest.raises(KernelError) as runtime_denied:
        CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
            harness.resolution_request(book_id=harness.book_ids[0])
        )
    assert runtime_denied.value.code == "CAPABILITY_PACK_APPROVAL_SCOPE_DENIED"


def test_approval_scope_rejects_unknown_protocol_keys() -> None:
    harness = CapabilityPackPostgresHarness("pack-policy-closed")
    version = harness.register_compile_approve("1.0.0", generation=1)
    invalid_scope = harness.approval_scope()
    invalid_scope["environment"] = "development"
    with pytest.raises(ValueError, match="closed v1 protocol"):
        harness.execute(
            "capability_pack.approval.decide",
            principal=harness.approver,
            pack_version=version.pack_version,
            compilation_id=version.compilation_id,
            payload={
                "compilation_hash": version.compilation_hash,
                "decision": "APPROVED",
                "approval_policy_ref": "capability-pack-approval-scope:v1",
                "scope": invalid_scope,
                "reason": "Unknown fields must fail closed.",
            },
        )
