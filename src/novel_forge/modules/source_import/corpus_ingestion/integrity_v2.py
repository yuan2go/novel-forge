from __future__ import annotations

from collections import defaultdict
from typing import Any

from novel_forge.modules.source_authority.corpus import corpus_hash
from .contracts import ParserProfile
from .integrity import issue


def enrich_integrity(rows: list[dict[str, Any]], parser: ParserProfile, result: dict[str, Any]) -> dict[str, Any]:
    profile = parser.normalization
    assert profile is not None
    chapters = [r for r in rows if r.get("unit_kind", "CHAPTER") in {"CHAPTER", "EXTRA"}]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id = {r["chapter_id"]: r for r in rows}
    for row in chapters:
        body = row["text"][row.get("confirmed_heading_chars", 0):]
        groups[corpus_hash(body)].append(row)
    for digest, members in groups.items():
        if len(members) < 2:
            continue
        count = len(members[0]["text"][members[0].get("confirmed_heading_chars", 0):].strip())
        finding = issue("DUPLICATE_BODY" if count >= profile.duplicate_body_min_chars else "REPEATED_SHORT_BODY", members, blocking=count >= profile.duplicate_body_min_chars)
        finding.update(body_hash=digest, body_characters=count, policy=profile.version, blocking_uses=["SOURCE_ANALYSIS"] if finding["blocking"] else [])
        for evidence, row in zip(finding["evidence"], members, strict=True):
            evidence.update(order=row["order"], volume=row["volume"], title=row["title"], body_hash=digest, heading_characters=row.get("confirmed_heading_chars", 0))
        result["issues"].append(finding)
    result["issues"] = [i for i in result["issues"] if i["code"] != "TOC_BODY_MISMATCH"]
    expected = profile.expected_toc
    if expected:
        for index in range(max(len(expected), len(chapters))):
            wanted = expected[index] if index < len(expected) else None
            row = chapters[index] if index < len(chapters) else None
            if row and wanted == row["title"]:
                continue
            finding = issue("TOC_ENTRY_MISMATCH", [row] if row else [])
            finding.update(toc_index=index, expected_title=wanted, observed_title=row["title"] if row else None, toc_evidence=profile.toc_evidence)
            finding["issue_id"] = corpus_hash(finding)
            result["issues"].append(finding)
    for unit in result["units"]:
        row = by_id[unit["unit_id"]]
        from .similarity import fingerprint
        unit["match_fingerprint"] = fingerprint([row["text"][row.get("confirmed_heading_chars", 0):]], size=16)["hashes"]
        unit.update(raw_file_hash=row["raw_file_hash"], decoded_unit_hash=row["original_content_hash"], body_hash=row["body_content_hash"], heading_characters=row.get("confirmed_heading_chars", 0), source_key=row.get("source_chapter_id"), source_file_key=corpus_hash({k:row["source_locator"].get(k) for k in ("path", "container_path", "record", "href")}))
    result["version"] = "corpus-integrity.v2"
    result["structure_usable"] = not any(i["blocking"] for i in result["issues"])
    result["coverage"] = "REVIEW_REQUIRED" if not result["structure_usable"] else "COMPLETE" if result["toc_matches"] else "EXCERPT" if parser.completeness == "EXCERPT" else "UNKNOWN"
    result["coverage_scope"] = {"claim": "SELECTED_CATALOGUE_AND_ACQUIRED_UNITS_ONLY", "catalogue_hash": corpus_hash(expected), "catalogue_evidence": profile.toc_evidence, "unit_manifest_hash": corpus_hash(result["units"]), "other_editions_verified": False, "text_completeness": "NOT_INFERRED_FROM_TITLES"}
    result["body_sequence_hash"] = corpus_hash([r["body_content_hash"] for r in chapters])
    return result
