from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from novel_forge.modules.book_authority.edition_application import BookEditionApplication
from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def verify_edition_dispatch_boundaries(captured, *, principal, selected_run, selected_revision_id, key):
    authority = captured["composition"].authority
    app = BookEditionApplication(authority.database_url, application_build_id=authority.application_build_id, commit_sha=authority.commit_sha)
    book = authority.require(selected_run)
    scope = dict(project_id=book["project_id"], workspace_id=book["workspace_id"], book_run_id=selected_run, principal=principal)
    selected = app.query(**scope, revision_id=selected_revision_id)["revision"]
    original_cursor = book["accepted_through_chapter"]
    assert original_cursor == len(selected["manifest"]["units"])

    def candidate(label):
        fork = app.execute(action="create", **scope, data={"base_revision_id": selected_revision_id,
            "base_manifest_digest": selected["manifest_digest"]}, idempotency_key=f"{key}:{label}:fork")
        units = deepcopy(selected["manifest"]["units"])
        units[-1]["scene_artifacts"][0]["text"] += " 灯影在石面上轻轻一颤。"
        units[-1]["text"] = serialize_realization(units[-1]["scene_artifacts"], units[-1].get("scene_separators"))
        saved = app.execute(action="save", **scope, data={"revision_id": fork["revision_id"], "expected_version": fork["version"],
            "base_manifest_digest": fork["manifest_digest"], "units": units, "reason": "受控版本与派发并发验证的明确作者表达修改", "change_kind": "EXPRESSION"},
            idempotency_key=f"{key}:{label}:save")
        run = app.start_validation(authority=authority, **scope, revision_id=saved["revision_id"])["validation_book_run_id"]
        return saved, run

    class CommandReady(Exception):
        pass

    def prepared_command(run):
        commands = []
        def capture(command, **_kwargs):
            commands.append(command)
            raise CommandReady()
        with patch.object(authority, "submit_chapter", side_effect=capture):
            for _ in range(40):
                try:
                    captured["composition"].supervisor.tick(run)
                except CommandReady:
                    return commands[0]
        raise AssertionError("Native planning did not freeze a validation Chapter for the concurrency check")

    race, race_run = candidate("selection-race")
    command = prepared_command(race_run)
    race_scope = {**scope, "book_run_id": race_run}
    prefix = app.query(**race_scope)["source_manifest"]
    snapshot = app.execute(action="create", **race_scope, data={"base_manifest_digest": prefix["manifest_digest"]}, idempotency_key=f"{key}:prefix-snapshot")
    from novel_forge.modules.book_authority import edition_runtime
    original_binding = edition_runtime.edition_dispatch_binding
    switches = []
    def switch_between_read_and_reservation(*args, **kwargs):
        binding = original_binding(*args, **kwargs)
        head = app.query(**scope)["head"]
        switches.append(app.execute(action="select", **race_scope, data={"revision_id": snapshot["revision_id"],
            "expected_head_version": head["version"], "reason": "在新任务冻结前显式选择已经接纳的未变前缀版本"}, idempotency_key=f"{key}:interleaved-selection"))
        return binding
    with patch.object(edition_runtime, "edition_dispatch_binding", side_effect=switch_between_read_and_reservation):
        with pytest.raises(KernelError, match="EDITION_DISPATCH_SELECTION_CHANGED"):
            authority.submit_chapter(command, principal=principal)
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_request WHERE book_run_id=%s", [race_run])
        assert uow.cursor.fetchone() == (0,)
    head = app.query(**scope)["head"]
    app.execute(action="select", **scope, data={"revision_id": selected_revision_id, "expected_head_version": head["version"],
        "reason": "完成受控交错验证后显式选择原正式稿"}, idempotency_key=f"{key}:select-main")
    app.execute(action="reject", **scope, data={"revision_id": race["revision_id"], "expected_version": race["version"],
        "reason": "保留已验证的并发失败候选与操作历史"}, idempotency_key=f"{key}:reject-race")

    frozen, frozen_run = candidate("reserved-recovery")
    frozen_command = prepared_command(frozen_run)
    with patch.object(type(authority.chapter_port), "submit", side_effect=RuntimeError("native reservation persisted before child admission")):
        with pytest.raises(RuntimeError, match="native reservation persisted"):
            authority.submit_chapter(frozen_command, principal=principal)
    reserved = authority.require_chapter_request(authority.require(frozen_run)["active_chapter_request_id"])
    assert not reserved["chapter_root_operation_id"]
    app.execute(action="reject", **scope, data={"revision_id": frozen["revision_id"], "expected_version": frozen["version"],
        "reason": "不再接受新任务，但已经冻结的请求必须按原合同恢复结算"}, idempotency_key=f"{key}:reject-reserved-candidate")
    from novel_forge.modules.book_authority.chapter_dispatch import reserved_chapter_command
    exact = reserved_chapter_command(authority.database_url, book=authority.require(frozen_run), persisted=reserved,
        actor_id=principal.principal_id, application_build_id=authority.application_build_id, commit_sha=authority.commit_sha)
    adoption = exact.preparation_report["author_draft_adoption"]
    for altered, error in ((replace(exact, title=exact.title + " forged"), "EDITION_RESERVED_ADOPTION_DRIFT"),
                           (replace(exact, idempotency_key=exact.idempotency_key + ":unreserved"), "EDITION_ADOPTION_REJECTED")):
        with pytest.raises(KernelError, match=error):
            edition_runtime.freeze_edition_adoption(authority.database_url, project_id=exact.project_id,
                workspace_id=exact.workspace_id, book_id=exact.book_id, chapter=exact.chapter,
                revision_id=adoption["revision_id"], book_run_id=frozen_run, principal=principal, chapter_request=altered)
    with patch.object(edition_runtime, "edition_dispatch_binding", side_effect=AssertionError("frozen recovery must not use latest edition")):
        restored = authority.recover_chapter_submission(reserved["chapter_request_id"], principal=principal)
    assert restored["chapter_request_id"] == reserved["chapter_request_id"]
    assert restored["command_payload"] == reserved["command_payload"]
    assert restored["stable_idempotency_key"] == reserved["stable_idempotency_key"]
    assert restored["chapter_root_operation_id"]
    assert authority.require(selected_run)["accepted_through_chapter"] == original_cursor
    assert authority.require(frozen_run)["accepted_through_chapter"] == original_cursor - 1
    return {"evidence_class": "SCRIPTED_NATIVE_CONCURRENT_EDITION_BOUNDARIES", "actual_real_model_calls": 0,
        "selection_race": {"candidate": race, "run": race_run, "selection": switches[0], "new_request_count": 0},
        "frozen_recovery": {"candidate": frozen, "run": frozen_run, "chapter_request_id": restored["chapter_request_id"],
            "root_operation_id": restored["chapter_root_operation_id"], "frozen_command": restored["command_payload"]},
        "selected_cursor_unchanged": original_cursor}
