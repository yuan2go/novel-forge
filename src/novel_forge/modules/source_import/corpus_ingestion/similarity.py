from __future__ import annotations

import hashlib
import heapq
import unicodedata
from typing import Any, Iterable


def fingerprint(texts: Iterable[str], *, size: int = 128) -> dict[str, Any]:
    from opencc import OpenCC

    converter = OpenCC("t2s")
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
    a, b = set(left["fingerprint"]["hashes"]), set(right["fingerprint"]["hashes"])
    union = sorted(a | b)[:128]
    score = sum(v in a and v in b for v in union) / len(union) if union else 0.0
    lu, ru = left["assessment"]["units"], right["assessment"]["units"]
    ah, bh = {r["hash"] for r in lu}, {r["hash"] for r in ru}
    at, bt = {r["title"]: r["hash"] for r in lu}, {r["title"]: r["hash"] for r in ru}
    return {
        "policy": "bottom-k-t2s-alnum-5.v1",
        "similarity_estimate": score,
        "exact_text": left["normalized_hash"] == right["normalized_hash"],
        "exact_structure": [(r["title"], r["hash"]) for r in lu]
        == [(r["title"], r["hash"]) for r in ru],
        "exact_unit_hashes": sorted(ah & bh),
        "left_only_hashes": sorted(ah - bh),
        "right_only_hashes": sorted(bh - ah),
        "changed_titles": sorted(t for t in at.keys() & bt.keys() if at[t] != bt[t]),
        "ordered_titles_equal": [r["title"] for r in lu] == [r["title"] for r in ru],
        "equivalence": "CANDIDATE_ONLY",
        "rights_transfer": False,
        "transitive_merge": False,
    }
