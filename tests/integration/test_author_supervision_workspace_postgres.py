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
from tests.integration.test_cross_model_source_postgres import original_author_draft as original_author_draft
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


def test_author_review_grant_recovers_new_attempt_without_rewriting_frozen_block(original_author_draft, tmp_path):
    from types import SimpleNamespace
    import pytest
    from psycopg.types.json import Jsonb
    from novel_forge.api.authority_dependencies import build_production_execution_composition
    from novel_forge.infrastructure.settings import IndustrialSettings
    from novel_forge.modules.book_authority.author_supervision import approve_route
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.command_kernel.attempt_runtime import (
        WorkerLeaseCommand, WorkerResultCommand, create_attempt, queue_attempt,
        acquire_attempt_lease, start_attempt, submit_attempt_result,
    )
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
    from tests.integration.capability_pack_postgres_support import ROOT

    scope, source_run, _ = original_author_draft
    project, book, workspace = (scope[key] for key in ("project_id", "book_id", "workspace_id"))
    author = Principal("source-author-test", PrincipalType.LOCAL_OPERATOR,
        frozenset({"book.authority.execute", "book.authority.query"}), frozenset({project}), "isolated-test")
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=project, workspace_id=workspace,
        content={"policy_version": "review-recovery-before-grant", "task_overrides": [], "reason": "Isolated review routing recovery",
            "author_supervised_books": [{"book_id": book, "author_id": author.principal_id, "reason": "Isolated review routing recovery"}]},
        idempotency_key=identifier("review-policy"), trace_id=project, correlation_id=project,
        application_build_id="review-recovery-test", commit_sha="a"*40, principal=author)
    operation, definition = identifier("review-recovery-operation"), identifier("review-recovery-fixture")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        draft = uow.repositories.asset_documents.require(project_id=project,
            asset_version_id=source_run.outputs[ChapterNode.DRAFT].asset_version_id)
        insert_definition(uow.cursor, definition)
        insert_operation(uow.cursor, operation_id=operation, definition_name=definition, project_id=project,
            workspace_id=workspace, status="READY", command_payload={"book_id": book, "chapter": scope["chapter"]})
        uow.cursor.execute("UPDATE authority_operation SET input_asset_snapshot=%s WHERE operation_id=%s",
            [Jsonb([{"asset_version_id": draft.asset_version_id, "content_hash": draft.content_hash}]), operation])
        uow.commit()

    def start_native_attempt():
        created = create_attempt(DATABASE_URL, operation_id=operation, project_id=project, max_attempts=2,
            trace_id=project, correlation_id=project)
        attempt = created["attempt_id"]
        queue_attempt(DATABASE_URL, attempt_id=attempt, project_id=project, trace_id=project, correlation_id=project)
        lease = acquire_attempt_lease(DATABASE_URL, attempt_id=attempt, project_id=project,
            worker_id="review-routing-test-worker", lease_seconds=60, trace_id=project, correlation_id=project)
        command = WorkerLeaseCommand(attempt_id=attempt, project_id=project, worker_id="review-routing-test-worker",
            fencing_token=lease["fencing_token"], trace_id=project, correlation_id=project)
        start_attempt(DATABASE_URL, command)
        return command

    settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=DATABASE_URL)
    composition = build_production_execution_composition(settings, env={"NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2", "NOVEL_FORGE_COMMIT_SHA": "a"*40,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "review-recovery-test", "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path)})
    base_route = composition.gateway.routes["review"]
    model = deepseek_candidates(available=True)[0]
    from novel_forge.modules.review.cross_model_binding import freeze_review_requirement
    router = ProductionProviderRouter(DATABASE_URL, review_requirement_resolver=freeze_review_requirement, candidates=[model], task_money_limit="1", task_token_limit=200000,
        token_caps={"work_total": 1000000}, call_caps={"work_total": 10}, execution_environment="development")
    first = start_native_attempt()
    arguments = dict(task_type="review", project_id=project, work_id=book, operation_id=operation,
        attempt_id=first.attempt_id, stable_key=operation+":review", input_tokens=1000, output_tokens=1000,
        trace_id=project, correlation_id=project, request_input={}, chapter=scope["chapter"],
        producer_contract={"schema_version": "fixture-review-routing-contract.v1", "stage": "review"})
    with pytest.raises(KernelError, match="PROVIDER_ROUTING_BLOCKED"):
        router.select(base_route, **arguments)
    pending = supervision_workspace(DATABASE_URL, project_id=project, book_id=book, principal=author)
    blocked_ref = next(p for p in pending["producers"] if p["operation_id"] == operation)
    frozen = router.registry.query.require(project_id=project, asset_version_id=blocked_ref["routing_asset_version_id"])
    blocked = deepcopy(frozen.content)
    requirement = blocked["task"]["declared_requirements"]["cross_model_review"]
    assert blocked["status"] == "BLOCKED"
    assert "CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED" in blocked["candidates"][0]["rejected_reasons"]
    assert requirement["schema_version"] == "cross-model-review.v2"
    assert requirement["authorized_reviewer"] == {}
    assert requirement["target_asset_version_id"] == draft.asset_version_id
    assert requirement["target_content_hash"] == draft.content_hash
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT version FROM authority_operation WHERE operation_id=%s", [operation])
        operation_version = uow.cursor.fetchone()[0]
    submit_attempt_result(DATABASE_URL, WorkerResultCommand(**first.__dict__, expected_operation_version=operation_version),
        outcome="retryable_failure", result={"code": "PROVIDER_ROUTING_BLOCKED", "request_sent": False,
            "routing_asset_version_id": frozen.asset_version_id})

    request = SimpleNamespace(routing_asset_version_id=frozen.asset_version_id, candidate_id=model.candidate_id,
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), maximum_tokens=100000, maximum_amount="1",
        reason="Isolated author approval for this exact reviewer task and Producer",
        expected_policy_hash=pending["policy_hash"], idempotency_key=identifier("approve-review-route"))
    approved = approve_route(DATABASE_URL, project_id=project, book_id=book, request=request, principal=author,
        application_build_id="review-recovery-test", commit_sha="a"*40)
    replay_approval = approve_route(DATABASE_URL, project_id=project, book_id=book, request=request, principal=author,
        application_build_id="review-recovery-test", commit_sha="a"*40)
    assert replay_approval["operation_id"] == approved["operation_id"]
    with pytest.raises(KernelError, match="PROVIDER_ROUTING_BLOCKED"):
        router.select(base_route, **arguments)
    assert router.registry.query.require(project_id=project, asset_version_id=frozen.asset_version_id).content == blocked

    second = start_native_attempt()
    assert second.attempt_id != first.attempt_id
    next_arguments = {**arguments, "attempt_id": second.attempt_id}
    _, allowed = router.select(base_route, **next_arguments)
    _, replay = router.select(base_route, **next_arguments)
    assert replay == allowed
    assert allowed["status"] == "AUTHOR_SUPERVISED_SELECTED"
    current = allowed["task"]["declared_requirements"]["cross_model_review"]
    assert current["target_asset_version_id"] == requirement["target_asset_version_id"]
    assert current["target_content_hash"] == requirement["target_content_hash"]
    assert current["source"] == requirement["source"]
    assert current["authorized_reviewer"]["candidate_id"] == model.candidate_id
    assert allowed["asset_version_id"] != frozen.asset_version_id
    assert router.registry.query.require(project_id=project, asset_version_id=frozen.asset_version_id).content == blocked
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT attempt_id,status,attempt_number FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [operation])
        assert uow.cursor.fetchall() == [(first.attempt_id, "FAILED_RETRYABLE", 1), (second.attempt_id, "RUNNING", 2)]
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [operation])
        assert uow.cursor.fetchone()[0] == 0
        uow.cursor.execute("""SELECT count(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='routing_decision' AND v.content #>> '{task,operation_id}'=%s""", [project, operation])
        assert uow.cursor.fetchone()[0] == 2
