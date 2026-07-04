from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any


def check_quote_leakage(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = _normalize(str(payload.get("candidate_text") or payload.get("text") or ""))
    sources = [str(item) for item in payload.get("source_texts") or [] if str(item).strip()]
    if payload.get("source_text"):
        sources.append(str(payload.get("source_text")))
    exact_hits: list[dict[str, Any]] = []
    near_hits: list[dict[str, Any]] = []
    min_chars = int(payload.get("min_chars", 18) or 18)
    for index, source in enumerate(sources):
        normalized_source = _normalize(source)
        if not normalized_source:
            continue
        for span in _source_spans(normalized_source, min_chars=min_chars):
            if span and span in candidate:
                exact_hits.append(_hit(index, span, "exact_quote_reuse"))
                break
        ratio = SequenceMatcher(None, candidate[:400], normalized_source[:400]).ratio() if candidate and normalized_source else 0.0
        if ratio >= float(payload.get("near_duplicate_threshold", 0.82)):
            near_hits.append({"source_index": index, "kind": "near_duplicate", "similarity": round(ratio, 4), "source_hash": _hash(normalized_source)})
    passed = not exact_hits and not near_hits
    return {
        "passed": passed,
        "leakage_risk": "low" if passed else "critical",
        "exact_hits": exact_hits,
        "near_hits": near_hits,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "reported_text_snippets": False},
    }


def _source_spans(text: str, *, min_chars: int) -> list[str]:
    spans: list[str] = []
    for sentence in re.split(r"[。！？!?；;。\n]", text):
        sentence = sentence.strip()
        if len(sentence) >= min_chars:
            spans.append(sentence[:120])
    if not spans and len(text) >= min_chars:
        spans.append(text[:120])
    return spans


def _hit(index: int, span: str, kind: str) -> dict[str, Any]:
    return {"source_index": index, "kind": kind, "span_hash": _hash(span), "span_length": len(span)}


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\[\]{}<>《》]+", "", text or "")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
