from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    NarrativeStateEvent,
    events_from_canon_patch,
    events_from_chapter_outcome,
)


def _events() -> tuple[NarrativeStateEvent, ...]:
    return events_from_canon_patch(
        project_id="project-hundred-chapters",
        book_id="book-river-city",
        source_chapter=30,
        chapter_outcome_id="chapter-outcome:book-river-city:30:plan-v30",
        canon_patch_asset_version_id="canon-patch-v30",
        accepted_draft_asset_version_id="draft-v30",
        source_operation_id="operation-accept-30",
        trace_id="trace-book-river-city",
        canon_patch={
            "facts": [
                {
                    "subject": "character:lin",
                    "predicate": "location",
                    "object": "Beijing",
                    "effective_from_chapter": 30,
                    "confidence": 0.97,
                    "coverage": "EXPLICIT",
                    "extraction_evidence": {"excerpt_digest": "sha256:evidence"},
                }
            ],
            "state_changes": {
                "character_state": [
                    {
                        "character_id": "character:lin",
                        "location": "Beijing",
                        "effective_from_chapter": 30,
                        "confidence": 0.96,
                        "coverage": "EXPLICIT",
                        "extraction_evidence": {"excerpt_digest": "sha256:location"},
                    }
                ]
            },
        },
    )


def test_v2_event_contract_has_one_identity_time_and_lineage_vocabulary() -> None:
    first = _events()[0].to_dict()
    repeated = _events()[0].to_dict()

    assert first == repeated
    assert first["event_id"].startswith("narrative-event:sha256:")
    assert first["scope"] == {
        "project_id": "project-hundred-chapters",
        "book_id": "book-river-city",
    }
    assert first["coordinate"] == {
        "source_chapter": 30,
        "effective_from_chapter": 30,
    }
    assert first["authority"] == {
        "status": "PENDING_BOOK_ACCEPTANCE",
        "required_boundary": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
    }
    assert first["supersession"] == {"supersedes_event_id": ""}
    encoded = repr(first)
    assert "effective_chapter" not in encoded
    assert "supersedes_version_id" not in encoded
    assert "supersedes_asset_version_id" not in encoded


def test_event_id_covers_evidence_and_rejects_tampering() -> None:
    encoded = _events()[0].to_dict()
    encoded["confidence"] = 0.25

    with pytest.raises(KernelError) as error:
        NarrativeStateEvent.from_dict(encoded)
    assert error.value.code == "NARRATIVE_EVENT_INTEGRITY_FAILED"


def test_v2_event_rejects_future_effective_state_and_missing_identity() -> None:
    patch = {
        "state_changes": {
            "character_state": [
                {
                    "location": "Beijing",
                    "effective_from_chapter": 31,
                    "confidence": 0.8,
                    "coverage": "EXPLICIT",
                    "extraction_evidence": {"excerpt_digest": "sha256:x"},
                }
            ]
        }
    }
    with pytest.raises(KernelError) as exc:
        events_from_canon_patch(
            project_id="project-hundred-chapters",
            book_id="book-river-city",
            source_chapter=30,
            chapter_outcome_id="outcome-30",
            canon_patch_asset_version_id="canon-30",
            accepted_draft_asset_version_id="draft-30",
            source_operation_id="operation-30",
            trace_id="trace-30",
            canon_patch=patch,
        )
    assert exc.value.code in {
        "NARRATIVE_IDENTITY_REQUIRED",
        "NARRATIVE_TEMPORAL_BOUNDARY_INVALID",
    }


def test_v1_outcome_is_adapted_only_at_the_read_boundary() -> None:
    events = events_from_chapter_outcome(
        "legacy-outcome-v1",
        {
            "type": "ChapterOutcome",
            "contract_version": "chapter-outcome-v1",
            "chapter_outcome_id": "legacy-outcome",
            "project_id": "project-hundred-chapters",
            "book_id": "book-river-city",
            "chapter_number": 20,
            "accepted_draft_version_id": "draft-v20",
            "created_by_operation_id": "operation-v20",
            "relationship_deltas": [
                {
                    "source_id": "character:lin",
                    "target_id": "character:mei",
                    "status": "HOSTILE",
                    "effective_chapter": 20,
                    "supersedes_asset_version_id": "legacy-relationship-v19",
                }
            ],
        },
        trace_id="trace-v20",
    )

    assert len(events) == 1
    encoded = events[0].to_dict()
    assert encoded["state_kind"] == "relationship_state"
    assert encoded["coordinate"]["effective_from_chapter"] == 20
    assert encoded["supersession"]["supersedes_event_id"] == (
        "legacy-relationship-v19"
    )
    assert "supersedes_asset_version_id" not in repr(encoded)


def test_v2_outcome_rejects_legacy_aliases_in_event_payload() -> None:
    event = _events()[0].to_dict()
    event["mutation"]["payload"]["effective_chapter"] = 30

    with pytest.raises(KernelError) as exc:
        NarrativeStateEvent.from_dict(event)

    assert exc.value.code == "NARRATIVE_V2_ALIAS_FORBIDDEN"
