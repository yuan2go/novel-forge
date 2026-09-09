from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import unicodedata
import zipfile

from novel_forge.modules.source_authority.corpus import corpus_hash

from .contracts import (
    IngestionBudget,
    IngestionFailure,
    ParserProfile,
    safe_relative_path,
)
from .safety import require_space, spool_json
from .text_records import decoded_lines


def _field(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise IngestionFailure("MAPPED_FIELD_MISSING", path)
        value = value[part]
    return value


def _mapped(
    row: dict[str, Any], profile: ParserProfile, ordinal: int, file: dict[str, Any]
) -> dict[str, Any] | None:
    if any(_field(row, key) != value for key, value in profile.filters.items()):
        return None
    values = {key: _field(row, path) for key, path in profile.fields.items()}
    values.update(profile.constants)
    if "text" not in values or not isinstance(values["text"], str):
        raise IngestionFailure("TEXT_FIELD_NOT_STRING")
    if profile.layout != "SINGLE_WORK" and "work_id" not in values:
        raise IngestionFailure(
            "WORK_ID_REQUIRED", "dataset row numbers are not work identities"
        )
    values.setdefault("work_id", file["path"])
    if profile.work_key_encoding == "SHA256":
        values["work_id"] = (
            "mapped:"
            + hashlib.sha256(str(values["work_id"]).encode("utf-8")).hexdigest()
        )
    values.setdefault("edition_id", "source-edition")
    values.setdefault("chapter_id", "body" if profile.layout != "CHAPTER_ROWS" else "")
    values.setdefault("order", 1)
    values.setdefault("title", str(values["chapter_id"]))
    values.setdefault("work_title", str(values["work_id"]))
    values.setdefault("volume", "")
    values.setdefault("author", "")
    for name in (
        "work_id",
        "edition_id",
        "chapter_id",
        "title",
        "work_title",
        "volume",
        "author",
    ):
        if not isinstance(values[name], (str, int)) or len(str(values[name])) > (
            512 if name in {"work_id", "edition_id", "chapter_id"} else 2048
        ):
            raise IngestionFailure("IDENTITY_FIELD_INVALID", name)
        values[name] = str(values[name])
    if not all(values[name] for name in ("work_id", "edition_id", "chapter_id")):
        raise IngestionFailure("EMPTY_RECORD_IDENTITY")
    if (
        isinstance(values["order"], bool)
        or not isinstance(values["order"], int)
        or values["order"] < 1
    ):
        raise IngestionFailure("CHAPTER_ORDER_INVALID")
    values["source_locator"] = {
        "path": file["path"],
        "container_path": file.get("container_path"),
        "record": ordinal,
        "field": profile.fields.get("text", "text"),
        "offset_kind": "STRUCTURED_RECORD",
        "original_byte_offset": None,
    }
    return values


def _html_text(content: str, profile: ParserProfile) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(content, "html.parser")
    for selector in profile.html_remove_selectors:
        for node in soup.select(selector):
            node.decompose()
    selected = soup.select(profile.html_body_selector)
    if not selected:
        raise IngestionFailure("HTML_BODY_NOT_FOUND", profile.html_body_selector)
    return "\n".join(node.get_text("\n", strip=True) for node in selected)


def _epub_records(
    path: Path, file: dict[str, Any], profile: ParserProfile, budget: IngestionBudget
) -> Iterator[dict[str, Any]]:
    from defusedxml.ElementTree import fromstring
    from ebooklib import epub

    if path.stat().st_size > budget.memory_bytes // 16:
        raise IngestionFailure("EPUB_CONTAINER_MEMORY_LIMIT")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > budget.max_files or sum(
            item.file_size for item in entries
        ) > min(budget.max_expanded_bytes, budget.memory_bytes // 4):
            raise IngestionFailure("EPUB_EXPANSION_LIMIT")
        seen = set()
        for item in entries:
            name = safe_relative_path(item.filename.rstrip("/"))
            if (
                name in seen
                or item.flag_bits & 1
                or (item.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise IngestionFailure("EPUB_MEMBER_INVALID")
            seen.add(name)
            if item.file_size > max(1, item.compress_size) * budget.max_archive_ratio:
                raise IngestionFailure("EPUB_EXPANSION_RATIO")
            if not item.is_dir() and name.lower().endswith(
                (".xml", ".opf", ".ncx", ".xhtml", ".html")
            ):
                fromstring(
                    archive.read(item),
                    forbid_dtd=False,
                    forbid_entities=True,
                    forbid_external=True,
                )
    book = epub.read_epub(str(path), options={"ignore_ncx": False})
    ordinal = 0
    for identifier, linear in book.spine:
        if linear == "no":
            continue
        item = book.get_item_with_id(identifier)
        if item is None:
            raise IngestionFailure("EPUB_SPINE_ITEM_MISSING", identifier)
        ordinal += 1
        text = _html_text(item.get_content().decode("utf-8", errors="strict"), profile)
        row = _mapped(
            {"text": text},
            profile.model_copy(update={"fields": {"text": "text"}}),
            ordinal,
            file,
        )
        assert row is not None
        row.update(chapter_id=identifier, order=ordinal, title=item.get_name())
        row["source_locator"].update(
            offset_kind="EPUB_SPINE",
            spine_ordinal=ordinal,
            href=item.get_name(),
            field=None,
        )
        yield row


def _format_records(
    file: dict[str, Any], profile: ParserProfile, budget: IngestionBudget
) -> Iterator[dict[str, Any]]:
    path = Path(file["cache_path"])
    if profile.format == "txt" and profile.normalization is not None:
        from .segmentation import txt_segments, explicit_segments

        for segment in (
            explicit_segments(file, profile.encoding, profile.normalization)
            if profile.normalization.boundaries
            else txt_segments(path, profile.encoding, profile.normalization)
        ):
            row = _mapped(
                {"text": segment["text"]},
                profile.model_copy(update={"fields": {"text": "text"}}),
                segment["order"],
                file,
            )
            assert row is not None
            row.update(
                {
                    key: value
                    for key, value in segment.items()
                    if key not in {"raw_start", "raw_end"}
                }
            )
            row["chapter_id"] = (
                "unit:"
                + hashlib.sha256(
                    f"{file['path']}:{segment['raw_start']}".encode()
                ).hexdigest()
            )
            row["source_locator"].update(
                offset_kind="RAW_DECODED_UNIT",
                original_byte_offset=segment["raw_start"],
                original_byte_end=segment["raw_end"],
                precision="UNIT_BYTES",
                encoding=profile.encoding,
            )
            yield row
        return
    if profile.format == "epub":
        yield from _epub_records(path, file, profile, budget)
        return
    if profile.format in {"txt", "html"}:
        if path.stat().st_size > budget.max_work_bytes:
            raise IngestionFailure(
                "DOCUMENT_REQUIRES_BOUNDED_STRUCTURE",
                "use explicit chapter records for larger books",
            )
        with path.open(
            "r", encoding=profile.encoding, errors="strict", newline=""
        ) as source:
            text = source.read(budget.max_work_bytes + 1)
        if profile.format == "html":
            text = _html_text(text, profile)
        row = _mapped(
            {"text": text},
            profile.model_copy(update={"fields": {"text": "text"}}),
            1,
            file,
        )
        assert row is not None
        row["source_locator"].update(
            offset_kind="RAW_FILE" if profile.format == "txt" else "HTML_SELECTOR",
            original_byte_offset=0 if profile.format == "txt" else None,
            selector=profile.html_body_selector if profile.format == "html" else None,
        )
        yield row
        return
    if profile.format == "jsonl":
        for ordinal, (line, offset, end) in enumerate(
            decoded_lines(path, profile.encoding, budget.max_record_bytes), 1
        ):
            if line.strip():
                parsed = json.loads(line)
                if not isinstance(parsed, dict):
                    raise IngestionFailure("RECORD_NOT_OBJECT")
                row = _mapped(parsed, profile, ordinal, file)
                if row is not None:
                    row["source_locator"].update(
                        offset_kind="JSONL_RECORD_BYTES",
                        original_byte_offset=offset,
                        original_byte_end=end,
                    )
                    yield row
        return
    if profile.format == "json":
        import ijson

        if path.stat().st_size > budget.memory_bytes // 8:
            raise IngestionFailure(
                "JSON_DOCUMENT_MEMORY_LIMIT", "use JSONL or bounded shards"
            )
        with path.open("rb") as source:
            decoded = (
                source
                if profile.encoding == "utf-8"
                else io.BytesIO(
                    source.read()
                    .decode(profile.encoding, errors="strict")
                    .encode("utf-8")
                )
            )
            with decoded:
                for ordinal, parsed in enumerate(
                    ijson.items(decoded, profile.records_path, use_float=True), 1
                ):
                    if not isinstance(parsed, dict):
                        raise IngestionFailure("RECORD_NOT_OBJECT")
                    row = _mapped(parsed, profile, ordinal, file)
                    if row is not None:
                        yield row
        return
    if profile.format == "parquet":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
        if any(
            metadata.row_group(i).total_byte_size > budget.memory_bytes // 4
            for i in range(metadata.num_row_groups)
        ):
            raise IngestionFailure("PARQUET_ROW_GROUP_MEMORY_LIMIT")
        columns = sorted(
            {
                value.split(".")[0]
                for value in (*profile.fields.values(), *profile.filters)
            }
        )
        ordinal = 0
        for batch in parquet.iter_batches(
            batch_size=1, columns=columns, use_threads=False
        ):
            for parsed in batch.to_pylist():
                ordinal += 1
                row = _mapped(parsed, profile, ordinal, file)
                if row is not None:
                    row["source_locator"].update(
                        offset_kind="PARQUET_ROW", original_byte_offset=None
                    )
                    yield row


def parse_records(
    file: dict[str, Any], profile: ParserProfile, budget: IngestionBudget
) -> Iterator[dict[str, Any]]:
    for record in _format_records(file, profile, budget):
        if (
            profile.normalization
            and profile.normalization.segmentation == "CHINESE_HEADINGS"
            and profile.format != "txt"
            and profile.layout != "CHAPTER_ROWS"
        ):
            from .segmentation import segment_lines

            def lines() -> Iterator[tuple[str, int, int]]:
                offset = 0
                for line in record["text"].splitlines(keepends=True):
                    yield line, offset, offset + len(line)
                    offset += len(line)

            for part in segment_lines(lines(), profile.normalization):
                locator = {
                    **record["source_locator"],
                    "precision": "EXTRACTED_TEXT_UNIT",
                    "extracted_unicode_start": part["raw_start"],
                    "extracted_unicode_end": part["raw_end"],
                    "original_byte_offset": None,
                }
                yield {
                    **record,
                    **{
                        k: v
                        for k, v in part.items()
                        if k not in {"raw_start", "raw_end"}
                    },
                    "chapter_id": record["chapter_id"] + ":" + str(part["raw_start"]),
                    "order": part["order"],
                    "source_locator": locator,
                }
        else:
            yield record


def compile_work_index(
    files: list[dict[str, Any]],
    profile: ParserProfile,
    budget: IngestionBudget,
    root: Path,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "parse-index.sqlite"
    database.unlink(missing_ok=True)
    count, filtered_files = 0, 0
    with sqlite3.connect(database) as index:
        index.execute("PRAGMA cache_size=-4096")
        index.execute(
            "CREATE TABLE units(work TEXT,edition TEXT,unit TEXT,ordinal INTEGER,body_bytes INTEGER,payload TEXT,volume_rank INTEGER,PRIMARY KEY(work,edition,unit),UNIQUE(work,edition,volume_rank,ordinal))"
        )
        volumes: dict[tuple[str, str, str], int] = {}
        sequences: dict[tuple[str, str], int] = {}
        profile_catalog: dict[str, ParserProfile] = {}
        for file in sorted(
            files, key=lambda item: (item.get("container_path", ""), item["path"])
        ):
            selected = ParserProfile.model_validate(
                file.get("parser") or profile.model_dump()
            )
            selected_hash = corpus_hash(selected.model_dump(mode="json"))
            profile_catalog[selected_hash] = selected
            file_count = 0
            for record in parse_records(file, selected, budget):
                count += 1
                file_count += 1
                if count > budget.max_records:
                    raise IngestionFailure("RECORD_COUNT_LIMIT")
                body = record["text"]
                if not body.strip():
                    raise IngestionFailure("EMPTY_TEXT_REVIEW_REQUIRED")
                normalized = body.replace("\r\n", "\n").replace("\r", "\n")
                if (
                    selected.normalization is None
                    or selected.normalization.unicode_form == "NFC"
                ):
                    normalized = unicodedata.normalize("NFC", normalized)
                encoded = normalized.encode("utf-8")
                if len(encoded) > (
                    selected.normalization.max_unit_bytes
                    if selected.normalization
                    else budget.max_record_bytes
                ):
                    raise IngestionFailure("RECORD_BYTE_LIMIT")
                record.update(
                    text=normalized,
                    raw_file_hash=file["checksum"],
                    raw_blob_id=file.get("blob_id"),
                    original_content_hash="sha256:"
                    + hashlib.sha256(body.encode()).hexdigest(),
                    normalized_content_hash="sha256:"
                    + hashlib.sha256(encoded).hexdigest(),
                    parser=selected.model_dump(mode="json")
                    if selected.normalization is None
                    else {"profile_hash": selected_hash},
                )
                volume_key = (
                    record["work_id"],
                    record["edition_id"],
                    record["volume"] if selected.normalization else "",
                )
                volume_rank = volumes.setdefault(volume_key, len(volumes))
                if selected.normalization and selected.layout != "CHAPTER_ROWS":
                    sequence_key = (record["work_id"], record["edition_id"])
                    record["physical_order"] = record["order"]
                    record["order"] = sequences.get(sequence_key, 0) + 1
                    sequences[sequence_key] = record["order"]
                if selected.normalization and record["volume"]:
                    record["source_chapter_id"] = record["chapter_id"]
                    record["chapter_id"] = record["volume"] + ":" + record["chapter_id"]
                record["normalization_evidence"] = {
                    "steps": ["STRICT_DECODE", "NEWLINE_LF"]
                    + (
                        ["NFC"]
                        if selected.normalization is None
                        or selected.normalization.unicode_form == "NFC"
                        else []
                    ),
                    "precision": "UNIT_BYTES"
                    if record["source_locator"].get("original_byte_offset") is not None
                    else "STRUCTURED_LOCATOR",
                    "raw_text_changed": body != normalized,
                    "normalized_unicode_length": len(normalized),
                    "normalized_utf8_bytes": len(encoded),
                }
                identity = (
                    record["work_id"],
                    record["edition_id"],
                    record["chapter_id"],
                )
                if selected.normalization is None:
                    record.pop("normalization_evidence", None)
                payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
                existing = index.execute(
                    "SELECT payload FROM units WHERE work=? AND edition=? AND unit=?",
                    identity,
                ).fetchone()
                if existing is not None:
                    if existing[0] != payload:
                        raise IngestionFailure("DUPLICATE_UNIT_CONFLICT")
                    continue
                try:
                    index.execute(
                        "INSERT INTO units VALUES (?,?,?,?,?,?,?)",
                        (
                            *identity,
                            record["order"],
                            len(encoded),
                            payload,
                            volume_rank,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise IngestionFailure("CHAPTER_ORDER_CONFLICT") from exc
                total, units = index.execute(
                    "SELECT SUM(body_bytes),COUNT(*) FROM units WHERE work=? AND edition=?",
                    identity[:2],
                ).fetchone()
                if total > budget.max_work_bytes or units > budget.max_units_per_work:
                    raise IngestionFailure("WORK_BUDGET_EXCEEDED")
                if count % 100 == 0:
                    require_space(root, budget)
                    index.commit()
            filtered_files += file_count == 0
        works = index.execute(
            "SELECT work,edition,COUNT(*),SUM(body_bytes) FROM units GROUP BY work,edition ORDER BY work,edition"
        )
        outputs = []
        for work_id, edition, units, body_bytes in works:
            if len(outputs) >= budget.max_works:
                raise IngestionFailure("WORK_COUNT_LIMIT")
            records = [
                json.loads(row[0])
                for row in index.execute(
                    "SELECT payload FROM units WHERE work=? AND edition=? ORDER BY volume_rank,ordinal,unit",
                    (work_id, edition),
                )
            ]
            profiles = {
                row["parser"].get("profile_hash") or corpus_hash(row["parser"])
                for row in records
            }
            if len(profiles) != 1:
                raise IngestionFailure("CROSS_SHARD_PARSER_CONFLICT")
            parser = profile_catalog[next(iter(profiles))]
            ordinals = [row["order"] for row in records]
            complete = parser.expected_units == units and ordinals == list(
                range(1, units + 1)
            )
            status = (
                "COMPLETE"
                if parser.completeness == "COMPLETE" and complete
                else parser.completeness
            )
            if parser.completeness == "COMPLETE" and not complete:
                status = "REVIEW_REQUIRED"
            if parser.layout == "CHAPTER_ROWS" and any(
                b != a + 1 for a, b in zip(ordinals, ordinals[1:])
            ):
                status = "REVIEW_REQUIRED"
            integrity = None
            if parser.normalization:
                from .integrity import assess_integrity

                integrity = assess_integrity(records, parser)
                status = integrity["coverage"]
            content = {
                "schema_version": "corpus-parsed-work.v1",
                "work_id": work_id,
                "edition_id": edition,
                "title": records[0]["work_title"],
                "units": records,
                "completeness": status,
                "declared_completeness": parser.completeness,
                "expected_units": parser.expected_units,
                "body_bytes": body_bytes,
                "parser_hash": corpus_hash(parser.model_dump(mode="json")),
            }
            if integrity is not None:
                content["parser_profile"] = parser.model_dump(mode="json")
                content["integrity"] = integrity
            pointer = spool_json(content, root / "works", budget)
            outputs.append(
                {
                    **pointer,
                    "work_id": work_id,
                    "edition_id": edition,
                    "title": content["title"],
                    "unit_count": units,
                    "completeness": status,
                }
            )
    database.unlink(missing_ok=True)
    if not outputs:
        raise IngestionFailure(
            "NO_PARSED_WORKS", "empty/filtered input is not an imported corpus"
        )
    return {
        "works": outputs,
        "records": count,
        "work_count": len(outputs),
        "filtered_files": filtered_files,
        "parser_version": profile.version,
    }
