from copy import deepcopy
from datetime import datetime, timedelta, timezone

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.author_supervision import supervision_workspace
from novel_forge.modules.book_authority.control_policy import ControlPolicy
from novel_forge.modules.command_kernel.dispatch_control import change_dispatch_control
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.versioned_policy_repository import VersionedPolicyRepository
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, seed_authority_project_book, insert_definition, insert_operation
from tests.unit.test_author_supervised_routing import prepared


def test_workspace_projects_native_control_scope_expiry_and_preserves_frozen_policy(monkeypatch):
    ensure_migrated()
    project = identifier("supervision-workspace")
    book, workspace = "book:" + project, "workspace:" + project
    seed_authority_project_book(project_id=project, book_id=book, workspace_id=workspace)
    author = Principal("author", PrincipalType.LOCAL_OPERATOR,
        frozenset({"book.authority.execute", "book.authority.query"}), frozenset({project}), "isolated-test")
    scope, _ = prepared()
    policy = deepcopy(scope.policy_snapshot["policy"])
    policy["author_supervised_authorizations"][0]["book_id"] = book
    policy["author_supervised_authorizations"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    policy["author_supervised_books"] = [{"book_id": book, "author_id": "author", "reason": "Isolated UI query test"}]
    routing_result = configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", content=policy,
        project_id=project, workspace_id=workspace, idempotency_key=project+":routing", trace_id=project,
        correlation_id=project, application_build_id="workspace-query-test", commit_sha="a"*40, principal=author)
    monkeypatch.setenv("NOVEL_FORGE_NO_MODEL_DISPATCH", "1")
    initial = supervision_workspace(DATABASE_URL, project_id=project, book_id=book, principal=author)
    assert initial["book_modes"][0]["book_id"] == book
    assert initial["authorizations"][0]["expired"] is True
    assert initial["controls"]["book_control"]["selected_policy"] is None
    assert "SCENE" in initial["controls"]["book_control"]["supervised_boundaries"]
    assert initial["controls"]["budget_ledger"] == {"scope": "PROJECT", "rows": []}
    assert initial["controls"]["dispatch"]["api_process_suspended"] is True
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("""INSERT INTO authority_budget_reservation(
            reservation_id,operation_id,project_id,stable_idempotency_key,provider,currency,
            estimated_amount,reserved_amount,settled_amount,estimated_tokens,actual_tokens,status,
            accounting_basis,estimated_cost_status,settled_cost_status)
            VALUES (%s,%s,%s,%s,'fixture-subscription','USD',NULL,NULL,NULL,20,12,'HELD_UNKNOWN',
                'ACCOUNT_ENTITLEMENT','UNKNOWN','UNKNOWN')""",
            [project+":reservation", routing_result["operation_id"], project, project+":reservation"])
        old = VersionedPolicyRepository(uow.cursor, owner="BOOK_CONTROL", project_id=project).freeze(
            subject_id="frozen:chapter:1", default=ControlPolicy().to_dict(), actor_id="author")
        uow.commit()
    configure_owned_policy(database_url=DATABASE_URL, owner="BOOK_CONTROL",
        content=ControlPolicy(policy_version="test-supervised", mode="AUTHOR_SUPERVISED").to_dict(),
        project_id=project, workspace_id=workspace, idempotency_key=project+":control", trace_id=project,
        correlation_id=project, application_build_id="workspace-query-test", commit_sha="a"*40, principal=author)
    change_dispatch_control(DATABASE_URL, project_id=project, principal=author, state="PAUSED", expected_version=0,
        idempotency_key=project+":pause", reason="Isolated query test", release_identity={"commit_sha": "a"*40})
    current = supervision_workspace(DATABASE_URL, project_id=project, book_id=book, principal=author)
    controls = current["controls"]
    assert controls["dispatch"]["state"] == "PAUSED"
    budget = controls["budget_ledger"]["rows"][0]
    assert budget["status"] == "HELD_UNKNOWN"
    assert budget["cost_status"] == "UNKNOWN"
    assert budget["settled_amount"] is None and budget["reserved_amount"] is None
    assert budget["actual_tokens"] == 12 and budget["estimated_tokens"] == 20
    assert controls["book_control"]["scope"] == "PROJECT_FUTURE_SUBJECTS"
    assert controls["book_control"]["selected_policy"]["mode"] == "AUTHOR_SUPERVISED"
    assert set(controls["book_control"]["selected_boundaries"]) == set(controls["book_control"]["supervised_boundaries"])
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        frozen = VersionedPolicyRepository(uow.cursor, owner="BOOK_CONTROL", project_id=project).freeze(
            subject_id="frozen:chapter:1", default=ControlPolicy().to_dict(), actor_id="author")
        assert frozen == old


def test_workspace_keeps_distinct_review_targets_for_one_producer():
    ensure_migrated()
    project = identifier("review-target-query")
    book = "book:" + project
    seed_authority_project_book(project_id=project, book_id=book, workspace_id="workspace:"+project)
    author = Principal("author", PrincipalType.LOCAL_OPERATOR, frozenset({"book.authority.query"}), frozenset({project}), "isolated-test")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        operation = project+":operation"
        definition = project+":fixture-definition"
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=operation, definition_name=definition,
            project_id=project, workspace_id="workspace:"+project, status="EXECUTING")
        for number in (1, 2):
            review = {"schema_version": "cross-model-review.v2", "target_asset_version_id": f"fixture-target:{number}",
                "target_content_hash": "sha256:"+str(number)*64, "source": {"kind": "AUTHOR_ORIGINAL"},
                "reviewer_policy": "EXPLICIT_AUTHORIZED_REVIEWER", "authorized_reviewer": {}}
            uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(
                operation_id=operation, project_id=project, asset_id=project+f":route:{number}",
                asset_type="routing_decision", schema_version="fixture-workspace-query.v1",
                logical_ref=f"fixture/query/{number}", category="production_execution", output_key=f"routing.{number}",
                role="routing_evidence", content={"status": "BLOCKED", "candidates": [], "task": {
                    "task_type": "review", "work_id": book, "operation_id": operation,
                    "producer_contract_hash": "sha256:"+"a"*64, "declared_requirements": {"cross_model_review": review}}},
                qualification_policy="fixture-only", trace_id=project, correlation_id=project))
        uow.commit()
    view = supervision_workspace(DATABASE_URL, project_id=project, book_id=book, principal=author)
    assert len(view["producers"]) == 2
    targets = {p["review_requirement"]["target_asset_version_id"]: p["review_requirement"]["target_content_hash"] for p in view["producers"]}
    assert targets == {f"fixture-target:{n}": "sha256:"+str(n)*64 for n in (1, 2)}
