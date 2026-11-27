from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.creation_checkpoints import reading_checkpoints, reading_review_template, validate_reading_review
from scripts.creation_reading import accepted_reading_manifest, write_accepted_reading
from tests.unit.test_creation_export import _comparison_exports


@pytest.fixture
def reading_inputs(tmp_path):
    _comparison_exports(tmp_path, chapter_count=12, group_ranges=((1, 3), (4, 6), (7, 9), (10, 12)))
    folder = tmp_path / "treatment"
    groups = json.loads((folder / "chapter-groups.json").read_text())
    workspaces = json.loads((folder / "chapter-workspaces.json").read_text())
    book = {key: groups[key] for key in ("project_id", "book_id", "book_run_id", "accepted_through_chapter")}
    book.update(state="PAUSED", target_chapter_count=180, version=37)
    return book, workspaces, groups


def reviewed(manifest):
    review = reading_review_template(manifest)
    review.update(status="REVIEWED", reviewer_id="fixture-editor", summary="Synthetic editorial fixture only")
    for item in review["chapter_assessments"]:
        text = manifest["chapters"][item["chapter_number"] - 1]["text"]
        item.update(assessment="The quoted choice is present in this exact accepted text.", locations=[{"start": 0, "end": 2, "text": text[:2]}])
    return review


def test_single_book_twelve_reading_has_exact_accepted_prose_and_four_native_groups(reading_inputs, tmp_path):
    book, workspaces, groups = reading_inputs
    rejected = deepcopy(workspaces[0])
    rejected["acceptance"] = {"status": "PENDING"}
    rejected["artifacts"]["history"][0]["content"]["text"] = "Rejected prose must not appear in reading"
    manifest = accepted_reading_manifest(book=book, workspaces=[*workspaces, rejected], lineage=groups, require_closed_groups=True)
    assert [item["chapter_number"] for item in manifest["chapters"]] == list(range(1, 13))
    assert len({item["group_run_id"] for item in manifest["chapters"]}) == 4
    assert all(item["acceptance_status"] == "COMMITTED" and item["han_characters"] > 0 for item in manifest["chapters"])
    target = tmp_path / "single-reading"
    target.mkdir()
    write_accepted_reading(manifest, destination=target, book=book)
    assert len(list((target / "reading").glob("chapter-*.md"))) == 12
    text = (target / "accepted-manuscript.md").read_text()
    assert "第 12 章" in text and "Rejected prose" not in text
    assert all(item["text"] in text for item in manifest["chapters"])
    result = json.loads((target / "accepted-manuscript.json").read_text())
    assert result["book_state"] == "PAUSED" and result["full_book_target"] == 180
    assert result["full_book_completion"] == "NOT_PROVEN"


@pytest.mark.parametrize("fault", ["duplicate_acceptance", "missing_chapter", "wrong_state", "unclosed_group", "foreign_book"])
def test_reading_rejects_incomplete_acceptance_or_group_lineage(reading_inputs, fault):
    book, workspaces, groups = reading_inputs
    if fault == "duplicate_acceptance":
        workspaces.append(deepcopy(workspaces[0]))
    elif fault == "missing_chapter":
        workspaces.pop()
    elif fault == "wrong_state":
        groups["groups"][0]["chapters"][0]["story_state_asset_version_id"] = "wrong-state"
    elif fault == "unclosed_group":
        groups["groups"][0]["state"] = "CLOSURE_PENDING"
    else:
        workspaces[0]["book_id"] = "different-book"
    with pytest.raises(ValueError):
        accepted_reading_manifest(book=book, workspaces=workspaces, lineage=groups, require_closed_groups=True)


def test_six_chapter_review_cannot_omit_text_prior_issues_or_claim_independent_human(reading_inputs):
    book, workspaces, groups = reading_inputs
    manifest = accepted_reading_manifest(book=book, workspaces=workspaces, lineage=groups, through_chapter=6, require_closed_groups=True)
    with pytest.raises(ValueError, match="exact accepted"):
        validate_reading_review(reading_review_template(manifest), manifest)
    review = reviewed(manifest)
    validate_reading_review(review, manifest)
    assert len(review["chapter_assessments"]) == 6
    for mutate in (
        lambda value: value["chapter_assessments"].pop(0),
        lambda value: value.update(reading_manifest_hash="sha256:wrong-text"),
        lambda value: value.update(independent_human_review="PASSED"),
        lambda value: value["chapter_assessments"][0]["locations"][0].update(text="unread invented quote"),
    ):
        invalid = deepcopy(review)
        mutate(invalid)
        with pytest.raises(ValueError):
            validate_reading_review(invalid, manifest)
    issue = {"issue_id": "obligation:1", "chapter_number": 1, "status": "OPEN", "diagnosis": "A payoff is still owed",
             "severity": "major", "repair_target": "Reassess the accepted payoff against this exact passage",
             "location": {"start": 0, "end": 2, "text": manifest["chapters"][0]["text"][:2]},
             "preservation_requirements": ["Retain the cost"], "acceptance_criteria": ["Give evidence of the payoff"]}
    previous = {**review, "issues": [issue]}
    with pytest.raises(ValueError, match="cannot disappear"):
        validate_reading_review(review, manifest, previous_reviews=[previous])
    review["issues"] = [issue]
    with pytest.raises(ValueError, match="Unresolved"):
        validate_reading_review(review, manifest)
    issue.update(status="RESOLVED", resolution_evidence=[{
        "reason": "Fixture reassessment, not independent semantic proof", "chapter_number": 1,
        "candidate_asset_version_id": manifest["chapters"][0]["candidate_asset_version_id"],
        "text_hash": manifest["chapters"][0]["text_hash"], "location": issue["location"],
        "preservation_check": "The quoted cost remains unchanged",
    }])
    validate_reading_review(review, manifest, previous_reviews=[previous])
    for field in ("severity", "repair_target"):
        invalid = deepcopy(review)
        invalid["issues"][0].pop(field)
        with pytest.raises(ValueError):
            validate_reading_review(invalid, manifest)
    invalid = deepcopy(review)
    invalid["issues"][0]["resolution_evidence"] = [{"reason": "Self-report without reading"}]
    with pytest.raises(ValueError, match="resolution"):
        validate_reading_review(invalid, manifest)


def test_frozen_checkpoints_end_at_twelve_and_do_not_change_long_book_goal():
    assert reading_checkpoints({"reading_checkpoints": [3, 6, 9, 12], "pilot_stop_after_chapter": 12}, book_target=180) == (3, 6, 9, 12)
    for checkpoints in ([3, 6], [3, 6, 12, 9], [3, 6, 6, 12], [True, 12], [3, 6, 9, 13]):
        with pytest.raises(ValueError):
            reading_checkpoints({"reading_checkpoints": checkpoints, "pilot_stop_after_chapter": 12}, book_target=180)


def test_six_checkpoint_without_native_review_never_dispatches_seventh(monkeypatch):
    from scripts import creation_pilot, run_world_production_smoke as runner
    from novel_forge.modules.command_kernel.errors import KernelError
    monkeypatch.setattr(runner, "RuntimeJobAuthority", lambda _url: None)
    def review(**values):
        if values["boundary"] == 3:
            return {"decision_version_id": "native-third-checkpoint"}
        raise KernelError("AUTHOR_READING_REVIEW_REQUIRED", "six exact accepted texts remain unreviewed")
    monkeypatch.setattr(creation_pilot, "require_reading_decision", review)
    book = {"project_id": "p", "book_id": "b", "book_run_id": "run", "accepted_through_chapter": 6,
            "state": "PAUSED", "version": 9, "target_chapter_count": 180}
    authority = SimpleNamespace(database_url="not-connected", require=lambda _: dict(book), resume=Mock(), pause=Mock())
    composition = SimpleNamespace(authority=authority, principal="operator")
    chapter = Mock()
    result = runner.drive(composition=composition, chapter=chapter, book_run_id="run", worker="worker",
                          events=lambda _: None, maximum_ticks=1, deadline=0, pilot_stop_after_chapter=12,
                          checkpoints=(3, 6, 9, 12), resume_after_checkpoint=6)
    assert result == "AUTHOR_READING_REVIEW_REQUIRED"
    authority.resume.assert_not_called()
    chapter.scheduler.assert_not_called()


def test_checkpoint_cli_help_does_not_construct_provider(monkeypatch):
    from scripts import creation_checkpoint_review as command
    monkeypatch.setattr(command, "metadata_composition", Mock(side_effect=AssertionError("No runtime on help")))
    with pytest.raises(SystemExit) as result:
        command.main(["--help"])
    assert result.value.code == 0


def test_earlier_checkpoint_discovery_resolves_native_locator_before_current_decision(monkeypatch):
    from scripts import creation_checkpoints as checkpoints
    book = {"project_id": "p", "book_id": "b", "book_run_id": "run", "accepted_through_chapter": 6}
    content = {"contract_version": "book-control-decision.v1", "book_run_id": "run", "book_id": "b",
               "chapter_number": 4, "accepted_through_chapter": 3, "boundary": "NEAR_TERM", "decision": "APPROVE",
               "operator_type": "local_operator", "subject_version_id": "review:3"}
    listed = SimpleNamespace(asset_version_id="decision:3", logical_ref="asset-version:decision:3", content=content)
    current = SimpleNamespace(asset_version_id="decision:3", content_hash="hash:3", logical_ref="book_control/decisions/3.json", content=content)
    query = Mock()
    query.require.return_value = current
    monkeypatch.setattr(checkpoints, "AuthorityAssetQuery", lambda _: query)
    monkeypatch.setattr(checkpoints, "_documents", lambda *args, **kwargs: [listed])
    monkeypatch.setattr(checkpoints, "_review", lambda *args: SimpleNamespace(asset_version_id="review:3", content={
        "reading_manifest_hash": "manifest:3", "evidence_class": "AI_EDITORIAL_REVIEW"}))
    from unittest.mock import MagicMock
    monkeypatch.setattr(checkpoints, "AuthorityUnitOfWork", lambda _: MagicMock())
    repo = Mock()
    repo.current_decision.side_effect = lambda **kwargs: (
        {"asset_version_id": "decision:3", "content_hash": "hash:3"} if kwargs["logical_ref"] == current.logical_ref else None)
    monkeypatch.setattr(checkpoints, "BookControlRepository", lambda _: repo)
    composition = SimpleNamespace(authority=SimpleNamespace(database_url="unused", require=lambda _: book))
    result = checkpoints.require_reading_decision(composition=composition, book_run_id="run", boundary=3)
    assert result["decision_version_id"] == "decision:3"
    query.require.assert_called_once_with(project_id="p", asset_version_id="decision:3")


def test_consumed_reading_approval_cannot_resume_a_new_operator_pause(monkeypatch):
    from scripts import creation_pilot
    book = {"project_id": "p", "book_id": "b", "book_run_id": "run", "accepted_through_chapter": 3,
            "state": "PAUSED", "version": 99, "paused_reason": "operator STOP after approved continuation"}
    authority = SimpleNamespace(require=lambda _: dict(book), resume=Mock(), pause=Mock())
    composition = SimpleNamespace(authority=authority, principal="operator",
                                  query=SimpleNamespace(active_chapter_group_run_id=lambda **_: ""))
    monkeypatch.setattr(creation_pilot, "require_reading_decision", lambda **_: {
        "decision_version_id": "old-approval", "paused_book_version": 17})
    result = creation_pilot.reading_checkpoint_gate(composition=composition, book=book, checkpoints=(3, 6, 9, 12),
                                                   resume_after_checkpoint=3, decision_version_id="old-approval", events=lambda _: None)
    assert result == "AUTHOR_READING_PAUSE_VERSION_CHANGED"
    authority.resume.assert_not_called()
