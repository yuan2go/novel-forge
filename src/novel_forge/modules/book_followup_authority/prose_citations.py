from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

INDEXED_CITATION_CONTRACT = "indexed-prose-citation.v1"
BOUND_FIELDS = ("chapter_number", "asset_version_id", "text_hash", "start", "end", "quote")


def _passages(span: Mapping[str, Any]):
    text = span["text"]
    start = span["start"]
    if not isinstance(text, str) or type(start) is not int or type(span["end"]) is not int or start < 0 or span["end"] != start + len(text):
        raise KernelError("LONGFORM_PROSE_CITATION_SOURCE_DRIFT", "Indexed passages require exact Unicode span boundaries")
    for part in text.splitlines(keepends=True):
        yield {**{key: span[key] for key in BOUND_FIELDS[:3]}, "start": start, "end": start + len(part), "quote": part}
        start += len(part)


def citation_catalog(window: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for span in window["spans"]:
        for record in _passages(span):
            if record["quote"].strip():
                key = tuple(record[key] for key in BOUND_FIELDS)
                records[key] = record
    return {f"P{ordinal:04d}": record for ordinal, (_, record) in enumerate(sorted(records.items()), 1)}


def project_indexed_window(window: Mapping[str, Any]) -> dict[str, Any]:
    catalog = citation_catalog(window)
    ids = {tuple(record[key] for key in BOUND_FIELDS): identifier for identifier, record in catalog.items()}
    result = deepcopy(dict(window))
    for source, span in zip(window["spans"], result["spans"], strict=True):
        span["passages"] = []
        for record in _passages(source):
            identifier = ids.get(tuple(record[key] for key in BOUND_FIELDS))
            span["passages"].append({"text": record["quote"], **({"citation_id": identifier} if identifier else {})})
        for key in ("text", "asset_version_id", "asset_hash", "text_hash", "acceptance_id"):
            span.pop(key, None)
    return result


def resolve_indexed_citations(report: Mapping[str, Any], *, window: Mapping[str, Any]) -> dict[str, Any]:
    from .prose_review import normalize_prose_review_output

    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    located = any(any(key in citation for key in BOUND_FIELDS)
        for finding in findings if isinstance(finding, Mapping)
        for citation in (finding.get("evidence") if isinstance(finding.get("evidence"), list) else []) if isinstance(citation, Mapping))
    result = normalize_prose_review_output(report, located_citations=located)
    catalog = citation_catalog(window)
    ordinal = 0
    for finding in result["findings"]:
        for citation in finding["evidence"]:
            record = catalog.get(citation["citation_id"])
            if record is None:
                raise KernelError("LONGFORM_PROSE_CITATION_ID_UNKNOWN", "Citation must select a passage in the exact frozen window",
                    details={"citation_ordinal": ordinal, "reason": "PASSAGE_ID_NOT_SUPPLIED"})
            if located and any(citation[key] != record[key] for key in BOUND_FIELDS):
                raise KernelError("LONGFORM_PROSE_CITATION_INVALID", "Persisted indexed evidence must retain its exact original passage binding")
            citation.update(record)
            ordinal += 1
    return result
