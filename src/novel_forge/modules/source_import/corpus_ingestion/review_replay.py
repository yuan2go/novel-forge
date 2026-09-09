from __future__ import annotations

from copy import deepcopy
from typing import Any
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import corpus_hash


def source_evidence_key(evidence: dict[str, Any]) -> str:
    locator = evidence["locator"]
    return corpus_hash(
        {
            "content_hash": evidence["content_hash"],
            "locator": {
                k: locator.get(k)
                for k in (
                    "path",
                    "container_path",
                    "record",
                    "href",
                    "original_byte_offset",
                    "original_byte_end",
                    "extracted_unicode_start",
                    "extracted_unicode_end",
                )
            },
        }
    )


def carry_review(
    document: dict[str, Any],
    review: dict[str, Any],
    *,
    boundary_repair: Any,
    parser: Any,
) -> None:
    assessment = document["integrity"]
    units = {
        source_evidence_key(
            {
                "content_hash": u["normalized_content_hash"],
                "locator": u["source_locator"],
            }
        ): u
        for u in document["units"]
    }
    findings = assessment["issues"]
    resolutions = deepcopy(review.get("resolutions", []))
    assessment["resolutions"] = resolutions
    mapped = {}
    for resolution in resolutions:
        if resolution["resolution"] == "MARK_NON_BODY":
            for evidence in resolution["evidence"]:
                unit = units.get(source_evidence_key(evidence))
                if unit is None:
                    raise KernelError(
                        "CORPUS_REVIEW_EVIDENCE_CHANGED",
                        "excluded occurrence no longer has the exact reviewed source span",
                    )
                unit["excluded_from_analysis"] = True
        mapped[resolution["issue_id"]] = resolution
    excluded = [u for u in document["units"] if u.get("excluded_from_analysis")]
    if excluded:
        from .integrity import assess_integrity
        from .integrity_v2 import enrich_integrity

        active = [u for u in document["units"] if not u.get("excluded_from_analysis")]
        if not active:
            raise KernelError(
                "CORPUS_NO_ANALYSABLE_BODY",
                "scoped exclusions cannot fabricate empty success",
            )
        fresh = enrich_integrity(active, parser, assess_integrity(active, parser))
        active_by_id = {u["unit_id"]: u for u in fresh["units"]}
        fresh["units"] = [
            {
                **active_by_id.get(u["unit_id"], u),
                "excluded_from_analysis": u["unit_id"] not in active_by_id,
            }
            for u in assessment["units"]
        ]
        fresh["unit_count"] = len(document["units"])
        fresh["coverage_scope"]["unit_manifest_hash"] = corpus_hash(fresh["units"])
        fresh["resolutions"] = resolutions
        document["integrity"] = assessment = fresh
        findings = assessment["issues"]
    for old in review["issues"]:
        keys = sorted(source_evidence_key(e) for e in old["evidence"])
        equivalent = [
            f
            for f in findings
            if f["code"] == old["code"]
            and sorted(source_evidence_key(e) for e in f["evidence"]) == keys
        ]
        if old["code"] == "TOC_ENTRY_MISMATCH":
            equivalent = [
                f
                for f in equivalent
                if all(
                    f.get(k) == old.get(k)
                    for k in (
                        "toc_evidence",
                        "toc_index",
                        "expected_title",
                        "observed_title",
                    )
                )
            ]
        if old["code"] == "TOC_BODY_MISMATCH" and assessment[
            "toc_evidence"
        ] == review.get("toc_evidence"):
            entries = [f for f in findings if f["code"] == "TOC_ENTRY_MISMATCH"]
            if entries:
                resolutions.append(
                    {
                        "issue_id": old["issue_id"],
                        "resolution": "REPLACED_BY_ENTRY_ASSESSMENT",
                        "replacement_issue_ids": [f["issue_id"] for f in entries],
                        "evidence": old["evidence"],
                    }
                )
                continue
        if equivalent:
            for finding in equivalent:
                resolved = old.get("resolution") or mapped.get(old["issue_id"])
                if resolved:
                    finding["resolution"] = {
                        **resolved,
                        "origin_issue_id": old["issue_id"],
                    }
                    finding["blocking"] = resolved["resolution"] == "REJECT_CORRUPT"
                if old.get("annotations"):
                    finding["annotations"] = deepcopy(old["annotations"])
                if finding["issue_id"] != old["issue_id"]:
                    finding["predecessor_issue_id"] = old["issue_id"]
            continue
        if old["blocking"] and not old.get("resolution"):
            excluded_numbers = {
                (u["volume"], u.get("declared_number")) for u in excluded
            }
            excluded_titles = {(u["volume"], u["title"]) for u in excluded}
            old_units = [units[k] for k in keys if k in units]
            repaired_by_exclusion = bool(old_units) and (
                old["code"] == "NUMBER_CONFLICT"
                and all(
                    (u["volume"], u.get("declared_number")) in excluded_numbers
                    for u in old_units
                )
                or old["code"] == "DUPLICATE_TITLE"
                and all((u["volume"], u["title"]) in excluded_titles for u in old_units)
                or all(u.get("excluded_from_analysis") for u in old_units)
            )
            if repaired_by_exclusion:
                resolutions.append(
                    {
                        "issue_id": old["issue_id"],
                        "resolution": "REASSESSED_AFTER_SCOPED_EXCLUSION",
                        "evidence": old["evidence"],
                        "excluded_unit_ids": [u["chapter_id"] for u in excluded],
                    }
                )
            elif boundary_repair(old):
                resolutions.append(
                    {
                        "issue_id": old["issue_id"],
                        "resolution": "RESEGMENTED_EXACT_SOURCE",
                        "evidence": old["evidence"],
                        "profile_hash": document["parser_hash"],
                    }
                )
            else:
                carried = deepcopy(old)
                carried["carry_reason"] = (
                    "UNRESOLVED_PRIOR_FINDING_REQUIRES_EXPLICIT_EVIDENCE"
                )
                findings.append(carried)
    assessment["structure_usable"] = not any(f["blocking"] for f in findings)
    if any(r["resolution"] == "CONFIRM_EXCERPT" for r in resolutions):
        assessment["coverage"] = "EXCERPT"
    elif any(r["resolution"] == "REJECT_CORRUPT" for r in resolutions):
        assessment["coverage"] = "CORRUPT"
    elif not assessment["structure_usable"]:
        assessment["coverage"] = "REVIEW_REQUIRED"
    elif assessment["coverage"] == "REVIEW_REQUIRED":
        assessment["coverage"] = "COMPLETE" if assessment["toc_matches"] else "UNKNOWN"
