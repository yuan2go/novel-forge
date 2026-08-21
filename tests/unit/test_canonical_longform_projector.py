from novel_forge.modules.book_authority.longform_projection import (
    AcceptedLongformEvidence,
    frozen_arc_plan_version_ids,
    project_accepted_longform,
)


def _evidence(*, outcome: dict) -> AcceptedLongformEvidence:
    return AcceptedLongformEvidence(
        project_id="project:1",
        book_id="book:1",
        book_run_id="book-run:1",
        chapter_request_id="request:1",
        chapter_number=1,
        acceptance_id="acceptance:1",
        acceptance_operation_id="operation:accept:1",
        chapter_outcome_asset_version_id="outcome:v1",
        chapter_outcome_content_hash="sha256:" + "1" * 64,
        story_state_asset_version_id="state:v1",
        story_state_content_hash="sha256:" + "2" * 64,
        canon_snapshot_asset_version_id="canon:v1",
        canon_snapshot_content_hash="sha256:" + "3" * 64,
        chapter_plan_asset_version_id="plan:v1",
        chapter_plan_content_hash="sha256:" + "4" * 64,
        active_arc_plan_version_ids=("arc:v1",),
        expected_progress_units={"arc:v1": 9},
        previous_arc_states={},
        chapter_outcome=outcome,
        story_state={"current_state": {"narrative_obligation": []}},
        source_contract=str(outcome.get("contract_version") or "legacy-v1"),
    )


def test_live_and_repair_use_one_deterministic_projection() -> None:
    evidence = _evidence(
        outcome={
            "contract_version": "chapter-outcome-v3",
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc:v1",
                    "observation_status": "OBSERVED",
                    "contribution_kind": "PRIMARY",
                    "progress_units": 1,
                    "resolution_evidence": ["scene:1"],
                }
            ],
        }
    )

    live_projection = project_accepted_longform(evidence)
    repair_projection = project_accepted_longform(evidence)

    assert live_projection == repair_projection
    adaptations = live_projection["projection_provenance"].get(
        "contract_adaptation_evidence", []
    )
    assert all("context" not in item for item in adaptations)


def test_legacy_missing_arc_evidence_is_unknown_not_planned_actual() -> None:
    projection = project_accepted_longform(
        _evidence(outcome={"contract_version": "chapter-outcome-v1"})
    )

    progress = projection["arc_progress"][0]
    assert progress["observation_status"] == "UNKNOWN"
    assert progress["progress_units"] == 0
    assert progress["cumulative_progress_units"] == 0
    assert progress["deviation_units"] is None
    adaptation = projection["projection_provenance"][
        "contract_adaptation_evidence"
    ][0]
    assert adaptation["adaptation"] == "MISSING_ACCEPTED_EVIDENCE_TO_UNKNOWN"
    assert adaptation["forbidden_substitute"] == "chapter_plan.expected_progress"
    assert projection["projection_provenance"]["actual_state_policy"] == (
        "ACCEPTED_EVIDENCE_ONLY"
    )


def test_projection_hash_covers_source_hashes_and_adaptation() -> None:
    projection = project_accepted_longform(
        _evidence(outcome={"contract_version": "chapter-outcome-v1"})
    )

    assert projection["projection_hash"].startswith("sha256:")
    assert projection["source_versions"]["chapter_plan_asset_version_id"] == "plan:v1"
    assert projection["projection_provenance"]["source_content_hashes"] == {
        "chapter_outcome": "sha256:" + "1" * 64,
        "story_state": "sha256:" + "2" * 64,
        "canon_snapshot": "sha256:" + "3" * 64,
        "chapter_plan": "sha256:" + "4" * 64,
    }


def test_frozen_chapter_arc_scope_wins_over_current_book_context() -> None:
    assert frozen_arc_plan_version_ids(
        request_payload={
            "context_version_refs": {"arc_plan_versions": ["arc:frozen"]}
        },
        book_context={"arc_plan_versions": ["arc:current"]},
    ) == ("arc:frozen",)
