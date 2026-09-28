from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.author_supervision import validate_grants
from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def supervision_workspace(database_url: str, *, project_id: str, book_id: str, principal: Any) -> dict[str, Any]:
    principal.require("book.authority.query", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        if uow.cursor.fetchone() is None:
            raise KernelError("BOOK_NOT_FOUND", "Book is outside project scope")
        uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='routing_decision'
              AND v.content #>> '{task,work_id}'=%s AND NOT v.content ? 'bootstrap_authorization'
            ORDER BY v.created_at DESC LIMIT 100""", [project_id, book_id])
        producers = []
        seen = set()
        for version, decision in uow.cursor.fetchall():
            task = decision["task"]
            identity = (task["task_type"], task.get("producer_contract_hash", ""))
            if identity in seen or not identity[1]:
                continue
            seen.add(identity)
            producers.append({"routing_asset_version_id": version, "task_type": identity[0], "producer_contract_hash": identity[1],
                "status": decision["status"], "candidates": decision["candidates"], "budget": task.get("budget_snapshot", {})})
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content,s.qualification,s.approval,s.planning_scope
            FROM authority_story_design_version_state s JOIN authority_asset_version v USING(asset_version_id)
            JOIN authority_story_planning_candidate c ON c.candidate_asset_version_id=v.asset_version_id
            WHERE s.project_id=%s AND v.content->>'book_id'=%s AND s.lifecycle NOT IN ('ACTIVE','REJECTED','SUPERSEDED','ARCHIVED')
              AND s.execution_evidence #>> '{author_supervision,mode}'='AUTHOR_SUPERVISED'
            ORDER BY v.created_at""", [project_id, book_id])
        pending = [dict(zip(("asset_version_id", "content_hash", "content", "qualification", "approval", "planning_scope"), row)) for row in uow.cursor.fetchall()]
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_asset_version v
            JOIN authority_asset a USING(asset_id)
            JOIN authority_asset_version candidate ON candidate.asset_version_id=v.content->>'candidate_asset_version_id'
            JOIN authority_asset source ON source.asset_id=candidate.asset_id AND source.project_id=a.project_id
            WHERE a.project_id=%s AND a.asset_type='narrative_design_evaluation'
              AND candidate.content->>'book_id'=%s AND v.content->>'evaluation_purpose'='AUTHOR_ADVISORY'
            ORDER BY v.created_at""", [project_id, book_id])
        reviews = [dict(zip(("asset_version_id", "content_hash", "content"), row)) for row in uow.cursor.fetchall()]
    policy = PostgresRoutingRegistry(database_url).policy(project_id)
    return {"policy_hash": policy.get("policy_hash", ""), "policy_version": policy.get("policy", {}).get("policy_version", ""),
        "book_modes": [b for b in policy.get("policy", {}).get("author_supervised_books", []) if b["book_id"] == book_id],
        "authorizations": [g for g in policy.get("policy", {}).get("author_supervised_authorizations", []) if g["book_id"] == book_id],
        "producers": producers, "pending_designs": pending, "model_reviews": reviews, "literary_qualification": "NOT_PROVEN"}


def approve_route(database_url: str, *, project_id: str, book_id: str, request: Any, principal: Any,
                  application_build_id: str, commit_sha: str) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("Only the authenticated author may approve supervised production")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_NOT_FOUND", "Book is outside project scope")
        workspace_id = row[0]
        uow.cursor.execute("""SELECT command_payload FROM authority_operation
            WHERE project_id=%s AND idempotency_scope='project:provider_routing:policy' AND idempotency_key=%s""",
            [project_id, request.idempotency_key])
        replay = uow.cursor.fetchone()
    document = AuthorityAssetQuery(database_url).require(project_id=project_id, asset_version_id=request.routing_asset_version_id)
    decision = document.content
    if (document.asset_type != "routing_decision" or decision.get("task", {}).get("work_id") != book_id
            or decision.get("bootstrap_authorization")):
        raise KernelError("AUTHOR_SUPERVISION_SCOPE_REQUIRED", "Select an actual same-Book production request; diagnostic samples cannot be promoted")
    rows = [r for r in decision["candidates"] if r["candidate"]["candidate_id"] == request.candidate_id]
    if len(rows) != 1:
        raise KernelError("AUTHOR_SUPERVISION_MODEL_MISMATCH", "Select a model from the exact request")
    candidate, task = rows[0]["candidate"], decision["task"]
    grant = {"authorization_id": "author-supervised:" + request.idempotency_key, "book_id": book_id,
        "task_type": task["task_type"], "producer_contract_hash": task["producer_contract_hash"],
        "candidate_id": candidate["candidate_id"], "model_revision": candidate["model_revision"], "author_id": principal.principal_id,
        "expires_at": request.expires_at, "maximum_tokens": request.maximum_tokens, "maximum_amount": request.maximum_amount,
        "reason": request.reason}
    validate_grants({"author_supervised_authorizations": [grant]}, author_id=principal.principal_id)
    policy_snapshot = PostgresRoutingRegistry(database_url).policy(project_id)
    if replay:
        policy = dict(replay[0]["policy"])
        if grant not in policy.get("author_supervised_authorizations", []) or replay[0].get("expected_policy_hash") != request.expected_policy_hash:
            raise KernelError("IDEMPOTENCY_CONFLICT", "Recover the original author request before changing its scope")
    else:
        if datetime.fromisoformat(grant["expires_at"]) <= datetime.now(timezone.utc):
            raise KernelError("AUTHOR_SUPERVISION_EXPIRED", "New author approval must be within its effective window")
        policy = deepcopy(policy_snapshot.get("policy") or {"task_overrides": []})
        policy.update(policy_version="author-supervised:" + request.idempotency_key, reason=request.reason)
        policy["author_supervised_authorizations"] = [g for g in policy.get("author_supervised_authorizations", [])
            if (g["book_id"],g["task_type"],g["producer_contract_hash"]) != (book_id,task["task_type"],task["producer_contract_hash"])] + [grant]
    return configure_owned_policy(database_url=database_url, owner="PROVIDER_ROUTING", content=policy,
        project_id=project_id, workspace_id=workspace_id, idempotency_key=request.idempotency_key,
        trace_id="author-supervision:"+request.idempotency_key, correlation_id=request.idempotency_key,
        application_build_id=application_build_id, commit_sha=commit_sha, principal=principal, expected_policy_hash=request.expected_policy_hash)


def select_book_mode(database_url: str, *, project_id: str, book_id: str, request: Any, principal: Any,
                     application_build_id: str, commit_sha: str) -> dict[str, Any]:
    principal.require("book.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("Book supervision requires its authenticated author")
    if request.mode not in {"STRICT", "AUTHOR_SUPERVISED"} or not request.reason.strip():
        raise KernelError("AUTHOR_SUPERVISION_GRANT_INVALID", "Choose a declared mode and record its reason")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_NOT_FOUND", "Book is outside project scope")
        workspace = row[0]
        uow.cursor.execute("""SELECT command_payload FROM authority_operation
            WHERE project_id=%s AND idempotency_scope='project:provider_routing:policy' AND idempotency_key=%s""", [project_id, request.idempotency_key])
        replay = uow.cursor.fetchone()
    entry = {"book_id": book_id, "author_id": principal.principal_id, "reason": request.reason}
    current = PostgresRoutingRegistry(database_url).policy(project_id)
    if replay:
        policy = replay[0]["policy"]
        selected = [b for b in policy.get("author_supervised_books", []) if b["book_id"] == book_id]
        if (selected != ([entry] if request.mode == "AUTHOR_SUPERVISED" else [])
                or policy["reason"] != request.reason or replay[0].get("expected_policy_hash") != request.expected_policy_hash):
            raise KernelError("IDEMPOTENCY_CONFLICT", "Recover the original mode decision before changing it")
    else:
        policy = deepcopy(current.get("policy") or {"task_overrides": []})
        policy.update(policy_version="author-mode:"+request.idempotency_key, reason=request.reason)
        policy["author_supervised_books"] = [b for b in policy.get("author_supervised_books", []) if b["book_id"] != book_id]
        if request.mode == "AUTHOR_SUPERVISED":
            policy["author_supervised_books"].append(entry)
        else:
            policy["author_supervised_authorizations"] = [g for g in policy.get("author_supervised_authorizations", []) if g["book_id"] != book_id]
    return configure_owned_policy(database_url=database_url, owner="PROVIDER_ROUTING", content=policy,
        project_id=project_id, workspace_id=workspace, idempotency_key=request.idempotency_key,
        trace_id="author-mode:"+request.idempotency_key, correlation_id=request.idempotency_key,
        application_build_id=application_build_id, commit_sha=commit_sha, principal=principal,
        expected_policy_hash=request.expected_policy_hash)


def author_creative_input(database_url: str, *, project_id: str, book_id: str, request: Any, principal: Any,
                          application_build_id: str, commit_sha: str) -> dict[str, Any]:
    from novel_forge.modules.content_authority import CONTENT_CODECS, ContentAuthorityApplication, ContentOperationRequest
    from novel_forge.modules.story_design_authority import DesignTransition, PlanningScope, PostgresStoryDesignAssetAuthority, StoryDesignTransitionCommand
    from novel_forge.modules.production_execution.author_supervision import selected_book_supervision
    principal.require("story_design.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("Original author input requires the authenticated author")
    query = AuthorityAssetQuery(database_url)
    brief = query.require(project_id=project_id, asset_version_id=request.brief_asset_version_id)
    if brief.asset_type != "creative_brief" or brief.content_hash != request.brief_content_hash:
        raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Select the exact original creative input")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_NOT_FOUND", "Book is outside project scope")
        workspace = row[0]
        uow.cursor.execute("""SELECT 1 FROM authority_operation_output_asset output
            JOIN authority_operation op ON op.operation_id=output.operation_id
            WHERE output.asset_version_id=%s AND output.content_hash=%s AND op.project_id=%s
              AND op.workspace_id=%s AND op.definition_name='creative.brief.create' AND op.status='SUCCEEDED'
              AND NOT op.command_payload ? 'routing_bootstrap_authorization'""",
            [brief.asset_version_id, brief.content_hash, project_id, workspace])
        if uow.cursor.fetchone() is None or brief.content.get("routing_eligibility") == "BENCHMARK_ONLY":
            raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Original brief must belong to this Book workspace and native author input")
        supervision = selected_book_supervision(uow.cursor, project_id=project_id, book_id=book_id)
        if supervision is None or supervision["author_id"] != principal.principal_id:
            raise PermissionError("Select author supervision for this Book before forming its original design")
    logical_key = "foundation:creative_foundation:author:" + book_id
    content = {"schema_version": "story_design.authority.v1", "project_id": project_id, "book_id": book_id,
        "generator_operation_name": "creative.candidates.generate", "planning_scope": "NOT_APPLICABLE", "logical_key": logical_key,
        "operator_authored": True, "provider_generated": False, "candidate_payload": dict(request.design),
        "author_input_source": {"brief_asset_version_id": brief.asset_version_id, "brief_content_hash": brief.content_hash,
            "contribution": request.contribution, "source_boundary": "ORIGINAL_AUTHOR_INPUT; diagnostic samples are not imported"}}
    if request.contribution not in {"OPERATOR_AUTHORED_INPUT", "AI_ASSISTED_AUTHOR_INPUT"}:
        raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Record the actual author contribution")
    application = ContentAuthorityApplication(database_url, application_build_id=application_build_id, commit_sha=commit_sha,
        integration_proven=CONTENT_CODECS, trusted_only=True)
    result = application.execute(ContentOperationRequest(definition_name="story_design.creative_foundation.author",
        project_id=project_id, workspace_id=workspace, actor_id=principal.principal_id, trace_id=request.idempotency_key,
        correlation_id=request.idempotency_key, idempotency_key=request.idempotency_key, payload={"content": content},
        input_assets=({"asset_version_id": brief.asset_version_id, "content_hash": brief.content_hash},)), principal=principal)
    authority = PostgresStoryDesignAssetAuthority(database_url, application_build_id=application_build_id, commit_sha=commit_sha)
    try:
        state = authority.require(project_id=project_id, asset_version_id=result.asset_version_id)
    except KernelError as exc:
        if exc.code != "STORY_DESIGN_CANDIDATE_NOT_FOUND":
            raise
        state = {"version": 0, "lifecycle": "UNENROLLED", "qualification": "PENDING"}
    for transition, apply in ((DesignTransition.ENROLL, state["lifecycle"] == "UNENROLLED"),
                             (DesignTransition.MATERIALIZE, state["lifecycle"] in {"UNENROLLED", "CANDIDATE"}),
                             (DesignTransition.STRUCTURAL_VALIDATE, state["qualification"] == "PENDING")):
        if apply:
            state = authority.transition(StoryDesignTransitionCommand(project_id=project_id, workspace_id=workspace,
                actor_id=principal.principal_id, trace_id=request.idempotency_key, correlation_id=request.idempotency_key,
                idempotency_key=request.idempotency_key+":"+transition.value, asset_version_id=result.asset_version_id,
                content_hash=result.content_hash, logical_key=logical_key, generator_operation_name="creative.candidates.generate",
                transition=transition, planning_scope=PlanningScope.NOT_APPLICABLE, expected_version=state["version"], source_kind="OPERATOR_AUTHORED",
                evidence={"passed": True, "operation_id": result.operation_id, "authoring_operation_id": result.operation_id,
                    "operator_authored": True, "provider_generated": False}), principal=principal)
    return {"asset_version_id": result.asset_version_id, "content_hash": result.content_hash, "content": content, "state": state}


def decide_creative_input(database_url: str, *, project_id: str, book_id: str, asset_version_id: str, request: Any,
                          principal: Any, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    from novel_forge.modules.story_design_authority import DesignTransition, PlanningScope, PostgresStoryDesignAssetAuthority, StoryDesignTransitionCommand
    from novel_forge.modules.story_design_authority.author_supervision import approved_design_receipt
    principal.require("story_design.authority.execute", project_id)
    if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
        raise PermissionError("Only the authenticated author can approve original input")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [project_id, book_id])
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_NOT_FOUND", "Book is outside project scope")
        workspace = row[0]
    candidate = AuthorityAssetQuery(database_url).require(project_id=project_id, asset_version_id=asset_version_id)
    if candidate.content.get("book_id") != book_id or candidate.content_hash != request.content_hash or candidate.content.get("provider_generated") is not False:
        raise KernelError("FORMATION_AUTHOR_INPUT_REQUIRED", "Only exact same-Book original author input can be approved")
    authority = PostgresStoryDesignAssetAuthority(database_url, application_build_id=application_build_id, commit_sha=commit_sha)
    state = authority.require(project_id=project_id, asset_version_id=asset_version_id)
    review = {"asset_version_id": asset_version_id, "content_hash": request.content_hash, "decision": "ACCEPT", "reason": request.reason, "findings": request.findings}
    for step, apply in ((DesignTransition.SEMANTIC_VALIDATE,state["qualification"] == "STRUCTURALLY_VALID"),
                        (DesignTransition.SUBMIT_APPROVAL,state["approval"] == "NOT_REQUESTED"),
                        (DesignTransition.APPROVE,state["approval"] != "APPROVED"),
                        (DesignTransition.ACTIVATE,state["lifecycle"] != "ACTIVE")):
        if apply:
            state = authority.transition(StoryDesignTransitionCommand(project_id=project_id, workspace_id=workspace,
                actor_id=principal.principal_id, trace_id=request.idempotency_key, correlation_id=request.idempotency_key,
                idempotency_key=request.idempotency_key+":"+step.value, asset_version_id=asset_version_id,
                content_hash=request.content_hash, logical_key=candidate.content["logical_key"], generator_operation_name="creative.candidates.generate",
                transition=step, planning_scope=PlanningScope.NOT_APPLICABLE, expected_version=state["version"], source_kind="OPERATOR_AUTHORED",
                evidence={"author_review":review}), principal=principal)
    with AuthorityUnitOfWork(database_url) as uow:
        receipt = approved_design_receipt(uow.cursor, project_id=project_id, book_id=book_id, asset_version_id=asset_version_id)
        if receipt is None or receipt["author_review"] != review or receipt["author_id"] != principal.principal_id:
            raise KernelError("AUTHOR_SUPERVISION_EXACT_REVIEW_REQUIRED", "Replay differs from the original author judgment")
    return {"asset_version_id": asset_version_id, "content_hash": candidate.content_hash, "state":state, "receipt":receipt}
