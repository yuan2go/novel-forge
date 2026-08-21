"""Canonical accepted-evidence input shared by live acceptance and repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from novel_forge.modules.longform_narrative import build_longform_projection_set


CANONICAL_LONGFORM_PROJECTOR_VERSION = "accepted-longform-projector-v2"


@dataclass(frozen=True, slots=True)
class AcceptedLongformEvidence:
    project_id: str
    book_id: str
    book_run_id: str
    chapter_request_id: str
    chapter_number: int
    acceptance_id: str
    acceptance_operation_id: str
    chapter_outcome_asset_version_id: str
    chapter_outcome_content_hash: str
    story_state_asset_version_id: str
    story_state_content_hash: str
    canon_snapshot_asset_version_id: str
    canon_snapshot_content_hash: str
    chapter_plan_asset_version_id: str
    chapter_plan_content_hash: str
    active_arc_plan_version_ids: tuple[str, ...]
    expected_progress_units: Mapping[str, int]
    previous_arc_states: Mapping[str, Mapping[str, Any]]
    chapter_outcome: Mapping[str, Any]
    story_state: Mapping[str, Any]
    source_contract: str = ""
    adaptation_context: Mapping[str, Any] = field(default_factory=dict)


def project_accepted_longform(
    evidence: AcceptedLongformEvidence,
) -> dict[str, Any]:
    """Project only accepted facts; absent legacy observations remain UNKNOWN."""

    outcome = dict(evidence.chapter_outcome)
    adaptations: list[dict[str, Any]] = []
    if "arc_evidence" not in outcome:
        outcome["arc_evidence"] = [
            {
                "arc_plan_version_id": arc_id,
                "observation_status": "UNKNOWN",
                "contribution_kind": "UNKNOWN",
                "progress_units": 0,
                "effect_dimensions": [],
                "milestone_ids": [],
                "actual_consequences": [],
                "obligation_ids": [],
                "resolution_evidence": [],
            }
            for arc_id in evidence.active_arc_plan_version_ids
        ]
        adaptations.append(
            {
                "source_contract": evidence.source_contract or "UNKNOWN",
                "field": "arc_evidence",
                "adaptation": "MISSING_ACCEPTED_EVIDENCE_TO_UNKNOWN",
                "unavailable_fields": [
                    "progress_units",
                    "milestone_ids",
                    "actual_consequences",
                    "resolution_evidence",
                ],
                "forbidden_substitute": "chapter_plan.expected_progress",
                "context": dict(evidence.adaptation_context),
            }
        )
    return build_longform_projection_set(
        project_id=evidence.project_id,
        book_id=evidence.book_id,
        book_run_id=evidence.book_run_id,
        chapter_request_id=evidence.chapter_request_id,
        chapter_number=evidence.chapter_number,
        acceptance_id=evidence.acceptance_id,
        acceptance_operation_id=evidence.acceptance_operation_id,
        chapter_outcome_asset_version_id=(
            evidence.chapter_outcome_asset_version_id
        ),
        story_state_asset_version_id=evidence.story_state_asset_version_id,
        canon_snapshot_asset_version_id=(
            evidence.canon_snapshot_asset_version_id
        ),
        active_arc_plan_version_ids=evidence.active_arc_plan_version_ids,
        expected_progress_units=evidence.expected_progress_units,
        previous_arc_states=evidence.previous_arc_states,
        chapter_outcome=outcome,
        story_state=evidence.story_state,
        projector_version=CANONICAL_LONGFORM_PROJECTOR_VERSION,
        chapter_plan_asset_version_id=evidence.chapter_plan_asset_version_id,
        source_content_hashes={
            "chapter_outcome": evidence.chapter_outcome_content_hash,
            "story_state": evidence.story_state_content_hash,
            "canon_snapshot": evidence.canon_snapshot_content_hash,
            "chapter_plan": evidence.chapter_plan_content_hash,
        },
        contract_adaptation_evidence=adaptations,
    )


__all__ = [
    "AcceptedLongformEvidence",
    "CANONICAL_LONGFORM_PROJECTOR_VERSION",
    "project_accepted_longform",
]
