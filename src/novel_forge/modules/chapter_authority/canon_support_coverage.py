from __future__ import annotations

from collections import Counter
from copy import deepcopy

from novel_forge.modules.canon_graph.grounding import grounded_claims, validate_support_review
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash

CONTRACT = "chapter-canon-support-coverage-repair.v1"


def bind_claim_identifiers(schema, claims):
    identifiers = [item["claim"]["grounded_claim_id"] for item in claims]
    if len(set(identifiers)) != len(identifiers):
        raise KernelError("CANON_SUPPORT_CLAIM_SET_INVALID", "Frozen extraction identifiers must be unique")
    result = deepcopy(schema)
    values = result["properties"]["claims"]
    values.update(minItems=len(identifiers), maxItems=len(identifiers))
    if identifiers:
        values["items"]["properties"]["claim_id"] = {"type": "string", "enum": identifiers}
    return result


def coverage_partition(extraction, review):
    claims = {item["claim"]["grounded_claim_id"]: item for item in grounded_claims(extraction)}
    values = review.get("claims")
    if review.get("coverage") != "COMPLETE" or not isinstance(values, list) or not claims:
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Retain a complete declared review of a nonempty extraction")
    if any(not isinstance(item, dict) or not isinstance(item.get("claim_id"), str) for item in values):
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Malformed assessments retain their validation owner")
    counts = Counter(item["claim_id"] for item in values)
    retained = []
    for item in values:
        if item["claim_id"] not in claims:
            continue
        claim = claims[item["claim_id"]]["claim"]
        if (item.get("assessment") != "SUPPORTED" or item.get("observed_kind") != claim["claim_kind"]
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_REQUIRED", "Coverage recovery cannot erase a known semantic disagreement")
        if counts[item["claim_id"]] == 1:
            retained.append(deepcopy(item))
    resolved = {item["claim_id"] for item in retained}
    missing = [deepcopy(item) for key, item in claims.items() if key not in resolved]
    if not retained or not missing:
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Require both retained independent assessments and unresolved exact claims")
    return {"retained_assessments": retained, "unresolved_claims": missing,
            "unassigned_claim_ids": sorted(set(counts)-set(claims)),
            "duplicate_claim_ids": sorted(key for key, count in counts.items() if count > 1)}


def combine_review(extraction, prior, fresh):
    partition = coverage_partition(extraction, prior)
    expected = {item["claim"]["grounded_claim_id"] for item in partition["unresolved_claims"]}
    values = fresh.get("claims")
    if (fresh.get("coverage") != "COMPLETE" or not isinstance(values, list)
            or any(not isinstance(item, dict) for item in values) or len(values) != len(expected)
            or {item.get("claim_id") for item in values} != expected):
        raise KernelError("CANON_GROUNDING_INVALID", "Fresh support must cover each unresolved exact claim once")
    return {"coverage": "COMPLETE", "no_change_supported": False,
            "claims": partition["retained_assessments"] + deepcopy(values)}


def retained_support_output(cursor, source, *, semantic_reextraction=False):
    from .model_effects import ModelProviderResult
    from novel_forge.modules.command_kernel.step_successor import has_candidate_domain_outputs
    from novel_forge.modules.production_execution.execution_template import verify_template_provenance

    op = source["operation_id"]
    if (source["definition_name"] != "chapter.canon.propose_changes" or source["definition_version"] != "3.9.8"
            or source["status"] != "FAILED_FINAL" or has_candidate_domain_outputs(cursor, op)):
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Require non-producing terminal legacy support")
    cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number", [op])
    attempts = [row[0] for row in cursor.fetchall()]
    if (len(attempts) != 1 or attempts[0]["status"] != "FAILED_FINAL"
            or attempts[0]["result"].get("error_code") != "CANON_GROUNDING_INVALID"
            or "every extracted claim exactly once" not in attempts[0]["result"].get("error_message", "")):
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Retain the exact full-set coverage diagnostic")
    cursor.execute("""SELECT e.external_effect_id,e.request_hash,e.request_payload,r.evidence,d.dispatch_id,receipt.payload->'evidence',e.status,r.status,r.accounting_basis
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id) JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE e.operation_id=%s AND e.effect_type='model.invoke' ORDER BY receipt.received_at""", [op])
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0][6:] != ("SUCCEEDED", "SETTLED", "ACCOUNT_ENTITLEMENT"):
        raise KernelError("CANON_SUPPORT_COVERAGE_UNSETTLED", "Unknown or unrelated outcomes retain their recovery owner")
    effect, request_hash, payload, budget, dispatch, receipt, *_ = rows[0]
    decision = payload.get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {})
    template = verify_template_provenance(cursor, decision)
    if (not template or template["mode"] != "CREATIVE_VALIDATION" or template["require_literary_qualification"]
            or payload["_production_execution"].get("attempt_id") != attempts[0]["attempt_id"]
            or decision.get("task", {}).get("operation_id") != op
            or decision.get("selected", {}).get("candidate", {}).get("authorization_ref") != budget.get("cost_authorization_ref")):
        raise KernelError("CANON_SUPPORT_COVERAGE_AUTHORIZATION_INVALID", "Require the original authorized creative membership receipt")
    assets = {}
    for binding in source["input_asset_snapshot"]:
        cursor.execute("SELECT a.asset_type,v.content,v.content_hash FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s", [binding["asset_version_id"], source["project_id"]])
        row = cursor.fetchone()
        if not row or row[2] != binding["content_hash"] or row[0] in assets:
            raise KernelError("CANON_SUPPORT_COVERAGE_INPUT_DRIFT", "Require uniquely typed immutable source inputs")
        assets[row[0]] = (binding["asset_version_id"], row[1])
    extraction_id, extraction = assets["canon_extraction"]
    target, revision = assets["best_draft_candidate"]
    raw = ModelProviderResult.from_evidence(receipt).output
    try:
        validate_support_review(extraction=extraction, revision=revision, revision_asset_version_id=target, result=raw)
    except KernelError as error:
        if error.code != "CANON_GROUNDING_INVALID" or "every extracted claim exactly once" not in error.message:
            raise
    else:
        raise KernelError("CANON_SUPPORT_COVERAGE_NOT_APPLICABLE", "Do not regenerate valid completed support")
    if semantic_reextraction:
        by_id = {item["claim"]["grounded_claim_id"]: item for item in grounded_claims(extraction)}
        counts = Counter(item["claim_id"] for item in raw["claims"])
        negative = [
            {"field": by_id[item["claim_id"]]["field"], "claim": by_id[item["claim_id"]]["claim"], "assessment": item}
            for item in raw["claims"] if item["claim_id"] in by_id and counts[item["claim_id"]] == 1
            and (item["assessment"] != "SUPPORTED" or item["observed_kind"] != by_id[item["claim_id"]]["claim"]["claim_kind"])
        ]
        if not negative:
            raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_NOT_APPLICABLE", "Require a real uniquely identified independent disagreement")
        partition = {"negative_assessments": negative, "unassigned_claim_ids": sorted(set(counts)-set(by_id)),
                     "semantic_assessments_reused_as_pass": False}
    else:
        partition = coverage_partition(extraction, raw)
    proof = {"contract_version": CONTRACT, "source_operation_id": op, "source_attempt": attempts[0],
             "source_effect_id": effect, "source_request_hash": request_hash, "source_dispatch_id": dispatch,
             "cost_authorization_ref": budget["cost_authorization_ref"], "source_output_hash": snapshot_hash(raw),
             "source_input_snapshot": source["input_asset_snapshot"], "target_asset_version_id": target,
             "extraction_asset_version_id": extraction_id, "claim_set_hash": snapshot_hash(grounded_claims(extraction)),
             "book_id": template["book_id"], **partition, "provider_invoked": True, "known_failed_effects": [],
             "strict_certification_eligible": False, "identifier_correction": "NOT_RUN_UNASSIGNED"}
    if not semantic_reextraction:
        return proof, raw
    cursor.execute("SELECT to_jsonb(o) FROM authority_operation o JOIN authority_operation_output_asset output USING(operation_id) WHERE output.asset_version_id=%s AND output.role='primary'", [extraction_id])
    canonical = cursor.fetchone()[0]
    if canonical["definition_version"] != "3.9.22" or canonical["status"] != "SUCCEEDED" or canonical["root_operation_id"] != source["root_operation_id"] or canonical["actor_id"] != source["actor_id"]:
        raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_INPUT_DRIFT", "Retain the completed native extraction and original actor")
    cursor.execute("""SELECT e.external_effect_id,e.request_hash,receipt.payload->'evidence',r.accounting_basis,r.status,e.status,r.evidence->>'cost_authorization_ref',e.request_payload #>> '{_production_execution,attempt_id}'
        FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id)
        JOIN authority_external_effect_dispatch d USING(external_effect_id) JOIN authority_external_receipt receipt USING(dispatch_id)
        WHERE e.operation_id=%s ORDER BY receipt.received_at""", [canonical["operation_id"]])
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0][3:7] != ("ACCOUNT_ENTITLEMENT", "SETTLED", "SUCCEEDED", budget["cost_authorization_ref"]):
        raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_UNSETTLED", "Retain one exact successful extraction receipt")
    cursor.execute("SELECT status FROM authority_attempt WHERE attempt_id=%s AND operation_id=%s", [rows[0][7], canonical["operation_id"]])
    if cursor.fetchone() != ("SUCCEEDED",):
        raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_UNSETTLED", "Require the successful original extraction Attempt")
    rejected = ModelProviderResult.from_evidence(rows[0][2]).output
    proof.update(contract_version="chapter-canon-support-reextraction.v1", source_review_input_snapshot=source["input_asset_snapshot"],
                 source_input_snapshot=canonical["input_asset_snapshot"], source_extraction_operation_id=canonical["operation_id"],
                 source_extraction_effect_id=rows[0][0], source_extraction_request_hash=rows[0][1], source_extraction_output_hash=snapshot_hash(rejected))
    return proof, rejected


def retained_review(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT as GRAPH

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    if proof.get("contract_version") != CONTRACT:
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute("SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id,o.idempotency_key,root.idempotency_key FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id JOIN authority_operation root ON root.operation_id=j.successor_root_operation_id WHERE o.operation_id=%s AND j.contract_version=%s", [request.operation_id, GRAPH])
        row = c.fetchone()
        if row and row[4] != row[5]+":canon_proposal:quality-correction:1":
            return None
        if not row or row[0] != binding or row[2] != proof["source_input_snapshot"] or row[3] != row[1]["root"]["actor_id"]:
            raise KernelError("CANON_SUPPORT_COVERAGE_BINDING_INVALID", "Require exact native continuation, actor and frozen inputs")
        c.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [proof["source_operation_id"]])
        actual, raw = retained_support_output(c, c.fetchone()[0])
        if actual != proof:
            raise KernelError("CANON_SUPPORT_COVERAGE_RECEIPT_DRIFT", "Preserve the exact failed receipt and partition")
    return proof, raw


def reextraction_feedback(request):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT as GRAPH
    from novel_forge.modules.canon_graph.domain import PROVIDER_SEMANTIC_CHANGE_FIELDS

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    if proof.get("contract_version") != "chapter-canon-support-reextraction.v1":
        return None
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute("SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id,o.idempotency_key,root.idempotency_key FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id JOIN authority_operation root ON root.operation_id=j.successor_root_operation_id WHERE o.operation_id=%s AND j.contract_version=%s", [request.operation_id, GRAPH])
        row = c.fetchone()
        if row and row[4] != row[5]+":canon_extraction:quality-correction:1":
            return None
        if not row or row[0] != binding or row[2] != proof["source_input_snapshot"] or row[3] != row[1]["root"]["actor_id"]:
            raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_BINDING_INVALID", "Require exact native continuation, actor and selected prose")
        c.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [proof["source_operation_id"]])
        actual, rejected = retained_support_output(c, c.fetchone()[0], semantic_reextraction=True)
        if actual != proof:
            raise KernelError("CANON_SUPPORT_SEMANTIC_REPAIR_RECEIPT_DRIFT", "Retain the failed independent review and original extraction")
    fields = {PROVIDER_SEMANTIC_CHANGE_FIELDS[item["field"]] for item in proof["negative_assessments"] if item["field"] in PROVIDER_SEMANTIC_CHANGE_FIELDS}
    return {"contract_version": "canon-support-reextraction-feedback.v1",
            "independent_negative_assessments": proof["negative_assessments"],
            "retained_extraction_hash": proof["source_extraction_output_hash"],
            "rejected_fields": {field: rejected[field] for field in sorted(fields)},
            "unassigned_claim_ids": proof["unassigned_claim_ids"],
            "instructions": "Repair the extraction against unchanged prose and native field kinds using this independent negative evidence. Do not rewrite the review or prose, guess unknown IDs, relabel a check as passed, or omit real changes to evade review. Regenerate a complete grounded extraction; new full independent support is required."}
