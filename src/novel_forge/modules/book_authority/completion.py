from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


COMPLETION_CONTRACT = "whole-book-completion-v1"


def completion_content_hash(content: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(dict(content), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def assess_whole_book_completion(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    boundary = dict(snapshot["accepted_boundary"])
    target = int(snapshot["target_chapter_count"])
    if int(boundary["chapter_number"]) != target or target <= 0:
        raise ValueError(
            "whole-book completion requires the exact terminal accepted boundary"
        )
    for key in (
        "acceptance_id",
        "projection_set_id",
        "chapter_outcome_asset_version_id",
        "story_state_asset_version_id",
        "canon_snapshot_asset_version_id",
        "projection_hash",
    ):
        if not boundary.get(key):
            raise ValueError(f"whole-book completion requires {key}")
    arcs = list(snapshot["arc_state"])
    obligations = [dict(item["state"]) for item in snapshot["obligation_state"]]
    unresolved_arcs = [
        str(item["arc_plan_version_id"])
        for item in arcs
        if item.get("lifecycle_status") != "COMPLETED"
        or item.get("observation_status") != "OBSERVED"
    ]
    unresolved_obligations = [
        str(item["obligation_id"])
        for item in obligations
        if item.get("status") != "FULFILLED"
        or not (
            item.get("payoff_evidence")
            or item.get("actual_payoff")
            or item.get("resolution_evidence")
        )
        or item.get("accepted_evaluation", {}).get("dependency_state") != "SATISFIED"
    ]
    blockers = [
        {
            "code": "WHOLE_BOOK_EDITORIAL_EVIDENCE_ABSENT",
            "status": "WAITING_EVIDENCE",
            "reason": "Chapter acceptance and AI Reader Proxy cannot prove whole-book human editorial acceptance.",
        },
        {
            "code": "WHOLE_BOOK_ENDING_APPROVAL_CONTRACT_REQUIRED",
            "status": "DESIGN_REVIEW_REQUIRED",
            "reason": "Frozen ending intent and accepted trajectory closure lack a typed whole-book editorial approval contract; cursor or volume goal status cannot supply it.",
        },
    ]
    if not arcs or unresolved_arcs:
        blockers.append(
            {
                "code": "TRAJECTORY_CLOSURE_NOT_PROVEN",
                "status": "WAITING_EVIDENCE",
                "arc_plan_version_ids": unresolved_arcs,
            }
        )
    if unresolved_obligations:
        blockers.append(
            {
                "code": "OBLIGATION_SETTLEMENT_NOT_PROVEN",
                "status": "WAITING_EVIDENCE",
                "obligation_ids": unresolved_obligations,
            }
        )
    if not snapshot.get("chapter_gate_evidence"):
        blockers.append(
            {
                "code": "ACCEPTED_CHAPTER_GATE_EVIDENCE_ABSENT",
                "status": "WAITING_EVIDENCE",
            }
        )
    return {
        "contract_version": COMPLETION_CONTRACT,
        "owner": "BookAuthority",
        "decision": "BLOCKED",
        "accepted_actual_mutation_allowed": False,
        "cursor_exhausted": True,
        "whole_book_accepted": False,
        "snapshot": dict(snapshot),
        "blockers": blockers,
        "evidence_dimensions": {
            "narrative_correctness": "NOT_PROVEN",
            "human_editorial": "WAITING_EVIDENCE",
            "reader_evidence": "NOT_PROVEN",
            "longitudinal_stability": "NOT_PROVEN",
            "production_evidence": "NOT_PROVEN",
        },
    }
