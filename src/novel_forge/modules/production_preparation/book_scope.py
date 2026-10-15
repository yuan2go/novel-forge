from __future__ import annotations

from collections.abc import Mapping

from .contracts import ResolvedProductionAsset


def book_scope_issue(asset: ResolvedProductionAsset, book_id: str) -> str:
    content = asset.content
    scopes = set(asset.book_scope_ids)
    nested = []
    for key in ("scope", "creative_input_selection"):
        value = content.get(key)
        if value is not None and not isinstance(value, Mapping):
            return "PREPARATION_BOOK_SCOPE_INVALID"
        nested.append((value or {}).get("book_id"))
    for value in (
        content.get("book_id"),
        *nested,
    ):
        if value is not None and value != "":
            if not isinstance(value, str) or not value.strip():
                return "PREPARATION_BOOK_SCOPE_INVALID"
            scopes.add(value)
    if len(scopes) > 1:
        return "PREPARATION_BOOK_SCOPE_CONFLICT"
    if scopes and scopes != {book_id}:
        return "PREPARATION_CROSS_BOOK_INPUT"
    return ""
