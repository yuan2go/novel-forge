from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority import edition_planning
from novel_forge.modules.command_kernel.errors import KernelError


def test_frozen_planning_request_can_recover_after_selected_revision_changes(monkeypatch):
    frozen = {"revision_id": "edition:original", "book_run_id": "run", "chapter": 2}
    cursor = Mock()
    cursor.fetchone.return_value = (frozen,)
    monkeypatch.setattr(edition_planning, "AuthorityUnitOfWork", lambda _: nullcontext(SimpleNamespace(cursor=cursor)))
    current = Mock(side_effect=AssertionError("Recovery cannot reinterpret the request through the current selection"))
    monkeypatch.setattr(edition_planning, "edition_plan_scope", current)
    edition_planning.require_edition_planning_request("postgresql://unit", project_id="p", book_id="b", scope=frozen,
        definition_name="planning", idempotency_key="frozen-key")
    with pytest.raises(KernelError, match="EDITION_PLANNING_SOURCE_DRIFT"):
        edition_planning.require_edition_planning_request("postgresql://unit", project_id="p", book_id="b",
            scope={**frozen, "revision_id": "edition:substituted"}, definition_name="planning", idempotency_key="frozen-key")


@pytest.mark.parametrize("revision_id,allowed", [("edition:selected", True), ("edition:original", False)])
def test_new_planning_request_must_bind_selected_revision(monkeypatch, revision_id, allowed):
    selected = {"revision_id": "edition:selected", "book_run_id": "run", "chapter": 3, "generator": "chapter_plan.generate"}
    cursor = Mock()
    cursor.fetchone.side_effect = [None, ({"book_run_id": "run"},)]
    monkeypatch.setattr(edition_planning, "AuthorityUnitOfWork", lambda _: nullcontext(SimpleNamespace(cursor=cursor)))
    monkeypatch.setattr(edition_planning, "edition_plan_scope", Mock(return_value=selected))
    def call():
        return edition_planning.require_edition_planning_request("postgresql://unit", project_id="p", book_id="b",
            scope={**selected, "revision_id": revision_id}, definition_name="planning", idempotency_key="new-key")
    if allowed:
        call()
    else:
        with pytest.raises(KernelError, match="EDITION_PLANNING_CURRENT_REVISION_REQUIRED"):
            call()
