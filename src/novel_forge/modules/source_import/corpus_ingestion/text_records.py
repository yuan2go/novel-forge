from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator

from .contracts import IngestionFailure


def decoded_lines(
    path: Path, encoding: str, max_line_bytes: int
) -> Iterator[tuple[str, int, int]]:
    with path.open("rb") as raw:
        prefix = raw.read(4)
        bom = 0
        codec = encoding
        if encoding == "utf-16":
            if prefix.startswith(b"\xff\xfe"):
                codec, bom = "utf-16-le", 2
            elif prefix.startswith(b"\xfe\xff"):
                codec, bom = "utf-16-be", 2
            else:
                raise IngestionFailure(
                    "ENCODING_BOM_REQUIRED", "UTF-16 requires an explicit endian BOM"
                )
        elif encoding == "utf-8-sig":
            codec, bom = "utf-8", 3 if prefix.startswith(b"\xef\xbb\xbf") else 0
        raw.seek(bom)
        offset = 0
        with io.TextIOWrapper(raw, encoding=codec, errors="strict", newline="") as text:
            while line := text.readline(max_line_bytes + 1):
                size = len(line.encode(codec)) + (bom if offset == 0 else 0)
                if size > max_line_bytes:
                    raise IngestionFailure(
                        "RECORD_BYTE_LIMIT",
                        "a physical line exceeds the frozen unit budget",
                    )
                yield line, offset, offset + size
                offset += size
