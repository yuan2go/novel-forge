from __future__ import annotations

from types import SimpleNamespace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    _read_verified_success,
    _validate_effect_context,
)
from novel_forge.storage.external_effect_repositories import ExternalEffectRepository

from .model_effects import ModelProviderResult

from novel_forge.modules.command_kernel.service import AdmissionContext
from novel_forge.modules.command_kernel.step_successor_v2 import (
    replace_failed_step,
    has_domain_outputs,
)
from novel_forge.modules.production_execution.execution_template import (
    selected_book_template,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from novel_forge.modules.production_execution.cost_routing import snapshot_hash

CONTRACT = "chapter-known-receipt.v2"


def _receipt(cursor, effect_id, project_id, *, source_operation_id, allow_completed=False, allow_retryable=False):
    cursor.execute(
        """SELECT actor_id,trace_id,correlation_id,status FROM authority_operation
        WHERE operation_id=%s AND project_id=%s""",
        [source_operation_id, project_id],
    )
    source = cursor.fetchone()
    allowed = {
        "FAILED_FINAL", "DEAD_LETTER", "WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED",
    }
    if allow_completed:
        allowed.add("SUCCEEDED")
    if allow_retryable:
        allowed.add("FAILED_RETRYABLE")
    if source is None or source[3] not in allowed:
        raise KernelError("KNOWN_RECEIPT_SOURCE_INVALID", "An exact stopped original owner is required")
    context = EffectCommandContext(operation_id=source_operation_id, project_id=project_id,
        actor_id=source[0], trace_id=source[1], correlation_id=source[2])
    _validate_effect_context(context)
    evidence = _read_verified_success(SimpleNamespace(cursor=cursor),
        ExternalEffectRepository(cursor), context, effect_id)
    if evidence is None or evidence["budget_reservation_status"] != "SETTLED":
        raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "The original outcome and cost must be settled")
    return ModelProviderResult.from_evidence(evidence["provider_evidence"])


LEGACY_CONTRACT = "chapter-known-receipt.v1"


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
            """SELECT DISTINCT to_jsonb(o) FROM authority_operation o JOIN authority_saga_step s USING(operation_id)
            JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.project_id=%s
            AND o.status='FAILED_FINAL' AND ((o.definition_name='chapter.draft.generate' AND o.definition_version='3.9.1' AND a.result->>'error_code'='PROGRAMMING_BUG') OR (o.definition_name='chapter.review.evaluate' AND o.definition_version='3.9.0' AND a.result->>'error_code'='REVIEW_KNOWLEDGE_CHECK_INVALID') OR (o.definition_name='chapter.canon.extract' AND o.definition_version='3.9.5' AND a.result->>'error_code'='MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE'))""",
            [request["chapter_root_operation_id"], book["project_id"]],
        )
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1:
            raise KernelError("KNOWN_RECEIPT_SOURCE_AMBIGUOUS", "Exactly one immutable stopped source is required")
        source = rows[0][0]
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
        result = _receipt(u.cursor, effect["external_effect_id"], book["project_id"], source_operation_id=source["operation_id"])
        u.cursor.execute("SELECT d.dispatch_id FROM authority_external_effect_dispatch d JOIN authority_external_receipt r USING(dispatch_id) WHERE d.external_effect_id=%s AND d.status='SUCCEEDED' AND r.status='VERIFIED' ORDER BY d.generation DESC LIMIT 1", [effect["external_effect_id"]])
        source_dispatch = u.cursor.fetchone()[0]
    rejected_ids, rejected_proof = completed_output_failures(authority.database_url, source, rejected) if rejected else ((), [])
    if source["definition_name"] == "chapter.canon.extract":
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates
        from novel_forge.modules.canon_graph.background import attach_background_proposals
        assets = [AuthorityAssetQuery(authority.database_url).require(project_id=book["project_id"], asset_version_id=a["asset_version_id"]) for a in source["input_asset_snapshot"]]
        revision = next(a for a in assets if a.asset_type == "best_draft_candidate")
        bundle = next(a for a in assets if a.asset_type == "context_bundle")
        candidate = extract_grounded_candidates(revision=revision.content, revision_asset_version_id=revision.asset_version_id,
            project_id=book["project_id"], context_bundle_version_id=bundle.asset_version_id,
            provider_extraction=known_canon_extraction(result, revision.content["text"], source_span_contract=(effect["request_payload"].get("input", {}).get("source_span_table") or {}).get("contract_version")), work_requirements=True)
        attach_background_proposals(extraction=candidate, binding=bundle.content["chapter_execution_expectations"]["world_preparation"])
    if reservation["status"] != "SETTLED":
        raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Original accounting must remain settled")
    evidence = {
        "contract_version": CONTRACT,
        "book_run_id": book_run_id,
        "chapter_request_id": request["chapter_request_id"],
        "source_operation_id": source["operation_id"],
        "source_dispatch_id": source_dispatch,
        "source_output_hash": snapshot_hash(result.output),
        "cost_authorization_ref": reservation["evidence"].get("cost_authorization_ref"),
        "source_span_contract": (effect["request_payload"].get("input", {}).get("source_span_table") or {}).get("contract_version"),
        "source_output_schema_ref": (effect["request_payload"].get("_production_execution") or {}).get("capability_runtime", {}).get("output_schema_ref"),
        "provider_invoked": False,
        "strict_certification_eligible": False,
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
        target_version="3.10.0",
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


def _consume_known_draft_receipt(request):
    if request.definition_version != "3.10.0" or not request.database_url:
        return None
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute(
            "SELECT policy_evidence,source_failure_snapshot FROM authority_saga_step_successor WHERE successor_operation_id=%s AND project_id=%s AND contract_version='kernel-failed-step-successor.v2'",
            [request.operation_id, request.project_id],
        )
        row = u.cursor.fetchone()
        if not row or row[0].get("contract_version") != CONTRACT:
            return None
        policy, failure = row
        source = failure["operation"]
        u.cursor.execute(
            "SELECT command_payload,input_asset_snapshot,actor_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [request.operation_id, request.project_id],
        )
        current = u.cursor.fetchone()
        if not current or current[2] != source["actor_id"]:
            raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Retain the original actor")
        command, inputs, _ = current
        u.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s AND project_id=%s", [source["operation_id"], request.project_id])
        if u.cursor.fetchone() != (source,):
            raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Retain the exact immutable original operation")
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
        result = _receipt(u.cursor, policy["source_effect_id"], request.project_id, source_operation_id=source["operation_id"])
        if policy.get("source_operation_id") != source["operation_id"] or snapshot_hash(result.output) != policy.get("source_output_hash"):
            raise KernelError("KNOWN_RECEIPT_BINDING_INVALID", "Retain exact result owner and output hash")
        u.cursor.execute("SELECT d.dispatch_id FROM authority_external_effect_dispatch d JOIN authority_external_receipt r USING(dispatch_id) WHERE d.external_effect_id=%s AND d.status='SUCCEEDED' AND r.status='VERIFIED' ORDER BY d.generation DESC LIMIT 1", [policy["source_effect_id"]])
        if u.cursor.fetchone() != (policy.get("source_dispatch_id"),) or policy.get("provider_invoked") is not False or policy.get("strict_certification_eligible") is not False:
            raise KernelError("KNOWN_RECEIPT_BINDING_INVALID", "Retain exact original dispatch and derivation boundary")
        return result, policy


def _cancelled(cursor, book):
    cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c JOIN authority_book_production b ON b.stable_idempotency_key=c.formation_run_id || ':production' WHERE b.project_id=%s AND b.book_run_id=%s)",
        [book["project_id"], book["book_run_id"]],
    )
    return cursor.fetchone()[0]


def is_known_receipt_revalidation(database_url, operation_id):
    with AuthorityUnitOfWork(database_url) as u:
        u.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE o.operation_id=%s AND o.project_id=s.project_id AND o.definition_version='3.10.0' AND s.policy_evidence->>'contract_version'=%s)",[operation_id,CONTRACT])
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
            "process_receipt_hash": receipt.content_hash, "request_hash": effect["request_hash"],
            "effect_status": effect["status"], "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "reservation_status": "SETTLED", "raw_output_asset_version_id": raw.asset_version_id,
            "raw_output_hash": raw.content_hash, "outcome": "COMPLETED_OUTPUT_SCHEMA_FAILURE"})
    return tuple(identities), proofs


def verified_attempt_feedback(cursor, *, operation_id, project_id, effect_id, request_hash):
    cursor.execute("""SELECT o.actor_id,o.trace_id,o.correlation_id FROM authority_operation o
        JOIN authority_external_effect e USING(operation_id)
        JOIN authority_attempt a ON a.attempt_id=e.request_payload #>> '{_production_execution,attempt_id}'
        WHERE o.operation_id=%s AND o.project_id=%s AND e.external_effect_id=%s AND e.request_hash=%s
        AND o.definition_name='chapter.canon.extract' AND o.definition_version IN ('3.9.29','3.9.30')
        AND a.operation_id=o.operation_id AND a.status='FAILED_RETRYABLE'
        AND a.result->>'error_code'='CANON_QUOTE_LOCALIZATION_INVALID'""",
        [operation_id, project_id, effect_id, request_hash])
    row = cursor.fetchone()
    if not row:
        raise KernelError("KNOWN_RECEIPT_SOURCE_INVALID", "Feedback must retain the exact original failed Attempt")
    context = EffectCommandContext(operation_id=operation_id, project_id=project_id,
        actor_id=row[0], trace_id=row[1], correlation_id=row[2])
    _validate_effect_context(context)
    evidence = _read_verified_success(SimpleNamespace(cursor=cursor), ExternalEffectRepository(cursor), context, effect_id)
    if evidence is None or evidence["budget_reservation_status"] != "SETTLED":
        raise KernelError("KNOWN_RECEIPT_RECONCILIATION_REQUIRED", "Feedback cannot bypass reconciliation")
    return ModelProviderResult.from_evidence(evidence["provider_evidence"])


def consume_known_draft_receipt(request):
    result = _consume_known_draft_receipt(request)
    return result[0] if result else None


def known_receipt_proof(request):
    result = _consume_known_draft_receipt(request)
    if not result:
        return None
    policy = result[1]
    return {key: policy[key] for key in ("contract_version", "source_operation_id", "source_effect_id", "source_dispatch_id", "source_output_hash", "source_request_hash", "provider_invoked", "strict_certification_eligible")}


def known_canon_extraction(result, text, *, source_span_contract):
    from .handlers import _canon_provider_extraction
    value = _canon_provider_extraction(result)
    if source_span_contract == "literal-source-spans.v1":
        from novel_forge.modules.canon_graph.source_spans import bind_source_spans
        return bind_source_spans(value, text)
    if source_span_contract is not None:
        raise KernelError("KNOWN_RECEIPT_BINDING_INVALID", "An unknown source wire cannot be reinterpreted")
    return value


def known_receipt_source_span_contract(request):
    result = _consume_known_draft_receipt(request)
    return result[1].get("source_span_contract") if result else None
