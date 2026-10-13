from types import SimpleNamespace

import pytest

from novel_forge.cli.manuscript import _continue_native_work
from novel_forge.modules.book_authority.manuscript import AUTHOR_WORKFLOW
from novel_forge.modules.command_kernel.errors import KernelError


def setup_runtime(
    monkeypatch, *, state="READY", chapter=4, outcome="YIELDED_CHECKPOINT", runtime_values=None
):
    from novel_forge.api import authority_dependencies as deps
    from novel_forge.modules.book_authority import creation_runtime, manuscript
    from novel_forge.cli import manuscript as manuscript_cli
    monkeypatch.setattr(manuscript_cli, "_manuscript_runtime_values", lambda *args, **kwargs: runtime_values)

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
        deps, "build_production_execution_composition", lambda settings, **kwargs: execution
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
        lambda **kwargs: SimpleNamespace(resolve_worker_principal=lambda name: principal),
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


def test_cancelled_original_formation_does_not_resume_or_dispatch_its_book(monkeypatch):
    from novel_forge.modules.book_authority import creation_runtime
    book, principal, calls = setup_runtime(monkeypatch,state='PAUSED')
    observed = []
    def cancelled(database_url, formation_run_id):
        observed.append((database_url,formation_run_id))
        return {'status':'CANCELLED'}
    monkeypatch.setattr(creation_runtime,'creation_cancellation',cancelled)
    result = _continue_native_work(SimpleNamespace(database_url='db'),SimpleNamespace(stop_after_chapter=5),
        book=book,principal=principal,formation_run_id='original-formation')
    assert result['status']=='SOURCE_CANCELLED' and len(result['manuscript']['units'])==4
    assert observed==[('db','original-formation')]
    assert all(call[0]=='permission' for call in calls) and book['state']=='PAUSED'


def test_original_author_first_cli_uses_same_book_round_and_configured_runtime(monkeypatch,tmp_path):
    from contextlib import nullcontext
    from unittest.mock import Mock
    from novel_forge.api import authority_dependencies as deps
    from novel_forge.cli import manuscript as cli
    from novel_forge.modules.book_authority import production
    from novel_forge.modules.book_followup_authority import application
    from novel_forge.storage import authority_uow
    book,principal,_ = setup_runtime(monkeypatch)
    book['stable_idempotency_key']='original-formation:production'
    monkeypatch.setattr(deps,'authority_release_identity',lambda:('build','a'*40))
    monkeypatch.setattr(deps,'build_trusted_principal_resolver',lambda:SimpleNamespace(resolve_api_principal=lambda:principal))
    monkeypatch.setattr(production,'PostgresBookAuthority',lambda *args,**kw:SimpleNamespace(require=lambda run:book))
    monkeypatch.setattr(application,'BookFollowupAuthorityApplication',lambda *args,**kw:None)
    cursor=Mock()
    cursor.fetchone.return_value=('original-formation',)
    monkeypatch.setattr(authority_uow,'AuthorityUnitOfWork',lambda *args:nullcontext(SimpleNamespace(cursor=cursor)))
    continued=Mock(return_value={'status':'MANUSCRIPT_READY'})
    monkeypatch.setattr(cli,'_continue_native_work',continued)
    settings=SimpleNamespace(database_url='db',root=tmp_path)
    args=SimpleNamespace(action='continue',project_id='p',book_run_id='same-run',stop_after_chapter=5)
    assert cli.run_manuscript_command(settings,args)=={'status':'MANUSCRIPT_READY'}
    continued.assert_called_once_with(settings,args,book=book,principal=principal,formation_run_id='original-formation')
    assert cursor.execute.call_args.args[1]==['p','b','original-formation:production']


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


def test_native_admission_exception_retains_prose_and_does_not_retry(monkeypatch):
    from novel_forge.modules.book_authority import creation_runtime

    book, principal, calls = setup_runtime(monkeypatch)

    def blocked(**kwargs):
        calls.append(("blocked", kwargs["book_run_id"]))
        raise KernelError(
            "PROVIDER_ROUTING_BLOCKED", "frozen context exceeds authorized capacity"
        )

    monkeypatch.setattr(creation_runtime, "drive_book", blocked)
    result = _continue_native_work(
        SimpleNamespace(database_url="db"),
        SimpleNamespace(stop_after_chapter=5),
        book=book,
        principal=principal,
    )
    assert result["status"] == "NATIVE_CONTINUATION_BLOCKED"
    assert result["failure"]["code"] == "PROVIDER_ROUTING_BLOCKED"
    assert len(result["manuscript"]["units"]) == 4
    assert calls.count(("blocked", "same-run")) == 1 and ("close",) in calls
    assert book["accepted_through_chapter"] == 0 and book["state"] == "READY"


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
