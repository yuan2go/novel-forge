from __future__ import annotations

from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.chapter_authority.author_editor import require_source, source_draft_content, text_hash
from novel_forge.modules.chapter_authority.contracts import ChapterAuxiliaryOutput, ChapterHandlerOutput, ChapterNode
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def freeze_author_adoption(database_url: str, *, project_id: str, workspace_id: str, book_id: str,
                           chapter: int, candidate_asset_version_id: str, decision_asset_version_id: str,
                           principal: Principal) -> dict[str, Any]:
    principal.require("chapter.authority.execute", project_id)
    scope = {"project_id": project_id, "workspace_id": workspace_id, "book_id": book_id, "chapter": chapter}
    with AuthorityUnitOfWork(database_url) as uow:
        candidate, decision = _require_adoption(uow, scope, candidate_asset_version_id, decision_asset_version_id)
        source = require_source(uow, scope, candidate.content["base_asset_version_id"])
    realization = source_draft_content(source).get("realization_contract") or {}
    plan_id = source.asset_version_id if source.asset_type == "chapter_plan" else realization.get("plan_version_id", "")
    return {**scope, "contract_version": "author-draft-adoption.v1",
            "candidate_asset_version_id": candidate.asset_version_id, "candidate_content_hash": candidate.content_hash,
            "decision_asset_version_id": decision.asset_version_id, "decision_content_hash": decision.content_hash,
            "text_hash": candidate.content["text_hash"], "base_asset_version_id": candidate.content["base_asset_version_id"],
            "originating_draft_asset_version_id": candidate.content.get("originating_draft_asset_version_id", candidate.content["base_asset_version_id"]),
            "author_id": candidate.content["author_id"], "decision_actor_id": decision.content["actor_id"],
            "rights_basis": candidate.content["rights_basis"], "source_chapter_plan_asset_version_id": plan_id}


def _require_adoption(uow, scope, candidate_id, decision_id):
    candidate = uow.repositories.asset_documents.require(project_id=scope["project_id"], asset_version_id=candidate_id)
    decision = uow.repositories.asset_documents.require(project_id=scope["project_id"], asset_version_id=decision_id)
    if (candidate.asset_type != "author_edit_candidate" or decision.asset_type != "author_edit_decision"
        or any(document.content.get(key) != value for document in (candidate, decision) for key, value in scope.items())
        or decision.content.get("candidate_asset_version_id") != candidate.asset_version_id
        or decision.content.get("candidate_content_hash") != candidate.content_hash
        or decision.content.get("decision") != "ACCEPT"
        or candidate.content.get("text_hash") != text_hash(candidate.content["text"])
        or decision.content.get("text_hash") != candidate.content.get("text_hash")):
        raise KernelError("AUTHOR_ADOPTION_INVALID", "An exact scoped author candidate and ACCEPT decision are required")
    require_source(uow, scope, candidate.content["base_asset_version_id"])
    uow.cursor.execute(
        """SELECT 1 FROM authority_book_chapter_acceptance accepted
           JOIN authority_book_production book USING(book_run_id)
           WHERE book.project_id=%s AND book.book_id=%s AND accepted.chapter_number=%s
             AND accepted.status='COMMITTED' LIMIT 1""",
        [scope["project_id"], scope["book_id"], scope["chapter"]])
    if uow.cursor.fetchone() is not None:
        raise KernelError("AUTHOR_HISTORICAL_EDIT_PENDING", "Historical accepted prose is read-only; candidate waits for a separately authorized edition workflow")
    return candidate, decision


def adopted_author_draft(request) -> ChapterHandlerOutput | None:
    adoption = (request.command.get("preparation_report") or {}).get("author_draft_adoption")
    if not adoption:
        return None
    if adoption.get("contract_version") == "book-edition-draft-adoption.v1":
        from novel_forge.modules.book_authority.edition_runtime import edition_adopted_draft
        return edition_adopted_draft(request, adoption)
    scope = {"project_id": request.project_id, "workspace_id": request.workspace_id,
             "book_id": request.command.get("book_id"), "chapter": int(request.command["chapter"])}
    if any(adoption.get(key) != value for key, value in scope.items()) or adoption.get("contract_version") != "author-draft-adoption.v1":
        raise KernelError("AUTHOR_ADOPTION_SCOPE_CONFLICT", "Frozen adoption differs from Chapter execution scope")
    with AuthorityUnitOfWork(request.database_url) as uow:
        candidate, decision = _require_adoption(uow, scope, adoption["candidate_asset_version_id"], adoption["decision_asset_version_id"])
    if (candidate.content_hash != adoption.get("candidate_content_hash") or decision.content_hash != adoption.get("decision_content_hash")
        or candidate.content["text_hash"] != adoption.get("text_hash")):
        raise KernelError("AUTHOR_ADOPTION_HASH_CONFLICT", "Frozen author adoption differs from immutable evidence")
    from .domain_handlers import normalize_draft_result
    from .craft_execution import require_craft_delivery

    plan, context = request.require_input("chapter_plan"), request.require_input("context_bundle")
    if adoption.get("source_chapter_plan_asset_version_id") and adoption["source_chapter_plan_asset_version_id"] != plan.content.get("source_chapter_plan_asset_version_id"):
        raise KernelError("AUTHOR_PLAN_DRIFT", "Author candidate must retain its exact originating Chapter Plan")
    intent, memo = request.require_input("chapter_execution_intent"), request.require_input("chapter_memo")
    require_craft_delivery(plan=plan.content, intent=intent.content, memo=memo.content, context=context.content)
    content = normalize_draft_result(
        plan=plan.content,
        context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash,
        context_content=context.content,
        result=candidate.content["draft_content"],
        provider_evidence={
            "source": "HUMAN_AUTHOR_INPUT",
            "model_call": "NOT_APPLICABLE",
        },
        work_requirements=request.work_requirements_enabled,
    )
    if content["text"] != candidate.content["text"]:
        raise KernelError("AUTHOR_TEXT_NORMALIZATION_CONFLICT", "Author text cannot change after exact version selection")
    content["author_draft_adoption"] = dict(adoption)
    content["creative_execution"] = {"memo_asset_version_id": memo.asset_version_id, "memo_content_hash": memo.content_hash,
                                    "memo_fingerprint": memo.content.get("memo_fingerprint"), "intent_asset_version_id": intent.asset_version_id,
                                    "guidance": dict(memo.content.get("creative_guidance") or {}),
                                    "scene_directives": list(memo.content.get("scene_directives") or []), "authority": "CREATIVE_SUGGESTION_ONLY"}
    return ChapterHandlerOutput(asset_type=ChapterNode.DRAFT.asset_type, output_key=ChapterNode.DRAFT.output_key,
                                role="primary", content=content, auxiliary_outputs=(ChapterAuxiliaryOutput(
                                    asset_type="author_draft_adoption_evidence", output_key="chapter.draft.author_adoption", role="completion_evidence",
                                    content={**adoption, "authority": "AUTHOR_CANDIDATE_ONLY", "semantic_review": "REQUIRED"},
                                    reference_asset_version_ids=(candidate.asset_version_id, decision.asset_version_id)),))
