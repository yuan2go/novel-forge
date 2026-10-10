from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.book_followup_authority import prose_change_evidence as subject
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.fixture
def evidence(monkeypatch):
    manifest = {"schema_version": "longform-prose-manifest.v3", "sources": [{"asset_version_id": "work-4", "text_hash": "original"}], "windows": [{"window_id": "window-1"}], "policy": {}}
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.repositories.asset_documents.require.return_value = SimpleNamespace(asset_type="longform_prose_review_report", content={"window_id": "window-1"})
    uow.cursor.fetchall.return_value = [("review-operation", "longform.prose_review", "3.0.0", {}, {}, "book-run:original", manifest, "release")]
    uow.repositories.definitions.get_release.return_value = {"registered": True}
    monkeypatch.setattr(subject, "AuthorityUnitOfWork", lambda _: uow)
    monkeypatch.setattr(subject, "frozen_prose_budget_scope", lambda *_args, **_kwargs: None)
    working_loader = MagicMock(return_value=[{"asset_version_id": "work-4", "text_hash": "original"}])
    accepted_loader = MagicMock(side_effect=AssertionError("Unaccepted working prose must not become accepted Canon"))
    monkeypatch.setattr(subject, "load_review_sources", working_loader)
    monkeypatch.setattr(subject, "load_accepted_sources", accepted_loader)
    monkeypatch.setattr(subject, "freeze_manifest", lambda **kwargs: {"sources": kwargs["sources"]})
    validator = MagicMock()
    monkeypatch.setattr(subject, "validate_window_report", validator)
    command = SimpleNamespace(execution_contract_version="1.21.0", project_id="p", workspace_id="w", book_id="b", edition_execution={}, world_preparation_request={})
    return command, manifest, working_loader, validator


def check(command):
    return subject.require_prose_planning_evidence("database", command=command, asset_version_id="report", commit_sha="release")


def test_current_planning_consumes_native_working_review_without_acceptance(evidence):
    command, _, loader, validator = evidence
    check(command)
    assert loader.call_args.args[1:] == ("book-run:original", "p")
    validator.assert_called_once()


def test_changed_working_prose_requires_fresh_review(evidence):
    command, _, loader, _ = evidence
    loader.return_value = [{"asset_version_id": "work-4-new", "text_hash": "changed"}]
    with pytest.raises(KernelError, match="PLANNING_PROSE_EVIDENCE_STALE"):
        check(command)


def test_review_cannot_cross_explicit_run_binding(evidence):
    command, _, _, _ = evidence
    command.edition_execution = {"book_run_id": "book-run:another"}
    with pytest.raises(KernelError, match="PLANNING_PROSE_EDITION_SCOPE_INVALID"):
        check(command)


def test_unbound_accepted_manifest_does_not_gain_working_scope_exception(evidence):
    command, manifest, _, _ = evidence
    manifest["schema_version"] = "longform-prose-manifest.v2"
    with pytest.raises(KernelError, match="PLANNING_PROSE_EDITION_SCOPE_INVALID"):
        check(command)
