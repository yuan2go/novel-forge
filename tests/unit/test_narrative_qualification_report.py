from dataclasses import replace

import pytest
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
)

from novel_forge.modules.chapter_quality_authority.narrative_qualification import (
    NARRATIVE_EVIDENCE_DIMENSIONS,
    NARRATIVE_LAYERS,
    NARRATIVE_QUALIFICATION_REPORT_SCHEMA,
    NarrativeReceipt,
    build_narrative_qualification_report,
)


SHA = "a" * 40
TREE = "sha256:" + "b" * 64


def receipt(
    layer: str, generator: str, *, source_class: str = "REAL_PROVIDER_SEMANTIC"
) -> NarrativeReceipt:
    return NarrativeReceipt(
        receipt_id=f"receipt:{layer}:{generator}",
        source_table="authority_narrative_design_qualification",
        layer=layer,
        generator=generator,
        asset_version_id=f"asset:{generator}",
        content_hash="sha256:" + "c" * 64,
        operation_id=f"operation:{generator}",
        implementation_sha=SHA,
        generation_sha=SHA,
        source_class=source_class,
        status="PASS",
        current=True,
        native_lineage_valid=True,
        profile_current=True,
    )


def report(receipts: tuple[NarrativeReceipt, ...] = ()) -> dict:
    return build_narrative_qualification_report(
        project_id="project:one",
        book_id="book:one",
        implementation_sha=SHA,
        implementation_tree_sha=TREE,
        receipts=receipts,
    )


def intent() -> tuple[NarrativeReceipt, ...]:
    return tuple(
        receipt("INTENT", name)
        for name in (
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "reader.promise.generate",
        )
    )


def test_report_schema_keeps_abstract_descent_and_six_evidence_dimensions() -> None:
    result = report()
    validate_chapter_provider_output_against_schema(
        "narrative_qualification_report", NARRATIVE_QUALIFICATION_REPORT_SCHEMA, result
    )
    assert [item["layer"] for item in result["layers"]] == list(NARRATIVE_LAYERS)
    assert set(result["evidence_dimensions"]) == set(NARRATIVE_EVIDENCE_DIMENSIONS)
    assert (
        result["evidence_dimensions"]["HUMAN_EDITORIAL"]["status"] == "WAITING_EVIDENCE"
    )
    assert result["prose_qualification_allowed"] is False
    assert result["authority_mutation_allowed"] is False
    assert report() == result


def test_unimplemented_trajectory_portfolio_blocks_even_after_valid_upper_receipts() -> (
    None
):
    sources = (
        *intent(),
        receipt("FOUNDATION", "world.design.generate"),
        receipt("FOUNDATION", "character.cast.generate"),
        receipt("BOOK_ARCHITECTURE", "book_plan.generate"),
        receipt("CHAPTER_MISSION", "chapter_plan.generate"),
        receipt("SCENE_ARCHITECTURE", "chapter_plan.generate"),
    )
    result = report(sources)
    assert [row["status"] for row in result["layers"][:3]] == ["PASS"] * 3
    assert result["layers"][3]["status"] == "DESIGN_REVIEW_REQUIRED"
    assert result["layers"][4]["observed_proof_status"] == "PASS"
    assert result["layers"][4]["status"] == "BLOCKED_BY_UPSTREAM"
    assert result["prose_qualification_allowed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"source_class": "SCRIPTED_FIXTURE"},
        {"source_class": "OPERATOR_REVIEW"},
        {"implementation_sha": "d" * 40},
        {"generation_sha": "d" * 40},
        {"current": False},
        {"native_lineage_valid": False},
        {"profile_current": False},
        {"gate_status": "NOT_PROVEN", "gate_reason": "FOUNDATION_SET_INCOMPLETE"},
    ],
)
def test_fixture_stale_or_unbound_evidence_cannot_qualify_current_layer(
    change: dict,
) -> None:
    sources = tuple(replace(item, **change) for item in intent())
    result = report(sources)
    assert result["layers"][0]["status"] != "PASS"
    assert (
        result["evidence_dimensions"]["HUMAN_EDITORIAL"]["status"] == "WAITING_EVIDENCE"
    )
    assert (
        result["evidence_dimensions"]["PRODUCTION_EVIDENCE"]["status"] == "NOT_PROVEN"
    )


def test_more_accepted_chapters_change_sample_size_without_upgrading_qualification() -> (
    None
):
    sources = tuple(
        replace(
            receipt(
                "ACCEPTANCE",
                "book.chapter.accept",
                source_class="ACCEPTED_ACTUAL_CONTRACT",
            ),
            receipt_id=f"acceptance:{number}",
            chapter_number=number,
        )
        for number in range(1, 51)
    )
    result = report(sources)
    assert result["sample"]["sample_size"] == 50
    assert result["sample"]["qualification_stage_determined_by_sample_size"] is False
    assert result["layers"][7]["status"] == "BLOCKED_BY_UPSTREAM"
    assert result["status"] == "NOT_PROVEN"


def test_current_failure_remains_visible_under_upstream_failure() -> None:
    result = report(
        (
            replace(
                receipt("SCENE_ARCHITECTURE", "chapter_plan.generate"), status="FAIL"
            ),
        )
    )
    assert result["status"] == "FAIL"
    assert result["layers"][5]["observed_proof_status"] == "FAIL"


def test_scope_and_duplicate_identity_fail_closed() -> None:
    with pytest.raises(ValueError, match="unique"):
        report((intent()[0], intent()[0]))
    with pytest.raises(ValueError, match="identity"):
        build_narrative_qualification_report(
            project_id="p",
            book_id="b",
            implementation_sha="short",
            implementation_tree_sha=TREE,
            receipts=(),
        )
