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


def span_output_schema(schema: dict, table: dict, *, compact: bool = False, span_pattern: bool = False) -> dict:
    result = deepcopy(schema)
    identity = {"type": "string", "enum": [s["span_id"] for s in table["spans"]]}
    if span_pattern:
        identity = {"type": "string", "pattern": "^(?:" + "|".join(re.escape(value) for value in identity["enum"]) + ")$"}
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


def expanded_enum_choices(schema):
    definitions = schema.get("$defs", {})
    def count(node, references=()):
        if isinstance(node, list):
            return sum(count(value, references) for value in node)
        if not isinstance(node, dict):
            return 0
        if "$ref" in node:
            ref = node["$ref"]
            if ref in references or not ref.startswith("#/$defs/") or ref.rsplit("/", 1)[1] not in definitions:
                raise KernelError("CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID", "Bounded local Schema references are required")
            return count(definitions[ref.rsplit("/", 1)[1]], (*references, ref))
        return len(node.get("enum", [])) + sum(count(value, references) for key, value in node.items() if key not in {"$defs", "enum"})
    return count(schema)


def quality_span_schema(schema, table, requirements):
    result = deepcopy(schema)
    row = result["properties"]["dimensions"]["items"]
    location = row["properties"]["evidence_locations"]["items"]
    location["properties"].pop("quote")
    location["properties"]["span_id"] = {"type": "string", "pattern": "^(?:" + "|".join(re.escape(s["span_id"]) for s in table["spans"]) + ")$"}
    location["required"] = ["span_id" if key == "quote" else key for key in location["required"]]
    branches = []
    for dimension, applicability in requirements.items():
        branch = deepcopy(row)
        fields = branch["properties"]
        fields["dimension"] = {"type": "string", "const": dimension}
        if applicability in {"NOT_APPLICABLE", "PROHIBITED"}:
            fields["gate_status"]["enum"] = ["NOT_APPLICABLE"]
            fields["score"] = {"type": "null"}
            fields["evidence_locations"]["maxItems"] = 0
        elif applicability == "UNDETERMINED":
            fields["gate_status"]["enum"] = ["INSUFFICIENT_EVIDENCE"]
            fields["score"] = {"type": "null"}
        else:
            fields["gate_status"]["enum"] = [v for v in fields["gate_status"]["enum"] if v != "NOT_APPLICABLE"]
        branches.append(branch)
    result["properties"]["dimensions"]["items"] = {"anyOf": branches}
    result["properties"]["dimensions"]["minItems"] = len(requirements)
    result["properties"]["dimensions"]["maxItems"] = len(requirements)
    return _share_schema_nodes(result)


def bind_quality_spans(locations, text):
    table = {span["span_id"]: span for span in source_spans(text)["spans"]}
    invalid = [location.get("span_id") for location in locations if location.get("span_id") not in table]
    if invalid:
        raise KernelError("QUALITY_SOURCE_SPAN_INVALID", "Evidence must belong to the exact candidate: " + str(invalid))
    return [{"quote": table[location["span_id"]]["quote"], "claim": location["claim"]} for location in locations]


def require_quality_dimensions(rows, expected):
    dimensions = [row.get("dimension") for row in rows]
    if len(dimensions) != len(expected) or set(dimensions) != set(expected):
        raise KernelError("QUALITY_DIMENSION_COVERAGE_INVALID", "Each frozen dimension must occur exactly once")


def constrain_transition_preconditions(schema, baselines):
    from .domain import SEMANTIC_CHANGE_FIELDS
    result = deepcopy(schema)
    for field, kind in SEMANTIC_CHANGE_FIELDS.items():
        if field not in result["properties"]:
            continue
        properties = result["properties"][field]["items"].get("properties", {})
        for predecessor, current in (("from_status", "status"), ("from_state", "state"),
                ("from_stance", "stance"), ("from_stage", "stage"), ("from_tier", "tier")):
            if predecessor in properties:
                values = [None, *dict.fromkeys(row[current] for row in baselines.get(kind, []) if current in row)]
                properties[predecessor]["enum"] = values
    return result


def constrain_planned_character_results(schema, transitions):
    result = deepcopy(schema)
    expected = {}
    for transition in transitions:
        if transition.get("state_kind") == "character_state":
            identity, state = transition.get("entity_key"), transition.get("to_state")
            if not isinstance(identity, str) or not identity or not isinstance(state, str) or not state:
                raise KernelError("CANON_PLANNED_RESULT_INVALID", "An exact entity and canonical result are required")
            expected.setdefault(identity, []).append(state)
    if not expected:
        return result
    array = result["properties"]["character_state_changes"]
    while "$ref" in array:
        array = result["$defs"][array["$ref"].rsplit("/", 1)[1]]
    result["properties"]["character_state_changes"] = deepcopy(array)
    row = array["items"]
    while "$ref" in row:
        row = result["$defs"][row["$ref"].rsplit("/", 1)[1]]
    branches = []
    for identity, states in sorted(expected.items()):
        branch = deepcopy(row)
        branch["properties"]["character_id"] = {"type": "string", "const": identity}
        branch["properties"]["state"] = {"type": "string", "enum": list(dict.fromkeys(states))}
        branches.append(branch)
    other = deepcopy(row)
    other["properties"]["character_id"] = {"type": "string", "pattern": "^(?!(?:" + "|".join(re.escape(identity) for identity in sorted(expected)) + ")$).+$"}
    result["properties"]["character_state_changes"]["items"] = {"anyOf": [*branches, other]}
    return result


def bind_quality_applicability_spans(schema, table):
    result = deepcopy(schema)
    rows = result["properties"]["dimensions"]["items"].get("anyOf")
    if not rows:
        raise KernelError("QUALITY_SOURCE_SPAN_INVALID", "Exact frozen dimension applicability is required")
    identity = {"type": "string", "enum": [span["span_id"] for span in table["spans"]]}
    for row in rows:
        fields = row["properties"]
        location = fields["evidence_locations"]["items"]
        location["properties"].pop("quote")
        location["properties"]["span_id"] = deepcopy(identity)
        location["required"] = ["span_id" if key == "quote" else key for key in location["required"]]
        statuses = fields["gate_status"]["enum"]
        if statuses == ["NOT_APPLICABLE"]:
            fields["score"] = {"type": "null"}
            fields["evidence_locations"]["maxItems"] = 0
        elif statuses == ["INSUFFICIENT_EVIDENCE"]:
            fields["score"] = {"type": "null"}
    return _share_schema_nodes(result)


def project_transition_preconditions(baselines):
    fields = {"asset_version_id", "source_event_id", "entity_key", "entity_version",
        "character_id", "source_id", "target_id", "fact_id", "proposition_id", "obligation_id",
        "thread_id", "promise_id", "rule_id", "entity_id", "arc_id", "status", "state", "stance", "stage", "tier"}
    result = {}
    for kind, rows in baselines.items():
        projected = []
        for row in rows:
            state = row["state"] if isinstance(row.get("state"), dict) else row
            for key in ("status", "state", "stance", "stage", "tier"):
                if state.get(key) is not None and not isinstance(state[key], str):
                    raise KernelError("CANON_ACCEPTED_PRECONDITION_INVALID", f"{kind}.{key} requires an accepted scalar")
            scalars = {key: deepcopy(value) for key, value in state.items()
                if key in fields and (value is None or type(value) in {str, int, float, bool})}
            projected.append({**{key: deepcopy(row[key]) for key in fields & row.keys()
                if key not in {"state", "status", "stance", "stage", "tier"}}, **scalars})
        result[kind] = projected
    return result
