from __future__ import annotations

from copy import deepcopy
import json
import re

from novel_forge.modules.command_kernel.errors import KernelError

from .domain import PROVIDER_SEMANTIC_CHANGE_FIELDS
from .grounding import text_hash

CONTRACT = "literal-source-spans.v1"


def source_spans(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise KernelError("CANON_SOURCE_TEXT_REQUIRED", "An exact candidate is required")
    intervals = {(m.start(), m.end()) for m in re.finditer(r"[^\n]+", text)}
    intervals.update((m.start(), m.end()) for m in re.finditer(r"[^。！？\n]+[。！？]?", text) if m.group().strip())
    return {
        "contract_version": CONTRACT,
        "source_text_hash": text_hash(text),
        "spans": [
            {"span_id": f"s{text_hash(text)[7:23]}_{start}_{end}", "start": start, "end": end, "quote": text[start:end]}
            for start, end in sorted(intervals)
        ],
    }


def span_output_schema(schema: dict, table: dict, *, compact: bool = False) -> dict:
    result = deepcopy(schema)
    identity = {"type": "string", "enum": [s["span_id"] for s in table["spans"]]}
    if compact:
        result["$defs"] = {"candidateEvidenceSpan": identity}
        identity = {"$ref": "#/$defs/candidateEvidenceSpan"}
    for array in result["properties"].values():
        if array.get("type") != "array":
            continue
        item = array["items"]
        fields = item["properties"]
        if "evidence_quote" in fields:
            fields.pop("evidence_quote")
            fields["evidence_span_id"] = deepcopy(identity)
            if "observation_status" in fields:
                fields["evidence_span_id"] = {"anyOf": [deepcopy(identity), {"type": "null"}]}
            item["required"] = ["evidence_span_id" if k == "evidence_quote" else k for k in item["required"]]
        if "resolution_evidence" in fields:
            fields["resolution_evidence"]["items"] = deepcopy(identity)
            fields["resolution_evidence"]["description"] = "Select source span IDs for observed contributions; [] for unobserved."
        if "accepted_prose_evidence" in fields:
            location = fields["accepted_prose_evidence"]["items"]
            location["properties"].pop("quote")
            location["properties"]["span_id"] = deepcopy(identity)
            location["required"] = ["span_id" if k == "quote" else k for k in location["required"]]
    return _share_schema_nodes(result) if compact else result


def _share_schema_nodes(schema):
    from collections import Counter
    counts = Counter()
    def children(node):
        yield from node.get("properties", {}).values()
        if isinstance(node.get("items"), dict):
            yield node["items"]
        for key in ("anyOf", "oneOf", "allOf"):
            yield from node.get(key, [])
    def signature(node):
        return json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    def count(node):
        counts[signature(node)] += 1
        for child in children(node):
            count(child)
    for child in children(schema):
        count(child)
    names = {key: f"sharedSchema{index}" for index, key in enumerate(sorted(key for key, count in counts.items() if count > 1 and len(key) >= 120))}
    definitions = deepcopy(schema.get("$defs", {}))
    def project(node, *, define=False):
        key = signature(node)
        if key in names and not define:
            return {"$ref": "#/$defs/" + names[key]}
        result = deepcopy(node)
        if "properties" in node:
            result["properties"] = {name: project(value) for name, value in node["properties"].items()}
        if isinstance(node.get("items"), dict):
            result["items"] = project(node["items"])
        for name in ("anyOf", "oneOf", "allOf"):
            if name in node:
                result[name] = [project(value) for value in node[name]]
        return result
    result = project(schema, define=True)
    definitions.update({name: project(json.loads(key), define=True) for key, name in names.items()})
    result["$defs"] = definitions
    return result


def extraction_diagnostics(extraction: dict, text: str, *, agency: bool) -> list:
    from novel_forge.modules.chapter_authority.provider_output_contracts import collect_native_world_schema_diagnostics
    from novel_forge.modules.worldbuilding.production_schema import world_transition_schema
    defects = []
    for field in (*PROVIDER_SEMANTIC_CHANGE_FIELDS.values(), "arc_evidence", "realization_evidence"):
        for index, item in enumerate(extraction.get(field, [])):
            path = f"$.{field}[{index}]"
            quotes = [(path + ".evidence_quote", item.get("evidence_quote"))]
            quotes.extend((path + f".resolution_evidence[{j}]", quote) for j, quote in enumerate(item.get("resolution_evidence", [])))
            quotes.extend((path + f".accepted_prose_evidence[{j}].quote", location.get("quote")) for j, location in enumerate(item.get("accepted_prose_evidence", [])))
            for location, quote in quotes:
                if quote is not None and (not isinstance(quote, str) or quote not in text):
                    defects.append({"field_path": location, "constraint": "literal evidence absent from exact candidate", "actual": quote})
            if item.get("world_transition"):
                try:
                    transition = json.loads(item["world_transition"]["payload_json"])
                except (ValueError, KeyError, TypeError):
                    defects.append({"field_path": path + ".world_transition", "constraint": "valid typed JSON required"})
                else:
                    defects.extend(collect_native_world_schema_diagnostics(world_transition_schema(agency=agency), transition, path=path + ".world_transition"))
    return defects


def bind_source_spans(extraction: dict, text: str) -> dict:
    result = deepcopy(extraction)
    table = source_spans(text)
    spans = {s["span_id"]: s for s in table["spans"]}
    defects = []

    def locate(identity, path):
        if not isinstance(identity, str) or identity not in spans:
            defects.append({"field_path": path, "constraint": "span must belong to exact candidate", "actual": identity})
            return None
        return spans[identity]

    for field in (*PROVIDER_SEMANTIC_CHANGE_FIELDS.values(), "arc_evidence", "realization_evidence"):
        for index, item in enumerate(result.get(field, [])):
            path = f"$.{field}[{index}]"
            observed = item.get("observation_status", "OBSERVED") == "OBSERVED"
            identity = item.pop("evidence_span_id", None)
            span = locate(identity, path + ".evidence_span_id") if observed else None
            if not observed and identity is not None:
                defects.append({"field_path": path, "constraint": "unobserved item cannot assert prose evidence"})
            if span:
                item.update(evidence_quote=span["quote"], evidence_start=span["start"], evidence_end=span["end"])
            for j, identity in enumerate(item.get("resolution_evidence", [])):
                located = locate(identity, path + f".resolution_evidence[{j}]")
                if located:
                    item["resolution_evidence"][j] = f"chars:{located['start']}-{located['end']}:{located['quote']}"
            for j, location in enumerate(item.get("accepted_prose_evidence", [])):
                located = locate(location.pop("span_id", None), path + f".accepted_prose_evidence[{j}].span_id")
                if located:
                    location.update(start=located["start"], end=located["end"])
    if defects:
        raise KernelError("CANON_SOURCE_SPAN_INVALID", str(defects))
    result["source_span_binding"] = {"contract_version": CONTRACT, "source_text_hash": table["source_text_hash"]}
    return result
