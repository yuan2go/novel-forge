from __future__ import annotations

from novel_forge.modules.command_kernel.budget_runtime import (
    acquire_budget_locks_in_uow,
)


class _RecordingCursor:
    def __init__(self) -> None:
        self.params: list[str] = []

    def execute(self, _statement: str, params: list[str]) -> None:
        self.params.append(params[0])


class _RecordingUow:
    def __init__(self) -> None:
        self.cursor = _RecordingCursor()


def test_budget_lock_interface_uses_currency_then_scope_in_sorted_order() -> None:
    uow = _RecordingUow()

    acquire_budget_locks_in_uow(
        uow,  # type: ignore[arg-type]
        currencies=("usd", "EUR", "USD"),
        budget_scope_ids=("scope:b", "scope:a", "scope:b"),
    )

    assert uow.cursor.params == [
        "authority-provider-budget:EUR",
        "authority-provider-budget:USD",
        "authority-provider-budget-scope:scope:a",
        "authority-provider-budget-scope:scope:b",
    ]
