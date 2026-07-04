from __future__ import annotations

from typing import Any


def build_import_quality_report(
    *,
    repository_id: str,
    manifest: dict[str, Any],
    imported_books: list[dict[str, Any]],
    imported_chapters: list[dict[str, Any]],
    parallel_pairs: list[dict[str, Any]],
    duplicate_count: int = 0,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    file_count = len(manifest.get("files", [])) if isinstance(manifest.get("files", []), list) else 0
    failure_count = len(failures or [])
    imported_count = len(imported_chapters) + len(parallel_pairs)
    extraction_coverage = round(imported_count / max(1, file_count), 4)
    duplicate_rate = round(duplicate_count / max(1, imported_count + duplicate_count), 4)
    return {
        "repository_id": repository_id,
        "source_count": file_count,
        "book_count": len(imported_books),
        "chapter_count": len(imported_chapters),
        "parallel_pair_count": len(parallel_pairs),
        "duplicate_count": duplicate_count,
        "failure_count": failure_count,
        "extraction_coverage": extraction_coverage,
        "duplicate_rate": duplicate_rate,
        "cleaning_warnings": [],
        "copyright_boundary": "evidence_only",
        "recommended_next_actions": ["run_source_type_extraction", "evaluate_extraction_quality"],
        "failures": failures or [],
    }
