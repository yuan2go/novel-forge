from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import stat

import pytest

from novel_forge.schemas.narrative_qualification import DIMENSIONS, EvidenceDimension
from novel_forge.tools.narrative_qualification import (
    CAPABILITIES,
    _effect_summary,
    _planning_boundaries,
    build_narrative_report,
    write_pack,
)


IDENTITY = {"commit_sha": "a" * 40, "implementation_tree_sha": "sha256:" + "b" * 64}
ENGINEERING = EvidenceDimension("NOT_PROVEN", "NO_P0", (), ("No current P0 supplied.",))


def _snapshot(count: int = 1) -> dict[str, object]:
    accepted = []
    observations = []
    assets = []
    for chapter in range(1, count + 1):
        accepted.append(
            {
                "acceptance_id": f"accepted:{chapter}",
                "chapter_number": chapter,
                "chapter_root_operation_id": f"root:{chapter}",
                "root_status": "SUCCEEDED",
                "source_commit_sha": "a" * 40,
                "projection": {"status": "COMPLETE", "arc_state": []},
            }
        )
        observations.append(
            {
                "project_id": "project:sample",
                "book_id": "book:sample",
                "chapter_number": chapter,
                "acceptance_id": f"accepted:{chapter}",
                "accepted_asset_version_id": f"outcome:{chapter}",
                "acceptance_status": "COMMITTED",
                "accepted_draft_asset_version_id": f"draft:{chapter}",
                "canon_snapshot_asset_version_id": f"canon:{chapter}",
                "story_state_asset_version_id": f"state:{chapter}",
                "quality_gate": "PASSED_WITH_UNCALIBRATED",
                "obligation_states": [],
            }
        )
        assets.append(
            {
                "asset_version_id": f"draft:{chapter}",
                "asset_type": "best_draft_candidate",
                "content_hash": "sha256:" + "c" * 64,
                "content": {
                    "text": f"The traveler made a costly decision. Passage {chapter}."
                },
                "root_operation_id": f"root:{chapter}",
                "operation_status": "SUCCEEDED",
            }
        )
    return {
        "book": {
            "book_run_id": "book-run:sample",
            "project_id": "project:sample",
            "book_id": "book:sample",
            "input_mode": "LEGACY_FIXTURE_INPUT_MODE",
        },
        "design": {},
        "accepted": accepted,
        "observations": observations,
        "assets": assets,
        "effects": [],
        "human_decisions": [],
        "reader_events": [],
    }


def _report(snapshot: dict[str, object]):
    return build_narrative_report(
        snapshot,
        implementation=IDENTITY,
        capabilities=CAPABILITIES,
        engineering=ENGINEERING,
    )


def test_fixture_acceptance_preserves_six_unqualified_dimensions() -> None:
    report, pack, private = _report(_snapshot())
    payload = report.to_dict()

    assert set(payload["dimensions"]) == set(DIMENSIONS)
    assert payload["collection_status"] == "PASS"
    assert payload["source"]["fixture_backed"] is True
    assert payload["real_chapter_production"]["status"] == "NOT_PROVEN"
    assert payload["dimensions"]["human_editorial"]["status"] == "WAITING_EVIDENCE"
    assert (
        payload["dimensions"]["longitudinal_stability"]["status"]
        == "EVIDENCE_NOT_YET_SUFFICIENT"
    )
    assert "total_score" not in payload
    assert len(pack.samples) == len(private["samples"]) == 1


def test_chapter_sample_size_never_upgrades_longitudinal_or_human_evidence() -> None:
    report, _, _ = _report(_snapshot(17))

    assert report.sampling["sample_size"] == 17
    assert (
        report.dimensions["longitudinal_stability"].status
        == "EVIDENCE_NOT_YET_SUFFICIENT"
    )
    assert report.dimensions["human_editorial"].status == "WAITING_EVIDENCE"
    assert len(report.progress_observations) == 17
    assert (
        report.sampling["capability_coverage"]["relationship_trajectory"]["status"]
        == "NOT_OBSERVED"
    )
    assert (
        report.sampling["capability_coverage"]["continuity"]["status"]
        == "SUPPORTING_OBSERVATIONS"
    )


def test_schema_rejects_fixture_promotion_and_combined_dimensions() -> None:
    report, _, _ = _report(_snapshot())
    dimensions = dict(report.dimensions)
    dimensions["human_editorial"] = EvidenceDimension(
        "BOUNDED_HUMAN_EVIDENCE", "HUMAN", ("fake:human",), ("test",)
    )
    with pytest.raises(ValueError, match="fixture evidence"):
        replace(report, dimensions=dimensions)
    with pytest.raises(ValueError, match="six independent"):
        replace(report, dimensions={"total_score": ENGINEERING})
    with pytest.raises(ValueError, match="fixture evidence"):
        replace(report, real_chapter_production={"status": "PASS"})


def test_blind_pack_excludes_identity_and_preserves_private_mapping(
    tmp_path: Path,
) -> None:
    report, pack, private = _report(_snapshot())
    output = tmp_path / "pack"
    write_pack(output, report, pack, private)
    public = json.loads((output / "reviewer/pack.json").read_text())
    hidden = json.loads((output / "private/mapping.json").read_text())

    public_json = json.dumps(public)
    for forbidden in (
        "book-run:sample",
        "draft:1",
        "accepted:1",
        "commit_sha",
        "provider",
        "model",
        "canonical",
    ):
        assert forbidden not in public_json
    assert public["samples"][0]["sample_token"] == hidden["samples"][0]["sample_token"]
    assert hidden["samples"][0]["accepted_draft_asset_version_id"] == "draft:1"
    assert stat.S_IMODE((output / "private/mapping.json").stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_pack(output, report, pack, private)


def test_report_replay_keeps_accepted_snapshot_but_rerun_creates_new_blind_tokens() -> (
    None
):
    first, pack_a, _ = _report(_snapshot())
    second, pack_b, _ = _report(_snapshot())

    assert (
        first.source["accepted_snapshot_hash"]
        == second.source["accepted_snapshot_hash"]
    )
    assert first.progress_observations == second.progress_observations
    assert pack_a.pack_token != pack_b.pack_token


def test_empty_snapshot_has_no_invented_chapter_or_editorial_sample() -> None:
    snapshot = _snapshot(0)
    snapshot["book"] = {}
    report, pack, _ = _report(snapshot)

    assert report.accepted_chapters == ()
    assert pack.samples == ()
    assert report.real_chapter_production["status"] == "NOT_PROVEN"
    assert report.design_evidence["upstream_gate_observed"] is False


def test_human_fixture_and_ai_identity_cannot_supply_editorial_evidence() -> None:
    snapshot = _snapshot()
    snapshot["human_decisions"] = [
        {
            "decision_id": "judge:1",
            "evidence_level": "FIXTURE",
            "blinded": True,
            "pack_id": "pack:1",
            "identity_class": "PROFESSIONAL_EDITOR",
        },
        {
            "decision_id": "judge:2",
            "evidence_level": "HUMAN_VERIFIED",
            "blinded": True,
            "pack_id": "pack:2",
            "identity_class": "AI_JUDGE",
        },
    ]
    report, _, _ = _report(snapshot)

    assert report.dimensions["human_editorial"].status == "WAITING_EVIDENCE"
    assert report.dimensions["human_editorial"].evidence_refs == ()


def test_real_provider_claim_requires_durable_receipt_admission_log_and_cost() -> None:
    effect = {
        "external_effect_id": "effect:1",
        "root_operation_id": "root:1",
        "capability": "model.draft",
        "provider": "openai",
        "model_id": "external-model",
        "provider_capability_profile": {"real_provider_validation_eligible": True},
        "provider_control_level": "V2_CONTROLLED",
        "provider_request_id": "response:1",
        "request_hash": "sha256:" + "d" * 64,
        "status": "SUCCEEDED",
        "dispatches": [{"dispatch_id": "dispatch:1"}],
        "receipts": [],
        "request_payload": {},
    }
    summary = _effect_summary(effect, [])
    assert summary["complete_real_receipt"] is False
    effect["provider"] = "scripted_provider_v2"
    summary = _effect_summary(effect, [])
    assert summary["fixture_backed"] is True
    assert summary["complete_real_receipt"] is False


def test_accepted_cursor_without_observation_does_not_prove_narrative_correctness() -> (
    None
):
    snapshot = _snapshot()
    snapshot["book"]["input_mode"] = "RESOLVED_AUTHORITY_INPUT"
    snapshot["observations"] = []
    report, _, _ = _report(snapshot)

    assert report.dimensions["narrative_correctness"].status == "NOT_PROVEN"
    assert report.real_chapter_production["status"] == "NOT_PROVEN"


def test_planning_source_can_belong_to_another_root_but_execution_binding_must_match() -> (
    None
):
    from novel_forge.modules.chapter_authority.chapter_plan_views import (
        normalize_authoritative_chapter_plan,
    )
    from tests.unit.test_chapter_mission_scene_contract import _plan

    source = _plan()
    source_hash = "sha256:" + "f" * 64
    normalized, _ = normalize_authoritative_chapter_plan(
        project_id="p",
        expected_chapter=2,
        content=source,
        asset_version_id="source-plan:v1",
        content_hash=source_hash,
    )
    contracts = normalized["narrative_contracts"]
    binding = {
        "source_asset_version_id": "source-plan:v1",
        "source_content_hash": source_hash,
        "chapter_mission_digest": contracts["chapter_mission_digest"],
        "scene_architecture_digest": contracts["scene_architecture_digest"],
    }
    assets = [
        {
            "asset_version_id": "source-plan:v1",
            "asset_type": "chapter_plan",
            "content_hash": source_hash,
            "content": source,
            "root_operation_id": "planning:root",
        },
        {
            "asset_version_id": "execution-plan:v1",
            "asset_type": "chapter_plan",
            "content_hash": "sha256:" + "c" * 64,
            "content": normalized,
            "root_operation_id": "chapter:root",
        },
        {
            "asset_version_id": "intent:v1",
            "asset_type": "chapter_execution_intent",
            "content": {"chapter_mission": {"planning_contract_binding": binding}},
            "root_operation_id": "chapter:root",
        },
    ]
    for accepted_plan in ("source-plan:v1", "execution-plan:v1"):
        result = _planning_boundaries(
            {"chapter_plan_asset_version_id": accepted_plan}, assets, "chapter:root"
        )
        assert result["gate"] == "STRUCTURAL_COVERAGE_PASS"
        assert result["source_asset_version_id"] == "source-plan:v1"
    binding["scene_architecture_digest"] = "sha256:" + "0" * 64
    assert (
        _planning_boundaries(
            {"chapter_plan_asset_version_id": "execution-plan:v1"},
            assets,
            "chapter:root",
        )["gate"]
        == "NOT_PROVEN"
    )
