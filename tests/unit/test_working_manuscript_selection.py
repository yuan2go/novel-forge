from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.manuscript import edit_selection_matches_source


@pytest.mark.parametrize("kind,identity,origin,expected", [
    ("chapter_draft", "current", None, True),
    ("chapter_draft", "old", None, False),
    ("author_edit_candidate", "edit", "current", True),
    ("author_edit_candidate", "edit", "old", False),
    ("author_edit_candidate", "edit", None, False),
])
def test_edit_session_selection_requires_the_current_native_source(kind, identity, origin, expected):
    source = SimpleNamespace(asset_version_id="current")
    candidate = SimpleNamespace(asset_version_id=identity, asset_type=kind,
        content={"originating_draft_asset_version_id": origin})
    assert edit_selection_matches_source(candidate, source) is expected


def test_legacy_saved_edit_can_bind_its_exact_base_without_inventing_a_choice():
    source = SimpleNamespace(asset_version_id="current")
    candidate = SimpleNamespace(asset_version_id="edit", asset_type="author_edit_candidate", content={"base_asset_version_id": "current"})
    assert edit_selection_matches_source(candidate, source)


def test_chained_candidate_matches_its_current_base_and_retains_native_origin():
    source = SimpleNamespace(asset_version_id="current-edit")
    candidate = SimpleNamespace(asset_version_id="next-edit", asset_type="author_edit_candidate", content={
        "base_asset_version_id": "current-edit", "originating_draft_asset_version_id": "native-draft"})
    assert edit_selection_matches_source(candidate, source)
    assert candidate.content["originating_draft_asset_version_id"] == "native-draft"


def test_working_selection_cli_requires_explicit_version_and_replay_identity():
    from novel_forge.cli.authority import _authority_parser
    args = _authority_parser().parse_args(["authority-manuscript", "use-working-candidate", "--book-run-id", "run",
        "--chapter", "1", "--candidate-version", "candidate", "--expected-version", "9", "--idempotency-key", "exact", "--reason", "authorized work revision"])
    assert (args.action, args.chapter, args.candidate_version, args.expected_version, args.idempotency_key) == ("use-working-candidate", 1, "candidate", 9, "exact")
