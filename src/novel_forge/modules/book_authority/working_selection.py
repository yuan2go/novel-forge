from collections import defaultdict
from functools import lru_cache
import re
from typing import Any, Mapping

from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

from .task_retrieval import select_task_passages


def task_passage_ranges(text: str, max_characters: int) -> list[tuple[int, int]]:
    return list(_task_passage_ranges(text, max_characters))


@lru_cache(maxsize=64)
def _task_passage_ranges(text: str, max_characters: int) -> tuple[tuple[int, int], ...]:
    if type(max_characters) is not int or not 64 <= max_characters <= 8000:
        raise KernelError("WORKING_PROSE_POLICY_INVALID", "Source passage granularity requires a positive Unicode length")
    cuts = [0, *(match.end() for match in re.finditer(r"(?:\r\n|\r|\n)(?:[ \t]*(?:\r\n|\r|\n))*[ \t]*", text)), len(text)]
    ranges = []
    for start, end in zip(cuts, cuts[1:]):
        while end - start > max_characters:
            window = text[start:start+max_characters]
            boundaries = [match.end() for match in re.finditer(r"[。！？!?；;][\"”’」』]*|[.](?=\s)|\s+", window)
                if match.end() >= max_characters // 2]
            cut = start + (boundaries[-1] if boundaries else max_characters)
            if text[cut-1:cut+1] == "\r\n":
                cut -= 1
            ranges.append((start, cut))
            start = cut
        if start < end:
            ranges.append((start, end))
    return tuple(ranges)


def select_working_context(sources: list[dict[str, Any]], *, target_chapter: int,
        policy: Mapping[str, Any], task: Mapping[str, Any] | None,
        memory: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(task, Mapping) or not task.get("task_hash"):
        raise KernelError("WORKING_TASK_REQUIRED", "Task projection requires its frozen planning source")
    by_chapter = {source["chapter"]: source for source in sources}
    units = [(source["chapter"], start, end, source["text"][start:end])
        for source in sources for start, end in task_passage_ranges(source["text"], policy["passage_characters"])]
    grouped: dict[int, list[tuple[int, int, int, str]]] = defaultdict(list)
    for unit in units:
        grouped[unit[0]].append(unit)
    retrieved = select_task_passages(
        [unit for unit in units if unit[0] >= target_chapter - policy["history_chapters"]],
        task=task, limit=policy["retrieval_passages"], per_chapter=policy["retrieval_per_chapter"])
    reasons: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    for number, start, end, _ in units:
        if number >= target_chapter - policy["recent_complete_chapters"]:
            reasons[(number, start, end)].add("EXPLICIT_COMPLETE_RECENT")
    tail = [unit for unit in units if unit[0] == target_chapter - 1][-policy["recent_tail_paragraphs"]:]
    for number, start, end, _ in tail:
        reasons[(number, start, end)].add("PREDECESSOR_ENDING")
    for row in retrieved["selected"]:
        reasons[(row["chapter"], row["start"], row["end"])].add("TASK_RETRIEVAL")
    for entry in (memory or {}).get("entries", []):
        location, number = entry["location"], entry["source"]["chapter"]
        for n, start, end, _ in grouped.get(number, []):
            if start < location["end"] and location["start"] < end:
                reasons[(n, start, end)].add("LOCATED_MEMORY_OR_CAUSE")
    seeds = set(reasons)
    for chapter_units in grouped.values():
        for index, (number, start, end, _) in enumerate(chapter_units):
            if (number, start, end) not in seeds:
                continue
            for n, low, high, _ in chapter_units[max(0, index-policy["neighbor_paragraphs"]):index+policy["neighbor_paragraphs"]+1]:
                if (n, low, high) not in seeds:
                    reasons[(n, low, high)].add("SUPPORTING_NEIGHBOR")
    passages = [{"chapter": number, "asset_version_id": by_chapter[number]["asset_version_id"],
        "start": start, "end": end, "text_hash": text_hash(by_chapter[number]["text"][start:end]),
        "reasons": sorted(reason)} for (number, start, end), reason in sorted(reasons.items())]
    body = {"contract_version": "working-task-selection.v1", "task_hash": task["task_hash"],
        "policy_hash": canonical_hash(policy), "retrieval": retrieved, "passages": passages,
        "boundary": "LOCATED_EXCERPTS_NOT_COMPLETE_SEMANTIC_MEMORY"}
    return {**body, "selection_hash": canonical_hash(body)}


def selected_memory_ranges(selection: Mapping[str, Any]) -> dict[str, list[dict[str, int]]]:
    ranges: dict[str, list[dict[str, int]]] = defaultdict(list)
    for passage in selection["passages"]:
        ranges[passage["asset_version_id"]].append({"start": passage["start"], "end": passage["end"]})
    return dict(ranges)


def validate_working_selection(snapshot: Mapping[str, Any]) -> None:
    from .task_retrieval import CONTRACT_VERSION, _query_catalog, _tokens

    def digest(value: Any) -> bool:
        return (isinstance(value, str) and len(value) == 71 and value.startswith("sha256:")
            and set(value[7:]) <= set("0123456789abcdef"))

    def ordered_strings(value: Any) -> bool:
        return (isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
            and value == sorted(set(value)))

    task, policy = snapshot.get("retrieval_task"), snapshot.get("projection_policy")
    selection = snapshot.get("context_selection")
    if (not isinstance(task, Mapping) or not isinstance(policy, Mapping) or not isinstance(selection, Mapping)
            or set(selection) != {"contract_version", "task_hash", "policy_hash", "retrieval", "passages", "boundary", "selection_hash"}
            or selection.get("contract_version") != "working-task-selection.v1"
            or selection.get("task_hash") != task.get("task_hash")
            or selection.get("policy_hash") != canonical_hash(policy)
            or selection.get("boundary") != "LOCATED_EXCERPTS_NOT_COMPLETE_SEMANTIC_MEMORY"
            or selection.get("selection_hash") != canonical_hash({key: value for key, value in selection.items() if key != "selection_hash"})
            or not isinstance(selection.get("passages"), list)
            or not isinstance(selection.get("retrieval"), Mapping)
            or selection["retrieval"].get("task_hash") != selection["task_hash"]):
        raise KernelError("WORKING_SELECTION_INVALID", "Selected context requires its exact task and source receipt")
    retrieval = selection["retrieval"]
    if (set(retrieval) != {"contract_version", "task_hash", "source_units_hash", "selection_policy", "input_unit_count",
            "candidate_count", "queries", "selected", "omitted_candidate_count", "semantic_completeness", "selection_hash"}
            or retrieval.get("contract_version") != CONTRACT_VERSION
            or not digest(retrieval.get("source_units_hash"))
            or retrieval.get("selection_hash") != canonical_hash({key: value for key, value in retrieval.items() if key != "selection_hash"})
            or retrieval.get("selection_policy") != {"limit": policy.get("retrieval_passages"),
                "per_chapter": policy.get("retrieval_per_chapter"), "score_scale": 1_000_000}
            or any(type(value) is not int for value in retrieval["selection_policy"].values())
            or any(type(retrieval.get(key)) is not int or retrieval[key] < 0
                for key in ("input_unit_count", "candidate_count", "omitted_candidate_count"))
            or not isinstance(retrieval.get("selected"), list)
            or not 0 <= len(retrieval["selected"]) <= retrieval["candidate_count"] <= retrieval["input_unit_count"]
            or retrieval["omitted_candidate_count"] != retrieval["candidate_count"] - len(retrieval["selected"])
            or len(retrieval["selected"]) > retrieval["selection_policy"]["limit"]
            or bool(retrieval["candidate_count"]) != bool(retrieval["selected"])
            or retrieval.get("semantic_completeness") != "NOT_ESTABLISHED"):
        raise KernelError("WORKING_SELECTION_INVALID", "Retrieval receipt requires its exact contract, hash, policy and selection counts")
    catalog = _query_catalog(task)
    if retrieval.get("queries") != [{"query_id": query.identity, "scope": query.scope, "kind": query.kind, "text": query.text} for query in catalog]:
        raise KernelError("WORKING_SELECTION_INVALID", "Retrieval queries must match the frozen task fields")
    queries = {query.identity: query for query in catalog}
    if not queries and retrieval["candidate_count"]:
        raise KernelError("WORKING_SELECTION_INVALID", "An empty retrieval task cannot produce lexical candidates")
    retrieved, ranks, chapter_counts = {}, set(), defaultdict(int)
    for row in retrieval["selected"]:
        if (not isinstance(row, Mapping) or set(row) != {"chapter", "start", "end", "text_hash", "score",
                "matched_queries", "matched_terms", "selection_reason", "selection_rank"}
                or any(type(row.get(key)) is not int for key in ("chapter", "start", "end", "score", "selection_rank"))
                or not max(1, snapshot["target_chapter"] - policy["history_chapters"]) <= row["chapter"] < snapshot["target_chapter"]
                or not 0 <= row["start"] < row["end"] or row["score"] <= 0
                or not 1 <= row["selection_rank"] <= len(retrieval["selected"])
                or not digest(row.get("text_hash"))
                or not ordered_strings(row.get("matched_queries")) or not row["matched_queries"]
                or not set(row["matched_queries"]).issubset(queries)
                or not ordered_strings(row.get("matched_terms")) or not row["matched_terms"]
                or row.get("selection_reason") not in {"TASK_SCOPE_COVERAGE", "QUERY_COVERAGE", "DIVERSE_RELEVANT_PASSAGE"}):
            raise KernelError("WORKING_SELECTION_INVALID", "Every retrieval hit requires its exact source range, query identities and rank")
        identity = (row["chapter"], row["start"], row["end"])
        chapter_counts[row["chapter"]] += 1
        if (identity in retrieved or row["selection_rank"] in ranks
                or chapter_counts[row["chapter"]] > retrieval["selection_policy"]["per_chapter"]):
            raise KernelError("WORKING_SELECTION_INVALID", "Retrieval hits require unique coordinates, ranks and the frozen chapter diversity policy")
        retrieved[identity] = row
        ranks.add(row["selection_rank"])
    if list(retrieved) != sorted(retrieved):
        raise KernelError("WORKING_SELECTION_INVALID", "Retrieval hits must retain chronological source order")
    projected = {source["asset_version_id"]: source for source in snapshot["sources"]}
    seen, delivered = set(), {}
    for item in selection["passages"]:
        if (not isinstance(item, Mapping)
                or set(item) != {"chapter", "asset_version_id", "start", "end", "text_hash", "reasons"}
                or not isinstance(item.get("asset_version_id"), str)
                or type(item.get("chapter")) is not int
                or type(item.get("start")) is not int or type(item.get("end")) is not int
                or not 0 <= item["start"] < item["end"]
                or not ordered_strings(item.get("reasons")) or not item["reasons"]
                or any(reason not in {"EXPLICIT_COMPLETE_RECENT", "PREDECESSOR_ENDING", "TASK_RETRIEVAL",
                    "LOCATED_MEMORY_OR_CAUSE", "SUPPORTING_NEIGHBOR"} for reason in item["reasons"])):
            raise KernelError("WORKING_SELECTION_INVALID", "Every selected passage requires exact positions and selection reasons")
        identity = (item["asset_version_id"], item["start"], item["end"])
        source = projected.get(item["asset_version_id"])
        if identity in seen or source is None or source["chapter"] != item["chapter"]:
            raise KernelError("WORKING_SELECTION_INVALID", "Selection source differs from its frozen prose")
        seen.add(identity)
        text = next((p["text"][item["start"]-p["start"]:item["end"]-p["start"]]
            for p in source["passages"] if p["start"] <= item["start"] < item["end"] <= p["end"]), None)
        if text is None or text_hash(text) != item["text_hash"]:
            raise KernelError("WORKING_SELECTION_INVALID", "Selected ranges must reconstruct the exact delivered prose")
        coordinate = (item["chapter"], item["start"], item["end"])
        if coordinate in delivered or ("TASK_RETRIEVAL" in item["reasons"]) != (coordinate in retrieved):
            raise KernelError("WORKING_SELECTION_INVALID", "Every retrieval hit must match one delivered passage and its selection reason")
        delivered[coordinate] = item
        if coordinate in retrieved:
            hit = retrieved[coordinate]
            terms = set(_tokens(text, source=True))
            expected_terms = set().union(*(queries[identity].terms.intersection(terms) for identity in hit["matched_queries"]))
            if (hit["text_hash"] != item["text_hash"] or hit["matched_terms"] != sorted(expected_terms)
                    or any(not queries[identity].terms.intersection(terms) for identity in hit["matched_queries"])):
                raise KernelError("WORKING_SELECTION_INVALID", "Retrieval evidence must match the literal delivered passage and task terms")
    if not set(retrieved).issubset(delivered) or list(delivered) != sorted(delivered):
        raise KernelError("WORKING_SELECTION_INVALID", "Selection receipt must deliver every retrieval hit in chronological order")
    for source in snapshot["sources"]:
        selected = sorted((item["start"], item["end"]) for item in selection["passages"]
            if item["asset_version_id"] == source["asset_version_id"])
        for passage in source["passages"]:
            spans = [(start, end) for start, end in selected if passage["start"] <= start < end <= passage["end"]]
            if (not spans or spans[0][0] != passage["start"] or spans[-1][1] != passage["end"]
                    or any(left[1] != right[0] for left, right in zip(spans, spans[1:]))):
                raise KernelError("WORKING_SELECTION_INVALID", "Every delivered passage requires a complete selection receipt")
