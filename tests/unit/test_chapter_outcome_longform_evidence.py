from __future__ import annotations

from novel_forge.modules.chapter_outcome.domain import build_chapter_outcome


def _canon_patch() -> dict[str, object]:
    return {
        "gate": "PASSED",
        "conflicts": [],
        "facts": [
            {
                "fact_id": "fact:1",
                "subject": "character:1",
                "predicate": "location",
                "value": "bridge",
                "status": "ACTIVE",
            }
        ],
    }


def test_chapter_outcome_v3_materializes_explicit_unobserved_arc_entries() -> None:
    outcome = build_chapter_outcome(
        project_id="project:1",
        book_id="book:1",
        chapter_number=2,
        chapter_plan_version_id="chapter-plan:v2",
        parent_group_version_id="chapter-group:v1",
        accepted_draft_version_id="draft:v2",
        final_release_gate_version_id="gate:v2",
        quality_aggregate_version_id="quality:v2",
        canon_patch_asset_version_id="canon-patch:v2",
        canon_patch=_canon_patch(),
        cost_receipt_refs=(),
        created_by_operation_id="operation:outcome:2",
        trace_id="trace:2",
        expected_arc_contributions=(
            {
                "arc_plan_version_id": "arc-plan:v1",
                "contribution_kind": "PRIMARY",
                "expected_progress": "must not leak into actual",
            },
        ),
    )

    assert outcome["contract_version"] == "chapter-outcome-v3"
    assert outcome["arc_evidence"][0]["observation_status"] == "NOT_OBSERVED"
    assert "expected_progress" not in outcome["arc_evidence"][0]
    assert outcome["obligation_events"] == []
    assert outcome["scene_outcomes"] == []


def test_chapter_outcome_uses_qualified_actual_arc_evidence() -> None:
    outcome = build_chapter_outcome(
        project_id="project:1",
        book_id="book:1",
        chapter_number=2,
        chapter_plan_version_id="chapter-plan:v2",
        parent_group_version_id="chapter-group:v1",
        accepted_draft_version_id="draft:v2",
        final_release_gate_version_id="gate:v2",
        quality_aggregate_version_id="quality:v2",
        canon_patch_asset_version_id="canon-patch:v2",
        canon_patch={
            **_canon_patch(),
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc-plan:v1",
                    "observation_status": "OBSERVED",
                    "contribution_kind": "PRIMARY",
                    "progress_units": 1,
                    "effect_dimensions": ["CONFLICT"],
                    "milestone_ids": ["milestone:1"],
                    "actual_consequences": ["the truce ends"],
                    "obligation_ids": [],
                    "resolution_evidence": ["scene:2:1"],
                }
            ],
        },
        cost_receipt_refs=(),
        created_by_operation_id="operation:outcome:2",
        trace_id="trace:2",
        expected_arc_contributions=(
            {"arc_plan_version_id": "arc-plan:v1", "contribution_kind": "PRIMARY"},
        ),
    )

    assert outcome["arc_evidence"][0]["progress_units"] == 1
    assert outcome["arc_evidence"][0]["actual_consequences"] == ["the truce ends"]
