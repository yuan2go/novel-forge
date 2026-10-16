from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash


SEMANTIC_CONTRACT = "source-unit-dependency-and-final-composition.v2"
ATTRIBUTION_FIELDS = frozenset({"subject", "speaker", "subject_id", "actor_id", "event_id", "observation_id", "time", "event_time", "perspective", "knowledge_owner", "epistemic_status", "status", "acceptance_status", "conditions", "exceptions", "negated", "cause_refs", "causes", "depends_on", "units", "quantity"})
_TEXT_FIELDS = frozenset({"text", "summary", "safe_summary", "claim", "description", "prose"})
_RELATIONS = frozenset({"cause_refs", "causes", "depends_on", "required_fact_ids", "predecessor_event_ids"})
_ALIASES = frozenset({"fact_id", "event_id", "observation_id", "state_id", "unit_ref"})
_RISK = re.compile(r"条件|除非|否则|只有|并非|没有|未曾|听说|以为|相信|读者|次日|翌日|此前|因此|所以|这两|其后|\b(?:unless|if|not|believes?|heard|therefore|before|after|they|it)\b", re.I)
_GAP = "\n\n[此处省略原来源片段；相邻摘录不代表连续事件，省略不表示未发生。]\n\n"


def enabled(task):
    return task.get("semantic_contract") == SEMANTIC_CONTRACT


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


def source_units(candidate, task):
    result = []
    try:
        document = json.loads(candidate.safe_summary)
    except (ValueError, TypeError):
        document = None

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
        for match in re.finditer(r"(?:\r?\n)[ \t]*(?:\r?\n)", text):
            if start < match.start():
                append(text[start:match.start()], path, kind="SOURCE_PARAGRAPH", index=index,
                    span=[start, match.start()], attribution=attribution)
                index += 1
            start = match.end()
        if start < len(text):
            append(text[start:], path, kind="SOURCE_PARAGRAPH", index=index, span=[start, len(text)], attribution=attribution)

    def visit(value, path=(), attribution=None):
        if isinstance(value, dict):
            attributed = {**(attribution or {}), **{key: deepcopy(child) for key, child in value.items() if key in ATTRIBUTION_FIELDS}}
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

    if isinstance(document, (dict, list)):
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
            observations = {row["observation_id"]: row for field in matches for row in field.get("located_observations", ())
                if row["range"][0] < end and row["range"][1] > start}
            if observations:
                unit["attribution"]["located_working_observations"] = list(observations.values())
                unit["source_aliases"] = sorted(set(unit["source_aliases"]) | set(observations))
                unit["explicit_refs"] = sorted(set(unit["explicit_refs"]) | {cause for row in observations.values() for cause in row["causes"]})
        if task.get("stage") == "reference_analysis" and re.match(r"^第[0-9一二三四五六七八九十百千万零〇两]+[章回节卷](?:\s|$)", unit["text"].strip()):
            unit.update(required=True, required_without_quotes=True)
    return result


def _text_fields(candidate, *, all_fields=False):
    try:
        document = json.loads(candidate.safe_summary)
    except (ValueError, TypeError):
        return [((), candidate.safe_summary)]
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
            text = "\n\n".join(value for _, value in fields)
            intervals, offset = [], 0
            for path, value in fields:
                intervals.append((path, offset, offset + len(value)))
                offset += len(value) + 2
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
    try:
        document = json.loads(candidate.safe_summary)
    except (ValueError, TypeError):
        document = None
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


def exact_deduplicate(candidates):
    candidates, union_receipts = merge_source_ranges(candidates)
    accepted, receipts, owners = [], [], {}
    for candidate in candidates:
        identity = narrative_hash({"source_identity": candidate.source_identity, "source_revision": candidate.source_revision,
            "project_id": candidate.project_id, "book_id": candidate.book_id, "qualification": candidate.qualification,
            "governance_status": candidate.governance_status, "authority_freshness": candidate.authority_freshness,
            "content_digest": candidate.content_digest, "asset_type": candidate.asset_type,
            "logical_context_kind": candidate.logical_context_kind, "summary": candidate.safe_summary,
            "facts": candidate.structured_facts, "accepted_boundary": candidate.accepted_boundary,
            "observation_boundary": candidate.observation_boundary, "source_use_mode": candidate.source_use_mode,
            "allowed_use": candidate.allowed_use, "provenance": candidate.provenance,
            "required": candidate.required, "context_class": candidate.context_class})
        previous = owners.get(identity)
        if previous is None:
            owners[identity] = candidate
            accepted.append(candidate)
        else:
            receipts.append({"asset_version_id": candidate.asset_version_id, "retained_asset_version_id": previous.asset_version_id,
                "reason": "IDENTICAL_VERSION_SCOPE_CONTENT_AND_ATTRIBUTION", "identity_hash": identity})
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
        scope = {"source": candidate.source_identity, "revision": candidate.source_revision,
            "project_id": candidate.project_id, "book_id": candidate.book_id,
            "qualification": candidate.qualification, "governance_status": candidate.governance_status,
            "authority_freshness": candidate.authority_freshness, "narrative_function": candidate.narrative_function,
            "whole_source_hash": candidate.content_digest, "field_path": span["field_path"],
            "asset_type": candidate.asset_type, "logical_context_kind": candidate.logical_context_kind,
            "facts": candidate.structured_facts, "boundary": candidate.accepted_boundary,
            "observation_boundary": candidate.observation_boundary, "required": candidate.required,
            "allowed_use": candidate.allowed_use, "source_use_mode": candidate.source_use_mode,
            "context_class": candidate.context_class, "provenance": {key: value for key, value in provenance.items() if key not in {"source_range", "lossless_range_union"}}}
        merged = False
        for index, previous in enumerate(result):
            prior_provenance = dict(previous.provenance or {})
            prior = prior_provenance.get("source_range")
            if not prior or prior_provenance.get("lossless_range_union", {}).get("scope_hash") != narrative_hash(scope):
                continue
            low, high = max(prior["start"], span["start"]), min(prior["end"], span["end"])
            if low > high:
                continue
            if previous.safe_summary[low - prior["start"]:high - prior["start"]] != candidate.safe_summary[low - span["start"]:high - span["start"]]:
                raise KernelError("TASK_CONTEXT_SOURCE_RANGE_AMBIGUOUS", "The same source version and field claim conflicting original overlap")
            start, end = min(prior["start"], span["start"]), max(prior["end"], span["end"])
            first, second = (previous, candidate) if prior["start"] <= span["start"] else (candidate, previous)
            first_span, second_span = ((prior, span) if first is previous else (span, prior))
            text = first.safe_summary + second.safe_summary[max(0, first_span["end"] - second_span["start"]):]
            if (text[prior["start"] - start:prior["end"] - start] != previous.safe_summary
                    or text[span["start"] - start:span["end"] - start] != candidate.safe_summary):
                raise KernelError("TASK_CONTEXT_SOURCE_RANGE_AMBIGUOUS", "Source range union must reconstruct every original member exactly")
            members = [*prior_provenance["lossless_range_union"]["members"], {"asset_version_id": candidate.asset_version_id, **span}]
            result[index] = replace(previous, safe_summary=text, estimated_tokens=len(text.encode()), provenance={**prior_provenance,
                "source_range": {"field_path": span["field_path"], "start": start, "end": end, "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()},
                "lossless_range_union": {"scope_hash": narrative_hash(scope), "members": members, "reversibility": "EVERY_ORIGINAL_MEMBER_EXACT"}})
            receipts.append({"asset_version_id": candidate.asset_version_id, "retained_asset_version_id": previous.asset_version_id,
                "reason": "VERIFIED_ORIGINAL_RANGE_UNION", "members": members})
            merged = True
            break
        if not merged:
            result.append(replace(candidate, provenance={**provenance,
                "lossless_range_union": {"scope_hash": narrative_hash(scope), "members": [{"asset_version_id": candidate.asset_version_id, **span}], "reversibility": "ORIGINAL_UNCHANGED"}}))
    return result, receipts


def source_audit(units, keep):
    return [{key: deepcopy(unit[key]) for key in ("unit_id", "source_path", "source_span", "order", "index", "field", "kind", "attribution", "source_fields", "explicit_refs", "source_aliases", "required", "semantic_risk") if key in unit} | {"unit_hash": narrative_hash(unit["text"])} for unit in units if unit["unit_id"] in keep]


def final_windows(units, keep, *, external_refs=()):
    windows = []
    indexes = {unit["unit_id"]: index for index, unit in enumerate(units)}
    centers = {index for index, unit in enumerate(units) if unit["unit_id"] in keep and
        (unit.get("semantic_risk") or any(0 <= neighbor < len(units) and units[neighbor]["unit_id"] not in keep for neighbor in (index - 1, index + 1)))}
    for center in sorted(centers):
        indexes_in_window = set(range(max(0, center - 2), min(len(units), center + 3)))
        indexes_in_window.update(indexes[value] for value in close_dependencies(units, {units[center]["unit_id"]}, external_refs=external_refs) if value in indexes)
        if windows and indexes_in_window & windows[-1] and len(indexes_in_window | windows[-1]) <= 32:
            windows[-1].update(indexes_in_window)
        else:
            windows.append(indexes_in_window)
    return [[units[index] for index in sorted(window)] for window in windows]


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
    evidence, assessments = [], []
    chosen = close_dependencies(units, keep, external_refs=external_refs)
    while chosen != all_ids:
        content_hash = narrative_hash(reconstruct(candidate, units, chosen))
        additions = set()
        for window in final_windows(units, chosen, external_refs=external_refs):
            pending = [window]
            while pending:
                group = pending.pop(0)
                task = {**payload(group), "selected_unit_ids": [unit["unit_id"] for unit in group if unit["unit_id"] in chosen],
                    "composition_check": {"phase": "FINAL_COMPOSED_EXTRACT", "result_content_hash": content_hash,
                        "catalog_hash": narrative_hash(source_audit(units, all_ids)), "meaning": "Judge this final selection against located original neighbors and attribution. Unselected units remain retrievable; identify required missing meaning by unit ID, without inventing facts."}}
                if not fits(task):
                    if len(group) == 1:
                        raise KernelError("TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE", "Final semantic check cannot fit its complete request")
                    middle = len(group) // 2
                    pending[0:0] = [group[:middle], group[middle:]]
                    continue
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
                "catalog_hash": narrative_hash(source_audit(units, all_ids)), "selected_unit_ids": [unit["unit_id"] for unit in units if unit["unit_id"] in chosen],
                "deterministic_required_fields_and_dependencies": "VERIFIED", "semantic_scope": "TARGETED_SOURCE_NEIGHBOR_WINDOWS_ONLY", "assessments": assessments}, evidence
        chosen = closed
    return chosen, {"contract_version": SEMANTIC_CONTRACT, "result_content_hash": narrative_hash(reconstruct(candidate, units, chosen)),
        "catalog_hash": narrative_hash(source_audit(units, all_ids)), "deterministic_required_fields_and_dependencies": "VERIFIED",
        "semantic_scope": "EXACT_COMPLETE_ORIGINAL_RESTORED", "assessments": assessments}, evidence
