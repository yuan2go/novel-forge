from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.canon_graph.grounding import grounded_claims, text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash

PROTOCOL = "canon-support-independent-reference.v1"
NO_CHANGE = "canon_no_change"


def reference_dimensions(extraction: Mapping[str, Any]) -> tuple[str, ...]:
    claims = grounded_claims(dict(extraction))
    dimensions = tuple("canon_support:" + row["claim"]["grounded_claim_id"] for row in claims)
    status = (extraction.get("grounding") or {}).get("extraction_status")
    if status == "NO_CHANGE" and not dimensions:
        return (NO_CHANGE,)
    if status != "EXTRACTED" or not dimensions or len(set(dimensions)) != len(dimensions):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "support references require an exact grounded claim set")
    return dimensions


def validate_sample_result(extraction: Mapping[str, Any], revision: Mapping[str, Any], revision_id: str,
                           result: Mapping[str, Any], *, output_schema: Mapping[str, Any] | None = None,
                           realization_comparison: Mapping[str, Any] | None = None) -> None:
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_schema

    if output_schema is None:
        validate_chapter_provider_output_schema("canon_support", dict(result))
    else:
        from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
        validate_chapter_provider_output_against_schema("canon_support", output_schema, dict(result))
    binding = extraction.get("grounding") or {}
    if (binding.get("contract_version") != "grounded-canon.v1"
        or binding.get("candidate_asset_version_id") != revision_id
        or binding.get("text_hash") != text_hash(str(revision.get("text") or ""))):
        raise KernelError("CANON_GROUNDING_INVALID", "support sample requires its exact extracted prose")
    expected = {row["claim"]["grounded_claim_id"] for row in grounded_claims(dict(extraction))}
    if (result.get("coverage") != "COMPLETE" or len(result["claims"]) != len(expected)
        or {row["claim_id"] for row in result["claims"]} != expected):
        raise KernelError("CANON_GROUNDING_INVALID", "support sample must assess every claim exactly once")
    if realization_comparison is not None:
        from novel_forge.modules.canon_graph.realization_comparison import validate_comparisons
        validate_comparisons(inputs=dict(realization_comparison), result=dict(result),
            revision_asset_version_id=revision_id, text=str(revision.get("text") or ""))
    elif "realization_comparisons" in result:
        raise KernelError("REALIZATION_COMPARISON_COVERAGE_INVALID", "Comparison sample requires its frozen planned events")
    reference_dimensions(extraction)


def observed_dimensions(reference: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    claims = reference["canon_support_claim_kinds"]
    if (result.get("coverage") != "COMPLETE" or not isinstance(result.get("claims"), list)
        or len(result["claims"]) != len(claims) or {row.get("claim_id") for row in result["claims"]} != set(claims)):
        raise KernelError("QUALITY_REFERENCE_RESULT_INVALID", "support result differs from exact reference claims")
    statuses = {"SUPPORTED": "PASSED", "UNSUPPORTED": "FAILED", "UNCERTAIN": "INSUFFICIENT_EVIDENCE"}
    result_dimensions = {}
    for row in result["claims"]:
        status = statuses.get(row.get("assessment"))
        if status is None or not str(row.get("reason") or "").strip():
            raise KernelError("QUALITY_REFERENCE_RESULT_INVALID", "support assessment requires a typed explained judgment")
        if status == "PASSED" and row.get("observed_kind") != claims[row["claim_id"]]:
            status = "FAILED"
        result_dimensions["canon_support:" + row["claim_id"]] = {"gate_status": status, "score": None}
    if not claims:
        if type(result.get("no_change_supported")) is not bool:
            raise KernelError("QUALITY_REFERENCE_RESULT_INVALID", "no-change coverage requires an explicit judgment")
        result_dimensions[NO_CHANGE] = {"gate_status": "PASSED" if result["no_change_supported"] else "FAILED", "score": None}
    return result_dimensions


def source_contract(cursor: Any, *, project_id: str, input_versions: list[dict[str, Any]]) -> dict[str, Any]:
    cursor.execute("""SELECT version.asset_version_id,version.content_hash,version.content,operation.actor_id
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        JOIN authority_operation_output_asset output ON output.asset_version_id=version.asset_version_id
          AND output.content_hash=version.content_hash
        JOIN authority_operation operation USING(operation_id)
        WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s) AND asset.asset_type='canon_extraction'
          AND version.lifecycle='ACTIVE' AND version.governance='CLEAR' AND version.eligibility='ELIGIBLE'
          AND operation.project_id=asset.project_id AND operation.definition_name='chapter.canon.extract'
          AND operation.status='SUCCEEDED'""", [project_id, [row["asset_version_id"] for row in input_versions]])
    targets = cursor.fetchall()
    if len(targets) != 1:
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "support references require the exact native extraction")
    target_id, digest, extraction, actor = targets[0]
    if digest != authorization_hash(extraction) or not any(row["asset_version_id"] == target_id and row["content_hash"] == digest for row in input_versions):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "support reference extraction differs from frozen inputs")
    grounding = extraction.get("grounding") or {}
    revision_id = grounding.get("candidate_asset_version_id")
    cursor.execute("""SELECT version.content,version.content_hash,ARRAY(SELECT operation.actor_id
        FROM authority_operation_output_asset output JOIN authority_operation operation USING(operation_id)
        WHERE output.asset_version_id=version.asset_version_id AND operation.project_id=asset.project_id)
        FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
        WHERE asset.project_id=%s AND version.asset_version_id=%s AND asset.asset_type='best_draft_candidate'
          AND version.governance='CLEAR' AND version.lifecycle='ACTIVE'""", [project_id, revision_id])
    revision = cursor.fetchone()
    if (grounding.get("contract_version") != "grounded-canon.v1" or not revision or not revision[2] or revision[1] != authorization_hash(revision[0])
        or grounding.get("text_hash") != text_hash(str(revision[0].get("text") or ""))
        or not any(row["asset_version_id"] == revision_id and row["content_hash"] == revision[1] for row in input_versions)):
        raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "support reference must include exact native extracted prose")
    claims = grounded_claims(extraction)
    return {"protocol_version": PROTOCOL, "evaluation_version": PROTOCOL, "dimensions": list(reference_dimensions(extraction)),
        "target_asset_version_id": target_id, "target_content_hash": digest, "source_asset_version_id": revision_id,
        "source_content_hash": revision[1], "source_text": revision[0]["text"], "extraction": extraction,
        "claims": claims, "excluded_generator_actor_ids": sorted({actor, *revision[2]}),
        "allowed_statuses": ["PASSED", "FAILED", "INSUFFICIENT_EVIDENCE"],
        "minimum_independent_blind_humans": 2, "distinct_adjudicator_required": True,
        "evidence_fields": ["claim_id", "source_asset_version_id", "start", "end", "quote", "rationale"],
        "no_change_claim_id": "$NO_CHANGE", "metric": "REFERENCE_AGREEMENT.v1", "risk": "HIGH"}


def sample_identity(extraction: Mapping[str, Any], *, text: str) -> str:
    claims = grounded_claims(dict(extraction))
    ephemeral = {extraction["grounding"]["candidate_asset_version_id"], *(row["claim"]["grounded_claim_id"] for row in claims)}

    def normalized(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()
                if key not in {"grounded_claim_id", "project_id", "previous_state_project_id", "source_revision_asset_version_id", "source_text_hash"}}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return "$SOURCE_IDENTITY" if isinstance(value, str) and value in ephemeral else value

    return authorization_hash({"task_type": "canon_support", "text": " ".join(text.split()),
        "claims": sorted((normalized(row) for row in claims), key=authorization_hash),
        "extraction_status": extraction["grounding"]["extraction_status"]})


def require_reference(cursor: Any, *, project_id: str, input_versions: list[dict[str, Any]],
                      binding: Mapping[str, Any], evaluator_actor_id: str, chapter: int) -> dict[str, Any]:
    from .reference_sampling import _native_label, require_adjudicated_reference

    if binding.get("protocol_version") != PROTOCOL:
        raise KernelError("QUALITY_REFERENCE_NOT_INDEPENDENT", "Canon support requires its explicit independent protocol")
    contract = source_contract(cursor, project_id=project_id, input_versions=input_versions)
    target_id, digest = contract["target_asset_version_id"], contract["target_content_hash"]
    extraction, revision_id = contract["extraction"], contract["source_asset_version_id"]
    dimensions = reference_dimensions(extraction)
    reference = require_adjudicated_reference(cursor, project_id=project_id, binding=binding, target_id=target_id,
        target_hash=digest, generators=contract["excluded_generator_actor_ids"], evaluator_actor_id=evaluator_actor_id, chapter=chapter,
        expected_dimensions=dimensions, allowed_statuses={"PASSED", "FAILED", "INSUFFICIENT_EVIDENCE"})
    if any(label["evaluation_version"] != PROTOCOL for label in reference["labels"]):
        raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "support reference evaluation contract differs")
    text = contract["source_text"]
    for label in reference["labels"]:
        adjudication, _, _ = _native_label(cursor, project_id=project_id,
            asset_version_id=label["adjudication_asset_version_id"], asset_type="adjudicated_evaluation",
            operation_name="quality.adjudication.record", actor_field="adjudicator_id")
        for human_id in adjudication["source_human_evaluation_asset_version_ids"]:
            human, _, _ = _native_label(cursor, project_id=project_id, asset_version_id=human_id,
                asset_type="human_evaluation", operation_name="quality.human_evaluation.record", actor_field="evaluator_id")
            if human["dimension"] != label["dimension"]:
                continue
            if not any(valid_located_evidence(row, dimension=label["dimension"], revision_id=revision_id, text=text)
                       for row in human["evidence"]):
                raise KernelError("QUALITY_REFERENCE_PROVENANCE_INVALID", "support labels require exact prose location and claim reasoning")
    return {**reference, "canon_support_claim_kinds": {row["claim"]["grounded_claim_id"]: row["claim"]["claim_kind"]
        for row in grounded_claims(extraction)}, "canon_source_asset_version_id": revision_id,
        "canon_reference_sample_identity": sample_identity(extraction, text=text)}


def valid_located_evidence(row: Mapping[str, Any], *, dimension: str, revision_id: str, text: str) -> bool:
    start, end = row.get("start"), row.get("end")
    return (row.get("claim_id") == ("$NO_CHANGE" if dimension == NO_CHANGE else dimension.removeprefix("canon_support:"))
        and row.get("source_asset_version_id") == revision_id and type(start) is int and type(end) is int
        and 0 <= start < end <= len(text) and row.get("quote") == text[start:end]
        and isinstance(row.get("rationale"), str) and bool(row["rationale"].strip()))
