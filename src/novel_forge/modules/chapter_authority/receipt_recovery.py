from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor import (
    replace_failed_step,
    has_domain_outputs,
)
from novel_forge.modules.command_kernel.budget_runtime import settle_provider_budget
from novel_forge.modules.chapter_authority.model_effects import (
    ModelProviderResult,
    _model_budget_settlement,
)
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

CONTRACT = "chapter-known-receipt.v1"


def recover_known_draft_receipt(authority, *, book_run_id, principal):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] not in {
        "CHAPTER_RUNNING",
        "CHAPTER_SUBMITTED",
        "CHAPTER_WAITING_RETRY",
    } or not book.get("active_chapter_request_id"):
        return False
    request = authority.require_chapter_request(book["active_chapter_request_id"])
    if request["chapter_number"] != book["accepted_through_chapter"] + 1:
        return False
    with AuthorityUnitOfWork(authority.database_url) as u:
        template = selected_book_template(
            u.cursor, project_id=book["project_id"], book_id=book["book_id"]
        )
        if not template or _cancelled(u.cursor, book):
            return False
        u.cursor.execute(
            """SELECT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.project_id=%s
            AND o.status='FAILED_FINAL' AND ((o.definition_name='chapter.draft.generate' AND o.definition_version='3.9.1' AND a.result->>'error_code'='PROGRAMMING_BUG') OR (o.definition_name='chapter.review.evaluate' AND o.definition_version='3.9.0' AND a.result->>'error_code'='REVIEW_KNOWLEDGE_CHECK_INVALID'))""",
            [request["chapter_root_operation_id"], book["project_id"]],
        )
        row = u.cursor.fetchone()
        if not row:
            return False
        source = row[0]
        if source["actor_id"] != principal.principal_id or has_domain_outputs(
            u.cursor, source["operation_id"]
        ):
            raise KernelError(
                "KNOWN_RECEIPT_SOURCE_INVALID",
                "Only the owned unmaterialized Draft may be revalidated",
            )
        u.cursor.execute(
            "SELECT to_jsonb(e),to_jsonb(b) FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s",
            [source["operation_id"]],
        )
        effects = u.cursor.fetchall()
        if len(effects) != 1 or effects[0][0]["status"] != "SUCCEEDED":
            raise KernelError(
                "KNOWN_RECEIPT_RECONCILIATION_REQUIRED",
                "Reconcile every original effect before continuation",
            )
        effect, reservation = effects[0]
        result = _receipt(u.cursor, effect["external_effect_id"], book["project_id"])
    amount, tokens, basis = _model_budget_settlement(
        result,
        reserved_amount=reservation["reserved_amount"],
        reserved_tokens=reservation["estimated_tokens"],
        frozen_capability_profile=effect.get("provider_capability_profile") or {},
    )
    settle_provider_budget(
        authority.database_url,
        reservation_id=reservation["reservation_id"],
        project_id=book["project_id"],
        actual_amount=amount,
        actual_tokens=tokens,
        evidence={
            "provider_id": result.provider_id,
            "model_id": result.model_id,
            "real_model_call": result.real_model_call,
            "fixture": not result.real_model_call,
            "recovered_completed_effect": True,
            **basis,
        },
    )
    evidence = {
        "contract_version": CONTRACT,
        "book_run_id": book_run_id,
        "chapter_request_id": request["chapter_request_id"],
        "source_effect_id": effect["external_effect_id"],
        "source_request_hash": effect["request_hash"],
        "policy_admission": template,
        "completion_checks": "UNCHANGED",
    }

    def guard(u):
        u.cursor.execute(
            "SELECT version,active_chapter_request_id,accepted_through_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE",
            [book_run_id],
        )
        if (
            u.cursor.fetchone()
            != (
                book["version"],
                book["active_chapter_request_id"],
                book["accepted_through_chapter"],
            )
            or _cancelled(u.cursor, book)
            or selected_book_template(
                u.cursor, project_id=book["project_id"], book_id=book["book_id"]
            )
            != template
        ):
            raise KernelError(
                "KNOWN_RECEIPT_FRONTIER_CHANGED", "Reload the exact live frontier"
            )

    replace_failed_step(
        authority.database_url,
        predecessor_id=source["operation_id"],
        target_version="3.9.2" if source["definition_name"] == "chapter.draft.generate" else "3.9.1",
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
        expected_failure_code="PROGRAMMING_BUG" if source["definition_name"] == "chapter.draft.generate" else "REVIEW_KNOWLEDGE_CHECK_INVALID",
        known_receipt_effects=((effect["external_effect_id"], effect["request_hash"]),),
        transaction_guard=guard,
    )
    return True


def consume_known_draft_receipt(request):
    if request.definition_version not in {"3.9.1", "3.9.2"} or not request.database_url:
        return None
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute(
            "SELECT policy_evidence,source_failure_snapshot FROM authority_saga_step_successor WHERE successor_operation_id=%s AND project_id=%s",
            [request.operation_id, request.project_id],
        )
        row = u.cursor.fetchone()
        if not row or row[0].get("contract_version") != CONTRACT:
            return None
        policy, failure = row
        source = failure["operation"]
        u.cursor.execute(
            "SELECT command_payload,input_asset_snapshot FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [request.operation_id, request.project_id],
        )
        command, inputs = u.cursor.fetchone()
        if (
            command != source["command_payload"]
            or inputs != source["input_asset_snapshot"]
        ):
            raise KernelError(
                "KNOWN_RECEIPT_INPUT_DRIFT",
                "Revalidation must retain the original exact inputs",
            )
        u.cursor.execute(
            "SELECT e.operation_id,e.request_hash,e.status,b.status FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.external_effect_id=%s AND e.project_id=%s",
            [policy["source_effect_id"], request.project_id],
        )
        if u.cursor.fetchone() != (
            source["operation_id"],
            policy["source_request_hash"],
            "SUCCEEDED",
            "SETTLED",
        ):
            raise KernelError(
                "KNOWN_RECEIPT_BINDING_INVALID",
                "Reconcile the original succeeded receipt",
            )
        return _receipt(u.cursor, policy["source_effect_id"], request.project_id)


def _receipt(cursor, effect_id, project_id):
    cursor.execute(
        "SELECT r.payload->'evidence' FROM authority_external_receipt r JOIN authority_external_effect_dispatch d USING(dispatch_id) JOIN authority_external_effect e USING(external_effect_id) WHERE e.external_effect_id=%s AND e.project_id=%s AND e.status='SUCCEEDED' ORDER BY r.received_at DESC LIMIT 1",
        [effect_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        raise KernelError(
            "KNOWN_RECEIPT_EVIDENCE_MISSING",
            "No exact durable successful Provider receipt",
        )
    return ModelProviderResult.from_evidence(row[0])


def _cancelled(cursor, book):
    cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c JOIN authority_story_formation_run f USING(formation_run_id) WHERE f.project_id=%s AND f.book_id=%s)",
        [book["project_id"], book["book_id"]],
    )
    return cursor.fetchone()[0]


def is_known_receipt_revalidation(database_url, operation_id):
    with AuthorityUnitOfWork(database_url) as u:
        u.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE o.operation_id=%s AND o.project_id=s.project_id AND o.definition_version IN ('3.9.1','3.9.2') AND s.policy_evidence->>'contract_version'=%s)",[operation_id,CONTRACT])
        return u.cursor.fetchone()[0]
