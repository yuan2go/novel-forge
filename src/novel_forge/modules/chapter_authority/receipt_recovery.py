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
            AND o.status='FAILED_FINAL' AND ((o.definition_name='chapter.draft.generate' AND o.definition_version='3.9.1' AND a.result->>'error_code'='PROGRAMMING_BUG') OR (o.definition_name='chapter.review.evaluate' AND o.definition_version='3.9.0' AND a.result->>'error_code'='REVIEW_KNOWLEDGE_CHECK_INVALID') OR (o.definition_name='chapter.canon.extract' AND o.definition_version='3.9.5' AND a.result->>'error_code'='MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE'))""",
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
                "Only owned unmaterialized Chapter output may be revalidated",
            )
        u.cursor.execute(
            "SELECT to_jsonb(e),to_jsonb(b) FROM authority_external_effect e JOIN authority_budget_reservation b USING(external_effect_id) WHERE e.operation_id=%s",
            [source["operation_id"]],
        )
        effects = u.cursor.fetchall()
        rejected = [pair for pair in effects if pair[0]["status"] != "SUCCEEDED"]
        effects = [pair for pair in effects if pair[0]["status"] == "SUCCEEDED"]
        if len(effects) != 1 or (rejected and source["definition_name"] != "chapter.canon.extract"):
            raise KernelError(
                "KNOWN_RECEIPT_RECONCILIATION_REQUIRED",
                "Reconcile every original effect before continuation",
            )
        effect, reservation = effects[0]
        result = _receipt(u.cursor, effect["external_effect_id"], book["project_id"])
    rejected_ids, rejected_proof = completed_output_failures(authority.database_url, source, rejected) if rejected else ((), [])
    if source["definition_name"] == "chapter.canon.extract":
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        from novel_forge.modules.canon_graph.source_spans import bind_source_spans
        from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates
        from novel_forge.modules.canon_graph.background import attach_background_proposals
        assets = [AuthorityAssetQuery(authority.database_url).require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
        revision = next(a for a in assets if a.asset_type == "best_draft_candidate")
        bundle = next(a for a in assets if a.asset_type == "context_bundle")
        candidate = extract_grounded_candidates(revision=revision.content, revision_asset_version_id=revision.asset_version_id,
            project_id=book["project_id"], context_bundle_version_id=bundle.asset_version_id,
            provider_extraction=bind_source_spans(result.output, revision.content["text"]), work_requirements=True)
        attach_background_proposals(extraction=candidate, binding=bundle.content["chapter_execution_expectations"]["world_preparation"])
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
        **({"schema_rejection_receipts": rejected_proof} if rejected_proof else {}),
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
        target_version="3.9.6" if source["definition_name"] == "chapter.canon.extract" else "3.9.2" if source["definition_name"] == "chapter.draft.generate" else "3.9.1",
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
        expected_failure_code="MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE" if source["definition_name"] == "chapter.canon.extract" else "PROGRAMMING_BUG" if source["definition_name"] == "chapter.draft.generate" else "REVIEW_KNOWLEDGE_CHECK_INVALID",
        known_receipt_effects=((effect["external_effect_id"], effect["request_hash"]),),
        known_rejected_effects=rejected_ids,
        transaction_guard=guard,
    )
    return True


def consume_known_draft_receipt(request):
    if request.definition_version not in {"3.9.1", "3.9.2", "3.9.6"} or not request.database_url:
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
        u.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE o.operation_id=%s AND o.project_id=s.project_id AND o.definition_version IN ('3.9.1','3.9.2','3.9.6') AND s.policy_evidence->>'contract_version'=%s)",[operation_id,CONTRACT])
        return u.cursor.fetchone()[0]


def completed_output_failures(database_url, source, effects):
    import json
    from hashlib import sha256
    from pathlib import Path
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    query = AuthorityAssetQuery(database_url)
    identities, proofs = [], []
    for effect, reservation in effects:
        result = (effect.get("last_error") or {}).get("production_execution", {}).get("execution_result", {})
        if effect["status"] != "FAILED_FINAL" or reservation["status"] != "SETTLED" or reservation["accounting_basis"] != "ACCOUNT_ENTITLEMENT":
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Uncertain or paid outcomes require their original reconciliation owner")
        receipt = query.require(project_id=source["project_id"], asset_version_id=result["process_receipt_ref"].removeprefix("authority-asset-version:"))
        raw = query.require(project_id=source["project_id"], asset_version_id=result["raw_output_ref"].removeprefix("authority-asset-version:"))
        payload = receipt.content.get("payload") or {}
        if (receipt.content.get("kind") != "process-receipt" or payload.get("status") != "SUCCEEDED"
            or payload.get("operation_id") != source["operation_id"] or payload.get("execution_id") != result.get("execution_id")
            or result.get("outcome") != "FINAL_FAILURE" or raw.content.get("kind") != "rejected-output"
            or raw.content.get("execution_id") != result.get("execution_id")
            or raw.content.get("payload", {}).get("validation") != "REJECTED"):
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Exact completed process and immutable malformed output evidence are required")
        artifact = raw.content["payload"]
        path = Path(artifact["result_path"]).resolve()
        if path.parent != Path(payload["execution_directory"]).resolve():
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Rejected output must remain inside its exact execution")
        data = path.read_bytes()
        if len(data) != artifact["byte_size"] or "sha256:" + sha256(data).hexdigest() != artifact["result_sha256"]:
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Rejected output bytes no longer match immutable evidence")
        try:
            outer = json.loads(data)
            json.loads(outer["payload_json"])
        except (ValueError, KeyError, TypeError):
            pass
        else:
            raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Only a proven malformed JSON envelope may use this continuation")
        identities.append((effect["external_effect_id"], effect["request_hash"], receipt.asset_version_id, receipt.content_hash))
        proofs.append({"external_effect_id": effect["external_effect_id"], "process_receipt_asset_version_id": receipt.asset_version_id,
            "process_receipt_hash": receipt.content_hash, "raw_output_asset_version_id": raw.asset_version_id,
            "raw_output_hash": raw.content_hash, "outcome": "COMPLETED_OUTPUT_SCHEMA_FAILURE"})
    return tuple(identities), proofs
