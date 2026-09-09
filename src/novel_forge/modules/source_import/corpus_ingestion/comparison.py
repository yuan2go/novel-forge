from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any


def score_hashes(a: list[str], b: list[str], size: int = 128) -> float:
    left, right = set(a), set(b)
    union = sorted(left | right)[:size]
    return sum(v in left and v in right for v in union) / len(union) if union else 0.0


def compare_versions(left: dict[str, Any], right: dict[str, Any], *, after: int = 0, limit: int = 200) -> dict[str, Any]:
    if not 0 <= after <= 20000 or not 1 <= limit <= 500:
        raise ValueError("comparison page must be bounded")
    lu, ru = left["assessment"]["units"], right["assessment"]["units"]
    if max(len(lu), len(ru)) > 10000:
        raise ValueError("processing unit contract exceeds comparison bound")
    matched: dict[int, tuple[int, str]] = {}
    used: set[int] = set()
    for field in ("hash", "body_hash"):
        index: dict[str, deque[int]] = defaultdict(deque)
        for j, unit in enumerate(ru):
            if j not in used and unit.get(field):
                index[unit[field]].append(j)
        for i, unit in enumerate(lu):
            if i not in matched and unit.get(field) and index[unit[field]]:
                j = index[unit[field]].popleft()
                matched[i] = (j, "EXACT_UNIT" if field == "hash" else "EXACT_BODY")
                used.add(j)
    index_keys: dict[tuple[str, str], list[int]] = defaultdict(list)
    if left.get("edition_id") == right.get("edition_id") and left.get("edition_id"):
        for j, unit in enumerate(ru):
            index_keys[(unit.get("source_file_key", ""), unit.get("source_key", ""))].append(j)
        for i, unit in enumerate(lu):
            key = (unit.get("source_file_key", ""), unit.get("source_key", ""))
            candidates = index_keys[key]
            if i not in matched and all(key) and len(candidates) == 1 and candidates[0] not in used:
                matched[i] = (candidates[0], "EXACT_SOURCE_KEY")
                used.add(candidates[0])
    buckets: dict[str, list[int]] = defaultdict(list)
    for j, unit in enumerate(ru):
        for value in unit.get("match_fingerprint", [])[:4]:
            if len(buckets[value]) < 8:
                buckets[value].append(j)
    near_evaluated = 0
    for i, unit in enumerate(lu):
        if i in matched:
            continue
        candidates = sorted({j for v in unit.get("match_fingerprint", [])[:4] for j in buckets[v] if j not in used})[:8]
        scores = sorted(((score_hashes(unit.get("match_fingerprint", []), ru[j].get("match_fingerprint", []), 16), j) for j in candidates), reverse=True)
        near_evaluated += len(scores)
        if scores and scores[0][0] >= 0.8 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
            matched[i] = (scores[0][1], "BOUNDED_SIMILARITY_CANDIDATE")
            used.add(scores[0][1])
    events = []
    left_counts = Counter(u.get("body_hash", u["hash"]) for u in lu)
    right_counts = Counter(u.get("body_hash", u["hash"]) for u in ru)
    for i, unit in enumerate(lu):
        if i not in matched:
            events.append({"left": i, "left_id": unit["unit_id"], "right": None, "changes": ["MISSING_OR_UNALIGNED"], "basis": "NO_RELIABLE_CORRESPONDENCE"})
            continue
        j, basis = matched[i]
        other = ru[j]
        changes = []
        if unit["hash"] != other["hash"]:
            changes.append("TITLE_OR_FORMAT_CHANGED" if unit.get("body_hash") and unit.get("body_hash") == other.get("body_hash") else "MODIFIED")
        if unit["title"] != other["title"]:
            changes.append("TITLE_CHANGED")
        if i != j or unit.get("volume") != other.get("volume"):
            changes.append("MOVED")
        if left_counts[unit.get("body_hash", unit["hash"])] > 1 or right_counts[other.get("body_hash", other["hash"])] > 1:
            changes.append("DUPLICATE_OCCURRENCE")
        events.append({"left":i, "right":j, "left_id":unit["unit_id"], "right_id":other["unit_id"], "left_volume":unit.get("volume"), "right_volume":other.get("volume"), "changes":changes or ["SAME"], "basis":basis})
    events.extend({"left":None,"right":j,"right_id":unit["unit_id"],"changes":["ADDED_OR_UNALIGNED"],"basis":"NO_RELIABLE_CORRESPONDENCE"} for j,unit in enumerate(ru) if j not in used)
    a, b = Counter(u["hash"] for u in lu), Counter(u["hash"] for u in ru)
    page = events[after:after+limit]
    return {
        "policy":"corpus-version-comparison.v2", "similarity_estimate":score_hashes(left["fingerprint"]["hashes"],right["fingerprint"]["hashes"]),
        "exact_text":left["normalized_hash"]==right["normalized_hash"],
        "exact_body":bool(left["assessment"].get("body_sequence_hash")) and left["assessment"].get("body_sequence_hash")==right["assessment"].get("body_sequence_hash"),
        "exact_structure":[(u.get("volume"),u["title"],u["hash"]) for u in lu]==[(u.get("volume"),u["title"],u["hash"]) for u in ru],
        "same_edition":bool(left.get("edition_id")) and left.get("edition_id")==right.get("edition_id"),
        "exact_unit_hashes":sorted((a&b)), "left_only_hashes":sorted((a-b)),"right_only_hashes":sorted((b-a)),
        "unit_multiplicity_differences":[{"hash":h,"left":a[h],"right":b[h]} for h in sorted(a.keys()|b.keys()) if a[h]!=b[h]][:500],
        "correspondence":page,"total_correspondences":len(events),"next_after":after+limit if after+limit<len(events) else None,
        "change_counts":dict(Counter(c for e in events for c in e["changes"])),"near_candidates_evaluated":near_evaluated,
        "alignment_limitations":"Exact occurrences first; local keys only within one Edition; bounded similarity is tentative, not proof of identity.",
        "ordered_titles_equal":[u["title"] for u in lu]==[u["title"] for u in ru],
        "equivalence":"CANDIDATE_ONLY","rights_transfer":False,"transitive_merge":False,
    }
