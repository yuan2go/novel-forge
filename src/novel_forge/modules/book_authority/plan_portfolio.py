from collections.abc import Iterable

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
