from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Iterator

from .contracts import IngestionFailure, NormalizationProfile
from .text_records import decoded_lines

_DIGITS = dict(
    zip("零〇○一二三四五六七八九两", (0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2))
)
_HEADING = re.compile(
    r"^(?:正文\s*)?第\s*([0-9０-９零〇○一二三四五六七八九十百千万两]+)\s*([章回节卷部篇])(?:\s+|[：:、.．]|$)(.*)$"
)
_SPECIAL = re.compile(
    r"^(番外(?:\s*\S+)?|序章|楔子|序言|前言|后记|後記|尾声|终章|作者(?:感言|附言|的话)|完本感言)(?:\s+|[：:]|$)(.*)$"
)


def chinese_number(text: str) -> int:
    if text.isdecimal():
        return int(text)
    if all(c in _DIGITS for c in text):
        return int("".join(str(_DIGITS[c]) for c in text))
    total = section = digit = 0
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char == "万":
            total += (section + digit) * 10000
            section = digit = 0
        else:
            section += (digit or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            digit = 0
    return total + section + digit


def heading(line: str, limit: int) -> tuple[str, int | None, str] | None:
    title = line.strip().lstrip("\ufeff")
    if len(title) > limit:
        return None
    if title.startswith("*** END OF THE PROJECT GUTENBERG"):
        return ("AUTHOR_NOTE", None, title)
    match = _HEADING.fullmatch(title)
    if match:
        return (
            "VOLUME" if match[2] in "卷部篇" else "CHAPTER",
            chinese_number(match[1]),
            title,
        )
    match = _SPECIAL.fullmatch(title)
    if match:
        return (
            "AUTHOR_NOTE" if match[1].startswith(("作者", "完本")) else "EXTRA",
            None,
            title,
        )
    return None


def segment_lines(
    lines: Iterator[tuple[str, int, int]], profile: NormalizationProfile
) -> Iterator[dict[str, Any]]:
    parts: list[str] = []
    start = end = 0
    current: tuple[str, int | None, str] = ("UNSTRUCTURED", None, "")
    volume = ""
    ordinal = size = 0

    def record() -> dict[str, Any]:
        return {
            "text": "".join(parts),
            "title": current[2],
            "unit_kind": current[0],
            "declared_number": current[1],
            "volume": volume,
            "order": ordinal,
            "raw_start": start,
            "raw_end": end,
        }

    for line, left, right in lines:
        found = heading(line, profile.heading_max_chars)
        if found and parts:
            ordinal += 1
            yield record()
            parts, size = [], 0
        if not parts:
            start = left
            if found:
                current = found
                if found[0] == "VOLUME":
                    volume = found[2]
        end = right
        parts.append(line)
        size += len(line.encode("utf-8"))
        if size > profile.max_unit_bytes:
            raise IngestionFailure(
                "BODY_UNIT_REVIEW_REQUIRED",
                "no reliable boundary within frozen maximum body unit",
            )
    if parts:
        ordinal += 1
        yield record()


def txt_segments(
    path: Path, encoding: str, profile: NormalizationProfile
) -> Iterator[dict[str, Any]]:
    for row in segment_lines(
        decoded_lines(path, encoding, profile.max_unit_bytes), profile
    ):
        row["chapter_id"] = (
            "unit:"
            + hashlib.sha256(f"{path.name}:{row['raw_start']}".encode()).hexdigest()
        )
        yield row


def explicit_segments(
    file: dict[str, Any], encoding: str, profile: NormalizationProfile
) -> Iterator[dict[str, Any]]:
    selected = [b for b in profile.boundaries if b.path == file["path"]]
    if not selected:
        raise IngestionFailure(
            "BOUNDARY_FILE_MISSING",
            "explicit boundary profile must cover each selected file",
        )
    if (
        selected[0].start != 0
        or selected[-1].end != file["size_bytes"]
        or any(a.end != b.start for a, b in zip(selected, selected[1:]))
    ):
        raise IngestionFailure(
            "BOUNDARY_COVERAGE_INVALID", "no gaps, overlap or implicit deletion"
        )
    with Path(file["cache_path"]).open("rb") as source:
        prefix = source.read(4)
        codec = encoding
        if encoding == "utf-16":
            if prefix.startswith(b"\xff\xfe"):
                codec = "utf-16-le"
            elif prefix.startswith(b"\xfe\xff"):
                codec = "utf-16-be"
            else:
                raise IngestionFailure("ENCODING_BOM_REQUIRED")
        for ordinal, boundary in enumerate(selected, 1):
            if boundary.checksum != file["checksum"]:
                raise IngestionFailure("BOUNDARY_SOURCE_DRIFT")
            if boundary.end - boundary.start > profile.max_unit_bytes:
                raise IngestionFailure("BODY_UNIT_REVIEW_REQUIRED")
            source.seek(boundary.start)
            raw = source.read(boundary.end - boundary.start)
            text = raw.decode(codec, errors="strict")
            if boundary.start == 0:
                text = text.removeprefix("\ufeff")
            yield {
                "chapter_id": "boundary:" + str(boundary.start),
                "text": text,
                "title": boundary.title,
                "unit_kind": boundary.kind,
                "declared_number": boundary.number,
                "volume": boundary.volume,
                "order": ordinal,
                "raw_start": boundary.start,
                "raw_end": boundary.end,
                "boundary_evidence": boundary.evidence,
            }
