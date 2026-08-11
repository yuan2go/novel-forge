from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
)
from novel_forge.modules.agent_runtime.queries import AgentRuntimeQuery
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
)
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
    chapter_root_operation_definition,
)
from novel_forge.modules.command_kernel.maintenance import (
    scan_expired_attempt_leases,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    submit_attempt_failure,
)
from novel_forge.modules.production_execution.postgres import (
    PostgresAttemptFenceVerifier,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import (
    test_chapter_authority_scheduler_postgres as chapter_fixtures,
)
from tests.integration import test_unified_agent_runtime_postgres as unified_fixtures


RELEASE_SHA = unified_fixtures.RELEASE_SHA


CRASH_POINTS = (
    "after_work_order_freeze",
    "after_runtime_binding_freeze",
    "after_external_effect_plan",
    "after_provider_success",
    "after_candidate_persist",
    "after_domain_asset_materialized",
    "after_authority_decision",
    "after_collaboration_commit",
    "before_attempt_result_submission",
)

CRASH_POINT_PRE_STATE = {
    "after_work_order_freeze": (1, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "after_runtime_binding_freeze": (1, 0, 0, 1, 1, 0, 0, 0, 0, 0),
    "after_external_effect_plan": (1, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "after_provider_success": (1, 1, 0, 1, 1, 0, 0, 0, 0, 0),
    "after_candidate_persist": (1, 1, 1, 1, 1, 1, 0, 0, 0, 0),
    "after_domain_asset_materialized": (1, 1, 1, 1, 1, 1, 1, 0, 0, 0),
    "after_authority_decision": (1, 1, 1, 1, 1, 1, 1, 1, 0, 0),
    "after_collaboration_commit": (1, 1, 1, 1, 1, 1, 1, 1, 1, 0),
    "before_attempt_result_submission": (1, 1, 1, 1, 1, 1, 1, 1, 1, 0),
}

CRASH_PRE_STATE_FIELDS = (
    "external_effect_count",
    "provider_dispatch_count",
    "budget_settlement_count",
    "work_order_count",
    "runtime_binding_count",
    "candidate_count",
    "asset_count",
    "decision_count",
    "commit_count",
    "attempt_result_count",
)


class SimulatedProcessCrash(BaseException):
    """Test-only process boundary; deliberately bypasses Exception handlers."""


class CrashController:
    def __init__(self) -> None:
        self.target = ""
        self.triggered = False

    def __call__(self, checkpoint: str) -> None:
        if checkpoint == self.target and not self.triggered:
            self.triggered = True
            raise SimulatedProcessCrash(checkpoint)


@pytest.fixture(scope="module")
def crash_authority_scope() -> dict[str, str]:
    ensure_migrated()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT operation.project_id, operation.workspace_id
            FROM authority_chapter_node_agent_binding AS binding
            JOIN authority_operation AS operation
              ON operation.operation_id=binding.created_by_operation_id
            WHERE binding.workflow_definition_ref=
                  'chapter_authority_slice@2.3.1'
              AND binding.workflow_node_id='draft'
              AND binding.binding_status='ACTIVE'
            ORDER BY binding.created_at DESC
            LIMIT 1
            """
        ).fetchone()
    actor = "crash-matrix-operator"
    if row is not None:
        return {
            "project_id": str(row[0]),
            "workspace_id": str(row[1]),
            "actor": actor,
        }
    project_id = identifier("agent-crash-matrix")
    workspace_id = f"workspace:{project_id}"
    seed_authority_project_book(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=f"book:{project_id}",
    )
    principal = _principal(
        actor,
        PrincipalType.LOCAL_OPERATOR,
        project_id,
        {"chapter.authority.execute", "agent.authority.admin"},
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(
            chapter_root_operation_definition(
                application_build_id="agent-runtime-crash-matrix",
                commit_sha=RELEASE_SHA,
                model_effects_required=True,
            )
        )
        for definition in chapter_operation_definitions(
            application_build_id="agent-runtime-crash-matrix",
            commit_sha=RELEASE_SHA,
            model_effects_required=True,
        ):
            uow.repositories.definitions.register(definition)
        uow.commit()
    unified_fixtures.UnifiedAgentRuntimePostgresTests._register_draft_agent(
        project_id=project_id,
        workspace_id=workspace_id,
        actor=actor,
        principal=principal,
    )
    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "actor": actor,
    }


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_postgres_process_crash_matrix(
    crash_point: str,
    tmp_path: Path,
    crash_authority_scope: dict[str, str],
) -> None:
    project_id = crash_authority_scope["project_id"]
    workspace_id = crash_authority_scope["workspace_id"]
    old_worker = f"worker-before-crash:{crash_point}"
    new_worker = f"worker-after-crash:{crash_point}"
    actor = crash_authority_scope["actor"]
    object_root = tmp_path / crash_point
    controller = CrashController()
    old_application, old_execution = _application(
        object_root=object_root,
        fault_injector=controller,
    )
    operator = _principal(
        actor,
        PrincipalType.LOCAL_OPERATOR,
        project_id,
        {"chapter.authority.execute", "agent.authority.admin"},
    )
    admission = old_application.admit(
        SingleChapterRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=actor,
            chapter=1,
            title="One Recoverable Draft",
            premise="A process crash cannot duplicate an external effect.",
            trace_id=identifier("crash-trace"),
            correlation_id=identifier("crash-correlation"),
            application_build_id="agent-runtime-crash-matrix",
            commit_sha=RELEASE_SHA,
            idempotency_key=(
                f"{project_id}:chapter:1:{crash_point}:{identifier('run')}"
            ),
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(
                chapter_fixtures.ChapterAuthoritySchedulerPostgresTests._release_evidence(
                    project_id
                )
            ),
        ),
        principal=operator,
    )
    old_scheduler = old_application.scheduler(
        principal=_principal(
            old_worker,
            PrincipalType.WORKER,
            project_id,
            {"chapter.authority.execute"},
        )
    )
    for expected_node in ("plan", "context"):
        assert (
            old_scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            ).node
            == expected_node
        )

    controller.target = crash_point
    with pytest.raises(SimulatedProcessCrash, match=crash_point):
        old_scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
    assert controller.triggered
    before = _draft_snapshot(project_id, admission.root_operation_id)
    assert before["attempt_count"] == 1
    assert before["operation_status"] == "EXECUTING"
    assert before["attempt_status"] == "RUNNING"
    assert (
        tuple(before[field] for field in CRASH_PRE_STATE_FIELDS)
        == (CRASH_POINT_PRE_STATE[crash_point])
    )
    old_execution.close()
    del old_scheduler, old_application

    _expire_worker_lease(project_id, admission.root_operation_id)
    expired = scan_expired_attempt_leases(
        DATABASE_URL,
        actor_id="crash-matrix-maintenance",
    )
    assert any(item["attempt_id"] == before["attempt_id"] for item in expired)

    new_application, new_execution = _application(object_root=object_root)
    new_scheduler = new_application.scheduler(
        principal=_principal(
            new_worker,
            PrincipalType.WORKER,
            project_id,
            {"chapter.authority.execute"},
        )
    )
    recovered = new_scheduler.tick(
        project_id=project_id,
        root_operation_id=admission.root_operation_id,
    )
    assert recovered.node == "draft"
    assert recovered.operation_status == "SUCCEEDED"
    after = _draft_snapshot(project_id, admission.root_operation_id)

    assert after["attempt_id"] == before["attempt_id"]
    assert after["attempt_count"] == 1
    assert after["lease_count"] == 2
    assert after["execution_fence"] < after["recovery_fence"]
    assert after["external_effect_count"] == 1
    assert after["provider_dispatch_count"] == 1
    assert after["provider_request_count"] == 1
    assert after["budget_reservation_count"] == 1
    assert after["budget_settlement_count"] == 1
    assert after["cost_evidence_count"] <= 1
    assert after["work_order_count"] == 1
    assert after["runtime_binding_count"] == 1
    assert after["candidate_count"] == 1
    assert after["asset_count"] == 1
    assert after["decision_count"] == 1
    assert after["commit_count"] == 1
    assert after["attempt_result_count"] == 1
    assert after["operation_status"] == "SUCCEEDED"
    assert after["attempt_status"] == "SUCCEEDED"
    assert after["duplicate_event_fact_count"] == 0
    if before["provider_request_id"]:
        assert after["provider_request_id"] == before["provider_request_id"]

    verifier = PostgresAttemptFenceVerifier(DATABASE_URL)
    with pytest.raises(ValueError, match="execution-active|current held"):
        verifier.assert_current(
            after["operation_id"],
            after["attempt_id"],
            after["execution_fence"],
        )
    lineage = AgentRuntimeQuery(DATABASE_URL).require_asset_lineage(
        project_id=project_id,
        asset_version_id=after["asset_version_id"],
    )
    assert lineage["lineage_strength"] == "EXACT_COLLABORATION_COMMIT"
    new_execution.close()


def test_new_attempt_retry_supersedes_failed_candidate(
    tmp_path: Path,
    crash_authority_scope: dict[str, str],
) -> None:
    project_id = crash_authority_scope["project_id"]
    workspace_id = crash_authority_scope["workspace_id"]
    actor = crash_authority_scope["actor"]
    first_worker = "worker-retry-attempt-1"
    second_worker = "worker-retry-attempt-2"
    controller = CrashController()
    application, execution = _application(
        object_root=tmp_path / "new-attempt-retry",
        fault_injector=controller,
    )
    admission = application.admit(
        SingleChapterRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=actor,
            chapter=1,
            title="One Attempt-aware Retry",
            premise="A failed candidate cannot cross the Attempt boundary.",
            trace_id=identifier("retry-trace"),
            correlation_id=identifier("retry-correlation"),
            application_build_id="agent-runtime-crash-matrix",
            commit_sha=RELEASE_SHA,
            idempotency_key=f"{project_id}:retry:{identifier('run')}",
            preparation_report={"decision": "READY", "fixture": True},
            context_candidates=tuple(
                chapter_fixtures.ChapterAuthoritySchedulerPostgresTests._release_evidence(
                    project_id
                )
            ),
        ),
        principal=_principal(
            actor,
            PrincipalType.LOCAL_OPERATOR,
            project_id,
            {"chapter.authority.execute", "agent.authority.admin"},
        ),
    )
    scheduler = application.scheduler(
        principal=_principal(
            first_worker,
            PrincipalType.WORKER,
            project_id,
            {"chapter.authority.execute"},
        )
    )
    for expected_node in ("plan", "context"):
        assert (
            scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            ).node
            == expected_node
        )
    controller.target = "after_candidate_persist"
    with pytest.raises(SimulatedProcessCrash, match="after_candidate_persist"):
        scheduler.tick(
            project_id=project_id,
            root_operation_id=admission.root_operation_id,
        )
    first = _draft_snapshot(project_id, admission.root_operation_id)
    submit_attempt_failure(
        DATABASE_URL,
        WorkerLeaseCommand(
            attempt_id=str(first["attempt_id"]),
            project_id=project_id,
            worker_id=first_worker,
            fencing_token=int(first["recovery_fence"]),
            trace_id=identifier("retry-failure-trace"),
            correlation_id=identifier("retry-failure-correlation"),
            causation_id=str(first["operation_id"]),
        ),
        retryable=True,
        error_code="SCRIPTED_RETRYABLE_FAILURE",
        error_message="fixture retry after Candidate persistence",
        failure_class="RETRYABLE",
    )
    execution.close()
    del scheduler, application

    recovered_application, recovered_execution = _application(
        object_root=tmp_path / "new-attempt-retry"
    )
    recovered_scheduler = recovered_application.scheduler(
        principal=_principal(
            second_worker,
            PrincipalType.WORKER,
            project_id,
            {"chapter.authority.execute"},
        )
    )
    recovered = recovered_scheduler.tick(
        project_id=project_id,
        root_operation_id=admission.root_operation_id,
    )
    assert recovered.node == "draft"
    assert recovered.operation_status == "SUCCEEDED"
    assert recovered.recovery_mode == "retry_attempt"

    facts = _retry_facts(project_id, str(first["operation_id"]))
    assert facts["attempt_numbers"] == [1, 2]
    assert facts["attempt_statuses"] == ["FAILED_RETRYABLE", "SUCCEEDED"]
    assert facts["attempt_ids"][0] == first["attempt_id"]
    assert facts["attempt_ids"][0] != facts["attempt_ids"][1]
    assert facts["effect_count"] == 2
    assert facts["dispatch_count"] == 2
    assert len(set(facts["provider_request_ids"])) == 2
    assert facts["budget_count"] == 2
    assert facts["settled_budget_count"] == 2
    assert facts["work_order_count"] == 2
    assert facts["binding_count"] == 2
    assert facts["session_count"] == 2
    assert facts["candidate_count"] == 2
    assert facts["supersession_count"] == 1
    assert facts["session_statuses"] == ["FAILED", "COMMITTED"]
    assert facts["decision_count"] == 1
    assert facts["commit_count"] == 1
    assert facts["commit_attempt_id"] == facts["attempt_ids"][1]
    assert facts["effective_candidate_id"] == facts["commit_candidate_id"]
    assert facts["failure_reason"]["result"]["error_code"] == (
        "SCRIPTED_RETRYABLE_FAILURE"
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        collaboration = AgentCollaborationApplication(
            uow.repositories.agent_collaboration
        )
        with pytest.raises(ValueError, match="only an accepted session can commit"):
            collaboration.commit_accepted_candidate(
                facts["session_ids"][0],
                operation_id=str(first["operation_id"]),
                idempotency_key="forbidden-superseded-commit",
            )
    with connect() as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            connection.execute(
                """
                UPDATE authority_agent_candidate_supersession
                SET failure_reason='{}'::jsonb
                WHERE operation_id=%s
                """,
                [str(first["operation_id"])],
            )
            connection.commit()
        connection.rollback()

    run = AgentRuntimeQuery(DATABASE_URL).require_run(
        project_id=project_id,
        agent_run_id=str(first["operation_id"]),
    )
    assert len(run["candidate_attempts"]) == 2
    assert run["effective_candidate"]["attempt_id"] == facts["attempt_ids"][1]
    health = AgentRuntimeQuery(DATABASE_URL).recovery_health(project_id=project_id)
    assert health["superseded_candidate"] >= 1
    assert all(
        "superseded_candidate" not in scope["categories"]
        or set(scope["categories"]) == {"superseded_candidate"}
        for scope in health["scopes"]
    )
    recovered_execution.close()


def test_recovery_authorization_constraints_require_a_current_fence(
    tmp_path: Path,
    crash_authority_scope: dict[str, str],
) -> None:
    test_postgres_process_crash_matrix(
        "after_external_effect_plan",
        tmp_path,
        crash_authority_scope,
    )
    project_id = crash_authority_scope["project_id"]
    with connect() as connection:
        row = connection.execute(
            """
            SELECT authorization_id, operation_id, attempt_id,
                   external_effect_id, execution_id,
                   execution_fencing_token, recovery_fencing_token,
                   recovery_worker_id, trace_id, correlation_id
            FROM authority_execution_recovery_authorization
            WHERE project_id=%s
            ORDER BY created_at DESC, authorization_id DESC
            LIMIT 1
            """,
            [project_id],
        ).fetchone()
        assert row is not None
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            connection.execute(
                """
                UPDATE authority_execution_recovery_authorization
                SET action='QUERY'
                WHERE authorization_id=%s
                """,
                [row[0]],
            )
            connection.commit()
        connection.rollback()
        with pytest.raises(psycopg.errors.CheckViolation) as rejected:
            connection.execute(
                """
                INSERT INTO authority_execution_recovery_authorization(
                    authorization_id, project_id, operation_id, attempt_id,
                    external_effect_id, execution_id,
                    execution_fencing_token, recovery_fencing_token,
                    recovery_worker_id, action, trace_id, correlation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'QUERY', %s, %s)
                """,
                [
                    identifier("inactive-recovery-authorization"),
                    project_id,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                ],
            )
            connection.commit()
        assert rejected.value.diag.constraint_name == (
            "authority_execution_recovery_fact_guard"
        )
        connection.rollback()


def _application(
    *,
    object_root: Path,
    fault_injector: CrashController | None = None,
):
    settings = IndustrialSettings(
        root=Path.cwd(),
        environment="test",
        database_url=DATABASE_URL,
    )
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(object_root),
    }
    execution = build_production_execution_composition(settings, env=env)
    return (
        build_chapter_authority_application(
            settings,
            execution=execution,
            env=env,
            runtime_fault_injector=fault_injector,
        ),
        execution,
    )


def _principal(
    principal_id: str,
    principal_type: PrincipalType,
    project_id: str,
    permissions: set[str],
) -> Principal:
    return Principal(
        principal_id=principal_id,
        principal_type=principal_type,
        permissions=frozenset(permissions),
        project_scope=frozenset({project_id}),
        authentication_source="integration-fixture",
    )


def _expire_worker_lease(project_id: str, root_operation_id: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE authority_lease_acquisition AS lease
            SET expires_at=lease.acquired_at + INTERVAL '1 microsecond'
            FROM authority_attempt AS attempt
            JOIN authority_operation AS operation
              ON operation.operation_id=attempt.operation_id
            WHERE lease.attempt_id=attempt.attempt_id
              AND operation.project_id=%s
              AND operation.definition_name='chapter.draft.generate'
              AND operation.root_operation_id=%s
              AND lease.status='HELD'
            """,
            [project_id, root_operation_id],
        )
        connection.commit()


def _draft_snapshot(project_id: str, root_operation_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT operation.operation_id, operation.status,
                   attempt.attempt_id, attempt.status,
                   COUNT(DISTINCT all_attempt.attempt_id),
                   COUNT(DISTINCT lease.lease_id),
                   MIN(lease.fencing_token), MAX(lease.fencing_token),
                   COUNT(DISTINCT effect.external_effect_id),
                   COUNT(DISTINCT dispatch.dispatch_id),
                   COUNT(DISTINCT COALESCE(
                       NULLIF(effect.provider_request_id, ''),
                       NULLIF(dispatch.provider_correlation_id, '')
                   )),
                   MAX(COALESCE(
                       NULLIF(effect.provider_request_id, ''),
                       dispatch.provider_correlation_id
                   )),
                   COUNT(DISTINCT budget.reservation_id),
                   COUNT(DISTINCT budget.reservation_id)
                       FILTER (WHERE budget.status='SETTLED'),
                   COUNT(DISTINCT cost.cost_evidence_id),
                   COUNT(DISTINCT work_order.work_order_id),
                   COUNT(DISTINCT binding.binding_id),
                   COUNT(DISTINCT candidate.candidate_version_id),
                   COUNT(DISTINCT output.asset_version_id)
                       FILTER (WHERE output.role='primary'),
                   MAX(output.asset_version_id)
                       FILTER (WHERE output.role='primary'),
                   COUNT(DISTINCT decision.decision_id),
                   COUNT(DISTINCT collaboration_commit.commit_id),
                   COUNT(DISTINCT attempt.attempt_id)
                       FILTER (WHERE attempt.result <> '{}'::jsonb),
                   (
                       SELECT COUNT(*)
                       FROM (
                           SELECT event_type, aggregate_id, payload
                           FROM state_event AS event
                           WHERE event.payload->>'operation_id'
                                 =operation.operation_id
                           GROUP BY event_type, aggregate_id, payload
                           HAVING COUNT(*) > 1
                       ) AS duplicate
                   )
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_attempt AS all_attempt
              ON all_attempt.operation_id=operation.operation_id
            LEFT JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            LEFT JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            LEFT JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            LEFT JOIN authority_budget_reservation AS budget
              ON budget.operation_id=operation.operation_id
            LEFT JOIN authority_operation_cost_evidence AS cost
              ON cost.operation_id=operation.operation_id
            LEFT JOIN authority_agent_work_order AS work_order
              ON work_order.operation_id=operation.operation_id
            LEFT JOIN authority_agent_runtime_binding AS binding
              ON binding.operation_id=operation.operation_id
            LEFT JOIN authority_agent_candidate_version AS candidate
              ON candidate.originating_turn_id=work_order.turn_id
            LEFT JOIN authority_operation_output_asset AS output
              ON output.operation_id=operation.operation_id
            LEFT JOIN authority_agent_collaboration_decision AS decision
              ON decision.candidate_version_id=candidate.candidate_version_id
            LEFT JOIN authority_agent_collaboration_commit
              AS collaboration_commit
              ON collaboration_commit.candidate_version_id=
                 candidate.candidate_version_id
            WHERE operation.project_id=%s
              AND operation.definition_name='chapter.draft.generate'
              AND operation.root_operation_id=%s
            GROUP BY operation.operation_id, operation.status,
                     attempt.attempt_id, attempt.status
            """,
            [project_id, root_operation_id],
        ).fetchone()
    assert row is not None
    names = (
        "operation_id",
        "operation_status",
        "attempt_id",
        "attempt_status",
        "attempt_count",
        "lease_count",
        "execution_fence",
        "recovery_fence",
        "external_effect_count",
        "provider_dispatch_count",
        "provider_request_count",
        "provider_request_id",
        "budget_reservation_count",
        "budget_settlement_count",
        "cost_evidence_count",
        "work_order_count",
        "runtime_binding_count",
        "candidate_count",
        "asset_count",
        "asset_version_id",
        "decision_count",
        "commit_count",
        "attempt_result_count",
        "duplicate_event_fact_count",
    )
    return dict(zip(names, row, strict=True))


def _retry_facts(project_id: str, operation_id: str) -> dict[str, object]:
    with connect() as connection:
        attempts = connection.execute(
            """
            SELECT attempt_id, attempt_number, status
            FROM authority_attempt
            WHERE operation_id=%s
            ORDER BY attempt_number
            """,
            [operation_id],
        ).fetchall()
        sessions = connection.execute(
            """
            SELECT session.session_id, session.status,
                   candidate.candidate_version_id,
                   supersession.supersession_id,
                   supersession.failure_reason
            FROM authority_agent_collaboration_session AS session
            JOIN authority_agent_candidate_version AS candidate
              ON candidate.session_id=session.session_id
            LEFT JOIN authority_agent_candidate_supersession AS supersession
              ON supersession.superseded_candidate_version_id=
                 candidate.candidate_version_id
            WHERE session.project_id=%s
              AND session.created_operation_id=%s
            ORDER BY (
                SELECT attempt_number FROM authority_attempt
                WHERE attempt_id=session.attempt_id
            )
            """,
            [project_id, operation_id],
        ).fetchall()
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM authority_external_effect
               WHERE operation_id=%s),
              (SELECT COUNT(*) FROM authority_external_effect_dispatch AS dispatch
               JOIN authority_external_effect AS effect
                 ON effect.external_effect_id=dispatch.external_effect_id
               WHERE effect.operation_id=%s),
              (SELECT ARRAY_AGG(dispatch.provider_correlation_id
                                ORDER BY dispatch.created_at)
               FROM authority_external_effect_dispatch AS dispatch
               JOIN authority_external_effect AS effect
                 ON effect.external_effect_id=dispatch.external_effect_id
               WHERE effect.operation_id=%s),
              (SELECT COUNT(*) FROM authority_budget_reservation
               WHERE operation_id=%s),
              (SELECT COUNT(*) FROM authority_budget_reservation
               WHERE operation_id=%s AND status='SETTLED'),
              (SELECT COUNT(*) FROM authority_agent_work_order
               WHERE operation_id=%s),
              (SELECT COUNT(*) FROM authority_agent_runtime_binding
               WHERE operation_id=%s),
              (SELECT COUNT(*) FROM authority_agent_collaboration_session
               WHERE project_id=%s AND created_operation_id=%s),
              (SELECT COUNT(*) FROM authority_agent_candidate_version AS candidate
               JOIN authority_agent_collaboration_session AS session
                 ON session.session_id=candidate.session_id
               WHERE session.project_id=%s AND session.created_operation_id=%s),
              (SELECT COUNT(*) FROM authority_agent_candidate_supersession
               WHERE operation_id=%s),
              (SELECT COUNT(*) FROM authority_agent_collaboration_decision
               WHERE session_id IN (
                 SELECT session_id FROM authority_agent_collaboration_session
                 WHERE project_id=%s AND created_operation_id=%s
               )),
              (SELECT COUNT(*) FROM authority_agent_collaboration_commit
               WHERE operation_id=%s)
            """,
            [
                operation_id,
                operation_id,
                operation_id,
                operation_id,
                operation_id,
                operation_id,
                operation_id,
                project_id,
                operation_id,
                project_id,
                operation_id,
                operation_id,
                project_id,
                operation_id,
                operation_id,
            ],
        ).fetchone()
        commit = connection.execute(
            """
            SELECT attempt_id, candidate_version_id
            FROM authority_agent_collaboration_commit
            WHERE operation_id=%s
            """,
            [operation_id],
        ).fetchone()
    assert counts is not None and commit is not None
    effective = next(row for row in reversed(sessions) if row[3] is None)
    superseded = next(row for row in sessions if row[3] is not None)
    return {
        "attempt_ids": [str(row[0]) for row in attempts],
        "attempt_numbers": [int(row[1]) for row in attempts],
        "attempt_statuses": [str(row[2]) for row in attempts],
        "session_ids": [str(row[0]) for row in sessions],
        "session_statuses": [str(row[1]) for row in sessions],
        "effect_count": int(counts[0]),
        "dispatch_count": int(counts[1]),
        "provider_request_ids": list(counts[2] or []),
        "budget_count": int(counts[3]),
        "settled_budget_count": int(counts[4]),
        "work_order_count": int(counts[5]),
        "binding_count": int(counts[6]),
        "session_count": int(counts[7]),
        "candidate_count": int(counts[8]),
        "supersession_count": int(counts[9]),
        "decision_count": int(counts[10]),
        "commit_count": int(counts[11]),
        "commit_attempt_id": str(commit[0]),
        "commit_candidate_id": str(commit[1]),
        "effective_candidate_id": str(effective[2]),
        "failure_reason": dict(superseded[4] or {}),
    }
