from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping, Sequence

from .prose_review import completion_digest


def evidence_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.casefold()))
    for phrase in re.findall(r"[\u3400-\u9fff]{3,}", text):
        for size in (3, 4):
            terms.update(
                phrase[start : start + size] for start in range(len(phrase) - size + 1)
            )
    return terms


def relation_windows(
    sources: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    width = policy["window_codepoints"] // 2
    if width < 8:
        return [], {
            "status": "INSUFFICIENT_WINDOW",
            "global_relationships_verified": False,
        }
    spans, index = [], defaultdict(list)
    for source, record in zip(sources, records, strict=True):
        for start in range(0, len(source["text"]), width):
            text = source["text"][start : start + width]
            span_id = len(spans)
            spans.append(
                {**record, "start": start, "end": start + len(text), "text": text}
            )
            for term in sorted(evidence_terms(text)):
                index[term].append(span_id)
    pairs: dict[tuple[int, int], list[str]] = defaultdict(list)
    excluded_common = 0
    for term, occurrences in sorted(index.items()):
        if len(occurrences) > 16:
            excluded_common += 1
            continue
        for position, left in enumerate(occurrences):
            for right in occurrences[position + 1 :]:
                if (
                    abs(spans[left]["chapter_number"] - spans[right]["chapter_number"])
                    > 1
                ):
                    pairs[(left, right)].append(term)
    ordered = sorted(pairs, key=lambda pair: (-len(pairs[pair]), pair))
    windows = []
    for left, right in ordered[: policy["relation_window_limit"]]:
        evidence = [spans[left], spans[right]]
        hypothesis = {
            "schema_version": "prose-relation-hypothesis.v1",
            "basis": "SHARED_TEXT_ANCHORS",
            "anchors": pairs[(left, right)][:16],
            "status": "UNVERIFIED",
            "confidence": None,
            "uncertainty": "Lexical recurrence may be intentional, incidental, or unrelated; assess both exact passages.",
            "hard_dependency_created": False,
        }
        hypothesis["hypothesis_id"] = completion_digest(
            {"evidence": evidence, "hypothesis": hypothesis}
        )
        body = {
            "spans": evidence,
            "policy": dict(policy),
            "relation_hypothesis": hypothesis,
        }
        windows.append(
            {
                "window_id": completion_digest(body),
                "spans": evidence,
                "relation_hypothesis": hypothesis,
            }
        )
    return windows, {
        "status": "BOUNDED_ANCHOR_RETRIEVAL",
        "candidate_pairs": len(ordered),
        "selected_pairs": len(windows),
        "unreviewed_candidate_pairs": max(0, len(ordered) - len(windows)),
        "excluded_frequent_anchors": excluded_common,
        "uncovered_relation_classes": [
            "NO_SHARED_TEXT_ANCHOR",
            "SYNONYM_ONLY",
            "MORE_THAN_TWO_PASSAGES",
            "EXCLUDED_FREQUENT_ANCHORS",
        ],
        "global_relationships_verified": False,
    }
