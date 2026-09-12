from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.composition import BookReplanCoordinator
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize("version,snapshot_id,accepted,should_resume", [
    (11, "snapshot:change", 3, True),
    (13, "snapshot:change", 3, False),
    (11, "snapshot:later", 3, False),
    (17, "snapshot:change", 6, False),
])
def test_plan_change_replay_only_resumes_its_unfinished_binding_checkpoint(monkeypatch, version, snapshot_id, accepted, should_resume):
    book = {"book_run_id": "run:one", "project_id": "project:one", "book_id": "book:one", "state": "PAUSED",
            "version": version, "input_snapshot_id": snapshot_id, "accepted_through_chapter": accepted}
    original = deepcopy(book)
    resumed = []

    def resume(book_run_id, **values):
        assert values["expected_version"] == version
        resumed.append(book_run_id)
        book["state"] = "READY"
        return deepcopy(book)

    proposal = {"project_id": "project:one", "book_id": "book:one", "status": "ACTIVE", "source_type": "HUMAN_FEEDBACK",
                "source_evidence_version_id": "change-request:v1", "proposed_asset_version_id": "future-plan:v2",
                "target_asset_version_id": "future-plan:v1", "target_contract_type": "CHAPTER_GROUP", "activation_operation_id": "activate:one"}
    documents = {
        "change-request:v1": SimpleNamespace(asset_version_id="change-request:v1", content={
            "contract_version": "operator-planning-change-request.v1", "book_id": "book:one",
            "target_plan_version_id": "future-plan:v1", "accepted_through_chapter": 3,
        }),
        "future-plan:v2": SimpleNamespace(asset_version_id="future-plan:v2", content={"chapter_range": [4, 6]}),
    }

    class ReadBinding:
        def __enter__(self):
            return SimpleNamespace(cursor=SimpleNamespace(execute=lambda *_args: None, fetchone=lambda: ("snapshot:change", "SUCCEEDED", 10)))

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("novel_forge.modules.book_replan.coordinator.AuthorityUnitOfWork", lambda _url: ReadBinding())
    monkeypatch.setattr("novel_forge.storage.authority_asset_store.AuthorityAssetQuery", lambda _url: SimpleNamespace(
        require=lambda *, asset_version_id, **_values: documents[asset_version_id],
    ))
    coordinator = object.__new__(BookReplanCoordinator)
    coordinator.database_url = "unused-read-protocol"
    coordinator.book = SimpleNamespace(require=lambda _identity: deepcopy(book), resume=resume)
    coordinator.plan_change = SimpleNamespace(require=lambda _identity: proposal)
    receipt = coordinator.resume_operator_plan_change(book_run_id="run:one", proposal_id="proposal:one", principal=SimpleNamespace(require=lambda *_args: None))
    assert bool(resumed) is should_resume
    assert receipt["replayed"] is True
    assert receipt["snapshot_id"] == "snapshot:change"
    assert receipt["accepted_through_chapter"] == 3
    if not should_resume:
        assert book == original


def test_book_resume_rejects_a_changed_checkpoint_before_reopening_saga():
    authority = object.__new__(PostgresBookAuthority)
    authority.require = lambda _identity: {"project_id": "project:one", "version": 13, "state": "PAUSED"}
    with pytest.raises(KernelError, match="BOOK_MUTATION_CONFLICT"):
        authority.resume("run:one", reason="recover binding", principal=SimpleNamespace(require=lambda *_args: None), expected_version=11)
