from copy import deepcopy

import pytest

from novel_forge.modules.book_followup_authority.prose_review import (
    text_digest,
    validate_window_report,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_longform_prose_editorial import chapter_literal_report_case, literal_report_case


@pytest.mark.parametrize("binding", ["manifest_digest", "window_id", "schema_version"])
def test_report_binding_precedes_missing_quote_diagnosis(binding):
    frozen, window, raw = chapter_literal_report_case()
    raw[binding] = "stale"
    raw["findings"][0]["evidence"][0]["quote"] = "未提供的引文"
    expected = "CONTRACT_DRIFT" if binding == "schema_version" else "REPORT_STALE"
    with pytest.raises(KernelError, match=expected):
        validate_window_report(raw, manifest=frozen, window=window)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_literal_failure_distinguishes_missing_and_ambiguous_without_disclosing_prose(ambiguous):
    frozen, window, raw = chapter_literal_report_case()
    citation = raw["findings"][0]["evidence"][0]
    if ambiguous:
        window["spans"][0]["text"] = citation["quote"] * 2
    else:
        citation["quote"] = "未提供的引文"
    before = deepcopy((frozen, raw))
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_NOT_UNIQUE") as caught:
        validate_window_report(raw, manifest=frozen, window=window)
    details = caught.value.details
    assert details["reason"] == ("QUOTE_AMBIGUOUS" if ambiguous else "QUOTE_NOT_FOUND")
    assert details["exact_occurrences"] == (2 if ambiguous else 0)
    assert details["citation_ordinal"] == 0
    assert details["chapter_number"] == citation["chapter_number"]
    assert details["quote_hash"] == text_digest(citation["quote"])
    assert "quote" not in details and "text" not in details
    assert citation["quote"] not in str(caught.value)
    assert (frozen, raw) == before


@pytest.mark.parametrize("field", ["asset_version_id", "text_hash", "chapter_number"])
def test_literal_host_binding_cannot_replace_the_frozen_manifest_source(field):
    frozen, window, raw = chapter_literal_report_case()
    window["spans"][0][field] = 2 if field == "chapter_number" else "replacement"
    if field == "chapter_number":
        raw["findings"][0]["evidence"][0][field] = 2
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_SOURCE_DRIFT"):
        validate_window_report(raw, manifest=frozen, window=window)


def test_chapter_literal_location_uses_absolute_unicode_codepoints_without_whitespace_repair():
    frozen, window, raw = chapter_literal_report_case()
    span = window["spans"][0]
    span.update(start=7, end=15, text="舟😀停。\r\n她走")
    citation = raw["findings"][0]["evidence"][0]
    citation["quote"] = "😀停。\r\n她"
    resolved = validate_window_report(raw, manifest=frozen, window=window)
    located = resolved["findings"][0]["evidence"][0]
    assert (located["start"], located["end"]) == (8, 14)
    assert validate_window_report(resolved, manifest=frozen, window=window) == resolved
    citation["quote"] = "😀停。她"
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_NOT_UNIQUE") as caught:
        validate_window_report(raw, manifest=frozen, window=window)
    assert caught.value.details["reason"] == "QUOTE_NOT_FOUND"


def test_literal_source_identity_failure_is_distinct_from_absent_text():
    frozen, window, raw = literal_report_case()
    raw["findings"][0]["evidence"][0]["text_hash"] = "a-different-version"
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_NOT_UNIQUE") as caught:
        validate_window_report(raw, manifest=frozen, window=window)
    assert caught.value.details["reason"] == "SOURCE_IDENTITY_NOT_SUPPLIED"


def test_registered_window_cannot_be_replaced_even_with_another_manifest_source():
    frozen, window, raw = chapter_literal_report_case()
    substituted = deepcopy(window)
    substituted["spans"][0]["text"] = "剑锋来自另一个窗口"
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_SOURCE_DRIFT"):
        validate_window_report(raw, manifest=frozen, window=substituted)


def test_handler_rejects_window_source_substitution_before_model_invocation(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest, AuthorityInputAsset
    from novel_forge.modules.book_followup_authority import prose_coordinator, prose_review
    from novel_forge.modules.book_followup_authority.prose_handler import LongformProseReviewHandler

    frozen, window, _ = chapter_literal_report_case()
    registered = deepcopy(frozen)
    registered["windows"][0]["input_asset"] = {"asset_version_id": "window-asset"}
    content = dict(schema_version="longform-prose-window.v2", source_isolation="ACCEPTED_PROSE_ONLY",
                   manifest_digest=frozen["manifest_digest"], book_run_id="b", policy=frozen["policy"], window=deepcopy(window))
    content["window"]["spans"][0]["asset_version_id"] = "replacement"
    source = AuthorityInputAsset("window-asset", "longform_prose_review_window", prose_review.completion_digest(content), content)
    request = AuthorityHandlerRequest("review", "p", "w", "author", "trace", "correlation", "longform.prose_review",
        "1.1.0", {"payload": dict(manifest_digest=frozen["manifest_digest"], book_run_id="b", window_id=window["window_id"])}, (source,))
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchall.return_value = [("review-run", registered)]
    monkeypatch.setattr("novel_forge.storage.authority_uow.AuthorityUnitOfWork", lambda _: uow)
    monkeypatch.setattr(prose_coordinator, "load_review_sources", lambda *_: [])
    monkeypatch.setattr(prose_review, "freeze_manifest", lambda **_: frozen)
    model = SimpleNamespace(external_effect_backed=True, database_url="test-db", invoke=MagicMock())
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_SOURCE_DRIFT"):
        LongformProseReviewHandler(model).execute(request)
    model.invoke.assert_not_called()
