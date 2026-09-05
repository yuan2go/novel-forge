from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.completion import (
    PostgresBookCompletionAuthority,
    HUMAN_POLICY_BLOCKER,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
)


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    ensure_migrated()


@pytest.fixture
def scope() -> dict:
    project_id = identifier("completion")
    workspace_id = "workspace:" + project_id
    book_id = "book:" + project_id
    book_run_id = "run:" + project_id
    seed_authority_project_book(
        project_id=project_id, workspace_id=workspace_id, book_id=book_id
    )
    operation_id = "operation:" + book_run_id
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        insert_definition(uow.cursor, project_id)
        insert_operation(
            uow.cursor,
            operation_id=operation_id,
            definition_name=project_id,
            project_id=project_id,
            workspace_id=workspace_id,
            status="SUCCEEDED",
        )
        uow.cursor.execute(
            "INSERT INTO authority_saga(saga_id,root_operation_id,project_id,status,trace_id,correlation_id) VALUES (%s,%s,%s,'SUCCEEDED',%s,%s)",
            [book_run_id, operation_id, project_id, project_id, project_id],
        )
        uow.cursor.execute(
            """INSERT INTO authority_book_production(
            book_run_id,project_id,workspace_id,book_id,book_design_version,book_plan_version,
            production_profile_version,longform_context_versions,root_operation_id,saga_id,
            stable_idempotency_key,state,current_chapter,target_chapter_count,light_recap_cadence,formal_recap_cadence,input_mode
        ) VALUES (%s,%s,%s,%s,'design:1','plan:1','profile:1',%s,%s,%s,%s,'READY',0,1,1,1,'LEGACY_FIXTURE_INPUT_MODE')""",
            [
                book_run_id,
                project_id,
                workspace_id,
                book_id,
                Jsonb(
                    {
                        "arc_plan_versions": ["source:1"],
                        **{
                            key: "source:1"
                            for key in (
                                "volume_plan_version",
                                "character_state_version",
                                "foreshadowing_state_version",
                                "quality_trend_version",
                                "reward_ledger_version",
                                "promise_ledger_version",
                            )
                        },
                    }
                ),
                operation_id,
                book_run_id,
                project_id,
            ],
        )
        uow.commit()
    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "book_run_id": book_run_id,
        "principal": Principal(
            principal_id="completion-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute", "book.authority.query"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        ),
    }


def _authority() -> PostgresBookCompletionAuthority:
    return PostgresBookCompletionAuthority(
        DATABASE_URL, application_build_id="completion-tests", commit_sha="e" * 40
    )


def _command(scope: dict, key: str) -> dict:
    return {
        **scope,
        "idempotency_key": key,
        "trace_id": "trace:" + key,
        "correlation_id": "correlation:" + key,
    }


def _decision(scope: dict, case: dict, key: str, **changes) -> dict:
    return {
        **_command(scope, key),
        "case_id": case["case_id"],
        "source_digest": case["source_digest"],
        "expected_case_version": case["case_version"],
        "expected_decision_version": 0,
        "decision": "REJECTED",
        "rationale": "Accepted history is incomplete.",
        **changes,
    }


def test_assessment_is_versioned_replayable_and_has_atomic_kernel_evidence(
    scope: dict,
) -> None:
    authority = _authority()
    key = identifier("assess")
    first = authority.assess(**_command(scope, key))
    replay = _authority().assess(**_command(scope, key))
    assert first["status"] == "NEEDS_REMEDIATION"
    assert replay["replayed"] is True
    assert replay["case_id"] == first["case_id"]
    assert replay["case_version"] == 1
    queried = authority.require_case(**scope, case_id=first["case_id"])
    assert queried["source_current"] is True
    assert queried["decision"] is None
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id=%s",
            [first["operation_id"]],
        )
        assert uow.cursor.fetchone()[0] == "SUCCEEDED"
        result = uow.repositories.operations.transaction_result(
            first["operation_id"], scope["project_id"]
        )["result"]
        assert result["case_id"] == first["case_id"]
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_attempt WHERE operation_id=%s",
            [first["operation_id"]],
        )
        assert uow.cursor.fetchone()[0] == 0


def test_rollback_and_postcommit_response_loss_do_not_duplicate_cases(
    scope: dict,
) -> None:
    key = identifier("recovery")

    def before_commit(point: str) -> None:
        if point == "after_completion_evidence":
            raise RuntimeError("crash before commit")

    with pytest.raises(RuntimeError, match="before commit"):
        _authority().assess(**_command(scope, key), fault_injector=before_commit)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_book_completion_case WHERE book_run_id=%s",
            [scope["book_run_id"]],
        )
        assert uow.cursor.fetchone()[0] == 0

    def response_loss(point: str) -> None:
        if point == "after_operation_completion_before_response":
            raise RuntimeError("response lost")

    with pytest.raises(RuntimeError, match="response lost"):
        _authority().assess(**_command(scope, key), fault_injector=response_loss)
    replay = _authority().assess(**_command(scope, key))
    assert replay["replayed"] is True
    assert replay["case_version"] == 1


def test_rejection_is_immutable_versioned_and_cas_protected(scope: dict) -> None:
    first = _authority().assess(**_command(scope, identifier("assess")))
    key = identifier("decide")
    decision = _authority().decide(**_decision(scope, first, key))
    assert decision["status"] == "REJECTED"
    assert _authority().decide(**_decision(scope, first, key))["replayed"] is True
    second = _authority().assess(**_command(scope, identifier("assess")))
    assert second["case_version"] == 2
    with pytest.raises(KernelError, match="cursor changed"):
        _authority().decide(**_decision(scope, second, identifier("stale")))
    with pytest.raises(KernelError, match="terminal completion evidence"):
        _authority().decide(
            **_decision(scope, first, identifier("repeat"), expected_decision_version=1)
        )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(Exception, match="immutable"):
            uow.cursor.execute(
                "UPDATE authority_book_completion_case SET status='READY_FOR_EDITORIAL' WHERE case_id=%s",
                [first["case_id"]],
            )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(Exception, match="immutable"):
            uow.cursor.execute(
                "DELETE FROM authority_book_completion_decision WHERE decision_id=%s",
                [decision["decision_id"]],
            )


def test_source_change_rejects_decision_without_rewriting_assessment(
    scope: dict,
) -> None:
    case = _authority().assess(**_command(scope, identifier("assess")))
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "UPDATE authority_book_production SET state='PAUSED' WHERE book_run_id=%s",
            [scope["book_run_id"]],
        )
        uow.commit()
    with pytest.raises(KernelError, match="current exact accepted source"):
        _authority().decide(**_decision(scope, case, identifier("decide")))
    current = _authority().require_case(**scope, case_id=case["case_id"])
    assert current["source_current"] is False
    assert current["source_digest"] == case["source_digest"]


def test_acceptance_is_durably_blocked_without_native_whole_book_human_policy(
    scope: dict,
) -> None:
    case = _authority().assess(**_command(scope, identifier("assess")))
    result = _authority().decide(
        **_decision(scope, case, identifier("accept"), decision="ACCEPTED")
    )
    assert result["status"] == "BLOCKED"
    assert HUMAN_POLICY_BLOCKER in result["blockers"]
    assert "WAITING_EXTERNAL_HUMAN_EVIDENCE" in result["blockers"]
    assert result["evidence_dimensions"]["HUMAN_EDITORIAL"] == "WAITING_EVIDENCE"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT accepted_through_chapter,state FROM authority_book_production WHERE book_run_id=%s",
            [scope["book_run_id"]],
        )
        assert uow.cursor.fetchone() == (0, "READY")
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s",
            [scope["book_run_id"]],
        )
        assert uow.cursor.fetchone()[0] == 0
