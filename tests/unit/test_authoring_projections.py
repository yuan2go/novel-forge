from __future__ import annotations

from novel_forge.modules.authoring import (
    build_chapter_transaction_workspace,
    build_hook_debt_projection,
    build_recent_trail_entry,
)


def _boundary(chapter: int = 3) -> dict[str, object]:
    return {
        "chapter_number": chapter,
        "acceptance_id": f"acceptance:{chapter}",
        "acceptance_operation_id": f"operation:accept:{chapter}",
        "chapter_outcome_asset_version_id": f"outcome:v{chapter}",
        "story_state_asset_version_id": f"story:v{chapter}",
        "canon_snapshot_asset_version_id": f"canon:v{chapter}",
        "projection_set_id": f"projection:{chapter}",
    }


def test_recent_trail_uses_only_accepted_typed_evidence() -> None:
    entry = build_recent_trail_entry(
        accepted_boundary=_boundary(),
        chapter_outcome={
            "chapter_number": 3,
            "accepted_draft_asset_version_id": "draft:v3",
            "state_events": [
                {
                    "state_kind": "relationship_state",
                    "identity": {"entity_key": "hero+rival"},
                    "mutation": {"payload": {"movement": "reluctant trust"}},
                },
                {
                    "state_kind": "consequence_state",
                    "identity": {"entity_key": "cost:bridge"},
                    "mutation": {"payload": {"consequence": "the bridge is lost"}},
                },
            ],
            "scene_outcomes": [
                {
                    "scene_id": "scene:3:1",
                    "scene_type": "CHOICE",
                    "turn": "victory creates public cost",
                    "opening_pattern": "IN_MEDIAS_RES",
                    "ending_pattern": "COST_REVEAL",
                    "repetition_key": "public-choice-cost",
                }
            ],
            "reader_state_observations": [
                {"mood": "TENSE", "pacing": "ACCELERATING", "chapter_type": "TURN"}
            ],
            "arc_evidence": [
                {
                    "arc_plan_version_id": "arc:v1",
                    "observation_status": "OBSERVED",
                    "contribution_kind": "PRIMARY",
                    "progress_units": 1,
                    "effect_dimensions": ["RELATIONSHIP", "CONFLICT"],
                    "actual_consequences": ["the truce becomes visible"],
                }
            ],
        },
    )

    assert entry["authority"] == "NONE_PROJECTION_ONLY"
    assert entry["accepted_boundary"]["acceptance_id"] == "acceptance:3"
    assert entry["relationship_movement"] == ["reluctant trust"]
    assert entry["opening_pattern"] == "IN_MEDIAS_RES"
    assert entry["repetition_footprint"] == [
        "TURN",
        "public-choice-cost",
        "CHOICE",
    ]
    assert entry["source_asset_version_ids"] == ["outcome:v3", "draft:v3"]
    assert entry["projection_hash"].startswith("sha256:")


def test_hook_debt_is_ranked_projection_of_accepted_obligations() -> None:
    debt = build_hook_debt_projection(
        accepted_boundary=_boundary(chapter=6),
        obligation_states=(
            {
                "entity_key": "obligation_id=promise:late",
                "source_event_id": "event:promise",
                "state": {
                    "obligation_id": "promise:late",
                    "obligation_type": "PROMISE",
                    "status": "OPEN",
                    "priority": "HIGH",
                    "opened_chapter": 1,
                    "development_history": [{"chapter": 2}],
                    "target_window": {"from_chapter": 3, "to_chapter": 4},
                    "dependencies": ["setup:key"],
                    "linked_arc_ids": ["arc:v1"],
                    "accepted_evaluation": {
                        "lifecycle": "OVERDUE",
                        "dependency_state": "UNRESOLVED",
                    },
                },
            },
            {
                "entity_key": "obligation_id=promise:done",
                "state": {
                    "obligation_id": "promise:done",
                    "obligation_type": "PAYOFF",
                    "status": "FULFILLED",
                    "opened_chapter": 1,
                    "accepted_evaluation": {"lifecycle": "FULFILLED"},
                },
            },
        ),
    )

    assert debt["authority"] == "NONE_PROJECTION_ONLY"
    assert [item["obligation_id"] for item in debt["items"]] == [
        "promise:late",
        "promise:done",
    ]
    assert debt["items"][0]["urgency"] == "CRITICAL"
    assert debt["items"][0]["silence_chapters"] == 4
    assert debt["summary"]["OVERDUE"] == 1
    assert debt["source_asset_version_ids"] == ["story:v6"]


def test_workspace_references_authority_assets_without_activation_permission() -> None:
    def output(
        asset_type: str, version: str, content: dict[str, object]
    ) -> dict[str, object]:
        return {
            "asset_type": asset_type,
            "asset_version_id": version,
            "content_hash": "sha256:" + "1" * 64,
            "output_key": f"chapter.{asset_type}",
            "role": "primary",
            "lifecycle": "ACTIVE",
            "eligibility": "ELIGIBLE",
            "governance": "CLEAR",
            "operation_id": f"operation:{asset_type}",
            "content": content,
        }

    workspace = build_chapter_transaction_workspace(
        chapter_run={
            "root_operation_id": "operation:chapter:3",
            "project_id": "project:1",
            "workspace_id": "workspace:1",
            "status": "SUCCEEDED",
            "trace_id": "trace:3",
            "command": {"chapter": 3},
            "outputs": [
                output(
                    "chapter_plan", "plan:v3", {"chapter_purpose": "force a choice"}
                ),
                output(
                    "chapter_execution_intent",
                    "intent:v3",
                    {
                        "chapter_mission": {
                            "why_this_chapter_exists": "make the truce costly",
                            "required_outcomes": ["public commitment"],
                            "arc_contributions": [{"arc_id": "arc:v1"}],
                        }
                    },
                ),
                output(
                    "context_bundle",
                    "context:v3",
                    {
                        "context_manifest": {
                            "protected_context": [{"asset_version_id": "story:v2"}],
                            "selected_inputs": [{"asset_version_id": "story:v2"}],
                            "rejected_inputs": [],
                        }
                    },
                ),
                output(
                    "candidate_comparison",
                    "comparison:v3",
                    {
                        "selected_asset_version_id": "revision:v3",
                        "stop_reason": "QUALITY_SATISFIED",
                        "net_improvement": 7,
                        "minimum_net_improvement": 3,
                    },
                ),
                output(
                    "quality_score_report",
                    "quality:v3",
                    {"accepted_candidate": True, "decision": "PASSED"},
                ),
            ],
            "operations": [],
            "model_effects": [],
        },
        accepted_evidence={
            "acceptance_id": "acceptance:3",
            "story_state_asset_version_id": "story:v3",
        },
        followup_evidence=(
            {"decision": "CORRECT", "target_plan_version_ids": ["group:v1"]},
        ),
        recent_trail={"entries": [{"repetition_footprint": ["public-choice-cost"]}]},
        hook_debt={
            "items": [
                {"obligation_id": "promise:late", "status": "OVERDUE"},
                {"obligation_id": "promise:done", "status": "FULFILLED"},
            ]
        },
    )

    assert workspace["authority"] == "NONE_READ_MODEL"
    assert (
        workspace["author_brief"]["why_this_chapter_exists"] == "make the truce costly"
    )
    assert workspace["candidate_decision"]["stop_reason"] == "QUALITY_SATISFIED"
    assert (
        workspace["canon_state_change"]["acceptance"]["acceptance_id"] == "acceptance:3"
    )
    assert workspace["stale_future_impact"][0]["decision"] == "CORRECT"
    assert workspace["recent_repetition_risk"] == ["public-choice-cost"]
    assert [item["obligation_id"] for item in workspace["active_hook_debt"]] == [
        "promise:late"
    ]
    assert workspace["activation_permissions"] == []
    assert workspace["immutable_asset_references_only"] is True
