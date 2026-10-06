import pytest
from novel_forge.modules.book_authority.member_retry import eligible_retry


@pytest.mark.parametrize('row',[
    ('foreign',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),
    ('actor',3,3,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),
    ('actor',3,1,'REVIEW_EVIDENCE_INVALID','grant'),
    ('actor',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','other-grant'),
])
def test_waiting_cannot_expand_attempts_or_borrow_other_identity_or_host_failures(row):
    assert not eligible_retry(row,'actor','grant')


def test_known_transport_wait_retains_current_operation_bounds_and_authorization():
    assert eligible_retry(('actor',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),'actor','grant')


def test_known_settled_host_repairs_require_their_explicit_successor_contract():
    for code, version in [("CHAPTER_LENGTH_REPAIR_INCOMPLETE", "3.9.26"), ("CANON_QUOTE_LOCALIZATION_INVALID", "3.9.29")]:
        assert not eligible_retry(("actor", 2, 1, code, "grant"), "actor", "grant")
        assert not eligible_retry(("actor", 2, 1, code, "grant", "3.9.24"), "actor", "grant")
        assert eligible_retry(("actor", 2, 1, code, "grant", version), "actor", "grant")
        assert not eligible_retry(("actor", 2, 2, code, "grant", version), "actor", "grant")
