from unittest.mock import Mock, patch

import pytest

from novel_forge.modules.command_kernel.dispatch_control import process_dispatch_suspended, require_dispatch_enabled
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.workers.dispatch_pause import pause_worker_dispatch


@pytest.mark.parametrize("value,expected", [("", False), ("0", False), ("false", False), ("1", True), ("true", True), ("invalid", True)])
def test_process_brake_is_fail_closed(monkeypatch, value, expected):
    monkeypatch.setenv("NOVEL_FORGE_NO_MODEL_DISPATCH", value)
    assert process_dispatch_suspended() is expected


def test_suspended_process_does_not_query_or_claim_historical_work(monkeypatch):
    monkeypatch.setenv("NOVEL_FORGE_NO_MODEL_DISPATCH", "1")
    cursor, supervisor = Mock(), Mock()
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        require_dispatch_enabled(cursor, "project")
    cursor.execute.assert_not_called()
    with patch("novel_forge.workers.dispatch_pause.time.sleep") as sleep:
        assert pause_worker_dispatch(supervisor, 0.1)
    supervisor.polled.assert_called_once_with(idle=True)
    sleep.assert_called_once_with(0.1)


def test_scoped_pause_blocks_but_unmanaged_preserves_legacy_behavior(monkeypatch):
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    cursor = Mock()
    cursor.fetchone.return_value = ("PAUSED", 1)
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        require_dispatch_enabled(cursor, "paused-project")
    cursor.fetchone.return_value = None
    require_dispatch_enabled(cursor, "other-project")


def test_runtime_coordination_process_pause_allocates_no_job_attempt(monkeypatch):
    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    monkeypatch.setenv("NOVEL_FORGE_NO_MODEL_DISPATCH", "true")
    with patch("novel_forge.modules.runtime_job.application.AuthorityUnitOfWork") as uow:
        assert RuntimeJobAuthority("unused-while-paused").claim(runtime_group="book", worker_id="worker", lease_seconds=10) is None
    uow.assert_not_called()


def test_only_native_pause_exception_with_matching_control_evidence_is_exempt(monkeypatch):
    from novel_forge.modules.command_kernel.dispatch_control import confirmed_dispatch_pause
    monkeypatch.setenv("NOVEL_FORGE_NO_MODEL_DISPATCH", "true")
    cursor = Mock()
    assert confirmed_dispatch_pause(cursor, KernelError("RUNTIME_DISPATCH_PAUSED", "forged"), "project") is None
    with pytest.raises(KernelError) as caught:
        require_dispatch_enabled(cursor, "project")
    assert confirmed_dispatch_pause(cursor, caught.value, "project")["scope"] == "PROCESS"
    assert confirmed_dispatch_pause(cursor, caught.value, "other") is None
    cursor.execute.assert_not_called()


def test_formation_pause_waits_without_recording_business_failure():
    from types import SimpleNamespace
    from novel_forge.modules.command_kernel.dispatch_control import RuntimeDispatchPaused
    from novel_forge.workers.book_authority import execute_story_formation_claim
    claim = SimpleNamespace(job_kind="STORY_FORMATION_ADVANCE", runtime_group="story_formation",
        subject_kind="STORY_FORMATION_RUN", subject_id="formation", attempt_id="attempt",
        input_snapshot={"observed_stage": "THEME_CONTRACT", "observed_version": 4})
    pause = RuntimeDispatchPaused("paused", {"project_id": "project", "scope": "PROJECT", "version": 1})
    formation, jobs = Mock(), Mock()
    formation.require.return_value = {"lifecycle": "RUNNING"}
    formation.advance_expected.side_effect = pause
    with pytest.raises(RuntimeDispatchPaused):
        execute_story_formation_claim(jobs, formation, Mock(), claim)
    formation.record_failure.assert_not_called()
    assert jobs.fail.call_args.kwargs["cause"] is pause
    jobs.complete.assert_not_called()
