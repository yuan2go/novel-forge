from collections.abc import Iterable
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def resolve_portfolio_lineage(
    frozen_versions: tuple[str, ...],
    activated_replacements: Iterable[tuple[str, str]],
) -> dict[str, str]:
    successors: dict[str, set[str]] = {}
    for source, target in activated_replacements:
        successors.setdefault(source, set()).add(target)
    resolved: dict[str, str] = {}
    for original in frozen_versions:
        current = original
        visited: set[str] = set()
        while current in successors:
            if current in visited or len(successors[current]) != 1:
                raise KernelError(
                    "BOOK_INPUT_PORTFOLIO_STALE",
                    "activated Plan replacement lineage is cyclic or ambiguous",
                )
            visited.add(current)
            current = next(iter(successors[current]))
        resolved[original] = current
    if len(set(resolved.values())) != len(frozen_versions):
        raise KernelError(
            "BOOK_INPUT_PORTFOLIO_STALE",
            "Plan portfolio lineage does not preserve distinct portfolio members",
        )
    return resolved


def validate_projected_design_receipt(
    original: dict[str, Any],
    current: dict[str, Any] | None,
    *,
    effective_asset_version_id: str,
    error_code: str,
) -> dict[str, Any]:
    if current is None or current.get("asset_version_id") != effective_asset_version_id:
        raise KernelError(error_code, "effective Plan has no matching current design receipt")
    if effective_asset_version_id == original["asset_version_id"]:
        if current != original:
            raise KernelError(error_code, "unchanged frozen design receipt differs from current evidence")
    else:
        for key in ("project_id", "book_id", "design_layer", "mode", "author_id", "profile_hash"):
            if key in original and current.get(key) != original[key]:
                raise KernelError(error_code, "replacement receipt changes design scope or authorization")
        if "lifecycle" in current and current["lifecycle"] != "ACTIVE":
            raise KernelError(error_code, "replacement design receipt is not active")
    return current
