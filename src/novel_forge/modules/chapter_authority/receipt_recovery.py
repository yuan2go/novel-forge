from __future__ import annotations

from .capacity_continuation import effective_context_content

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


def lock_scope_recovery_creation(cursor, *, root_id, project_id):
    cursor.execute("""SELECT formation.formation_run_id FROM authority_story_formation_run formation
        JOIN authority_book_production book ON book.stable_idempotency_key=formation.formation_run_id || ':production'
        AND book.project_id=formation.project_id JOIN authority_book_chapter_request request
        ON request.chapter_request_id=book.active_chapter_request_id AND request.book_run_id=book.book_run_id
        WHERE request.chapter_root_operation_id=%s AND book.project_id=%s FOR UPDATE OF formation""", [root_id, project_id])
    row = cursor.fetchone()
    if row is None:
        raise KernelError("DRAFT_SCOPE_RECOVERY_SOURCE_INVALID", "Scope recovery requires its native Creation owner")
    cursor.execute("""SELECT book.book_run_id FROM authority_book_production book
        JOIN authority_book_chapter_request request ON request.chapter_request_id=book.active_chapter_request_id
        AND request.book_run_id=book.book_run_id WHERE request.chapter_root_operation_id=%s AND book.project_id=%s
        AND book.stable_idempotency_key=%s FOR UPDATE OF book""", [root_id, project_id, row[0] + ":production"])
    if cursor.fetchone() is None:
        raise KernelError("DRAFT_SCOPE_RECOVERY_FRONTIER_CHANGED", "Retain the exact active Chapter frontier")
    cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=%s)", [row[0]])
    if cursor.fetchone()[0]:
        raise KernelError("DRAFT_SCOPE_RECOVERY_CANCELLED", "Original Creation cancellation prevents adoption")


def guard_scope_draft_materialization(uow, request):
    if request.definition_version != "3.10.3":
        return
    uow.cursor.execute("SELECT root_operation_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
        [request.operation_id, request.project_id])
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("DRAFT_SCOPE_RECOVERY_SOURCE_INVALID", "Scope materialization requires its admitted native owner")
    lock_scope_recovery_creation(uow.cursor, root_id=row[0], project_id=request.project_id)


def revalidate_applicability_scope(source, result, *, asset_reader):
    from .scene_receipt_recovery import draft_receipt_inputs
    from .chapter_plan_views import build_creative_baseline, build_draft_style_view
    from .realization_composition import compile_realization_contract, resolve_accepted_realization_sources
    from .domain_handlers import normalize_draft_result
    from .craft_execution import require_craft_delivery
    from novel_forge.modules.book_authority.manuscript import validate_complete_prose

    request = draft_receipt_inputs(source, asset_reader=asset_reader)
    plan, context = request.require_input("chapter_plan"), request.require_input("context_bundle")
    try:
        build_creative_baseline(plan.content, effective_context_content(request, context), contract_version="creative-baseline.v1")
    except KernelError as error:
        if error.code != "QUALITY_APPLICABILITY_CONFLICT":
            raise
    else:
        raise KernelError("DRAFT_SCOPE_RECOVERY_NOT_APPLICABLE", "Require the original deterministic cross-scope conflict")
    baseline = build_creative_baseline(plan.content, effective_context_content(request, context), contract_version="creative-baseline.v2")
    require_craft_delivery(plan=plan.content, intent=request.require_input("chapter_execution_intent").content,
        memo=request.require_input("chapter_memo").content, context=effective_context_content(request, context))
    contract = compile_realization_contract(plan.content, build_draft_style_view(effective_context_content(request, context), work_requirements=True),
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1",
        accepted_sources=resolve_accepted_realization_sources(request, asset_reader=asset_reader, verify_content_hash=True),
        world_preparation=effective_context_content(request, context).get("chapter_execution_expectations", {}).get("world_preparation", {}))
    content = normalize_draft_result(plan=plan.content, context_asset_version_id=context.asset_version_id,
        context_content_hash=context.content_hash, context_content=effective_context_content(request, context), result=result.output,
        provider_evidence=result.to_evidence(), work_requirements=True,
        core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1", realization_contract=contract,
        enforce_voice_contract=not bool((request.command.get("preparation_report") or {}).get("author_workflow")))
    validate_complete_prose(content)
    return {"contract_version": "book-chapter-applicability.v1", "source_contract": "creative-baseline.v1",
        "target_contract": "creative-baseline.v2", "baseline_digest": baseline["baseline_digest"],
        "raw_output_hash": snapshot_hash(result.output), "realization_contract_hash": snapshot_hash(contract),
        "prose_changed": False, "author_constraints_changed": False, "fact_mutation_allowed": False}


def recover_applicability_scope_receipt(authority, *, book_run_id, principal):
    return recover_known_draft_receipt(authority, book_run_id=book_run_id, principal=principal,
        failure_code="QUALITY_APPLICABILITY_CONFLICT")


def recover_known_draft_receipt(authority, *, book_run_id, principal, failure_code=""):
    book = authority.require(book_run_id)
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    if book["state"] not in {
        "PAUSED",
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
            AND o.status='FAILED_FINAL' AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor j WHERE j.predecessor_operation_id=o.operation_id)
            AND ((o.definition_name='chapter.draft.generate' AND o.definition_version='3.10.0' AND a.result->>'error_code' IN ('PROGRAMMING_BUG','QUALITY_APPLICABILITY_CONFLICT')) OR (o.definition_name='chapter.review.evaluate' AND o.definition_version='3.9.0' AND a.result->>'error_code'='REVIEW_KNOWLEDGE_CHECK_INVALID') OR (o.definition_name='chapter.canon.extract' AND o.definition_version='3.9.5' AND a.result->>'error_code'='MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE'))
            AND (%s='' OR a.result->>'error_code'=%s)""",
            [request["chapter_root_operation_id"], book["project_id"], failure_code, failure_code],
        )
        rows = u.cursor.fetchall()
        if not rows:
            return False
        if len(rows) != 1:
            raise KernelError("KNOWN_RECEIPT_SOURCE_AMBIGUOUS", "Exactly one immutable stopped source is required")
        source = rows[0][0]
        _require_current_receipt_family(source)
        u.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number", [source["operation_id"]])
        failure_codes = {row[0] for row in u.cursor.fetchall()}
        scope_repair = failure_codes == {"QUALITY_APPLICABILITY_CONFLICT"} and source["definition_name"] == "chapter.draft.generate"
        if "QUALITY_APPLICABILITY_CONFLICT" in failure_codes and not scope_repair:
            raise KernelError("DRAFT_SCOPE_RECOVERY_SOURCE_INVALID", "Only an exact applicability failure can change the scope contract")
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
        if scope_repair:
            scope_proof = revalidate_applicability_scope(source, result, asset_reader=u.repositories.asset_documents)
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
        **({"creative_baseline_scope_revalidation": scope_proof} if scope_repair else {}),
        **({"schema_rejection_receipts": rejected_proof} if rejected_proof else {}),
    }

    def guard(u):
        if scope_repair:
            lock_scope_recovery_creation(u.cursor, root_id=source["root_operation_id"], project_id=book["project_id"])
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

    target_version = "3.10.3" if scope_repair else "3.10.0"
    if scope_repair:
        from .definitions import chapter_operation_definitions
        target = next(item for item in chapter_operation_definitions(application_build_id=authority.application_build_id,
            commit_sha=authority.commit_sha, model_effects_required=True, coordinated_contract=True)
            if item["name"] == "chapter.draft.generate" and item["definition_version"] == target_version)
        with AuthorityUnitOfWork(authority.database_url) as u:
            u.repositories.definitions.register(target)
            u.commit()
    replace_failed_step(
        authority.database_url,
        predecessor_id=source["operation_id"],
        target_version=target_version,
        context=AdmissionContext(
            principal.principal_id,
            principal.permissions,
            authority.chapter_port.application.registry.available_handler_keys,
            authority.application_build_id,
            authority.commit_sha,
        ),
        policy_evidence=evidence,
        expected_failure_code="QUALITY_APPLICABILITY_CONFLICT" if scope_repair else "MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE" if source["definition_name"] == "chapter.canon.extract" else "PROGRAMMING_BUG" if source["definition_name"] == "chapter.draft.generate" else "REVIEW_KNOWLEDGE_CHECK_INVALID",
        known_receipt_effects=((effect["external_effect_id"], effect["request_hash"]),),
        known_rejected_effects=rejected_ids,
        transaction_guard=guard,
    )
    return True


def _require_current_receipt_family(source):
    if source.get("definition_name") != "chapter.draft.generate":
        return
    policy = (source.get("definition_snapshot") or {}).get("policy") or {}
    if (source.get("definition_version") != "3.10.0"
            or policy.get("scene_core_projection") != "continuous-scene.v1"
            or policy.get("scene_information_flow") != "actor-source-scope.v1"):
        raise KernelError("KNOWN_RECEIPT_HISTORICAL_CONTRACT_BLOCKED", "Historical Draft receipt does not prove the mandatory current continuous-scene and actor-source contract")


def _consume_known_draft_receipt(request):
    if request.definition_version not in {"3.10.0", "3.10.1", "3.10.2", "3.10.3"} or not request.database_url:
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
        if request.definition_version == "3.10.2":
            from .memo_recovery import original_memo_source
            source = original_memo_source(u.cursor, source, policy)
        _require_current_receipt_family(source)
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
        if request.definition_version == "3.10.3" and revalidate_applicability_scope(source, result, asset_reader=u.repositories.asset_documents) != policy.get("creative_baseline_scope_revalidation"):
            raise KernelError("DRAFT_SCOPE_RECOVERY_PROOF_DRIFT", "Retain the exact source-bound scope correction")
        return result, policy


def _cancelled(cursor, book):
    cursor.execute(
        "SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation c JOIN authority_book_production b ON b.stable_idempotency_key=c.formation_run_id || ':production' WHERE b.project_id=%s AND b.book_run_id=%s)",
        [book["project_id"], book["book_run_id"]],
    )
    return cursor.fetchone()[0]


def is_known_receipt_revalidation(database_url, operation_id):
    with AuthorityUnitOfWork(database_url) as u:
        u.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE o.operation_id=%s AND o.project_id=s.project_id AND o.definition_version IN ('3.10.0','3.10.1','3.10.3') AND s.policy_evidence->>'contract_version'=%s)",[operation_id,CONTRACT])
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


def consume_completed_generation_result(request, *, stage, payload):
    from dataclasses import replace
    from psycopg.types.json import Jsonb
    with AuthorityUnitOfWork(request.database_url) as u:
        u.cursor.execute("""SELECT e.external_effect_id FROM authority_external_effect e
            WHERE e.operation_id=%s AND e.project_id=%s AND e.request_payload->>'stage'=%s
              AND (e.request_payload->'input'=%s OR (e.request_payload->'input')-'_context_capacity_projection'=%s)
              AND e.status IN ('DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED')
              AND e.request_payload#>>'{_production_execution,attempt_id}'<>%s
              AND NOT authority_generation_isolated(e.external_effect_id) LIMIT 1""",
            [request.operation_id, request.project_id, stage, Jsonb(payload), Jsonb(payload), request.attempt_id])
        unresolved = u.cursor.fetchone()
        if unresolved:
            raise KernelError("MODEL_EFFECT_RECONCILIATION_REQUIRED", "reconcile the original invocation before resuming identical stage input",
                              details={"external_effect_id": unresolved[0]})
        u.cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.request_payload,o.actor_id,o.trace_id,o.correlation_id
            FROM authority_external_effect e JOIN authority_operation o USING(operation_id)
            JOIN authority_attempt a ON a.attempt_id=e.request_payload#>>'{_production_execution,attempt_id}'
            WHERE e.operation_id=%s AND e.project_id=%s AND o.workspace_id=%s AND e.status='SUCCEEDED' AND e.effect_type='model.invoke'
              AND e.request_payload->>'stage'=%s
              AND (e.request_payload->'input'=%s OR (e.request_payload->'input')-'_context_capacity_projection'=%s)
              AND a.status IN ('FAILED_RETRYABLE','FAILED_FINAL')
              AND NOT (%s AND COALESCE(a.result->>'error_code','')='REVIEW_RESOLUTION_CHECKS_REQUIRED')
              AND a.attempt_id<>%s ORDER BY a.attempt_number DESC,e.created_at DESC LIMIT 1""",
            [request.operation_id, request.project_id, request.workspace_id, stage, Jsonb(payload), Jsonb(payload),
             stage == 'rereview' and request.effective_definition_version == '3.10.0'
             and bool((request.command.get('preparation_report') or {}).get('working_revision')), request.attempt_id])
        own = u.cursor.fetchone()
        if own and {key: value for key, value in own[2].get('input', {}).items() if key != '_context_capacity_projection'} == {key: value for key, value in payload.items() if key != '_context_capacity_projection'}:
            expected_book = request.command.get('book_id')
            original_book = (own[2].get('_production_execution') or {}).get('book_id')
            if expected_book and original_book != expected_book:
                raise KernelError('KNOWN_RECEIPT_INPUT_DRIFT', 'The retained invocation belongs to another Book')
            verified = _read_verified_success(u, u.repositories.external_effects,
                EffectCommandContext(request.operation_id, request.project_id, own[3], own[4], own[5]), own[0],
                retained_generation_stage=True)
            if verified is None:
                raise KernelError('KNOWN_RECEIPT_SOURCE_INVALID', 'Reuse requires the original verified complete model result')
            result = ModelProviderResult.from_evidence(verified['provider_evidence'])
            return replace(result, execution_evidence={**(result.execution_evidence or {}),
                'completed_attempt_reuse': {'contract_version': 'chapter-completed-attempt-reuse.v1',
                    'source_operation_id': request.operation_id, 'source_effect_id': own[0], 'source_request_hash': own[1],
                    'source_attempt_id': own[2]['_production_execution']['attempt_id'],
                    'stage': stage, 'provider_invoked': False, 'accounting_status': verified['budget_reservation_status'],
                    **({'pending_settlement': {key: verified[key] for key in (
                        'budget_reservation_id', 'budget_reserved_amount', 'budget_estimated_tokens', 'provider_capability_profile')}}
                       if verified['budget_reservation_status'] != 'SETTLED' else {})}})
        u.cursor.execute("""SELECT journal.policy_evidence,journal.source_failure_snapshot,
            current.command_payload,current.input_asset_snapshot,current.actor_id,current.definition_version
            FROM authority_saga_step_successor journal JOIN authority_operation current
              ON current.operation_id=journal.successor_operation_id
            WHERE journal.successor_operation_id=%s AND journal.project_id=%s
              AND journal.policy_evidence->>'contract_version'='chapter-pure-generation-successor.v1'""",
            [request.operation_id, request.project_id])
        row = u.cursor.fetchone()
        if not row:
            return None
        policy, failure, command, inputs, actor, version = row
        source = failure["operation"]
        if (command != source["command_payload"] or inputs != source["input_asset_snapshot"]
                or actor != source["actor_id"] or version != source["definition_version"]
                or version != request.effective_definition_version):
            raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Completed siblings retain the same Chapter actor, frozen inputs and execution contract")
        matches = []
        for proof in policy.get("completed_model_effects", []):
            if proof.get("stage") != stage:
                continue
            u.cursor.execute("""SELECT operation_id,request_hash,status,request_payload FROM authority_external_effect
                WHERE external_effect_id=%s AND project_id=%s""", [proof["external_effect_id"], request.project_id])
            effect = u.cursor.fetchone()
            if not effect or effect[:3] != (source["operation_id"], proof["request_hash"], "SUCCEEDED"):
                raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "The retained sibling identity changed")
            if effect[3].get("input") == payload:
                matches.append(proof)
        if not matches:
            if policy.get("completed_revalidation"):
                raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Completed-only succession cannot dispatch a changed model request")
            return None
        if len(matches) != 1:
            raise KernelError("KNOWN_RECEIPT_SOURCE_AMBIGUOUS", "Exactly one completed sibling may satisfy the current stage and input")
        proof = matches[0]
        context = EffectCommandContext(source["operation_id"], request.project_id, source["actor_id"],
            source["trace_id"], source["correlation_id"])
        verified = _read_verified_success(u, u.repositories.external_effects, context,
            proof["external_effect_id"], retained_generation_stage=True)
        if verified is None:
            raise KernelError("KNOWN_RECEIPT_SOURCE_INVALID", "A verified retained model result is required")
        result = ModelProviderResult.from_evidence(verified["provider_evidence"])
        return replace(result, execution_evidence={**(result.execution_evidence or {}),
            "completed_sibling_reuse": {"contract_version": "chapter-completed-sibling-reuse.v1",
                "source_operation_id": source["operation_id"], "source_effect_id": proof["external_effect_id"],
                "source_request_hash": proof["request_hash"], "successor_operation_id": request.operation_id,
                "stage": stage, "provider_invoked": False, "accounting_status": verified['budget_reservation_status'],
                "original_submission_right": "REVOKED"}})


def recover_completed_chapter_results(authority, *, book_run_id, principal, root_operation_id):
    from dataclasses import replace
    from .contracts import ChapterHandlerRequest, ChapterInputAsset, ChapterNode
    from .model_effects import ModelProviderResult
    from novel_forge.modules.command_kernel.step_successor import require_live_chapter_frontier
    book = authority.require(book_run_id)
    app = authority.chapter_port.application
    principal.require("book.authority.execute", book["project_id"])
    principal.require("chapter.authority.execute", book["project_id"])
    with AuthorityUnitOfWork(authority.database_url) as uow:
        require_live_chapter_frontier(uow.cursor, root_id=root_operation_id,
            project_id=book["project_id"], book_run_id=book_run_id)
        uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o
            JOIN authority_saga_step step USING(operation_id)
            WHERE o.root_operation_id=%s AND o.project_id=%s AND o.actor_id=%s
              AND o.status IN ('FAILED_FINAL','DEAD_LETTER') AND o.definition_snapshot->>'commit_sha'<>%s
              AND EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=o.operation_id)
              AND NOT EXISTS(SELECT 1 FROM authority_external_effect e WHERE e.operation_id=o.operation_id
                AND (e.status<>'SUCCEEDED' OR e.effect_type<>'model.invoke'))
              AND NOT EXISTS(SELECT 1 FROM authority_saga_step_successor s WHERE s.predecessor_operation_id=o.operation_id)
            ORDER BY o.created_at""", [root_operation_id, book["project_id"], principal.principal_id, authority.commit_sha])
        sources = [row[0] for row in uow.cursor.fetchall()]
    changed = False
    for source in sources:
        node = next((item for item in ChapterNode if item.definition_name == source["definition_name"]), None)
        if node is None:
            continue
        with AuthorityUnitOfWork(authority.database_url) as uow:
            if has_domain_outputs(uow.cursor, source["operation_id"]):
                continue
            inputs = []
            for binding in source["input_asset_snapshot"]:
                doc = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=binding["asset_version_id"])
                if doc.content_hash != binding["content_hash"]:
                    raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Retain exact frozen source content")
                inputs.append(ChapterInputAsset(doc.asset_version_id, doc.asset_type, doc.content_hash, doc.content))
            uow.cursor.execute("SELECT to_jsonb(e) FROM authority_external_effect e WHERE operation_id=%s ORDER BY created_at", [source["operation_id"]])
            effects = [row[0] for row in uow.cursor.fetchall()]
            retained = []
            context = EffectCommandContext(source["operation_id"], book["project_id"], source["actor_id"], source["trace_id"], source["correlation_id"])
            for effect in effects:
                verified = _read_verified_success(uow, uow.repositories.external_effects, context,
                    effect["external_effect_id"], retained_generation_stage=True)
                if verified is None:
                    raise KernelError("KNOWN_RECEIPT_SOURCE_INVALID", "A complete verified pure generation is required")
                result = ModelProviderResult.from_evidence(verified["provider_evidence"])
                retained.append((effect["request_payload"], replace(result,
                    execution_evidence={**(result.execution_evidence or {}), "completed_attempt_reuse": {
                        "contract_version": "chapter-completed-result-validation.v1",
                        "source_operation_id": source["operation_id"], "source_effect_id": effect["external_effect_id"],
                        "source_request_hash": effect["request_hash"], "provider_invoked": False,
                        "accounting_status": verified["budget_reservation_status"]}})))
            uow.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source["operation_id"]])
            failure_code = uow.cursor.fetchone()[0]
        request = ChapterHandlerRequest(source["operation_id"], source["project_id"], source["workspace_id"],
            source["trace_id"], source["correlation_id"], source["command_payload"], tuple(inputs),
            definition_version=source["definition_version"], database_url=authority.database_url)
        from .runtime import bind_working_revision_inputs
        request = bind_working_revision_inputs(request)
        handler = app.registry.require(node)
        port = _CompletedOnlyPort(retained, getattr(handler.provider, "adapter", None))
        replace(handler, provider=port).execute(request)
        policy = {"contract_version": "chapter-pure-generation-successor.v1", "completed_revalidation": True,
            "book_run_id": book_run_id, "release_sha": authority.commit_sha, "provider_invoked": False,
            "completion_checks": "UNCHANGED", "completed_model_effects": [
                {"external_effect_id": item["external_effect_id"], "request_hash": item["request_hash"],
                 "stage": item["request_payload"]["stage"]} for item in effects]}
        replace_failed_step(authority.database_url, predecessor_id=source["operation_id"],
            target_version=source["definition_version"], expected_failure_code=failure_code,
            context=AdmissionContext(principal.principal_id, principal.permissions,
                app.registry.available_handler_keys, authority.application_build_id, authority.commit_sha),
            policy_evidence=policy, known_receipt_effects=tuple(
                (item["external_effect_id"], item["request_hash"]) for item in effects))
        changed = True
    return changed


class _CompletedOnlyPort:
    def __init__(self, retained, adapter=None):
        self.retained = retained
        self.adapter = adapter

    def invoke(self, request, *, stage, payload, **kwargs):
        matches = [result for original, result in self.retained
                   if original.get("stage") == stage and original.get("input") == payload]
        if len(matches) != 1:
            raise KernelError("KNOWN_RECEIPT_INPUT_DRIFT", "Completed-result revalidation cannot send changed or new model input")
        return matches[0]


def completed_result_proof(request):
    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute("""SELECT j.policy_evidence,j.source_failure_snapshot FROM authority_saga_step_successor j
            WHERE j.successor_operation_id=%s AND j.project_id=%s AND j.contract_version='kernel-failed-step-successor.v2'""",
            [request.operation_id, request.project_id])
        row = uow.cursor.fetchone()
    if not row or row[0].get("completed_revalidation") is not True:
        return None
    policy, frozen = row
    return {"contract_version": "chapter-completed-result-revalidation.v1",
        "source_operation_id": frozen["operation"]["operation_id"],
        "successor_operation_id": request.operation_id, "provider_invoked": False,
        "strict_certification_eligible": False, "completed_model_effects": policy["completed_model_effects"]}


def _owner_context_sources(database_url, *, project_id, operation_id, owner_stage, cursor=None):
    if cursor is None:
        with AuthorityUnitOfWork(database_url) as uow:
            return _owner_context_sources(database_url, project_id=project_id, operation_id=operation_id,
                owner_stage=owner_stage, cursor=uow.cursor)
    cursor.execute("""SELECT request_payload FROM authority_external_effect
            WHERE project_id=%s AND operation_id=%s AND effect_type='model.invoke'
              AND (request_payload->>'stage'=%s
                OR request_payload#>>'{input,context_compression_task,task,stage}'=%s)
            ORDER BY created_at,external_effect_id""", [project_id, operation_id, owner_stage, owner_stage])
    rows = cursor.fetchall()
    sources = {}
    for (payload,) in rows:
        if payload.get("stage") == owner_stage:
            bindings = [item for item in payload.get("_production_execution", {}).get("input_artifacts", [])
                        if item.get("artifact_type") == "context_bundle"]
        else:
            chunk = payload.get("input", {}).get("context_compression_task", {})
            if chunk.get("contract_version") != "task-context-compression.v2" or chunk.get("task", {}).get("capacity_policy") != "complete-request-capacity.v1":
                continue
            bindings = [chunk.get("source_binding") or {}]
        for binding in bindings:
            version, digest = binding.get("asset_version_id"), binding.get("content_hash")
            if not version or not digest:
                raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "Retained Owner invocation has an incomplete source binding")
            sources[(version, digest)] = {"asset_version_id": version, "content_hash": digest}
    return tuple(sources.values())


def retained_owner_context(database_url, *, project_id, operation_id, owner_stage, current_content):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    sources = _owner_context_sources(database_url, project_id=project_id, operation_id=operation_id, owner_stage=owner_stage)
    if not sources:
        return None
    if len(sources) != 1:
        raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "One owning Operation cannot replace its retained Context sources")
    source = sources[0]
    document = AuthorityAssetQuery(database_url).require(project_id=project_id, asset_version_id=source["asset_version_id"])
    if (document.asset_type != "context_bundle" or document.content_hash != source["content_hash"]
            or document.governance != "CLEAR" or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            or document.content.get("operation_id") != operation_id
            or snapshot_hash({key: value for key, value in document.content.items() if key != "attempt_id"})
                != snapshot_hash({key: value for key, value in current_content.items() if key != "attempt_id"})):
        raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "Retained Context must preserve every original field, source and Owner")
    return document


def require_retained_owner_context_binding(database_url, *, project_id, operation_id, owner_stage, source, cursor=None):
    bindings = _owner_context_sources(database_url, project_id=project_id, operation_id=operation_id,
        owner_stage=owner_stage, cursor=cursor)
    if not any(item == {key: source.get(key) for key in ("asset_version_id", "content_hash")} for item in bindings):
        raise KernelError("CONTEXT_COMPRESSION_OWNER_DRIFT", "Another Attempt Context requires its original durable Owner invocation")


def retained_capacity_bindings(database_url, *, project_id, operation_id, source_hash, source_boundary, stage):
    from novel_forge.modules.narrative_state.reality import narrative_hash
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT request_payload#>'{input,context_compression_task,task}'
            FROM authority_external_effect WHERE operation_id=%s AND project_id=%s
              AND request_payload#>>'{input,context_compression_task,task,source_projection_hash}'=%s
              AND request_payload#>>'{input,context_compression_task,task,stage}'=%s""",
            [operation_id, project_id, source_hash, stage])
        rows = uow.cursor.fetchall()
    bindings = {}
    for (task,) in rows:
        if task.get("frozen_input_boundary") != source_boundary:
            raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "Retained compression belongs to another frozen source boundary")
        value = task.get("capacity_bindings")
        if value:
            bindings[narrative_hash(value)] = value
    if len(bindings) > 1:
        raise KernelError("ROUTING_CAPACITY_BINDING_DRIFT", "Retained chunks disagree on their prepared route identities")
    return next(iter(bindings.values()), {})
