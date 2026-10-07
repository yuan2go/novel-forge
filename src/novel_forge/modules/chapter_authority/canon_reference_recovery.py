from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.canon_graph.evidence_localization import localize_provider_quotes
from .canon_quote_references import resolve_references
from .model_effects import ModelProviderResult

CONTRACT = "chapter-canon-reference-resolution-revalidation.v1"


def derive_source(cursor, source, *, raw, inputs, evidence):
    from .handlers import _canon_provider_extraction
    from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates
    from novel_forge.modules.canon_graph.background import attach_background_proposals

    if source["definition_version"] != "3.9.31":
        raise KernelError("CANON_REFERENCE_DERIVATION_NOT_APPLICABLE", "Only the frozen reference host defect may derive a result")
    cursor.execute(
        """SELECT e.request_payload,p.payload->'evidence' FROM authority_external_effect e
        JOIN authority_external_effect_dispatch d USING(external_effect_id)
        JOIN authority_external_receipt p USING(dispatch_id)
        WHERE e.external_effect_id=%s AND d.dispatch_id=%s ORDER BY p.received_at DESC""",
        [evidence["source_effect_id"], evidence["source_dispatch_id"]],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("CANON_REFERENCE_DERIVATION_RECEIPT_INVALID", "Retain one exact successful settled receipt")
    payload, receipt = rows[0]
    from .receipt_recovery import _receipt
    verified = _receipt(cursor, evidence["source_effect_id"], source["project_id"], source_operation_id=source["operation_id"])
    if verified.output != raw:
        raise KernelError("CANON_REFERENCE_DERIVATION_RECEIPT_INVALID", "The exact verified result must match frozen raw output")
    runtime = payload["_production_execution"]["capability_runtime"]
    execution = receipt["production_execution"]
    validation = execution["validation_manifest"]
    target, candidate = inputs["best_draft_candidate"]
    context, context_doc = inputs["context_bundle"]
    if (
        runtime.get("output_schema_ref") != "schema:chapter-provider-output:canon_extraction:v27"
        or validation.get("decision") != "ACCEPTED"
        or validation.get("operation_id") != source["operation_id"]
        or any(check.get("status") != "PASSED" for check in validation.get("checks", []))
        or set(validation.get("required_check_kinds", [])) != {check["check_kind"] for check in validation.get("checks", [])}
        or "output_schema" not in validation.get("required_check_kinds", [])
        or payload["input"]["revision"] != candidate
    ):
        raise KernelError("CANON_REFERENCE_DERIVATION_VALIDATION_INVALID", "Retain the real original Schema, route, fencing and tool validation")
    normalized_ref = execution["output_manifest"]["normalized_output_ref"]
    cursor.execute(
        """SELECT v.content FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        WHERE v.asset_version_id=%s AND a.project_id=%s""",
        [normalized_ref.removeprefix("authority-asset-version:"), source["project_id"]],
    )
    normalized = cursor.fetchone()
    if not normalized or normalized[0].get("payload") != raw:
        raise KernelError("CANON_REFERENCE_DERIVATION_RECEIPT_INVALID", "Do not replace the original normalized Provider result")
    corpus = payload["input"]["canon_quote_references"]
    resolved, resolution = resolve_references(raw, text=candidate["text"], target_asset_version_id=target["asset_version_id"], corpus=corpus)
    legacy = deepcopy(resolved)
    legacy_intervals = []

    def legacy_walk(value, path):
        if isinstance(value, dict):
            if isinstance(value.get("resolution_evidence"), list):
                for index, ref in enumerate(value["resolution_evidence"]):
                    match = re.fullmatch(r"chars:(\d+)-(\d+):(.+)", ref)
                    if not match:
                        raise KernelError("CANON_REFERENCE_DERIVATION_INTERVAL_INVALID", "Require complete native exact reference intervals")
                    value["resolution_evidence"][index] = f"chars:{match[1]}:{match[2]}:{match[3]}"
                    legacy_intervals.append(path + f".resolution_evidence[{index}]")
            for key, child in value.items():
                legacy_walk(child, path + "." + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                legacy_walk(child, path + f"[{index}]")

    legacy_walk(legacy, "$")
    if not legacy_intervals:
        raise KernelError("CANON_REFERENCE_DERIVATION_NOT_APPLICABLE", "Require the actual defective host interval conversion")
    try:
        localize_provider_quotes(legacy, text=candidate["text"], target_asset_version_id=target["asset_version_id"])
    except KernelError as error:
        if error.code != "CANON_QUOTE_LOCALIZATION_INVALID":
            raise
    else:
        raise KernelError("CANON_REFERENCE_DERIVATION_NOT_APPLICABLE", "Reproduce the original host rejection")
    localize_provider_quotes(resolved, text=candidate["text"], target_asset_version_id=target["asset_version_id"])
    result = replace(ModelProviderResult.from_evidence(receipt), output=resolved)
    corrected = extract_grounded_candidates(
        revision=candidate, revision_asset_version_id=target["asset_version_id"],
        project_id=source["project_id"], context_bundle_version_id=context["asset_version_id"],
        provider_extraction=_canon_provider_extraction(result), work_requirements=True,
    )
    corrected = attach_background_proposals(extraction=corrected, binding=dict((context_doc.get("chapter_execution_expectations") or {}).get("world_preparation") or {}))
    corrected["canon_reference_resolution"] = resolution
    return {
        "corrected_content_hash": snapshot_hash(corrected),
        "reference_corpus_hash": snapshot_hash(corpus),
        "normalized_output_ref": normalized_ref,
        "legacy_interval_paths": legacy_intervals,
        "semantic_support": "NOT_RUN",
    }, corrected


def materialize(request):
    if request.definition_version != "3.10.0":
        raise KernelError("RETAINED_RESULT_CURRENT_CONTRACT_REQUIRED", "Derivation requires the explicit current contract")
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.command_kernel.retained_graph import BINDING, CONTRACT as GRAPH
    from .current_quote_recovery import source_graph, asset, receipt

    binding = (request.command.get("preparation_report") or {}).get(BINDING) or {}
    proof = binding.get("retained_result") or {}
    with AuthorityUnitOfWork(request.database_url) as uow:
        c = uow.cursor
        c.execute("SELECT j.policy_evidence,j.source_snapshot,o.input_asset_snapshot,o.actor_id FROM authority_graph_continuation j JOIN authority_operation o ON o.root_operation_id=j.successor_root_operation_id WHERE o.operation_id=%s AND j.contract_version=%s", [request.operation_id, GRAPH])
        row = c.fetchone()
        if not row or row[0] != binding or proof.get("contract_version") != CONTRACT or row[2] != proof["source_input_snapshot"] or row[3] != row[1]["root"]["actor_id"]:
            raise KernelError("CANON_REFERENCE_DERIVATION_BINDING_INVALID", "Require the exact native continuation, actor and frozen inputs")
        actual = source_graph(c, root=row[1]["root"], saga=row[1]["saga"])
        if actual != row[1] or actual["retained_result"] != proof:
            raise KernelError("CANON_REFERENCE_DERIVATION_SOURCE_DRIFT", "Retain the complete original settled graph and result")
        c.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [proof["source_operation_id"]])
        source = c.fetchone()[0]
        inputs = {kind: (item, doc) for item in source["input_asset_snapshot"] for kind, doc in [asset(c, source["project_id"], item)]}
        evidence, raw = receipt(c, source)
        derivation, corrected = derive_source(c, source, raw=raw, inputs=inputs, evidence=evidence)
        if any(proof.get(key) != value for key, value in derivation.items()):
            raise KernelError("CANON_REFERENCE_DERIVATION_RECEIPT_DRIFT", "Retain the exact deterministic host derivation")
    corrected["retained_result_derivation"] = {key: proof[key] for key in ("contract_version", "source_operation_id", "source_effect_id", "source_dispatch_id", "source_output_hash", "source_request_hash", "provider_invoked", "strict_certification_eligible")}
    return corrected
