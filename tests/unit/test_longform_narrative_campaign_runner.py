from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_script():
    root = Path(__file__).resolve().parents[2]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_longform_narrative_campaign",
            scripts / "run_longform_narrative_campaign.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


@pytest.mark.parametrize("target", (1, 30, 100, 300))
def test_campaign_accepts_bounded_cumulative_targets(target: int) -> None:
    campaign = _load_script()

    assert campaign._validate_target(target) == target


@pytest.mark.parametrize("target", (0, 31, 299, 301))
def test_campaign_rejects_non_checkpoint_targets(target: int) -> None:
    campaign = _load_script()

    with pytest.raises(ValueError, match="target chapter"):
        campaign._validate_target(target)


@pytest.mark.parametrize(
    ("message", "category"),
    (
        ("codex login credential unavailable", "PROVIDER_FAILURE"),
        ("context manifest omits required fact", "CONTEXT_DEFECT"),
        ("PostgreSQL connection refused", "ENVIRONMENT_BLOCKER"),
        ("chapter prose violates frozen canon", "CONTENT_CORRECTNESS_FAILURE"),
        ("quality corrective action regressed", "CONTENT_QUALITY_FAILURE"),
        ("supervisor state invariant failed", "RUNTIME_DEFECT"),
    ),
)
def test_campaign_failure_classification_is_explicit(
    message: str, category: str
) -> None:
    campaign = _load_script()

    assert campaign._classify_failure(RuntimeError(message)) == category


def test_resume_checkpoint_must_match_contract_release_and_target() -> None:
    campaign = _load_script()
    checkpoint = {
        "contract_identity": "sha256:" + "a" * 64,
        "release": {"commit_sha": "b" * 40},
        "accepted_through_chapter": 30,
    }

    campaign._validate_resume_checkpoint(
        checkpoint,
        contract_identity="sha256:" + "a" * 64,
        commit_sha="b" * 40,
        target_chapter=100,
    )

    with pytest.raises(RuntimeError, match="another Proof Contract"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "c" * 64,
            commit_sha="b" * 40,
            target_chapter=100,
        )
    with pytest.raises(RuntimeError, match="another exact HEAD"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "a" * 64,
            commit_sha="d" * 40,
            target_chapter=100,
        )
    with pytest.raises(RuntimeError, match="behind the durable cursor"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "a" * 64,
            commit_sha="b" * 40,
            target_chapter=1,
        )


def test_frozen_provider_policy_rejects_cli_drift_and_overrides_legacy_planning() -> None:
    campaign = _load_script()
    provider = {
        "provider": "codex-cli",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "quality_context_token_budget": 28_000,
        "silent_fallback": False,
    }

    campaign._validate_frozen_provider_policy(
        provider,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        quality_context_token_budget=28_000,
    )
    env = campaign._apply_frozen_provider_policy(
        {
            "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
            "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "xhigh",
        },
        provider,
    )
    assert env["NOVEL_FORGE_PLANNING_REASONING_EFFORT"] == "high"
    assert env["NOVEL_FORGE_REASONING_EFFORT"] == "high"

    with pytest.raises(RuntimeError, match="model differs"):
        campaign._validate_frozen_provider_policy(
            provider,
            model="another-model",
            reasoning_effort="high",
            quality_context_token_budget=28_000,
        )


def test_process_failure_is_persisted_before_campaign_checkpoint_exists(
    tmp_path: Path,
) -> None:
    campaign = _load_script()

    path = campaign._record_process_failure(
        tmp_path,
        RuntimeError("frozen Provider configuration drift"),
        category="PROOF_HARNESS_DEFECT",
        context={"phase": "INITIALISATION"},
    )

    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert payload["failures"][0]["category"] == "PROOF_HARNESS_DEFECT"
    assert payload["failures"][0]["context"] == {"phase": "INITIALISATION"}


def test_campaign_counts_embedded_narrative_context_manifests(monkeypatch) -> None:
    campaign = _load_script()
    observed_sql: list[str] = []

    def query_rows(_database_url: str, sql: str, _params):
        observed_sql.append(sql)
        if "authority_book_chapter_request" in sql:
            return [{"chapter_number": 1, "accepted": 1}]
        if (
            "asset_type='context_bundle'" in sql
            and "content->'context_manifest'->>'contract_version'" in sql
        ):
            return [{"count": 1}]
        return [{"count": 0}]

    monkeypatch.setattr(campaign, "_query_rows", query_rows)

    measurements = campaign._collect_measurements(
        "postgresql://authority",
        project_id="project-1",
        book_run_id="book-run-1",
    )

    assert measurements["context_manifests"] == 1
    assert measurements["duplicate_logical_chapters"] == 0
    assert any("asset_type='context_bundle'" in sql for sql in observed_sql)
