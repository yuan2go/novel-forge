from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from typing import Any, Callable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate, ContextClass
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.production_execution.token_meter import SYSTEM_CONTEXT_LIMIT, TOKENIZER_METHODS, serialized_tokens

from .task_compression import compile_task_context
from . import semantic_units


CAPACITY_POLICY = "complete-request-capacity.v1"
STORY_EXTRACT_TRANSPORT = "capacity-story-extract.v1"
_HISTORY_TYPES = frozenset({"narrative_retrieval_document", "chapter_episodic_summary", "scene_episodic_summary", "character_timeline", "relationship_timeline"})


def validate_projection_quotes(data: dict, quotes: tuple[str, ...]) -> list[dict]:
    if not quotes:
        return []
    candidates = []
    def source_view(value):
        if isinstance(value, dict):
            if value.get("version") in ("working-observations.v1", "working-observations-provider.v1", "working-observations-packet.v2", "working-observations-provider.v2"):
                return {"source_coverage": value.get("source_coverage", [])}
            result = {}
            for key, child in value.items():
                if key == "preserve_quotes":
                    continue
                if key == "safe_summary" and isinstance(child, str):
                    parsed, _ = semantic_units.decode_json_values(child)
                    if isinstance(parsed, (dict, list)):
                        child = parsed
                result[key] = source_view(child)
            return result
        if isinstance(value, list):
            return [source_view(child) for child in value]
        return value
    def visit(value, path=()):
        if isinstance(value, dict):
            if value.get("asset_version_id") and ("passages" in value or "safe_summary" in value):
                candidates.append(ContextCandidate(asset_version_id="quote-source:" + narrative_hash(list(path)),
                    asset_type="historical_expression_projection", project_id="projection", estimated_tokens=1,
                    safe_summary=json.dumps(value, ensure_ascii=False)))
                return
            for key, child in value.items():
                if key != "preserve_quotes":
                    visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))
        elif isinstance(value, str) and value:
            candidates.append(ContextCandidate(asset_version_id="quote-field:" + narrative_hash(list(path)),
                asset_type="historical_expression_projection", project_id="projection", estimated_tokens=1, safe_summary=value))
    visit(source_view(data))
    catalogs = {item.asset_version_id: semantic_units.source_units(item, {}) for item in candidates}
    return semantic_units.protect_quotes(candidates, catalogs, quotes)


def working_observation_index(data):
    result = {}
    def visit(value):
        if isinstance(value, dict):
            if value.get("version") in ("working-observations.v1", "working-observations-provider.v1", "working-observations-packet.v2", "working-observations-provider.v2") and value.get("authority") == "UNREVIEWED_WORKING_OBSERVATIONS":
                for entry in value.get("entries") or []:
                    source = entry.get("source") or {}
                    identity = (source.get("asset_version_id"), source.get("content_hash"))
                    result.setdefault(identity, {})[entry["observation_id"]] = entry
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)
    return {key: list(values.values()) for key, values in result.items()}


def recompose_capacity_context(original: dict, upgrade: Mapping[str, Any]) -> tuple[dict, dict]:
    if (upgrade.get("transport_projection") != "chapter-complete-request-capacity.v1"
            or upgrade.get("target_context_policy_ref") not in {"context-policy:chapter-generation-pack:v3", "context-policy:chapter-generation-pack:v4"}
            or not upgrade.get("policy_hash") or not upgrade.get("source_operation_id")):
        raise KernelError("CHAPTER_CAPACITY_UPGRADE_SOURCE_DRIFT", "Context derivation requires its registered exact source and target policy")
    result = deepcopy(original)
    result.pop("capacity_policy_upgrade", None)
    rebuilt = bool(upgrade.get("context_source"))
    result["request_context_derivation"] = {
        "contract_version": "capacity-context-projection.v1", "source_projection_hash": narrative_hash(original),
        "policy_hash": upgrade["policy_hash"], "source_selection": "ORIGINAL_FROZEN_INPUTS_REBUILT" if rebuilt else "ORIGINAL_FROZEN_SELECTION",
        "meaning": "The original source versions and attribution are unchanged. Context is rebuilt from the original producer's frozen inputs before complete request admission." if rebuilt else "The original frozen sources and their attribution are unchanged. Complete request admission replaces only the old material capacity veto. Earlier selection gaps remain retrievable source evidence and never establish absence."}
    return result, {"contract_version": "capacity-context-projection.v1", "source_projection_hash": narrative_hash(original),
        "derived_projection_hash": narrative_hash(result), "policy_hash": upgrade["policy_hash"],
        "source_operation_id": upgrade["source_operation_id"], "source_selection": "ORIGINAL_FROZEN_INPUTS_REBUILT" if rebuilt else "UNCHANGED"}


def expand_semantic_history(data: dict) -> dict:
    result = deepcopy(data)
    def visit(value):
        if isinstance(value, dict):
            if (value.get("asset_type") or value.get("logical_context_kind")) in _HISTORY_TYPES and isinstance(value.get("safe_summary"), str):
                parsed, _ = semantic_units.decode_json_values(value["safe_summary"])
                if isinstance(parsed, (dict, list)):
                    value["safe_summary"] = parsed
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(result)
    return result


def historical_expression_paths(data: Any, *, semantic: bool = False, history_exact_chapters: int | None = None) -> dict[tuple, str]:
    result = {}

    def visit(value, path=()):
        if isinstance(value, dict):
            if isinstance(value.get("projection_policy"), dict) and isinstance(value.get("sources"), list):
                policy = value["projection_policy"]
                prepared_complete = int(policy.get("recent_complete_chapters") or 0)
                protected_complete = min(prepared_complete, history_exact_chapters) if semantic and history_exact_chapters is not None else prepared_complete
                recent = int(value.get("target_chapter") or 0) - protected_complete
                for index, source in enumerate(value["sources"]):
                    if int(source.get("chapter") or 0) >= recent:
                        continue
                    for position, passage in enumerate(source.get("passages") or []):
                        if isinstance(passage.get("text"), str):
                            result[(*path, "sources", index, "passages", position, "text")] = passage["text"]
                return
            if (value.get("asset_type") or value.get("logical_context_kind")) in _HISTORY_TYPES:
                summary = value.get("safe_summary")
                if isinstance(summary, str) and summary:
                    try:
                        structured = isinstance(json.loads(summary), (dict, list))
                    except ValueError:
                        structured = False
                    if not structured:
                        result[(*path, "safe_summary")] = summary
                elif semantic and isinstance(summary, (dict, list)):
                    def narrative_fields(value, scope):
                        if isinstance(value, dict):
                            for key, child in value.items():
                                if key in {"text", "summary", "safe_summary", "prose", "description"} and isinstance(child, str) and child:
                                    result[(*scope, key)] = child
                                elif isinstance(child, (dict, list)):
                                    narrative_fields(child, (*scope, key))
                        elif isinstance(value, list):
                            for index, child in enumerate(value):
                                narrative_fields(child, (*scope, index))
                    narrative_fields(summary, (*path, "safe_summary"))
            for key, child in value.items():
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))

    visit(data)
    return result


def apply_capacity_projection(data: dict, projection: Mapping[str, Any]) -> dict:
    if projection.get("contract_version") != CAPACITY_POLICY or projection.get("original_hash") != narrative_hash(data):
        raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "capacity derivation must match the original frozen Provider projection")
    semantic = projection.get("semantic_contract") == semantic_units.SEMANTIC_CONTRACT
    exact = projection.get("capacity_history_exact_chapters")
    if exact is not None and (not semantic or type(exact) is not int or exact < 1):
        raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "Historical expression protection is not a valid frozen semantic policy")
    allowed = historical_expression_paths(data, semantic=semantic, history_exact_chapters=projection.get("capacity_history_exact_chapters"))
    result = deepcopy(data)
    seen = set()
    for row in projection.get("replacements") or []:
        path = tuple(row["path"])
        if path in seen or path not in allowed or row["source_text_hash"] != narrative_hash(allowed[path]):
            raise KernelError("CONTEXT_CAPACITY_SOURCE_DRIFT", "only original eligible historical expression may be extracted")
        seen.add(path)
        source = allowed[path]
        pieces = []
        end = 0
        for start, stop in row["ranges"]:
            if type(start) is not int or type(stop) is not int or not end <= start < stop <= len(source):
                raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "extract ranges must be ordered original Unicode positions")
            pieces.append(source[start:stop])
            end = stop
        target = result
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = semantic_units.excerpt_text(source, row["ranges"]) if semantic else "\n\n".join(pieces)
    if projection.get("result_hash") != narrative_hash(result):
        raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "derived Provider projection hash changed")
    return result


def project_capacity_passages(original: dict, derived: dict, projection: Mapping[str, Any]) -> dict:
    grouped = {}
    for row in projection["replacements"]:
        path = tuple(row["path"])
        if len(path) >= 3 and path[-3] == "passages" and path[-1] == "text":
            grouped.setdefault(path[:-3], {})[path[-2]] = row["ranges"]
    for path, selections in grouped.items():
        source, target = original, derived
        for part in path:
            source, target = source[part], target[part]
        passages = source["passages"]
        if set(selections) != set(range(len(passages))) or not source.get("asset_version_id") or not source.get("content_hash"):
            continue
        previous = 0
        valid = True
        for passage in passages:
            if (set(passage) != {"start", "end", "text", "text_hash"} or type(passage["start"]) is not int
                    or type(passage["end"]) is not int or not isinstance(passage["text"], str)
                    or not previous <= passage["start"] < passage["end"]
                    or passage["end"] - passage["start"] != len(passage["text"])
                    or passage["text_hash"] != "sha256:" + hashlib.sha256(passage["text"].encode()).hexdigest()):
                valid = False
                break
            previous = passage["end"]
        if not valid or type(source.get("source_characters")) is not int or source["source_characters"] < previous:
            continue
        if all(selections[index] == [[0, len(passage["text"])]] for index, passage in enumerate(passages)):
            continue
        supplied = []
        for index, passage in enumerate(passages):
            for low, high in selections[index]:
                text = passage["text"][low:high]
                supplied.append({"start": passage["start"] + low, "end": passage["start"] + high,
                    "text": text, "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()})
        omitted = []
        cursor = 0
        for passage in supplied:
            if cursor < passage["start"]:
                omitted.append([cursor, passage["start"]])
            cursor = passage["end"]
        if cursor < source["source_characters"]:
            omitted.append([cursor, source["source_characters"]])
        target["passages"] = supplied
        target["omitted_ranges"] = omitted
        target["historical_extract"] = {"contract_version": "capacity-historical-passages.v1",
            "original_passage_count": len(passages), "supplied_passage_count": len(supplied),
            "additional_omission_reason": "COMPLETE_REQUEST_CAPACITY",
            "meaning": "Each passage is an exact original Unicode range. Omitted ranges include prior selection gaps and new capacity omissions; their original reasons remain in the frozen source projection. Gaps are not consecutive events or evidence of absence. Source version and whole-source hashes remain unchanged; passage hashes bind supplied text. Omitted text remains retrievable from that source."}
    return derived


def _extract_ranges(original: str, candidate: ContextCandidate) -> list[list[int]]:
    selected = candidate.safe_summary
    if selected == original:
        return [[0, len(original)]] if original else []
    if candidate.compression_trace:
        if candidate.compression_trace[0].get("semantic_contract") == semantic_units.SEMANTIC_CONTRACT:
            ranges, previous = [], None
            for unit in candidate.compression_trace[0]["source_units"]:
                start, stop = unit["source_span"]
                if not 0 <= start < stop <= len(original) or narrative_hash(original[start:stop]) != unit["unit_hash"]:
                    raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "Semantic extract no longer matches its original Unicode range")
                if ranges and (previous is not None and unit["order"] == previous + 1 or ranges[-1][1] == start):
                    ranges[-1][1] = stop
                else:
                    ranges.append([start, stop])
                previous = unit["order"]
            if semantic_units.excerpt_text(original, ranges) != candidate.safe_summary:
                raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "Semantic reconstruction differs from the original selected ranges")
            return ranges
        paragraphs = original.split("\n\n")
        offsets = []
        position = 0
        for paragraph in paragraphs:
            offsets.append(position)
            position += len(paragraph) + 2
        ranges = []
        for unit in candidate.compression_trace[0]["source_units"]:
            index = unit["index"]
            if type(index) is not int or not unit["unit_id"].startswith("text:"):
                raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "historical expressions require original paragraph coordinates")
            low, high = unit.get("source_offsets", [0, len(paragraphs[index])])
            start, stop = offsets[index] + low, offsets[index] + high
            if ranges and ranges[-1][1] == start:
                ranges[-1][1] = stop
            else:
                ranges.append([start, stop])
        if "\n\n".join(original[start:end] for start, end in ranges) != selected:
            raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "selected expression differs from its original unit coordinates")
        return ranges
    ranges = []
    cursor = 0
    for text in selected.split("\n\n"):
        if not text:
            continue
        start = original.find(text, cursor)
        if start < 0:
            raise KernelError("CONTEXT_CAPACITY_EXTRACT_INVALID", "the compression result is not an ordered extract of its original source")
        ranges.append([start, start + len(text)])
        cursor = start + len(text)
    return ranges


def verify_request_composition(candidates, compressed, *, supplied, task, source_boundary, chunk_fits, model_call):
    units, selected, originals, origins = [], set(), {}, {}
    unchanged = set()
    by_id = {item.asset_version_id: item for item in compressed}
    for original in candidates:
        result = by_id[original.asset_version_id]
        if result.safe_summary == original.safe_summary and result.structured_facts == original.structured_facts:
            unchanged.add(original.asset_version_id)
        trace = result.compression_trace[0] if result.compression_trace else None
        if trace:
            catalog = trace["source_catalog"]
        else:
            original_units = semantic_units.source_units(original, task)
            catalog = semantic_units.source_audit(original_units, {unit["unit_id"] for unit in original_units})
        keep = set(trace["selected_unit_ids"]) if trace else {unit["unit_id"] for unit in catalog}
        local_ids = {record["unit_id"] for record in catalog}
        for record in catalog:
            start, end = record["source_span"]
            text = original.safe_summary[start:end]
            if narrative_hash(text) != record["unit_hash"]:
                raise KernelError("CONTEXT_FINAL_COMPOSITION_DRIFT", "Final checker source no longer matches the original catalog")
            identity = "source:" + narrative_hash([original.asset_version_id, record["unit_id"]]).split(":")[-1][:32]
            unit = {**record, "unit_id": identity, "text": text, "order": len(units),
                "explicit_refs": ["source:" + narrative_hash([original.asset_version_id, ref]).split(":")[-1][:32] if ref in local_ids else ref for ref in record.get("explicit_refs", ())],
                "attribution": {**record.get("attribution", {}), "source_expression": (original.provenance or {}).get("source_expression", {})}}
            units.append(unit)
            originals[identity] = text
            origins[identity] = original.asset_version_id
            if record["unit_id"] in keep:
                selected.add(identity)
    proof = {"contract_version": semantic_units.SEMANTIC_CONTRACT, "phase": "FINAL_PROVIDER_COMPOSITION",
        "supplied_projection_hash": narrative_hash(supplied), "selection_hash": narrative_hash(sorted(selected)),
        "catalog_hash": narrative_hash(semantic_units.source_audit(units, {unit["unit_id"] for unit in units})), "checks": [],
        "exact_original_sources": sorted(unchanged)}
    additions = set()
    closed = semantic_units.close_dependencies(units, selected, external_refs=task.get("external_dependency_refs") or ())
    if closed - selected:
        proof["deterministic_dependency_additions"] = sorted(closed - selected)
        return proof, [originals[identity] for identity in sorted(closed - selected)]
    transformed = [unit for unit in units if origins[unit["unit_id"]] not in unchanged]
    external = set(task.get("external_dependency_refs") or ()) | {alias for unit in units if origins[unit["unit_id"]] in unchanged for alias in unit.get("source_aliases", ())}
    def check_task(group):
        return {"contract_version": "task-context-compression.v3", "semantic_contract": semantic_units.SEMANTIC_CONTRACT,
            "policy_version": "task-scoped-context.v1", "frozen_input_boundary": source_boundary,
            "task_fingerprint": task["source_projection_hash"], "task": task, "source_binding": source_boundary["sources"][0],
            "units": group, "required_unit_ids": [unit["unit_id"] for unit in group if unit["required"]],
            "target_tokens": 512_000, "selected_unit_ids": [unit["unit_id"] for unit in group if unit["unit_id"] in selected],
            "composition_check": {key: proof[key] for key in ("phase", "supplied_projection_hash", "selection_hash", "catalog_hash")}}
    windows = semantic_units.final_windows(transformed, selected, external_refs=external)
    for group in semantic_units.pack_final_windows(windows, payload=check_task, fits=chunk_fits):
        chunk = check_task(group)
        verdict = dict(model_call("context_fidelity", chunk))
        allowed = {unit["unit_id"] for unit in group}
        missing = set(verdict.get("missing_unit_ids") or ())
        distorted = set(verdict.get("distorted_unit_ids") or ())
        unsupported = (missing | distorted) - allowed or verdict.get("supported") is not True or (verdict.get("coverage_complete") is not True and not missing)
        requested = allowed if unsupported or distorted else missing
        if requested and requested <= selected:
            affected = {origins[identity] for identity in allowed}
            requested = {identity for identity, source in origins.items() if source in affected}
            if requested <= selected:
                raise KernelError("TASK_CONTEXT_FINAL_COMPOSITION_UNCERTAIN", "Final combination still has an unresolved semantic risk despite carrying its complete original sources", details={"proof": proof, "verdict": verdict})
        additions.update(requested - selected)
        proof["checks"].append({"task": chunk, "fidelity": {key: value for key, value in verdict.items() if key != "_execution_evidence"}, "execution_evidence": dict(verdict.get("_execution_evidence") or {})})
    return proof, [originals[identity] for identity in sorted(additions)]


def prepare_request_capacity(
    *, original: dict, stage: str, source_boundary: dict, route: Any,
    measure: Callable[[dict | None], tuple[int, int]],
    model_call: Callable[[str, dict], Mapping[str, Any]],
    chunk_fits: Callable[[dict], bool],
    preserve_quotes: tuple[str, ...] = (),
    capacity_bindings: dict | None = None,
    semantic_contract: str = "",
    history_exact_chapters: int | None = None,
) -> dict | None:
    if semantic_contract not in {"", semantic_units.SEMANTIC_CONTRACT}:
        raise KernelError("CONTEXT_SEMANTIC_POLICY_INVALID", "Unknown frozen semantic Context method")
    semantic = bool(semantic_contract)
    if history_exact_chapters is not None and (not semantic or type(history_exact_chapters) is not int or history_exact_chapters < 1):
        raise KernelError("CONTEXT_HISTORY_PROTECTION_POLICY_INVALID", "History expression protection requires its frozen semantic policy")
    quote_locations = validate_projection_quotes(original, preserve_quotes) if semantic else []
    before, limit = measure(None)
    if before <= limit:
        return None
    method = route.token_accounting_method
    conservative_semantic = False
    if semantic:
        from novel_forge.modules.production_execution.provider_admission import build_route_token_accounting_contract
        accounting = build_route_token_accounting_contract(provider=route.model_profile.model_provider,
            model=route.model_profile.model_id, route_identity="complete-request-preparation",
            accounting_method=method, accounting_evidence_ref=route.token_accounting_evidence_ref,
            model_context_limit=route.model_context_limit, execution_token_limit=SYSTEM_CONTEXT_LIMIT,
            output_reserve=1, safety_margin=route.token_safety_margin, framing_overhead=route.token_framing_overhead,
            contract_version="provider-token-accounting-v4")
        conservative_semantic = accounting.precision in {"PROVEN_UPPER_BOUND", "APPLICATION_VISIBLE_UPPER_BOUND"}
    if method not in TOKENIZER_METHODS and route.model_profile.model_provider != "scripted_provider_v2" and not conservative_semantic:
        raise KernelError("PROVIDER_CONTEXT_CAPACITY_UNCERTAIN", "a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression",
                          details={"upper_bound": before, "limit": limit, "actual_tokens": None})
    paths = dict(sorted(historical_expression_paths(original, semantic=semantic, history_exact_chapters=history_exact_chapters).items(),
                        key=lambda row: tuple((isinstance(part, int), part) for part in row[0])))
    if not paths:
        raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "the complete request exceeds capacity and contains no eligible historical expression",
                          details={"reserved": before, "limit": limit, "source_boundary": source_boundary})
    if len(source_boundary["sources"]) != 1:
        raise KernelError("CONTEXT_CAPACITY_SOURCE_AMBIGUOUS", "Each frozen Provider projection requires its actual Context custodian")
    source = source_boundary["sources"][0]
    def counter(value):
        return serialized_tokens(value, method=method, model=route.model_profile.model_id,
                                 evidence_ref=route.token_accounting_evidence_ref)
    grouped = {}
    for path, text in paths.items():
        parent = path[:-3] if len(path) >= 3 and path[-3] == "passages" else path
        if semantic:
            value = original
            for index, part in enumerate(path):
                if isinstance(value, dict) and (value.get("asset_type") or value.get("logical_context_kind")) in _HISTORY_TYPES:
                    parent = path[:index]
                    break
                value = value[part]
        grouped.setdefault(parent, []).append((path, text))
    candidates_by_hash = {}
    locations = {}
    observations_by_source = working_observation_index(original) if semantic else {}
    for parent, expressions in grouped.items():
        combined, expression_positions = semantic_units.join_original_fields(original, expressions) if semantic else ("\n\n".join(text for _, text in expressions), [])
        origin = original
        for part in parent:
            origin = origin[part]
        identity = {key: origin[key] for key in ("asset_version_id", "content_hash", "chapter") if isinstance(origin, dict) and key in origin}
        if not identity.get("asset_version_id") or not identity.get("content_hash"):
            identity = {}
        field_attributions = []
        for path, _ in expressions:
            attributed, value = {}, original
            for part in path:
                if isinstance(value, dict):
                    attributed.update({key: deepcopy(child) for key, child in value.items() if key in semantic_units.ATTRIBUTION_FIELDS})
                value = value[part]
            field_attributions.append(attributed)
        digest = narrative_hash({"text": combined, "source": identity if identity.get("asset_version_id") and identity.get("content_hash") else list(parent),
            **({"field_attributions": field_attributions} if semantic else {})})
        candidate = candidates_by_hash.get(digest)
        if candidate is None:
            candidate = ContextCandidate(asset_version_id="historical-expression:" + digest.split(":")[-1],
                asset_type="historical_expression_projection", project_id=source_boundary["project_id"],
                book_id=source_boundary["book_id"], estimated_tokens=1, relevance_score=1,
                safe_summary=combined, content_digest=narrative_hash(combined), compression_method="none",
                provenance={"frozen_input_boundary": source_boundary, "source_binding": source,
                    "original_expression_paths": [], "source_expression": identity,
                    **({"source_field_ranges": []} if semantic else {})})
            candidates_by_hash[digest] = candidate
        position = 0
        for expression_index, (path, text) in enumerate(expressions):
            if semantic:
                position = expression_positions[expression_index][1]
            candidate.provenance["original_expression_paths"].append(list(path))
            locations[path] = (candidate.asset_version_id, position, position + len(text))
            if semantic:
                located = []
                if len(path) >= 3 and path[-3] == "passages":
                    passage = original
                    for part in path[:-1]:
                        passage = passage[part]
                    for entry in observations_by_source.get((identity.get("asset_version_id"), identity.get("content_hash")), ()):
                        location = entry["location"]
                        if location["start"] < passage["end"] and location["end"] > passage["start"]:
                            located.append({key: deepcopy(entry[key]) for key in ("observation_id", "subject", "perspective", "knowledge_owner", "causes", "claim")} | {
                                "range": [position + max(0, location["start"] - passage["start"]), position + min(len(text), location["end"] - passage["start"])],
                                "authority": "UNREVIEWED_WORKING_OBSERVATIONS", "semantic_support": "NOT_VERIFIED"})
                candidate.provenance["source_field_ranges"].append({"path": list(path), "start": position, "end": position + len(text), "attribution": field_attributions[expression_index],
                    **({"located_observations": located} if located else {})})
            position += len(text) + 2
    candidates = list(candidates_by_hash.values())
    dependency_bindings = semantic_units.protected_dependency_bindings(original, excluded_scopes=set(grouped)) if semantic else []
    eligible_quotes = [quote for quote in preserve_quotes if any(quote.replace("\r\n", "\n") in item.safe_summary.replace("\r\n", "\n") for item in candidates)] if semantic else list(preserve_quotes)
    task = {"stage": stage, "frozen_input_boundary": source_boundary, "source_projection_hash": narrative_hash(original),
            "preserve_quotes": eligible_quotes, "task_context": compression_task_context(original.get("input_manifest") or {}), "capacity_policy": CAPACITY_POLICY,
            **({"capacity_bindings": capacity_bindings} if capacity_bindings else {}),
            **({"semantic_contract": semantic_contract} if semantic else {}),
            **({"capacity_history_exact_chapters": history_exact_chapters} if history_exact_chapters is not None else {}),
            **({"external_dependency_refs": sorted({row["alias"] for row in dependency_bindings})} if semantic else {}),
            "route_contract": {"provider": route.model_profile.model_provider, "model": route.model_profile.model_id,
                               "method": method, "evidence": route.token_accounting_evidence_ref,
                               "context_limit": route.model_context_limit, "output_limit": route.model_output_limit}}
    original_amount = sum(counter({"safe_summary": item.safe_summary, "structured_facts": []}) for item in candidates)
    empty = deepcopy(original)
    empty_projection = {"contract_version": CAPACITY_POLICY, "provider_extract_transport": STORY_EXTRACT_TRANSPORT, "original_hash": narrative_hash(original),
        "source_boundary": source_boundary, "stage": stage, "compression_receipt": {}, "replacements": []}
    if semantic:
        empty_projection["semantic_contract"] = semantic_contract
        if history_exact_chapters is not None:
            empty_projection["capacity_history_exact_chapters"] = history_exact_chapters
    for path, text in paths.items():
        owner = empty
        for part in path[:-1]:
            owner = owner[part]
        owner[path[-1]] = semantic_units.excerpt_text(text, []) if semantic else ""
        empty_projection["replacements"].append({"path": list(path), "source_text_hash": narrative_hash(text), "ranges": []})
    empty_projection["result_hash"] = narrative_hash(empty)
    empty_reserved, _ = measure(empty_projection)
    target = (original_amount * max(1, limit - empty_reserved) // max(1, before - empty_reserved)
              if empty_reserved < limit else original_amount * 3 // 4)
    target = min(SYSTEM_CONTEXT_LIMIT, original_amount - 1,
                 max(sum(counter({"safe_summary": "", "structured_facts": []}) for _ in candidates) + 1, target))
    working = list(candidates)
    raw_required_ids = set()
    while target > 0:
        try:
            compressed, receipt = compile_task_context(working, task=task, token_budget=target,
                required_asset_types=(), model_call=model_call, compression_input_tokens=SYSTEM_CONTEXT_LIMIT,
                token_counter=counter, chunk_fits=chunk_fits, allow_restored_overflow=True, token_accounting_method=method)
        except KernelError as error:
            identity = (error.details or {}).get("source_asset_version_id")
            if semantic and error.code == "TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE" and identity in {item.asset_version_id for item in candidates} and identity not in raw_required_ids:
                raw_required_ids.add(identity)
                working = [replace(item, context_class=ContextClass.PROTECTED) if item.asset_version_id in raw_required_ids else item for item in candidates]
                continue
            raise
        projection = {"contract_version": CAPACITY_POLICY, "provider_extract_transport": STORY_EXTRACT_TRANSPORT, "original_hash": narrative_hash(original),
                      "source_boundary": source_boundary, "stage": stage, "replacements": [], "compression_receipt": receipt,
                      "target_basis": {"policy": "FULL_RENDERED_REMOVABLE_EXPRESSION", "empty_reserved": empty_reserved,
                          "expression_paths": len(paths), "unique_expression_sources": len(candidates)},
                      "retained_fidelity_traces": [trace for item in compressed for trace in item.compression_trace if trace not in receipt["compression_trace"]]}
        if semantic:
            projection["semantic_contract"] = semantic_contract
            if history_exact_chapters is not None:
                projection["capacity_history_exact_chapters"] = history_exact_chapters
        derived = deepcopy(original)
        by_id = {candidate.asset_version_id: candidate for candidate in compressed}
        selected_ranges = {item.asset_version_id: _extract_ranges(item.safe_summary, by_id[item.asset_version_id]) for item in candidates}
        for path, text in paths.items():
            identity, start, stop = locations[path]
            ranges = [[max(low, start) - start, min(high, stop) - start]
                      for low, high in selected_ranges[identity] if low < stop and high > start]
            projection["replacements"].append({"path": list(path), "source_text_hash": narrative_hash(text), "ranges": ranges})
            owner = derived
            for part in path[:-1]:
                owner = owner[part]
            owner[path[-1]] = semantic_units.excerpt_text(text, ranges) if semantic else "\n\n".join(text[start:end] for start, end in ranges)
        projection["result_hash"] = narrative_hash(derived)
        if semantic:
            supplied = project_capacity_passages(original, deepcopy(derived), projection)
            combined_proof, additions = verify_request_composition(candidates, compressed, supplied=supplied,
                task=task, source_boundary=source_boundary, chunk_fits=chunk_fits, model_call=model_call)
            new_quotes = [text for text in additions if text not in task["preserve_quotes"]]
            if new_quotes:
                task["preserve_quotes"] = [*task["preserve_quotes"], *new_quotes]
                working = [replace(item, context_class=ContextClass.PROTECTED) if item.asset_version_id in raw_required_ids else item for item in candidates]
                continue
            projection["final_composition"] = {"contract_version": semantic_contract,
                "supplied_projection_hash": narrative_hash(supplied), "source_boundary_hash": narrative_hash(source_boundary),
                "original_hash": projection["original_hash"], "result_hash": projection["result_hash"],
                "selection_hash": narrative_hash(projection["replacements"]), "quote_locations": quote_locations,
                "indivisible_original_sources_retained": sorted(raw_required_ids),
                "candidate_fidelity_hashes": [narrative_hash(trace["final_composition"]) for trace in receipt["compression_trace"] if trace.get("final_composition")],
                "provider_combination": combined_proof,
                "unchanged_dependency_bindings": dependency_bindings,
                "deterministic_source_fields_ranges_attribution_and_dependencies": "VERIFIED",
                "semantic_scope": "FINAL_EXTRACTS_WITH_BOUNDED_ORIGINAL_RISK_WINDOWS; NOT_AN_ABSOLUTE_FREE_TEXT_EQUIVALENCE_PROOF"}
        after, current_limit = measure(projection)
        projection["measurement"] = {"before_reserved": before, "after_reserved": after, "limit": current_limit,
                                     "token_method": method, "actual_provider_tokens": None}
        if after <= current_limit:
            return projection
        if receipt["fast_path"] or semantic and receipt["effective_material_target_tokens"] > target:
            raise KernelError("TASK_CONTEXT_COMPRESSION_NO_PROGRESS", "All remaining source expression is required or already verified; the complete request still exceeds capacity",
                              details={"projection": projection})
        working = [replace(by_id[item.asset_version_id], context_class=ContextClass.PROTECTED)
                   if item.asset_version_id in raw_required_ids or by_id[item.asset_version_id].safe_summary == item.safe_summary and by_id[item.asset_version_id].compression_trace
                   else item for item in candidates]
        next_target = target - max(1, after - current_limit)
        if not semantic:
            next_target = min(next_target, target * 3 // 4)
        if next_target <= 0:
            raise KernelError("TASK_CONTEXT_COMPRESSION_NO_PROGRESS", "Verified source restoration leaves no remaining capacity; retain completed Effects",
                              details={"projection": projection})
        target = next_target
    raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "necessary content and complete request overhead cannot fit the selected capacity")


def protected_expression_quotes(value: Any, *, include_working_observations: bool = False) -> tuple[str, ...]:
    quotes = set()
    def visit(item):
        if isinstance(item, dict):
            if include_working_observations and item.get("version") in ("working-observations.v1", "working-observations-provider.v1", "working-observations-packet.v2", "working-observations-provider.v2") and item.get("authority") == "UNREVIEWED_WORKING_OBSERVATIONS":
                for entry in item.get("entries") or []:
                    quote = (entry.get("location") or {}).get("quote")
                    if quote and quote == entry.get("quote") and (entry.get("source") or {}).get("asset_version_id"):
                        quotes.add(quote)
            for key, child in item.items():
                if key == "preserve_quotes" and isinstance(child, list):
                    quotes.update(text for text in child if isinstance(text, str) and text)
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return tuple(sorted(quotes))


def compression_task_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ({"source_projection_hash": narrative_hash(child), "delivery": "ORIGINAL_SOURCE_UNITS_PER_CHUNK"}
                if key in {"working_manuscript", "working_memory", "source_history"} else compression_task_context(child))
                for key, child in value.items()}
    if isinstance(value, list):
        return [compression_task_context(child) for child in value]
    return deepcopy(value)
