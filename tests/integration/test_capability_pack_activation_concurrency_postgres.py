from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, Callable
from uuid import uuid4

import pytest

from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.capability_pack_postgres_support import (
    APP_BUILD_ID,
    DATABASE_URL,
    RELEASE_SHA,
    CapabilityPackPostgresHarness,
)


def _independent_command(
    harness: CapabilityPackPostgresHarness,
    *,
    action: str,
    principal: Any,
    pack_version: str,
    deployment_id: str = "",
    rollout_id: str = "",
    compilation_id: str = "",
    expected_activation_version: int = 0,
    payload: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    application = CapabilityPackAuthorityApplication(
        DATABASE_URL,
        application_build_id=APP_BUILD_ID,
        commit_sha=RELEASE_SHA,
    )
    token = uuid4().hex
    command = CapabilityPackAuthorityCommand(
        definition_name=action,
        project_id=harness.project_id,
        workspace_id=harness.workspace_id,
        actor_id=principal.principal_id,
        pack_id=harness.pack_id,
        pack_version=pack_version,
        compilation_id=compilation_id,
        deployment_id=deployment_id,
        rollout_id=rollout_id,
        expected_activation_version=expected_activation_version,
        idempotency_key=f"{harness.project_id}:{action}:{token}",
        trace_id=f"trace:{harness.project_id}:{token}",
        correlation_id=f"correlation:{harness.project_id}",
        payload=payload,
    )

    def invoke() -> dict[str, Any]:
        return application.execute(command, principal=principal)

    return invoke


def _race(*calls: Callable[[], dict[str, Any]]) -> list[object]:
    barrier = Barrier(len(calls))

    def invoke(call: Callable[[], dict[str, Any]]) -> object:
        barrier.wait()
        try:
            return call()
        except Exception as exc:  # returned for exact race outcome assertions
            return exc

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(invoke, calls))


def test_two_independent_sessions_prove_activation_cas_conflict() -> None:
    harness = CapabilityPackPostgresHarness("pack-cas")
    version = harness.register_compile_approve("1.0.0", generation=1)
    initial = harness.deploy(version)
    contender_a = harness.deploy(version)
    contender_b = harness.deploy(version)
    harness.activate(initial)
    principal_a = harness.principal("cas-a", *harness.compiler.permissions)
    principal_b = harness.principal("cas-b", *harness.compiler.permissions)
    results = _race(
        _independent_command(
            harness,
            action="capability_pack.deployment.activate",
            principal=principal_a,
            pack_version=version.pack_version,
            deployment_id=contender_a.deployment_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "concurrent A"},
        ),
        _independent_command(
            harness,
            action="capability_pack.deployment.activate",
            principal=principal_b,
            pack_version=version.pack_version,
            deployment_id=contender_b.deployment_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "concurrent B"},
        ),
    )
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, KernelError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "CAPABILITY_PACK_ACTIVATION_CONFLICT"
    winner = successes[0]
    assert winner["activation_version"] == 2
    assert winner["active_deployment_id"] in {
        contender_a.deployment_id,
        contender_b.deployment_id,
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT active_deployment_id, activation_version
            FROM authority_capability_pack_activation
            WHERE pack_id=%s
            """,
            [harness.pack_id],
        )
        assert uow.cursor.fetchone() == (
            winner["active_deployment_id"],
            2,
        )
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM audit_log
               WHERE operation_id=%s
                 AND action='authority.capability_pack.deployment.activate.committed'),
              (SELECT COUNT(*) FROM state_event
               WHERE payload->>'operation_id'=%s
                 AND event_type=
                     'authority.capability_pack.deployment.activate.committed'),
              (SELECT COUNT(*) FROM outbox_event
               WHERE payload->>'operation_id'=%s
                 AND topic=
                     'authority.capability_pack.deployment.activate.committed')
            """,
            [winner["operation_id"]] * 3,
        )
        assert uow.cursor.fetchone() == (1, 1, 1)
        uow.commit()


def test_rollout_complete_and_manual_rollback_cas_race_has_one_winner() -> None:
    harness = CapabilityPackPostgresHarness("pack-complete-race")
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1)
    harness.activate(baseline)
    version_2 = harness.register_compile_approve("1.1.0", generation=2)
    candidate = harness.deploy(version_2)
    rollout_id = f"rollout:{harness.pack_id}"
    harness.execute(
        "capability_pack.rollout.start",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        payload={
            "environment": "development",
            "baseline_deployment_id": baseline.deployment_id,
            "candidate_deployment_id": candidate.deployment_id,
            "mode": "CANARY",
            "percentage": 10,
            "assignment_key_policy": "BOOK",
        },
    )
    results = _race(
        _independent_command(
            harness,
            action="capability_pack.rollout.complete",
            principal=harness.principal(
                "complete", *harness.compiler.permissions
            ),
            pack_version=version_1.pack_version,
            rollout_id=rollout_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "complete"},
        ),
        _independent_command(
            harness,
            action="capability_pack.rollback",
            principal=harness.principal(
                "rollback", *harness.compiler.permissions
            ),
            pack_version=version_1.pack_version,
            deployment_id=baseline.deployment_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "rollback"},
        ),
    )
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, KernelError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code in {
        "CAPABILITY_PACK_ACTIVATION_CONFLICT",
        "CAPABILITY_PACK_ROLLOUT_TRANSITION_CONFLICT",
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT activation.active_deployment_id, activation.activation_version,
                   rollout.status
            FROM authority_capability_pack_activation AS activation
            JOIN authority_capability_pack_rollout AS rollout
              ON rollout.rollout_id=%s
            WHERE activation.pack_id=%s
            """,
            [rollout_id, harness.pack_id],
        )
        active_id, activation_version, status = uow.cursor.fetchone()
        assert activation_version == 2
        assert (active_id, status) in {
            (candidate.deployment_id, "COMPLETED"),
            (baseline.deployment_id, "ROLLED_BACK"),
        }
        uow.commit()


def test_revoke_activate_and_retire_create_races_remain_fail_closed() -> None:
    harness = CapabilityPackPostgresHarness("pack-policy-race")
    version = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version)
    candidate = harness.deploy(version)
    harness.activate(baseline)
    revoke_activate = _race(
        _independent_command(
            harness,
            action="capability_pack.revoke",
            principal=harness.principal(
                "revoke", *harness.approver.permissions
            ),
            pack_version=version.pack_version,
            compilation_id=version.compilation_id,
            payload={"environment": "development", "reason": "race revoke"},
        ),
        _independent_command(
            harness,
            action="capability_pack.deployment.activate",
            principal=harness.principal(
                "activate", *harness.compiler.permissions
            ),
            pack_version=version.pack_version,
            deployment_id=candidate.deployment_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "race activate"},
        ),
    )
    revoke_successes = [item for item in revoke_activate if isinstance(item, dict)]
    revoke_conflicts = [
        item for item in revoke_activate if isinstance(item, KernelError)
    ]
    assert len(revoke_successes) in {1, 2}
    assert len(revoke_successes) + len(revoke_conflicts) == 2
    assert all(
        item.code
        in {
            "CAPABILITY_PACK_APPROVAL_INVALID",
            "CAPABILITY_PACK_DEPLOYMENT_BLOCKED",
        }
        for item in revoke_conflicts
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        approval = uow.repositories.capability_packs.latest_approval(
            version.compilation_id
        )
        assert approval is not None and approval["decision"] == "REVOKED"
        uow.commit()
    with pytest.raises(KernelError) as runtime_blocked:
        CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
            harness.resolution_request()
        )
    assert runtime_blocked.value.code in {
        "CAPABILITY_PACK_APPROVAL_INVALID",
        "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
    }

    retire_harness = CapabilityPackPostgresHarness("pack-retire-race")
    retire_version = retire_harness.register_compile_approve(
        "1.0.0", generation=1
    )
    pending_deployment_id = f"race-deployment:{uuid4()}"
    retire_create = _race(
        _independent_command(
            retire_harness,
            action="capability_pack.retire",
            principal=retire_harness.principal(
                "retire", *retire_harness.compiler.permissions
            ),
            pack_version=retire_version.pack_version,
            payload={
                "environment": "development",
                "reason": "race retirement",
                "migration_required": True,
                "migration_policy_ref": "migration:fixture:v1",
            },
        ),
        _independent_command(
            retire_harness,
            action="capability_pack.deployment.create",
            principal=retire_harness.principal(
                "create", *retire_harness.compiler.permissions
            ),
            pack_version=retire_version.pack_version,
            compilation_id=retire_version.compilation_id,
            deployment_id=pending_deployment_id,
            payload={
                "target_scope_type": "BOOK",
                "project_id": retire_harness.project_id,
                "workspace_id": retire_harness.workspace_id,
                "book_id": retire_harness.book_ids[0],
                "environment": "development",
                "rollout_policy_ref": "rollout:stable-sha256:v1",
            },
        ),
    )
    retire_successes = [item for item in retire_create if isinstance(item, dict)]
    retire_conflicts = [
        item for item in retire_create if isinstance(item, KernelError)
    ]
    assert len(retire_successes) in {1, 2}
    assert len(retire_successes) + len(retire_conflicts) == 2
    assert all(
        item.code == "CAPABILITY_PACK_VERSION_RETIRED"
        for item in retire_conflicts
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        deprecation = uow.repositories.capability_packs.latest_deprecation(
            retire_harness.pack_id, retire_version.pack_version
        )
        assert deprecation is not None and deprecation["retired"] is True
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_capability_pack_deployment
            WHERE deployment_id=%s
            """,
            [pending_deployment_id],
        )
        deployment_count = int(uow.cursor.fetchone()[0])
        uow.commit()
    assert deployment_count == (1 if len(retire_successes) == 2 else 0)
    if deployment_count:
        with pytest.raises(KernelError) as retired_activation:
            retire_harness.execute(
                "capability_pack.deployment.activate",
                principal=retire_harness.compiler,
                pack_version=retire_version.pack_version,
                deployment_id=pending_deployment_id,
                payload={
                    "environment": "development",
                    "reason": "must remain blocked",
                },
            )
        assert retired_activation.value.code == "CAPABILITY_PACK_VERSION_RETIRED"
    with pytest.raises(KernelError) as post_race_create:
        retire_harness.deploy(retire_version)
    assert post_race_create.value.code == "CAPABILITY_PACK_VERSION_RETIRED"
