from __future__ import annotations

from functools import lru_cache
import hashlib
import heapq
import unicodedata
from typing import Any, Iterable


@lru_cache(maxsize=1)
def _converter() -> Any:
    from opencc import OpenCC
    return OpenCC("t2s")


def fingerprint(texts: Iterable[str], *, size: int = 128) -> dict[str, Any]:
    converter = _converter()
    heap: list[int] = []
    retained: set[int] = set()
    for text in texts:
        projection = "".join(
            c
            for c in converter.convert(unicodedata.normalize("NFKC", text))
            if c.isalnum()
        )
        for offset in range(max(0, len(projection) - 4)):
            value = int.from_bytes(
                hashlib.blake2b(
                    projection[offset : offset + 5].encode(), digest_size=8
                ).digest(),
                "big",
            )
            if value in retained:
                continue
            if len(heap) < size:
                heapq.heappush(heap, -value)
                retained.add(value)
            elif value < -heap[0]:
                retained.remove(-heapq.heapreplace(heap, -value))
                retained.add(value)
    hashes = [f"{v:016x}" for v in sorted(retained)]
    return {
        "version": "bottom-k-t2s-alnum-5.v1",
        "hashes": hashes,
        "buckets": ["shingle:" + v for v in hashes[:32]],
        "size": size,
    }


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    from .comparison import compare_versions
    return compare_versions(left, right)
