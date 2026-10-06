from __future__ import annotations

from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.canon_graph.evidence_localization import localize_provider_quotes
from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates
from .model_effects import ModelProviderResult

CONTRACT = "chapter-canon-output-repair.v1"


def retained_canon_output(cursor, source):
    from .handlers import _canon_provider_extraction
    from novel_forge.modules.production_execution.execution_template import verify_template_provenance
    from novel_forge.modules.command_kernel.step_successor import has_candidate_domain_outputs

    op = source["operation_id"]
    if (source["definition_name"] != "chapter.canon.extract" or source["definition_version"] != "3.9.7"
            or source["status"] != "FAILED_FINAL" or has_candidate_domain_outputs(cursor, op)):
        raise KernelError("CANON_OUTPUT_RECOVERY_NOT_APPLICABLE", "Require the exact non-producing terminal legacy Canon extraction")
    cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number", [op])
    attempts = [r[0] for r in cursor.fetchall()]
    if (not attempts or attempts[-1]["status"] != "FAILED_FINAL"
            or attempts[-1]["result"].get("error_code") not in {"REVIEW_EVIDENCE_INVALID", "CANON_GROUNDING_INVALID"}
            or any(a["status"] != "FAILED_RETRYABLE" or a["result"].get("error_code") != "MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE" for a in attempts[:-1])):
        raise KernelError("CANON_OUTPUT_RECOVERY_DIAGNOSTIC_REQUIRED", "Retain the failed host validation and every prior transport attempt")
    cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.request_payload,r.evidence,d.dispatch_id,receipt.payload->'evidence'
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE e.operation_id=%s AND e.status='SUCCEEDED' AND r.status='SETTLED'
        AND r.accounting_basis='ACCOUNT_ENTITLEMENT' AND e.effect_type='model.invoke'
        AND e.request_payload #>> '{_production_execution,attempt_id}'=%s ORDER BY receipt.received_at DESC""", [op, attempts[-1]["attempt_id"]])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("CANON_OUTPUT_RECOVERY_RECEIPT_REQUIRED", "Require one original settled membership receipt")
    effect, request_hash, payload, budget, dispatch, receipt = rows[0]
    decision = payload.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
    template = verify_template_provenance(cursor, decision)
    if (not template or template["mode"] != "CREATIVE_VALIDATION" or template["require_literary_qualification"]
            or decision.get("task", {}).get("operation_id") != op
            or decision.get("selected", {}).get("candidate", {}).get("authorization_ref") != budget.get("cost_authorization_ref")):
        raise KernelError("CANON_OUTPUT_RECOVERY_AUTHORIZATION_INVALID", "Retain the original creative membership identity")
    assets = {}
    for binding in source["input_asset_snapshot"]:
        cursor.execute("SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s", [binding["asset_version_id"], source["project_id"]])
        row = cursor.fetchone()
        if not row or row[2] != binding["content_hash"] or row[0] in assets:
            raise KernelError("CANON_OUTPUT_RECOVERY_INPUT_DRIFT", "Retain the exact uniquely typed frozen candidate and context")
        assets[row[0]] = (binding["asset_version_id"], row[1])
    target_id, candidate = assets["best_draft_candidate"]
    context_id, _ = assets["context_bundle"]
    result = ModelProviderResult.from_evidence(receipt)
    arguments = dict(project_id=source["project_id"], revision=candidate, revision_asset_version_id=target_id,
                     context_bundle_version_id=context_id, work_requirements=True)
    try:
        extract_grounded_candidates(**arguments, provider_extraction=_canon_provider_extraction(result))
    except KernelError as error:
        if error.code not in {"REVIEW_EVIDENCE_INVALID", "CANON_GROUNDING_INVALID"}:
            raise
        diagnostic = {"code": error.code, "reason": error.message}
    else:
        raise KernelError("CANON_OUTPUT_RECOVERY_NOT_APPLICABLE", "Do not regenerate valid retained Canon output")
    localized, localization = localize_provider_quotes(result.output, text=candidate["text"], target_asset_version_id=target_id)
    try:
        extract_grounded_candidates(**arguments, provider_extraction=_canon_provider_extraction(replace(result, output=localized)))
    except KernelError as error:
        if error.code != "CANON_GROUNDING_INVALID":
            raise
        remaining = {"code": error.code, "reason": error.message}
    else:
        raise KernelError("CANON_OUTPUT_RECOVERY_NOT_APPLICABLE", "A valid localized result requires derivation rather than a fresh call")
    cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.status,r.status,r.accounting_basis,r.evidence->>'cost_authorization_ref',
        a.attempt_id,a.status
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_attempt a ON a.attempt_id=e.request_payload #>> '{_production_execution,attempt_id}'
        WHERE e.operation_id=%s AND e.external_effect_id<>%s ORDER BY e.external_effect_id""", [op, effect])
    prior = cursor.fetchall()
    if (len(prior) != len(attempts)-1 or any(r[2:6] != ("FAILED_RETRYABLE", "SETTLED", "ACCOUNT_ENTITLEMENT", budget["cost_authorization_ref"])
            or r[6] not in {a["attempt_id"] for a in attempts[:-1]} or r[7] != "FAILED_RETRYABLE" for r in prior)):
        raise KernelError("CANON_OUTPUT_RECOVERY_UNSETTLED", "Unknown, live or unrelated failed effects retain their reconciliation owner")
    proof = {"contract_version": CONTRACT, "source_operation_id": op, "source_attempt": attempts[-1],
        "source_effect_id": effect, "source_request_hash": request_hash, "source_dispatch_id": dispatch,
        "cost_authorization_ref": budget["cost_authorization_ref"], "source_output_hash": snapshot_hash(result.output),
        "source_input_snapshot": source["input_asset_snapshot"], "legacy_diagnostic": diagnostic,
        "remaining_diagnostic": remaining, "quote_localization": localization,
        "target_asset_version_id": target_id, "book_id": template["book_id"],
        "known_failed_effects": [list(r[:6]) for r in prior], "provider_invoked": True,
        "strict_certification_eligible": False}
    return proof, result.output


def repair_feedback(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT as GRAPH

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    if proof.get("contract_version") != CONTRACT:
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute("SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id WHERE o.operation_id=%s AND j.contract_version=%s", [request.operation_id, GRAPH])
        row = c.fetchone()
        if (not row or row[0] != binding or row[2] != proof["source_input_snapshot"] or row[3] != row[1]["root"]["actor_id"]):
            raise KernelError("CANON_OUTPUT_RECOVERY_BINDING_INVALID", "Require exact native continuation, actor and candidate inputs")
        c.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [proof["source_operation_id"]])
        actual, raw = retained_canon_output(c, c.fetchone()[0])
        if actual != proof:
            raise KernelError("CANON_OUTPUT_RECOVERY_RECEIPT_DRIFT", "Retain the original failed result and evidence")
    return {"contract_version": CONTRACT, "rejected_output": raw, "diagnostic": proof["remaining_diagnostic"],
        "quote_localization": proof["quote_localization"], "target_asset_version_id": proof["target_asset_version_id"],
        "instructions": "Repair the Canon extraction only. Preserve the exact selected prose. Each field must use its allowed claim_kind; disclosure_events describe reader knowledge, not character acquisition. Quote the prose literally. Do not discard real changes to evade diagnostics. Independent Canon support remains required."}


def localize_new_result(request, generated, candidate):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.production_execution.execution_template import verify_template_provenance

    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute("SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE operation_id=%s AND request_payload #>> '{_production_execution,attempt_id}'=%s AND status='SUCCEEDED'", [request.operation_id, request.attempt_id])
        row = c.fetchone()
        template = verify_template_provenance(c, row[0]) if row else None
    if not template or template.get("canon_evidence_localization") != "TYPOGRAPHIC_QUOTE_EQUIVALENCE_V1":
        return generated, None
    if template["mode"] != "CREATIVE_VALIDATION" or template["version"] != "creative-execution-template.v9":
        raise KernelError("CANON_QUOTE_LOCALIZATION_POLICY_INVALID", "Strict certification retains literal Provider evidence")
    localized, evidence = localize_provider_quotes(generated.output, text=candidate.content["text"], target_asset_version_id=candidate.asset_version_id)
    return replace(generated, output=localized), evidence
