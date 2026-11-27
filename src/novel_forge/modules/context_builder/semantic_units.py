from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal, DecimalException
import hashlib
import json
import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import FROZEN_COMPRESSION_REQUEST_MAX_UNITS
from novel_forge.modules.narrative_state.reality import narrative_hash


SEMANTIC_CONTRACT = "source-unit-dependency-and-final-composition.v2"
ATTRIBUTION_FIELDS = frozenset({"subject", "speaker", "subject_id", "actor_id", "event_id", "observation_id", "time", "event_time", "perspective", "knowledge_owner", "epistemic_status", "status", "acceptance_status", "conditions", "exceptions", "negated", "cause_refs", "causes", "depends_on", "units", "quantity"})
ATTRIBUTION_FIELDS |= frozenset({"fact_id", "state_id", "unit_ref", "required_fact_ids", "predecessor_event_ids"})
_TEXT_FIELDS = frozenset({"text", "summary", "safe_summary", "claim", "description", "prose"})
_RELATIONS = frozenset({"cause_refs", "causes", "depends_on", "required_fact_ids", "predecessor_event_ids"})
_ALIASES = frozenset({"fact_id", "event_id", "observation_id", "state_id", "unit_ref"})
_RISK = re.compile(r"条件|除非|否则|只有|并非|没有|未曾|听说|以为|相信|读者|次日|翌日|此前|因此|所以|这两|其后|\b(?:unless|if|not|believes?|heard|therefore|before|after|they|it)\b", re.I)
_GAP = "\n\n[此处省略原来源片段；相邻摘录不代表连续事件，省略不表示未发生。]\n\n"


def enabled(task):
    return task.get("semantic_contract") == SEMANTIC_CONTRACT


def decode_json_values(text):
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("DUPLICATE_JSON_FIELD")
            value[key] = child
        return value
    def exact_float(value):
        result = float(value)
        try:
            preserved = Decimal(str(result)) == Decimal(value)
        except DecimalException:
            preserved = False
        if not preserved:
            raise ValueError("JSON_NUMERIC_VALUE_NOT_PRESERVED")
        return result
    def finite(value):
        raise ValueError("JSON_NONFINITE_VALUE")
    try:
        return json.loads(text, object_pairs_hook=unique, parse_float=exact_float, parse_constant=finite), "JSON_VALUES_PRESERVED"
    except (ValueError, TypeError) as error:
        if isinstance(error, (json.JSONDecodeError, TypeError)):
            return None, "PLAIN_TEXT"
        reason = str(error)
        from .source_json import loads
        try:
            loads(text)
        except KernelError as invalid:
            return None, "DUPLICATE_JSON_FIELD" if invalid.code == "CONTEXT_SOURCE_JSON_AMBIGUOUS" else "JSON_NONFINITE_VALUE"
        except (ValueError, TypeError):
            return None, "PLAIN_TEXT"
        return None, reason if reason in {"DUPLICATE_JSON_FIELD", "JSON_NUMERIC_VALUE_NOT_PRESERVED", "JSON_NONFINITE_VALUE"} else "JSON_NUMERIC_VALUE_NOT_PRESERVED"


def _located_json_document(text):
    document, reason = decode_json_values(text)
    if reason == "JSON_NUMERIC_VALUE_NOT_PRESERVED":
        from .source_json import loads
        document = loads(text)
    return document


def sentence_spans(text):
    stack, result, start = [], [], 0
    pairs = {"“": "”", "‘": "’", "「": "」", "『": "』", "（": "）", "(": ")", "[": "]", "【": "】"}
    for index, character in enumerate(text):
        if character in pairs:
            stack.append(pairs[character])
        elif stack and character == stack[-1]:
            stack.pop()
        if (not stack and character in "。！？!?\n" or not stack and character == "." and (index + 1 == len(text) or text[index + 1].isspace())):
            result.append([start, index + 1])
            start = index + 1
    if start < len(text):
        result.append([start, len(text)])
    return result


def excerpt_text(text: str, ranges: list[list[int]]) -> str:
    if ranges == [[0, len(text)]]:
        return text
    result = ""
    previous = 0
    for start, end in ranges:
        if start > previous:
            result += _GAP
        result += text[start:end]
        previous = end
    if previous < len(text):
        result += _GAP
    return result


def _references(value, keys):
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys:
                if isinstance(child, str) and child:
                    result.add(child)
                elif isinstance(child, list):
                    result.update(item for item in child if isinstance(item, str) and item)
            result.update(_references(child, keys))
    elif isinstance(value, list):
        for child in value:
            result.update(_references(child, keys))
    return result


def join_original_fields(document, fields):
    text, positions, previous = "", [], None
    for path, value in fields:
        separator = "\n\n" if previous is not None else ""
        if previous is not None and len(path) >= 3 and path[-3] == "passages" and path[-1] == "text" and previous[:-2] == path[:-2]:
            parent = document
            for part in path[:-2]:
                parent = parent[part]
            before, current = parent[previous[-2]], parent[path[-2]]
            valid = all(type(item.get("start")) is int and type(item.get("end")) is int and
                item["end"] - item["start"] == len(item["text"]) for item in (before, current))
            separator = "" if valid and before["end"] == current["start"] else _GAP
        text += separator
        positions.append((path, len(text), len(text) + len(value)))
        text += value
        previous = path
    return text, positions


def source_units(candidate, task):
    result = []
    document, source_parse = decode_json_values(candidate.safe_summary)

    def append(text, path, *, kind, field="safe_summary", index=None, span=None, attribution=None, required=False, value=None):
        identity = f"text:{index}" if document is None and field == "safe_summary" else "field:" + narrative_hash([field, path, span, index]).split(":")[-1][:24]
        result.append({"unit_id": identity, "text": text, "kind": kind, "field": field,
            "source_path": list(path), "index": index, "source_span": span,
            "order": len(result), "attribution": deepcopy(attribution or {}),
            "required_without_quotes": bool(required or candidate.required or field == "structured_facts"),
            "required": bool(required or candidate.required or field == "structured_facts"),
            "explicit_refs": sorted(_references(value, _RELATIONS)),
            "source_aliases": sorted(_references(value, _ALIASES)),
            "semantic_risk": bool(_RISK.search(text))})

    def paragraphs(text, path, attribution):
        start = 0
        index = 0
        separator = (r"\r?\n(?:[ \t]*\r?\n)*" if enabled(task)
            and task.get("capacity_policy") == "complete-request-capacity.v1" else r"(?:\r?\n)[ \t]*(?:\r?\n)")
        for match in re.finditer(separator, text):
            if start < match.start():
                append(text[start:match.start()], path, kind="SOURCE_PARAGRAPH", index=index,
                    span=[start, match.start()], attribution=attribution, value=attribution)
                index += 1
            start = match.end()
        if start < len(text):
            append(text[start:], path, kind="SOURCE_PARAGRAPH", index=index, span=[start, len(text)], attribution=attribution, value=attribution)

    def visit(value, path=(), attribution=None):
        if isinstance(value, dict):
            attributed = {**(attribution or {}), **{key: deepcopy(child) for key, child in value.items() if key in ATTRIBUTION_FIELDS or key in _ALIASES or key in _RELATIONS}}
            for key, child in value.items():
                if key == "preserve_quotes":
                    append(json.dumps({key: child}, ensure_ascii=False), (*path, key), kind="SOURCE_FIELD", required=True, value=child)
                elif isinstance(child, str) and key in _TEXT_FIELDS:
                    paragraphs(child, (*path, key), attributed)
                elif isinstance(child, (dict, list)) and key not in ATTRIBUTION_FIELDS:
                    visit(child, (*path, key), attributed)
                else:
                    append(json.dumps({key: child}, ensure_ascii=False, separators=(",", ":")), (*path, key), kind="SOURCE_FIELD", attribution=attributed, required=True, value={key: child})
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index), attribution)
        else:
            append(json.dumps(value, ensure_ascii=False), path, kind="SOURCE_FIELD", attribution=attribution, required=True, value=value)

    if source_parse not in {"PLAIN_TEXT", "JSON_VALUES_PRESERVED"}:
        append(candidate.safe_summary, (), kind="OPAQUE_ORIGINAL_JSON", span=[0, len(candidate.safe_summary)], required=True,
            value=_located_json_document(candidate.safe_summary) if source_parse == "JSON_NUMERIC_VALUE_NOT_PRESERVED" else None)
        result[-1]["source_parse_assessment"] = source_parse
    elif isinstance(document, (dict, list)):
        visit(document)
    else:
        paragraphs(candidate.safe_summary, (), {})
    for index, fact in enumerate(candidate.structured_facts):
        if fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY":
            append(json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":")), (index,),
                field="structured_facts", index=index, kind="STATE_OR_CAUSAL_UNIT", required=True,
                attribution={key: deepcopy(value) for key, value in fact.items() if key in ATTRIBUTION_FIELDS}, value=fact)
    for unit in result:
        field_ranges = (candidate.provenance or {}).get("source_field_ranges") or []
        if unit.get("source_span") and field_ranges:
            start, end = unit["source_span"]
            matches = [row for row in field_ranges if row["start"] < end and row["end"] > start]
            unit["source_fields"] = deepcopy(matches)
            if matches and len({narrative_hash(row.get("attribution") or {}) for row in matches}) == 1:
                unit["attribution"].update(deepcopy(matches[0].get("attribution") or {}))
                unit["source_aliases"] = sorted(set(unit["source_aliases"]) | _references(unit["attribution"], _ALIASES))
                unit["explicit_refs"] = sorted(set(unit["explicit_refs"]) | _references(unit["attribution"], _RELATIONS))
            observations = {row["observation_id"]: row for field in matches for row in field.get("located_observations", ())
                if row["range"][0] < end and row["range"][1] > start}
            if observations:
                unit["attribution"]["located_working_observations"] = list(observations.values())
                unit["source_aliases"] = sorted(set(unit["source_aliases"]) | set(observations))
                unit["explicit_refs"] = sorted(set(unit["explicit_refs"]) | {cause for row in observations.values() for cause in row["causes"]})
        if task.get("stage") == "reference_analysis" and re.match(r"^第[0-9一二三四五六七八九十百千万零〇两]+[章回节卷](?:\s|$)", unit["text"].strip()):
            unit.update(required=True, required_without_quotes=True)
    return result


def frozen_plan_dependencies(sources, intent):
    indexed, records = {}, []
    for source in sources:
        for path, content in [((), source.content), (("candidate_payload",), source.content.get("candidate_payload") or {})]:
            for index, event in enumerate(content.get("narrative_event_chain") or ()):
                if not isinstance(event, dict) or not event.get("event_id"):
                    continue
                identity = (source.asset_version_id, path, index)
                records.append((identity, source, event, [*path, "narrative_event_chain", index]))
                indexed.setdefault(event["event_id"], []).append(identity)
    requested = _references(intent, _RELATIONS)
    chosen, pending = set(), list(requested)
    by_identity = {record[0]: record for record in records}
    while pending:
        for identity in indexed.get(pending.pop(), ()):
            if identity not in chosen:
                chosen.add(identity)
                pending.extend(_references(by_identity[identity][2], _RELATIONS))
    result = {}
    seen = set()
    for identity, source, event, path in records:
        event_hash = narrative_hash(event)
        if identity in chosen and (source.asset_version_id, event_hash) not in seen:
            result.setdefault(source.asset_version_id, []).append({"status": "FROZEN_PLAN_NOT_EVENT_ACCEPTANCE",
                "source_field_path": path, "planned_event": deepcopy(event)})
            seen.add((source.asset_version_id, event_hash))
    return result


def _text_fields(candidate, *, all_fields=False):
    document = _located_json_document(candidate.safe_summary)
    if not isinstance(document, (dict, list)):
        return [((), candidate.safe_summary)]
    result = []
    def visit(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "preserve_quotes":
                    continue
                if (all_fields or key in _TEXT_FIELDS) and isinstance(child, str):
                    result.append(((*path, key), child))
                elif isinstance(child, (dict, list)):
                    visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))
    visit(document)
    return result


def protect_quotes(candidates, catalogs, quotes):
    receipts = []
    if not quotes:
        return receipts
    originals = []
    for candidate in candidates:
        narrative = _text_fields(candidate)
        paths = {path for path, _ in narrative}
        field_groups = [narrative, *[[item] for item in _text_fields(candidate, all_fields=True) if item[0] not in paths]]
        for fields in field_groups:
            document = _located_json_document(candidate.safe_summary)
            text, intervals = join_original_fields(document, fields)
            normalized, coordinates = [], []
            index = 0
            while index < len(text):
                crlf = text[index:index + 2] == "\r\n"
                normalized.append("\n" if crlf else text[index])
                coordinates.append(index)
                index += 2 if crlf else 1
            originals.append((candidate, intervals, text, "".join(normalized), coordinates))
    for quote in dict.fromkeys(quotes):
        if not isinstance(quote, str) or not quote:
            raise KernelError("TASK_CONTEXT_PRESERVE_QUOTE_INVALID", "An explicit preserved quotation must contain source text")
        matches = []
        for candidate, intervals, text, normalized, coordinates in originals:
            sought = quote.replace("\r\n", "\n")
            for match in re.finditer(re.escape(sought), normalized):
                low = coordinates[match.start()]
                high = coordinates[match.end()] if match.end() < len(coordinates) else len(text)
                positions = [(path, max(low, start) - start, min(high, end) - start)
                    for path, start, end in intervals if low < end and high > start]
                hits = []
                for unit in catalogs[candidate.asset_version_id]:
                    if unit["kind"] == "OPAQUE_ORIGINAL_JSON":
                        unit["required"] = True
                        hits.append(unit["unit_id"])
                        continue
                    span = unit.get("source_span")
                    if any(tuple(unit["source_path"]) == path and (span is None or span[0] < stop and start < span[1]) for path, start, stop in positions):
                        unit["required"] = True
                        if span:
                            for path, start, stop in positions:
                                if tuple(unit["source_path"]) == path and span[0] < stop and start < span[1]:
                                    unit.setdefault("protected_spans", []).extend([max(start, span[0]), min(stop, span[1])])
                        hits.append(unit["unit_id"])
                if hits:
                    matches.append({"source_asset_version_id": candidate.asset_version_id, "field_positions": [list(positions[0]), list(positions[-1])], "unit_ids": hits})
        if not matches:
            raise KernelError("TASK_CONTEXT_PRESERVE_QUOTE_UNAVAILABLE", "Explicit preserved quotation has no located original source", details={"quote_hash": narrative_hash(quote)})
        receipts.append({"quote_hash": narrative_hash(quote), "resolution": "ALL_EXACT_MATCHES_PROTECTED" if len(matches) > 1 else "UNIQUE_ORIGINAL_MATCH", "matches": matches, "coordinates": "UNICODE_CODEPOINTS_ORIGINAL_NEWLINES"})
    remapped = {}
    for source, units in catalogs.items():
        refined = []
        for unit in units:
            spans = sentence_spans(unit["text"]) if unit.get("protected_spans") and not unit["required_without_quotes"] else [[0, len(unit["text"])]]
            if len(spans) == 1:
                refined.append(unit)
                continue
            required = []
            base = unit["source_span"][0]
            protected = list(zip(unit["protected_spans"][::2], unit["protected_spans"][1::2]))
            blocks = []
            for start, end in spans:
                must_keep = any(low < base + end and high > base + start for low, high in protected)
                if blocks and blocks[-1][2] == must_keep:
                    blocks[-1][1] = end
                else:
                    blocks.append([start, end, must_keep])
            for start, end, must_keep in blocks:
                fragment = {**unit, "unit_id": unit["unit_id"] + f":{start}:{end}", "text": unit["text"][start:end],
                    "source_span": [base + start, base + end], "parent_unit_id": unit["unit_id"],
                    "required": must_keep}
                observations = (unit.get("attribution") or {}).get("located_working_observations") or []
                if observations:
                    visible = [row for row in observations if row["range"][0] < base + end and row["range"][1] > base + start]
                    fragment["attribution"] = {**unit["attribution"], "located_working_observations": visible}
                    fragment["source_aliases"] = sorted((set(unit["source_aliases"]) - {row["observation_id"] for row in observations}) | {row["observation_id"] for row in visible})
                    fragment["explicit_refs"] = sorted((set(unit["explicit_refs"]) - {cause for row in observations for cause in row["causes"]}) | {cause for row in visible for cause in row["causes"]})
                refined.append(fragment)
                if fragment["required"]:
                    required.append(fragment["unit_id"])
            remapped[(source, unit["unit_id"])] = required
        units[:] = [dict(unit, order=index) for index, unit in enumerate(refined)]
    for receipt in receipts:
        for match in receipt["matches"]:
            match["unit_ids"] = [identity for original in match["unit_ids"]
                for identity in remapped.get((match["source_asset_version_id"], original), [original])]
    return receipts


def close_dependencies(units, selected, *, external_refs=()):
    by_id = {unit["unit_id"]: unit for unit in units}
    aliases = {}
    for unit in units:
        for alias in [unit["unit_id"], *unit.get("source_aliases", ())]:
            aliases.setdefault(alias, set()).add(unit["unit_id"])
    chosen = set(selected)
    queue = list(chosen)
    while queue:
        unit = by_id[queue.pop()]
        for reference in unit.get("explicit_refs", ()):
            required = aliases.get(reference, set())
            if not required and reference not in external_refs:
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "A selected source dependency cannot be located", details={"unit_id": unit["unit_id"], "reference": reference})
            for identity in required - chosen:
                chosen.add(identity)
                queue.append(identity)
    return chosen


def close_catalog_dependencies(catalogs, *, external_refs=()):
    aliases = {}
    for source, units in catalogs.items():
        for unit in units:
            for alias in unit.get("source_aliases", ()):
                aliases.setdefault(alias, []).append((source, unit))
    pending = [unit for units in catalogs.values() for unit in units if unit["required"]]
    seen = set()
    while pending:
        unit = pending.pop()
        for reference in unit.get("explicit_refs", ()):
            matches = aliases.get(reference, ())
            if not matches and reference not in external_refs:
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "A necessary original dependency is unavailable", details={"reference": reference})
            for source, dependency in matches:
                identity = (source, dependency["unit_id"])
                dependency["required"] = True
                dependency["required_without_quotes"] = True
                if identity not in seen:
                    pending.append(dependency)
                    seen.add(identity)
    return set(aliases) | set(external_refs)


def close_selected_catalog_dependencies(catalogs, selections, *, external_refs=()):
    local = {source: {unit["unit_id"]: unit for unit in units} for source, units in catalogs.items()}
    aliases = {}
    for source, units in catalogs.items():
        for unit in units:
            for alias in unit.get("source_aliases", ()):
                aliases.setdefault(alias, []).append((source, unit["unit_id"]))
    result = {source: set(values) for source, values in selections.items()}
    pending = [(source, identity) for source, values in result.items() for identity in values]
    while pending:
        source, identity = pending.pop()
        for reference in local[source][identity].get("explicit_refs", ()):
            required = [(source, reference)] if reference in local[source] else aliases.get(reference, ())
            if not required and reference not in external_refs:
                raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "Final selected dependency has no located source", details={"source": source, "reference": reference})
            for owner, dependency in required:
                if dependency not in result[owner]:
                    result[owner].add(dependency)
                    pending.append((owner, dependency))
    return result


def protected_dependency_bindings(document, *, excluded_scopes):
    result = []
    def visit(value, path=(), numeric_json=False):
        if path in excluded_scopes:
            return
        if isinstance(value, dict):
            aliases = {child for key, child in value.items() if key in _ALIASES and isinstance(child, str) and child}
            semantic_keys = set(value) & (_TEXT_FIELDS | {"state", "state_deltas", "action", "decision", "resistance", "consequence", "motivation", "condition", "conditions", "preconditions", "exceptions", "predicate", "value", "mutation", "payload", "quantity", "negated", "knowledge_boundary", "from_state", "to_state"})
            if aliases and any(value[key] not in (None, "", [], {}) for key in semantic_keys):
                from .source_json import dumps
                record_hash = narrative_hash(dumps(value)) if numeric_json else narrative_hash(value)
                result.extend({"alias": alias, "original_projection_path": list(path), "record_hash": record_hash,
                    "status": "EXACT_UNCHANGED_PROVIDER_RECORD"} for alias in sorted(aliases))
            for key, child in value.items():
                if key == "safe_summary" and isinstance(child, str):
                    parsed, reason = decode_json_values(child)
                    if reason == "JSON_NUMERIC_VALUE_NOT_PRESERVED":
                        parsed = _located_json_document(child)
                    if isinstance(parsed, (dict, list)):
                        visit(parsed, (*path, key, "$decoded_json"), reason == "JSON_NUMERIC_VALUE_NOT_PRESERVED")
                        continue
                visit(child, (*path, key), numeric_json)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index), numeric_json)
    visit(document)
    return result


def selected_ranges(units, keep, path):
    ranges = []
    previous_order = None
    for unit in units:
        if unit["unit_id"] not in keep or unit["field"] != "safe_summary" or tuple(unit["source_path"]) != tuple(path) or unit.get("source_span") is None:
            continue
        start, end = unit["source_span"]
        if ranges and (previous_order is not None and unit["order"] == previous_order + 1 or ranges[-1][1] == start):
            ranges[-1][1] = end
        else:
            ranges.append([start, end])
        previous_order = unit["order"]
    return ranges


def reconstruct(candidate, units, keep):
    all_ids = {unit["unit_id"] for unit in units}
    if not set(keep) <= all_ids:
        raise KernelError("TASK_CONTEXT_COMPRESSOR_IDENTITY_INVALID", "Unknown original unit in reconstruction")
    mandatory = {unit["unit_id"] for unit in units if unit["required"]}
    if not mandatory <= set(keep):
        raise KernelError("TASK_CONTEXT_REQUIRED_UNIT_MISSING", "Reconstruction cannot omit a required original range or field")
    facts = tuple(candidate.structured_facts[unit["index"]] for unit in units if unit["field"] == "structured_facts" and unit["unit_id"] in keep)
    if set(keep) == all_ids:
        return {"safe_summary": candidate.safe_summary, "structured_facts": list(facts)}
    document, _ = decode_json_values(candidate.safe_summary)
    if not isinstance(document, (dict, list)):
        text = excerpt_text(candidate.safe_summary, selected_ranges(units, keep, ()))
    else:
        document = deepcopy(document)
        for path, original in _text_fields(candidate):
            owner = document
            for part in path[:-1]:
                owner = owner[part]
            owner[path[-1]] = excerpt_text(original, selected_ranges(units, keep, path))
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return {"safe_summary": text, "structured_facts": list(facts)}


def _source_metadata(candidate):
    return {key: value for key, value in asdict(candidate).items()
            if key not in {"asset_version_id", "estimated_tokens", "relevance_score"}}


def exact_deduplicate(candidates):
    candidates, union_receipts = merge_source_ranges(candidates)
    accepted, receipts, owners = [], [], {}
    for candidate in candidates:
        identity = narrative_hash(_source_metadata(candidate))
        index = owners.get(identity)
        if index is None:
            owners[identity] = len(accepted)
            accepted.append(candidate)
        else:
            previous = accepted[index]
            accepted[index] = replace(previous, relevance_score=max(previous.relevance_score, candidate.relevance_score))
            receipts.append({"asset_version_id": candidate.asset_version_id, "retained_asset_version_id": previous.asset_version_id,
                "reason": "IDENTICAL_VERSION_SCOPE_CONTENT_AND_ATTRIBUTION", "identity_hash": identity,
                "relevance_policy": "MAX_IDENTICAL_SCOPE", "retained_relevance_score": accepted[index].relevance_score})
    return accepted, [*union_receipts, *receipts]


def merge_source_ranges(candidates):
    result, receipts = [], []
    for candidate in candidates:
        provenance = dict(candidate.provenance or {})
        span = provenance.get("source_range")
        if (not isinstance(span, dict) or set(span) != {"field_path", "start", "end", "text_hash"}
                or not candidate.source_revision or not candidate.content_digest
                or not isinstance(span["field_path"], list) or type(span["start"]) is not int or type(span["end"]) is not int
                or not 0 <= span["start"] < span["end"] or span["end"] - span["start"] != len(candidate.safe_summary)
                or span["text_hash"] != "sha256:" + hashlib.sha256(candidate.safe_summary.encode()).hexdigest()):
            result.append(candidate)
            continue
        scope = _source_metadata(candidate)
        scope.pop("safe_summary")
        scope["field_path"] = span["field_path"]
        scope["provenance"] = {key: value for key, value in provenance.items() if key not in {"source_range", "lossless_range_union"}}
        scope_hash = narrative_hash(scope)
        members = [{"asset_version_id": candidate.asset_version_id, **span}]
        combined = replace(candidate, provenance={**provenance, "lossless_range_union": {
            "scope_hash": scope_hash, "members": members, "reversibility": "ORIGINAL_UNCHANGED"}})
        insertion = len(result)
        index = 0
        while index < len(result):
            previous = result[index]
            prior_provenance = dict(previous.provenance or {})
            prior = prior_provenance.get("source_range")
            current = combined.provenance["source_range"]
            if not prior or prior_provenance.get("lossless_range_union", {}).get("scope_hash") != scope_hash:
                index += 1
                continue
            low, high = max(prior["start"], current["start"]), min(prior["end"], current["end"])
            if low > high:
                index += 1
                continue
            if previous.safe_summary[low - prior["start"]:high - prior["start"]] != combined.safe_summary[low - current["start"]:high - current["start"]]:
                raise KernelError("TASK_CONTEXT_SOURCE_RANGE_AMBIGUOUS", "The same source version and field claim conflicting original overlap")
            start, end = min(prior["start"], current["start"]), max(prior["end"], current["end"])
            first, second = (previous, combined) if prior["start"] <= current["start"] else (combined, previous)
            first_span, second_span = ((prior, current) if first is previous else (current, prior))
            text = first.safe_summary + second.safe_summary[max(0, first_span["end"] - second_span["start"]):]
            if (text[prior["start"] - start:prior["end"] - start] != previous.safe_summary
                    or text[current["start"] - start:current["end"] - start] != combined.safe_summary):
                raise KernelError("TASK_CONTEXT_SOURCE_RANGE_AMBIGUOUS", "Source range union must reconstruct every original member exactly")
            members = [*prior_provenance["lossless_range_union"]["members"], *combined.provenance["lossless_range_union"]["members"]]
            combined = replace(previous, safe_summary=text, estimated_tokens=len(text.encode()),
                relevance_score=max(previous.relevance_score, combined.relevance_score), provenance={**prior_provenance,
                "source_range": {"field_path": span["field_path"], "start": start, "end": end, "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()},
                "lossless_range_union": {"scope_hash": scope_hash, "members": members, "reversibility": "EVERY_ORIGINAL_MEMBER_EXACT"}})
            receipts.append({"asset_version_id": candidate.asset_version_id, "retained_asset_version_id": previous.asset_version_id,
                "reason": "VERIFIED_ORIGINAL_RANGE_UNION", "members": deepcopy(members)})
            insertion = min(insertion, index)
            result.pop(index)
            index = 0
        result.insert(insertion, combined)
    return result, receipts


def source_audit(units, keep):
    return [{key: deepcopy(unit[key]) for key in ("unit_id", "source_path", "source_span", "order", "index", "field", "kind", "attribution", "source_fields", "explicit_refs", "source_aliases", "required", "semantic_risk", "source_parse_assessment") if key in unit} | {"unit_hash": narrative_hash(unit["text"])} for unit in units if unit["unit_id"] in keep]


def final_windows(units, keep, *, external_refs=()):
    windows = []
    indexes = {unit["unit_id"]: index for index, unit in enumerate(units)}
    centers = {index for index, unit in enumerate(units) if unit["unit_id"] in keep and
        (unit.get("semantic_risk") or any(0 <= neighbor < len(units) and units[neighbor]["unit_id"] not in keep for neighbor in (index - 1, index + 1)))}
    for center in sorted(centers):
        neighborhood = set(range(max(0, center - 2), min(len(units), center + 3)))
        neighborhood.update(indexes[value] for value in close_dependencies(units, {units[center]["unit_id"]}, external_refs=external_refs) if value in indexes)
        windows.append([units[index] for index in sorted(neighborhood)])
    return windows


def pack_final_windows(windows, *, payload, fits):
    def merged(groups):
        unique = {unit["unit_id"]: unit for group in groups for unit in group}
        return sorted(unique.values(), key=lambda unit: unit["order"])
    def admissible(group):
        return len(group) <= FROZEN_COMPRESSION_REQUEST_MAX_UNITS and fits(payload(group))
    if not windows:
        return []
    whole = merged(windows)
    if admissible(whole):
        return [whole]
    batches, current = [], []
    for window in windows:
        combined = merged([current, window])
        if admissible(combined):
            current = combined
            continue
        if current:
            batches.append(current)
        if not admissible(window):
            raise KernelError("TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE", "A complete semantic risk neighborhood and dependency closure cannot fit the checker request")
        current = window
    if current:
        batches.append(current)
    return batches


def split_oversized_unit(unit, fits):
    if unit["field"] != "safe_summary" or not unit.get("source_span"):
        raise KernelError("TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE", "An indivisible source field cannot fit the complete checker request")
    text = unit["text"]
    original_start = unit["source_span"][0]
    protected = list(zip(unit.get("protected_spans", ())[::2], unit.get("protected_spans", ())[1::2]))
    boundaries = [end for _, end in sentence_spans(text)]
    if len(text) not in boundaries:
        boundaries.append(len(text))
    boundaries = [end for end in boundaries if not any(start < original_start + end < stop for start, stop in protected)]
    result, start = [], 0
    while start < len(text):
        possible = [end for end in boundaries if end > start]
        low, high, chosen = 0, len(possible) - 1, None
        while low <= high:
            middle = (low + high) // 2
            end = possible[middle]
            fragment = {**unit, "unit_id": unit["unit_id"] + f":{start}:{end}", "text": text[start:end],
                "source_span": [original_start + start, original_start + end],
                "source_aliases": [*unit.get("source_aliases", ()), unit["unit_id"]], "parent_unit_id": unit["unit_id"],
                "required": unit.get("required_without_quotes", False) or any(left < original_start + end and right > original_start + start for left, right in protected)}
            if fits([fragment]):
                chosen, low = fragment, middle + 1
            else:
                high = middle - 1
        if chosen is None:
            raise KernelError("TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE", "No complete sentence or protected quotation can fit the full compressor and fidelity requests")
        result.append(chosen)
        start = chosen["source_span"][1] - original_start
    return result


def verify_final_selection(candidate, units, keep, *, payload, fits, model_call, external_refs=()):
    all_ids = {unit["unit_id"] for unit in units}
    catalog_hash = narrative_hash(source_audit(units, all_ids))
    evidence, assessments = [], []
    chosen = close_dependencies(units, keep, external_refs=external_refs)
    while chosen != all_ids:
        content_hash = narrative_hash(reconstruct(candidate, units, chosen))
        additions = set()
        def check_task(group):
            return {**payload(group), "selected_unit_ids": [unit["unit_id"] for unit in group if unit["unit_id"] in chosen],
                "composition_check": {"phase": "FINAL_COMPOSED_EXTRACT", "result_content_hash": content_hash,
                    "catalog_hash": catalog_hash, "meaning": "Judge this final selection against located original neighbors and attribution. Unselected units remain retrievable; identify required missing meaning by unit ID, without inventing facts."}}
        windows = final_windows(units, chosen, external_refs=external_refs)
        for group in pack_final_windows(windows, payload=check_task, fits=fits):
            task = check_task(group)
            verdict = dict(model_call("context_fidelity", task))
            allowed = {unit["unit_id"] for unit in group}
            missing = set(verdict.get("missing_unit_ids") or ())
            distorted = set(verdict.get("distorted_unit_ids") or ())
            unsupported = (missing | distorted) - allowed or verdict.get("supported") is not True or (verdict.get("coverage_complete") is not True and not missing)
            additions.update(allowed if unsupported or distorted else missing)
            evidence.append(dict(verdict.get("_execution_evidence") or {}))
            assessments.append({"task": task, "fidelity": {key: value for key, value in verdict.items() if key != "_execution_evidence"}, "fidelity_evidence": dict(verdict.get("_execution_evidence") or {})})
            if unsupported and allowed <= chosen:
                additions.update(all_ids)
        closed = close_dependencies(units, chosen | additions, external_refs=external_refs)
        if closed == chosen:
            return chosen, {"contract_version": SEMANTIC_CONTRACT, "result_content_hash": content_hash,
                "catalog_hash": catalog_hash, "selected_unit_ids": [unit["unit_id"] for unit in units if unit["unit_id"] in chosen],
                "deterministic_required_fields_and_dependencies": "VERIFIED", "semantic_scope": "TARGETED_SOURCE_NEIGHBOR_WINDOWS_ONLY", "assessments": assessments}, evidence
        chosen = closed
    return chosen, {"contract_version": SEMANTIC_CONTRACT, "result_content_hash": narrative_hash(reconstruct(candidate, units, chosen)),
        "catalog_hash": catalog_hash, "deterministic_required_fields_and_dependencies": "VERIFIED",
        "semantic_scope": "EXACT_COMPLETE_ORIGINAL_RESTORED", "assessments": assessments}, evidence
