from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import re
from typing import Any, Mapping, Sequence
import unicodedata

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.story_planning_runtime.domain import canonical_hash

CONTRACT_VERSION = "working-task-passage-retrieval.v1"
_SCORE_SCALE = 1_000_000
_CJK = r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f]"
_LEXEMES = re.compile(_CJK + r"+|[a-z0-9]+(?:['’-][a-z0-9]+)*")
_STOP_WORDS = frozenset((
    "a an the and or but if then than as at by for from in into of on onto to with without "
    "is are was were be been being do does did have has had it its this that these those "
    "he him his she her hers they them their we us our you your i me my who what when "
    "where why how can could may might must shall should will would not no yes also "
    "very just only some any each all both other another already now next previous "
    "chapter scene task goal objective character subject event object place ref id "
    "continue continues continuing continued discuss discussing conversation story write writing"
).split())
_CJK_STOP_WORDS = frozenset((
    "一个 一些 这个 那个 这些 那些 他们 她们 我们 你们 自己 他的 她的 它的 "
    "已经 现在 然后 于是 还是 但是 因为 所以 如果 什么 怎么 为何 如何 是否 "
    "进行 相关 内容 情况 本章 章节 场景 任务 目标 继续 讨论 对话 人物 主角"
).split())
_CJK_STOP_PATTERN = re.compile("|".join(sorted(_CJK_STOP_WORDS, key=lambda value: (-len(value), value))))
_WEIGHTS = {"goal": 1, "queries": 2, "event_refs": 4, "object_refs": 4, "place_refs": 3}
_REF_KINDS = frozenset({"event_refs", "object_refs", "place_refs"})


@dataclass(frozen=True)
class _Query:
    identity: str
    scope: str
    kind: str
    text: str
    match_text: str
    terms: frozenset[str]
    subject_terms: frozenset[str]


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


@lru_cache(maxsize=4096)
def _token_items(text: str, source: bool) -> tuple[tuple[str, int], ...]:
    result: Counter[str] = Counter()
    for match in _LEXEMES.finditer(_normalized(text)):
        word = match.group()
        if re.fullmatch(_CJK + "+", word):
            for fragment in _CJK_STOP_PATTERN.split(word):
                sizes = (1, 2, 3) if source else (1,) if len(fragment) == 1 else (2, 3)
                for size in sizes:
                    result.update(fragment[index:index + size] for index in range(len(fragment) - size + 1))
        elif word not in _STOP_WORDS and not word.isdecimal():
            result[word] += 1
    return tuple(result.items())


def _tokens(text: str, *, source: bool = False) -> Counter[str]:
    return Counter(dict(_token_items(text, source)))


def _strings(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise KernelError("WORKING_TASK_RETRIEVAL_INVALID", f"{field} requires literal query strings")
    return [item.strip() for item in value if item.strip()]


def _query_catalog(task: Mapping[str, Any]) -> list[_Query]:
    scenes = task.get("scenes", [])
    if not isinstance(scenes, (list, tuple)) or any(not isinstance(scene, Mapping) for scene in scenes):
        raise KernelError("WORKING_TASK_RETRIEVAL_INVALID", "Task scenes require scoped mappings")
    scopes = [("", "task", task)] + [(f"scenes/{index}/", f"scene:{index}:{scene.get('scene_id', '')}", scene)
        for index, scene in enumerate(scenes)]
    subjects = sorted({_normalized(subject) for _, _, source in scopes
        for subject in _strings(source.get("subjects"), "subjects")}, key=lambda value: (-len(value), value))
    subject_terms = frozenset(term for subject in subjects for term in _tokens(subject))
    result = []
    for prefix, scope, source in scopes:
        goal = source.get("goal", "")
        if not isinstance(goal, str):
            raise KernelError("WORKING_TASK_RETRIEVAL_INVALID", "Task goal requires frozen text")
        for kind in _WEIGHTS:
            values = [goal] if kind == "goal" else _strings(source.get(kind), prefix + kind)
            for index, text in enumerate(values):
                if not text.strip():
                    continue
                normalized = _normalized(text)
                if kind not in _REF_KINDS:
                    for subject in subjects:
                        if re.search(_CJK, subject):
                            normalized = normalized.replace(subject, " ")
                        else:
                            normalized = re.sub(r"(?<![a-z0-9])" + re.escape(subject) + r"(?![a-z0-9])", " ", normalized)
                terms = frozenset(_tokens(normalized))
                if kind not in _REF_KINDS:
                    terms -= subject_terms
                if terms:
                    result.append(_Query(prefix + kind + (f"/{index}" if kind != "goal" else ""),
                        scope, kind, text, " ".join(normalized.split()), terms, subject_terms))
    return result


def _source_units(units: Sequence[tuple[int, int, int, str]], task: Mapping[str, Any]) -> list[tuple[int, int, int, str]]:
    selected: dict[tuple[int, int, int], str] = {}
    target = task.get("target_chapter")
    if target is not None and (type(target) is not int or target < 1):
        raise KernelError("WORKING_TASK_RETRIEVAL_INVALID", "Task target must be a positive chapter")
    for unit in units:
        if not isinstance(unit, (tuple, list)) or len(unit) != 4:
            raise KernelError("WORKING_TASK_RETRIEVAL_RANGE_INVALID", "Require chapter, start, end and exact source text")
        chapter, start, end, text = unit
        if (any(type(value) is not int for value in (chapter, start, end)) or chapter < 1
                or start < 0 or start >= end or not isinstance(text, str) or end - start != len(text)
                or target is not None and chapter >= target):
            raise KernelError("WORKING_TASK_RETRIEVAL_RANGE_INVALID", "Historical passage must retain its Unicode codepoint range")
        key = (chapter, start, end)
        if key in selected and selected[key] != text:
            raise KernelError("WORKING_TASK_RETRIEVAL_RANGE_INVALID", "A source coordinate cannot identify different text")
        selected[key] = text
    ordered = [(*key, text) for key, text in sorted(selected.items())]
    for previous, current in zip(ordered, ordered[1:]):
        if previous[0] == current[0] and previous[2] > current[1]:
            raise KernelError("WORKING_TASK_RETRIEVAL_RANGE_INVALID", "Source paragraph units cannot overlap")
    return ordered


def _rank_candidates(units: list[tuple[int, int, int, str]], queries: list[_Query]) -> list[dict[str, Any]]:
    if not units or not queries:
        return []
    vocabulary = set().union(*(query.terms for query in queries))
    documents = [_tokens(unit[3], source=True) for unit in units]
    frequency = Counter(term for document in documents for term in vocabulary.intersection(document))
    size = Decimal(len(documents))
    average = Decimal(sum(sum(document.values()) for document in documents)) / size or Decimal(1)
    idf = {term: (1 + (size - frequency[term] + Decimal("0.5")) / (frequency[term] + Decimal("0.5"))).ln()
        for term in sorted(vocabulary)}
    result = []
    for unit, document in zip(units, documents, strict=True):
        normalized = " ".join(_normalized(unit[3]).split())
        length = Decimal(sum(document.values()))
        norm = Decimal("1.2") * (Decimal("0.25") + Decimal("0.75") * length / average)
        term_scores = {term: idf[term] * document[term] * Decimal("2.2") / (document[term] + norm)
            for term in sorted(vocabulary.intersection(document))}
        scores, matched = {}, set()
        for query in queries:
            common = query.terms.intersection(term_scores)
            if not common:
                continue
            exact = bool(query.match_text and query.match_text in normalized)
            if query.kind in _REF_KINDS and not exact and common <= query.subject_terms:
                continue
            if query.kind not in _REF_KINDS and len(documents) > 3 and len(query.terms) == 1 and all(frequency[term] * 2 > len(documents) for term in common):
                continue
            if query.kind not in _REF_KINDS and not exact and len(documents) > 3:
                if len(common) < 2 and len(query.terms) > 1 and all(frequency[term] * 2 > len(documents) for term in common):
                    continue
                if query.kind == "goal" and len(common) * 2 < len(query.terms) and all(frequency[term] * 3 > len(documents) * 2 for term in common):
                    continue
            score = sum(term_scores[term] for term in sorted(common)) / sum(idf[term] for term in sorted(query.terms))
            score *= _WEIGHTS[query.kind] * _SCORE_SCALE
            if exact:
                score *= Decimal("1.25")
            quantized = int(score.to_integral_value(rounding=ROUND_HALF_EVEN))
            if quantized > 0:
                scores[query.identity] = quantized
                matched.update(common)
        if scores:
            result.append({"unit": unit, "scores": scores, "terms": matched,
                "score": max(scores.values()) + sum(scores.values()) // len(scores)})
    return result


def select_task_passages(units: Sequence[tuple[int, int, int, str]], *, task: Mapping[str, Any],
                         limit: int = 12, per_chapter: int = 3) -> dict[str, Any]:
    if not isinstance(task, Mapping) or type(limit) is not int or limit < 0 or type(per_chapter) is not int or per_chapter < 1:
        raise KernelError("WORKING_TASK_RETRIEVAL_INVALID", "Require a frozen task and nonnegative retrieval selection limits")
    task_hash = canonical_hash({key: value for key, value in task.items() if key != "task_hash"})
    if "task_hash" in task and task["task_hash"] != task_hash:
        raise KernelError("WORKING_TASK_RETRIEVAL_IDENTITY_INVALID", "Task hash differs from its frozen source bindings and fields")
    ordered = _source_units(units, task)
    queries = _query_catalog(task)
    from .derived_cache import task_selection_cache
    source_hash = canonical_hash([{"chapter": chapter, "start": start, "end": end, "text_hash": prose_hash(text)}
        for chapter, start, end, text in ordered])
    cache_key = (CONTRACT_VERSION, task_hash, source_hash, limit, per_chapter)
    cached = task_selection_cache.get(cache_key)
    if cached is not None:
        return cached
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        candidates = _rank_candidates(ordered, queries)
    by_query = {query.identity: query for query in queries}
    pending = list(candidates)
    selected, covered_queries, covered_scopes = [], set(), set()
    chapter_counts: Counter[int] = Counter()
    while pending and len(selected) < limit:
        eligible = [row for row in pending if chapter_counts[row["unit"][0]] < per_chapter]
        if not eligible:
            break
        def priority(row):
            novel = set(row["scores"]) - covered_queries
            scopes = {by_query[identity].scope for identity in row["scores"]} - covered_scopes
            marginal = row["score"] + 2 * max((row["scores"][identity] for identity in novel), default=0)
            marginal = marginal * 2 // (2 + chapter_counts[row["unit"][0]])
            return (bool(scopes), bool(novel), marginal, row["score"], row["unit"][0], -row["unit"][1])
        chosen = max(eligible, key=priority)
        identities = set(chosen["scores"])
        scopes = {by_query[identity].scope for identity in identities}
        reason = "TASK_SCOPE_COVERAGE" if scopes - covered_scopes else "QUERY_COVERAGE" if identities - covered_queries else "DIVERSE_RELEVANT_PASSAGE"
        chapter, start, end, text = chosen["unit"]
        selected.append({"chapter": chapter, "start": start, "end": end, "text_hash": prose_hash(text),
            "score": chosen["score"], "matched_queries": sorted(identities), "matched_terms": sorted(chosen["terms"]),
            "selection_reason": reason, "selection_rank": len(selected) + 1})
        covered_queries.update(identities)
        covered_scopes.update(scopes)
        chapter_counts[chapter] += 1
        pending.remove(chosen)
    result = {"contract_version": CONTRACT_VERSION, "task_hash": task_hash,
        "source_units_hash": source_hash,
        "selection_policy": {"limit": limit, "per_chapter": per_chapter, "score_scale": _SCORE_SCALE},
        "input_unit_count": len(ordered), "candidate_count": len(candidates),
        "queries": [{"query_id": query.identity, "scope": query.scope, "kind": query.kind, "text": query.text} for query in queries],
        "selected": sorted(selected, key=lambda row: (row["chapter"], row["start"], row["end"])),
        "omitted_candidate_count": len(candidates) - len(selected), "semantic_completeness": "NOT_ESTABLISHED"}
    result = {**result, "selection_hash": canonical_hash(result)}
    task_selection_cache.put(cache_key, result)
    return result


def select_task_observations(entries: Sequence[Mapping[str, Any]], *, task: Mapping[str, Any]) -> dict[str, Any]:
    from .derived_cache import task_selection_cache
    version = "working-task-observation-relevance.v1"
    task_hash, input_hash = task.get("task_hash") or canonical_hash(task), canonical_hash(entries)
    key = (version, task_hash, input_hash)
    cached = task_selection_cache.get(key)
    if cached is not None:
        return cached
    queries = _query_catalog(task)
    documents = ["\n".join(entry[field] for field in ("state_key", "claim", "quote")) for entry in entries]
    ranking_projection_units = [(entry["source"]["chapter"], index, index + len(document), document)
        for index, (entry, document) in enumerate(zip(entries, documents, strict=True))]
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        candidates = _rank_candidates(ranking_projection_units, queries)
    selected, covered = set(), []
    for query in queries:
        matching = [row for row in candidates if query.identity in row["scores"]]
        if not matching:
            continue
        best = max(matching, key=lambda row: (row["scores"][query.identity], row["unit"][0],
            -entries[row["unit"][1]]["location"]["start"]))
        identity = entries[best["unit"][1]]["observation_id"]
        selected.add(identity)
        covered.append({"query_id": query.identity, "observation_id": identity, "score": best["scores"][query.identity]})
    body = {"version": version, "task_hash": task_hash, "input_hash": input_hash,
        "candidate_count": len(entries), "selected_ids": sorted(selected), "query_support": covered,
        "unmatched_queries": [query.identity for query in queries if query.identity not in {row["query_id"] for row in covered}],
        "semantic_completeness": "NOT_ESTABLISHED"}
    result = {**body, "selection_hash": canonical_hash(body)}
    task_selection_cache.put(key, result)
    return result
