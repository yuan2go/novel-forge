from copy import deepcopy

import pytest

from scripts.creation_checkpoints import reading_checkpoints, reading_review_template, validate_reading_review


def manifest(boundary):
    return {"project_id": "project-fixture", "book_id": "book-fixture", "book_run_id": "run-fixture",
            "accepted_through_chapter": boundary, "manifest_hash": "prefix:" + str(boundary), "book_version": boundary,
            "chapters": [{"chapter_number": number, "candidate_asset_version_id": "candidate:" + str(number),
                          "text_hash": "text:" + str(number), "text": "已接纳正文"} for number in range(1, boundary + 1)]}


def review(boundary, start):
    result = reading_review_template(manifest(boundary), reading_start_chapter=start)
    result.update(status="REVIEWED", reviewer_id="synthetic-editorial-fixture", summary="Fixture coverage only")
    for assessment in result["chapter_assessments"]:
        assessment.update(assessment="Exact fixture passage inspected", locations=[{"start": 0, "end": 2, "text": "已接"}])
    return result


def test_volume_checkpoints_require_entire_intervening_arc_and_previous_accepted_text():
    earlier = [review(3, 1), review(9, 4)]
    current = review(21, 10)
    validate_reading_review(earlier[0], manifest(3))
    validate_reading_review(earlier[1], manifest(9), previous_reviews=earlier[:1])
    validate_reading_review(current, manifest(21), previous_reviews=earlier)
    assert len(current["chapter_assessments"]) == 12
    with pytest.raises(ValueError, match="earlier accepted chapters"):
        validate_reading_review(current, manifest(21), previous_reviews=earlier[1:])
    invalid = deepcopy(current)
    invalid["chapter_assessments"].pop(0)
    with pytest.raises(ValueError, match="omits"):
        validate_reading_review(invalid, manifest(21), previous_reviews=earlier)
    altered = deepcopy(earlier)
    altered[0]["chapter_assessments"][0]["text_hash"] = "different-text"
    with pytest.raises(ValueError, match="earlier accepted chapters"):
        validate_reading_review(current, manifest(21), previous_reviews=altered)
    altered = deepcopy(earlier)
    altered[0]["chapter_assessments"][0]["locations"][0]["text"] = "虚假"
    with pytest.raises(ValueError, match="earlier accepted chapters"):
        validate_reading_review(current, manifest(21), previous_reviews=altered)


def test_nonblocking_open_opinion_survives_and_cannot_mask_a_hard_issue():
    current = review(3, 1)
    issue = {"issue_id": "fixture-style-opinion", "chapter_number": 1, "status": "OPEN", "blocking": False,
             "severity": "minor", "diagnosis": "A local phrase could be tighter", "repair_target": "Optional wording",
             "preservation_requirements": ["Retain character position"], "acceptance_criteria": ["Keep meaning"],
             "location": {"start": 0, "end": 2, "text": "已接"}}
    current["issues"] = [issue]
    validate_reading_review(current, manifest(3))
    following = review(9, 4)
    with pytest.raises(ValueError, match="cannot disappear"):
        validate_reading_review(following, manifest(9), previous_reviews=[current])
    following["issues"] = [deepcopy(issue)]
    validate_reading_review(following, manifest(9), previous_reviews=[current])
    following["issues"][0]["severity"] = "major"
    with pytest.raises(ValueError, match="hard checkpoint"):
        validate_reading_review(following, manifest(9), previous_reviews=[current])


@pytest.mark.parametrize("target,checkpoints", [(30, [3, 9, 21, 30]), (40, [3, 9, 21, 40]), (50, [3, 9, 24, 50])])
def test_frozen_volume_checkpoints_do_not_impose_twelve_chapter_or_third_replan(target, checkpoints):
    assert reading_checkpoints({"pilot_stop_after_chapter": target, "reading_checkpoints": checkpoints},
                               book_target=120) == tuple(checkpoints)
