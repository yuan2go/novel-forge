from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    CapabilityPackPostgresHarness,
)


def test_distinct_version_canary_complete_and_rollback_converge_on_activation() -> None:
    harness = CapabilityPackPostgresHarness("pack-rollout", book_count=40)
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1, scope_type="WORKSPACE")
    activation = harness.activate(baseline)
    assert activation["activation_version"] == 1

    version_2 = harness.register_compile_approve("1.1.0", generation=2)
    candidate = harness.deploy(version_2, scope_type="WORKSPACE")
    assert baseline.binding_set_hash != candidate.binding_set_hash
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
            "mode": "PERCENTAGE",
            "percentage": 50,
            "assignment_key_policy": "BOOK",
        },
    )

    resolver = CapabilityPackRuntimeResolver(DATABASE_URL)

    def resolve(book_id: str) -> tuple[str, str, str]:
        snapshot = resolver.resolve_active_deployment(
            harness.resolution_request(book_id=book_id)
        )
        return (
            snapshot.deployment_id,
            snapshot.assignment_ref,
            snapshot.pack_version,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        first_results = list(pool.map(resolve, harness.book_ids))
    with ThreadPoolExecutor(max_workers=8) as pool:
        repeated_results = list(pool.map(resolve, harness.book_ids))
    assert repeated_results == first_results
    candidate_count = sum(
        deployment_id == candidate.deployment_id
        for deployment_id, _, _ in first_results
    )
    assert 8 <= candidate_count <= 32
    assert len({assignment for _, assignment, _ in first_results}) == len(
        harness.book_ids
    )
    assert {
        version
        for _, _, version in first_results
    } == {"1.0.0", "1.1.0"}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT subject_key),
                   COUNT(DISTINCT assignment_id)
            FROM authority_capability_pack_assignment
            WHERE rollout_id=%s
            """,
            [rollout_id],
        )
        assert uow.cursor.fetchone() == (40, 40, 40)
        uow.commit()

    harness.execute(
        "capability_pack.rollout.pause",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        payload={"environment": "development", "reason": "fixture pause"},
    )
    assert all(resolve(book_id)[0] == baseline.deployment_id for book_id in harness.book_ids)
    harness.execute(
        "capability_pack.rollout.resume",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        payload={"environment": "development", "reason": "fixture resume"},
    )
    assert [resolve(book_id) for book_id in harness.book_ids] == first_results

    completed = harness.execute(
        "capability_pack.rollout.complete",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        expected_activation_version=1,
        payload={"environment": "development", "reason": "qualified fixture"},
    )
    assert completed["status"] == "COMPLETED"
    assert completed["active_deployment_id"] == candidate.deployment_id
    assert completed["activation_version"] == 2
    completed_results = [resolve(book_id) for book_id in harness.book_ids]
    assert {item[0] for item in completed_results} == {candidate.deployment_id}
    assert {item[2] for item in completed_results} == {"1.1.0"}
    assert all(item[1].endswith("@2") for item in completed_results)

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM audit_log
               WHERE operation_id=%s
                 AND action='authority.capability_pack.rollout.complete.committed'),
              (SELECT COUNT(*) FROM state_event
               WHERE payload->>'operation_id'=%s
                 AND event_type=
                     'authority.capability_pack.rollout.complete.committed'),
              (SELECT COUNT(*) FROM outbox_event
               WHERE payload->>'operation_id'=%s
                 AND topic=
                     'authority.capability_pack.rollout.complete.committed')
            """,
            [completed["operation_id"]] * 3,
        )
        assert uow.cursor.fetchone() == (1, 1, 1)
        uow.commit()

    rolled_back = harness.execute(
        "capability_pack.rollback",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        deployment_id=baseline.deployment_id,
        expected_activation_version=2,
        payload={"environment": "development", "reason": "fixture rollback"},
    )
    assert rolled_back["active_deployment_id"] == baseline.deployment_id
    assert rolled_back["activation_version"] == 3
    assert {resolve(book_id)[0] for book_id in harness.book_ids} == {
        baseline.deployment_id
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT status FROM authority_capability_pack_rollout
            WHERE rollout_id=%s
            """,
            [rollout_id],
        )
        assert uow.cursor.fetchone() == ("ROLLED_BACK",)
        uow.cursor.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT assignment_hash)
            FROM authority_capability_pack_assignment WHERE rollout_id=%s
            """,
            [rollout_id],
        )
        assert uow.cursor.fetchone() == (40, 40)
        uow.commit()
