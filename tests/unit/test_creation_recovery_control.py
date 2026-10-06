from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority.creation_runtime import drive_book
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.fixture
def drive(monkeypatch):
    from novel_forge.modules.chapter_authority import candidate_repair, derived_recovery

    authority = SimpleNamespace(database_url="unused", require=Mock(return_value={"state": "RUNNING", "project_id": "p"}), cancel=Mock())
    composition = SimpleNamespace(authority=authority, principal=object())
    for name in (
        "recover_quality_frontier", "recover_support_frontier", "recover_information_frontier",
        "recover_review_frontier", "recover_length_frontier", "recover_length_retry_phase",
        "recover_canon_capacity_frontier", "recover_canon_protocol_frontier", "recover_canon_schema_retry_phase",
    ):
        monkeypatch.setattr(candidate_repair, name, Mock(return_value=False))
    monkeypatch.setattr(derived_recovery, "recover_derived_frontier", Mock(return_value=False))
    arguments = dict(composition=composition, chapter=object(), book_run_id="b", worker=Mock(), maximum_ticks=3, deadline=float("inf"))
    return arguments, candidate_repair, derived_recovery


def test_original_cancellation_between_hooks_prevents_next_recovery(drive):
    arguments, candidates, _ = drive
    live = True

    def repair(*_, **__):
        nonlocal live
        live = False
        return True

    candidates.recover_quality_frontier.side_effect = repair
    assert drive_book(**arguments, continuation_live=lambda: live) == "CANCELLED"
    candidates.recover_quality_frontier.assert_called_once()
    candidates.recover_support_frontier.assert_not_called()
    arguments["composition"].authority.cancel.assert_called_once()


def test_derived_recovery_repeated_success_is_finitely_bounded(drive):
    arguments, candidates, derived = drive
    derived.recover_derived_frontier.return_value = True
    assert drive_book(**arguments) == "YIELDED_CHECKPOINT"
    assert derived.recover_derived_frontier.call_count == arguments["maximum_ticks"]
    candidates.recover_quality_frontier.assert_not_called()


def test_deadline_between_hooks_prevents_next_mutation(drive, monkeypatch):
    arguments, candidates, _ = drive
    now = 0
    arguments["deadline"] = 1
    monkeypatch.setattr("novel_forge.modules.book_authority.creation_runtime.monotonic", lambda: now)

    def repair(*_, **__):
        nonlocal now
        now = 1
        return True

    candidates.recover_quality_frontier.side_effect = repair
    assert drive_book(**arguments) == "YIELDED_CHECKPOINT"
    candidates.recover_support_frontier.assert_not_called()


def test_lost_execution_lease_between_hooks_propagates_before_next_mutation(drive):
    arguments, candidates, _ = drive
    lease_live = True

    def repair(*_, **__):
        nonlocal lease_live
        lease_live = False
        return True

    def probe():
        if not lease_live:
            raise KernelError("CREATION_EXECUTION_LEASE_LOST", "lease lost")

    candidates.recover_quality_frontier.side_effect = repair
    with pytest.raises(KernelError, match="lease lost"):
        drive_book(**arguments, execution_probe=probe)
    candidates.recover_support_frontier.assert_not_called()
