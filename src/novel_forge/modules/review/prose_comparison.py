from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .diagnostics import prose_hash


def prose_comparison(original: Mapping[str, Any], revised: Mapping[str, Any], *, original_id: str, revised_id: str) -> dict[str, Any]:
    before, after = original.get("text"), revised.get("text")
    if not isinstance(before, str) or not isinstance(after, str) or not original_id or not revised_id:
        raise KernelError("REREVIEW_COMPARISON_REQUIRED", "exact original and revised candidate identities and prose are required")
    edits, unchanged = [], []
    for kind, start, end, new_start, new_end in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        span = {"before_start": start, "before_end": end, "after_start": new_start, "after_end": new_end}
        if kind == "equal":
            unchanged.append({**span, "text_hash": prose_hash(before[start:end])})
        else:
            edits.append({**span, "before": before[start:end], "after": after[new_start:new_end]})
    return {
        "contract_version": "exact-prose-comparison.v1",
        "offset_unit": "UNICODE_CODE_POINT",
        "original": {"asset_version_id": original_id, "text_hash": prose_hash(before), "text": before},
        "revised": {"asset_version_id": revised_id, "text_hash": prose_hash(after)},
        "edits": edits,
        "unchanged_ranges": unchanged,
        "declared_targeted_edits": revised.get("targeted_edits", []),
        "coverage": "COMPLETE_BEFORE_AND_AFTER",
        "semantic_preservation": "REQUIRES_REVIEW",
    }
