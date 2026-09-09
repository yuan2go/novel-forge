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


def parse_records(
    file: dict[str, Any], profile: ParserProfile, budget: IngestionBudget
) -> Iterator[dict[str, Any]]:
    path = Path(file["cache_path"])
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
        with path.open("rb") as source:
            ordinal, offset = 0, 0
            while line := source.readline(budget.max_record_bytes + 1):
                ordinal += 1
                if len(line) > budget.max_record_bytes:
                    raise IngestionFailure("RECORD_BYTE_LIMIT")
                if line.strip():
                    parsed = json.loads(line.decode(profile.encoding, errors="strict"))
                    if not isinstance(parsed, dict):
                        raise IngestionFailure("RECORD_NOT_OBJECT")
                    row = _mapped(parsed, profile, ordinal, file)
                    if row is not None:
                        row["source_locator"].update(
                            offset_kind="JSONL_RECORD_BYTES",
                            original_byte_offset=offset,
                            original_byte_end=offset + len(line),
                        )
                        yield row
                offset += len(line)
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
            "CREATE TABLE units(work TEXT,edition TEXT,unit TEXT,ordinal INTEGER,body_bytes INTEGER,payload TEXT,PRIMARY KEY(work,edition,unit),UNIQUE(work,edition,ordinal))"
        )
        for file in sorted(
            files, key=lambda item: (item.get("container_path", ""), item["path"])
        ):
            selected = ParserProfile.model_validate(
                file.get("parser") or profile.model_dump()
            )
            file_count = 0
            for record in parse_records(file, selected, budget):
                count += 1
                file_count += 1
                if count > budget.max_records:
                    raise IngestionFailure("RECORD_COUNT_LIMIT")
                body = record["text"]
                if not body.strip():
                    raise IngestionFailure("EMPTY_TEXT_REVIEW_REQUIRED")
                normalized = unicodedata.normalize(
                    "NFC", body.replace("\r\n", "\n").replace("\r", "\n")
                )
                encoded = normalized.encode("utf-8")
                if len(encoded) > budget.max_record_bytes:
                    raise IngestionFailure("RECORD_BYTE_LIMIT")
                record.update(
                    text=normalized,
                    raw_file_hash=file["checksum"],
                    raw_blob_id=file.get("blob_id"),
                    original_content_hash="sha256:"
                    + hashlib.sha256(body.encode()).hexdigest(),
                    normalized_content_hash="sha256:"
                    + hashlib.sha256(encoded).hexdigest(),
                    parser=selected.model_dump(mode="json"),
                )
                identity = (
                    record["work_id"],
                    record["edition_id"],
                    record["chapter_id"],
                )
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
                        "INSERT INTO units VALUES (?,?,?,?,?,?)",
                        (*identity, record["order"], len(encoded), payload),
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
                    "SELECT payload FROM units WHERE work=? AND edition=? ORDER BY ordinal,unit",
                    (work_id, edition),
                )
            ]
            profiles = {corpus_hash(row["parser"]) for row in records}
            if len(profiles) != 1:
                raise IngestionFailure("CROSS_SHARD_PARSER_CONFLICT")
            parser = ParserProfile.model_validate(records[0]["parser"])
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
            if parser.layout == "CHAPTER_ROWS" and ordinals != list(
                range(min(ordinals), max(ordinals) + 1)
            ):
                status = "REVIEW_REQUIRED"
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
