from __future__ import annotations

from types import SimpleNamespace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor_v2 import replace_failed_step, has_domain_outputs
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .character_references import CONTRACT, frozen_character_references
from .creative_memo import qualify_creative_memo
from .receipt_recovery import _receipt, _cancelled

VERSION = "3.10.1"


def recover_memo_references(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not book.get("active_chapter_request_id") or book["state"] not in {"PAUSED", "CHAPTER_RUNNING", "CHAPTER_WAITING_RETRY", "CHAPTER_SUBMITTED"}:
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.definition_name='chapter.memo.generate'
            AND o.status IN ('FAILED_FINAL','DEAD_LETTER') AND o.definition_version='3.10.0'""",
            [request["chapter_root_operation_id"], book["project_id"]])
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1 or _cancelled(u.cursor, book):
            raise KernelError("MEMO_RECOVERY_SCOPE_INVALID", "Require one live owned Memo frontier")
        source = rows[0][0]
        if source["actor_id"] != principal.principal_id or has_domain_outputs(u.cursor, source["operation_id"]):
            raise KernelError("MEMO_RECOVERY_SCOPE_INVALID", "Require exact actor and unmaterialized source")
        u.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source["operation_id"]])
        failures = [row[0] for row in u.cursor.fetchall()]
        if not failures or any(code != "CHAPTER_MEMO_CHARACTER_DRIFT" for code in failures):
            raise KernelError("MEMO_RECOVERY_FAILURE_UNSUPPORTED", "Only the diagnosed immutable identity-contract failure may use this repair")
        assets = [u.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
        intents = [a for a in assets if a.asset_type == "chapter_execution_intent"]
        if len(intents) != 1:
            raise KernelError("MEMO_RECOVERY_INPUT_DRIFT", "Require one exact frozen intent")
        intent = intents[0]
        scope = SimpleNamespace(database_url=authority.database_url, command=source["command_payload"], project_id=book["project_id"], workspace_id=book["workspace_id"])
        refs = frozen_character_references(scope, scenes=intent.content["scene_plans"])
        if refs is None:
            raise KernelError("MEMO_RECOVERY_REFERENCE_MISSING", "A trusted original cast binding is required")
        u.cursor.execute("SELECT to_jsonb(e),b.status FROM authority_external_effect e LEFT JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s ORDER BY e.created_at", [source["operation_id"]])
        effects = u.cursor.fetchall()
        retained = []
        for effect, status in effects:
            if effect["status"] != "SUCCEEDED" or status != "SETTLED":
                raise KernelError("MEMO_RECOVERY_RECONCILIATION_REQUIRED", "Every original effect must have settled verified evidence")
            result = _receipt(u.cursor, effect["external_effect_id"], book["project_id"], source_operation_id=source["operation_id"])
            qualify_creative_memo(intent=intent.content, intent_asset_version_id=intent.asset_version_id,
                result=result.output, execution_evidence=result.execution_evidence or {}, character_references=refs)
            u.cursor.execute("SELECT d.dispatch_id FROM authority_external_effect_dispatch d JOIN authority_external_receipt r USING(dispatch_id) WHERE d.external_effect_id=%s AND d.status='SUCCEEDED' AND r.status='VERIFIED' ORDER BY d.generation DESC LIMIT 1", [effect["external_effect_id"]])
            retained.append({"source_effect_id": effect["external_effect_id"], "source_request_hash": effect["request_hash"],
                "source_output_hash": snapshot_hash(result.output), "source_dispatch_id": u.cursor.fetchone()[0]})
        if not retained:
            raise KernelError("MEMO_RECOVERY_RECEIPT_MISSING", "Require actual original model result")
        evidence = {"contract_version": "chapter-known-receipt.v2", "source_operation_id": source["operation_id"],
                    **retained[-1], "provider_invoked": False, "strict_certification_eligible": False,
                    "completion_checks": "UNCHANGED", "character_reference_contract": refs,
                    "reference_contract_hash": snapshot_hash(refs), "settled_memo_receipts": retained}
        u.cursor.execute("SELECT evidence->>'cost_authorization_ref' FROM authority_budget_reservation WHERE external_effect_id=%s AND status='SETTLED'", [retained[-1]["source_effect_id"]])
        evidence["cost_authorization_ref"] = u.cursor.fetchone()[0]

    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"]) or _cancelled(u.cursor, book):
            raise KernelError("MEMO_RECOVERY_FRONTIER_CHANGED", "Reload the exact live Book frontier")
    from .definitions import chapter_operation_definitions
    target = next(d for d in chapter_operation_definitions(application_build_id=authority.application_build_id,
        commit_sha=authority.commit_sha, model_effects_required=True, coordinated_contract=True) if d["name"] == "chapter.memo.generate" and d["definition_version"] == VERSION)
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.repositories.definitions.register(target)
        u.commit()
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version=VERSION,
        context=AdmissionContext(principal.principal_id, principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence=evidence, expected_failure_code="CHAPTER_MEMO_CHARACTER_DRIFT",
        known_receipt_effects=tuple((r["source_effect_id"], r["source_request_hash"]) for r in retained),
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "memo_reference_contract", "policy_value": CONTRACT},
        transaction_guard=guard)
    return True


def consume_memo_receipt(request):
    if request.definition_version not in {VERSION, "3.10.2"}:
        return None
    from .receipt_recovery import _consume_known_draft_receipt
    retained = _consume_known_draft_receipt(request)
    if retained is None:
        raise KernelError("MEMO_RECOVERY_JOURNAL_REQUIRED", "A repair successor cannot dispatch a fresh model call")
    result, policy = retained
    intent = request.require_input("chapter_execution_intent")
    refs = frozen_character_references(request, scenes=intent.content["scene_plans"])
    if refs != policy.get("character_reference_contract") or snapshot_hash(refs) != policy.get("reference_contract_hash"):
        raise KernelError("MEMO_RECOVERY_INPUT_DRIFT", "Retain the exact frozen original cast")
    return result, refs


def original_memo_source(cursor, predecessor, policy):
    if predecessor.get("definition_name") != "chapter.memo.generate" or predecessor.get("definition_version") != VERSION:
        raise KernelError("MEMO_COMPLETION_LINEAGE_INVALID", "Require the exact failed first repair")
    cursor.execute("SELECT source_failure_snapshot,policy_evidence FROM authority_saga_step_successor WHERE successor_operation_id=%s", [predecessor["operation_id"]])
    row = cursor.fetchone()
    if not row or row[0]["operation"]["operation_id"] != policy.get("source_operation_id") or any(row[1].get(k) != policy.get(k) for k in ("source_effect_id", "source_output_hash", "source_request_hash", "source_dispatch_id", "character_reference_contract", "settled_memo_receipts")):
        raise KernelError("MEMO_COMPLETION_LINEAGE_INVALID", "Retain all original receipt and reference bindings")
    return row[0]["operation"]


def recover_memo_completion(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    with AuthorityUnitOfWork(authority.database_url) as u:
        u.cursor.execute("SELECT to_jsonb(o),j.policy_evidence FROM authority_operation o JOIN authority_saga_step s USING(operation_id) JOIN authority_saga_step_successor j ON j.successor_operation_id=o.operation_id WHERE o.root_operation_id=%s AND o.definition_name='chapter.memo.generate' AND o.definition_version='3.10.1' AND o.status='FAILED_FINAL'", [request["chapter_root_operation_id"]])
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1 or _cancelled(u.cursor, book):
            raise KernelError("MEMO_COMPLETION_LINEAGE_INVALID", "Require one uncancelled exact failed repair")
        source, policy = rows[0]
        original_memo_source(u.cursor, source, policy)
        u.cursor.execute("SELECT b.evidence->>'cost_authorization_ref' FROM authority_budget_reservation b WHERE external_effect_id=%s AND status='SETTLED'", [policy["source_effect_id"]])
        authorization = u.cursor.fetchone()
        if not authorization or not authorization[0]:
            raise KernelError("MEMO_RECOVERY_RECONCILIATION_REQUIRED", "Original accounting must retain its authorization")
        policy = {**policy, "cost_authorization_ref": authorization[0], "completion_revalidation": "settled-memo-completion.v1"}
        u.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source["operation_id"]])
        error = u.cursor.fetchone()[0]
        from .definitions import chapter_operation_definitions
        target = next(d for d in chapter_operation_definitions(application_build_id=authority.application_build_id, commit_sha=authority.commit_sha, model_effects_required=True, coordinated_contract=True) if d["name"] == "chapter.memo.generate" and d["definition_version"] == "3.10.2")
        u.repositories.definitions.register(target)
        u.commit()
    def guard(u):
        u.cursor.execute("SELECT version,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [book_run_id])
        if u.cursor.fetchone() != (book["version"], book["active_chapter_request_id"]) or _cancelled(u.cursor, book):
            raise KernelError("MEMO_RECOVERY_FRONTIER_CHANGED", "Reload the live frontier")
    replace_failed_step(authority.database_url, predecessor_id=source["operation_id"], target_version="3.10.2",
        context=AdmissionContext(principal.principal_id, principal.permissions, authority.chapter_port.application.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
        policy_evidence=policy, expected_failure_code=error, transaction_guard=guard)
    return True
