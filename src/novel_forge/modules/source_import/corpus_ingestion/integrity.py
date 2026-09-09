from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any

from novel_forge.modules.source_authority.corpus import corpus_hash
from .contracts import ParserProfile


def issue(
    code: str, rows: list[dict[str, Any]], *, blocking: bool = True
) -> dict[str, Any]:
    evidence = [
        {
            "unit_id": r["chapter_id"],
            "locator": r["source_locator"],
            "content_hash": r["normalized_content_hash"],
        }
        for r in rows
    ]
    return {
        "issue_id": corpus_hash({"code": code, "evidence": evidence}),
        "code": code,
        "severity": "ERROR" if blocking else "NOTICE",
        "blocking": blocking,
        "evidence": evidence,
        "recommendation": "Inspect exact source units and submit a scoped decision; no rights waiver.",
    }


def assess_integrity(
    rows: list[dict[str, Any]], parser: ParserProfile
) -> dict[str, Any]:
    profile = parser.normalization
    assert profile is not None
    issues = []
    chapters = [
        r for r in rows if r.get("unit_kind", "CHAPTER") in {"CHAPTER", "EXTRA"}
    ]
    if not chapters:
        issues.append(issue("RELIABLE_BOUNDARIES_MISSING", rows[:1]))
    previous: dict[str, int] = {}
    seen: set[tuple[str, int]] = set()
    titles = Counter(r["title"] for r in chapters)
    metadata_rows = {(r["work_title"], r["author"]): r for r in rows}
    if len(metadata_rows) > 1:
        issues.append(issue("WORK_METADATA_CONFLICT", list(metadata_rows.values())[:2]))
    for row in rows:
        kind = row.get("unit_kind", "CHAPTER")
        if kind in {"AUTHOR_NOTE", "UNSTRUCTURED", "VOLUME"}:
            issues.append(
                issue(
                    "NON_BODY_UNIT",
                    [row],
                    blocking=kind in {"UNSTRUCTURED", "AUTHOR_NOTE"},
                )
            )
        if kind not in {"CHAPTER", "EXTRA"}:
            continue
        first_line, separator, remainder = row["text"].partition("\n")
        body = (
            remainder
            if separator and first_line.strip() == row["title"]
            else row["text"]
        )
        if len(body.strip()) < profile.min_body_chars:
            issues.append(issue("SHORT_OR_TOC_UNIT", [row]))
        n = row.get("declared_number", row["order"])
        volume = row["volume"]
        if n is not None:
            if (volume, n) in seen:
                issues.append(issue("NUMBER_CONFLICT", [row]))
            elif volume in previous and n != previous[volume] + 1:
                issues.append(issue("MISSING_OR_UNORDERED_CHAPTER", [row]))
            seen.add((volume, n))
            previous[volume] = n
        if titles[row["title"]] > 1:
            issues.append(issue("DUPLICATE_TITLE", [row]))
    expected = list(profile.expected_toc)
    actual = [r["title"] for r in chapters]
    toc_matches = bool(expected) and expected == actual
    if expected and not toc_matches:
        issues.append(issue("TOC_BODY_MISMATCH", chapters[:1]))
    coverage = (
        "COMPLETE"
        if toc_matches and not any(i["blocking"] for i in issues)
        else parser.completeness
    )
    if coverage == "COMPLETE" and not toc_matches:
        coverage = "UNKNOWN"
    if any(i["blocking"] for i in issues):
        coverage = "REVIEW_REQUIRED"
    return {
        "version": "corpus-integrity.v1",
        "metadata": {
            "title": rows[0]["work_title"],
            "author": rows[0]["author"],
            "external_work_ids": list(profile.external_work_ids),
        },
        "profile_hash": corpus_hash(profile.model_dump(mode="json")),
        "coverage": coverage,
        "work_completion": profile.work_completion,
        "acquisition_integrity": "VERIFIED_BYTES",
        "structure_usable": not any(i["blocking"] for i in issues),
        "toc_evidence": profile.toc_evidence,
        "toc_matches": toc_matches,
        "chapter_count": len(chapters),
        "unit_count": len(rows),
        "issues": issues,
        "units": [
            {
                "unit_id": r["chapter_id"],
                "title": r["title"],
                "volume": r["volume"],
                "kind": r.get("unit_kind", "CHAPTER"),
                "original_order": r.get("physical_order", r["order"]),
                "normalized_order": r["order"],
                "number": r.get("declared_number"),
                "hash": r["normalized_content_hash"],
                "characters": len(r["text"]),
                "locator": r["source_locator"],
            }
            for r in rows
        ],
        "text_hash": "sha256:"
        + hashlib.sha256("\n\n".join(r["text"] for r in rows).encode()).hexdigest(),
    }
