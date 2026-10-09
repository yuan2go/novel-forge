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
