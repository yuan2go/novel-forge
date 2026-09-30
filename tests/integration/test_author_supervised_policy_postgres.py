from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import (
    selected_book_supervision, supervised_decision, verify_dispatch_budget, verify_policy_provenance,
)
from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, seed_authority_project_book
from tests.unit.test_author_supervised_routing import prepared


def test_native_author_policy_provenance_frozen_replay_and_nonrenewal():
    ensure_migrated()
    project = identifier("author-supervised")
    seed_authority_project_book(project_id=project, book_id="book", workspace_id="workspace:" + project)
    author = Principal("author", PrincipalType.LOCAL_OPERATOR, frozenset({"book.authority.execute"}), frozenset({project}), "isolated-test")
    scope, model = prepared()
    now = datetime.now(timezone.utc)
    policy = deepcopy(scope.policy_snapshot["policy"])
    policy["author_supervised_authorizations"][0]["expires_at"] = (now + timedelta(hours=1)).isoformat()
    def configure(value, actor=author, key="one"):
        return configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", content=value,
            project_id=project, workspace_id="workspace:" + project, idempotency_key=project + ":" + key,
            trace_id="test:author-supervised", correlation_id=project, application_build_id="author-supervised-test",
            commit_sha="a" * 40, principal=actor)
    result = configure(policy)
    assert configure(policy)["operation_id"] == result["operation_id"]
    assert configure(policy)["replayed"] is True
    with pytest.raises(PermissionError):
        configure(policy, replace(author, principal_type=PrincipalType.SERVICE), "service")
    with pytest.raises(KernelError):
        configure(policy, replace(author, principal_id="other-author"), "other")
    frozen = PostgresRoutingRegistry(DATABASE_URL).policy(project)
    task = replace(scope, project_id=project, policy_snapshot=frozen)
    decision = supervised_decision(CostAwareRouter().explain(task, [model], {}, now=now), now=now).to_dict()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        verify_policy_provenance(uow.cursor, decision)
        assert selected_book_supervision(uow.cursor, project_id=project, book_id="other") is None
        assert selected_book_supervision(uow.cursor, project_id=project, book_id="book")["literary_qualification"] == "NOT_PROVEN"
        verify_dispatch_budget(uow.cursor, decision, estimated_tokens=1000, amount=Decimal("0.01"), new_dispatch=True)
        with pytest.raises(KernelError, match="BUDGET_EXCEEDED"):
            verify_dispatch_budget(uow.cursor, decision, estimated_tokens=100001, amount=Decimal("0.01"), new_dispatch=True)
        corrupted = deepcopy(decision)
        corrupted["task"]["policy_snapshot"]["operation_id"] = "invented-approval"
        with pytest.raises(KernelError, match="UNTRUSTED"):
            verify_policy_provenance(uow.cursor, corrupted)
    configure({"policy_version": "strict-successor", "task_overrides": [], "reason": "return new work to strict mode"}, key="strict")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert selected_book_supervision(uow.cursor, project_id=project, book_id="book") is None
        verify_dispatch_budget(uow.cursor, decision, estimated_tokens=1000, amount=Decimal("0.01"), new_dispatch=False)
    assert decision["independent_qualification_eligible"] is False
    assert PostgresRoutingRegistry(DATABASE_URL).policy(project)["policy"]["policy_version"] == "strict-successor"


def test_native_author_design_is_approved_without_independent_qualification():
    from novel_forge.modules.content_authority import CONTENT_CODECS, ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.story_design_authority import DesignTransition, PlanningScope, PostgresStoryDesignAssetAuthority, StoryDesignTransitionCommand
    from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
    ensure_migrated()
    project = identifier("supervised-design")
    book, workspace = "book:" + project, "workspace:" + project
    seed_authority_project_book(project_id=project, book_id=book, workspace_id=workspace)
    author = Principal("author", PrincipalType.LOCAL_OPERATOR, frozenset({"book.authority.execute", "content.authority.execute",
        "content.operation:story_design.creative_foundation.author", "story_design.authority.execute"}), frozenset({project}), "isolated-test")
    scope, _ = prepared("creative.candidates.generate")
    policy = deepcopy(scope.policy_snapshot["policy"])
    grant = policy["author_supervised_authorizations"][0]
    grant.update(book_id=book, expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", content=policy, project_id=project, workspace_id=workspace,
        idempotency_key=project+":policy", trace_id=project, correlation_id=project, application_build_id="supervised-design-test", commit_sha="a"*40, principal=author)
    candidate = {"schema_version": "story_design.authority.v1", "project_id": project, "book_id": book,
        "generator_operation_name": "creative.candidates.generate", "planning_scope": "NOT_APPLICABLE", "logical_key": "foundation:test",
        "operator_authored": True, "provider_generated": False, "candidate_payload": {
            "objective": "Protect a witness while disclosing an accountable record.", "target_reader": "adult mystery readers",
            "why_worth_writing": "Truth requires responsibility for its consequences.", "genre": "mystery", "subgenre": "institutional mystery",
            "core_desire": "restore a lost record", "core_fear": "expose a witness", "core_conflict": "public evidence risks a private life",
            "narrative_engine": "each clue creates a concrete obligation", "differentiation": "proof has a physical cost",
            "emotional_contract": "courage includes return and protection", "serialization_potential": "new records expose connected obligations"}}
    content = ContentAuthorityApplication(DATABASE_URL, application_build_id="supervised-design-test", commit_sha="a"*40, integration_proven=CONTENT_CODECS, trusted_only=True)
    result = content.execute(ContentOperationRequest(definition_name="story_design.creative_foundation.author", project_id=project, workspace_id=workspace,
        actor_id=author.principal_id, trace_id=project, correlation_id=project, idempotency_key=project+":author", payload={"content": candidate}), principal=author)
    authority = PostgresStoryDesignAssetAuthority(DATABASE_URL, application_build_id="supervised-design-test", commit_sha="a"*40)
    state = {"version": 0}
    def transition(step, evidence, actor=author):
        return authority.transition(StoryDesignTransitionCommand(project_id=project, workspace_id=workspace, actor_id=actor.principal_id,
            trace_id=project, correlation_id=project, idempotency_key=project+":"+step.value+":"+actor.principal_id,
            asset_version_id=result.asset_version_id, content_hash=result.content_hash, logical_key="foundation:test",
            generator_operation_name="creative.candidates.generate", transition=step, planning_scope=PlanningScope.NOT_APPLICABLE,
            expected_version=state["version"], source_kind="OPERATOR_AUTHORED", evidence=evidence), principal=actor)
    state = transition(DesignTransition.ENROLL, {"operation_id": result.operation_id, "authoring_operation_id": result.operation_id,
        "operator_authored": True, "provider_generated": False})
    for step in (DesignTransition.MATERIALIZE, DesignTransition.STRUCTURAL_VALIDATE):
        state = transition(step, {"passed": True})
    review = {"asset_version_id": result.asset_version_id, "content_hash": result.content_hash,
        "decision": "ACCEPT", "reason": "Protocol test author explicitly preserves costly protection after disclosure", "findings": []}
    with pytest.raises(PermissionError):
        transition(DesignTransition.SEMANTIC_VALIDATE, {"author_review": review}, replace(author, principal_type=PrincipalType.WORKER))
    with pytest.raises(KernelError, match="EXACT_REVIEW"):
        transition(DesignTransition.SEMANTIC_VALIDATE, {"author_review": {**review, "content_hash": "sha256:"+"b"*64}})
    state = transition(DesignTransition.SEMANTIC_VALIDATE, {"author_review": review})
    with pytest.raises(KernelError, match="NOT_INDEPENDENT"):
        transition(DesignTransition.QUALIFY, {"passed": True})
    for step in (DesignTransition.SUBMIT_APPROVAL, DesignTransition.APPROVE):
        state = transition(step, {"author_review": review})
    state = transition(DesignTransition.ACTIVATE, {})
    assert (state["lifecycle"], state["qualification"], state["approval"]) == ("ACTIVE", "SEMANTICALLY_VALID", "APPROVED")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        receipt = approved_design_receipt(uow.cursor, project_id=project, book_id=book, asset_version_id=result.asset_version_id)
        assert receipt["author_review"] == review and receipt["literary_qualification"] == "NOT_PROVEN"
        uow.cursor.execute("SELECT count(*) FROM authority_narrative_design_qualification WHERE project_id=%s", [project])
        assert uow.cursor.fetchone()[0] == 0
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project])
        assert uow.cursor.fetchone()[0] == 0
        from novel_forge.storage.story_formation_repositories import StoryFormationRepository
        layer = StoryFormationRepository(uow.cursor).authored_creative_layer(project_id=project, book_id=book,
            asset_version_id=result.asset_version_id, content_hash=result.content_hash)
        assert layer.selection_basis == "AUTHOR_DIRECTION"
        assert layer.candidate_asset_version_ids == (result.asset_version_id,)
        from novel_forge.modules.review.cross_model_binding import generator_identity
        with pytest.raises(KernelError, match="CROSS_MODEL_REVIEW_SOURCE_REQUIRED"):
            generator_identity(uow.cursor, project_id=project, book_id=book, asset_version_id=result.asset_version_id, content_hash=result.content_hash)
        from novel_forge.modules.story_design_authority.author_supervision import reusable_qualified_design_receipt
        with pytest.raises(KernelError, match="LONGFORM_DESIGN_QUALIFICATION_INCOMPLETE"):
            reusable_qualified_design_receipt(uow.cursor, project_id=project, book_id=book,
                asset_version_id=result.asset_version_id, generator="creative.candidates.generate")
        with pytest.raises(KernelError):
            StoryFormationRepository(uow.cursor).authored_creative_layer(project_id=project, book_id="other-book",
                asset_version_id=result.asset_version_id, content_hash=result.content_hash)
    from types import SimpleNamespace
    from novel_forge.modules.book_authority.author_supervision import author_creative_input, decide_creative_input
    author = replace(author, permissions=author.permissions | {"content.operation:creative.brief.create"})
    brief = content.execute(ContentOperationRequest(definition_name="creative.brief.create", project_id=project, workspace_id=workspace,
        actor_id=author.principal_id, trace_id=project, correlation_id=project, idempotency_key=project+":brief",
        payload={"brief":{"creative_brief_contract_version":"creative-brief-v2","idea":"Protect an original witness while delivering the record.",
            "genre":"mystery","audience":"adult readers","constraints":["Evidence must be witnessed"],"source_boundaries":["Original author input"]}}), principal=author)
    request = SimpleNamespace(brief_asset_version_id=brief.asset_version_id, brief_content_hash=brief.content_hash,
        design=candidate["candidate_payload"], contribution="OPERATOR_AUTHORED_INPUT", idempotency_key=project+":author-adapter")
    args = dict(project_id=project, book_id=book, principal=author, application_build_id="supervised-design-test", commit_sha="a"*40)
    authored = author_creative_input(DATABASE_URL, request=request, **args)
    assert author_creative_input(DATABASE_URL, request=request, **args)["asset_version_id"] == authored["asset_version_id"]
    rejected = author_creative_input(DATABASE_URL, request=SimpleNamespace(**{
        **vars(request), "idempotency_key": project+":reject-adapter",
        "design": {**request.design, "core_conflict": "A separate rejected protocol-test direction"}}), **args)
    from novel_forge.modules.story_planning_runtime.application import StoryPlanningGenerationApplication
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    rejected_document = AuthorityAssetQuery(DATABASE_URL).require(
        project_id=project, asset_version_id=rejected["asset_version_id"])
    generation = {**rejected_document.content, "workspace_id": workspace, "content_hash": rejected["content_hash"],
        "planning_scope": PlanningScope.NOT_APPLICABLE}
    planning_rejection = SimpleNamespace(database_url=DATABASE_URL, story_design=authority,
        require_candidate=lambda asset: generation)
    reject_args = dict(principal=author, idempotency_key=project+":reject-decision", reason="Preserve the failed direction for comparison", decision="REQUEST_CHANGES")
    rejected_state = StoryPlanningGenerationApplication.reject_candidate(planning_rejection, rejected["asset_version_id"], **reject_args)
    assert rejected_state["lifecycle"] == "REJECTED"
    assert StoryPlanningGenerationApplication.reject_candidate(planning_rejection, rejected["asset_version_id"], **reject_args) == rejected_state
    with pytest.raises(KernelError, match="IDEMPOTENCY"):
        StoryPlanningGenerationApplication.reject_candidate(planning_rejection, rejected["asset_version_id"], **{**reject_args,"reason":"Changed judgment cannot reuse the old key"})
    judgment = SimpleNamespace(content_hash=authored["content_hash"], reason="The approved reading promise requires witnessed knowledge.",
        findings=[], idempotency_key=project+":confirm-adapter")
    approved = decide_creative_input(DATABASE_URL, asset_version_id=authored["asset_version_id"], request=judgment, **args)
    assert approved["state"]["lifecycle"] == "ACTIVE"
    assert decide_creative_input(DATABASE_URL, asset_version_id=authored["asset_version_id"], request=judgment, **args)["receipt"] == approved["receipt"]
    from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput
    frozen = StoryFormationInput(creative_brief_asset_version_id=brief.asset_version_id, creative_brief_content_hash=brief.content_hash,
        generation_policy={"contract_version":"formation-generation.v3","approval_mode":"REVIEW_PLAN","creative_candidates":1,
            "target_chapters":1,"title":"Protocol test", "author_creative_foundation":{"asset_version_id":authored["asset_version_id"],"content_hash":authored["content_hash"]}})
    assert StoryFormationInput.from_mapping(frozen.to_dict()).digest == frozen.digest
    from novel_forge.modules.book_design_authority.formation import StoryFormationApplication, StartStoryFormationCommand
    from novel_forge.modules.book_design_authority.formation_generation import FormationGeneration
    from unittest.mock import Mock
    planning = SimpleNamespace(database_url=DATABASE_URL, generate=Mock(side_effect=AssertionError("Author direction must not generate creative candidates")))
    formation = StoryFormationApplication(DATABASE_URL, application_build_id="supervised-design-test", commit_sha="a"*40, generation=FormationGeneration(planning))
    author = replace(author, permissions=author.permissions | {"story_planning.authority.execute", "story_planning.authority.activate"})
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT version FROM authority_book WHERE project_id=%s AND book_id=%s", [project,book])
        book_version = uow.cursor.fetchone()[0]
    admission = formation.admit(StartStoryFormationCommand(project_id=project,workspace_id=workspace,book_id=book,
        actor_id=author.principal_id,expected_book_version=book_version,stable_idempotency_key=project+":formation",
        trace_id=project,correlation_id=project,frozen_input=frozen),principal=author)
    formation.advance(admission.formation_run_id,principal=author)
    advanced = formation.advance(admission.formation_run_id,principal=author)
    assert advanced["current_stage"] == "THEME_CONTRACT"
    planning.generate.assert_not_called()
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [project])
        assert uow.cursor.fetchone()[0] == 0


def test_book_design_freezes_author_policy_and_activation_consumes_native_decision():
    from novel_forge.modules.book_design_authority import BookDesignAuthorityCommand
    from novel_forge.modules.book_design_authority.author_supervision import approved_book_design_receipt
    from tests.integration.test_authority_book_design_postgres import BookDesignAuthorityPostgresTests
    case = BookDesignAuthorityPostgresTests()
    case.setUp()
    case.application.allow_scripted_evaluation_fixture = False
    author = replace(case.principal, permissions=case.principal.permissions | {"book.authority.execute"})
    case.principal = author
    case._book_command("book.create", payload={"schema_version": "book-authority.v1", "title": "Supervised protocol",
        "production_profile": {}, "runtime_policy": {"silent_fallback": False}, "release_identity": "test@"+"b"*40},
        idempotency_key=case.book_id+":create")
    book = case.query.require_book(project_id=case.project_id, book_id=case.book_id)
    scope, _ = prepared("creative.candidates.generate")
    policy = deepcopy(scope.policy_snapshot["policy"])
    policy["author_supervised_authorizations"][0].update(book_id=case.book_id, author_id=author.principal_id,
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", content=policy,
        project_id=case.project_id, workspace_id=case.workspace_id, idempotency_key=case.book_id+":policy",
        trace_id=case.book_id, correlation_id=case.book_id, application_build_id="book-design-integration", commit_sha="b"*40, principal=author)
    common = dict(project_id=case.project_id, workspace_id=case.workspace_id, book_id=case.book_id,
        actor_id=author.principal_id, service_identity="test", expected_book_version=book["version"],
        trace_id=case.book_id, correlation_id=case.book_id)
    proposal = BookDesignAuthorityCommand(**common, definition_name="book_design.propose", idempotency_key=case.book_id+":propose", payload=case._evolution_design())
    candidate = case.application.execute(proposal, principal=author)
    assert candidate["status"] == "VALIDATED"
    decision = BookDesignAuthorityCommand(**common, definition_name="book_design.decide", idempotency_key=case.book_id+":decide",
        target_asset_version_id=candidate["asset_version_id"], payload={"decision": "APPROVE", "reason": "Protocol author reviewed exact design"})
    with pytest.raises(PermissionError):
        case.application.execute(replace(decision, actor_id="other"), principal=replace(author, principal_id="other"))
    case.application.execute(decision, principal=author)
    case.application.execute(BookDesignAuthorityCommand(**common, definition_name="book_design.activate", idempotency_key=case.book_id+":activate",
        target_asset_version_id=candidate["asset_version_id"], payload={"reason": "Select exact author-reviewed design"}), principal=author)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        receipt = approved_book_design_receipt(uow.cursor, project_id=case.project_id, book_id=case.book_id, asset_version_id=candidate["asset_version_id"])
        assert receipt["lifecycle"] == "ACTIVE" and receipt["literary_qualification"] == "NOT_PROVEN"
        uow.cursor.execute("SELECT count(*) FROM authority_narrative_design_qualification WHERE project_id=%s", [case.project_id])
        assert uow.cursor.fetchone()[0] == 0
    assert case.application.execute(proposal, principal=author)["replayed"] is True
