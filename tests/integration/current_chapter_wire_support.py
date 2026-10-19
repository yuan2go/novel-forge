"""Exact current wire projection for scripted Chapter evidence."""

from copy import deepcopy
import json

from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response


def current_chapter_fixture_response(stage, inputs, *, json_envelope=True):
    return current_chapter_wire_result(stage, inputs, default_chapter_fixture_response(stage, inputs), json_envelope=json_envelope)


def current_chapter_wire_result(stage, inputs, result, *, json_envelope=True):
    table = inputs.get("source_span_table") or {}
    current_canon = stage == "canon_extraction" and inputs.get("canon_context_projection") == "canon-source-context.v1"
    current_quality = stage.startswith("quality_") and inputs.get("quality_span_contract") == "literal-source-spans.v1"
    if not (current_canon or current_quality):
        return result
    if table.get("contract_version") != "literal-source-spans.v1":
        raise ValueError("current Chapter fixture requires its exact frozen source span table")
    value = deepcopy(json.loads(result["payload_json"]) if current_canon and set(result) == {"payload_json"} else result)
    text = inputs["revision"]["text"]

    def existing_span(identity):
        matches = [span for span in table["spans"] if span["span_id"] == identity
                   and span["quote"] == text[span["start"]:span["end"]]]
        if len(matches) != 1:
            raise ValueError("current Chapter fixture span must belong to its exact frozen candidate")
        return identity

    def span_id(location):
        quote = location.get("quote")
        if quote is None:
            start, end = location.get("start"), location.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
                raise ValueError("current Chapter fixture requires literal evidence in its original candidate")
            quote = text[start:end]
        start, end = location.get("start"), location.get("end")
        anchored = isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)
        if anchored and text[start:end] != quote:
            raise ValueError("current Chapter fixture evidence changed at its original source location")
        matches = [span for span in table["spans"]
                   if isinstance(quote, str) and quote and quote in span["quote"]
                   and span["quote"] == text[span["start"]:span["end"]]
                   and (not anchored or span["start"] <= start < end <= span["end"])]
        if not matches:
            raise ValueError("current Chapter fixture cannot invent a span for absent evidence")
        return min(matches, key=lambda span: (len(span["quote"]), span["start"]))["span_id"]

    if current_canon:
        from novel_forge.modules.canon_graph.domain import PROVIDER_SEMANTIC_CHANGE_FIELDS

        for field in (*PROVIDER_SEMANTIC_CHANGE_FIELDS.values(), "arc_evidence", "realization_evidence"):
            for claim in value.get(field, []):
                if "evidence_span_id" in claim:
                    if any(key in claim for key in ("evidence_quote", "evidence_start", "evidence_end")):
                        raise ValueError("current Chapter fixture cannot mix span and coordinate evidence")
                    if claim.get("observation_status") == "NOT_OBSERVED":
                        if claim["evidence_span_id"] is not None:
                            raise ValueError("unobserved fixture claim cannot assert a source span")
                    else:
                        existing_span(claim["evidence_span_id"])
                else:
                    quote = claim.pop("evidence_quote", None)
                    start, end = claim.pop("evidence_start", None), claim.pop("evidence_end", None)
                    claim["evidence_span_id"] = (
                        None if claim.get("observation_status") == "NOT_OBSERVED"
                        else span_id({"quote": quote, "start": start, "end": end})
                    )
                if "resolution_evidence" in claim:
                    identities = {span["span_id"] for span in table["spans"]}
                    claim["resolution_evidence"] = [existing_span(quote) if quote in identities else span_id({"quote": quote}) for quote in claim["resolution_evidence"]]
                for location in claim.get("accepted_prose_evidence", []):
                    identity = existing_span(location["span_id"]) if "span_id" in location else span_id(location)
                    location.pop("quote", None)
                    location.pop("start", None)
                    location.pop("end", None)
                    location["span_id"] = identity
        if json_envelope:
            value = {"payload_json": json.dumps(value, ensure_ascii=False)}
    else:
        requirements = inputs["quality_context"]["creative_baseline"].get("method_requirements", {})
        for row in value["dimensions"]:
            status = requirements.get(row["dimension"], {}).get("status")
            if status in {"NOT_APPLICABLE", "PROHIBITED"}:
                row.update(gate_status="NOT_APPLICABLE", score=None, evidence_locations=[])
                continue
            if status == "UNDETERMINED":
                row.update(gate_status="INSUFFICIENT_EVIDENCE", score=None)
            row["evidence_locations"] = [
                {"span_id": existing_span(location["span_id"]) if "span_id" in location else span_id(location), "claim": location.get("claim") or "Scripted wire evidence only; no literary qualification."}
                for location in row["evidence_locations"]
            ]
    return value
