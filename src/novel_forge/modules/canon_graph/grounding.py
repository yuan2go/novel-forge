from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError

from .domain import PROVIDER_SEMANTIC_CHANGE_FIELDS, extract_canon_candidates

OBSERVATION_FIELDS = ("arc_evidence", "realization_evidence")
FINAL_CANDIDATE_PAYOFF = {"asset_version_id": "$FINAL_CANDIDATE", "event_id": "$CURRENT_CLAIM"}


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fail(message: str) -> None:
    raise KernelError("CANON_GROUNDING_INVALID", message)


def validate_payoff_reference(item: dict[str, Any]) -> None:
    payoff = item.get("payoff_evidence")
    if not payoff and item.get("status") != "FULFILLED":
        return
    if not isinstance(payoff, dict) or not payoff.get("asset_version_id") or not payoff.get("event_id"):
        _fail("fulfilled Narrative Obligation requires typed payoff evidence")
    if item.get("obligation_type") != "CAUSAL_DEBT" and payoff != FINAL_CANDIDATE_PAYOFF:
        _fail("prose payoff requires final-candidate/current-claim references, never Provider-authored Authority IDs")


def _validate_claim(
    item: dict[str, Any], *, field: str, text: str, project_id: str,
    revision_id: str,
) -> None:
    start, end = item.get("evidence_start"), item.get("evidence_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        _fail("evidence requires a nonempty Unicode code-point interval in final prose")
    if item.get("evidence_quote") != text[start:end]:
        _fail("literal evidence quote must match final prose exactly")
    for key, expected in (
        ("source_revision_asset_version_id", revision_id),
        ("source_text_hash", text_hash(text)),
        ("previous_state_project_id", project_id),
    ):
        if key in item and item[key] != expected:
            _fail(f"stale or cross-project grounding: {key}")
    kind = item.get("claim_kind")
    allowed = {
        "character_knowledge_changes": {"KNOWLEDGE_ACQUISITION"},
        "character_belief_changes": {"BELIEF", "SUSPICION", "HEARSAY", "DIALOGUE_ASSERTION"},
        "disclosure_events": {"READER_DISCLOSURE"},
        "arc_evidence": {"NARRATIVE_OBSERVATION"},
        "realization_evidence": {"NARRATIVE_OBSERVATION"},
    }.get(field, {"OBJECTIVE_EVENT", "OBJECTIVE_STATE"})
    if kind not in allowed:
        _fail(f"claim kind {kind!r} cannot authorize {field}")
    if kind == "KNOWLEDGE_ACQUISITION" and not item.get("character_id"):
        _fail("knowledge acquisition requires its specific character")
    if field == "obligation_changes":
        validate_payoff_reference(item)


def _bind_claim_location(item: dict[str, Any], text: str) -> None:
    from novel_forge.modules.review.diagnostics import validate_location

    try:
        location = validate_location(
            {
                "quote": item.get("evidence_quote"),
                **({"start": item["evidence_start"], "end": item["evidence_end"]}
                   if "evidence_start" in item or "evidence_end" in item else {}),
            },
            text,
        )
    except KernelError as error:
        if error.code != "REVIEW_EVIDENCE_INVALID":
            raise
        raise KernelError("CANON_GROUNDING_INVALID", error.message) from error
    item["evidence_start"] = location["start"]
    item["evidence_end"] = location["end"]


def _bind_prose_payoff(item: dict[str, Any]) -> None:
    if item.get("status") != "FULFILLED" or item.get("obligation_type") == "CAUSAL_DEBT":
        return
    if item.get("payoff_evidence") is None:
        item["payoff_evidence"] = dict(FINAL_CANDIDATE_PAYOFF)


def _bind_observation_locations(source: dict[str, Any], text: str) -> None:
    from novel_forge.modules.review.diagnostics import validate_location

    for item in source.get("arc_evidence", []):
        if item.get("observation_status") != "OBSERVED":
            continue
        located = []
        for reference in item.get("resolution_evidence") or []:
            legacy = re.fullmatch(r"chars:(\d+)-(\d+):(.+)", reference)
            if legacy:
                start, end = int(legacy.group(1)), int(legacy.group(2))
                if not 0 <= start < end <= len(text):
                    _fail("Arc evidence points outside final candidate prose")
                location = validate_location({"start": start, "end": end, "quote": text[start:end]}, text)
                located.append((location, reference))
            else:
                location = validate_location({"quote": reference}, text)
                located.append((location, f"chars:{location['start']}-{location['end']}:{reference}"))
        if not located:
            _fail("observed Arc contribution requires final-prose evidence")
        item["resolution_evidence"] = [reference for _, reference in located]
        item.update({"claim_kind": "NARRATIVE_OBSERVATION", "evidence_quote": located[0][0]["quote"],
                     "evidence_start": located[0][0]["start"], "evidence_end": located[0][0]["end"]})
    for item in source.get("realization_evidence", []):
        if item.get("observation_status") != "OBSERVED":
            continue
        located = []
        for evidence in item.get("accepted_prose_evidence") or []:
            if not isinstance(evidence, dict):
                _fail("realization evidence must be structured")
            if "quote" in evidence:
                location = validate_location({"quote": evidence["quote"]}, text)
            else:
                start, end = evidence.get("start"), evidence.get("end")
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                    _fail("realization evidence points outside final candidate prose")
                location = validate_location({"start": start, "end": end, "quote": text[start:end]}, text)
            located.append({"start": location["start"], "end": location["end"], "summary": evidence.get("summary")})
        if not located:
            _fail("observed realization requires final-prose evidence")
        item["accepted_prose_evidence"] = located
        first = located[0]
        item.update({"claim_kind": "NARRATIVE_OBSERVATION", "evidence_quote": text[first["start"]:first["end"]],
                     "evidence_start": first["start"], "evidence_end": first["end"]})


def extract_grounded_candidates(
    *, project_id: str, revision: dict[str, Any], revision_asset_version_id: str,
    context_bundle_version_id: str, provider_extraction: dict[str, Any],
    work_requirements: bool = False,
) -> dict[str, Any]:
    text = revision.get("text")
    if not isinstance(text, str) or not text.strip():
        _fail("final candidate prose is required")
    status = provider_extraction.get("extraction_status")
    if status not in {"EXTRACTED", "NO_CHANGE"}:
        _fail("extraction must explicitly distinguish changes from a successful no-op")
    source = dict(provider_extraction)
    output_schema_ref = str(source.get("provider_output_schema_ref") or "")
    host_binds_prose_payoff = output_schema_ref in {
        "schema:chapter-provider-output:canon_extraction:v20",
        "schema:chapter-provider-output:canon_extraction:v21",
        "schema:chapter-provider-output:canon_extraction:v22",
        "schema:chapter-provider-output:canon_extraction:v23",
        "schema:chapter-provider-output:canon_extraction:v24",
        "schema:chapter-provider-output:canon_extraction:v25",
        "schema:chapter-provider-output:canon_extraction:v26",
    }
    if "facts" in source:
        if "canon_facts" in source:
            _fail("duplicate Canon fact representations")
        source["canon_facts"] = source.pop("facts")
    _bind_observation_locations(source, text)
    count = 0
    for field in PROVIDER_SEMANTIC_CHANGE_FIELDS.values():
        values = source.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            _fail(f"{field} must contain structured claims")
        count += len(values)
        for item in values:
            _bind_claim_location(item, text)
            if field == "obligation_changes" and host_binds_prose_payoff:
                _bind_prose_payoff(item)
            _validate_claim(item, field=field, text=text, project_id=project_id, revision_id=revision_asset_version_id)
    for field in OBSERVATION_FIELDS:
        values = source.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            _fail(f"{field} must contain structured observations")
        for item in values:
            if item.get("observation_status") == "OBSERVED":
                _validate_claim(item, field=field, text=text, project_id=project_id, revision_id=revision_asset_version_id)
                count += 1
    if (status == "EXTRACTED") != bool(count):
        _fail("extraction status disagrees with observed changes")
    if status == "NO_CHANGE" and not str(source.get("no_change_reason") or "").strip():
        _fail("no-op requires an explicit coverage explanation for support review")
    result = extract_canon_candidates(
        project_id=project_id, revision={"chapter": revision["chapter"], "text": text},
        revision_asset_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        provider_extraction=source, work_requirements=work_requirements,
    )
    for field in (*PROVIDER_SEMANTIC_CHANGE_FIELDS, "reader_knowledge_changes", *OBSERVATION_FIELDS):
        for item in result.get(field, []):
            if field in OBSERVATION_FIELDS and item.get("observation_status") != "OBSERVED":
                continue
            if item.get("predicate") == "accepted_revision_digest":
                item["object"] = text_hash(text)
                continue
            start, end = item["evidence_start"], item["evidence_end"]
            item.setdefault("extraction_evidence", {}).update({
                "quote": text[start:end], "excerpt_digest": text_hash(text[start:end]),
                "text_hash": text_hash(text), "offset_unit": "UNICODE_CODE_POINT",
                "span": {"start": start, "end": end},
                "project_id": project_id,
            })
            identity = json.dumps({"field": field, "claim": item, "revision": revision_asset_version_id}, ensure_ascii=False, sort_keys=True)
            item["grounded_claim_id"] = text_hash(identity)
            if field == "obligation_changes" and item.get("payoff_evidence") == FINAL_CANDIDATE_PAYOFF:
                item["payoff_evidence"] = {
                    "asset_version_id": revision_asset_version_id,
                    "event_id": item["grounded_claim_id"],
                    "evidence_mode": "GROUNDED_FINAL_CANDIDATE_CLAIM",
                }
    result["grounding"] = {
        "contract_version": "grounded-canon.v1", "project_id": project_id,
        "candidate_asset_version_id": revision_asset_version_id,
        "context_asset_version_id": context_bundle_version_id,
        "text_hash": text_hash(text), "extraction_status": status,
        "no_change_reason": str(source.get("no_change_reason") or ""),
        "semantic_status": "PENDING_SUPPORT_REVIEW",
    }
    result["canon_extraction_contract_version"] = "canon-grounded-extraction-v2" if work_requirements else "canon-grounded-extraction-v1"
    return result


def grounded_claims(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"field": field, "claim": item}
        for field in (*PROVIDER_SEMANTIC_CHANGE_FIELDS, *OBSERVATION_FIELDS)
        for item in extraction.get(field, []) if item.get("grounded_claim_id")
    ]


def validate_support_review(
    *, extraction: dict[str, Any], revision: dict[str, Any],
    revision_asset_version_id: str, result: dict[str, Any],
) -> dict[str, Any]:
    binding = dict(extraction.get("grounding") or {})
    if (binding.get("contract_version") != "grounded-canon.v1"
        or binding.get("candidate_asset_version_id") != revision_asset_version_id
        or binding.get("text_hash") != text_hash(str(revision.get("text") or ""))):
        _fail("support review must consume the exact extracted final candidate")
    claims = {item["claim"]["grounded_claim_id"]: item["claim"] for item in grounded_claims(extraction)}
    reviews = result.get("claims")
    if (result.get("coverage") != "COMPLETE" or not isinstance(reviews, list)
        or any(not isinstance(item, dict) for item in reviews)
        or len(reviews) != len(claims)
        or {item.get("claim_id") for item in reviews} != set(claims)):
        _fail("semantic support review must account for every extracted claim exactly once")
    for review in reviews:
        claim = claims[review["claim_id"]]
        if (review.get("assessment") != "SUPPORTED"
            or review.get("observed_kind") != claim.get("claim_kind")
            or not str(review.get("reason") or "").strip()):
            raise KernelError("CANON_GROUNDING_REEXTRACTION_REQUIRED", "unsupported or uncertain claim requires repair; a matching span is insufficient")
    if binding["extraction_status"] == "NO_CHANGE" and result.get("no_change_supported") is not True:
        raise KernelError("CANON_GROUNDING_REEXTRACTION_REQUIRED", "empty extraction has not passed semantic coverage review")
    return {
        **binding, "semantic_status": "SUPPORTED_CANDIDATE",
        "support_review": result,
        "claim_set_hash": text_hash(json.dumps(grounded_claims(extraction), ensure_ascii=False, sort_keys=True)),
    }
