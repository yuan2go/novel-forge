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


def test_cli_exposes_only_bounded_quality_operations() -> None:
    parser = _module()._parser()
    subparsers = next(
        action
        for action in parser._actions
        if action.__class__.__name__ == "_SubParsersAction"
    )
    assert set(subparsers.choices) == {
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
