from __future__ import annotations

from novel_forge.modules.book_authority.production import (
    BOOK_PRODUCTION_STATE_SEMANTICS,
    BookProductionState,
    BookProductionStateClass,
    actionable_book_production_states,
    book_production_state_semantics,
)


def test_every_book_state_has_one_total_scheduling_classification() -> None:
    assert set(BOOK_PRODUCTION_STATE_SEMANTICS) == set(BookProductionState)
    assert {
        book_production_state_semantics(state).state_class
        for state in BookProductionState
    } == {
        BookProductionStateClass.ACTIONABLE,
        BookProductionStateClass.DURABLE_WAIT,
        BookProductionStateClass.TERMINAL,
    }


def test_actionable_claim_set_is_derived_from_domain_semantics() -> None:
    expected = {
        state.value
        for state, semantics in BOOK_PRODUCTION_STATE_SEMANTICS.items()
        if semantics.state_class is BookProductionStateClass.ACTIONABLE
    }
    assert set(actionable_book_production_states()) == expected
    assert BookProductionState.CHAPTER_FAILED_RETRYABLE.value in expected
    assert BookProductionState.REPLAN_APPROVAL_PENDING.value not in expected
    assert BookProductionState.PAUSED.value not in expected
    assert BookProductionState.COMPLETED.value not in expected


def test_every_durable_wait_explains_wake_condition() -> None:
    waits = {
        state: semantics
        for state, semantics in BOOK_PRODUCTION_STATE_SEMANTICS.items()
        if semantics.state_class is BookProductionStateClass.DURABLE_WAIT
    }
    assert waits
    assert all(item.blocking_class != "NONE" for item in waits.values())
    assert all(item.blocking_reason for item in waits.values())
    assert all(item.wake_condition not in {"", "NONE"} for item in waits.values())
