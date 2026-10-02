#!/usr/bin/env python3
"""Offline import for one frozen reference source; no network, model, DB or Git writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_index(lines: list[str]) -> bytes:
    pattern = re.compile(r"^\s*第(\d+)章\s*(.*)$")
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            headings.append((index, int(match.group(1)), match.group(2).strip()))
    records: list[str] = []
    for index, (start, number, title) in enumerate(headings):
        stop = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        text = "\n".join(lines[start:stop])
        record = {
            "chapter_number": number,
            "title": title,
            "start_line": start + 1,
            "end_line": stop,
            "nonwhitespace_characters": sum(not char.isspace() for char in text),
            "normalized_chapter_sha256": sha256(text.encode("utf-8")),
        }
        records.append(json.dumps(record, ensure_ascii=False))
    return ("\n".join(records) + "\n").encode("utf-8")


def verify_cases(lines: list[str], cases: dict[str, Any], digest: str) -> int:
    if cases.get("source_sha256") != digest:
        raise ValueError("Test cases refer to another source version")
    count = 0
    for case in cases["source_cases"]:
        for span in case["evidence"]:
            start, stop = int(span["source_start_line"]), int(span["source_end_line"])
            if not 1 <= start <= stop <= len(lines):
                raise ValueError(f"Invalid line range: {case['id']}")
            data = "\n".join(lines[start - 1:stop]).encode("utf-8")
            if sha256(data) != span["normalized_span_sha256"]:
                raise ValueError(f"Source evidence hash mismatch: {case['id']}:{start}-{stop}")
            count += 1
    return count


def save_without_overwrite(path: Path, data: bytes) -> str:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"Refusing to replace different content: {path}")
        return "ALREADY_IDENTICAL"
    # Exclusive creation prevents silently overwriting concurrent user changes.
    with path.open("xb") as stream:
        stream.write(data)
    return "CREATED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Original TXT or source.txt from the full handoff package")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent, help="Reference directory to populate")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "source-manifest.json").read_text(encoding="utf-8"))
    case_bytes = (here / "test-cases.json").read_bytes()
    if sha256(case_bytes) != manifest["repository_delivery"]["test_cases_sha256"]:
        raise ValueError("Test case manifest changed; review and rebind before importing")
    data = args.source.resolve(strict=True).read_bytes()
    source = manifest["source"]
    digest = sha256(data)
    if len(data) != source["bytes"] or digest != source["raw_file_sha256"]:
        raise ValueError("Original source size/hash differs; no output was written")
    lines = data.decode(source["encoding"]).splitlines()
    if len(lines) != manifest["scan"]["line_count"]:
        raise ValueError("Line count differs from the frozen source")
    index_bytes = build_index(lines)
    expected = manifest["repository_delivery"]["chapter_index_sha256"]
    if sha256(index_bytes) != expected:
        raise ValueError("Rebuilt chapter index differs; do not silently replace the supplied index")
    span_count = verify_cases(lines, json.loads(case_bytes), digest)
    output = args.output.resolve()
    planned = {output / "source.txt": data, output / "chapter-index.jsonl": index_bytes}
    # Check every existing destination before writing either output.
    for path, value in planned.items():
        if path.is_symlink() or path.exists() and (not path.is_file() or path.read_bytes() != value):
            raise ValueError(f"Destination differs: {path}; no output was written")
    output.mkdir(parents=True, exist_ok=True)
    results = {str(path): save_without_overwrite(path, value) for path, value in planned.items()}
    print(json.dumps({
        "status": "LOCAL_SOURCE_AND_INDEX_VERIFIED",
        "source_sha256": digest,
        "source_git_blob_sha1": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
        "index_sha256": expected,
        "evidence_spans_verified": span_count,
        "files": results,
        "github_upload": "NOT_PERFORMED_BY_THIS_SCRIPT",
        "model_evaluation": "NOT_RUN",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        print(f"IMPORT_FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
