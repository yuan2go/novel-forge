from types import SimpleNamespace

import pytest

from novel_forge.cli.manuscript import _continue_native_work
from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW


def setup_runtime(
    monkeypatch, *, state="READY", chapter=4, outcome="YIELDED_CHECKPOINT"
):
    from novel_forge.api import authority_dependencies as deps
    from novel_forge.modules.book_authority import creation_runtime, manuscript

    book = {
        "project_id": "p",
        "book_id": "b",
        "book_run_id": "same-run",
        "state": state,
        "current_chapter": chapter,
        "accepted_through_chapter": 0,
        "target_chapter_count": 40,
        "author_workflow": dict(AUTHOR_WORKFLOW),
    }
    calls = []
    principal = SimpleNamespace(
        require=lambda permission, project: calls.append(
            ("permission", permission, project)
        )
    )

    def resume(run, **kwargs):
        assert run == "same-run"
        book["state"] = "READY"
        calls.append(("resume", run))

    def pause(run, **kwargs):
        assert run == "same-run"
        book["state"] = "PAUSED"
        calls.append(("pause", run))

    authority = SimpleNamespace(
        require=lambda run: dict(book), resume=resume, pause=pause
    )
    execution = SimpleNamespace(close=lambda: calls.append(("close",)))
    monkeypatch.setattr(
        deps, "build_production_execution_composition", lambda settings: execution
    )
    monkeypatch.setattr(
        deps,
        "build_chapter_authority_application",
        lambda settings, **kwargs: "native-chapter",
    )
    monkeypatch.setattr(
        deps,
        "build_book_production_composition",
        lambda settings, **kwargs: SimpleNamespace(authority=authority),
    )
    monkeypatch.setattr(
        deps,
        "build_trusted_principal_resolver",
        lambda: SimpleNamespace(resolve_worker_principal=lambda name: principal),
    )

    def drive(**kwargs):
        assert kwargs["book_run_id"] == "same-run" and kwargs["maximum_ticks"] == 1
        assert kwargs["chapter"] == "native-chapter"
        calls.append(("drive", kwargs["book_run_id"]))
        if outcome == "YIELDED_CHECKPOINT":
            book["current_chapter"] += 1
        return outcome

    monkeypatch.setattr(creation_runtime, "drive_book", drive)
    monkeypatch.setattr(
        manuscript,
        "require_manuscript",
        lambda *args, **kwargs: {
            "book_run_id": kwargs["book_run_id"],
            "units": [
                {"chapter": i, "text": "retained prose"}
                for i in range(1, book["current_chapter"] + 1)
            ],
            "accepted_through_chapter": 0,
        },
    )
    return book, principal, calls


def test_paused_nonformation_work_continues_same_run_and_stops_round_without_acceptance(
    monkeypatch,
):
    book, principal, calls = setup_runtime(monkeypatch, state="PAUSED")
    result = _continue_native_work(
        SimpleNamespace(database_url="db"),
        SimpleNamespace(stop_after_chapter=5),
        book=dict(book),
        principal=principal,
    )
    assert (
        result["status"] == "MANUSCRIPT_READY"
        and result["next_chapter"] == 6
        and len(result["manuscript"]["units"]) == 5
    )
    assert result["delivery_window"] == 40 and book["accepted_through_chapter"] == 0
    assert ("resume", "same-run") in calls and ("pause", "same-run") in calls
    assert calls.count(("drive", "same-run")) == 1 and ("close",) in calls


def test_already_delivered_round_is_read_only_replay(monkeypatch):
    book, principal, calls = setup_runtime(monkeypatch, state="PAUSED", chapter=5)
    result = _continue_native_work(
        SimpleNamespace(database_url="db"),
        SimpleNamespace(stop_after_chapter=5),
        book=book,
        principal=principal,
    )
    assert result["status"] == "MANUSCRIPT_READY" and result["next_chapter"] == 6
    assert all(c[0] == "permission" for c in calls) and book["state"] == "PAUSED"


@pytest.mark.parametrize("end", [0, 41, True])
def test_round_cannot_expand_existing_window(monkeypatch, end):
    book, principal, calls = setup_runtime(monkeypatch)
    with pytest.raises(ValueError, match="frozen delivery window"):
        _continue_native_work(
            SimpleNamespace(database_url="db"),
            SimpleNamespace(stop_after_chapter=end),
            book=book,
            principal=principal,
        )
    assert all(c[0] == "permission" for c in calls)


@pytest.mark.parametrize(
    "outcome",
    [
        "WAIT_EXTERNAL_RECONCILIATION",
        "WAITING_LEASE_OR_DEPENDENCY",
        "CHAPTER_ATTEMPT_EXHAUSTED",
    ],
)
def test_existing_failure_or_concurrent_owner_retains_readable_work_without_repeating_dispatch(
    monkeypatch, outcome
):
    book, principal, calls = setup_runtime(monkeypatch, outcome=outcome)
    result = _continue_native_work(
        SimpleNamespace(database_url="db"),
        SimpleNamespace(stop_after_chapter=5),
        book=book,
        principal=principal,
    )
    assert result["status"] == outcome and len(result["manuscript"]["units"]) == 4
    assert (
        calls.count(("drive", "same-run")) == 1
        and book["accepted_through_chapter"] == 0
    )


def test_aborted_work_never_acquires_a_new_continuation(monkeypatch):
    book, principal, calls = setup_runtime(monkeypatch, state="ABORTED")
    result = _continue_native_work(
        SimpleNamespace(database_url="db"),
        SimpleNamespace(stop_after_chapter=5),
        book=book,
        principal=principal,
    )
    assert result["status"] == "ABORTED" and all(c[0] == "permission" for c in calls)
