from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

from novel_forge.modules.chapter_authority.character_references import frozen_character_references
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .manuscript import writing_frontier

CONTRACT = "book-preprose-plan-replacement.v1"
BINDING = "book_plan_replacement"


def _ref(book_run_id, chapter):
    return f"book-plan-recovery/{book_run_id}/{chapter}"


def require_reference_failure(cursor, *, book, request, actor_id):
    if (book["active_chapter_request_id"] != request["chapter_request_id"]
            or request["book_run_id"] != book["book_run_id"]
            or request["project_id"] != book["project_id"]
            or request["chapter_number"] != writing_frontier(book) + 1
            or book["state"] in {"ABORTED", "CANCELLED", "COMPLETED"}):
        raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Require the exact live next unaccepted Chapter")
    cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [request["chapter_root_operation_id"]])
    row = cursor.fetchone()
    root = row[0] if row else {}
    if (root.get("actor_id") != actor_id or root.get("project_id") != book["project_id"]
            or root.get("workspace_id") != book["workspace_id"]
            or root.get("command_payload", {}).get("book_id") != book["book_id"]
            or root.get("command_payload", {}).get("chapter") != request["chapter_number"]
            or root.get("status") not in {"WAITING_CHILDREN", "FAILED_FINAL", "CANCELLATION_REQUESTED", "CANCELLED"}):
        raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Retain the original owned Chapter root")
    cursor.execute("""SELECT o.operation_id,a.attempt_number,a.result FROM authority_operation o
        JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s
        AND o.definition_name='chapter.execution_intent.prepare'
        AND o.status IN ('FAILED_FINAL','DEAD_LETTER') ORDER BY a.attempt_number""", [root["operation_id"]])
    failures = cursor.fetchall()
    if not failures or any(r[2].get("error_code") != "CHAPTER_MEMO_REFERENCE_CONTRACT_INVALID" for r in failures):
        raise KernelError("BOOK_PLAN_RECOVERY_NOT_APPLICABLE", "Require an actual frozen-reference contract failure")
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
            WHERE o.root_operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset a JOIN authority_operation o USING(operation_id)
            WHERE o.root_operation_id=%s AND o.definition_name<>'chapter.plan.materialize' AND a.role='primary'),
        EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
            JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s
            AND l.released_at IS NULL AND l.expires_at>NOW()),
        EXISTS(SELECT 1 FROM authority_book_chapter_acceptance WHERE chapter_request_id=%s)""",
        [root["operation_id"],root["operation_id"],root["operation_id"],request["chapter_request_id"]])
    if any(cursor.fetchone()):
        raise KernelError("BOOK_PLAN_RECOVERY_NOT_APPLICABLE", "Preserve dispatched, leased, produced or accepted work in its existing recovery path")
    return {"root_operation_id": root["operation_id"], "failures": [{"operation_id": r[0], "attempt_number": r[1], "result": r[2]} for r in failures]}


def retire_reference_failed_chapter(authority, *, book_run_id, proposal_id, plan_change, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    proposal = plan_change.require(proposal_id)
    if (proposal["status"] != "ACTIVE" or proposal["target_contract_type"] != "CHAPTER"
            or proposal["project_id"] != book["project_id"] or proposal["book_id"] != book["book_id"]):
        raise KernelError("BOOK_PLAN_RECOVERY_INVALID", "Require this Book's active Chapter PlanChange")
    stable = "book-plan-recovery:" + sha256(f"{book_run_id}:{proposal_id}".encode()).hexdigest()
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("SELECT operation_id,actor_id FROM authority_operation WHERE project_id=%s AND idempotency_scope='book:authority-mutation' AND idempotency_key=%s", [book["project_id"],stable])
        prior = u.cursor.fetchone()
        if prior:
            if prior[1] != principal.principal_id:
                raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Replay retains its original actor")
            replay = u.repositories.operations.transaction_result(prior[0],book["project_id"])
            if replay["status"] != "SUCCEEDED":
                raise KernelError("BOOK_PLAN_RECOVERY_RECONCILIATION_REQUIRED", "Reconcile the original retirement mutation")
            return {**replay["result"],"replayed":True}
    if not book.get("active_chapter_request_id"):
        raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Require the exact failed predecessor")
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if (request.get("command_payload", {}).get("preparation_report") or {}).get(BINDING):
        raise KernelError("BOOK_PLAN_RECOVERY_EXHAUSTED", "A corrected-contract successor cannot repeatedly replace its own failed input")
    if request["chapter_plan_version"] != proposal["target_asset_version_id"]:
        raise KernelError("BOOK_PLAN_RECOVERY_INVALID", "PlanChange must replace the failed request's exact Plan")
    with AuthorityUnitOfWork(authority.database_url) as u:
        proof = require_reference_failure(u.cursor,book=book,request=request,actor_id=principal.principal_id)
        candidate = u.repositories.asset_documents.require(project_id=book["project_id"],asset_version_id=proposal["proposed_asset_version_id"])
        refs = frozen_character_references(SimpleNamespace(database_url=authority.database_url,project_id=book["project_id"],workspace_id=book["workspace_id"],command={"book_id":book["book_id"],"context_version_refs":{"book_production_input_snapshot_id":book["input_snapshot_id"]}}),scenes=candidate.content["scene_plan"])
        if refs is None or candidate.content.get("chapter_number") != request["chapter_number"]:
            raise KernelError("BOOK_PLAN_RECOVERY_INVALID", "Corrected Plan needs the same chapter and trusted frozen cast")
    cancel_key = stable + ":cancel"
    authority.chapter_port.cancel(project_id=book["project_id"],root_operation_id=request["chapter_root_operation_id"],actor_id=principal.principal_id,
        reason="Unproduced reference-invalid Chapter replaced by its active PlanChange",idempotency_key=cancel_key,trace_id=stable,correlation_id=book["root_operation_id"])
    stopped = authority.chapter_port.require_run(project_id=book["project_id"],root_operation_id=request["chapter_root_operation_id"])
    if stopped["status"] != "CANCELLED":
        return {"status":"CANCELLATION_PENDING","book_run_id":book_run_id,"chapter_request_id":request["chapter_request_id"],"proposal_id":proposal_id}
    authority.reconcile_chapter(request["chapter_request_id"])
    book = authority.require(book_run_id)
    def commit(uow, operation_id, checkpoint):
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        current = uow.cursor.fetchone()[0]
        if current["version"] != book["version"]:
            raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Reload the unchanged recovery checkpoint")
        live_proposal = uow.repositories.plan_change.require(proposal_id)
        if any(live_proposal.get(k) != proposal.get(k) for k in ("status","project_id","book_id","target_asset_version_id","proposed_asset_version_id","activation_operation_id")):
            raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Retain the exact active PlanChange")
        uow.cursor.execute("""SELECT v.content_hash FROM active_story_plan_version a JOIN story_plan_binding b ON b.binding_id=a.binding_id
            JOIN authority_asset_version v ON v.asset_version_id=b.asset_version_id WHERE a.project_id=%s AND a.book_id=%s
            AND b.contract_type='CHAPTER' AND b.freshness='CURRENT' AND b.asset_version_id=%s""", [book["project_id"],book["book_id"],candidate.asset_version_id])
        if uow.cursor.fetchone() != (candidate.content_hash,):
            raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Corrected Plan is no longer the current typed binding")
        current_proof = require_reference_failure(uow.cursor,book=current,request=request,actor_id=principal.principal_id)
        if current_proof != proof:
            raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Original failure history must remain exact")
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [request["chapter_root_operation_id"]])
        if uow.cursor.fetchone()[0] != "CANCELLED":
            raise KernelError("BOOK_PLAN_RECOVERY_CANCELLATION_PENDING", "Finish native predecessor cancellation before replacement")
        uow.cursor.execute("SELECT count(*),count(*) FILTER (WHERE idempotency_key=%s AND actor_id=%s) FROM authority_cancellation_command WHERE operation_id=%s", [cancel_key,principal.principal_id,request["chapter_root_operation_id"]])
        if uow.cursor.fetchone() != (1,1):
            raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "User cancellation cannot authorize a plan successor")
        content = {"contract_version":CONTRACT,"book_run_id":book_run_id,"project_id":book["project_id"],"workspace_id":book["workspace_id"],"book_id":book["book_id"],
            "chapter":request["chapter_number"],"proposal_id":proposal_id,"predecessor_request_id":request["chapter_request_id"],
            "predecessor_root_operation_id":request["chapter_root_operation_id"],"generation":request["generation"]+1,
            "corrected_plan_asset_version_id":candidate.asset_version_id,"corrected_plan_content_hash":candidate.content_hash,"reference_contract":refs,"original_failure_proof":proof}
        output = uow.repositories.asset_documents.materialize_output(AuthorityAssetWriteCommand(operation_id=operation_id,project_id=book["project_id"],asset_id="book-plan-recovery:"+operation_id,
            asset_type="book_chapter_plan_recovery",schema_version=CONTRACT,logical_ref=_ref(book_run_id,request["chapter_number"]),category="chapter-recovery",output_key="book.chapter_plan.recovery",role="completion_evidence",
            content=content,qualification_policy=CONTRACT,trace_id=stable,correlation_id=book["root_operation_id"]))
        uow.cursor.execute("UPDATE authority_child_delegation SET superseded_at=NOW(),version=version+1,updated_at=NOW() WHERE chapter_request_id=%s AND superseded_at IS NULL", [request["chapter_request_id"]])
        uow.cursor.execute("UPDATE authority_book_production SET active_chapter_request_id=NULL,active_child_delegation_id=NULL,state='READY',paused_reason='',failure_reason='',version=version+1,updated_at=NOW() WHERE book_run_id=%s", [book_run_id])
        checkpoint("after_plan_recovery_retirement")
        return {"book_run_id":book_run_id,"chapter":request["chapter_number"],"recovery_asset_version_id":output.asset_version_id}
    return authority._execute_mutation(book=book,action="chapter_plan_recover",event_type="book.chapter_plan.recovery_prepared",idempotency_key=stable,
        actor_id=principal.principal_id,trace_id=stable,correlation_id=book["root_operation_id"],causation_id=proposal["activation_operation_id"],payload={"proposal_id":proposal_id},handler=commit,
        input_assets=authority.resolve_asset_refs(project_id=book["project_id"],asset_version_ids=(candidate.asset_version_id,)))


def replacement_binding(uow, *, book, chapter, plan_version, plan_hash):
    uow.cursor.execute("""SELECT v.asset_version_id,v.content FROM authority_asset_locator l JOIN authority_asset_version v ON v.asset_version_id=l.current_asset_version_id
        JOIN authority_asset a USING(asset_id) WHERE l.project_id=%s AND l.logical_ref=%s AND a.asset_type='book_chapter_plan_recovery'""", [book["project_id"],_ref(book["book_run_id"],chapter)])
    row = uow.cursor.fetchone()
    if not row:
        return None
    content = row[1]
    if content["corrected_plan_asset_version_id"] != plan_version or content["corrected_plan_content_hash"] != plan_hash:
        raise KernelError("BOOK_PLAN_RECOVERY_CONFLICT", "Dispatch the exact corrected Plan from the recovery journal")
    return {**{k:content[k] for k in ("contract_version","book_run_id","proposal_id","predecessor_request_id","predecessor_root_operation_id","generation")},"recovery_asset_version_id":row[0]}
