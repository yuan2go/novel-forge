from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from novel_forge.storage.migrations import LATEST_MIGRATION_ID


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_bounded_quality_qualification.py"


def _module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "run_bounded_quality_qualification",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state() -> dict[str, object]:
    return {
        "schema_version": "novel-forge.bounded-quality-runtime-state.v1",
        "campaign_id": "campaign:quality:v1",
        "project_id": "project:quality",
        "workspace_id": "workspace:quality",
        "book_id": "book:quality",
        "book_run_id": "book-run:quality",
        "primary_arc_plan_version_id": "arc:quality:v1",
        "volume_scope_id": "volume:1:chapters:1-8",
        "exact_release_sha": "a" * 40,
        "migration_head": LATEST_MIGRATION_ID,
        "capability_pack_manifest": {"planning": {}},
        "foundation_lineage": {"book_design_asset_version_id": "design:v5"},
        "planning_lineage": {"input_snapshot_id": "snapshot:v1"},
        "realization_lineage": {"contract": "narrative-realization-v1"},
        "reviewers": [
            {
                "reviewer_id": "reviewer-1",
                "identity_class": "PROFESSIONAL_EDITOR",
            },
            {
                "reviewer_id": "reviewer-2",
                "identity_class": "EXPERIENCED_READER",
            },
        ],
        "runtime_env": {"NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2"},
    }


def _scripted_route_environment() -> dict[str, str]:
    return {
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_MODEL": "scripted-quality-campaign-v1",
        "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "high",
        "NOVEL_FORGE_DRAFT_MODEL": "scripted-quality-campaign-v1",
        "NOVEL_FORGE_REVIEW_MODEL": "scripted-quality-campaign-v1",
        "NOVEL_FORGE_REVISION_MODEL": "scripted-quality-campaign-v1",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": "scripted-quality-campaign-v1",
        "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": "high",
        "NOVEL_FORGE_REASONING_EFFORT": "high",
    }


def test_cli_exposes_only_bounded_quality_operations() -> None:
    parser = _module()._parser()
    subparsers = next(
        action
        for action in parser._actions
        if action.__class__.__name__ == "_SubParsersAction"
    )
    assert set(subparsers.choices) == {
        "prepare",
        "capture-real-state",
        "dry-run",
        "freeze",
        "run-real",
        "export-blind-packs",
        "record-human",
        "evaluate",
        "resume",
    }
    rendered = parser.format_help()
    assert "30" not in rendered
    assert "100" not in rendered
    assert "300" not in rendered


def test_capture_state_requires_two_distinct_typed_reviewer_targets() -> None:
    module = _module()
    assert module._reviewer_targets(
        [
            "editor:one:PROFESSIONAL_EDITOR",
            "reader:two:EXPERIENCED_READER",
        ]
    ) == [
        {
            "reviewer_id": "editor:one",
            "identity_class": "PROFESSIONAL_EDITOR",
        },
        {
            "reviewer_id": "reader:two",
            "identity_class": "EXPERIENCED_READER",
        },
    ]

    with pytest.raises(ValueError, match="exactly two"):
        module._reviewer_targets(["editor:PROFESSIONAL_EDITOR"])
    with pytest.raises(ValueError, match="independent"):
        module._reviewer_targets(
            [
                "same:PROFESSIONAL_EDITOR",
                "same:EXPERIENCED_READER",
            ]
        )
    with pytest.raises(ValueError, match="unsupported"):
        module._reviewer_targets(["editor:MODEL", "reader:EXPERIENCED_READER"])


def test_runtime_state_requires_two_reviewers_and_forbids_persisted_credentials(
    tmp_path: Path,
) -> None:
    module = _module()
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_state()), encoding="utf-8")
    assert module._state(path)["campaign_id"] == "campaign:quality:v1"

    duplicate = _state()
    duplicate["reviewers"] = [duplicate["reviewers"][0]] * 2  # type: ignore[index]
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="two independent"):
        module._state(path)

    secret = _state()
    secret["runtime_env"] = {"NOVEL_FORGE_API_KEY": "must-not-persist"}
    path.write_text(json.dumps(secret), encoding="utf-8")
    with pytest.raises(ValueError, match="must not persist credentials"):
        module._state(path)

    non_hex = _state()
    non_hex["exact_release_sha"] = "z" * 40
    path.write_text(json.dumps(non_hex), encoding="utf-8")
    with pytest.raises(ValueError, match="release or migration"):
        module._state(path)

    malformed_reviewer = _state()
    malformed_reviewer["reviewers"] = ["reviewer-1", "reviewer-2"]
    path.write_text(json.dumps(malformed_reviewer), encoding="utf-8")
    with pytest.raises(ValueError, match="two independent"):
        module._state(path)


def test_result_export_is_atomic_and_datetime_safe(tmp_path: Path) -> None:
    module = _module()
    output = module._write_json(
        tmp_path / "result.json",
        {
            "status": "NOT_PROVEN",
            "created_at": datetime(2026, 8, 26, tzinfo=timezone.utc),
        },
    )
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "created_at": "2026-08-26T00:00:00+00:00",
        "status": "NOT_PROVEN",
    }


def test_runtime_routes_must_match_profile_and_frozen_manifest() -> None:
    module = _module()
    profile = module.load_quality_campaign_profile(
        module.DEFAULT_PROFILE,
        repository_root=ROOT,
    )
    values = _scripted_route_environment()
    frozen = {
        **profile.provider_routes["scripted"],
        "mode": "scripted",
        "campaign_profile_digest": profile.digest,
    }

    module._verify_runtime_routes(
        profile,
        values,
        mode="scripted",
        frozen_route_manifest=frozen,
    )

    drifted_values = {**values, "NOVEL_FORGE_QUALITY_MODEL": "drifted-model"}
    with pytest.raises(RuntimeError, match="quality_structural Provider route"):
        module._verify_runtime_routes(
            profile,
            drifted_values,
            mode="scripted",
            frozen_route_manifest=frozen,
        )

    drifted_frozen = {**frozen, "campaign_profile_digest": "sha256:" + "0" * 64}
    with pytest.raises(RuntimeError, match="profile or Provider mode drifted"):
        module._verify_runtime_routes(
            profile,
            values,
            mode="scripted",
            frozen_route_manifest=drifted_frozen,
        )


def test_runtime_pack_ids_must_match_frozen_bindings() -> None:
    module = _module()
    state = _state()
    bindings = {
        role: {
            "pack_id": pack_id,
            "deployment_id": f"deployment:{role}",
            "hash": "sha256:" + "1" * 64,
        }
        for role, (_environment_key, pack_id) in module._PACK_RUNTIME_BINDINGS.items()
    }
    state["capability_pack_manifest"] = bindings
    values = {
        environment_key: pack_id
        for _role, (
            environment_key,
            pack_id,
        ) in module._PACK_RUNTIME_BINDINGS.items()
    }

    module._verify_runtime_pack_ids(state, values, mode="real")

    values["NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID"] = "drifted-pack"
    with pytest.raises(RuntimeError, match="Pack id drifted for chapter"):
        module._verify_runtime_pack_ids(state, values, mode="real")


def test_runtime_state_cannot_replace_frozen_campaign_lineage() -> None:
    module = _module()
    state = _state()
    campaign = {
        field: state[field]
        for field in (
            "project_id",
            "workspace_id",
            "book_id",
            "exact_release_sha",
            "migration_head",
            "capability_pack_manifest",
            "foundation_lineage",
            "planning_lineage",
            "realization_lineage",
        )
    }
    module._verify_frozen_campaign_binding(campaign, state)

    campaign["planning_lineage"] = {"input_snapshot_id": "snapshot:drifted"}
    with pytest.raises(RuntimeError, match="planning_lineage"):
        module._verify_frozen_campaign_binding(campaign, state)


def test_runtime_environment_applies_profile_caps_and_real_validation_boundary() -> (
    None
):
    module = _module()
    profile = module.load_quality_campaign_profile(
        module.DEFAULT_PROFILE,
        repository_root=ROOT,
    )
    state = _state()
    state["runtime_env"] = _scripted_route_environment()
    values = module._runtime_env(state, mode="scripted", profile=profile)

    assert values["NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL"] == "4.00"
    assert values["NOVEL_FORGE_CHAPTER_PROVIDER_CAP"] == "20.00"
    assert values["NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP"] == "80.00"

    state["runtime_env"] = {
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
        "NOVEL_FORGE_ENVIRONMENT": "development",
    }
    with pytest.raises(RuntimeError, match="controlled validation"):
        module._runtime_env(state, mode="real", profile=profile)
