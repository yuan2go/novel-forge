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


CAPACITY_POLICY = "complete-request-capacity.v1"
_HISTORY_TYPES = frozenset({"narrative_retrieval_document", "chapter_episodic_summary", "scene_episodic_summary", "character_timeline", "relationship_timeline"})


def recompose_capacity_context(original: dict, upgrade: Mapping[str, Any]) -> tuple[dict, dict]:
    if (upgrade.get("transport_projection") != "chapter-complete-request-capacity.v1"
            or upgrade.get("target_context_policy_ref") != "context-policy:chapter-generation-pack:v3"
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


def historical_expression_paths(data: Any) -> dict[tuple, str]:
    result = {}

    def visit(value, path=()):
        if isinstance(value, dict):
            if isinstance(value.get("projection_policy"), dict) and isinstance(value.get("sources"), list):
                policy = value["projection_policy"]
                recent = int(value.get("target_chapter") or 0) - int(policy.get("recent_complete_chapters") or 0)
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
    allowed = historical_expression_paths(data)
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
        target[path[-1]] = "\n\n".join(pieces)
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
    if candidate.compression_trace:
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


def prepare_request_capacity(
    *, original: dict, stage: str, source_boundary: dict, route: Any,
    measure: Callable[[dict | None], tuple[int, int]],
    model_call: Callable[[str, dict], Mapping[str, Any]],
    chunk_fits: Callable[[dict], bool],
    preserve_quotes: tuple[str, ...] = (),
    capacity_bindings: dict | None = None,
) -> dict | None:
    before, limit = measure(None)
    if before <= limit:
        return None
    method = route.token_accounting_method
    if method not in TOKENIZER_METHODS and route.model_profile.model_provider != "scripted_provider_v2":
        raise KernelError("PROVIDER_CONTEXT_CAPACITY_UNCERTAIN", "a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression",
                          details={"upper_bound": before, "limit": limit, "actual_tokens": None})
    paths = dict(sorted(historical_expression_paths(original).items(),
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
        grouped.setdefault(parent, []).append((path, text))
    candidates_by_hash = {}
    locations = {}
    for parent, expressions in grouped.items():
        combined = "\n\n".join(text for _, text in expressions)
        origin = original
        for part in parent:
            origin = origin[part]
        identity = {key: origin[key] for key in ("asset_version_id", "content_hash", "chapter") if isinstance(origin, dict) and key in origin}
        digest = narrative_hash({"text": combined, "source": identity if identity.get("asset_version_id") and identity.get("content_hash") else list(parent)})
        candidate = candidates_by_hash.get(digest)
        if candidate is None:
            candidate = ContextCandidate(asset_version_id="historical-expression:" + digest.split(":")[-1],
                asset_type="historical_expression_projection", project_id=source_boundary["project_id"],
                book_id=source_boundary["book_id"], estimated_tokens=1, relevance_score=1,
                safe_summary=combined, content_digest=narrative_hash(combined), compression_method="none",
                provenance={"frozen_input_boundary": source_boundary, "source_binding": source,
                    "original_expression_paths": [], "source_expression": identity})
            candidates_by_hash[digest] = candidate
        position = 0
        for path, text in expressions:
            candidate.provenance["original_expression_paths"].append(list(path))
            locations[path] = (candidate.asset_version_id, position, position + len(text))
            position += len(text) + 2
    candidates = list(candidates_by_hash.values())
    task = {"stage": stage, "frozen_input_boundary": source_boundary, "source_projection_hash": narrative_hash(original),
            "preserve_quotes": list(preserve_quotes), "task_context": compression_task_context(original.get("input_manifest") or {}), "capacity_policy": CAPACITY_POLICY,
            **({"capacity_bindings": capacity_bindings} if capacity_bindings else {}),
            "route_contract": {"provider": route.model_profile.model_provider, "model": route.model_profile.model_id,
                               "method": method, "evidence": route.token_accounting_evidence_ref,
                               "context_limit": route.model_context_limit, "output_limit": route.model_output_limit}}
    original_amount = sum(counter({"safe_summary": item.safe_summary, "structured_facts": []}) for item in candidates)
    empty = deepcopy(original)
    empty_projection = {"contract_version": CAPACITY_POLICY, "original_hash": narrative_hash(original),
        "source_boundary": source_boundary, "stage": stage, "compression_receipt": {}, "replacements": []}
    for path, text in paths.items():
        owner = empty
        for part in path[:-1]:
            owner = owner[part]
        owner[path[-1]] = ""
        empty_projection["replacements"].append({"path": list(path), "source_text_hash": narrative_hash(text), "ranges": []})
    empty_projection["result_hash"] = narrative_hash(empty)
    empty_reserved, _ = measure(empty_projection)
    target = (original_amount * max(1, limit - empty_reserved) // max(1, before - empty_reserved)
              if empty_reserved < limit else original_amount * 3 // 4)
    target = min(SYSTEM_CONTEXT_LIMIT, original_amount - 1,
                 max(sum(counter({"safe_summary": "", "structured_facts": []}) for _ in candidates) + 1, target))
    working = list(candidates)
    while target > 0:
        compressed, receipt = compile_task_context(working, task=task, token_budget=target,
            required_asset_types=(), model_call=model_call, compression_input_tokens=SYSTEM_CONTEXT_LIMIT,
            token_counter=counter, chunk_fits=chunk_fits, allow_restored_overflow=True, token_accounting_method=method)
        projection = {"contract_version": CAPACITY_POLICY, "original_hash": narrative_hash(original),
                      "source_boundary": source_boundary, "stage": stage, "replacements": [], "compression_receipt": receipt,
                      "target_basis": {"policy": "FULL_RENDERED_REMOVABLE_EXPRESSION", "empty_reserved": empty_reserved,
                          "expression_paths": len(paths), "unique_expression_sources": len(candidates)},
                      "retained_fidelity_traces": [trace for item in compressed for trace in item.compression_trace if trace not in receipt["compression_trace"]]}
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
            owner[path[-1]] = "\n\n".join(text[start:end] for start, end in ranges)
        projection["result_hash"] = narrative_hash(derived)
        after, current_limit = measure(projection)
        projection["measurement"] = {"before_reserved": before, "after_reserved": after, "limit": current_limit,
                                     "token_method": method, "actual_provider_tokens": None}
        if after <= current_limit:
            return projection
        if receipt["fast_path"]:
            raise KernelError("TASK_CONTEXT_COMPRESSION_NO_PROGRESS", "All remaining source expression is required or already verified; the complete request still exceeds capacity",
                              details={"projection": projection})
        working = [replace(by_id[item.asset_version_id], context_class=ContextClass.PROTECTED)
                   if by_id[item.asset_version_id].safe_summary == item.safe_summary and by_id[item.asset_version_id].compression_trace
                   else item for item in candidates]
        next_target = min(target - max(1, after - current_limit), target * 3 // 4)
        if next_target <= 0:
            raise KernelError("TASK_CONTEXT_COMPRESSION_NO_PROGRESS", "Verified source restoration leaves no remaining capacity; retain completed Effects",
                              details={"projection": projection})
        target = next_target
    raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "necessary content and complete request overhead cannot fit the selected capacity")


def protected_expression_quotes(value: Any) -> tuple[str, ...]:
    quotes = set()
    def visit(item):
        if isinstance(item, dict):
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
