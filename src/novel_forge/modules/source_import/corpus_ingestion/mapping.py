from __future__ import annotations

import hashlib
from typing import Any

from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_import.classical_corpus import (
    AcquiredWorkSpec,
    ParsedSourceUnit,
    ParsedSourceWork,
)
from novel_forge.modules.source_import.domain import (
    NormalizedSource,
    chunk_normalized_text,
)


def parsed_source_work(
    document: dict[str, Any], *, edition_id: str, snapshot_id: str, max_chunk_bytes: int
) -> ParsedSourceWork:
    units, parts = [], []
    byte_offset = character_offset = 0
    for ordinal, row in enumerate(document["units"], 1):
        text = str(row["text"])
        prefix = "\n\n" if parts else ""
        byte_offset += len(prefix.encode())
        character_offset += len(prefix)
        parts.append(prefix + text)
        encoded = text.encode()
        unit = ParsedSourceUnit(
            unit_id=str(row["chapter_id"]),
            unit_version_id=corpus_hash({"edition": edition_id, "unit": row}),
            ordinal=ordinal,
            kind="chapter",
            title=str(row["title"]),
            author=str(row["author"]),
            body=text,
            raw_file_path=str(row["source_locator"]["path"]),
            raw_file_hash=str(row["raw_file_hash"]),
            source_locator=dict(row["source_locator"]),
            original_content_hash=str(row["original_content_hash"]),
            normalized_content_hash=str(row["normalized_content_hash"]),
            character_count=len(text),
            line_count=len(text.splitlines()),
            metadata={
                "volume": row["volume"],
                "declared_order": row["order"],
                "raw_blob_id": row["raw_blob_id"],
                "normalized_unicode_start": character_offset,
                "normalized_unicode_end": character_offset + len(text),
                "original_offset_semantics": row["source_locator"]["offset_kind"],
            },
            status="AVAILABLE",
            normalized_byte_start=byte_offset,
            normalized_byte_end=byte_offset + len(encoded),
            normalized_character_start=character_offset,
            normalized_character_end=character_offset + len(text),
        )
        units.append(unit)
        byte_offset += len(encoded)
        character_offset += len(text)
    text = "".join(parts)
    normalized = NormalizedSource(
        text=text,
        encoding="utf-8",
        media_type="text/plain",
        source_format="corpus-work",
        normalization_version="corpus-normalization.v1",
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        byte_size=byte_offset,
        character_count=character_offset,
        structural_markers=(),
    )
    spec = AcquiredWorkSpec(
        work_key=edition_id,
        title=document["title"],
        collection_kind="NOVEL",
        parser_profile="universal-corpus.v1",
        registry_id="corpus-ingestion-manifest.v1",
        registry_hash=document["parser_hash"],
        acquisition={
            "corpus_edition_id": edition_id,
            "snapshot_id": snapshot_id,
            "external_work_id": document["work_id"],
            "external_edition_id": document["edition_id"],
            "completeness": document["completeness"],
        },
    )
    return ParsedSourceWork(
        spec=spec,
        units=tuple(units),
        normalized=normalized,
        chunks=chunk_normalized_text(normalized, max_chunk_bytes=max_chunk_bytes),
        diagnostics={
            "completeness": document["completeness"],
            "expected_units": document["expected_units"],
            "deduplication": "EXACT_RECORD_ONLY",
        },
        excluded_fields=(),
        parser_version="corpus-parser.v1",
    )
